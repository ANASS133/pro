"""
JobScout Autonomous WhatsApp Liaison.
Integrates the central JobScout Conductor with WhatsApp AI and Meta Cloud API.
Dispatches real-time proactive updates to candidates regarding:
- Newly discovered and staged applications
- Recruiter replies, interview invitations, and status changes
- Personalized daily or weekly progress digests
- Polite requests for missing profile documents
Preserves human takeover rules, prevents duplicate notifications, and respects client notification preferences.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.client_manager import client_manager
from services.conductor_store import conductor_store
from services.whatsapp_service import whatsapp_service
from services.whatsapp_store import whatsapp_store

logger = logging.getLogger(__name__)


class ConductorWhatsAppLiaison:
    def __init__(self, store=None, wa_store=None, wa_service=None):
        self._store = store
        self._wa_store = wa_store
        self._wa_service = wa_service

    @property
    def store(self):
        return self._store or conductor_store

    @property
    def wa_store(self):
        return self._wa_store or whatsapp_store

    @property
    def wa_service(self):
        return self._wa_service or whatsapp_service

    def _get_client_phone_and_name(self, client_id: str) -> Tuple[Optional[str], str]:
        """Resolves recipient phone and display name from client dossier."""
        client_data = client_manager.get_client(client_id) or {}
        applicant = client_data.get("applicant", {})
        personal = applicant.get("personal", {})
        contact = applicant.get("contact", {})

        first_name = personal.get("first_name") or ""
        full_name = (
            personal.get("full_name")
            or f"{first_name} {personal.get('last_name', '')}".strip()
            or client_data.get("name")
            or client_id.replace("_", " ").title()
        )
        greeting_name = first_name or full_name

        raw_phone = (
            contact.get("phone")
            or contact.get("whatsapp")
            or client_data.get("phone")
            or client_data.get("whatsapp")
            or ""
        )
        clean_phone = re.sub(r"[^\d]", "", str(raw_phone))

        return (clean_phone if len(clean_phone) >= 6 else None), greeting_name

    def _can_notify_client(self, client_id: str, phone: Optional[str]) -> bool:
        """Verifies global emergency stop, automation toggles, phone validity, and human takeover lock."""
        if not phone:
            return False

        if self.store.is_emergency_stopped():
            self.store.log_event("WARN", "whatsapp", f"Emergency stop active. Suppressed WhatsApp notice for {client_id}.", client_id)
            return False

        if self.store.get_setting("auto_whatsapp_updates", "true").lower() not in ("true", "1", "yes"):
            self.store.log_event("INFO", "whatsapp", f"Global WhatsApp updates disabled. Suppressed for {client_id}.", client_id)
            return False

        config = self.store.get_client_config(client_id)
        if config.get("is_paused", 0):
            self.store.log_event("INFO", "whatsapp", f"Client {client_id} automation is paused. Notification suppressed.", client_id)
            return False

        if not config.get("auto_notify_whatsapp", 1):
            self.store.log_event("INFO", "whatsapp", f"WhatsApp notifications disabled in config for {client_id}.", client_id)
            return False

        # Check if staff human takeover is active for this conversation
        conv = None
        if hasattr(self.wa_store, "get_conversation_by_wa_id"):
            conv = self.wa_store.get_conversation_by_wa_id(phone)
        elif hasattr(self.wa_store, "get_conversation_by_phone"):
            conv = self.wa_store.get_conversation_by_phone(phone)

        if conv and conv.get("id"):
            mode = str(conv.get("mode") or "AI_ACTIVE").upper()
            if mode in ("HUMAN_ACTIVE", "ESCALATED"):
                self.store.log_event(
                    "INFO",
                    "whatsapp",
                    f"Human takeover ({mode}) active for {phone}. Proactive notification suppressed.",
                    client_id
                )
                return False

            takeover_until = conv.get("human_takeover_until")
            if takeover_until:
                try:
                    t_dt = datetime.fromisoformat(takeover_until)
                    if t_dt > datetime.now(timezone.utc):
                        self.store.log_event("INFO", "whatsapp", f"Human takeover timer active for {phone}. Notification suppressed.", client_id)
                        return False
                except Exception:
                    pass

        return True

    def _dispatch_and_record(
        self,
        client_id: str,
        phone: str,
        name: str,
        msg: str,
        notification_type: str,
        dedupe_key: str,
    ) -> bool:
        """Dispatches message via WhatsAppService, records in WhatsAppStore transcript, and logs deduplication key."""
        if self.store.has_notification_been_sent(dedupe_key):
            self.store.log_event(
                "INFO",
                "whatsapp",
                f"Skipped duplicate WhatsApp notification ({notification_type}) for {client_id}.",
                client_id
            )
            return False

        try:
            res = self.wa_service.send_text_message(phone, msg)
            if not res.get("success"):
                return False

            # Record in WhatsApp conversation transcript
            try:
                conv = self.wa_store.get_or_create_conversation(phone, display_name=name, client_id=client_id)
                if conv and conv.get("id"):
                    self.wa_store.add_message(
                        conversation_id=conv["id"],
                        direction="outbound",
                        sender_type="ai",
                        sender_name="JobScout Conductor",
                        content=msg,
                        provider_message_id=res.get("provider_message_id"),
                        delivery_status="sent",
                    )
            except Exception as store_err:
                logger.debug("Could not append outbound Conductor message to whatsapp_store: %s", store_err)

            now_iso = datetime.now(timezone.utc).isoformat()
            self.store.record_notification(
                client_id=client_id,
                notification_type=notification_type,
                dedupe_key=dedupe_key,
                channel="whatsapp",
                content_preview=msg,
            )
            self.store.update_client_config(client_id, {"last_notification_at": now_iso})
            return True
        except Exception as exc:
            logger.error("Failed sending WhatsApp (%s) to %s: %s", notification_type, phone, exc)
            return False

    def notify_new_applications(
        self,
        client_id: str,
        count: int,
        job_titles: Optional[List[str]] = None,
        match_ids: Optional[List[str]] = None,
    ) -> bool:
        """Notifies the candidate about new applications prepared or sent (deduplicated per batch)."""
        if count <= 0:
            return False

        phone, name = self._get_client_phone_and_name(client_id)
        if not self._can_notify_client(client_id, phone):
            return False

        titles_clean = [t.strip() for t in (job_titles or []) if t and t.strip()]
        sig_source = "|".join(sorted(match_ids or titles_clean)) or f"{count}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        dedupe_key = f"new_apps:{client_id}:{hashlib.md5(sig_source.encode()).hexdigest()[:12]}"

        titles_bullet = ""
        if titles_clean:
            bullet_lines = [f"• {t}" for t in titles_clean[:3]]
            titles_bullet = "\n" + "\n".join(bullet_lines)

        msg = (
            f"Hallo {name}! 🚀\n\n"
            f"JobScout hat heute {count} neue Bewerbung(en) für Sie vorbereitet und geprüft:{titles_bullet}\n\n"
            f"Sie können alle Details jederzeit in Ihrem JobScout-Portal einsehen. Bei Fragen schreiben Sie uns einfach hier!"
        )

        sent = self._dispatch_and_record(
            client_id=client_id,
            phone=phone,
            name=name,
            msg=msg,
            notification_type="new_applications",
            dedupe_key=dedupe_key,
        )
        if sent:
            self.store.log_event("SUCCESS", "whatsapp", f"Dispatched new application alert to {phone} ({name})", client_id)
        return sent

    def notify_interview_invitation(
        self,
        client_id: str,
        company: str,
        summary: str = "",
        message_id: str = "",
    ) -> bool:
        """Sends an urgent celebratory notification about an interview invitation."""
        phone, name = self._get_client_phone_and_name(client_id)
        if not self._can_notify_client(client_id, phone):
            return False

        dedupe_key = f"interview:{client_id}:{company.lower().strip()}:{message_id or summary[:30]}"
        details_snippet = f"\n📋 Hinweis: {summary}\n" if summary else ""
        msg = (
            f"🎉 Großartige Neuigkeiten, {name}!\n\n"
            f"Die Firma *{company}* hat auf Ihre Bewerbung geantwortet und möchte ein Gespräch mit Ihnen vereinbaren! 🌟\n"
            f"{details_snippet}\n"
            f"Bitte prüfen Sie umgehend Ihre E-Mails. Wenn Sie Hilfe bei der Vorbereitung wünschen, lassen Sie es uns einfach wissen!"
        )

        sent = self._dispatch_and_record(
            client_id=client_id,
            phone=phone,
            name=name,
            msg=msg,
            notification_type="interview_invitation",
            dedupe_key=dedupe_key,
        )
        if sent:
            self.store.log_event("SUCCESS", "whatsapp", f"Sent INTERVIEW INVITATION alert to {phone} ({company})", client_id)
        return sent

    def notify_recruiter_reply(
        self,
        client_id: str,
        company: str,
        intent: str,
        summary: str = "",
        message_id: str = "",
    ) -> bool:
        """Notifies the candidate about important recruiter replies or status changes (e.g., info_request)."""
        if intent == "interview_invitation":
            return self.notify_interview_invitation(client_id, company, summary=summary, message_id=message_id)

        phone, name = self._get_client_phone_and_name(client_id)
        if not self._can_notify_client(client_id, phone):
            return False

        dedupe_key = f"reply:{client_id}:{intent}:{company.lower().strip()}:{message_id or summary[:30]}"
        if intent == "info_request":
            msg = (
                f"📩 Wichtige Rückmeldung zu Ihrer Bewerbung, {name}!\n\n"
                f"Die Firma *{company}* hat sich gemeldet und bittet um zusätzliche Informationen oder Unterlagen:\n"
                f"„{summary or 'Bitte prüfen Sie Ihr E-Mail-Postfach für Details.'}“\n\n"
                f"Antworten Sie uns gerne direkt hier im Chat, falls wir die Unterlagen für Sie nachreichen sollen!"
            )
        else:
            msg = (
                f"ℹ️ Status-Update für {name}:\n\n"
                f"Neue Rückmeldung von *{company}*: {summary or intent}\n\n"
                f"Ihr JobScout-Team hält Ihr Bewerbungsdossier automatisch aktuell."
            )

        sent = self._dispatch_and_record(
            client_id=client_id,
            phone=phone,
            name=name,
            msg=msg,
            notification_type=f"recruiter_reply_{intent}",
            dedupe_key=dedupe_key,
        )
        if sent:
            self.store.log_event("INFO", "whatsapp", f"Sent recruiter reply ({intent}) notice to {phone} ({company})", client_id)
        return sent

    def send_daily_digest(self, client_id: str, period: str = "daily", force: bool = False) -> bool:
        """Sends a consolidated daily or weekly progress summary to the candidate."""
        phone, name = self._get_client_phone_and_name(client_id)
        if not self._can_notify_client(client_id, phone):
            return False

        counts = self.store.count_matches_by_status(client_id)
        staged = counts.get("staged_for_approval", 0) + counts.get("discovered", 0)
        applied = counts.get("applied", 0)
        interview = counts.get("interview", 0)
        rejected = counts.get("rejected", 0)

        period_label = "Wochenübersicht" if period == "weekly" else "Tagesübersicht"
        date_bucket = datetime.now(timezone.utc).strftime("%Y-%W" if period == "weekly" else "%Y-%m-%d")
        dedupe_key = (
            f"digest:{client_id}:{period}:{date_bucket}:{datetime.now().timestamp()}"
            if force
            else f"digest:{client_id}:{period}:{date_bucket}"
        )

        msg = (
            f"📊 Guten Tag {name}, hier ist Ihre aktuelle JobScout-{period_label}:\n\n"
            f"• In Vorbereitung / Geprüft: {staged}\n"
            f"• Verschickte Bewerbungen: {applied}\n"
            f"• Einladungen / Gespräche: {interview}\n"
            f"• Abgeschlossene Verfahren: {rejected}\n\n"
            f"Unser Autopilot sucht weiterhin automatisch nach den besten Chancen für Sie. Einen erfolgreichen Tag!"
        )

        sent = self._dispatch_and_record(
            client_id=client_id,
            phone=phone,
            name=name,
            msg=msg,
            notification_type=f"{period}_digest",
            dedupe_key=dedupe_key,
        )
        if sent:
            self.store.log_event("INFO", "whatsapp", f"Sent {period} digest to {phone} ({name})", client_id)
        return sent

    def request_missing_documents(self, client_id: str, force: bool = False) -> bool:
        """Detects if CV or language certificate is missing and politely requests upload via chat."""
        phone, name = self._get_client_phone_and_name(client_id)
        if not self._can_notify_client(client_id, phone):
            return False

        docs = client_manager.list_documents(client_id)
        has_cv = any(
            kw in (d.get("fileName", "") or d.get("name", "")).lower()
            for kw in ["cv", "lebenslauf", "resume", "curriculum"]
            for d in docs
        )
        has_cert = any(
            kw in (d.get("fileName", "") or d.get("name", "")).lower()
            for kw in ["b1", "b2", "c1", "zertifikat", "goethe", "telc", "zeugnis", "osd"]
            for d in docs
        )

        missing = []
        if not has_cv:
            missing.append("Lebenslauf (PDF)")
        if not has_cert:
            missing.append("Deutsch-Zertifikat (z. B. B1/B2)")

        if not missing:
            return False  # Complete

        missing_str = " und ".join(missing)
        dedupe_key = (
            f"missing_docs:{client_id}:{missing_str}:{datetime.now().timestamp()}"
            if force
            else f"missing_docs:{client_id}:{missing_str}"
        )

        msg = (
            f"Hallo {name}! 👋\n\n"
            f"Um Ihre Bewerbungserfolge zu beschleunigen, fehlt in Ihrem Profil noch: *{missing_str}*.\n\n"
            f"Sie können die Datei(en) ganz einfach direkt hier im Chat als PDF oder klares Foto senden. Unser System fügt sie automatisch Ihrem Dossier hinzu! 📄"
        )

        sent = self._dispatch_and_record(
            client_id=client_id,
            phone=phone,
            name=name,
            msg=msg,
            notification_type="missing_documents_request",
            dedupe_key=dedupe_key,
        )
        if sent:
            self.store.log_event("INFO", "whatsapp", f"Requested missing document(s) ({missing_str}) from {phone}", client_id)
        return sent


conductor_whatsapp_liaison = ConductorWhatsAppLiaison()
