"""
Persistent SQLite-backed Campaign Store with on-disk attachment management.
Replaces the monolithic 5.2MB email_campaigns.json file, eliminating thread lock bottlenecks,
memory bloat, and base64 embedding.
"""

import base64
import hashlib
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "campaigns.db"
ASSETS_DIR = DATA_DIR / "campaign_assets"
LEGACY_JSON_PATH = BASE_DIR / "email_campaigns.json"


class CampaignStore:
    def __init__(self, db_path: Path = DB_PATH, assets_dir: Path = ASSETS_DIR):
        self.db_path = Path(db_path)
        self.assets_dir = Path(assets_dir)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.assets_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS campaigns (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        full_name TEXT DEFAULT '',
                        mode TEXT DEFAULT 'standard',
                        rows_json TEXT DEFAULT '[]',
                        anschreiben_json TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS campaign_attachments (
                        id TEXT PRIMARY KEY,
                        campaign_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        file_hash TEXT NOT NULL,
                        file_size INTEGER DEFAULT 0,
                        mimetype TEXT DEFAULT 'application/octet-stream',
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_attach_campaign ON campaign_attachments(campaign_id);")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def store_attachment_bytes(self, campaign_id: str, filename: str, content: bytes, mimetype: str = "application/pdf") -> Dict[str, Any]:
        """Store binary payload into content-addressable disk file and save metadata in SQLite."""
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        file_hash = hashlib.sha256(content).hexdigest()[:16]
        safe_fname = "".join(c for c in filename if c.isalnum() or c in "._- ")
        disk_filename = f"{file_hash}_{safe_fname}"
        file_path = self.assets_dir / disk_filename

        if not file_path.exists():
            file_path.write_bytes(content)

        attachment_id = f"att_{file_hash}_{campaign_id[:8]}"
        now = self._now()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO campaign_attachments (id, campaign_id, filename, file_path, file_hash, file_size, mimetype, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET filename=excluded.filename, file_path=excluded.file_path;
                """, (attachment_id, campaign_id, filename, str(file_path), file_hash, len(content), mimetype, now))

        return {
            "id": attachment_id,
            "filename": filename,
            "file_path": str(file_path),
            "file_hash": file_hash,
            "file_size": len(content),
            "mimetype": mimetype
        }

    def save_campaign(self, campaign_data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update campaign record and persist attachments to disk."""
        cid = str(campaign_data.get("id") or "").strip()
        if not cid:
            raise ValueError("Campaign ID is required")

        name = str(campaign_data.get("name") or cid).strip()
        full_name = str(campaign_data.get("full_name") or name).strip()
        mode = str(campaign_data.get("mode") or "standard").strip()
        rows = campaign_data.get("rows") or []
        anschreiben = campaign_data.get("anschreiben") or {}
        now = self._now()

        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO campaigns (id, name, full_name, mode, rows_json, anschreiben_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        full_name=excluded.full_name,
                        mode=excluded.mode,
                        rows_json=excluded.rows_json,
                        anschreiben_json=excluded.anschreiben_json,
                        updated_at=excluded.updated_at;
                """, (
                    cid,
                    name,
                    full_name,
                    mode,
                    json.dumps(rows, ensure_ascii=False),
                    json.dumps(anschreiben, ensure_ascii=False),
                    now,
                    now
                ))

        # Handle attachments
        raw_attachments = campaign_data.get("attachments") or []
        for att in raw_attachments:
            if isinstance(att, dict):
                fname = att.get("filename", "")
                b64 = att.get("content_b64", "")
                mtype = att.get("mimetype", "application/pdf")
                fpath = att.get("file_path", "")

                if b64:
                    try:
                        raw_bytes = base64.b64decode(b64)
                        self.store_attachment_bytes(cid, fname, raw_bytes, mtype)
                    except Exception as e:
                        logger.error(f"Failed to decode base64 attachment {fname}: {e}")
                elif fpath and Path(fpath).exists():
                    try:
                        raw_bytes = Path(fpath).read_bytes()
                        self.store_attachment_bytes(cid, fname, raw_bytes, mtype)
                    except Exception as e:
                        logger.error(f"Failed to read file attachment {fname}: {e}")

        return self.get_campaign(cid) or {}

    def get_campaign(self, campaign_id: str, include_b64: bool = False) -> Optional[Dict[str, Any]]:
        """Retrieve a campaign by ID. If include_b64=True, loads attachment files into base64 for legacy clients."""
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if not row:
            return None

        cid = row["id"]
        attach_rows = conn.execute("SELECT * FROM campaign_attachments WHERE campaign_id = ?", (cid,)).fetchall()
        attachments = []
        for a in attach_rows:
            att_dict = {
                "id": a["id"],
                "filename": a["filename"],
                "file_path": a["file_path"],
                "file_hash": a["file_hash"],
                "file_size": a["file_size"],
                "mimetype": a["mimetype"]
            }
            if include_b64 and a["file_path"] and Path(a["file_path"]).exists():
                try:
                    att_dict["content_b64"] = base64.b64encode(Path(a["file_path"]).read_bytes()).decode("ascii")
                except Exception:
                    pass
            attachments.append(att_dict)

        return {
            "id": cid,
            "name": row["name"],
            "full_name": row["full_name"],
            "mode": row["mode"],
            "rows": json.loads(row["rows_json"] or "[]"),
            "anschreiben": json.loads(row["anschreiben_json"] or "{}"),
            "attachments": attachments,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

    def list_campaigns(self) -> List[Dict[str, Any]]:
        """List all campaigns summary."""
        conn = self._get_connection()
        rows = conn.execute("SELECT * FROM campaigns ORDER BY updated_at DESC").fetchall()
        result = []
        for r in rows:
            camp = self.get_campaign(r["id"], include_b64=False)
            if camp:
                result.append(camp)
        return result

    def delete_campaign(self, campaign_id: str) -> bool:
        """Delete campaign and associated attachments."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
        return True

    def count(self) -> int:
        conn = self._get_connection()
        row = conn.execute("SELECT COUNT(*) as c FROM campaigns").fetchone()
        return row["c"] if row else 0

    def migrate_legacy_json(self, json_path: Path = LEGACY_JSON_PATH) -> int:
        """Migrate legacy email_campaigns.json into SQLite and disk assets."""
        path = Path(json_path)
        if not path.exists():
            return 0

        # Don't re-migrate if already populated
        if self.count() > 0:
            return 0

        try:
            logger.info(f"Starting migration of legacy {path} to SQLite CampaignStore...")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            campaigns = data.get("campaigns", [])
            migrated_count = 0
            for camp in campaigns:
                self.save_campaign(camp)
                migrated_count += 1
            logger.info(f"Successfully migrated {migrated_count} campaigns from {path} to SQLite.")
            return migrated_count
        except Exception as e:
            logger.error(f"Migration from legacy JSON failed: {e}")
            return 0


# Global singleton instance
campaign_store = CampaignStore()
try:
    campaign_store.migrate_legacy_json()
except Exception as _mig_err:
    logger.warning(f"Campaign migration warning: {_mig_err}")
