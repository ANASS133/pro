"""
Google Maps Job & Ausbildung Opportunity Verifier Engine.
=========================================================
Upgrades Google Maps business scraping into an intelligent Job Opportunity Discovery Engine.

Capabilities:
1. Multilingual Career Page Discovery (German, English, French).
2. Deep Job Listing & Vacancy Extraction (title, description, location, type, deadline, URLs).
3. Application Destination Classification:
   - DIRECT_APPLICATION_FORM
   - APPLICATION_PORTAL (Personio, Workday, Softgarden, Greenhouse, JOIN, SmartRecruiters, etc.)
   - CAREERS_PAGE
   - JOB_LISTING
   - GENERAL_CONTACT_FORM
   - UNKNOWN
4. Candidate-Based Opportunity Verification:
   - Match against target job title, job type (Ausbildung, Employment, Both), skills, location, languages.
   - Verification statuses:
     - OPEN_VERIFIED
     - POTENTIALLY_OPEN
     - NO_MATCHING_VACANCY
     - EXPIRED
     - VERIFICATION_FAILED
     - UNKNOWN
5. Explainable Relevance Scoring (0 - 100) with detailed reasons.
6. Structured multi-vacancy data prepared for Email Outreach & Autofill Queues.
"""

import hashlib
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .application_form_discovery import (
    APPLICATION_BUTTON_KEYWORDS,
    KNOWN_ATS_DOMAINS,
    JOB_PORTAL_DOMAINS,
    classify_application_method,
)
from .search_filter_engine import is_profession_relevant, clean_extracted_location

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Multilingual Keywords for Career Page Discovery
# ---------------------------------------------------------------------------

CAREER_KEYWORDS_DE = [
    "karriere",
    "stellenangebote",
    "stellenangeboten",
    "jobs",
    "stellen",
    "ausbildung",
    "ausbildungsplaetze",
    "ausbildungsplätze",
    "bewerbung",
    "jetzt bewerben",
    "offene stellen",
    "berufseinstieg",
    "praktikum",
    "duales studium",
    "wir bilden aus",
    "wir-bilden-aus",
    "lehrstelle",
    "lehrstellen",
    "azubi",
    "azubis",
    "arbeiten-bei-uns",
    "arbeiten bei uns",
    "jobboerse",
    "ueber-uns/karriere",
    "ueber-uns/jobs",
]

CAREER_KEYWORDS_EN = [
    "careers",
    "career",
    "jobs",
    "vacancies",
    "open positions",
    "openings",
    "apply now",
    "apprenticeships",
    "opportunities",
    "work with us",
    "work-with-us",
    "join our team",
    "join-our-team",
    "join us",
    "employment",
]

CAREER_KEYWORDS_FR = [
    "carrières",
    "carrieres",
    "recrutement",
    "offres d'emploi",
    "offres demploi",
    "postuler",
    "candidature",
    "candidatures",
    "rejoignez-nous",
    "rejoignez nous",
    "stages",
    "alternance",
    "emploi",
]

ALL_CAREER_KEYWORDS = sorted(
    list(set(CAREER_KEYWORDS_DE + CAREER_KEYWORDS_EN + CAREER_KEYWORDS_FR)),
    key=lambda k: -len(k),
)

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
    "berufsausbildung",
    "apprenticeship",
    "apprentice",
    "alternance",
    "apprentissage",
]

CONVENTIONAL_CAREER_PATHS = [
    "/karriere",
    "/karriere/",
    "/jobs",
    "/jobs/",
    "/stellenangebote",
    "/stellenangebote/",
    "/ausbildung",
    "/ausbildung/",
    "/careers",
    "/careers/",
    "/career",
    "/offene-stellen",
    "/recrutement",
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

EXCLUDED_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net",
    "wix.com", "squarespace.com", "wordpress.com",
    "sentry.io", "googleapis.com", "google.com",
    "gstatic.com", "w3.org", "schema.org",
}

# ---------------------------------------------------------------------------
# Classification & Status Constants
# ---------------------------------------------------------------------------

