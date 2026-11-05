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
        self.last_search_meta = {
            "original_location": "",
            "normalized_location": "",
            "fallback_triggered": False,
            "fallback_results": 0,
            "rejected_by_location": 0,
            "final_accepted_results": 0,
        }

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
        Fetches apprenticeship positions from AUBI-plus with strict location filtering
        and controlled nationwide discovery fallback.
        """
        search_kw = str(keyword or "").strip()
        search_loc = str(location or "").strip()

        # 1. Normalize: strip stop-word prefixes ("Ausbildung als", "Ausbildung zum/zur", etc.)
        # AUBI-plus mSuggest uses literal matching and positions never start with "Ausbildung als"
        clean_kw = re.sub(
            r"^(?:ausbildung\s+(?:als\s+|zum\s+|zur\s+|f[üu]r\s+)?|lehre\s+als\s+|duales\s+studium\s+(?:in\s+|f[üu]r\s+)?)\s*",
            "",
            search_kw,
            flags=re.IGNORECASE,
        ).strip()
        if not clean_kw:
            clean_kw = search_kw

        # 2. Normalize generic locations to empty string (AUBI-plus treats non-city names as literal 0-match queries)
        clean_loc = search_loc
        if clean_loc.lower() in {
            "bundesweit",
            "deutschlandweit",
            "ganz deutschland",
            "deutschland",
            "alle",
            "all",
            "remote",
            "germany",
            "homeoffice",
            "überall",
            "uberall",
        }:
            clean_loc = ""

        is_nationwide = not clean_loc
        fallback_triggered = False
        fallback_results_count = 0
        rejected_by_location_count = 0

        logger.info(
            "AUBI-plus fetch start: original_location='%s', normalized_location='%s', "
            "keyword='%s' (clean='%s'), max_jobs=%s",
            search_loc,
            clean_loc,
            search_kw,
            clean_kw,
            max_jobs,
        )

        # 3. Initial Search (with aSuggest if location provided, or nationwide if empty)
        initial_jobs = self._fetch_pages(clean_kw, clean_loc, max_jobs)

        accepted_jobs: List[Dict] = []
        if is_nationwide:
            accepted_jobs = list(initial_jobs)
        else:
            for job in initial_jobs:
                if self._is_location_match(job, search_loc):
                    accepted_jobs.append(job)
                else:
                    rejected_by_location_count += 1

        # 4. Controlled Fallback: If 0 local results, try nationwide discovery but strictly filter by original location
        if not accepted_jobs and not is_nationwide:
            fallback_triggered = True
            logger.info(
                "AUBI-plus: 0 valid listings found for '%s' in '%s'. "
                "Triggering controlled nationwide discovery fallback...",
                clean_kw,
                search_loc,
            )
            fallback_raw = self._fetch_pages(clean_kw, "", max_jobs)
            fallback_results_count = len(fallback_raw)

            for job in fallback_raw:
                if self._is_location_match(job, search_loc):
                    accepted_jobs.append(job)
                else:
                    rejected_by_location_count += 1

        self.total_jobs_fetched = len(accepted_jobs)
        self.last_search_meta = {
            "original_location": search_loc,
            "normalized_location": clean_loc,
            "fallback_triggered": fallback_triggered,
            "fallback_results": fallback_results_count,
            "rejected_by_location": rejected_by_location_count,
            "final_accepted_results": self.total_jobs_fetched,
        }

        # 5. Logging & Transparency
        logger.info(
            "AUBI-plus search summary: "
            "original_location='%s', "
            "normalized_location='%s', "
            "fallback_triggered=%s, "
            "fallback_results=%d, "
            "rejected_by_location=%d, "
            "final_accepted_results=%d",
            search_loc,
            clean_loc,
            fallback_triggered,
            fallback_results_count,
            rejected_by_location_count,
            self.total_jobs_fetched,
        )
        return accepted_jobs

    def _is_location_match(self, job: Dict, search_location: str) -> bool:
        """
        Validates whether a job satisfies the searched location.
        - Nationwide searches accept all jobs.
        - Explicit location searches check city, postal code, and commuter radius.
        - Non-matching jobs or generic 'Deutschland' / 'k. A.' locations are rejected.
        """
        search_loc = str(search_location or "").strip()
        if not search_loc:
            return True

        if search_loc.lower() in {
            "bundesweit",
            "deutschlandweit",
            "ganz deutschland",
            "deutschland",
            "alle",
            "all",
            "remote",
            "germany",
            "homeoffice",
            "überall",
            "uberall",
        }:
            return True

        job_loc = str(job.get("location") or "").strip()
        job_city = str(job.get("city") or "").strip()
        job_plz = str(job.get("postal_code") or "").strip()

        # Reject jobs with generic Deutschland / k. A. when user asked for a specific location
        if job_city.lower() in {"deutschland", "k. a.", "n/a", ""} and job_loc.lower() in {"deutschland", "k. a.", "n/a", ""}:
            return False

        # 1. Use search_filter_engine's is_location_relevant
        try:
            from .search_filter_engine import is_location_relevant
            if is_location_relevant(job_loc, job_city, job_plz, search_loc):
                return True
        except Exception as exc:
            logger.debug("is_location_relevant error: %s", exc)

        # 2. Enhanced check for umlaut normalizations and PLZ match
        s_norm = search_loc.lower().strip()
        s_base = (
            s_norm.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            .replace("ae", "a").replace("oe", "o").replace("ue", "u")
        )

        # 2a. Postal code check
        plz_match = re.search(r"\b(\d{5})\b", search_loc)
        if plz_match:
            search_plz = plz_match.group(1)
            if job_plz and job_plz != "N/A":
                return job_plz == search_plz or job_plz[:2] == search_plz[:2]
            return False

        # 2b. City check
        city_norm = job_city.lower().strip()
        city_base = (
            city_norm.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            .replace("ae", "a").replace("oe", "o").replace("ue", "u")
        )
        if city_base and (city_base in s_base or s_base in city_base):
            return True

        # 2c. Full location check
        loc_norm = job_loc.lower().strip()
        loc_base = (
            loc_norm.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            .replace("ae", "a").replace("oe", "o").replace("ue", "u")
        )
        if loc_base and (s_base in loc_base):
            return True

        return False

    def _fetch_pages(self, query_kw: str, query_loc: str, max_jobs: int) -> List[Dict]:
        """Internal paginated fetching loop for AUBI-plus."""
        jobs: List[Dict] = []
        seen_refs = set()
        page = 1

        while len(jobs) < max_jobs:
            params = {
                "mSuggest": query_kw,
                "p": page,
            }
            if query_loc:
                params["aSuggest"] = query_loc

            try:
                logger.info("Fetching AUBI-plus page %s (kw='%s', loc='%s')", page, query_kw, query_loc)
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

                page_jobs = self._parse_cards(cards, search_keyword=query_kw)
                new_jobs_count = 0

                for job in page_jobs:
                    ref = job.get("reference") or job.get("url")
                    if not ref or ref in seen_refs:
                        continue
                    seen_refs.add(ref)
                    jobs.append(job)
                    new_jobs_count += 1
                    if len(jobs) >= max_jobs:
                        break

                logger.info(
                    "AUBI-plus page %s: found %s cards, added %s new (total=%s)",
                    page,
                    len(cards),
                    new_jobs_count,
                    len(jobs),
                )

                if new_jobs_count == 0 or len(cards) < 5:
                    break

                page += 1
                time.sleep(0.3)

            except Exception as exc:
                logger.warning("Error fetching AUBI-plus page %s: %s", page, exc)
                break

        return jobs

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
