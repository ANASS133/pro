"""
JobScout Conductor Store.
Persistent, thread-safe SQLite-backed store for autonomous orchestration:
- Conductor configuration and emergency-stop state
- Per-client automation toggles (auto-search, auto-cover-letter, auto-apply, auto-notify, is_paused, digest_frequency)
- Task orchestration queue and history
- Client job matches and staged applications
- Email inbox reply monitoring logs
- Deduplicated outbound WhatsApp/notification tracking
- System and agent activity event logs
"""

import hashlib
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "conductor.db"


class ConductorStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def close(self):
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.connection = None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            with conn:
                # 1. Global Conductor Settings
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conductor_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                # 2. Per-Client Automation Configuration
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS client_automation_configs (
                        client_id TEXT PRIMARY KEY,
                        is_paused INTEGER DEFAULT 0,
                        auto_search INTEGER DEFAULT 1,
                        auto_cover_letter INTEGER DEFAULT 1,
                        auto_apply INTEGER DEFAULT 0,
                        auto_notify_whatsapp INTEGER DEFAULT 1,
                        digest_frequency TEXT DEFAULT 'daily',
                        max_daily_applications INTEGER DEFAULT 5,
                        last_search_at TEXT DEFAULT '',
                        last_notification_at TEXT DEFAULT '',
                        updated_at TEXT NOT NULL
                    );
                """)
                # Safe column migrations for existing tables
                existing_cols = {
                    r["name"] for r in conn.execute("PRAGMA table_info(client_automation_configs);").fetchall()
                }
                if "is_paused" not in existing_cols:
                    conn.execute("ALTER TABLE client_automation_configs ADD COLUMN is_paused INTEGER DEFAULT 0;")
                if "digest_frequency" not in existing_cols:
                    conn.execute("ALTER TABLE client_automation_configs ADD COLUMN digest_frequency TEXT DEFAULT 'daily';")

                # 3. Conductor Tasks Queue & History
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conductor_tasks (
                        id TEXT PRIMARY KEY,
                        task_type TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        result_summary TEXT DEFAULT '',
                        error_message TEXT DEFAULT '',
                        retry_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        started_at TEXT DEFAULT '',
                        completed_at TEXT DEFAULT ''
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON conductor_tasks(status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_client ON conductor_tasks(client_id);")

                # 4. Client Matches & Staged Applications
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS client_matches (
                        id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL,
                        job_title TEXT NOT NULL,
                        company TEXT NOT NULL,
                        location TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        link TEXT DEFAULT '',
                        source TEXT DEFAULT '',
                        score REAL DEFAULT 0.0,
                        status TEXT NOT NULL DEFAULT 'discovered',
                        cover_letter_path TEXT DEFAULT '',
                        discovered_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_client ON client_matches(client_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_status ON client_matches(status);")

                # 5. Email Inbox Reply Logs
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS email_inbox_logs (
                        id TEXT PRIMARY KEY,
                        message_id TEXT UNIQUE NOT NULL,
                        sender TEXT NOT NULL,
                        recipient TEXT DEFAULT '',
                        subject TEXT NOT NULL,
                        received_at TEXT NOT NULL,
                        intent TEXT NOT NULL DEFAULT 'other',
                        confidence REAL DEFAULT 0.0,
                        matched_client_id TEXT DEFAULT '',
                        matched_company TEXT DEFAULT '',
                        summary TEXT DEFAULT '',
                        suggested_reply TEXT DEFAULT '',
                        action_taken TEXT DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_client ON email_inbox_logs(matched_client_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_intent ON email_inbox_logs(intent);")

                # 6. Sent Notifications Deduplication Log
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sent_notifications (
                        id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL,
                        channel TEXT NOT NULL DEFAULT 'whatsapp',
                        notification_type TEXT NOT NULL,
                        dedupe_key TEXT UNIQUE NOT NULL,
                        content_preview TEXT DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_client ON sent_notifications(client_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_dedupe ON sent_notifications(dedupe_key);")

                # 7. Operational Event Log
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conductor_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        level TEXT NOT NULL,
                        module TEXT NOT NULL,
                        client_id TEXT DEFAULT '',
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_created ON conductor_logs(created_at DESC);")

            # Default global settings
            defaults = {
                "emergency_stop": "false",
                "auto_daily_search": "true",
                "auto_email_monitoring": "true",
                "auto_whatsapp_updates": "true",
                "daily_search_interval_hours": "24",
                "email_monitor_interval_minutes": "15",
                "max_consecutive_errors": "5",
                "max_task_retries": "3",
            }
            with conn:
                for k, v in defaults.items():
                    conn.execute("""
                        INSERT INTO conductor_settings (key, value, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO NOTHING;
                    """, (k, v, self._now()))

    # --- Settings ---

    def get_setting(self, key: str, default: str = "") -> str:
        conn = self._get_connection()
        row = conn.execute("SELECT value FROM conductor_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: Any):
        now = self._now()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO conductor_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
                """, (key, str(value), now))

    def get_all_settings(self) -> Dict[str, str]:
        conn = self._get_connection()
        rows = conn.execute("SELECT key, value FROM conductor_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def is_emergency_stopped(self) -> bool:
        return self.get_setting("emergency_stop", "false").lower() in ("true", "1", "yes")

    def set_emergency_stop(self, stopped: bool):
        self.set_setting("emergency_stop", "true" if stopped else "false")
        self.log_event(
            "WARN" if stopped else "INFO",
            "conductor",
            message=f"Global Emergency Stop {'ACTIVATED! All autonomous agent tasks paused.' if stopped else 'Deactivated. Automation resumed.'}"
        )

    # --- Client Automation Config ---

    def get_client_config(self, client_id: str) -> Dict[str, Any]:
        cid = str(client_id).strip()
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM client_automation_configs WHERE client_id = ?", (cid,)).fetchone()
        if row:
            res = dict(row)
            res.setdefault("is_paused", 0)
            res.setdefault("digest_frequency", "daily")
            return res

        default_cfg = {
            "client_id": cid,
            "is_paused": 0,
            "auto_search": 1,
            "auto_cover_letter": 1,
            "auto_apply": 0,
            "auto_notify_whatsapp": 1,
            "digest_frequency": "daily",
            "max_daily_applications": 5,
            "last_search_at": "",
            "last_notification_at": "",
            "updated_at": self._now()
        }
        with self._lock:
            with conn:
                conn.execute("""
                    INSERT INTO client_automation_configs 
                    (client_id, is_paused, auto_search, auto_cover_letter, auto_apply, auto_notify_whatsapp, digest_frequency, max_daily_applications, last_search_at, last_notification_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_id) DO NOTHING;
                """, (cid, 0, 1, 1, 0, 1, "daily", 5, "", "", default_cfg["updated_at"]))
        return default_cfg

    def update_client_config(self, client_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        cid = str(client_id).strip()
        current = self.get_client_config(cid)
        now = self._now()
        updated = {**current, **updates, "updated_at": now}

        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO client_automation_configs 
                    (client_id, is_paused, auto_search, auto_cover_letter, auto_apply, auto_notify_whatsapp, digest_frequency, max_daily_applications, last_search_at, last_notification_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_id) DO UPDATE SET
                        is_paused = excluded.is_paused,
                        auto_search = excluded.auto_search,
                        auto_cover_letter = excluded.auto_cover_letter,
                        auto_apply = excluded.auto_apply,
                        auto_notify_whatsapp = excluded.auto_notify_whatsapp,
                        digest_frequency = excluded.digest_frequency,
                        max_daily_applications = excluded.max_daily_applications,
                        last_search_at = excluded.last_search_at,
                        last_notification_at = excluded.last_notification_at,
                        updated_at = excluded.updated_at;
                """, (
                    cid,
                    int(bool(updated.get("is_paused", 0))),
                    int(bool(updated.get("auto_search", 1))),
                    int(bool(updated.get("auto_cover_letter", 1))),
                    int(bool(updated.get("auto_apply", 0))),
                    int(bool(updated.get("auto_notify_whatsapp", 1))),
                    str(updated.get("digest_frequency", "daily")),
                    int(updated.get("max_daily_applications", 5)),
                    str(updated.get("last_search_at", "")),
                    str(updated.get("last_notification_at", "")),
                    now
                ))
        return self.get_client_config(cid)

    def list_client_configs(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        rows = conn.execute("SELECT * FROM client_automation_configs ORDER BY client_id ASC").fetchall()
        return [dict(r) for r in rows]

    # --- Tasks Queue & History ---

    def create_task(self, task_type: str, client_id: str = "all") -> Dict[str, Any]:
        tid = f"task_{int(datetime.now().timestamp() * 1000)}_{hashlib.md5(f'{task_type}_{client_id}_{self._now()}'.encode()).hexdigest()[:6]}"
        now = self._now()
        task = {
            "id": tid,
            "task_type": task_type,
            "client_id": client_id,
            "status": "pending",
            "result_summary": "",
            "error_message": "",
            "retry_count": 0,
            "created_at": now,
            "started_at": "",
            "completed_at": ""
        }
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO conductor_tasks (id, task_type, client_id, status, result_summary, error_message, retry_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (tid, task_type, client_id, "pending", "", "", 0, now))
        return task

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM conductor_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: str, updates: Dict[str, Any]):
        fields = []
        vals = []
        for k in ["status", "result_summary", "error_message", "retry_count", "started_at", "completed_at"]:
            if k in updates:
                fields.append(f"{k} = ?")
                vals.append(updates[k])
        if not fields:
            return
        vals.append(task_id)
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(f"UPDATE conductor_tasks SET {', '.join(fields)} WHERE id = ?", vals)

    def list_tasks(self, limit: int = 50, client_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        query = "SELECT * FROM conductor_tasks WHERE 1=1"
        params: List[Any] = []
        if client_id:
            query += " AND client_id = ?"
            params.append(client_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # --- Client Matches & Staged Applications ---

    def save_match(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        mid = match_data.get("id")
        cid = match_data.get("client_id", "default")
        title = match_data.get("job_title", "")
        company = match_data.get("company", "")
        if not mid:
            mid = f"match_{hashlib.sha256(f'{cid}_{title.lower().strip()}_{company.lower().strip()}'.encode()).hexdigest()[:12]}"

        now = self._now()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO client_matches (
                        id, client_id, job_title, company, location, email, link, source, score, status, cover_letter_path, discovered_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        score = excluded.score,
                        status = excluded.status,
                        cover_letter_path = CASE WHEN excluded.cover_letter_path != '' THEN excluded.cover_letter_path ELSE client_matches.cover_letter_path END,
                        updated_at = excluded.updated_at;
                """, (
                    mid,
                    cid,
                    title,
                    company,
                    match_data.get("location", ""),
                    match_data.get("email", ""),
                    match_data.get("link", ""),
                    match_data.get("source", ""),
                    float(match_data.get("score", 0.0)),
                    match_data.get("status", "discovered"),
                    match_data.get("cover_letter_path", ""),
                    match_data.get("discovered_at", now),
                    now
                ))
        return self.get_match(mid) or match_data

    def get_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM client_matches WHERE id = ?", (match_id,)).fetchone()
        return dict(row) if row else None

    def list_matches(self, client_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        query = "SELECT * FROM client_matches WHERE 1=1"
        params = []
        if client_id:
            query += " AND client_id = ?"
            params.append(client_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def update_match_status(self, match_id: str, new_status: str, cover_letter_path: str = "") -> bool:
        now = self._now()
        with self._lock:
            conn = self._get_connection()
            with conn:
                if cover_letter_path:
                    conn.execute(
                        "UPDATE client_matches SET status = ?, cover_letter_path = ?, updated_at = ? WHERE id = ?",
                        (new_status, cover_letter_path, now, match_id)
                    )
                else:
                    conn.execute(
                        "UPDATE client_matches SET status = ?, updated_at = ? WHERE id = ?",
                        (new_status, now, match_id)
                    )
        return True

    def count_matches_by_status(self, client_id: Optional[str] = None) -> Dict[str, int]:
        conn = self._get_connection()
        if client_id:
            rows = conn.execute(
                "SELECT status, count(*) as c FROM client_matches WHERE client_id = ? GROUP BY status",
                (client_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT status, count(*) as c FROM client_matches GROUP BY status").fetchall()
        res = {"discovered": 0, "staged_for_approval": 0, "cover_letter_generated": 0, "applied": 0, "interview": 0, "rejected": 0}
        for r in rows:
            res[r["status"]] = r["c"]
        return res

    # --- Email Inbox Monitoring Logs ---

    def log_inbox_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = message_data.get("message_id")
        if not msg_id:
            msg_id = f"inbox_{hashlib.md5(f'{message_data.get('sender')}_{message_data.get('subject')}_{message_data.get('received_at')}'.encode()).hexdigest()[:12]}"

        lid = f"log_{msg_id}"
        now = self._now()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO email_inbox_logs (
                        id, message_id, sender, recipient, subject, received_at, intent, confidence, matched_client_id, matched_company, summary, suggested_reply, action_taken, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        intent = excluded.intent,
                        confidence = excluded.confidence,
                        matched_client_id = excluded.matched_client_id,
                        matched_company = excluded.matched_company,
                        summary = excluded.summary,
                        suggested_reply = excluded.suggested_reply,
                        action_taken = excluded.action_taken;
                """, (
                    lid,
                    msg_id,
                    message_data.get("sender", ""),
                    message_data.get("recipient", ""),
                    message_data.get("subject", ""),
                    message_data.get("received_at", now),
                    message_data.get("intent", "other"),
                    float(message_data.get("confidence", 0.0)),
                    message_data.get("matched_client_id", ""),
                    message_data.get("matched_company", ""),
                    message_data.get("summary", ""),
                    message_data.get("suggested_reply", ""),
                    message_data.get("action_taken", ""),
                    now
                ))
        return {**message_data, "id": lid, "message_id": msg_id}

    def list_inbox_logs(self, limit: int = 50, intent: Optional[str] = None, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        query = "SELECT * FROM email_inbox_logs WHERE 1=1"
        params = []
        if intent:
            query += " AND intent = ?"
            params.append(intent)
        if client_id:
            query += " AND matched_client_id = ?"
            params.append(client_id)
        query += " ORDER BY received_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # --- Notification Deduplication ---

    def has_notification_been_sent(self, dedupe_key: str) -> bool:
        if not dedupe_key:
            return False
        conn = self._get_connection()
        row = conn.execute("SELECT 1 FROM sent_notifications WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
        return row is not None

    def record_notification(
        self,
        client_id: str,
        notification_type: str,
        dedupe_key: str,
        channel: str = "whatsapp",
        content_preview: str = ""
    ) -> Dict[str, Any]:
        nid = f"notif_{hashlib.md5(dedupe_key.encode()).hexdigest()[:12]}"
        now = self._now()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    INSERT INTO sent_notifications (id, client_id, channel, notification_type, dedupe_key, content_preview, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dedupe_key) DO NOTHING;
                """, (nid, client_id, channel, notification_type, dedupe_key, content_preview[:200], now))
        return {"id": nid, "client_id": client_id, "notification_type": notification_type, "dedupe_key": dedupe_key, "created_at": now}

    def list_notifications(self, client_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        if client_id:
            rows = conn.execute(
                "SELECT * FROM sent_notifications WHERE client_id = ? ORDER BY created_at DESC LIMIT ?",
                (client_id, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sent_notifications ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # --- Operational Event Logs ---

    def log_event(self, level: str, module: str, message: str, client_id: str = ""):
        now = self._now()
        try:
            with self._lock:
                conn = self._get_connection()
                with conn:
                    conn.execute("""
                        INSERT INTO conductor_logs (level, module, client_id, message, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (level.upper(), module, client_id, message, now))
        except Exception as exc:
            logger.error("Failed to write to conductor_logs: %s", exc)

    def list_logs(self, limit: int = 100, module: Optional[str] = None, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        query = "SELECT * FROM conductor_logs WHERE 1=1"
        params = []
        if module:
            query += " AND module = ?"
            params.append(module)
        if client_id:
            query += " AND client_id = ?"
            params.append(client_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


conductor_store = ConductorStore()
