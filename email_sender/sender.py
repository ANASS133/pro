import logging
import os
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Tuple

from .throttler import DomainThrottler
from .validator import EmailValidator

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, sender_email=None, password=None, throttler=None):
        self.sender_email = str(sender_email or os.getenv("GMAIL_SENDER_EMAIL", "")).strip()
        self.password = str(password or os.getenv("GMAIL_APP_PASSWORD", "")).replace(" ", "").strip()
        self.throttler = throttler or DomainThrottler()

        if not self.sender_email or not self.password:
            raise ValueError("Missing GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD")

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachments: Optional[List] = None,
        validate: bool = False,
        check_cooldown: bool = False,
        cooldown_days: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Send an email via Gmail SMTP SSL.
        Optionally pre-validates syntax/deliverability and respects domain cooldown.
        """
        clean_recipient = EmailValidator.normalize_email(to_email)
        if not clean_recipient:
            return False, "Recipient email is empty"

        # Optional Deliverability Pre-Validation
        if validate:
            is_valid, reason = EmailValidator.validate_for_sending(clean_recipient, check_mx=True)
            if not is_valid:
                return False, f"Validation failed: {reason}"

        # Optional Domain Cooldown Check
        if check_cooldown:
            allowed, cooldown_reason = self.throttler.can_send(clean_recipient, cooldown_days=cooldown_days)
            if not allowed:
                return False, f"Throttled: {cooldown_reason}"

        try:
            message = MIMEMultipart("mixed")
            message["Subject"] = subject
            message["From"] = self.sender_email
            message["To"] = clean_recipient

            message.attach(MIMEText(body, "plain", "utf-8"))

            for item in attachments or []:
                try:
                    filename, file_bytes, _content_type = item
                except (TypeError, ValueError):
                    continue

                safe_name = str(filename or "").strip()
                payload = bytes(file_bytes or b"")
                if not safe_name or not payload:
                    continue

                part = MIMEBase("application", "octet-stream")
                part.set_payload(payload)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=("utf-8", "", safe_name),
                )
                message.attach(part)

            context = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
                server.login(self.sender_email, self.password)
                server.sendmail(self.sender_email, clean_recipient, message.as_string())

            # Record send history for throttling protection
            self.throttler.record_send(clean_recipient, subject=subject)

            return True, f"Email sent successfully to {clean_recipient}"
        except Exception as exc:
            return False, f"Failed to send: {exc}"
