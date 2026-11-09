"""
Deep Bewerbungsformular Discovery & Verification Engine.

Actively discovers, navigates, and verifies authentic online application forms
(Bewerbungsformulare), ATS portals, and application workflows for German job listings.
Differentiates between verified application forms, verified workflow entry points,
generic career pages, and original job listings.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Exact 21 columns required in existing Excel export files in exact order
EXCEL_COLUMNS: List[str] = [
    "title",
    "company",
    "location",
    "city",
    "published_date",
    "start_date",
    "hauptberuf",
    "email",
    "phone",
    "source",
    "arbeitsgeber",
    "apply_url",
    "form_link",
    "has_form",
    "application_method",
    "bewerbung_art",
    "bewerbung_link",
    "anrede",
    "vacancies",
    "scraped_at",
    "salary",
]

# Application button and link keywords (German, English, French)
APPLICATION_BUTTON_KEYWORDS = [
    "jetzt bewerben",
    "online bewerben",
    "bewerbung starten",
    "zur bewerbung",
    "bewerben sie sich",
    "über internetseite des arbeitgebers",
    "uber internetseite des arbeitgebers",
    "bewerbungsportal",
    "bewerbungsformular",
    "direkt bewerben",
    "jetzt online bewerben",
    "info zur bewerbung",
    "apply now",
    "apply online",
    "submit application",
    "start application",
    "hier bewerben",
    "online-bewerbung",
    "online bewerbung",
    "bewerbung absenden",
    "bewerbung einreichen",
    "unterlagen einreichen",
    "bewerben",
    "apply",
    "candidater",
    "postuler",
    "postuler en ligne",
]

# Known ATS (Applicant Tracking System) domains used in Germany and internationally
KNOWN_ATS_DOMAINS = [
    "personio.de",
    "personio.net",
    "myworkdayjobs.com",
    "workday.com",
    "softgarden.io",
    "softgarden.de",
    "greenhouse.io",
    "boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "recruitee.com",
    "smartrecruiters.com",
    "d-vinci-easy.com",
    "d-vinci-hr.com",
    "d-vinci.de",
    "coveto.de",
    "prescreen.io",
    "prescreen.app",
    "umantis.com",
    "persis.de",
    "persis",
    "covider.de",
    "rexx-systems.com",
    "rexx.com",
    "successfactors.com",
    "successfactors.eu",
    "bamboohr.com",
    "taleo.net",
    "kenjo.io",
    "workwise.io",
    "onlyfy.com",
    "join.com",
    "haufe.com",
    "successfactors.com",
    "successfactors.eu",
    "taleo.net",
    "jobvite.com",
    "breezy.hr",
    "join.com",
    "stepstone.de",
    "stellenanzeigen.de",
    "rexx-systems.com",
    "rexx.com",
    "perbit.de",
    "perbit-cloud.de",
    "onlyfy.com",
    "workwise.io",
    "campusjaeger.de",
    "jobstairs.de",
]

# Portal listing domains that are merely advertisements or search engines, NOT forms
JOB_PORTAL_DOMAINS = {
    "arbeitsagentur.de",
    "jobboerse.arbeitsagentur.de",
    "rest.arbeitsagentur.de",
    "ausbildung.de",
    "azubiyo.de",
    "aubi-plus.de",
    "ihk.de",
    "ihk-lehrstellenboerse.de",
    "lehrstellenboerse.de",
    "meine-ausbildung-in-deutschland.de",
    "jobs.meine-ausbildung-in-deutschland.de",
    "indexinternet.de",
    "ihk-azubi-stellenmarkt.indexinternet.de",
    "indeed.com",
    "indeed.de",
    "stepstone.de/stellenangebote",
    "stellenanzeigen.de",
    "yourfirm.de",
    "heyjobs.co",
    "hogapage.de",
    "jobs.hogapage.de",
    "bewerbung2go.de",
    "funkeworks.de",
}

CAREER_PATH_CANDIDATES = [
    "/karriere",
    "/karriere/",
    "/jobs",
    "/jobs/",
    "/stellenangebote",
    "/stellenangebote/",
    "/ausbildung",
    "/ausbildung/",
    "/stellen",
    "/stellen/",
    "/offene-stellen",
    "/career",
]

# Classification Categories
STATUS_VERIFIED_FORM = "verified_form"
STATUS_VERIFIED_ENTRY_POINT = "verified_entry_point"
STATUS_GENERIC_CAREERS_PAGE = "generic_careers_page"
STATUS_JOB_AD_ONLY = "job_ad_only"
STATUS_NONE = "none"


@dataclass
class FormDiscoveryResult:
    status: str = STATUS_NONE
    has_form: bool = False
    form_link: str = ""
    bewerbung_link: str = ""
    apply_url: str = ""
    evidence: List[str] = field(default_factory=list)
    final_url: str = ""


class ApplicationFormDiscovery:
    """
    Intelligent layered application form discovery engine.
    Follows redirects, ATS links, iframes, and career pages without losing job opportunities.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int = 8,
        max_hops: int = 3,
    ):
        self.timeout = timeout
        self.max_hops = max_hops
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36 JobScout/2.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
            }
        )
        self.cache: Dict[str, Tuple[str, str]] = {}  # url -> (final_url, html)
        self.domain_cache: Dict[str, FormDiscoveryResult] = {}

    @staticmethod
    def is_job_portal_url(url: str) -> bool:
        """Determines if a URL is an aggregator or original portal listing, not a form."""
        if not url:
            return False
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        for portal in JOB_PORTAL_DOMAINS:
            if portal in netloc or portal in f"{netloc}{path}":
                # Except if it's an explicit apply endpoint on an ATS subpath
                if not any(k in path for k in ["/apply", "/bewerbung-senden", "/bewerbungsformular"]):
                    return True
        return False

    @staticmethod
    def is_known_ats_url(url: str) -> bool:
        """Detects whether a URL belongs to a verified applicant tracking system."""
        if not url:
            return False
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower()
        return any(ats in netloc for ats in KNOWN_ATS_DOMAINS)

    def fetch_page(self, url: str) -> Tuple[str, str]:
        """Fetches page HTML with redirect resolution and caching."""
        if not url or url.startswith("javascript:") or url.startswith("#") or url.startswith("mailto:"):
            return "", ""
        if url in self.cache:
            return self.cache[url]

        try:
            from .rate_limiter import safe_http_get
            resp = safe_http_get(self.session, url, timeout=self.timeout)
            if resp is not None and resp.status_code == 200 and resp.text:
                final_url = resp.url
                html = resp.text

                # Meta-refresh detection (e.g., Ausbildung.de partner/ATS redirect)
                meta_match = re.search(r'<meta[^>]*http-equiv=["\']?refresh["\']?[^>]*content=["\']?[^"\'>]*url=([^"\'\s;>]+)', html, re.IGNORECASE)
                if meta_match:
                    raw_target = meta_match.group(1).strip(" '\"")
                    resolved_target = urljoin(final_url, raw_target)
                    parsed_target = urlparse(resolved_target)
                    if parsed_target.scheme in ("http", "https") and parsed_target.netloc:
                        try:
                            redir_resp = safe_http_get(self.session, resolved_target, timeout=self.timeout)
                            if redir_resp is not None and redir_resp.status_code == 200 and redir_resp.text:
                                final_url = redir_resp.url
                                html = redir_resp.text
                        except Exception as red_err:
                            logger.debug("Meta-refresh redirect follow failed for %s: %s", resolved_target, red_err)

                self.cache[url] = (final_url, html)
                return final_url, html
        except Exception as exc:
            logger.debug("Fetch failed for %s: %s", url, exc)

        return url, ""

    @classmethod
    def verify_form_page(cls, html: str, url: str) -> Tuple[bool, str, List[str]]:
        """
        Inspects destination HTML and URL for concrete evidence of a genuine
        online application form or confirmed workflow entry point.
        """
        if not html:
            return False, STATUS_NONE, []

        evidence: List[str] = []
        parsed = urlparse(url)
        path_lower = (parsed.path or "").lower()

        # Portals like Arbeitsagentur jobdetail are NOT application forms
        if cls.is_job_portal_url(url):
            return False, STATUS_JOB_AD_ONLY, ["job_portal_listing"]

        from services.data_validator import is_advice_or_generic_page, GENERIC_PORTAL_ROOTS
        if is_advice_or_generic_page(url):
            return False, STATUS_NONE, ["generic_advice_page"]

        netloc = (parsed.netloc or "").lower()
        if netloc in GENERIC_PORTAL_ROOTS:
            if not path_lower or path_lower in ("jobs", "stellenangebote", "stellen", "jobsuche"):
                return False, STATUS_JOB_AD_ONLY, ["generic_job_portal_root"]

        soup = BeautifulSoup(html, "html.parser")

        # 1. Check for ATS application workflow endpoints
        if cls.is_known_ats_url(url):
            if any(k in path_lower for k in ["apply", "bewerbung", "candidat", "form", "job"]):
                evidence.append("ats_apply_endpoint")
                return True, STATUS_VERIFIED_FORM, evidence
            evidence.append("ats_workflow_entry")
            return True, STATUS_VERIFIED_ENTRY_POINT, evidence

        # 2. Check for form inputs & candidate data collection
        inputs = soup.find_all(["input", "textarea", "select"])
        input_names: Set[str] = set()
        has_file_upload = False
        has_email_field = False
        has_name_field = False
        has_phone_field = False

        for inp in inputs:
            itype = (inp.get("type") or "text").lower()
            iname = (inp.get("name") or "").lower()
            iid = (inp.get("id") or "").lower()
            iplaceholder = (inp.get("placeholder") or "").lower()
            ihaystack = f"{itype} {iname} {iid} {iplaceholder}"

            input_names.add(ihaystack)

            if itype == "file":
                has_file_upload = True
                evidence.append("input_file_upload")

            if itype == "email" or any(k in ihaystack for k in ["email", "e-mail", "mail"]):
                has_email_field = True
                evidence.append("input_candidate_email")

            if any(k in ihaystack for k in ["vorname", "nachname", "firstname", "lastname", "bewerber", "fullname"]):
                has_name_field = True
                evidence.append("input_candidate_name")

            if itype == "tel" or any(k in ihaystack for k in ["telefon", "phone", "mobil", "handy"]):
                has_phone_field = True
                evidence.append("input_candidate_phone")

        # 3. Check for form submit button
        submit_btn = soup.find(
            lambda tag: tag.name in ["button", "input"]
            and (
                tag.get("type") == "submit"
                or any(
                    k in (tag.get_text() or "").lower() or k in (tag.get("value") or "").lower()
                    for k in [
                        "bewerbung absenden",
                        "jetzt bewerben",
                        "unterlagen senden",
                        "bewerbung einreichen",
                        "submit application",
                    ]
                )
            )
        )
        if submit_btn:
            evidence.append("form_submit_button")

        # 4. Check for embedded ATS iframes (e.g. Personio / Softgarden iframe)
        for iframe in soup.find_all("iframe", src=True):
            isrc = (iframe.get("src") or "").lower()
            if any(ats in isrc for ats in KNOWN_ATS_DOMAINS):
                evidence.append(f"embedded_ats_iframe:{isrc}")
                return True, STATUS_VERIFIED_FORM, evidence

        # Multi-factor evaluation:
        # A true application form requires candidate contact input AND either file upload or submit button
        candidate_fields_count = sum([has_email_field, has_name_field, has_phone_field])
        if (candidate_fields_count >= 2 and (has_file_upload or submit_btn)) or (
            has_file_upload and has_email_field
        ):
            return True, STATUS_VERIFIED_FORM, evidence

        # Entry point evaluation:
        # If the page states "Schritt 1" or has a confirmed apply workflow starter
        page_text = soup.get_text(separator=" ").lower()
        if any(
            wf in page_text
            for wf in [
                "schritt 1 von",
                "bewerbungsformular",
                "online-bewerbungsformular",
                "unterlagen jetzt hochladen",
            ]
        ) and (has_email_field or has_name_field or submit_btn):
            evidence.append("multi_step_workflow_entry")
            return True, STATUS_VERIFIED_ENTRY_POINT, evidence

        # Generic career or listing page fallback
        if any(kw in path_lower for kw in ["karriere", "jobs", "stellenangebote", "career"]):
            return False, STATUS_GENERIC_CAREERS_PAGE, ["generic_career_path"]

        return False, STATUS_NONE, evidence

    @classmethod
    def extract_application_links_from_html(cls, html: str, base_url: str) -> List[str]:
        """
        Extracts candidate application links, buttons, and iframes from page HTML.
        Prioritizes links with explicit 'Jetzt bewerben' text and ATS domains.
        """
        if not html:
            return []

        candidates: List[str] = []
        seen: Set[str] = {base_url.rstrip("/")}

        try:
            soup = BeautifulSoup(html, "html.parser")
            # Remove site navigation, header, footer, and sidebar recommendation cards to prevent cross-job contamination
            for noise in soup.find_all(["nav", "header", "footer"]):
                noise.decompose()
            for noise_div in soup.find_all(
                "div",
                class_=lambda c: c and any(k in " ".join(c if isinstance(c, list) else [c]).lower() for k in ["job-offer-teaser", "similar-jobs", "recommended", "footer", "mega-menu"]),
            ):
                noise_div.decompose()

            # 1. Prioritize ATS iframes
            for iframe in soup.find_all("iframe", src=True):
                isrc = urljoin(base_url, (iframe.get("src") or "").strip())
                if cls.is_known_ats_url(isrc) and isrc not in seen:
                    seen.add(isrc)
                    candidates.append(isrc)

            # 2. Extract anchor links
            for a_tag in soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                    continue

                full_url = urljoin(base_url, href)
                if full_url in seen:
                    continue

                from services.data_validator import is_advice_or_generic_page
                if is_advice_or_generic_page(full_url):
                    continue

                text = (a_tag.get_text() or "").strip().lower()
                title_attr = (a_tag.get("title") or "").strip().lower()
                aria_label = (a_tag.get("aria-label") or "").strip().lower()
                class_str = " ".join(a_tag.get("class", [])).lower()
                haystack = f"{text} {title_attr} {aria_label} {class_str} {full_url.lower()}"

                # Exclude advice/guide keywords in text
                if any(bad in haystack for bad in ["ratgeber", "tipps", "magazin", "faq", "hilfe"]):
                    continue

                # Direct match for application button keywords or ATS
                is_apply_button = any(kw in haystack for kw in APPLICATION_BUTTON_KEYWORDS)
                is_ats = cls.is_known_ats_url(full_url)

                if is_apply_button or is_ats:
                    seen.add(full_url)
                    # ATS links take precedence
                    if is_ats:
                        candidates.insert(0, full_url)
                    else:
                        candidates.append(full_url)

            # 3. Check for onclick JavaScript navigation on buttons
            for btn in soup.find_all(["button", "div", "span", "a"], onclick=True):
                onclick = btn.get("onclick", "")
                url_match = re.search(
                    r"(?:location(?:\.href|\.assign|\.replace)?|window\.location(?:\.href|\.assign|\.replace)?|window\.open)\s*(?:=|\()\s*['\"]([^'\"]+)['\"]",
                    onclick,
                    re.IGNORECASE,
                )
                if url_match:
                    full_url = urljoin(base_url, url_match.group(1).strip())
                    btn_text = (btn.get_text() or "").lower()
                    if full_url not in seen and (
                        any(kw in btn_text for kw in APPLICATION_BUTTON_KEYWORDS)
                        or cls.is_known_ats_url(full_url)
                    ):
                        seen.add(full_url)
                        candidates.append(full_url)

        except Exception as exc:
            logger.debug("Failed parsing application links from HTML: %s", exc)

        return candidates[:8]

    def find_company_career_fallback(self, company: str, base_url: str = "") -> Optional[str]:
        """Discovers company career page as unverified fallback when no direct form exists."""
        if not base_url:
            return None

        from services.employer_cache import is_non_employer_domain
        if self.is_job_portal_url(base_url) or is_non_employer_domain(base_url):
            return None

        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        root_domain = f"{parsed.scheme}://{parsed.netloc}"

        for path in CAREER_PATH_CANDIDATES:
            cand = urljoin(root_domain, path)
            final_url, html = self.fetch_page(cand)
            if html:
                return final_url

        return None

    def discover_application_form(
        self,
        job: Dict,
        driver=None,
    ) -> FormDiscoveryResult:
        """
        Executes the 5-step deep application form discovery workflow.
        Returns a FormDiscoveryResult with verified status, confirmed link, or fallback.
        """
        original_apply_url = str(job.get("apply_url") or job.get("form_link") or job.get("url") or "").strip()
        job_url = str(job.get("url") or "").strip()
        start_url = original_apply_url or job_url
        company = str(job.get("company") or "").strip()

        result = FormDiscoveryResult(
            apply_url=original_apply_url or job_url,
            bewerbung_link=start_url,
        )

        if not start_url:
            return result

        # Check domain cache to avoid repeated requests to same company
        cache_key = f"{start_url}|{company}"
        if cache_key in self.domain_cache:
            cached = self.domain_cache[cache_key]
            return FormDiscoveryResult(
                status=cached.status,
                has_form=cached.has_form,
                form_link=cached.form_link,
                bewerbung_link=cached.bewerbung_link or start_url,
                apply_url=original_apply_url or job_url,
                evidence=list(cached.evidence),
                final_url=cached.final_url,
            )

        # Step 1: Inspect start URL
        final_start_url, start_html = self.fetch_page(start_url)
        if not start_html and driver is not None:
            # Fall back to Selenium DOM if request failed or was protected
            try:
                current_driver_url = driver.current_url
                if current_driver_url and start_url in current_driver_url:
                    start_html = driver.page_source
                    final_start_url = current_driver_url
            except Exception:
                pass

        if start_html:
            is_verified, status_type, evidence = self.verify_form_page(start_html, final_start_url)
            if is_verified:
                result.status = status_type
                result.has_form = True
                result.form_link = final_start_url
                result.bewerbung_link = final_start_url
                result.final_url = final_start_url
                result.evidence = evidence
                self.domain_cache[cache_key] = result
                return result

        # Step 2: Follow application links from the listing
        candidate_links = self.extract_application_links_from_html(start_html, final_start_url or start_url)

        # Selenium fallback if HTML did not yield candidate links
        if not candidate_links and driver is not None:
            try:
                from selenium.webdriver.common.by import By

                links = driver.find_elements(By.XPATH, "//a[@href]")
                for el in links:
                    try:
                        href = el.get_attribute("href")
                        text = (el.text or "").strip().lower()
                        if any(kw in text for kw in APPLICATION_BUTTON_KEYWORDS) or self.is_known_ats_url(href):
                            if href and href not in candidate_links:
                                candidate_links.append(href)
                    except Exception:
                        continue
            except Exception:
                pass

        visited: Set[str] = {start_url, final_start_url}
        for link in candidate_links[:self.max_hops]:
            if link in visited:
                continue
            visited.add(link)

            cand_final_url, cand_html = self.fetch_page(link)
            if not cand_html:
                continue

            is_verified, status_type, evidence = self.verify_form_page(cand_html, cand_final_url)
            if is_verified:
                result.status = status_type
                result.has_form = True
                result.form_link = cand_final_url
                result.bewerbung_link = cand_final_url
                result.final_url = cand_final_url
                result.evidence = evidence
                self.domain_cache[cache_key] = result
                return result

            # Hop 2: Destination might be a job detail page on company site with another 'Bewerben' button
            sub_links = self.extract_application_links_from_html(cand_html, cand_final_url)
            for sub in sub_links[:2]:
                if sub in visited:
                    continue
                visited.add(sub)
                sub_final_url, sub_html = self.fetch_page(sub)
                if not sub_html:
                    continue
                sub_verified, sub_status, sub_evidence = self.verify_form_page(sub_html, sub_final_url)
                if sub_verified:
                    result.status = sub_status
                    result.has_form = True
                    result.form_link = sub_final_url
                    result.bewerbung_link = sub_final_url
                    result.final_url = sub_final_url
                    result.evidence = sub_evidence
                    self.domain_cache[cache_key] = result
                    return result

        # Step 3: Search Company Career Page as fallback
        career_fallback = self.find_company_career_fallback(company, final_start_url or start_url)
        if career_fallback:
            result.status = STATUS_GENERIC_CAREERS_PAGE
            result.has_form = False
            result.form_link = ""  # Never fill form_link with generic unverified fallback
            result.bewerbung_link = career_fallback
            result.evidence = ["company_career_page_fallback"]
            self.domain_cache[cache_key] = result
            return result

        # Step 5: Smart Fallback (Original listing URL preserved, has_form=False)
        result.status = STATUS_JOB_AD_ONLY if self.is_job_portal_url(start_url) else STATUS_NONE
        result.has_form = False
        result.form_link = ""
        result.bewerbung_link = start_url
        result.evidence = ["preserved_original_url_fallback"]
        self.domain_cache[cache_key] = result
        return result


