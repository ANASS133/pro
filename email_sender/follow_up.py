"""
Polite Follow-Up Automation (Nachfass-Manager).
Identifies past outreach candidates eligible for a gentle German follow-up
(5–14 business days after initial contact) and drafts courteous follow-up correspondence.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_FILE = Path("data") / "outreach_history.json"


class FollowUpManager:
    """Detects pending applications and drafts polite German follow-up letters."""

    def __init__(self, history_file: Optional[Path] = None):
        self.history_file = history_file or DEFAULT_HISTORY_FILE

    def _load_history(self) -> Dict[str, Dict]:
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as exc:
            logger.warning("Could not load history for follow-up: %s", exc)
        return {}

    def find_eligible_follow_ups(
        self, min_days: int = 5, max_days: int = 21
    ) -> List[Dict]:
        """
        Identify companies contacted between min_days and max_days ago
        who have not received a follow-up yet.
        """
        history = self._load_history()
        eligible = []
        now = datetime.now()

        for domain, data in history.items():
            last_sent_str = data.get("last_sent")
            if not last_sent_str:
                continue

            try:
                last_sent_dt = datetime.fromisoformat(last_sent_str)
                elapsed = now - last_sent_dt
                elapsed_days = elapsed.days

                # Check window
                if min_days <= elapsed_days <= max_days:
                    # Check if already followed up
                    history_list = data.get("history", [])
                    has_follow_up = any("nachfass" in str(h.get("subject", "")).lower() or "rückfrage" in str(h.get("subject", "")).lower() for h in history_list)

                    if not has_follow_up:
                        latest_entry = history_list[-1] if history_list else {}
                        eligible.append({
                            "domain": domain,
                            "email": data.get("last_email") or (latest_entry.get("email", "")),
                            "last_sent": last_sent_str,
                            "days_ago": elapsed_days,
                            "initial_subject": latest_entry.get("subject", ""),
                            "metadata": latest_entry.get("metadata", {}),
                        })
            except Exception as exc:
                logger.debug("Error parsing history date for domain %s: %s", domain, exc)

        return sorted(eligible, key=lambda x: x["days_ago"], reverse=True)

    @classmethod
    def generate_follow_up(
        cls,
        candidate_entry: Dict,
        sender_name: str = "",
        job_title: str = "",
        salutation: str = "Sehr geehrte Damen und Herren,",
    ) -> Dict[str, str]:
        """
        Drafts a courteous, professional German follow-up letter.
        """
        email = candidate_entry.get("email", "")
        days_ago = candidate_entry.get("days_ago", 7)
        initial_subject = candidate_entry.get("initial_subject", "")

        # Formulate subject line
        if job_title:
            subject = f"Rückfrage zu meiner Bewerbung als {job_title}"
        elif initial_subject:
            subject = f"Rückfrage: {initial_subject}"
        else:
            subject = "Kurze Rückfrage zu meinen Bewerbungsunterlagen"

        # Formulate respectful body text
        time_desc = "rund einer Woche" if 5 <= days_ago <= 10 else f"{days_ago} Tagen"
        role_desc = f" für die Position als {job_title}" if job_title else ""
        closing_name = sender_name or "Ihr Bewerber"

        body = (
            f"{salutation}\n\n"
            f"vor {time_desc} habe ich Ihnen meine Bewerbungsunterlagen{role_desc} zukommen lassen. "
            f"Da ich großes Interesse an einer Mitarbeit in Ihrem Unternehmen habe, möchte ich mich heute "
            f"kurz und freundlich erkundigen, ob meine Unterlagen wohlbehalten bei Ihnen eingegangen sind "
            f"und ob Sie möglicherweise noch ergänzende Informationen von mir benötigen.\n\n"
            f"Über eine kurze Rückmeldung zum aktuellen Stand des Bewerbungsverfahrens würde ich mich sehr freuen.\n\n"
            f"Mit freundlichen Grüßen\n"
            f"{closing_name}"
        )

        return {
            "recipient": email,
            "subject": subject,
            "body": body,
            "days_ago": days_ago,
        }