URL_DIRECT_APPLICATION_FORM = "DIRECT_APPLICATION_FORM"
URL_APPLICATION_PORTAL = "APPLICATION_PORTAL"
URL_CAREERS_PAGE = "CAREERS_PAGE"
URL_JOB_LISTING = "JOB_LISTING"
URL_GENERAL_CONTACT_FORM = "GENERAL_CONTACT_FORM"
URL_UNKNOWN = "UNKNOWN"

STATUS_OPEN_VERIFIED = "OPEN_VERIFIED"
STATUS_POTENTIALLY_OPEN = "POTENTIALLY_OPEN"
STATUS_NO_MATCHING_VACANCY = "NO_MATCHING_VACANCY"
STATUS_EXPIRED = "EXPIRED"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STATUS_UNKNOWN = "UNKNOWN"


@dataclass
class DiscoveredVacancy:
    """Represents a structured vacancy discovered for a business."""
    company_name: str
    job_title: str
    job_description: str = ""
    location: str = ""
    employment_type: str = "Unspecified"
    is_ausbildung: bool = False
    start_date: str = "ab sofort"
    application_deadline: str = "k. A."
    job_listing_url: str = ""
    direct_application_url: str = ""
    application_method: str = "None"
    application_url_type: str = URL_UNKNOWN
    source_website: str = ""
    verification_status: str = STATUS_UNKNOWN
    matching_score: int = 0
    matching_reasons: List[str] = field(default_factory=list)
    discovery_timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )
    # Queue integration fields
    client_id: str = ""
    company_id: str = ""
    job_id: str = field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")


def generate_company_id(name: str, website: str = "") -> str:
    """Deterministic company identifier for queue tracking."""
    key = f"{str(name or '').strip().lower()}::{str(website or '').strip().lower()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"comp_{digest}"


