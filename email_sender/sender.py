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
    def __init__(
        self,
        sender_email=None,
        password=None,
        throttler=None,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        use_ssl: Optional[bool] = None,
        use_tls: Optional[bool] = None,
    ):
        self.sender_email = str(sender_email or os.getenv("GMAIL_SENDER_EMAIL", os.getenv("SMTP_USER", ""))).strip()
        self.password = str(password or os.getenv("GMAIL_APP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))).replace(" ", "").strip()
        self.throttler = throttler or DomainThrottler()

        self.smtp_host = str(smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")).strip()
        raw_port = smtp_port or os.getenv("SMTP_PORT", "465" if self.smtp_host == "smtp.gmail.com" else "587")
        try:
            self.smtp_port = int(raw_port)
        except ValueError:
            self.smtp_port = 465

        if use_ssl is not None:
            self.use_ssl = use_ssl
        else:
            self.use_ssl = os.getenv("SMTP_USE_SSL", "true" if self.smtp_port == 465 else "false").lower() in ("true", "1")

        if use_tls is not None:
            self.use_tls = use_tls
        else:
            self.use_tls = os.getenv("SMTP_USE_TLS", "true" if self.smtp_port == 587 else "false").lower() in ("true", "1")

        if not self.sender_email or not self.password:
            raise ValueError("Missing sender email or password credentials")

    def _open_connection(self):
        """Creates an authenticated SMTP connection based on configuration."""
        context = ssl.create_default_context()
        if self.use_ssl:
            server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=25)
        else:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=25)
            if self.use_tls:
                server.starttls(context=context)

        server.login(self.sender_email, self.password)
        return server

    def build_message(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        attachments: Optional[List] = None,
    ) -> MIMEMultipart:
        """Constructs a clean MIME message supporting plain text, HTML, and attachments."""
        message = MIMEMultipart("mixed")
        message["Subject"] = subject
        message["From"] = self.sender_email
        message["To"] = to_email

        if body_html:
            body_part = MIMEMultipart("alternative")
            body_part.attach(MIMEText(body, "plain", "utf-8"))
            body_part.attach(MIMEText(body_html, "html", "utf-8"))
            message.attach(body_part)
        else:
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

        return message

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        attachments: Optional[List] = None,
        validate: bool = False,
        check_cooldown: bool = False,
        cooldown_days: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Send a single email via SMTP with optional HTML and pre-checks."""
        clean_recipient = EmailValidator.normalize_email(to_email)
        if not clean_recipient:
            return False, "Recipient email is empty"

        if validate:
            is_valid, reason = EmailValidator.validate_for_sending(clean_recipient, check_mx=True)
            if not is_valid:
                return False, f"Validation failed: {reason}"

        if check_cooldown:
            allowed, cooldown_reason = self.throttler.can_send(clean_recipient, cooldown_days=cooldown_days)
            if not allowed:
                return False, f"Throttled: {cooldown_reason}"

        try:
            message = self.build_message(clean_recipient, subject, body, body_html, attachments)
            with self._open_connection() as server:
                server.sendmail(self.sender_email, clean_recipient, message.as_string())

            self.throttler.record_send(clean_recipient, subject=subject)
            return True, f"Email sent successfully to {clean_recipient}"
        except Exception as exc:
            return False, f"Failed to send: {exc}"

    def send_batch(
        self,
        recipients_data: List[Dict],
        subject_template: str,
        body_template: str,
        body_html_template: Optional[str] = None,
        attachments: Optional[List] = None,
        delay_seconds: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """
        Sends emails to multiple recipients reusing a single persistent SMTP connection.
        Recipients data: list of dicts with 'email', 'name', 'company', etc.
        """
        results = []
        try:
            with self._open_connection() as server:
                for idx, item in enumerate(recipients_data):
                    to_email = item.get("email") or item.get("recipient")
                    clean_recipient = EmailValidator.normalize_email(to_email)
                    if not clean_recipient:
                        results.append({"email": to_email, "success": False, "error": "Invalid email address"})
                        continue

                    # Cooldown check
                    allowed, reason = self.throttler.can_send(clean_recipient)
                    if not allowed:
                        results.append({"email": clean_recipient, "success": False, "error": f"Throttled: {reason}"})
                        continue

                    try:
                        # Template interpolation
                        context = item.get("context", item)
                        subject = subject_template
                        body = body_template
                        body_html = body_html_template

                        for k, v in context.items():
                            token = "{{" + str(k) + "}}"
                            subject = subject.replace(token, str(v or ""))
                            body = body.replace(token, str(v or ""))
                            if body_html:
                                body_html = body_html.replace(token, str(v or ""))

                        message = self.build_message(clean_recipient, subject, body, body_html, attachments)
                        server.sendmail(self.sender_email, clean_recipient, message.as_string())
                        self.throttler.record_send(clean_recipient, subject=subject)
                        results.append({"email": clean_recipient, "success": True, "error": None})
                    except Exception as err:
                        logger.error(f"Failed to send in batch to {clean_recipient}: {err}")
                        results.append({"email": clean_recipient, "success": False, "error": str(err)})

                    if delay_seconds > 0 and idx < len(recipients_data) - 1:
                        import time
                        time.sleep(delay_seconds)
        except Exception as conn_err:
            logger.error(f"Batch SMTP connection failed: {conn_err}")
            results.append({"email": "all", "success": False, "error": f"Connection failed: {conn_err}"})

        return results

