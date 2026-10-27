"""
Candidate Onboarding Status Tracker for JobScout.
Maintains persistent, thread-safe mapping between Supabase application UUIDs
and JobScout client dossiers across server restarts and browser refreshes.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)

ONBOARDING_RECORDS_FILE = DATA_DIR / "onboarding_records.json"


class OnboardingStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    READY_FOR_IMPORT = "READY_FOR_IMPORT"
    IMPORTING = "IMPORTING"
    PROFILE_REVIEW_REQUIRED = "PROFILE_REVIEW_REQUIRED"
    READY = "READY"
    IMPORT_FAILED = "IMPORT_FAILED"


class OnboardingTracker:
    """Thread-safe manager for persistent onboarding records."""

    def __init__(self, storage_file: Path = ONBOARDING_RECORDS_FILE):
        self.storage_file = Path(storage_file)
        self.lock = threading.Lock()
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_file.exists():
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _read_records_unlocked(self) -> Dict[str, Dict[str, Any]]:
        if not self.storage_file.exists():
            return {}
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error("Failed reading onboarding records from %s: %s", self.storage_file, exc)
            return {}

    def _write_records_unlocked(self, records: Dict[str, Dict[str, Any]]) -> None:
        try:
            # Atomic file replacement
            temp_file = self.storage_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            temp_file.replace(self.storage_file)
        except Exception as exc:
            logger.error("Failed writing onboarding records to %s: %s", self.storage_file, exc)

    def get_record(self, application_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves onboarding record for a specific Supabase application ID."""
        clean_id = str(application_id or "").strip()
        with self.lock:
            records = self._read_records_unlocked()
            return records.get(clean_id)

    def get_all_records(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves all tracked onboarding records."""
        with self.lock:
            return self._read_records_unlocked()

    def find_by_client_id(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Finds onboarding record by JobScout candidate slug."""
        clean_id = str(client_id or "").strip().lower()
        with self.lock:
            records = self._read_records_unlocked()
            for rec in records.values():
                if str(rec.get("client_id") or "").strip().lower() == clean_id:
                    return rec
        return None

    def set_status(
        self,
        application_id: str,
        status: str,
        client_id: Optional[str] = None,
        client_name: Optional[str] = None,
        payment_verified: bool = False,
        document_count: int = 0,
        cv_document: Optional[str] = None,
        cv_parsed: bool = False,
        missing_fields: Optional[List[str]] = None,
        package: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
        profile_ready: bool = False,
    ) -> Dict[str, Any]:
        """Creates or updates an onboarding record atomically."""
        clean_id = str(application_id or "").strip()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.lock:
            records = self._read_records_unlocked()
            existing = records.get(clean_id, {})

            record = {
                "application_id": clean_id,
                "client_id": client_id or existing.get("client_id"),
                "client_name": client_name or existing.get("client_name", ""),
                "status": status,
                "payment_verified": payment_verified or existing.get("payment_verified", False),
                "imported_at": existing.get("imported_at") or (now_iso if status in {OnboardingStatus.READY, OnboardingStatus.PROFILE_REVIEW_REQUIRED} else None),
                "updated_at": now_iso,
                "document_count": document_count or existing.get("document_count", 0),
                "cv_document": cv_document or existing.get("cv_document"),
                "cv_parsed": cv_parsed or existing.get("cv_parsed", False),
                "missing_fields": missing_fields if missing_fields is not None else existing.get("missing_fields", []),
                "package": package or existing.get("package", {}),
                "last_error": last_error,
                "profile_ready": profile_ready or (status == OnboardingStatus.READY),
            }

            records[clean_id] = record
            self._write_records_unlocked(records)
            return record


# Global tracker singleton
onboarding_tracker = OnboardingTracker()