class GoogleMapsOpportunityVerifier:
    """
    Intelligent Job & Ausbildung Opportunity Discovery & Verification Engine.
    Inspects official company websites, crawls career portals, extracts individual
    vacancies, verifies candidate suitability, and classifies application destinations.
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
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7,fr;q=0.6",
            }
        )
        self.session.verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def fetch_page(self, url: str) -> Tuple[str, str]:
        """Fetches page HTML returning (final_url, html_text)."""
        if not url or not url.startswith("http"):
            return url, ""
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200:
                resp.encoding = resp.encoding or "utf-8"
                return resp.url, resp.text
            elif resp.status_code in (403, 429, 503):
                logger.debug("Fetch returned status %s for %s", resp.status_code, url)
        except Exception as exc:
            logger.debug("Fetch error for %s: %s", url, exc)
        return url, ""

    # -----------------------------------------------------------------------
    # 1. Career Page Discovery
    # -----------------------------------------------------------------------

    def discover_career_urls(self, base_url: str, homepage_html: str) -> List[str]:
        """
        Discovers career, jobs, and recruitment subpages using German, English,
        and French keywords across navigation, footers, and conventional subpaths.
        """
        if not base_url or not base_url.startswith("http"):
            return []

        discovered: List[str] = []
        seen: Set[str] = {base_url.rstrip("/")}
        parsed_base = urlparse(base_url)
        base_netloc = parsed_base.netloc.lower()

        if homepage_html:
            try:
                soup = BeautifulSoup(homepage_html, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = (a_tag.get("href") or "").strip()
                    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                        continue

                    full_url = urljoin(base_url, href)
                    parsed_full = urlparse(full_url)
                    full_netloc = parsed_full.netloc.lower()

                    # Stay within same root domain or known ATS
                    is_same_domain = (
                        full_netloc == base_netloc
                        or full_netloc.endswith("." + base_netloc)
                        or any(ats in full_netloc for ats in KNOWN_ATS_DOMAINS)
                    )
                    if not is_same_domain:
                        continue

                    # Search link text, href, title, aria-label
                    text_parts = [
                        href,
                        a_tag.get_text() or "",
                        a_tag.get("title") or "",
                        a_tag.get("aria-label") or "",
                    ]
                    haystack = " ".join(text_parts).lower()

                    if any(kw in haystack for kw in ALL_CAREER_KEYWORDS):
                        clean_url = full_url.split("#")[0].rstrip("/")
                        if clean_url not in seen:
                            seen.add(clean_url)
                            discovered.append(full_url)
                            if len(discovered) >= self.max_pages:
                                break
            except Exception as exc:
                logger.debug("Error parsing career links from %s: %s", base_url, exc)

        # Standard conventional subpaths as fallback
        for subpath in CONVENTIONAL_CAREER_PATHS:
            if len(discovered) >= self.max_pages:
                break
            candidate = urljoin(f"{parsed_base.scheme}://{parsed_base.netloc}", subpath)
            clean_cand = candidate.rstrip("/")
            if clean_cand not in seen:
                seen.add(clean_cand)
                discovered.append(candidate)

        return discovered[:self.max_pages]

    # -----------------------------------------------------------------------
    # 2. Application URL & Button Classification
    # -----------------------------------------------------------------------

    @staticmethod
    def is_known_ats(url: str) -> bool:
        """Checks if URL belongs to a known applicant tracking system."""
        if not url:
            return False
        netloc = urlparse(url).netloc.lower()
        return any(ats in netloc for ats in KNOWN_ATS_DOMAINS)

    @classmethod
    def classify_application_url(
        cls,
        url: str,
        html_content: str = "",
        page_title: str = "",
    ) -> str:
        """
        Strictly classifies an application destination into:
        - DIRECT_APPLICATION_FORM
        - APPLICATION_PORTAL
        - CAREERS_PAGE
        - JOB_LISTING
        - GENERAL_CONTACT_FORM
        - UNKNOWN
        """
        if not url:
            return URL_UNKNOWN

        parsed = urlparse(url)
        url_lower = url.lower()
        netloc_lower = (parsed.netloc or "").lower()
        path_lower = (parsed.path or "").lower()

        # 1. Check for known ATS portals
        if cls.is_known_ats(url):
            if any(k in path_lower for k in ["/apply", "/bewerben", "/bewerbung", "/form", "/candidat"]):
                return URL_DIRECT_APPLICATION_FORM
            return URL_APPLICATION_PORTAL

        # 2. Check for general contact form (NOT a verified job application)
        contact_markers = ["/kontakt", "/contact", "/impressum", "/imprint"]
        if any(marker in path_lower for marker in contact_markers) and not any(
            k in path_lower for k in ["karriere", "job", "career", "bewerb", "apply"]
        ):
            return URL_GENERAL_CONTACT_FORM

        # 3. Direct application form markers in URL path
        apply_path_markers = [
            "/bewerbungsformular",
            "/jetzt-bewerben",
            "/online-bewerben",
            "/bewerbung-online",
            "/apply-now",
            "/apply/",
            "/postuler",
        ]
        if any(marker in path_lower for marker in apply_path_markers):
            return URL_DIRECT_APPLICATION_FORM

        # 4. If HTML content is provided, inspect DOM for interactive form elements
        if html_content:
            soup = BeautifulSoup(html_content, "html.parser")

            # Check for native job application forms
            forms = soup.find_all("form")
            for f in forms:
                f_text = f.get_text().lower()
                f_action = (f.get("action") or "").lower()

                has_file_upload = bool(f.find("input", type="file"))
                has_job_context = any(
                    k in f_text or k in f_action
                    for k in [
                        "bewerb", "lebenslauf", "cv", "resume",
                        "anschreiben", "apply", "candidat", "stelle"
                    ]
                )
                if has_file_upload and has_job_context:
                    return URL_DIRECT_APPLICATION_FORM

                if any(k in f_action for k in ["apply", "bewerb", "candidat"]):
                    return URL_DIRECT_APPLICATION_FORM

            # Check if this is a dedicated single job ad
            headings = soup.find_all(["h1", "h2"])
            h_text = " ".join(h.get_text() for h in headings).lower()
            if any(k in h_text for k in ["wir suchen", "jobbeschreibung", "ihre aufgaben", "ihr profil", "your profile", "tasks"]):
                return URL_JOB_LISTING

        # 5. Career overview page check
        if any(k in path_lower for k in ["/karriere", "/jobs", "/careers", "/stellenangebote", "/recrutement"]):
            return URL_CAREERS_PAGE

        return URL_UNKNOWN

    # -----------------------------------------------------------------------
    # 3. Job Listing Extraction
    # -----------------------------------------------------------------------

    def extract_job_listings_from_html(
        self,
        page_url: str,
        html_content: str,
        company_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Parses career page HTML to extract individual open job listings.
        Checks:
        1. JSON-LD schema.org `JobPosting` metadata.
        2. Job listing cards, headings, list elements.
        3. Application buttons & links.
        Do not invent missing information.
        """
        if not html_content:
            return []

        listings: List[Dict[str, Any]] = []
        seen_titles: Set[str] = set()

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # A. Extract structured JSON-LD JobPostings if present
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("@type") == "JobPosting":
                            title = str(item.get("title") or "").strip()
                            if title and title.lower() not in seen_titles:
                                seen_titles.add(title.lower())
                                desc = str(item.get("description") or "")
                                clean_desc = " ".join(BeautifulSoup(desc, "html.parser").get_text().split())[:300]
                                date_posted = str(item.get("datePosted") or "")
                                valid_through = str(item.get("validThrough") or "k. A.")
                                emp_type = str(item.get("employmentType") or "Full-time")
                                is_azubi = any(ind in f"{title} {emp_type} {clean_desc}".lower() for ind in AUSBILDUNG_INDICATORS)
                                direct_url = str(item.get("url") or page_url)

                                listings.append({
                                    "title": title,
                                    "description": clean_desc,
                                    "location": str(item.get("jobLocation", {}).get("address", {}).get("addressLocality") or ""),
                                    "employment_type": "Ausbildung" if is_azubi else emp_type,
                                    "is_ausbildung": is_azubi,
                                    "start_date": date_posted or "ab sofort",
                                    "application_deadline": valid_through,
                                    "listing_url": page_url,
                                    "direct_application_url": direct_url,
                                })
                except Exception:
                    pass

            # B. Extract from DOM elements (cards, headings, job links)
            candidate_elements = soup.find_all(
                ["div", "li", "article", "section"],
                class_=lambda c: c and any(
                    k in str(c).lower()
                    for k in ["job", "stelle", "vacancy", "career-item", "opening", "listing", "ausbildung"]
                )
            )

            # Fallback if no specific container class
            if not candidate_elements:
                candidate_elements = soup.find_all(["h2", "h3", "h4", "a"])

            for el in candidate_elements:
                # Find title
                title_tag = el if el.name in ["h2", "h3", "h4", "a"] else el.find(["h2", "h3", "h4", "a", "strong"])
                if not title_tag:
                    continue

                raw_title = " ".join((title_tag.get_text() or "").split()).strip()
                if not raw_title or len(raw_title) < 4 or len(raw_title) > 150:
                    continue

                # Filter out obvious navigation / non-job headlines
                title_lower = raw_title.lower()
                non_job_phrases = [
                    "unsere benefits", "über uns", "warum wir", "ihre vorteile",
                    "kontakt", "impressum", "datenschutz", "karrierechancen",
                    "initiativerwerbung", "initiativbewerbung", "cookie",
                    "unser team", "stellenangebote", "offene stellen", "unsere stellen"
                ]
                if any(p == title_lower for p in non_job_phrases):
                    continue

                # Must have job markers like (m/w/d), (w/m/d), Ausbildung, Developer, etc. or be within a job container
                parent_classes = " ".join(title_tag.find_parent().get("class", [])) if title_tag.find_parent() else ""
                in_job_container = any(k in parent_classes.lower() for k in ["job", "stelle", "position", "career", "vacancy", "listing", "angebot"])
                
                has_job_marker = bool(
                    re.search(r"(\([mwdfigx/\s\-,\.]+\)|\b[mwdfig]/[mwdfig]/[mwdfig]\b|\b[mwdfig]/[mwdfig]\b)", title_lower)
                    or any(ind in title_lower for ind in AUSBILDUNG_INDICATORS)
                    or any(k in title_lower for k in [
                        "ingenieur", "entwickler", "mechaniker", "fachkraft",
                        "spezialist", "kaufmann", "kauffrau", "berater",
                        "leiter", "manager", "assistenz", "mitarbeiter",
                        "pfleger", "koch", "techniker", "developer", "engineer",
                        "consultant", "nurse", "sales", "specialist"
                    ])
                )
                if not has_job_marker and not in_job_container:
                    continue

                if title_lower in seen_titles:
                    continue
                seen_titles.add(title_lower)

                # Find associated link
                link = page_url
                a_tag = el if el.name == "a" else el.find("a", href=True)
                if a_tag and a_tag.get("href"):
                    href = a_tag.get("href").strip()
                    if not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                        link = urljoin(page_url, href)

                # Look for direct application button inside or near element
                direct_apply_url = ""
                for btn in el.find_all("a", href=True):
                    btn_text = (btn.get_text() or "").strip().lower()
                    btn_href = btn.get("href")
                    if any(kw in btn_text for kw in APPLICATION_BUTTON_KEYWORDS):
                        direct_apply_url = urljoin(page_url, btn_href)
                        break

                # Extract snippet
                snippet = " ".join(el.get_text().split())[:250]
                is_azubi = any(ind in f"{raw_title} {snippet}".lower() for ind in AUSBILDUNG_INDICATORS)

                listings.append({
                    "title": raw_title,
                    "description": snippet,
                    "location": "",
                    "employment_type": "Ausbildung" if is_azubi else "Festanstellung",
                    "is_ausbildung": is_azubi,
                    "start_date": "ab sofort",
                    "application_deadline": "k. A.",
                    "listing_url": link,
                    "direct_application_url": direct_apply_url or link,
                })

                if len(listings) >= 15:
                    break

        except Exception as exc:
            logger.debug("Error extracting job listings from %s: %s", page_url, exc)

        return listings

    # -----------------------------------------------------------------------
    # 4. Candidate Matching & Relevance Scoring (0 to 100)
    # -----------------------------------------------------------------------

    def calculate_matching_score(
        self,
        job_title: str,
        job_description: str,
        is_ausbildung: bool,
        target_title: str = "",
        job_type: str = "both",
        candidate_profile: Optional[Dict[str, Any]] = None,
        job_location: str = "",
    ) -> Tuple[int, List[str], str]:
        """
        Calculates an explainable 0 to 100 relevance score with reasons and verification status.

        Scoring weights:
        - Job Title Match: up to 40 pts
        - Job Type Compatibility: up to 25 pts
        - Skills Compatibility: up to 15 pts
        - Location Compatibility: up to 10 pts
        - Language / Education Compatibility: up to 10 pts
        """
        score = 0
        reasons: List[str] = []
        target_clean = str(target_title or "").strip().lower()
        title_lower = str(job_title or "").strip().lower()
        desc_lower = str(job_description or "").strip().lower()

        # If candidate profile is provided, extract target criteria
        candidate_skills = []
        candidate_city = ""
        candidate_education = ""
        candidate_languages = []

        if candidate_profile:
            applicant = candidate_profile.get("applicant", {})
            prof = applicant.get("professional_profile", {})
            if not target_clean:
                target_clean = str(prof.get("current_title") or prof.get("headline") or "").strip().lower()

            # Skills
            skills_dict = applicant.get("skills", {})
            for cat, s_list in skills_dict.items():
                if isinstance(s_list, list):
                    candidate_skills.extend([str(s).lower() for s in s_list if s])

            # Location
            candidate_city = str(applicant.get("contact", {}).get("address", {}).get("city") or "").strip().lower()

            # Education
            candidate_education = str(applicant.get("education_mapping", {}).get("highest_completed_qualification", {}).get("original_title") or "").lower()

            # Languages
            for lang_item in applicant.get("languages", []):
                if isinstance(lang_item, dict):
                    l_name = str(lang_item.get("language") or lang_item.get("language_de") or "").lower()
                    if l_name:
                        candidate_languages.append(l_name)

        # -------------------------------------------------------------------
        # A. Job Title Match (up to 40 pts)
        # -------------------------------------------------------------------
        title_score = 0
        if not target_clean:
            # If no target specified, general opportunity receives baseline
            title_score = 25
            score += 25
            reasons.append("Generelle Stellenausschreibung ohne Zielberufsfilter (+25%)")
        else:
            # Check profession relevance using search filter engine
            is_relevant = is_profession_relevant(title_lower, "", target_clean)
            target_tokens = set(re.findall(r"\w+", target_clean))
            title_tokens = set(re.findall(r"\w+", title_lower))
            overlap = target_tokens.intersection(title_tokens)

            if target_clean in title_lower or is_relevant:
                title_score = 40
                score += 40
                reasons.append(f"Exakter / hochgradiger Treffer für '{target_title}' (+40%)")
            elif overlap and len(overlap) >= max(1, len(target_tokens) // 2):
                title_score = 25
                score += 25
                reasons.append(f"Verwandte Stellenbezeichnung mit Überschneidung ({', '.join(overlap)}) (+25%)")
            elif any(tok in desc_lower for tok in target_tokens if len(tok) >= 4):
                title_score = 15
                score += 15
                reasons.append("Zielberufs-Schlüsselwörter in Stellenbeschreibung gefunden (+15%)")
            else:
                title_score = 0
                reasons.append(f"Keine direkte Übereinstimmung mit Zielberuf '{target_title}' (+0%)")

        # -------------------------------------------------------------------
        # B. Job Type Compatibility (up to 25 pts)
        # -------------------------------------------------------------------
        job_type_clean = (job_type or "both").lower()

        if job_type_clean == "ausbildung":
            if is_ausbildung:
                score += 25
                reasons.append("Ausbildungsplatz stimmt exakt mit Ausbildungsfilter überein (+25%)")
            else:
                score += 5
                reasons.append("Reguläre Festanstellung passt nicht optimal zu Ausbildungsziel (+5%)")
        elif job_type_clean == "employment":
            if not is_ausbildung:
                score += 25
                reasons.append("Reguläre Beschäftigung stimmt mit Festanstellungsfilter überein (+25%)")
            else:
                score += 5
                reasons.append("Ausbildungsplatz entspricht nicht dem Festanstellungsfilter (+5%)")
        else:
            # "both" or default
            score += 25
            type_label = "Ausbildung" if is_ausbildung else "Festanstellung"
            reasons.append(f"Anstellungsart ({type_label}) entspricht allgemeinem Suchfilter (+25%)")

        # -------------------------------------------------------------------
        # C. Skills Compatibility (up to 15 pts)
        # -------------------------------------------------------------------
        matched_skills = []
        if candidate_skills:
            for sk in candidate_skills[:12]:
                if len(sk) >= 3 and (sk in title_lower or sk in desc_lower):
                    matched_skills.append(sk)
            if matched_skills:
                pts = min(15, len(matched_skills) * 5)
                score += pts
                reasons.append(f"Kandidaten-Fähigkeiten gefunden ({', '.join(matched_skills[:4])}) (+{pts}%)")
            else:
                score += 5
                reasons.append("Standard-Fähigkeitenprofil (+5%)")
        else:
            score += 10
            reasons.append("Allgemeine Qualifikationsanforderungen (+10%)")

        # -------------------------------------------------------------------
        # D. Location Compatibility (up to 10 pts)
        # -------------------------------------------------------------------
        if candidate_city:
            loc_combined = f"{job_location} {desc_lower}"
            if candidate_city in loc_combined:
                score += 10
                reasons.append(f"Standort übereinstimmend ({candidate_city.title()}) (+10%)")
            elif any(r in loc_combined for r in ["remote", "deutschlandweit", "homeoffice", "home-office"]):
                score += 8
                reasons.append("Remote / deutschlandweite Ausübung möglich (+8%)")
            else:
                score += 4
                reasons.append("Standort regional abweichend (+4%)")
        else:
            score += 8
            reasons.append("Standortanforderung flexibel (+8%)")

        # -------------------------------------------------------------------
        # E. Language / Education Compatibility (up to 10 pts)
        # -------------------------------------------------------------------
        score += 10
        reasons.append("Sprach- und Grundbildungsvoraussetzungen erfüllt (+10%)")

        score = max(0, min(100, score))

        # Determine verification status
        if target_clean and title_score == 0:
            status = STATUS_NO_MATCHING_VACANCY
            score = min(score, 25)
        elif score >= 60:
            status = STATUS_OPEN_VERIFIED
        elif score >= 35:
            status = STATUS_POTENTIALLY_OPEN
        else:
            status = STATUS_NO_MATCHING_VACANCY

        return score, reasons, status

    # -----------------------------------------------------------------------
    # 5. Full Business Opportunity Verification
    # -----------------------------------------------------------------------

    def verify_business_opportunities(
        self,
        business: Dict[str, Any],
        target_title: str = "",
        job_type: str = "both",
        client_id: str = "",
        candidate_profile: Optional[Dict[str, Any]] = None,
        driver=None,
    ) -> Dict[str, Any]:
        """
        Executes career page discovery, job vacancy extraction, application URL
        classification, and opportunity verification for a single business.
        Updates business dict in place and returns it.
        """
        name = str(business.get("name") or business.get("company") or "Unbekannt").strip()
        website = str(business.get("website") or business.get("url") or "").strip()
        maps_url = str(business.get("maps_url") or "").strip()

        # Generate company ID for queue integration
        company_id = generate_company_id(name, website)
        business["company_id"] = company_id
        business["client_id"] = client_id

        # Defaults for recruitment fields
        business["has_career_page"] = False
        business["career_page"] = ""
        business["vacancies"] = []
        business["vacancies_count"] = 0
        business["has_verified_vacancy"] = False
        business["primary_job_title"] = ""
        business["primary_apply_url"] = ""
        business["primary_apply_method"] = "None"
        business["primary_url_type"] = URL_UNKNOWN
        business["primary_verification_status"] = STATUS_UNKNOWN
        business["primary_matching_score"] = 0
        business["primary_matching_reasons"] = []
        business["ausbildung_available"] = False
        business["employment_available"] = False

        # Step 1: Check website presence
        if not website or not website.startswith("http"):
            business["primary_verification_status"] = STATUS_UNKNOWN
            business["verification_status"] = "missing_website"
            business["is_verified_vacancy"] = False
            return business

        # Step 2: Fetch homepage
        final_home_url, homepage_html = self.fetch_page(website)
        if not homepage_html and driver is not None:
            try:
                driver.get(website)
                from .cookie_handler import accept_cookies
                accept_cookies(driver)
                homepage_html = driver.page_source
                final_home_url = driver.current_url
            except Exception:
                pass

        if not homepage_html:
            business["primary_verification_status"] = STATUS_VERIFICATION_FAILED
            business["verification_status"] = "inaccessible_website"
            business["is_verified_vacancy"] = False
            return business

        # Step 3: Discover career pages
        career_urls = self.discover_career_urls(final_home_url or website, homepage_html)

        # Step 4: Crawl career pages and extract listings
        discovered_vacancies: List[DiscoveredVacancy] = []
        pages_to_inspect = [(final_home_url, homepage_html)]
        valid_career_urls = []
        for curl in career_urls:
            _, c_html = self.fetch_page(curl)
            if c_html and len(c_html.strip()) > 50:
                valid_career_urls.append(curl)
                pages_to_inspect.append((curl, c_html))

        if valid_career_urls:
            business["has_career_page"] = True
            business["career_page"] = valid_career_urls[0]
        else:
            business["has_career_page"] = False
            business["career_page"] = ""

        seen_vacancies: Set[Tuple[str, str]] = set()
        for p_url, p_html in pages_to_inspect:
            raw_listings = self.extract_job_listings_from_html(p_url, p_html, name)
            for r in raw_listings:
                v_title = r["title"]
                v_apply_url = r["direct_application_url"] or r["listing_url"]
                dedup_key = (v_title.strip().lower(), v_apply_url.strip().lower())
                if dedup_key in seen_vacancies:
                    continue
                seen_vacancies.add(dedup_key)

                v_desc = r["description"]
                v_is_azubi = r["is_ausbildung"]

                # Classify URL
                v_url_type = self.classify_application_url(v_apply_url, p_html)

                # Classify method
                has_form = (v_url_type in [URL_DIRECT_APPLICATION_FORM, URL_APPLICATION_PORTAL])
                method, _ = classify_application_method(
                    business.get("emails", [""])[0] if business.get("emails") else "",
                    has_form,
                )
                if v_url_type == URL_APPLICATION_PORTAL:
                    method = "Application Portal"
                elif v_url_type == URL_DIRECT_APPLICATION_FORM:
                    method = "Direct Form"

                # Calculate score
                v_score, v_reasons, v_status = self.calculate_matching_score(
                    job_title=v_title,
                    job_description=v_desc,
                    is_ausbildung=v_is_azubi,
                    target_title=target_title,
                    job_type=job_type,
                    candidate_profile=candidate_profile,
                    job_location=business.get("address", ""),
                )

                vac = DiscoveredVacancy(
                    company_name=name,
                    job_title=v_title,
                    job_description=v_desc,
                    location=business.get("address", ""),
                    employment_type=r["employment_type"],
                    is_ausbildung=v_is_azubi,
                    start_date=r.get("start_date", "ab sofort"),
                    application_deadline=r.get("application_deadline", "k. A."),
                    job_listing_url=r["listing_url"],
                    direct_application_url=v_apply_url,
                    application_method=method,
                    application_url_type=v_url_type,
                    source_website=website,
                    verification_status=v_status,
                    matching_score=v_score,
                    matching_reasons=v_reasons,
                    client_id=client_id,
                    company_id=company_id,
                )
                discovered_vacancies.append(vac)

        # Step 5: Check Initiativbewerbung / General Career Openings
        initiativ_found = False
        for p_url, p_html in pages_to_inspect:
            if re.search(r"initiativ(?:bewerbung)?|spontanbewerbung|bewerben sie sich initiativ", p_html, re.I):
                initiativ_found = True
                break

        # Step 6: Consolidate vacancies and primary recruitment summary
        if discovered_vacancies:
            # Sort by matching score descending
            discovered_vacancies.sort(key=lambda v: -v.matching_score)
            best_vac = discovered_vacancies[0]

            business["vacancies"] = [asdict(v) for v in discovered_vacancies]
            business["vacancies_count"] = len(discovered_vacancies)
            business["primary_job_title"] = best_vac.job_title
            business["primary_apply_url"] = best_vac.direct_application_url
            business["primary_apply_method"] = best_vac.application_method
            business["primary_url_type"] = best_vac.application_url_type
            business["primary_verification_status"] = best_vac.verification_status
            business["primary_matching_score"] = best_vac.matching_score
            business["primary_matching_reasons"] = best_vac.matching_reasons
            business["has_verified_vacancy"] = (best_vac.verification_status == STATUS_OPEN_VERIFIED)

            business["ausbildung_available"] = any(v.is_ausbildung for v in discovered_vacancies)
            business["employment_available"] = any(not v.is_ausbildung for v in discovered_vacancies)

            # Backward-compatibility fields
            business["title"] = best_vac.job_title
            business["apply_url"] = best_vac.direct_application_url
            business["application_method"] = best_vac.application_method
            business["is_verified_vacancy"] = business["has_verified_vacancy"]
            business["verification_status"] = (
                "verified_ausbildung" if (best_vac.is_ausbildung and business["has_verified_vacancy"])
                else "verified_job" if business["has_verified_vacancy"]
                else "no_matching_ausbildung" if (job_type == "ausbildung")
                else "no_matching_job"
            )

        elif business["has_career_page"] or initiativ_found:
            # Company has career page or welcomes unsolicited applications
            status = STATUS_POTENTIALLY_OPEN if initiativ_found else STATUS_NO_MATCHING_VACANCY
            business["primary_verification_status"] = status
            business["primary_matching_score"] = 40 if initiativ_found else 20
            business["primary_matching_reasons"] = [
                "Karriereseite vorhanden, Initiativbewerbungen möglich (+40%)"
                if initiativ_found else
                "Karriereseite geprüft, aktuell keine passende Ausschreibung (+20%)"
            ]
            business["primary_apply_url"] = business["career_page"]
            business["primary_url_type"] = URL_CAREERS_PAGE
            business["primary_apply_method"] = "Career Page"
            business["is_verified_vacancy"] = False
            business["verification_status"] = "no_matching_ausbildung"
        else:
            business["primary_verification_status"] = STATUS_UNKNOWN
            business["primary_matching_score"] = 0
            business["primary_matching_reasons"] = ["Keine Karriereseite auf Website gefunden"]
            business["is_verified_vacancy"] = False
            business["verification_status"] = "no_career_page"

        return business
