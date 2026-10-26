import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

import bs4
import requests

logger = logging.getLogger(__name__)


class AubiPlusScraper:
    """
    Scraper for AUBI-plus (aubi-plus.de) - Germany's premier vocational training
    and dual study directory with nationwide coverage.
    """

    BASE_URL = "https://www.aubi-plus.de/suchmaschine/suche/"

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
                "Referer": "https://www.aubi-plus.de/suchmaschine/",
            }
        )

    def fetch_jobs(
        self,
        keyword: str = "",
        location: str = "",
        max_jobs: int = 40,
    ) -> List[Dict]:
        """
        Fetches apprenticeship positions from AUBI-plus.
        Supports pagination via parameter p.
        """
        all_jobs: List[Dict] = []
        seen_refs = set()
        page = 1
        search_kw = str(keyword or "").strip()
        search_loc = str(location or "").strip()

        logger.info(
            "AUBI-plus fetch start: keyword='%s', location='%s', max_jobs=%s",
            search_kw,
            search_loc,
            max_jobs,
        )

        while len(all_jobs) < max_jobs:
            params = {
                "mSuggest": search_kw,
                "p": page,
            }
            if search_loc:
                params["aSuggest"] = search_loc

            try:
                logger.info("Fetching AUBI-plus page %s", page)
                resp = self.session.get(self.BASE_URL, params=params, timeout=12)
                resp.encoding = "utf-8"
                if resp.status_code != 200:
                    logger.warning("AUBI-plus page %s returned status %s", page, resp.status_code)
                    break

                soup = bs4.BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all(
                    "div",
                    class_=lambda c: c and "bg-white" in c and "position-relative" in c and "p-4" in c,
                )

                if not cards:
                    logger.info("No more cards found on AUBI-plus page %s", page)
                    break

                page_jobs = self._parse_cards(cards, search_keyword=search_kw)
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
                    "AUBI-plus page %s: found %s cards, added %s new (total=%s)",
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
                logger.warning("Error fetching AUBI-plus page %s: %s", page, exc)
                break

        self.total_jobs_fetched = len(all_jobs)
        logger.info("AUBI-plus fetch complete. Total: %s", self.total_jobs_fetched)
        return all_jobs

    def _parse_cards(self, cards: List[bs4.Tag], search_keyword: str = "") -> List[Dict]:
        """Parses AUBI-plus DOM cards into standard job dictionaries."""
        parsed: List[Dict] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for card in cards:
            try:
                # 1. Title
                h2 = card.find("h2")
                title = h2.get_text(strip=True) if h2 else "Ausbildungsplatz"

                # 2. Company
                company = "N/A"
                comp_link = card.find("a", href=lambda h: h and "/premium/" in h)
                if comp_link and comp_link.get_text(strip=True):
                    company = comp_link.get_text(strip=True)
                else:
                    logo_img = card.find("img", alt=re.compile(r"^Logo\s+", re.I))
                    if logo_img and logo_img.get("alt"):
                        company = re.sub(r"^Logo\s+", "", logo_img["alt"], flags=re.I).strip()

                # Fallback company from text lines
                strings = list(card.stripped_strings)
                if company == "N/A" and len(strings) >= 3:
                    for s in strings:
                        if s != title and s not in {"Top-Ausbilder", "Ausbildung", "Start"} and not re.search(r"^\d{5}", s) and not re.search(r"\d{2}\.\d{2}\.\d{4}", s):
                            company = s
                            break

                # 3. URL & Reference
                link_el = card.find("a", href=lambda h: h and ("/ausbildung/" in h or "/duales-studium/" in h))
                relative_url = link_el["href"] if link_el else ""
                full_url = urllib.parse.urljoin("https://www.aubi-plus.de", relative_url)

                slug_match = re.search(r"/ausbildung/([^/]+)/?", relative_url)
                if slug_match:
                    ref = f"aubi_plus_{slug_match.group(1)[:80]}"
                elif relative_url:
                    ref = f"aubi_plus_{abs(hash(relative_url)) % 100000000}"
                else:
                    ref = f"aubi_plus_{abs(hash(title + company)) % 100000000}"

                # 4. Location and Start date from card strings
                postal_code = "N/A"
                city = "Deutschland"
                location = "Deutschland"
                start_date = "nach Absprache"

                for s in strings:
                    # Location e.g. "50668 Köln"
                    plz_match = re.search(r"^(\d{5})\s+(.+)$", s)
                    if plz_match:
                        postal_code = plz_match.group(1)
                        city = plz_match.group(2).strip()
                        location = f"{postal_code} {city}"
                    # Start date e.g. "01.09.2027" or "Start: 01.09.2027" or "Ab sofort"
                    elif re.search(r"\d{2}\.\d{2}\.\d{4}", s):
                        d_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", s)
                        start_date = d_m.group(1) if d_m else s
                    elif s.lower().startswith("ab sofort"):
                        start_date = "Ab sofort"

                from .search_filter_engine import clean_extracted_location
                loc_meta = clean_extracted_location(location, city)

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
                        "vacancies": "1 Platz",
                        "hauptberuf": title,
                        "url": full_url,
                        "source": "aubi-plus.de",
                        "scraped_at": now_str,
                        "email_extracted": False,
                        "email": None,
                        "phone": None,
                    }
                )
            except Exception as exc:
                logger.debug("Failed parsing AUBI-plus card: %s", exc)

        return parsed
