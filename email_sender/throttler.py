"""
Domain-Level Outreach Throttler and History Tracker.
Prevents contacting the same company/domain multiple times within a cooldown window,
protecting sender reputation and avoiding spam complaints.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_FILE = Path("data") / "outreach_history.json"


class DomainThrottler:
    """Manages cooldown intervals per company domain."""

    def __init__(self, history_file: Optional[Path] = None, default_cooldown_days: int = 14):
        self.history_file = history_file or DEFAULT_HISTORY_FILE
        self.default_cooldown_days = default_cooldown_days
        self._history: Dict[str, Dict] = {}
        self._load_history()

    def _load_history(self) -> None:
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
            else:
                self._history = {}
        except Exception as exc:
            logger.warning("Could not load outreach history from %s: %s", self.history_file, exc)
            self._history = {}

    def _save_history(self) -> None:
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self._history, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Could not save outreach history to %s: %s", self.history_file, exc)

    @staticmethod
    def extract_domain(email: str) -> str:
        norm = str(email or "").strip().lower()
        if "@" in norm:
            return norm.split("@", 1)[1]
        return norm

    def can_send(self, email: str, cooldown_days: Optional[int] = None) -> Tuple[bool, str]:
        """
        Check if an email can be sent to this recipient/domain.
        Returns (allowed, reason).
        """
        domain = self.extract_domain(email)
        if not domain:
            return False, "Invalid email address or domain"

        cooldown = self.default_cooldown_days if cooldown_days is None else cooldown_days
        entry = self._history.get(domain)
        if not entry:
            return True, "Domain not previously contacted"

        last_sent_str = entry.get("last_sent")
        if not last_sent_str:
            return True, "No prior timestamp recorded"

        try:
            last_sent_dt = datetime.fromisoformat(last_sent_str)
            elapsed = datetime.now() - last_sent_dt
            if elapsed < timedelta(days=cooldown):
                remaining_days = cooldown - elapsed.days
                return False, f"Domain {domain} is in cooldown (contacted {elapsed.days} days ago, {remaining_days} days remaining)"
        except Exception as exc:
            logger.debug("Error parsing date %s: %s", last_sent_str, exc)

        return True, "Cooldown expired"

    def record_send(self, email: str, subject: str = "", metadata: Optional[Dict] = None) -> None:
        """Record successful outreach to this domain and email."""
        domain = self.extract_domain(email)
        if not domain:
            return

        now_iso = datetime.now().isoformat()
        entry = self._history.get(domain, {
            "domain": domain,
            "send_count": 0,
            "recipients": [],
            "history": [],
        })

        entry["send_count"] = entry.get("send_count", 0) + 1
        entry["last_sent"] = now_iso
        entry["last_email"] = email

        recipients = entry.get("recipients", [])
        if email not in recipients:
            recipients.append(email)
        entry["recipients"] = recipients

        history_list = entry.get("history", [])
        history_list.append({
            "timestamp": now_iso,
            "email": email,
            "subject": subject,
            "metadata": metadata or {},
        })
        entry["history"] = history_list[-20:]  # Keep latest 20 sends per domain

        self._history[domain] = entry
        self._save_history()

    def get_domain_status(self, domain: str) -> Optional[Dict]:
        """Get past history for a domain."""
        return self._history.get(domain.lower().strip())
