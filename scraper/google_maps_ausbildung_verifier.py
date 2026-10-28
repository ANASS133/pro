"""
Google Maps Ausbildung Verifier
===============================
Mandatory verification engine for businesses discovered via Google Maps.

Critical Rule:
For EVERY company discovered through Google Maps, visiting and inspecting its
official website is mandatory, regardless of email availability.

Verification steps:
1. Identify the company's official website.
2. Open the website.
3. Search its careers, jobs and Ausbildung sections.
4. Verify whether an actual Ausbildung vacancy matching the user's requested profession exists.
5. If a matching advertisement exists:
   - Extract title, details, and original URL.
   - Check for available business application email.
   - If email exists: save email and verified vacancy info.
   - If no email exists: follow vacancy's application links to discover the actual Bewerbungsformular.
   - Save the verified application URL.
6. If no matching Ausbildung vacancy is found:
   - Retain company as an unconfirmed potential employer, NOT as a verified Ausbildung opportunity.
7. If website is missing or inaccessible:
   - Record that verification was unsuccessful rather than assuming no Ausbildung exists.
"""

import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .search_filter_engine import is_profession_relevant, clean_extracted_location
from .application_form_discovery import ApplicationFormDiscovery, classify_application_method
from .google_maps_opportunity_verifier import GoogleMapsOpportunityVerifier

logger = logging.getLogger(__name__)

CAREER_KEYWORDS = [
    "karriere",
    "jobs",
    "stellenangebote",
    "stellenangeboten",
    "stellen",
    "ausbildung",
    "ausbildungsplaetze",
    "wir-bilden-aus",
    "wir bilden aus",
    "berufsausbildung",
    "lehrstelle",
    "lehrstellen",
    "career",
    "careers",
    "vacancies",
    "openings",
    "azubi",
    "azubis",
    "arbeiten-bei-uns",
    "ueber-uns/karriere",
    "ueber-uns/jobs",
]

AUSBILDUNG_INDICATORS = [
    "ausbildung",
    "auszubildend",
    "azubi",
    "lehrling",
    "lehrstelle",
    "ausbildungsplatz",
    "wir bilden aus",
    "duales studium",
    "lehre als",
    "ausbildungsstart",
]

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

EXCLUDED_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net",
    "wix.com", "squarespace.com", "wordpress.com",
    "sentry.io", "googleapis.com", "google.com",
    "gstatic.com", "w3.org", "schema.org",
}


def _normalize_email(val: Optional[str]) -> str:
    if not val:
        return ""
    return str(val).strip().strip(".,;:\"'<>()[]").lower()