def classify_application_method(
    email: Optional[str],
    has_form: bool,
    existing_method: str = "",
    direct_url: str = "",
) -> Tuple[str, str]:
    """
    Standard application method and art classifier matching the specification:
    | Email available | Verified online form | application_method | bewerbung_art |
    | Yes             | No                   | email              | E-Mail |
    | No              | Yes                  | form               | Online-Formular |
    | Yes             | Yes                  | both               | E-Mail + Online-Formular |
    | No              | No                   | unknown            | Unbekannt |
    Also supports portal / external_link, phone, and postal channels.
    """
    clean_email = str(email or "").strip().lower()
    has_valid_email = bool(
        clean_email
        and "@" in clean_email
        and not clean_email.startswith("error:")
        and clean_email != "captcha_failed"
        and clean_email != "duplicate_email_skipped"
    )

    em = str(existing_method or "").strip().lower()
    has_direct_url = bool(direct_url and not ApplicationFormDiscovery.is_job_portal_url(direct_url))

    if has_valid_email and (has_form or has_direct_url):
        return "both", "E-Mail + Online-Formular"
    if has_valid_email:
        return "email", "E-Mail"
    if has_form:
        return "form", "Online-Formular"
    if has_direct_url or em in {"external_link", "portal"}:
        return "external_link", "Online-Portal / Link"
    if em == "phone":
        return "phone", "Telefon"
    if em in {"postal", "schriftlich"}:
        return "postal", "Post / Schriftlich"
    if em in {"portal_login_required", "portal_login"}:
        return "portal_login_required", "Portal-Registrierung erforderlich"
    if em in {"none", "keine"}:
        return "none", "Keine"
    return "unknown", "Unbekannt"


