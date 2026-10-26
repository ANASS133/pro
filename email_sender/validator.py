"""
Email Deliverability & Syntax Pre-Flight Validator.
Validates email syntax, filters out disposable/temp mail providers,
system unmonitored mailboxes (noreply), and verifies domain MX DNS records.
"""

import logging
import re
import socket
from typing import Optional, Set, Tuple

logger = logging.getLogger(__name__)

EMAIL_RFC_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

DISPOSABLE_DOMAINS: Set[str] = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com",
    "temp-mail.org", "throwawaymail.com", "sharklasers.com",
    "yopmail.com", "trashmail.com", "getairmail.com", "dispostable.com"
}

SYSTEM_UNMONITORED_PREFIXES: Set[str] = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "hostmaster", "abuse",
    "spam", "daemon", "root", "nobody"
}


class EmailValidator:
    """Pre-flight validator for outbound outreach emails."""

    @classmethod
    def normalize_email(cls, email: Optional[str]) -> str:
        """Strip surrounding punctuation and lowercase."""
        if not email:
            return ""
        return str(email).strip().strip(".,;:\"'<>()[]").lower()

    @classmethod
    def extract_domain(cls, email: str) -> str:
        """Extract domain part of an email address."""
        norm = cls.normalize_email(email)
        if "@" in norm:
            return norm.split("@", 1)[1]
        return ""

    @classmethod
    def check_syntax(cls, email: str) -> Tuple[bool, str]:
        """Check whether email matches valid RFC format."""
        norm = cls.normalize_email(email)
        if not norm:
            return False, "Empty email address"
        if len(norm) > 254:
            return False, "Email address exceeds maximum length of 254 characters"
        if not EMAIL_RFC_REGEX.match(norm):
            return False, "Invalid email address syntax"
        local, domain = norm.split("@", 1)
        if len(local) > 64:
            return False, "Local part exceeds 64 characters"
        if "." not in domain:
            return False, "Domain missing top-level domain"
        return True, "Valid syntax"

    @classmethod
    def is_unmonitored_or_disposable(cls, email: str) -> Tuple[bool, str]:
        """Identify noreply or throwaway temporary mailboxes."""
        norm = cls.normalize_email(email)
        if "@" not in norm:
            return True, "Invalid email format"
        local, domain = norm.split("@", 1)

        if domain in DISPOSABLE_DOMAINS:
            return True, f"Disposable email provider detected: {domain}"

        if local in SYSTEM_UNMONITORED_PREFIXES:
            return True, f"Unmonitored system mailbox: {local}@"

        return False, "Mailbox is monitored"

    @classmethod
    def verify_domain_has_mx(cls, domain: str, timeout: float = 3.0) -> Tuple[bool, str]:
        """
        Verify domain has resolvable mail exchanger (MX) or host IP.
        Uses socket.getaddrinfo as a lightweight zero-dependency resolver.
        """
        if not domain:
            return False, "Missing domain"

        try:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(timeout)
            try:
                # First try resolving MX or host address
                socket.getaddrinfo(domain, 25, socket.AF_UNSPEC, socket.SOCK_STREAM)
                return True, f"Domain {domain} is active and resolvable"
            finally:
                socket.setdefaulttimeout(old_timeout)
        except (socket.gaierror, socket.timeout) as exc:
            return False, f"Domain DNS resolution failed: {exc}"
        except Exception as exc:
            return False, f"Error validating domain: {exc}"

    @classmethod
    def validate_for_sending(
        cls, email: str, check_mx: bool = True
    ) -> Tuple[bool, str]:
        """
        Full validation pipeline. Returns (is_valid, reason).
        """
        valid_syntax, reason = cls.check_syntax(email)
        if not valid_syntax:
            return False, reason

        is_bad, bad_reason = cls.is_unmonitored_or_disposable(email)
        if is_bad:
            return False, bad_reason

        if check_mx:
            domain = cls.extract_domain(email)
            has_mx, mx_reason = cls.verify_domain_has_mx(domain)
            if not has_mx:
                return False, mx_reason

        return True, "Email is valid and deliverable"