class GoogleMapsAusbildungVerifier:
    """
    Inspects Google Maps businesses and enforces mandatory official website verification
    for authentic Ausbildung opportunities.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int = 10,
        max_pages: int = 6,
    ):
        self.timeout = timeout
        self.max_pages = max_pages
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36 JobScout/2.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        self.session.verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.form_discovery = ApplicationFormDiscovery(session=self.session, timeout=timeout)
        self.opportunity_verifier = GoogleMapsOpportunityVerifier(
            session=self.session,
            timeout=timeout,
            max_pages=max_pages,
        )

    def _fetch_page(self, url: str) -> Optional[str]:
        if not url or not url.startswith("http"):
            return None
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                resp.encoding = resp.encoding or "utf-8"
                return resp.text
        except Exception as exc:
            logger.debug("Failed fetching %s: %s", url, exc)
        return None

    def discover_career_links(self, base_url: str, html: str) -> List[str]:
        """Discovers career, job, and Ausbildung subpages from HTML and common subpaths."""
        discovered: List[str] = []
        seen: Set[str] = {base_url.rstrip("/")}
        parsed_base = urlparse(base_url)
        base_netloc = parsed_base.netloc.lower()

        if html:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                full_url = urljoin(base_url, href)
                parsed_full = urlparse(full_url)
                if parsed_full.netloc.lower() != base_netloc:
                    continue

                haystack = f"{href} {a.get_text()} {a.get('title', '')} {a.get('aria-label', '')}".lower()
                if any(kw in haystack for kw in CAREER_KEYWORDS):
                    clean_url = full_url.split("#")[0].rstrip("/")
                    if clean_url not in seen:
                        seen.add(clean_url)
                        discovered.append(full_url)

        # Candidate standard subpaths
        standard_subpaths = [
            "/karriere",
            "/jobs",
            "/ausbildung",
            "/stellenangebote",
            "/wir-bilden-aus",
            "/ueber-uns/karriere",
        ]
        for sub in standard_subpaths:
            candidate = urljoin(f"{parsed_base.scheme}://{parsed_base.netloc}", sub)
            clean_cand = candidate.rstrip("/")
            if clean_cand not in seen and len(discovered) < self.max_pages:
                seen.add(clean_cand)
                discovered.append(candidate)

        return discovered[:self.max_pages]

    def check_page_for_ausbildung(
        self, page_url: str, html: str, profession_keyword: str
    ) -> Optional[Dict]:
        """
        Inspects an HTML page for an actual Ausbildung vacancy matching profession_keyword.
        Returns details dict if verified, None otherwise.
        """
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 1. Inspect headings, links, and cards
        candidate_elements = soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "a", "li", "div"],
            class_=lambda c: c and any(k in str(c).lower() for k in ["job", "stelle", "title", "teaser", "card", "career", "ausbildung"])
        )
        if not candidate_elements:
            candidate_elements = soup.find_all(["h1", "h2", "h3", "h4", "h5", "a"])

        for el in candidate_elements:
            text = " ".join(el.get_text().split()).strip()
            if not text or len(text) < 4 or len(text) > 200:
                continue

            text_lower = text.lower()
            # Must indicate Ausbildung and be relevant to the profession
            has_indicator = any(ind in text_lower for ind in AUSBILDUNG_INDICATORS)
            if has_indicator and is_profession_relevant(text, "", profession_keyword):
                # Extract link if inside or is an <a> tag
                link = page_url
                if el.name == "a" and el.get("href"):
                    link = urljoin(page_url, el.get("href"))
                else:
                    parent_a = el.find_parent("a") or el.find("a")
                    if parent_a and parent_a.get("href"):
                        link = urljoin(page_url, parent_a.get("href"))

                return {
                    "title": text,
                    "vacancy_url": link,
                    "snippet": text,
                }

        # 2. Broader text block search (e.g. paragraphs containing "Wir bilden aus: Koch/Köchin")
        for p in soup.find_all(["p", "section", "article"]):
            p_text = " ".join(p.get_text().split()).strip()
            if not p_text or len(p_text) < 15:
                continue
            p_lower = p_text.lower()
            if any(ind in p_lower for ind in AUSBILDUNG_INDICATORS) and is_profession_relevant(p_text[:120], "", profession_keyword):
                first_line = p_text.split(".")[0][:100].strip()
                title = first_line if len(first_line) > 10 else f"Ausbildung zum {profession_keyword}"
                return {
                    "title": title,
                    "vacancy_url": page_url,
                    "snippet": p_text[:250],
                }

        return None

    def extract_emails_from_html(self, html: str) -> List[str]:
        if not html:
            return []
        found = set()
        for raw in EMAIL_PATTERN.findall(html):
            norm = _normalize_email(raw)
            if norm and "@" in norm:
                domain = norm.split("@", 1)[1]
                if domain not in EXCLUDED_EMAIL_DOMAINS:
                    found.add(norm)
        return list(found)

    def verify_business(
        self,
        business: Dict,
        profession_keyword: str,
        driver=None,
    ) -> Dict:
        """
        Executes the mandatory website inspection for a Google Maps business.
        Updates business dict in place and returns it.
        """
        name = business.get("name") or business.get("company") or "Unbekannt"
        website = business.get("website") or business.get("url") or ""
        search_kw = profession_keyword.strip()

        # Step 1: Check website presence
        if not website or not website.startswith("http"):
            business["opportunity_type"] = "UNVERIFIED"
            business["is_verified_vacancy"] = False
            business["verification_status"] = "missing_website"
            business["status"] = "Unbestätigt: Keine Website vorhanden"
            business["verification_notes"] = "Keine offizielle Website auf Google Maps hinterlegt"
            business["source"] = "Google Maps"
            return business

        # Step 2: Open official website
        homepage_html = self._fetch_page(website)
        if not homepage_html and driver is not None:
            try:
                driver.get(website)
                from .cookie_handler import accept_cookies
                accept_cookies(driver)
                time.sleep(2)
                accept_cookies(driver)
                homepage_html = driver.page_source
            except Exception as exc:
                logger.debug("Selenium fallback failed for %s: %s", website, exc)

        if not homepage_html:
            business["opportunity_type"] = "UNVERIFIED"
            business["is_verified_vacancy"] = False
            business["verification_status"] = "inaccessible_website"
            business["status"] = "Unbestätigt: Website nicht erreichbar"
            business["verification_notes"] = f"Website {website} konnte nicht geöffnet werden (Timeout / Zugriff verweigert)"
            business["source"] = "Google Maps"
            return business

        # Step 3: Search careers, jobs, and Ausbildung sections
        career_links = self.discover_career_links(website, homepage_html)
        pages_to_check = [(website, homepage_html)]
        for link in career_links:
            page_html = self._fetch_page(link)
            if page_html:
                pages_to_check.append((link, page_html))

        # Step 4: Verify whether an actual Ausbildung vacancy exists
        matched_vacancy: Optional[Dict] = None
        for page_url, p_html in pages_to_check:
            res = self.check_page_for_ausbildung(page_url, p_html, search_kw)
            if res:
                matched_vacancy = res
                matched_vacancy["found_on_page"] = page_url
                break

        # Step 5: If matching advertisement exists -> extract details, email, and application form
        if matched_vacancy:
            verified_title = matched_vacancy["title"]
            vacancy_url = matched_vacancy["vacancy_url"]

            business["opportunity_type"] = "VERIFIED_AUSBILDUNG"
            business["is_verified_vacancy"] = True
            business["verification_status"] = "verified_ausbildung"
            business["title"] = verified_title
            business["company"] = name
            business["source"] = "Google Maps"
            business["hauptberuf"] = search_kw
            business["job_type"] = "Ausbildung"
            business["apply_url"] = vacancy_url
            business["status"] = "Bestätigte Ausbildungsstelle"
            business["verification_notes"] = f"Ausschreibung '{verified_title}' auf Unternehmenswebsite verifiziert"

            # Check for business application email
            emails_found = []
            for _, p_html in pages_to_check:
                emails_found.extend(self.extract_emails_from_html(p_html))

            # Also check /impressum or /kontakt
            contact_paths = ["/kontakt", "/impressum", "/contact", "/imprint"]
            parsed_site = urlparse(website)
            for cp in contact_paths:
                cp_url = urljoin(f"{parsed_site.scheme}://{parsed_site.netloc}", cp)
                cp_html = self._fetch_page(cp_url)
                if cp_html:
                    emails_found.extend(self.extract_emails_from_html(cp_html))

            clean_emails = [e for e in set(emails_found) if e]
            if clean_emails:
                business["email"] = clean_emails[0]
                business["emails"] = clean_emails
                business["email_extracted"] = True
            else:
                business["email"] = ""
                business["email_extracted"] = False

            # If no email exists, follow vacancy's application links for Bewerbungsformular
            if not business.get("email"):
                discovery = self.form_discovery.discover_application_form(
                    business,
                    driver=driver,
                )
                business["has_form"] = discovery.has_form
                business["form_link"] = discovery.form_link
                business["bewerbung_link"] = discovery.bewerbung_link or vacancy_url
            else:
                # Email exists -> check if form also exists
                business["has_form"] = False
                business["form_link"] = ""
                business["bewerbung_link"] = vacancy_url

            method, art = classify_application_method(
                business.get("email"),
                business.get("has_form"),
            )
            business["application_method"] = method
            business["bewerbung_art"] = art
            return business

        # Step 6: If NO matching Ausbildung vacancy is found -> retain as POTENTIAL_EMPLOYER
        # Extract publicly available contact email so outreach is still possible
        emails_found = []
        for _, p_html in pages_to_check:
            emails_found.extend(self.extract_emails_from_html(p_html))

        contact_paths = ["/kontakt", "/impressum", "/contact", "/imprint"]
        parsed_site = urlparse(website)
        for cp in contact_paths:
            cp_url = urljoin(f"{parsed_site.scheme}://{parsed_site.netloc}", cp)
            cp_html = self._fetch_page(cp_url)
            if cp_html:
                emails_found.extend(self.extract_emails_from_html(cp_html))

        clean_emails = [e for e in set(emails_found) if e]
        if clean_emails:
            business["email"] = clean_emails[0]
            business["emails"] = clean_emails
            business["email_extracted"] = True
        else:
            business.setdefault("email", "")
            business["email_extracted"] = False

        business["opportunity_type"] = "POTENTIAL_EMPLOYER"
        business["is_verified_vacancy"] = False
        business["verification_status"] = "no_matching_ausbildung"
        business["status"] = "Potenzieller Ausbildungsbetrieb: Keine passende Ausschreibung (Initiativbewerbung)"
        business["title"] = f"Potenzieller Ausbildungsbetrieb: {name}"
        business["company"] = name
        business["hauptberuf"] = search_kw
        business["job_type"] = "Ausbildung"
        business["apply_url"] = website
        business["verification_notes"] = f"Website geprüft ({len(pages_to_check)} Seiten), keine offene Stellenausschreibung für '{search_kw}' gefunden"
        business["source"] = "Google Maps"
        return business

    def verify_business_for_arbeit(
        self,
        business: Dict,
        profession_keyword: str = "",
    ) -> Dict:
        """
        Inspects an employer website for Arbeit mode:
        1. Visits official company website.
        2. Inspects homepage, Kontakt, Impressum, and Karriere pages.
        3. Extracts, normalizes, and validates publicly listed professional email addresses.
        4. Preserves the employer opportunity even when no email is found.
        5. Does NOT require a verified online application form.
        """
        name = str(business.get("name") or business.get("company") or "Unbekannt").strip()
        website = str(business.get("website") or business.get("url") or "").strip()
        city = str(business.get("city") or "").strip()
        location = str(business.get("location") or business.get("address") or city or "Deutschland").strip()
        phone = str(business.get("phone") or "").strip()
        search_kw = profession_keyword.strip()

        title = f"{search_kw} bei {name}" if search_kw else f"Stellenangebot bei {name}"
        business["title"] = title
        business["company"] = name
        business["location"] = location
        business["city"] = city
        business["phone"] = phone
        business["source"] = "Google Maps"
        business["apply_url"] = website
        business["has_form"] = False
        business["form_link"] = ""
        business["bewerbung_link"] = website
        business["hauptberuf"] = search_kw or "Arbeit"
        business["published_date"] = "k. A."
        business["start_date"] = "ab sofort"
        business["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Step 1: Check website
        if not website or not website.startswith("http"):
            business["email"] = ""
            business["email_extracted"] = False
            business["application_method"] = "None"
            business["bewerbung_art"] = "Keine"
            business["is_verified_vacancy"] = True
            business["verification_status"] = "missing_website"
            business["status"] = "Unternehmen erfasst (Keine Website)"
            business["verification_notes"] = "Keine offizielle Website hinterlegt"
            return business

        # Step 2: Open official website homepage
        html = self._fetch_page(website)
        if not html:
            business["email"] = ""
            business["email_extracted"] = False
            business["application_method"] = "None"
            business["bewerbung_art"] = "Keine"
            business["is_verified_vacancy"] = True
            business["verification_status"] = "inaccessible_website"
            business["status"] = "Unternehmen erfasst (Website nicht erreichbar)"
            business["verification_notes"] = "Website konnte nicht geladen werden"
            return business

        # Step 3: Extract emails from homepage
        emails_found = self.extract_emails_from_html(html)

        # Step 4: Discover Impressum, Kontakt, and Karriere subpages
        contact_pages = []
        soup = BeautifulSoup(html, "html.parser")
        base_netloc = urlparse(website).netloc.lower()

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            full_url = urljoin(website, href)
            if urlparse(full_url).netloc.lower() != base_netloc:
                continue

            text = f"{href} {a.get_text()} {a.get('title', '')}".lower()
            if any(k in text for k in ["kontakt", "contact", "impressum", "imprint", "karriere", "jobs"]):
                clean_url = full_url.split("#")[0].rstrip("/")
                if clean_url not in contact_pages and len(contact_pages) < 4:
                    contact_pages.append(clean_url)

        # Inspect discovered pages
        for cp_url in contact_pages:
            cp_html = self._fetch_page(cp_url)
            if cp_html:
                emails_found.extend(self.extract_emails_from_html(cp_html))

        # Step 5: Normalize and deduplicate emails
        valid_emails = [e for e in set(emails_found) if e and "@" in e]
        if valid_emails:
            business["email"] = valid_emails[0]
            business["emails"] = valid_emails
            business["email_extracted"] = True
            business["application_method"] = "Email"
            business["bewerbung_art"] = "E-Mail"
            business["verification_status"] = "email_found"
            business["status"] = f"E-Mail gefunden: {valid_emails[0]}"
            business["verification_notes"] = f"{len(valid_emails)} E-Mail-Adresse(n) extrahiert"
        else:
            business["email"] = ""
            business["email_extracted"] = False
            business["application_method"] = "None"
            business["bewerbung_art"] = "Keine"
            business["verification_status"] = "no_email"
            business["status"] = "Unternehmen erfasst (Keine E-Mail)"
            business["verification_notes"] = "Keine öffentliche Kontakt-E-Mail gefunden"

        business["is_verified_vacancy"] = True
        return business

    def verify_opportunities(
        self,
        business: Dict,
        target_title: str = "",
        job_type: str = "both",
        client_id: str = "",
        candidate_profile: Optional[Dict] = None,
        driver=None,
    ) -> Dict:
        """
        Executes full job opportunity and Ausbildung verification across business official website.
        Discovers career pages, extracts vacancies, classifies apply destinations,
        calculates explainable 0-100 matching scores, and prepares queue integration data.
        """
        return self.opportunity_verifier.verify_business_opportunities(
            business=business,
            target_title=target_title,
            job_type=job_type,
            client_id=client_id,
            candidate_profile=candidate_profile,
            driver=driver,
        )

    @classmethod
    def calculate_relevance_score(
        cls,
        business: Dict,
        category_relevance: float = 1.0,
        target_location: str = "",
    ) -> int:
        """
        Calculates a composite explainable score (0-100) based on:
        1. Category relevance from ProfessionIntelligence (0-35 pts)
        2. Opportunity verification (30 pts for verified, 18 pts for potential employer)
        3. Contact accessibility (up to 20 pts for email/phone/form)
        4. Geographic relevance (up to 15 pts for city match)
        """
        score = 0
        # 1. Category relevance (0-35 pts)
        cat_rel = float(business.get("profession_relevance") or business.get("category_relevance") or category_relevance or 1.0)
        score += int(min(max(cat_rel, 0.0), 1.0) * 35)

        # 2. Opportunity verification (up to 30 pts)
        opp_type = business.get("opportunity_type")
        if opp_type == "VERIFIED_AUSBILDUNG" or business.get("is_verified_vacancy"):
            score += 30
        elif opp_type == "POTENTIAL_EMPLOYER" or business.get("has_career_page"):
            score += 18
        elif business.get("website"):
            score += 8

        # 3. Contact accessibility (up to 20 pts)
        if business.get("email"):
            score += 20
        elif business.get("has_form") or business.get("apply_url"):
            score += 12
        elif business.get("phone"):
            score += 8

        # 4. Geographic relevance (up to 15 pts)
        biz_city = str(business.get("city") or business.get("location") or "").lower()
        target_loc = str(target_location or "").lower()
        if target_loc and (target_loc in biz_city or biz_city in target_loc):
            score += 15
        elif biz_city:
            score += 8

        return min(max(score, 0), 100)

    @classmethod
    def smart_rank_employers(
        cls,
        employers: List[Dict],
        category_relevance_map: Optional[Dict[str, float]] = None,
        target_location: str = "",
        profession: str = "",
        **kwargs,
    ) -> List[Dict]:
        """
        Ranks a list of employers using calculate_relevance_score and sorts them descending.
        """
        cat_map = category_relevance_map or {}
        for emp in employers:
            cat = str(emp.get("employer_category") or emp.get("category") or emp.get("target_category") or "").strip()
            cat_rel = cat_map.get(cat, float(emp.get("profession_relevance") or emp.get("category_relevance", 0.9)))
            emp["category_relevance"] = cat_rel
            score = cls.calculate_relevance_score(
                emp,
                category_relevance=cat_rel,
                target_location=target_location,
            )
            emp["relevance_score"] = score
            emp["smart_relevance_score"] = score

        return sorted(employers, key=lambda x: x.get("relevance_score", 0), reverse=True)