def normalize_job_opportunity_row(
    job: Dict,
    discovery_result: Optional[FormDiscoveryResult] = None,
) -> Dict:
    """
    Normalizes a job dictionary into the exact 21-column Excel schema in exact order.
    Preserves all discovered job opportunities regardless of email availability.
    Enforces strict data quality on listing URLs, phones, recruiters, and form links.
    """
    row = dict(job or {})
    from services.data_validator import (
        validate_job_listing_url,
        validate_phone_number,
        sanitize_contact_person,
        validate_application_url,
        validate_form_link,
        is_advice_or_generic_page,
    )

    # 1. Extract or preserve email (and verify employer compatibility)
    from services.contamination_detector import (
        PORTAL_SUPPORT_PHONES,
        is_email_compatible_with_employer,
        is_url_compatible_with_job,
    )
    company_str = str(row.get("company") or row.get("firma") or "").strip()
    raw_email = row.get("email")
    clean_email = str(raw_email or "").strip().lower()
    has_valid_email = bool(
        clean_email
        and "@" in clean_email
        and not clean_email.startswith("error:")
        and clean_email != "captcha_failed"
        and clean_email != "duplicate_email_skipped"
    )
    if has_valid_email:
        email_compat, _ = is_email_compatible_with_employer(clean_email, company_str)
        if not email_compat:
            has_valid_email = False
    email_val = clean_email if has_valid_email else ""

    # 2. Preserve genuine job listing URL (never overwrite with advice page)
    orig_listing_cand = str(row.get("job_listing_url") or row.get("url") or row.get("original_url") or "").strip()
    if is_advice_or_generic_page(orig_listing_cand):
        alt_cand = str(row.get("url") or row.get("original_url") or "").strip()
        if not is_advice_or_generic_page(alt_cand):
            orig_listing_cand = alt_cand

    is_list_ok, clean_listing, _ = validate_job_listing_url(orig_listing_cand)
    job_listing_url = clean_listing or (orig_listing_cand if not is_advice_or_generic_page(orig_listing_cand) else "")

    # 3. Application destination URL (apply_url)
    raw_apply = str(row.get("apply_url") or "").strip()
    is_app_ok, clean_apply_url, _ = validate_application_url(raw_apply)
    apply_url = clean_apply_url if (is_app_ok and not is_advice_or_generic_page(clean_apply_url)) else job_listing_url

    # 4. Direct application URL / mailto correction
    raw_direct = str(row.get("direct_application_url") or "").strip()
    if "mailto:" in raw_direct.lower():
        m = re.search(r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", raw_direct, re.I)
        if m and not email_val:
            cand_m = m.group(1).lower()
            m_ok, _ = is_email_compatible_with_employer(cand_m, company_str)
            if m_ok:
                email_val = cand_m
        direct_app_url = ""
    else:
        is_dir_ok, clean_dir_url, _ = validate_application_url(raw_direct)
        if is_dir_ok:
            is_dir_ok, _ = is_url_compatible_with_job(clean_dir_url, company=company_str, job_listing_url=job_listing_url)
        direct_app_url = clean_dir_url if is_dir_ok else ""

    # 5. Form discovery validation (reject generic portal roots like jobs.hogapage.de)
    if discovery_result is not None:
        raw_has_form = bool(discovery_result.has_form)
        raw_form_link = str(discovery_result.form_link or "").strip() if raw_has_form else ""
        is_form_valid, form_link, _ = validate_form_link(raw_form_link, has_form=raw_has_form)
        if is_form_valid:
            is_form_valid, _ = is_url_compatible_with_job(form_link, company=company_str, job_listing_url=job_listing_url)
        has_form = is_form_valid
        form_link = form_link if is_form_valid else ""
        raw_bewerbung_link = str(discovery_result.bewerbung_link or apply_url or job_listing_url or "").strip()
    else:
        raw_has_form = bool(row.get("has_form") is True or str(row.get("has_form")).lower() in {"true", "1"})
        raw_form_link = str(row.get("form_link") or (row.get("direct_application_url") if raw_has_form else "") or "").strip()
        is_form_valid, form_link, _ = validate_form_link(raw_form_link, has_form=raw_has_form)
        if is_form_valid:
            is_form_valid, _ = is_url_compatible_with_job(form_link, company=company_str, job_listing_url=job_listing_url)
        has_form = is_form_valid
        form_link = form_link if is_form_valid else ""
        raw_bewerbung_link = str(row.get("bewerbung_link") or form_link or apply_url or job_listing_url or "").strip()

    if not direct_app_url and has_form and form_link:
        direct_app_url = form_link

    # Clean bewerbung_link of advice pages or malformed mailto
    if is_advice_or_generic_page(raw_bewerbung_link) or "mailto:" in raw_bewerbung_link.lower():
        bewerbung_link = direct_app_url or job_listing_url
    else:
        bewerbung_link = raw_bewerbung_link or direct_app_url or job_listing_url

    # 6. Phone number validation (reject fragments, coordinates, dates, portal support hotlines)
    raw_phone = row.get("phone")
    if raw_phone is None or str(raw_phone).strip().lower() in ("nan", "none", "null", ""):
        phone_val = ""
    else:
        is_phone_ok, clean_phone, _ = validate_phone_number(str(raw_phone))
        phone_val = clean_phone if (is_phone_ok and clean_phone not in PORTAL_SUPPORT_PHONES) else ""

    # 7. Recruiter / Contact person sanitization (strip addresses, street markers)
    raw_contact = row.get("contact_person") or row.get("arbeitsgeber")
    if raw_contact is None or str(raw_contact).strip().lower() in ("nan", "none", "null", ""):
        contact_val = ""
    else:
        is_cp_ok, clean_cp, _ = sanitize_contact_person(str(raw_contact))
        contact_val = clean_cp if is_cp_ok else ""
    arbeitsgeber = contact_val

    # Method inference
    existing_method = str(row.get("application_method") or "").strip()
    src_val = str(row.get("source") or "").lower()
    if ("ihk" in src_val or "ihk" in job_listing_url) and not email_val and not has_form and not direct_app_url:
        if row.get("postal_only") or "schriftlich" in str(row.get("bewerbungsart", "")).lower() or "post" in str(row.get("bewerbungsart", "")).lower() or existing_method in ("postal", "schriftlich"):
            existing_method = "postal"

    if ("azubiyo" in src_val or "azubiyo" in job_listing_url) and not email_val and not has_form and not direct_app_url:
        if row.get("portal_application_only") or row.get("is_portal_login_required") or row.get("portal_login_required") or "login" in str(row.get("bewerbungsart", "")).lower() or "registrier" in str(row.get("bewerbungsart", "")).lower() or existing_method in ("portal_login_required", "portal_login"):
            existing_method = "portal_login_required"

    app_method, bewerbung_art = classify_application_method(
        email_val,
        has_form,
        existing_method=existing_method,
        direct_url=direct_app_url,
    )

    # Anrede calculation
    contact = contact_val.lower()
    if contact.startswith("herr") or contact.startswith("herrn"):
        anrede = "Sehr geehrter"
    elif contact.startswith("frau"):
        anrede = "Sehr geehrte"
    else:
        anrede = "Sehr geehrte Damen und Herren"

    email_type = str(row.get("email_type") or ("recruitment" if email_val else "")).strip()
    employer_website = str(row.get("employer_website") or "").strip()
    application_url_type = str(row.get("application_url_type") or ("direct_form" if has_form else ("postal" if app_method == "postal" else ("portal_login" if app_method == "portal_login_required" else "none")))).strip()
    if not has_form and application_url_type == "direct_form":
        application_url_type = "career_portal" if direct_app_url else "none"

    required_documents = str(row.get("required_documents") or "").strip()
    default_status = "completed" if (email_val or has_form or direct_app_url or app_method in ("postal", "portal_login_required")) else "unresolved"
    extraction_status = str(row.get("extraction_status") or default_status).strip()
    if app_method == "portal_login_required" and extraction_status in ("unresolved", "failed"):
        extraction_status = "completed"
    app_methods = row.get("application_methods") or ([app_method] if app_method not in ("unknown", "none") else [])

    out = {
        "title": str(row.get("title") or "N/A"),
        "company": str(row.get("company") or "N/A"),
        "location": str(row.get("location") or "N/A"),
        "city": str(row.get("city") or "N/A"),
        "published_date": str(row.get("published_date") or "N/A"),
        "start_date": str(row.get("start_date") or "N/A"),
        "hauptberuf": str(row.get("hauptberuf") or "N/A"),
        "email": email_val,
        "phone": phone_val,
        "source": str(row.get("source") or "Arbeitsagentur"),
        "arbeitsgeber": contact_val,
        "apply_url": apply_url,
        "form_link": form_link,
        "has_form": has_form,
        "application_method": app_method,
        "bewerbung_art": bewerbung_art,
        "bewerbung_link": bewerbung_link,
        "anrede": anrede,
        "vacancies": str(row.get("vacancies") or ""),
        "scraped_at": str(row.get("scraped_at") or time.strftime("%Y-%m-%d %H:%M")),
        "salary": str(row.get("salary") or ""),
        # Extended fields for full application details
        "email_type": email_type,
        "email_extracted": bool(email_val and "@" in email_val),
        "manual_review_required": bool(row.get("manual_review_required")),
        "contact_person": contact_val,
        "job_listing_url": job_listing_url,
        "employer_website": employer_website,
        "direct_application_url": direct_app_url,
        "application_url_type": application_url_type,
        "required_documents": required_documents,
        "extraction_status": extraction_status,
        "application_methods": app_methods,
        "extraction_method": str(row.get("extraction_method") or "").strip(),
    }
    # Preserve provenance and diagnostic metadata when present
    for prov_key in (
        "email_source_url",
        "email_source_section",
        "email_verified",
        "application_url_source",
        "application_url_verified",
        "form_link_source",
        "form_link_verified",
        "phone_source",
        "phone_verified",
        "contact_person_source",
        "contact_person_verified",
        "validation_status",
        "validation_reason",
        "contact_provenance",
        "raw_candidates",
        "extraction_completed",
        "manual_review_reason",
    ):
        if prov_key in row:
            out[prov_key] = row[prov_key]
    return out
