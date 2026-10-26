import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import bs4
import requests

logger = logging.getLogger(__name__)


class AusbildungDeScraper:
    """
    Scraper for Ausbildung.de - Germany's leading apprenticeship and training portal.
    Extracts vacancies, company names, cities, start dates, and direct application links.
    """

    BASE_URL = "https://www.ausbildung.de/suche/"

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
                "Referer": "https://www.ausbildung.de/",
            }
        )

    def fetch_jobs(
        self,
        keyword: str,
        location: str = "",
        max_jobs: int = 60,
        published_since_days: Optional[int] = None,
    ) -> List[Dict]:
        """
        Fetches apprenticeship positions from ausbildung.de.
        Supports pagination up to max_jobs.
        """
        all_jobs: List[Dict] = []
        seen_refs = set()
        page = 1
        size_per_page = 20

        search_keyword = str(keyword or "").strip()
        search_location = str(location or "").strip()

        logger.info(
            "Ausbildung.de fetch start: what='%s' where='%s' max_jobs=%s",
            search_keyword,
            search_location,
            max_jobs,
        )

        while len(all_jobs) < max_jobs:
            # Ausbildung.de uses 'search' as the primary keyword search parameter
            query_parts = []
            if search_keyword:
                query_parts.append(search_keyword)
            if search_location:
                query_parts.append(search_location)
            combined_query = " ".join(query_parts)

            params = {
                "search": combined_query if combined_query else search_keyword,
                "page": page,
            }

            try:
                logger.info("Fetching ausbildung.de page %s with params %s", page, params)
                resp = self.session.get(self.BASE_URL, params=params, timeout=15)
                resp.encoding = "utf-8"
                if resp.status_code != 200:
                    logger.warning("Ausbildung.de page %s returned status %s", page, resp.status_code)
                    break

                soup = bs4.BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("article", attrs={"data-testid": "jp-card"})
                if not cards:
                    # Fallback selector if class names change
                    cards = soup.find_all("article", class_=re.compile(r"cardWrapper|jobPosting", re.I))

                if not cards:
                    logger.info("No more job cards found on page %s", page)
                    break

                page_jobs = self._parse_cards(cards)
                new_jobs_count = 0

                for job in page_jobs:
                    ref = job.get("reference") or job.get("url")
                    if ref in seen_refs:
                        continue
                    seen_refs.add(ref)
                    all_jobs.append(job)
                    new_jobs_count += 1
                    if len(all_jobs) >= max_jobs:
                        break


                logger.info(
                    "Page %s -> found %s cards, added %s new (total=%s)",
                    page,
                    len(cards),
                    new_jobs_count,
                    len(all_jobs),
                )

                if len(cards) < size_per_page or new_jobs_count == 0:
                    logger.info("Reached end of ausbildung.de results")
                    break

                page += 1
                time.sleep(0.3)

            except Exception as exc:
                logger.error("Error fetching ausbildung.de page %s: %s", page, exc)
                break

        self.total_jobs_fetched = len(all_jobs)
        logger.info("Ausbildung.de fetch completed. Total jobs: %s", self.total_jobs_fetched)
        return all_jobs

    def _parse_cards(self, cards: List[bs4.Tag]) -> List[Dict]:
        """Parses job article tags into standardized dictionary objects."""
        parsed: List[Dict] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for card in cards:
            try:
                # 1. Title
                title_el = (
                    card.find(attrs={"data-testid": "jp-title"})
                    or card.find("h3")
                )
                title = title_el.get_text(strip=True) if title_el else "Ausbildungsplatz"

                # 2. Company
                comp_el = (
                    card.find(attrs={"data-testid": "jp-customer"})
                    or card.find("h4")
                )
                company = "N/A"
                if comp_el:
                    company = comp_el.get_text(" ", strip=True)
                    company = re.sub(r"^bei\s+", "", company, flags=re.I).strip()

                # 3. Location / Branches
                loc_el = card.find(attrs={"data-testid": "jp-branches"})
                raw_loc = loc_el.get_text(" ", strip=True) if loc_el else "Deutschland"
                # Clean up e.g. "06108 Halle (Saale) + 1332 weitere"
                loc_clean = re.sub(r"\+\s*\d+\s*weitere.*", "", raw_loc).strip()
                postal_code = "N/A"
                city = loc_clean

                match_plz = re.match(r"^(\d{5})\s+(.+)$", loc_clean)
                if match_plz:
                    postal_code = match_plz.group(1)
                    city = match_plz.group(2).strip()

                # 4. Starting Date
                start_el = card.find(attrs={"data-testid": "jp-starting-at"})
                start_date = start_el.get_text(strip=True) if start_el else "nach Absprache"

                # 5. Vacancies
                vac_el = card.find(attrs={"data-testid": "jp-vacancies"})
                vacancies = vac_el.get_text(strip=True) if vac_el else "1 Platz"

                # 6. URL & Reference
                link_el = card.find("a", href=True)
                relative_url = link_el["href"] if link_el else ""
                full_url = urllib.parse.urljoin("https://www.ausbildung.de", relative_url)

                # Generate reference ID from slug or URL
                ref = "N/A"
                if relative_url:
                    slug_match = re.search(r"stellen/([^/]+)/?", relative_url)
                    if slug_match:
                        ref = f"ausbildung_de_{slug_match.group(1)[:80]}"
                    else:
                        ref = f"ausbildung_de_{abs(hash(relative_url)) % 100000000}"

                from .search_filter_engine import clean_extracted_location
                loc_meta = clean_extracted_location(loc_clean, city)

                parsed.append(
                    {
                        "title": title,
                        "company": company,
                        "location": loc_meta["location"],
                        "city": loc_meta["city"],
                        "postal_code": loc_meta["postal_code"] if loc_meta["postal_code"] != "N/A" else postal_code,
                        "reference": ref,
                        "job_type": "Ausbildung",
                        "published_date": "k. A.",
                        "start_date": start_date,
                        "vacancies": vacancies,
                        "hauptberuf": title,
                        "url": full_url,
                        "source": "ausbildung.de",
                        "scraped_at": now_str,
                        "email_extracted": False,
                        "email": None,
                        "phone": None,
                    }
                )
            except Exception as exc:
                logger.debug("Failed parsing card: %s", exc)

        return parsed
