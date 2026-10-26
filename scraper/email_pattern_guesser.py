"""
Email Pattern Guesser for Corporate Outreach.
Generates highly probable business email addresses for known contacts and companies,
accurately handling German umlauts, academic titles, and common company naming conventions.
"""

import re
import unicodedata
from typing import Dict, List, Optional
from urllib.parse import urlparse

UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "Ä": "ae",
    "Ö": "oe",
    "Ü": "ue",
    "ß": "ss",
}

COMMON_GERMAN_TITLES = {
    "frau", "herr", "herrn", "dr.", "dr", "prof.", "prof", "dipl.-ing.", "dipl.",
    "ing.", "mag.", "b.a.", "m.a.", "b.sc.", "m.sc.", "mba"
}


def clean_german_umlauts(text: str) -> str:
    """Replace German umlauts with standard ASCII representations."""
    res = text
    for char, rep in UMLAUT_MAP.items():
        res = res.replace(char, rep)
    # Strip remaining accents
    nfkd = unicodedata.normalize("NFKD", res)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def extract_domain(website_or_url: str) -> str:
    """Extract clean domain without www., http(s), or trailing paths."""
    val = str(website_or_url or "").strip().lower()
    if not val:
        return ""
    if not val.startswith(("http://", "https://")):
        val = "http://" + val
    parsed = urlparse(val)
    netloc = parsed.netloc or parsed.path
    netloc = netloc.split(":")[0]  # strip port
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.strip("/ ")


class EmailPatternGuesser:
    """Generates and ranks candidate email addresses based on person names and company domains."""

    @classmethod
    def parse_name(cls, full_name: str) -> Dict[str, str]:
        """Split and normalize first and last names, removing titles and honorifics."""
        cleaned = re.sub(r"[,;()]+", " ", str(full_name or "")).strip()
        tokens = cleaned.split()

        filtered_tokens = []
        salutation = ""
        for t in tokens:
            t_lower = t.lower()
            if t_lower in ["frau", "herr", "herrn"]:
                salutation = t
                continue
            if t_lower in COMMON_GERMAN_TITLES:
                continue
            filtered_tokens.append(t)

        if not filtered_tokens:
            return {"first_name": "", "last_name": "", "salutation": salutation}

        if len(filtered_tokens) == 1:
            return {"first_name": "", "last_name": filtered_tokens[0], "salutation": salutation}

        first_name = filtered_tokens[0]
        # For hyphenated last names (e.g. Weber-Schmidt), keep together
        last_name = " ".join(filtered_tokens[1:])

        return {
            "first_name": first_name,
            "last_name": last_name,
            "salutation": salutation,
        }

    @classmethod
    def generate_candidates(
        cls,
        full_name: str,
        domain_or_website: str,
        limit: int = 6,
    ) -> List[Dict[str, str]]:
        """
        Generate ranked candidate emails for a contact.
        Returns list of dicts with 'email', 'pattern', and 'confidence'.
        """
        domain = extract_domain(domain_or_website)
        if not domain or "@" in domain:
            return []

        name_info = cls.parse_name(full_name)
        first = clean_german_umlauts(name_info["first_name"]).lower()
        last = clean_german_umlauts(name_info["last_name"]).lower()

        # Sanitize non-alphanumeric characters except hyphen
        first = re.sub(r"[^a-z0-9\-]", "", first)
        last = re.sub(r"[^a-z0-9\-]", "", last)

        candidates: List[Dict[str, str]] = []

        if first and last:
            # 1. vorname.nachname@domain (Most common in Germany)
            candidates.append({
                "email": f"{first}.{last}@{domain}",
                "pattern": "first.last",
                "confidence": "high",
            })
            # 2. v.nachname@domain
            candidates.append({
                "email": f"{first[0]}.{last}@{domain}",
                "pattern": "f.last",
                "confidence": "high",
            })
            # 3. nachname@domain
            candidates.append({
                "email": f"{last}@{domain}",
                "pattern": "last",
                "confidence": "medium",
            })
            # 4. vornamenachname@domain
            candidates.append({
                "email": f"{first}{last}@{domain}",
                "pattern": "firstlast",
                "confidence": "medium",
            })
            # 5. v_nachname@domain
            candidates.append({
                "email": f"{first[0]}_{last}@{domain}",
                "pattern": "f_last",
                "confidence": "low",
            })
            # 6. vorname@domain
            candidates.append({
                "email": f"{first}@{domain}",
                "pattern": "first",
                "confidence": "low",
            })
        elif last:
            # Only last name known (e.g. "Herr Müller")
            candidates.append({
                "email": f"{last}@{domain}",
                "pattern": "last",
                "confidence": "medium",
            })

        # Also provide generic department fallbacks if needed
        return candidates[:limit]
