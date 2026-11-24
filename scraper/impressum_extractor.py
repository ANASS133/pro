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

# Patterns for discovering impressum links (prioritized) and contact/career fallbacks
IMPRESSUM_URL_PATTERNS = [
    re.compile(r"impressum", re.IGNORECASE),
    re.compile(r"imprint", re.IGNORECASE),
    re.compile(r"legal[-_]?notice", re.IGNORECASE),
    re.compile(r"rechtliche[s]?[-_]?hinweise", re.IGNORECASE),
]

KONTAKT_URL_PATTERNS = [
    re.compile(r"\bkontakt\b|kontakt[-_]|/contact", re.IGNORECASE),
    re.compile(r"karriere|ausbildung", re.IGNORECASE),
]

NON_APPLICATION_EMAIL_PREFIXES = (
    "noreply@",
    "no-reply@",
    "donotreply@",
    "do-not-reply@",
    "datenschutz@",
    "privacy@",
    "dsb@",
    "webmaster@",
    "postmaster@",
    "abuse@",
    "widerruf@",
    "dsa@",
    "barrierefreiheit@",
    "hinweisgeber@",
)

DEMOTED_DEPARTMENT_PREFIXES = (
    "partnerprogramm",
    "affiliate",
    "eshop",
    "onlineshop",
    "shop",
    "bestellung",
    "rechnung",
    "buchhaltung",
    "mahnung",
    "presse",
    "pr",
    "beschwerde",
    "reklamation",
    "kundenservice",
    "support",
)

JUNK_EMAIL_SUBSTRINGS = (
    "example.",
    "sentry.",
    "wix.",
    "wixpress.",
)

