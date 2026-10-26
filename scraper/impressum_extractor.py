"""
Impressum & German Legal Notice (§ 5 TMG / DDG) Extractor.
Extracts managing directors (Geschäftsführer/Inhaber), company representation,
direct emails, and telephone numbers from German websites.
"""

import logging
import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Patterns for discovering impressum links
IMPRESSUM_URL_PATTERNS = [
    re.compile(r"impressum", re.IGNORECASE),
    re.compile(r"imprint", re.IGNORECASE),
    re.compile(r"legal[-_]?notice", re.IGNORECASE),
    re.compile(r"rechtliche[s]?[-_]?hinweise", re.IGNORECASE),
]

# Patterns for extracting managing directors / representatives
GESCHAEFTSFUEHRER_PATTERNS = [
    re.compile(
        r"(?:geschäftsführer(?:in)?|geschäftsführung|inhaber(?:in)?|vorstand|vertreten\s+durch)\s*[:\-\s]\s*([^\n\r<]{3,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:vertretungsberechtigt[e|er|en]*)\s*(?:person(?:en)?|gesellschafter)?\s*[:\-\s]\s*([^\n\r<]{3,120})",
        re.IGNORECASE,
    ),
]

# Clean name token: matches German names like "Dr. Thomas Müller" or "Melanie Weber"
NAME_TOKEN = r"(?:(?:Dr\.|Prof\.|Dipl\.-[A-Za-z]+)\s+)*[A-ZÄÖÜ][a-zäöüß]+(?:[- ][A-ZÄÖÜ][a-zäöüß]+)*"
INDIVIDUAL_NAME_RE = re.compile(rf"\b{NAME_TOKEN}\s+{NAME_TOKEN}\b")

# Email regex
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Phone regex (German format support)
PHONE_REGEX = re.compile(
    r"(?:\+49|0049|0)\s*(?:\(0\)\s*)?[1-9][0-9\s/().\-]{5,22}[0-9]",
    re.MULTILINE,
)


