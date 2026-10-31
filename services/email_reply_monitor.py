"""
JobScout Autonomous Email Reply Monitoring Engine.
Connects to recruitment email inboxes via secure IMAP/OAuth (XOAUTH2 or App Password).
Detects recruiter replies, interview invitations, rejections, info requests, and confirmation of receipts.
Utilizes the Central AI Gateway (ai_manager) to classify intent, extract summaries, and draft follow-ups.
Automatically updates client application statuses and client statistics in ConductorStore & ClientManager,
notifies administrators about important messages, and triggers real-time WhatsApp candidate alerts.
"""

import email
from email.header import decode_header
import imaplib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.ai_provider_manager import ai_manager
from services.client_manager import client_manager
from services.conductor_store import conductor_store

logger = logging.getLogger(__name__)


def _clean_header(val: str) -> str:
    """Decodes MIME encoded-word syntax in email headers."""
    if not val:
        return ""
    try:
        decoded_parts = decode_header(val)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(str(part))
        return " ".join(result).strip()
    except Exception:
        return str(val)


class EmailReplyMonitor:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        oauth_token: Optional[str] = None,
        use_ssl: Optional[bool] = None,
        store=None,
    ):
        self.host = str(host or os.getenv("IMAP_HOST", "imap.gmail.com")).strip()
        raw_port = port or os.getenv("IMAP_PORT", "993")
        try:
            self.port = int(raw_port)
        except ValueError:
            self.port = 993

        self.user = str(user or os.getenv("IMAP_USER", os.getenv("GMAIL_SENDER_EMAIL", os.getenv("SMTP_USER", "")))).strip()
        self.password = str(password or os.getenv("IMAP_PASSWORD", os.getenv("GMAIL_APP_PASSWORD", os.getenv("SMTP_PASSWORD", "")))).replace(" ", "").strip()
        self.oauth_token = str(oauth_token or os.getenv("IMAP_OAUTH_TOKEN", "")).strip()
        self.use_ssl = use_ssl if use_ssl is not None else os.getenv("IMAP_USE_SSL", "true").lower() in ("true", "1")
        self._store = store

    @property
    def store(self):
        return self._store or conductor_store

    def is_configured(self) -> bool:
        return bool(self.user and (self.password or self.oauth_token))

    def _open_imap_connection(self) -> Optional[imaplib.IMAP4]:
        if not self.is_configured():
            logger.debug("IMAP monitor not configured with user and password/OAuth token.")
            return None
        try:
            if self.use_ssl:
                conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=20)
            else:
                conn = imaplib.IMAP4(self.host, self.port, timeout=20)

            if self.oauth_token:
                auth_string = f"user={self.user}\x01auth=Bearer {self.oauth_token}\x01\x01"
                conn.authenticate("XOAUTH2", lambda _: auth_string.encode("utf-8"))
            else:
                conn.login(self.user, self.password)
            return conn
        except Exception as exc:
            logger.warning("Could not connect to IMAP server %s: %s", self.host, exc)
            return None

    def classify_email_content(self, sender: str, subject: str, body: str) -> Dict[str, Any]:
        """
        Uses central AI Gateway to classify incoming recruiter messages into intent,
        extract matching company, and generate polite German response draft if relevant.
        """
        system_prompt = (
            "You are JobScout Autonomous Recruitment Email Classifier.\n"
            "Analyze the incoming recruiter email and classify it accurately into exactly one intent:\n"
            "- 'interview_invitation': Invitation to a job interview, phone screening, assessment, or conversation.\n"
            "- 'rejection': Negative response, rejection, position already filled, or cancellation.\n"
            "- 'confirmation_of_receipt': Automated receipt confirmation acknowledging application was received.\n"
            "- 'info_request': Asking for more documents, certificates, references, or specific questions.\n"
            "- 'other': Newsletter, marketing, unrelated, or spam.\n\n"
            "Return valid JSON with schema:\n"
            "{\n"
            "  \"intent\": \"interview_invitation|rejection|confirmation_of_receipt|info_request|other\",\n"
            "  \"confidence\": 0.95,\n"
            "  \"company\": \"Company Name\",\n"
            "  \"candidate_name\": \"Candidate Name if found\",\n"
            "  \"summary\": \"1-2 sentence German summary of the recruiter's message\",\n"
            "  \"suggested_reply\": \"Polite, professional German reply draft if follow-up is warranted, else empty\"\n"
            "}"
        )

        user_content = f"SENDER: {sender}\nSUBJECT: {subject}\n\nBODY SNIPPET:\n{body[:1500]}"

        try:
            res = ai_manager.complete(
                prompt=user_content,
                system_prompt=system_prompt,
                json_mode=True,
                max_output_tokens=500,
                temperature=0.1,
                use_cache=True,
            )
            parsed = res.get("parsed_json")
            if not parsed and res.get("content"):
                cleaned = res["content"].replace("```json", "").replace("```", "").strip()
                parsed = json.loads(cleaned)

            if isinstance(parsed, dict) and "intent" in parsed:
                return {
                    "intent": parsed.get("intent", "other"),
                    "confidence": float(parsed.get("confidence", 0.85)),
                    "company": parsed.get("company", ""),
                    "candidate_name": parsed.get("candidate_name", ""),
                    "summary": parsed.get("summary", ""),
                    "suggested_reply": parsed.get("suggested_reply", ""),
                }
        except Exception as exc:
            logger.warning("AI classification error: %s. Using rule-based fallback.", exc)

        # Rule-based fallback classifier
        text_lower = f"{subject} {body}".lower()
        sender_domain_company = sender.split("@")[-1].split(".")[0].replace("-", " ").title() if "@" in sender else ""

        if any(w in text_lower for w in ["vorstellungsgespräch", "kennenlernen", "einladung zum", "interview", "video-call", "terminvorschlag", "einladen"]):
            return {
                "intent": "interview_invitation",
                "confidence": 0.92,
                "company": sender_domain_company,
                "candidate_name": "",
                "summary": "Einladung zu einem Kennenlerngespräch oder Vorstellungsgespräch erhalten.",
                "suggested_reply": (
                    "Sehr geehrte Damen und Herren,\n\n"
                    "vielen Dank für Ihre positive Rückmeldung und die Einladung zum Vorstellungsgespräch! "
                    "Gerne bestätige ich den vorgeschlagenen Termin und freue mich auf das persönliche Kennenlernen.\n\n"
                    "Mit freundlichen Grüßen"
                ),
            }
        elif any(w in text_lower for w in ["leider", "absage", "anderweitig entschieden", "nicht berücksichtigen", "nicht geklappt", "bedauern"]):
            return {
                "intent": "rejection",
                "confidence": 0.92,
                "company": sender_domain_company,
                "candidate_name": "",
                "summary": "Absage des Unternehmens zur eingereichten Bewerbung.",
                "suggested_reply": "",
            }
        elif any(w in text_lower for w in ["eingangsbestätigung", "haben wir erhalten", "vielen dank für ihre bewerbung", "bestätigung", "eingang ihrer bewerbung"]):
            return {
                "intent": "confirmation_of_receipt",
                "confidence": 0.88,
                "company": sender_domain_company,
                "candidate_name": "",
                "summary": "Automatische Eingangsbestätigung der Bewerbung.",
                "suggested_reply": "",
            }
        elif any(w in text_lower for w in ["unterlagen nachreichen", "zeugnis", "zertifikat", "rückfrage", "bitte senden sie", "fehlende unterlagen"]):
            return {
                "intent": "info_request",
                "confidence": 0.87,
                "company": sender_domain_company,
                "candidate_name": "",
                "summary": "Das Unternehmen bittet um zusätzliche Informationen oder Bewerbungsunterlagen.",
                "suggested_reply": (
                    "Sehr geehrte Damen und Herren,\n\n"
                    "vielen Dank für Ihre Nachricht. Anbei sende ich Ihnen gerne die gewünschten zusätzlichen Unterlagen zu.\n\n"
                    "Mit freundlichen Grüßen"
                ),
            }

        return {
            "intent": "other",
            "confidence": 0.60,
            "company": sender_domain_company,
            "candidate_name": "",
            "summary": "Allgemeine oder nicht zuordenbare Nachricht.",
            "suggested_reply": "",
        }

    def correlate_with_client_matches(
        self,
        sender: str,
        recipient: str,
        company_name: str,
        candidate_name: str,
        body_text: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Finds matching (client_matches record, client_id) by sender email, company name,
        sender domain, recipient email, or candidate name in body.
        """
        matches = self.store.list_matches(limit=500)
        sender_clean = (sender or "").lower()
        recipient_clean = (recipient or "").lower()
        company_clean = (company_name or "").lower().strip()
        candidate_clean = (candidate_name or "").lower().strip()
        body_lower = (body_text or "").lower()

        # 1. Match on exact or substring company name in client_matches
        if company_clean and len(company_clean) > 2:
            for m in matches:
                m_comp = m.get("company", "").lower().strip()
                if m_comp and (company_clean in m_comp or m_comp in company_clean):
                    return m, m["client_id"]

        # 2. Match on sender email address in client_matches
        for m in matches:
            m_email = m.get("email", "").lower().strip()
            if m_email and m_email in sender_clean:
                return m, m["client_id"]

        # 3. Match on sender domain against match link or email
        sender_domain = sender_clean.split("@")[-1].split(">")[0].strip() if "@" in sender_clean else ""
        if sender_domain and len(sender_domain) > 3 and not sender_domain.endswith(("gmail.com", "yahoo.com", "gmx.de", "web.de", "outlook.com")):
            domain_stem = sender_domain.split(".")[0]
            for m in matches:
                link = m.get("link", "").lower()
                m_email = m.get("email", "").lower()
                m_comp = m.get("company", "").lower()
                if sender_domain in link or sender_domain in m_email or (len(domain_stem) > 3 and domain_stem in m_comp):
                    return m, m["client_id"]

        # 4. Match candidate by recipient email or candidate name in body against registered clients
        try:
            for c in client_manager.list_clients():
                cid = c["id"]
                c_name = str(c.get("name") or "").lower().strip()
                c_email = str(c.get("email") or "").lower().strip()
                if (c_email and c_email in recipient_clean) or (candidate_clean and candidate_clean in c_name) or (c_name and len(c_name) > 4 and c_name in body_lower):
                    c_matches = [m for m in matches if m.get("client_id") == cid]
                    return (c_matches[0] if c_matches else None), cid
        except Exception:
            pass

        if matches:
            return matches[0], matches[0]["client_id"]
        return None, ""

    def _update_client_reply_stats(self, client_id: str, intent: str):
        """Updates the client's dossier metrics when an interview, rejection, or confirmation arrives."""
        if not client_id:
            return
        try:
            client_data = client_manager.get_client(client_id)
            if not client_data:
                return
            metrics = client_data.get("metrics") or {}
            if intent == "interview_invitation":
                metrics["interviews_count"] = int(metrics.get("interviews_count", 0)) + 1
            elif intent == "rejection":
                metrics["rejections_count"] = int(metrics.get("rejections_count", 0)) + 1
            elif intent == "confirmation_of_receipt":
                metrics["confirmations_count"] = int(metrics.get("confirmations_count", 0)) + 1
            metrics["last_reply_at"] = datetime.now(timezone.utc).isoformat()
            client_data["metrics"] = metrics
            client_manager.save_client(client_id, client_data)
        except Exception as exc:
            logger.debug("Could not update client reply stats for %s: %s", client_id, exc)

    def process_incoming_message(
        self,
        message_id: str,
        sender: str,
        recipient: str,
        subject: str,
        received_at: str,
        body: str,
        client_id_hint: str = "",
    ) -> Dict[str, Any]:
        """Classifies an individual email message, updates application & client state, and generates alerts."""
        classification = self.classify_email_content(sender, subject, body)
        intent = classification["intent"]
        company = classification.get("company") or ""
        candidate_name = classification.get("candidate_name") or ""

        # Correlate with client & match
        matched_match, resolved_client_id = self.correlate_with_client_matches(
            sender=sender,
            recipient=recipient,
            company_name=company,
            candidate_name=candidate_name,
            body_text=f"{subject}\n{body}",
        )
        client_id = client_id_hint or resolved_client_id
        if matched_match and not company:
            company = matched_match.get("company", "")

        action_taken = "Logged message"
        match_id = matched_match["id"] if matched_match else None

        if intent == "interview_invitation":
            if match_id:
                self.store.update_match_status(match_id, "interview")
            action_taken = f"Updated status to INTERVIEW for {company or sender}; drafted follow-up & notified admin + candidate"
            self.store.log_event(
                "SUCCESS",
                "email_monitor",
                f"🎉 ADMIN ALERT — INTERVIEW INVITATION from {company or sender} for client '{client_id or 'unassigned'}': {classification.get('summary')}",
                client_id=client_id,
            )
            self._update_client_reply_stats(client_id, intent)
            if client_id:
                try:
                    from services.conductor_whatsapp_liaison import conductor_whatsapp_liaison
                    conductor_whatsapp_liaison.notify_interview_invitation(
                        client_id=client_id,
                        company=company or sender,
                        summary=classification.get("summary", "Einladung zum Vorstellungsgespräch"),
                        message_id=message_id,
                    )
                except Exception as exc:
                    logger.debug("WhatsApp interview notification dispatch: %s", exc)

        elif intent == "rejection":
            if match_id:
                self.store.update_match_status(match_id, "rejected")
            action_taken = f"Updated status to REJECTED for {company or sender}"
            self.store.log_event(
                "INFO",
                "email_monitor",
                f"Recorded rejection from {company or sender} for client '{client_id}'",
                client_id=client_id,
            )
            self._update_client_reply_stats(client_id, intent)

        elif intent == "confirmation_of_receipt":
            if match_id:
                self.store.update_match_status(match_id, "applied")
            action_taken = f"Confirmed application delivery for {company or sender}"
            self.store.log_event(
                "INFO",
                "email_monitor",
                f"Application receipt confirmed by {company or sender} for '{client_id}'",
                client_id=client_id,
            )
            self._update_client_reply_stats(client_id, intent)

        elif intent == "info_request":
            action_taken = f"Drafted follow-up & alerted administrator + client for {company or sender}"
            self.store.log_event(
                "WARN",
                "email_monitor",
                f"⚠️ ADMIN ALERT — Recruiter info/document request from {company or sender} for '{client_id}': {classification.get('summary')}",
                client_id=client_id,
            )
            if client_id:
                try:
                    from services.conductor_whatsapp_liaison import conductor_whatsapp_liaison
                    conductor_whatsapp_liaison.notify_recruiter_reply(
                        client_id=client_id,
                        company=company or sender,
                        intent="info_request",
                        summary=classification.get("summary", ""),
                        message_id=message_id,
                    )
                except Exception as exc:
                    logger.debug("WhatsApp info_request notification dispatch: %s", exc)

        log_entry = {
            "message_id": message_id,
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "received_at": received_at,
            "intent": intent,
            "confidence": classification.get("confidence", 0.0),
            "matched_client_id": client_id,
            "matched_company": company,
            "summary": classification.get("summary", ""),
            "suggested_reply": classification.get("suggested_reply", ""),
            "action_taken": action_taken,
        }
        saved = self.store.log_inbox_message(log_entry)
        return saved

    def check_inbox(self, max_messages: int = 15) -> Dict[str, Any]:
        """
        Polls IMAP server for recent email replies.
        If IMAP credentials are not configured, runs in unconfigured audit mode.
        """
        if not self.is_configured():
            self.store.log_event("INFO", "email_monitor", "IMAP credentials not configured. Running in audit check mode.")
            return {
                "configured": False,
                "status": "unconfigured_audit_mode",
                "processed_count": 0,
                "messages": [],
            }

        conn = self._open_imap_connection()
        if not conn:
            self.store.log_event("WARN", "email_monitor", "Failed connecting to IMAP server. Please verify credentials.")
            return {
                "configured": True,
                "status": "connection_error",
                "processed_count": 0,
                "messages": [],
            }

        processed = []
        try:
            conn.select("INBOX", readonly=True)
            status, msg_nums = conn.search(None, "ALL")
            if status != "OK" or not msg_nums or not msg_nums[0]:
                conn.logout()
                return {"configured": True, "status": "empty_inbox", "processed_count": 0, "messages": []}

            ids = msg_nums[0].split()
            recent_ids = ids[-max_messages:]

            for mid_bytes in reversed(recent_ids):
                try:
                    res, data = conn.fetch(mid_bytes, "(RFC822)")
                    if res != "OK" or not data:
                        continue
                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    subj = _clean_header(msg.get("Subject", ""))
                    sender = _clean_header(msg.get("From", ""))
                    recipient = _clean_header(msg.get("To", ""))
                    date_hdr = msg.get("Date", "")
                    message_id_hdr = msg.get("Message-ID") or f"imap_{mid_bytes.decode()}_{date_hdr}"

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            cdisp = str(part.get("Content-Disposition", ""))
                            if ctype == "text/plain" and "attachment" not in cdisp:
                                payload_bytes = part.get_payload(decode=True)
                                if payload_bytes:
                                    body = payload_bytes.decode("utf-8", errors="replace")
                                break
                    else:
                        payload_bytes = msg.get_payload(decode=True)
                        if payload_bytes:
                            body = payload_bytes.decode("utf-8", errors="replace")

                    result = self.process_incoming_message(
                        message_id=message_id_hdr,
                        sender=sender,
                        recipient=recipient,
                        subject=subj,
                        received_at=datetime.now(timezone.utc).isoformat(),
                        body=body,
                    )
                    processed.append(result)
                except Exception as inner_exc:
                    logger.debug("Error processing email message %s: %s", mid_bytes, inner_exc)

            conn.logout()
        except Exception as exc:
            logger.error("Error during IMAP check: %s", exc)
            return {"configured": True, "status": "error", "error": str(exc), "processed_count": 0, "messages": []}

        return {
            "configured": True,
            "status": "success",
            "processed_count": len(processed),
            "messages": processed,
        }


email_reply_monitor = EmailReplyMonitor()