ASSET_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")

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
        """Discover Impressum URLs (and secondary Kontakt/Karriere links) from page HTML and fallback routes."""
        discovered: List[str] = []
        contact_fallbacks: List[str] = []
        seen: Set[str] = set()
        base_netloc = urlparse(base_url).netloc.lower()

        if html_content:
            try:
                soup = BeautifulSoup(html_content, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = (a_tag.get("href") or "").strip()
                    text = a_tag.get_text(" ", strip=True) or ""
                    if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                        continue

                    full_url = urljoin(base_url, href)
                    if urlparse(full_url).netloc.lower() != base_netloc:
                        continue

                    if any(p.search(href) or p.search(text) for p in IMPRESSUM_URL_PATTERNS):
                        if full_url not in seen:
                            seen.add(full_url)
                            discovered.append(full_url)
                    elif any(p.search(href) or p.search(text) for p in KONTAKT_URL_PATTERNS):
                        if full_url not in seen and full_url not in contact_fallbacks:
                            contact_fallbacks.append(full_url)
            except Exception as exc:
                logger.debug("Failed parsing links for impressum: %s", exc)

        for cf in contact_fallbacks:
            if cf not in seen:
                seen.add(cf)
                discovered.append(cf)

        common_paths = ["/impressum", "/impressum/", "/impressum.html", "/de/impressum", "/imprint", "/kontakt", "/karriere"]
        for path in common_paths:
            fallback_url = urljoin(base_url, path)
            if fallback_url not in seen:
                seen.add(fallback_url)
                discovered.append(fallback_url)

        return discovered

    @staticmethod
    def _is_usable_email(email: str) -> bool:
        e = str(email or "").strip().lower()
        if not e or "@" not in e:
            return False
        local = e.split("@")[0]
        if "widerruf" in local:
            return False
        if e.endswith(ASSET_EMAIL_SUFFIXES):
            return False
        if e.startswith(NON_APPLICATION_EMAIL_PREFIXES):
            return False
        if any(sub in e for sub in JUNK_EMAIL_SUBSTRINGS):
            return False
        return True

    @staticmethod
    def _rank_emails(emails: Set[str], source_url: str = "") -> List[str]:
        """Rank usable emails: HR/recruitment first, then general business, then others, demoting non-HR departments."""
        site_host = urlparse(source_url).netloc.lower().lstrip("www.") if source_url else ""

        def _score(em: str):
            local, _, dom = em.partition("@")
            domain_match = 0 if (site_host and (dom == site_host or site_host.endswith("." + dom) or dom.endswith("." + site_host))) else 1
            if any(local == d or local.startswith(d + "-") or local.startswith(d + ".") for d in DEMOTED_DEPARTMENT_PREFIXES):
                tier = 3
            elif any(k in local for k in ("bewerbung", "ausbildung", "karriere", "personal", "recruiting", "jobs", "hr")):
                tier = 0
            elif any(k in local for k in ("info", "kontakt", "zentrale", "office", "verwaltung", "service", "mail")):
                tier = 1
            else:
                tier = 2
            return (domain_match, tier, em)

        return sorted(emails, key=_score)

    def extract_from_html(self, html_content: str, source_url: str = "") -> Dict:
        """Parse Impressum HTML to extract directors, emails, phone numbers, and salutation."""
        result = {
            "geschaeftsfuehrer": "",
            "geschaeftsfuehrer_liste": [],
            "salutation": "Sehr geehrte Damen und Herren,",
            "emails": [],
            "primary_email": "",
            "phone": "",
            "telephones": [],
            "source_url": source_url,
        }

        if not html_content:
            return result

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Extract emails (mailto, TYPO3 data-mailto-token, Cloudflare data-cfemail, (at) obfuscation, and plain text)
        emails: Set[str] = set()
        try:
            from services.application_url_validator import extract_all_emails_including_obfuscated
            for obf_e in extract_all_emails_including_obfuscated(html_content):
                clean = str(obf_e).strip().strip(".,;:").lower()
                if self._is_usable_email(clean):
                    emails.add(clean)
        except Exception:
            pass

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if href.startswith("mailto:"):
                clean = href.replace("mailto:", "").split("?")[0].strip().strip(".,;:").lower()
                if self._is_usable_email(clean):
                    emails.add(clean)

        raw_text = soup.get_text(separator=" ")
        for match in EMAIL_REGEX.findall(raw_text):
            clean = match.strip().strip(".,;:").lower()
            if self._is_usable_email(clean):
                emails.add(clean)

        ranked_emails = self._rank_emails(emails, source_url=source_url)
        result["emails"] = ranked_emails
        if ranked_emails:
            result["primary_email"] = ranked_emails[0]

        # 2. Extract phone numbers
        phone_matches = PHONE_REGEX.findall(raw_text)
        if phone_matches:
            cleaned_phone = re.sub(r"\s+", " ", phone_matches[0]).strip()
            result["phone"] = cleaned_phone
            result["telephones"] = [cleaned_phone]

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
        """Attempt to fetch and parse the website's Impressum / Kontakt pages (bounded to max 5 HTTP fetches)."""
        if not base_url:
            return self.extract_from_html("")

        effective_base = base_url
        effective_home_html = homepage_html or ""

        if not effective_home_html:
            try:
                from .rate_limiter import safe_http_get
                home_resp = safe_http_get(self.session, base_url, timeout=min(self.timeout, 6))
                if home_resp is not None and home_resp.status_code == 200 and home_resp.text:
                    effective_home_html = home_resp.text
                    effective_base = getattr(home_resp, "url", None) or base_url
            except Exception as exc:
                logger.debug("Failed fetching homepage %s for impressum discovery: %s", base_url, exc)

        home_parsed = self.extract_from_html(effective_home_html, source_url=effective_base) if effective_home_html else None

        candidate_urls = self.find_impressum_urls(effective_base, effective_home_html)
        best_partial: Optional[Dict] = None
        for url in candidate_urls[:5]:
            try:
                from .rate_limiter import safe_http_get
                resp = safe_http_get(self.session, url, timeout=min(self.timeout, 6))
                if resp is not None and resp.status_code == 200 and resp.text:
                    parsed = self.extract_from_html(resp.text, source_url=getattr(resp, "url", None) or url)
                    if parsed.get("primary_email"):
                        if not parsed.get("geschaeftsfuehrer") and home_parsed and home_parsed.get("geschaeftsfuehrer"):
                            parsed["geschaeftsfuehrer"] = home_parsed["geschaeftsfuehrer"]
                        return parsed
                    if (parsed.get("geschaeftsfuehrer") or parsed.get("phone")) and not best_partial:
                        best_partial = parsed
            except Exception as exc:
                logger.debug("Failed requesting impressum %s: %s", url, exc)

        if home_parsed and (home_parsed.get("primary_email") or home_parsed.get("geschaeftsfuehrer") or home_parsed.get("phone")):
            if best_partial and not home_parsed.get("geschaeftsfuehrer") and best_partial.get("geschaeftsfuehrer"):
                home_parsed["geschaeftsfuehrer"] = best_partial["geschaeftsfuehrer"]
            return home_parsed

        return best_partial or self.extract_from_html("")

# Backward compatibility alias
ImpressumExtractor.extract_from_url = ImpressumExtractor.extract_from_website