class ImpressumExtractor:
    """Extracts executive contact details from German Impressum pages."""

    def __init__(self, session: Optional[requests.Session] = None, timeout: int = 12):
        self.session = session or requests.Session()
        self.timeout = timeout
        if "User-Agent" not in self.session.headers:
            self.session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                }
            )

    def find_impressum_urls(self, base_url: str, html_content: str) -> List[str]:
        """Discover Impressum URLs from page HTML links and standard fallback routes."""
        discovered: List[str] = []
        seen: Set[str] = set()

        if html_content:
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = (a_tag.get("href") or "").strip()
                    text = a_tag.get_text() or ""
                    if not href or href.startswith("#") or href.startswith("javascript:"):
                        continue

                    is_match = any(p.search(href) or p.search(text) for p in IMPRESSUM_URL_PATTERNS)
                    if is_match:
                        full_url = urljoin(base_url, href)
                        if urlparse(full_url).netloc == urlparse(base_url).netloc:
                            if full_url not in seen:
                                seen.add(full_url)
                                discovered.append(full_url)
            except Exception as exc:
                logger.debug("Failed parsing links for impressum: %s", exc)

        common_paths = ["/impressum", "/impressum/", "/impressum.html", "/de/impressum", "/imprint"]
        for path in common_paths:
            fallback_url = urljoin(base_url, path)
            if fallback_url not in seen:
                seen.add(fallback_url)
                discovered.append(fallback_url)

        return discovered

    def extract_from_html(self, html_content: str, source_url: str = "") -> Dict:
        """Parse Impressum HTML to extract directors, emails, phone numbers, and salutation."""
        result = {
            "geschaeftsfuehrer": "",
            "geschaeftsfuehrer_liste": [],
            "salutation": "Sehr geehrte Damen und Herren,",
            "emails": [],
            "primary_email": "",
            "phone": "",
            "source_url": source_url,
        }

        if not html_content:
            return result

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Extract emails (from mailto and text)
        emails: Set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if href.startswith("mailto:"):
                clean = href.replace("mailto:", "").split("?")[0].strip().lower()
                if clean:
                    emails.add(clean)

        raw_text = soup.get_text(separator=" ")
        for match in EMAIL_REGEX.findall(raw_text):
            clean = match.strip().strip(".,;:").lower()
            if not clean.endswith((".png", ".jpg", ".jpeg", ".gif")):
                emails.add(clean)

        sorted_emails = sorted(list(emails))
        result["emails"] = sorted_emails
        if sorted_emails:
            primary = sorted_emails[0]
            for em in sorted_emails:
                if any(k in em for k in ["bewerbung", "karriere", "jobs", "gf", "leitung"]):
                    primary = em
                    break
            result["primary_email"] = primary

        # 2. Extract phone numbers
        phone_matches = PHONE_REGEX.findall(raw_text)
        if phone_matches:
            result["phone"] = re.sub(r"\s+", " ", phone_matches[0]).strip()

        # 3. Extract Managing Directors / Leaders
        directors: List[str] = []

        # Check block elements with flattened space
        blocks_to_check = []
        for tag in soup.find_all(["p", "div", "li", "td", "span"]):
            text = re.sub(r"\s+", " ", tag.get_text()).strip()
            if len(text) > 5:
                blocks_to_check.append(text)
        blocks_to_check.append(re.sub(r"\s+", " ", raw_text))

        for block_text in blocks_to_check:
            for pattern in GESCHAEFTSFUEHRER_PATTERNS:
                for match in pattern.finditer(block_text):
                    chunk = match.group(1).strip()
                    # Clean out common trailing legal words
                    clean_chunk = re.split(
                        r"(?:Amtsgericht|HRB|HRA|USt-IdNr|Sitz der Gesellschaft|Registergericht|Inhaltlich Verantwortlicher)",
                        chunk,
                        flags=re.IGNORECASE,
                    )[0]
                    # Find person names in this chunk
                    names = INDIVIDUAL_NAME_RE.findall(clean_chunk)
                    for n in names:
                        cleaned_name = n.strip()
                        # Avoid false positives like "GmbH & Co" or company words
                        if not any(k in cleaned_name.lower() for k in ["gmbh", "amtsgericht", "deutschland", "strasse"]):
                            if len(cleaned_name) > 4 and cleaned_name not in directors:
                                directors.append(cleaned_name)

        result["geschaeftsfuehrer_liste"] = directors
        if directors:
            primary_director = directors[0]
            result["geschaeftsfuehrer"] = primary_director
            result["salutation"] = self.generate_salutation(primary_director)

        return result

    @staticmethod
    def generate_salutation(full_name: str) -> str:
        """Generate appropriate German business salutation (e.g. 'Sehr geehrter Herr Dr. Müller,')."""
        if not full_name:
            return "Sehr geehrte Damen und Herren,"

        clean = re.sub(r"\s+", " ", full_name).strip()
        tokens = clean.split()
        if not tokens:
            return "Sehr geehrte Damen und Herren,"

        last_name = tokens[-1]
        title = ""
        for t in tokens[:-1]:
            if t in ["Dr.", "Prof.", "Dr. med.", "Prof. Dr."]:
                title = f"{t} "
                break

        # Check for explicit Frau / Herr
        first_word = tokens[0].lower()
        if "frau" in first_word:
            return f"Sehr geehrte Frau {title}{last_name},"
        if "herr" in first_word or "herrn" in first_word:
            return f"Sehr geehrter Herr {title}{last_name},"

        if title:
            return f"Sehr geehrte/r {title}{last_name},"

        return f"Sehr geehrte/r {clean},"

    def extract_from_website(self, base_url: str, homepage_html: Optional[str] = None) -> Dict:
        """Attempt to fetch and parse the website's Impressum page."""
        if not base_url:
            return self.extract_from_html("")

        candidate_urls = self.find_impressum_urls(base_url, homepage_html or "")
        for url in candidate_urls:
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                if resp.status_code == 200 and resp.text:
                    parsed = self.extract_from_html(resp.text, source_url=url)
                    if parsed.get("geschaeftsfuehrer") or parsed.get("primary_email"):
                        return parsed
            except Exception as exc:
                logger.debug("Failed requesting impressum %s: %s", url, exc)

        if homepage_html:
            return self.extract_from_html(homepage_html, source_url=base_url)

        return self.extract_from_html("")
