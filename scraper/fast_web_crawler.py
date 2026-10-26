"""
Fast Web Crawler for Company Websites.
Performs high-speed, concurrent HTTP extraction of emails, phone numbers,
Impressum legal data, tech-stack detection, and career pages without Selenium overhead.
"""

import concurrent.futures
import logging
import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .career_crawler import CareerPageCrawler
from .impressum_extractor import ImpressumExtractor
from .tech_detector import TechDetector

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

EXCLUDED_DOMAINS = {
    "example.com", "example.org", "sentry.io", "wix.com",
    "squarespace.com", "wordpress.com", "schema.org",
    "google.com", "googleapis.com", "facebook.com", "instagram.com"
}

EXCLUDED_PREFIXES = {
    "noreply", "no-reply", "donotreply", "mailer-daemon",
    "postmaster", "hostmaster", "webmaster", "abuse"
}

CONTACT_KEYWORDS = [
    "kontakt", "contact", "impressum", "imprint",
    "ueber-uns", "about", "team", "ansprechpartner", "karriere", "jobs"
]


class FastWebCrawler:
    """Lightweight and fast HTTP website scraper for contact, tech-stack, and career discovery."""

    def __init__(self, max_pages: int = 5, timeout: int = 10, max_threads: int = 4):
        self.max_pages = max_pages
        self.timeout = timeout
        self.max_threads = max_threads
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
        })
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session.verify = False

        self.impressum_extractor = ImpressumExtractor(session=self.session, timeout=self.timeout)

    def _normalize_email(self, email: str) -> str:
        return str(email or "").strip().strip(".,;:\"'<>()[]").lower()

    def _is_valid_email(self, email: str) -> bool:
        norm = self._normalize_email(email)
        if not norm or "@" not in norm:
            return False
        local, domain = norm.split("@", 1)
        if domain in EXCLUDED_DOMAINS:
            return False
        if local in EXCLUDED_PREFIXES or any(norm.startswith(p + "@") for p in EXCLUDED_PREFIXES):
            return False
        if norm.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")):
            return False
        return True

    def _extract_emails_from_html(self, html: str) -> Set[str]:
        if not html:
            return set()
        emails = set()
        try:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if href.startswith("mailto:"):
                    clean = href.replace("mailto:", "").split("?")[0].strip()
                    norm = self._normalize_email(clean)
                    if self._is_valid_email(norm):
                        emails.add(norm)
            text = soup.get_text(separator=" ")
            for match in EMAIL_PATTERN.findall(text):
                norm = self._normalize_email(match)
                if self._is_valid_email(norm):
                    emails.add(norm)
        except Exception:
            pass
        return emails

    def _find_candidate_links(self, base_url: str, html: str) -> List[str]:
        if not html:
            return []
        discovered = []
        seen = {base_url}
        try:
            soup = BeautifulSoup(html, "html.parser")
            base_netloc = urlparse(base_url).netloc
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)
                if parsed.netloc != base_netloc:
                    continue
                path_lower = parsed.path.lower()
                text_lower = (a.get_text() or "").lower()
                if any(kw in path_lower or kw in text_lower for kw in CONTACT_KEYWORDS):
                    if full_url not in seen:
                        seen.add(full_url)
                        discovered.append(full_url)
                        if len(discovered) >= self.max_pages:
                            break
        except Exception:
            pass
        return discovered

    def _fetch_url(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200 and resp.text:
                return resp.text
        except Exception:
            pass
        return None

    def crawl_website(self, website_url: str) -> Dict:
        """
        Crawl homepage, contact, impressum, and career pages to extract emails,
        phone, managing directors, tech-stack, and open vacancies.
        """
        result = {
            "website": website_url,
            "emails": [],
            "primary_email": "",
            "phone": "",
            "geschaeftsfuehrer": "",
            "salutation": "Sehr geehrte Damen und Herren,",
            "technologies": [],
            "primary_tech": "",
            "open_jobs": [],
            "initiativ_welcomed": False,
            "source_pages": [],
        }

        if not website_url:
            return result

        normalized_url = website_url
        if not normalized_url.startswith(("http://", "https://")):
            normalized_url = "https://" + normalized_url

        # 1. Fetch homepage
        homepage_html = self._fetch_url(normalized_url)
        if not homepage_html and normalized_url.startswith("https://"):
            normalized_url = "http://" + normalized_url[8:]
            homepage_html = self._fetch_url(normalized_url)

        if not homepage_html:
            return result

        result["source_pages"].append(normalized_url)
        all_emails: Set[str] = self._extract_emails_from_html(homepage_html)

        # 2. Detect Tech Stack
        tech_info = TechDetector.detect(homepage_html)
        result["technologies"] = tech_info.get("technologies", [])
        result["primary_tech"] = tech_info.get("primary_tech", "")

        # 3. Extract Impressum
        impressum_data = self.impressum_extractor.extract_from_website(normalized_url, homepage_html)
        if impressum_data.get("primary_email"):
            all_emails.add(impressum_data["primary_email"])
        for em in impressum_data.get("emails", []):
            all_emails.add(em)
        if impressum_data.get("phone"):
            result["phone"] = impressum_data["phone"]
        if impressum_data.get("geschaeftsfuehrer"):
            result["geschaeftsfuehrer"] = impressum_data["geschaeftsfuehrer"]
            result["salutation"] = impressum_data["salutation"]

        # 4. Discover Career Pages
        career_urls = CareerPageCrawler.find_career_urls(normalized_url, homepage_html)
        for c_url in career_urls[:2]:
            c_html = self._fetch_url(c_url)
            if c_html:
                result["source_pages"].append(c_url)
                c_data = CareerPageCrawler.parse_career_page(c_html, career_url=c_url)
                for hr_em in c_data.get("hr_emails", []):
                    all_emails.add(hr_em)
                if c_data.get("jobs_found"):
                    result["open_jobs"].extend(c_data["jobs_found"])
                if c_data.get("initiativ_welcomed"):
                    result["initiativ_welcomed"] = True

        # 5. Find other contact pages and fetch concurrently
        candidate_links = self._find_candidate_links(normalized_url, homepage_html)
        remaining_links = [l for l in candidate_links if l not in result["source_pages"]][:self.max_pages]
        if remaining_links:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_threads, len(remaining_links))) as executor:
                future_to_url = {executor.submit(self._fetch_url, url): url for url in remaining_links}
                for future in concurrent.futures.as_completed(future_to_url):
                    link_url = future_to_url[future]
                    html = future.result()
                    if html:
                        result["source_pages"].append(link_url)
                        for em in self._extract_emails_from_html(html):
                            all_emails.add(em)

        clean_emails = sorted(list(all_emails))
        result["emails"] = clean_emails
        if clean_emails:
            chosen = clean_emails[0]
            # Prioritize dedicated recruiting / application emails
            for em in clean_emails:
                if any(k in em for k in ["bewerbung", "karriere", "jobs", "recruiting"]):
                    chosen = em
                    break
            result["primary_email"] = chosen

        return result
