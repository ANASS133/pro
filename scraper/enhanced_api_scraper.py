import logging
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class EnhancedJobScraper:
    """Fetch all available jobs via paginated Arbeitsagentur API."""

    def __init__(self):
        self.base_url = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
        self.session = requests.Session()
        self.setup_headers()
        self.total_jobs_fetched = 0

    def setup_headers(self):
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
                "Referer": "https://www.arbeitsagentur.de/jobsuche",
                "Origin": "https://www.arbeitsagentur.de",
                "X-API-Key": "jobboerse-jobsuche",
            }
        )

    def fetch_all_jobs(
        self,
        keyword: str,
        location: str = "",
        max_jobs: int = 8000,
        published_since_days: Optional[int] = None,
    ) -> List[Dict]:
        """Fetch all available jobs until max_jobs or no more results."""
        all_jobs: List[Dict] = []
        seen_refs = set()
        page = 1
        size = 25

        logger.info("Start fetch: keyword=%s location=%s max_jobs=%s", keyword, location, max_jobs)

        while len(all_jobs) < max_jobs:
            params = {
                "angebotsart": 4,
                "was": keyword.strip(),
                "page": page,
                "size": size,
                "pav": "false",
                "facetten": "false",
            }
            if location.strip():
                params["wo"] = location.strip()
            if published_since_days is not None:
                params["veroeffentlichtseit"] = int(published_since_days)

            logger.info("Fetching page %s", page)

            try:
                response = self.session.get(self.base_url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as exc:
                logger.error("Error on page %s: %s", page, exc)
                break

            jobs_on_page = data.get("ergebnisliste", [])
            if not jobs_on_page:
                logger.info("No more jobs available")
                break

            parsed_jobs = self.parse_jobs(jobs_on_page)
            for job in parsed_jobs:
                ref = job.get("reference")
                if ref and ref in seen_refs:
                    continue
                if ref:
                    seen_refs.add(ref)
                all_jobs.append(job)
                if len(all_jobs) >= max_jobs:
                    break

            logger.info("Page %s -> %s jobs (total=%s)", page, len(parsed_jobs), len(all_jobs))

            if len(jobs_on_page) < size:
                logger.info("Reached last page")
                break

            page += 1
            time.sleep(0.7)

        self.total_jobs_fetched = len(all_jobs)
        logger.info("Finished fetch total=%s", self.total_jobs_fetched)
        return all_jobs

    def parse_jobs(self, jobs_list: List[Dict]) -> List[Dict]:
        """Parse raw API jobs into clean format."""
        parsed: List[Dict] = []

        for job in jobs_list:
            try:
                city = "N/A"
                postal_code = "N/A"
                location = "N/A"

                if job.get("stellenlokationen"):
                    addr = job["stellenlokationen"][0].get("adresse", {})
                    city = addr.get("ort", "N/A")
                    postal_code = addr.get("plz", "N/A")
                    location = f"{postal_code} {city}".strip()

                reference = job.get("referenznummer", "")

                parsed.append(
                    {
                        "title": job.get("stellenangebotsTitel", "N/A"),
                        "company": job.get("firma", "N/A"),
                        "location": location,
                        "city": city,
                        "postal_code": postal_code,
                        "reference": reference or "N/A",
                        "job_type": "Vollzeit" if job.get("arbeitszeitVollzeit") else "Teilzeit",
                        "published_date": job.get("veroeffentlichungszeitraum", {}).get("von", "N/A"),
                        "start_date": job.get("eintrittszeitraum", {}).get("von", "N/A"),
                        "hauptberuf": job.get("hauptberuf", "N/A"),
                        "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}" if reference else "",
                        "email_extracted": False,
                        "email": None,
                        "phone": None,
                    }
                )
            except Exception as exc:
                logger.error("Error parsing job: %s", exc)

        return parsed
