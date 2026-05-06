import os
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class EmailSender:
    def __init__(self, sender_email=None, password=None):
        self.sender_email = str(sender_email or os.getenv("GMAIL_SENDER_EMAIL", "")).strip()
        self.password = str(password or os.getenv("GMAIL_APP_PASSWORD", "")).replace(" ", "").strip()

        if not self.sender_email or not self.password:
            raise ValueError("Missing GMAIL_SENDER_EMAIL or GMAIL_APP_PASSWORD")

    def send(self, to_email, subject, body, attachments=None):
        try:
            message = MIMEMultipart("mixed")
            message["Subject"] = subject
            message["From"] = self.sender_email
            message["To"] = to_email

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
                server.sendmail(self.sender_email, to_email, message.as_string())

            return True, f"Email sent successfully to {to_email}"
        except Exception as exc:
            return False, f"Failed to send: {exc}"
