import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import bs4
import requests

logger = logging.getLogger(__name__)


def slugify_german(text: str) -> str:
    """Converts German text into clean URL slugs with umlaut handling."""
    if not text:
        return ""
    s = str(text).lower().strip()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


class AzubiyoScraper:
    """
    Scraper for Azubiyo.de - one of Germany's top apprenticeship and dual study portals.
    Supports semantic slug resolution, card parsing, salary detection, and deduplication.
    """

    BASE_URL = "https://www.azubiyo.de/ausbildung/"

    # Common German profession shortcuts mapped to Azubiyo slugs
    PROFESSION_SLUG_MAP = {
        "informatik": "fachinformatiker-anwendungsentwicklung",
        "fachinformatiker": "fachinformatiker-anwendungsentwicklung",
        "fachinformatiker anwendungsentwicklung": "fachinformatiker-anwendungsentwicklung",
        "fachinformatiker systemintegration": "fachinformatiker-systemintegration",
        "softwareentwickler": "fachinformatiker-anwendungsentwicklung",
        "it": "fachinformatiker-anwendungsentwicklung",
        "e-commerce": "kaufmann-e-commerce",
        "kaufmann im e-commerce": "kaufmann-e-commerce",
        "einzelhandel": "kaufmann-einzelhandel",
        "bueromanagement": "kaufmann-bueromanagement",
        "buero": "kaufmann-bueromanagement",
        "bankkaufmann": "bankkaufmann",
        "industriekaufmann": "industriekaufmann",
        "marketing": "kaufmann-marketingkommunikation",
        "pflege": "pflegefachmann",
        "krankenpflege": "pflegefachmann",
        "mechatroniker": "mechatroniker",
        "kfz": "kfz-mechatroniker",
        "logistik": "fachkraft-lagerlogistik",
    }

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.setup_headers()
        self.total_jobs_fetched = 0

    def setup_headers(self):
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
                "Referer": "https://www.azubiyo.de/",
            }
        )

    def _resolve_profession_slug(self, keyword: str) -> str:
        """Resolves free-form keyword into best Azubiyo profession slug."""
        clean = keyword.lower().strip()
        if clean in self.PROFESSION_SLUG_MAP:
            return self.PROFESSION_SLUG_MAP[clean]
        for key, slug in self.PROFESSION_SLUG_MAP.items():
            if key in clean or clean in key:
                return slug
        return slugify_german(keyword)

    def build_candidate_urls(self, keyword: str, location: str) -> List[str]:
        """Builds prioritized list of URL candidates for Azubiyo search."""
        kw_slug = self._resolve_profession_slug(keyword) if keyword else ""
        loc_slug = slugify_german(location) if location else ""

        urls = []

        # 1. Location + Profession
        if loc_slug and kw_slug:
            urls.append(f"https://www.azubiyo.de/ausbildung/{loc_slug}/{kw_slug}/")
            urls.append(f"https://www.azubiyo.de/ausbildung/{kw_slug}/{loc_slug}/")

        # 2. Location only
        if loc_slug:
            urls.append(f"https://www.azubiyo.de/ausbildung/{loc_slug}/")

        # 3. Profession only
        if kw_slug:
            urls.append(f"https://www.azubiyo.de/ausbildung/{kw_slug}/")

        # 4. Fallback: general current vacancies
        urls.append("https://www.azubiyo.de/ausbildung/aktuelle-ausbildungsplaetze/")

        return urls

    def fetch_jobs(
        self,
        keyword: str = "",
        location: str = "",
        max_jobs: int = 60,
    ) -> List[Dict]:
        """
        Fetches apprenticeship positions from Azubiyo.de.
        Extracts titles, companies, locations, start dates, salaries, and application links.
        """
        candidate_urls = self.build_candidate_urls(keyword, location)
        all_jobs: List[Dict] = []
        seen_refs = set()

        search_kw = str(keyword or "").strip().lower()
        search_loc = str(location or "").strip().lower()

        logger.info(
            "Azubiyo fetch start: keyword='%s', location='%s', max_jobs=%s",
            keyword,
            location,
            max_jobs,
        )

        for target_url in candidate_urls:
            if len(all_jobs) >= max_jobs:
                break

            try:
                logger.info("Trying Azubiyo URL: %s", target_url)
                resp = self.session.get(target_url, timeout=12)
                resp.encoding = "utf-8"

                if resp.status_code != 200:
                    logger.debug("Azubiyo URL %s returned HTTP %s", target_url, resp.status_code)
                    continue

                soup = bs4.BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("div", class_=lambda c: c and "job-offer-teaser" in c)
                if not cards:
                    # Alternative selector if class names vary
                    cards = soup.find_all(
                        "div",
                        class_=lambda c: c and ("card" in c and any("job" in x.lower() for x in c)),
                    )

                if not cards:
                    continue

                page_jobs = self._parse_cards(cards)

                # Filter and deduplicate
                for job in page_jobs:
                    ref = job.get("reference") or job.get("url")
                    if not ref or ref in seen_refs:
                        continue

                    # If we used a broad fallback URL, apply gentle keyword/location matching
                    if search_kw and target_url.endswith("/aktuelle-ausbildungsplaetze/"):
                        title_lower = job.get("title", "").lower()
                        if not any(w in title_lower for w in search_kw.split()):
                            continue

                    seen_refs.add(ref)
                    all_jobs.append(job)
                    if len(all_jobs) >= max_jobs:
                        break

                logger.info("Found %s total valid jobs from %s", len(all_jobs), target_url)

                # If primary specific URL succeeded with good results, we don't need fallback
                if len(all_jobs) > 0 and not target_url.endswith("/aktuelle-ausbildungsplaetze/"):
                    break

            except Exception as exc:
                logger.warning("Error querying Azubiyo URL %s: %s", target_url, exc)
                continue

        self.total_jobs_fetched = len(all_jobs)
        logger.info("Azubiyo fetch completed. Total jobs: %s", self.total_jobs_fetched)
        return all_jobs

    def _parse_cards(self, cards: List[bs4.Tag]) -> List[Dict]:
        """Parses Azubiyo job card DOM tags into standard job dictionaries."""
        parsed: List[Dict] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for card in cards:
            try:
                # 1. Title
                title_el = (
                    card.find("span", class_=lambda cl: cl and "h3" in cl)
                    or card.find("h3")
                    or card.find("a", class_=lambda cl: cl and "text-decoration-none" in cl)
                )
                title = title_el.get_text(strip=True) if title_el else "Ausbildungsplatz"

                # 2. Company
                comp_el = card.find("span", class_=lambda cl: cl and "text-secondary" in cl)
                company = comp_el.get_text(strip=True) if comp_el else "N/A"

                # 3. URL & Reference
                link_el = card.find("a", href=True)
                relative_url = link_el["href"] if link_el else ""
                full_url = urllib.parse.urljoin("https://www.azubiyo.de", relative_url)

                slug_match = re.search(r"/stellenanzeigen/([^/]+)/?", relative_url)
                if slug_match:
                    ref = f"azubiyo_{slug_match.group(1)[:80]}"
                elif relative_url:
                    ref = f"azubiyo_{abs(hash(relative_url)) % 100000000}"
                else:
                    ref = f"azubiyo_{abs(hash(title + company)) % 100000000}"

                # 4. Details list (Start date, location, salary)
                ul = card.find("ul")
                start_date = "nach Absprache"
                location = "Deutschland"
                city = "Deutschland"
                postal_code = "N/A"
                salary = None

                if ul:
                    for li in ul.find_all("li"):
                        txt = li.get_text(" ", strip=True)
                        if not txt:
                            continue
                        # Date check: e.g. 01.08.2025
                        if re.search(r"\d{2}\.\d{2}\.\d{4}", txt):
                            start_date = txt
                        # Salary check: e.g. 1.250 € pro Monat
                        elif any(s in txt for s in ["€", "EUR", "pro Monat", "Vergütung"]):
                            salary = txt
                        # Location check
                        elif len(txt) > 2:
                            clean_loc = re.sub(r"\(u\.a\.\)", "", txt).strip()
                            plz_match = re.search(r"(\d{5})\s+(.+)", clean_loc)
                            if plz_match:
                                postal_code = plz_match.group(1)
                                city = plz_match.group(2).strip()
                                location = f"{postal_code} {city}"
                            else:
                                location = clean_loc
                                if "standort" not in clean_loc.lower():
                                    city = clean_loc

                parsed.append(
                    {
                        "title": title,
                        "company": company,
                        "location": location,
                        "city": city,
                        "postal_code": postal_code,
                        "reference": ref,
                        "job_type": "Ausbildung",
                        "published_date": now_str[:10],
                        "start_date": start_date,
                        "vacancies": "1 Platz",
                        "salary": salary,
                        "hauptberuf": title,
                        "url": full_url,
                        "source": "azubiyo.de",
                        "scraped_at": now_str,
                        "email_extracted": False,
                        "email": None,
                        "phone": None,
                    }
                )
            except Exception as exc:
                logger.debug("Failed parsing Azubiyo card: %s", exc)

        return parsed
