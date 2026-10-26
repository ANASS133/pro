"""
Deep Career Page Crawler.
Finds dedicated company career and job subpages, extracts open job listings,
identifies dedicated HR/Bewerbung email addresses, and detects whether
unsolicited applications (Initiativbewerbungen) are welcomed.
"""

import logging
import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CAREER_KEYWORDS = [
    "karriere", "career", "jobs", "stellenangebote",
    "stellen", "wir-suchen", "offene-stellen", "vacancies",
    "arbeiten-bei-uns", "jobboerse"
]

INITIATIV_PATTERNS = [
    re.compile(r"initiativ(?:bewerbung)?", re.IGNORECASE),
    re.compile(r"keine\s+passende\s+stelle", re.IGNORECASE),
    re.compile(r"bewerben\s+sie\s+sich\s+initiativ", re.IGNORECASE),
    re.compile(r"spontanbewerbung", re.IGNORECASE),
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


class CareerPageCrawler:
    """Discovers and parses company career pages for jobs and HR contacts."""

    @classmethod
    def find_career_urls(cls, base_url: str, html_content: str) -> List[str]:
        """Discover links pointing to career/job pages from homepage HTML."""
        if not html_content or not base_url:
            return []

        discovered: List[str] = []
        seen: Set[str] = set()
        base_netloc = urlparse(base_url).netloc

        try:
            soup = BeautifulSoup(html_content, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                text = (a_tag.get_text() or "").strip().lower()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue

                href_lower = href.lower()
                is_match = any(kw in href_lower or kw in text for kw in CAREER_KEYWORDS)
                if is_match:
                    full_url = urljoin(base_url, href)
                    # Stay within same root domain
                    parsed = urlparse(full_url)
                    if parsed.netloc == base_netloc or parsed.netloc.endswith("." + base_netloc):
                        if full_url not in seen:
                            seen.add(full_url)
                            discovered.append(full_url)
        except Exception as exc:
            logger.debug("Failed parsing links for career URLs: %s", exc)

        # Standard conventional paths as fallbacks
        fallbacks = ["/karriere", "/karriere/", "/jobs", "/stellenangebote"]
        for p in fallbacks:
            fallback_url = urljoin(base_url, p)
            if fallback_url not in seen:
                seen.add(fallback_url)
                discovered.append(fallback_url)

        return discovered[:4]

    @classmethod
    def parse_career_page(cls, html_content: str, career_url: str = "") -> Dict:
        """
        Extract job listings, HR application emails, and check if
        unsolicited applications (Initiativbewerbung) are welcomed.
        """
        result = {
            "career_url": career_url,
            "jobs_found": [],
            "hr_emails": [],
            "initiativ_welcomed": False,
        }

        if not html_content:
            return result

        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=" ")

        # 1. Check for Initiativbewerbung
        for pat in INITIATIV_PATTERNS:
            if pat.search(text):
                result["initiativ_welcomed"] = True
                break

        # 2. Extract dedicated HR emails
        hr_emails: Set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if href.startswith("mailto:"):
                clean = href.replace("mailto:", "").split("?")[0].strip().lower()
                if clean:
                    hr_emails.add(clean)

        for match in EMAIL_PATTERN.findall(text):
            clean = match.strip().strip(".,;:").lower()
            if any(k in clean for k in ["bewerbung", "karriere", "jobs", "hr", "recruiting"]):
                hr_emails.add(clean)

        result["hr_emails"] = sorted(list(hr_emails))

        # 3. Detect job postings from headings or list elements
        detected_jobs: List[str] = []
        heading_tags = soup.find_all(["h2", "h3", "h4", "strong"])
        for h in heading_tags:
            h_text = re.sub(r"\s+", " ", h.get_text()).strip()
            # Match job-like titles (e.g. "Mitarbeiter im Vertrieb (m/w/d)", "Junior Webentwickler (w/m/d)")
            if re.search(r"\((?:m/w/d|w/m/d|d/m/w|gn)\)", h_text, re.IGNORECASE) or (
                10 < len(h_text) < 70 and any(kw in h_text.lower() for kw in ["entwickler", "mechaniker", "assistent", "kaufmann", "leitung", "manager"])
            ):
                if h_text not in detected_jobs:
                    detected_jobs.append(h_text)
                    if len(detected_jobs) >= 10:
                        break

        result["jobs_found"] = detected_jobs
        return result
