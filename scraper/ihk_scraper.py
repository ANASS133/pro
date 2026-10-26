import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import bs4
import requests

logger = logging.getLogger(__name__)


class IhkScraper:
    """
    Scraper for IHK Lehrstellenbörse (ihk-lehrstellenboerse.de / meine-ausbildung-in-deutschland.de)
    The official German Chamber of Commerce and Industry apprenticeship portal.
    """

    BASE_URL = "https://ihk-azubi-stellenmarkt.indexinternet.de/index.php"

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
                "Referer": "https://meine-ausbildung-in-deutschland.de/",
            }
        )

    def fetch_jobs(
        self,
        keyword: str = "",
        location: str = "",
        max_jobs: int = 40,
    ) -> List[Dict]:
        """
        Fetches apprenticeship positions from the official IHK Lehrstellenbörse.
        Supports pagination via parameter page.
        """
        all_jobs: List[Dict] = []
        seen_refs = set()
        page = 1
        search_kw = str(keyword or "").strip()
        search_loc = str(location or "").strip()

        logger.info(
            "IHK fetch start: keyword='%s', location='%s', max_jobs=%s",
            search_kw,
            search_loc,
            max_jobs,
        )

        while len(all_jobs) < max_jobs:
            params = {
                "page": page,
                "jobs": search_kw,
                "action": "search",
            }
            if search_loc:
                params["geopost_new"] = search_loc

            try:
                logger.info("Fetching IHK Lehrstellenbörse page %s", page)
                resp = self.session.get(self.BASE_URL, params=params, timeout=12)
                resp.encoding = "utf-8"
                if resp.status_code != 200:
                    logger.warning("IHK page %s returned status %s", page, resp.status_code)
                    break

                soup = bs4.BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("section", class_="job")

                if not cards:
                    logger.info("No more job cards found on IHK page %s", page)
                    break

                page_jobs = self._parse_cards(cards)
                new_jobs_count = 0

                for job in page_jobs:
                    ref = job.get("reference") or job.get("url")
                    if not ref or ref in seen_refs:
                        continue
                    seen_refs.add(ref)
                    all_jobs.append(job)
                    new_jobs_count += 1
                    if len(all_jobs) >= max_jobs:
                        break

                logger.info(
                    "IHK page %s: found %s cards, added %s new (total=%s)",
                    page,
                    len(cards),
                    new_jobs_count,
                    len(all_jobs),
                )

                if new_jobs_count == 0 or len(cards) < 5:
                    break

                page += 1
                time.sleep(0.3)

            except Exception as exc:
                logger.warning("Error fetching IHK page %s: %s", page, exc)
                break

        self.total_jobs_fetched = len(all_jobs)
        logger.info("IHK fetch complete. Total: %s", self.total_jobs_fetched)
        return all_jobs

    def _parse_cards(self, cards: List[bs4.Tag]) -> List[Dict]:
        """Parses IHK DOM sections into standard job dictionaries."""
        parsed: List[Dict] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for card in cards:
            try:
                # 1. Title & URL
                title_el = card.find("h3", class_="job_title") or card.find("h3")
                link_el = title_el.find("a", href=True) if title_el else card.find("a", href=True)

                title = title_el.get_text(strip=True) if title_el else "Ausbildungsplatz"
                relative_url = link_el["href"] if link_el else ""
                full_url = urllib.parse.urljoin("https://jobs.meine-ausbildung-in-deutschland.de", relative_url)

                # Reference
                ref = "N/A"
                if relative_url:
                    match_id = re.search(r"(?:anzeige|id)=(\d+)", relative_url, flags=re.I)
                    if match_id:
                        ref = f"ihk_{match_id.group(1)}"
                    else:
                        ref = f"ihk_{abs(hash(relative_url)) % 100000000}"
                else:
                    ref = f"ihk_{abs(hash(title)) % 100000000}"

                # 2. Company
                firma_el = card.find("p", class_="firma")
                company = firma_el.get_text(strip=True) if firma_el else "N/A"

                # 3. Location / Region
                region_el = card.find("p", class_="job-region")
                raw_loc = region_el.get_text(" ", strip=True) if region_el else "Deutschland"
                # Strip trailing country code if present e.g. "Abensberg DE" -> "Abensberg"
                loc_clean = re.sub(r"\s+DE$", "", raw_loc).strip()

                postal_code = "N/A"
                city = loc_clean
                plz_match = re.search(r"^(\d{5})\s+(.+)$", loc_clean)
                if plz_match:
                    postal_code = plz_match.group(1)
                    city = plz_match.group(2).strip()
                else:
                    city_candidate = re.sub(r"^Region\s+", "", loc_clean, flags=re.I).strip()
                    city_candidate = re.sub(r"\s*\([^)]*\)$", "", city_candidate).strip()
                    if city_candidate:
                        city = city_candidate

                parsed.append(
                    {
                        "title": title,
                        "company": company,
                        "location": loc_clean or city,
                        "city": city,
                        "postal_code": postal_code,
                        "reference": ref,
                        "job_type": "Ausbildung",
                        "published_date": now_str[:10],
                        "start_date": "nach Absprache",
                        "vacancies": "1 Platz",
                        "hauptberuf": title,
                        "url": full_url,
                        "source": "ihk.de",
                        "scraped_at": now_str,
                        "email_extracted": False,
                        "email": None,
                        "phone": None,
                    }
                )
            except Exception as exc:
                logger.debug("Failed parsing IHK card: %s", exc)

        return parsed
