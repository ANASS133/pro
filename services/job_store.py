import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from config import DATA_DIR

DB_PATH = DATA_DIR / "jobs.db"
_local = threading.local()


class JobStore:
    """Thread-safe persistent job store backed by SQLite."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection for this store."""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            self._local.connection = conn
        return conn

    def close(self):
        """Close thread-local SQLite connection."""
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            conn.close()
            self._local.connection = None

    def _init_db(self):
        """Create jobs table and indexes if they do not exist."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS background_jobs (
                        job_id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        phase TEXT DEFAULT 'pending',
                        is_running INTEGER DEFAULT 0,
                        paused INTEGER DEFAULT 0,
                        progress INTEGER DEFAULT 0,
                        total INTEGER DEFAULT 0,
                        last_error TEXT DEFAULT '',
                        payload TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON background_jobs(job_type);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_running ON background_jobs(is_running);")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def save_job(
        self,
        job_id: str,
        job_type: str,
        phase: str = "pending",
        is_running: bool = True,
        paused: bool = False,
        progress: int = 0,
        total: int = 0,
        last_error: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Save a new job or overwrite an existing job."""
        now = self._now()
        payload_str = json.dumps(payload or {})
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO background_jobs (
                        job_id, job_type, phase, is_running, paused,
                        progress, total, last_error, payload, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        job_type=excluded.job_type,
                        phase=excluded.phase,
                        is_running=excluded.is_running,
                        paused=excluded.paused,
                        progress=excluded.progress,
                        total=excluded.total,
                        last_error=excluded.last_error,
                        payload=excluded.payload,
                        updated_at=excluded.updated_at;
                    """,
                    (
                        job_id,
                        job_type,
                        phase,
                        1 if is_running else 0,
                        1 if paused else 0,
                        progress,
                        total,
                        last_error,
                        payload_str,
                        now,
                        now,
                    ),
                )
        return self.get_job(job_id)

    def update_job(self, job_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update specific fields of an existing job."""
        if not kwargs:
            return self.get_job(job_id)

        valid_fields = {
            "phase",
            "is_running",
            "paused",
            "progress",
            "total",
            "last_error",
            "payload",
        }
        updates = []
        params = []
        for key, val in kwargs.items():
            if key in valid_fields:
                updates.append(f"{key} = ?")
                if key in ("is_running", "paused"):
                    params.append(1 if val else 0)
                elif key == "payload":
                    params.append(json.dumps(val or {}))
                else:
                    params.append(val)

        if not updates:
            return self.get_job(job_id)

        now = self._now()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(job_id)

        query = f"UPDATE background_jobs SET {', '.join(updates)} WHERE job_id = ?"
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(query, params)

        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a job by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM background_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def list_jobs(self, job_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent jobs with optional filtering by type."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if job_type:
                cursor.execute(
                    "SELECT * FROM background_jobs WHERE job_type = ? ORDER BY created_at DESC LIMIT ?",
                    (job_type, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM background_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def delete_job(self, job_id: str) -> bool:
        """Delete a job by ID."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute("DELETE FROM background_jobs WHERE job_id = ?", (job_id,))
                return cursor.rowcount > 0

    def reset_stale_jobs(self) -> int:
        """Mark any jobs left running across restarts as 'interrupted'."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE background_jobs
                    SET is_running = 0, phase = 'interrupted', last_error = 'Interrupted by server restart'
                    WHERE is_running = 1;
                    """
                )
                return cursor.rowcount

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["is_running"] = bool(data.get("is_running"))
        data["paused"] = bool(data.get("paused"))
        try:
            data["payload"] = json.loads(data.get("payload") or "{}")
        except (ValueError, TypeError):
            data["payload"] = {}
        return data


# Global singleton instance
job_store = JobStore()
