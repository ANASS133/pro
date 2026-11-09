"""
Dedicated Detail Extractor for Ausbildung.de.

Implements the strict 5-step extraction strategy:
1. Open and isolate each job listing (prevent cross-job state leakage)
2. Prioritize "Weitere Bewerbungsoptionen" -> "Per E-Mail bewerben"
3. Search the entire job page (DOM, mailto links, contact / recruiter sections)
4. Click "Jetzt bewerben" when no email is found (external ATS, internal direktbewerbung, modal, tab)
5. Conform to Excel output rules (mutually exclusive email vs application form columns)
"""

import json
import logging
import re
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper.application_form_discovery import ApplicationFormDiscovery, normalize_job_opportunity_row
from scraper.cookie_handler import accept_cookies
from services.contamination_detector import attach_contact_provenance
from services.data_validator import validate_phone_number, sanitize_contact_person
from services.employer_cache import is_shortener_domain

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Email domains belonging to portal infrastructure, tracking, or mock/examples
EMAIL_BLACKLIST = {
    "ausbildung.de",
    "funkeworks.de",
    "funke-digital.de",
    "funke.de",
    "example.com",
    "sentry.io",
    "wix.com",
    "google.com",
    "u003c",
}


def is_valid_application_email(email_str: str) -> bool:
    """Validates email format and ensures it does not belong to the portal/tracking blacklist."""
    if not email_str:
        return False
    clean = str(email_str).strip().lower()
    if not EMAIL_PATTERN.match(clean):
        return False
    domain = clean.split("@")[-1].strip()
    if any(domain == b or domain.endswith("." + b) for b in EMAIL_BLACKLIST):
        return False
    return True


class AusbildungDeDetailExtractor:
    """Extracts application email or application form URL for individual Ausbildung.de listings."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

    def extract_vacancy(
        self,
        job: Dict[str, Any],
        driver: Optional[Any] = None,
        session: Optional[requests.Session] = None,
        on_stage_change: Optional[Callable[[str], None]] = None,
        worker_id: int = 1,
    ) -> Dict[str, Any]:
        """
        Executes the staged Ausbildung.de extraction pipeline.
        Isolates state completely per job and returns normalized job dictionary.
        """
        job_url = str(job.get("url") or job.get("job_listing_url") or "").strip()
        employer = str(job.get("company") or job.get("firma") or "N/A").strip()
        job_id = str(job.get("job_id") or job.get("reference") or job_url[:60]).strip()

        # Step 1: Initialize completely isolated record for this job
        norm_job = dict(job)
        norm_job["email"] = ""
        norm_job["email_extracted"] = False
        norm_job["has_form"] = False
        norm_job["form_link"] = ""
        norm_job["direct_application_url"] = ""
        norm_job["bewerbung_link"] = ""
        norm_job["apply_url"] = job_url

        req_session = session or self.session

        # Step 7 / Fast-Path: Try rapid HTTP parsing first (~150ms)
        http_res = self._extract_via_fast_http(norm_job, req_session, worker_id=worker_id)
        if http_res is not None:
            # If fast HTTP found an explicit email or direct external ATS form URL, return it immediately
            if http_res.get("email") or http_res.get("has_form"):
                if on_stage_change:
                    on_stage_change("Email Extraction" if http_res.get("email") else "Finding Application Form")
                return normalize_job_opportunity_row(http_res)

        # Fallback to interactive Selenium extraction
        if driver is not None:
            if on_stage_change:
                on_stage_change("Selenium Fallback")
            sel_res = self._extract_via_selenium(
                norm_job,
                driver,
                on_stage_change=on_stage_change,
                worker_id=worker_id,
            )
            return normalize_job_opportunity_row(sel_res)

        # If driver is unavailable and HTTP produced no result, mark for review (Step 5)
        self._record_audit_log(
            worker_id=worker_id,
            job_id=job_id,
            url=job_url,
            employer=employer,
            weitere_optionen_found=False,
            weitere_optionen_expanded=False,
            per_email_bewerben_found=False,
            extracted_email="",
            email_source_location="N/A",
            full_page_fallback_used=True,
            jetzt_bewerben_clicked=False,
            final_destination="",
            extraction_status="review_required",
            status_reason="No application method discovered and Selenium driver unavailable",
        )
        norm_job["extraction_status"] = "review_required"
        norm_job["extraction_completed"] = True
        norm_job["manual_review_required"] = True
        norm_job["manual_review_reason"] = "No application method (email or form) could be discovered on Ausbildung.de"
        norm_job["validation_status"] = "no_contact"
        norm_job["validation_reason"] = norm_job["manual_review_reason"]
        return normalize_job_opportunity_row(norm_job)

    def _extract_scoped_phone_and_contact(self, html: str, job_url: str = "") -> Tuple[str, str]:
        """Extracts phone and contact person strictly from the current job listing body/JSON-LD."""
        phone_out = ""
        contact_out = ""
        if not html:
            return phone_out, contact_out

        from services.contamination_detector import PORTAL_SUPPORT_PHONES
        try:
            soup = BeautifulSoup(html, "html.parser")
            for noise in soup.find_all(["nav", "header", "footer"]):
                noise.decompose()

            # 1. Check JSON-LD JobPosting description
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    ld_raw = json.loads(script.string or "")
                    ld_list = ld_raw if isinstance(ld_raw, list) else [ld_raw]
                    for item in ld_list:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            desc = item.get("description") or ""
                            if desc and not phone_out:
                                for m in re.findall(r"(?:tel(?:efon)?\.?|fon|phone|mobil)\s*[:\-\s]\s*([+0-9\s/().\-]{7,25})", desc, re.I):
                                    ok, cp, _ = validate_phone_number(m)
                                    if ok and cp not in PORTAL_SUPPORT_PHONES:
                                        phone_out = cp
                                        break
                            if desc and not contact_out:
                                anspr = re.search(
                                    r"(?:Ansprechpartner(?:in)?|Kontaktperson)\s*[:\-]\s*([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\s\.\-]{3,45})",
                                    BeautifulSoup(desc, "html.parser").get_text(" ", strip=True),
                                    re.I,
                                )
                                if anspr:
                                    ok, c_name, _ = sanitize_contact_person(anspr.group(1))
                                    if ok:
                                        contact_out = c_name
                except Exception:
                    pass

            # 2. Check main content tel: links and labeled Telefon cues
            main_node = soup.find("main") or soup.find("article") or soup.body or soup
            if not phone_out and main_node:
                for tel_a in main_node.find_all("a", href=lambda h: h and h.lower().startswith("tel:")):
                    raw_t = tel_a.get("href", "")[4:].strip()
                    ok, cp, _ = validate_phone_number(raw_t)
                    if ok and cp not in PORTAL_SUPPORT_PHONES:
                        phone_out = cp
                        break

            if not phone_out and main_node:
                text_content = main_node.get_text("\n", strip=True)
                for m in re.findall(r"(?:tel(?:efon)?\.?|fon|phone|mobil)\s*[:\-\s]\s*([+0-9\s/().\-]{7,25})", text_content, re.I):
                    ok, cp, _ = validate_phone_number(m)
                    if ok and cp not in PORTAL_SUPPORT_PHONES:
                        phone_out = cp
                        break

            if not contact_out and main_node:
                text_content = main_node.get_text("\n", strip=True)
                anspr = re.search(
                    r"(?:Ansprechpartner(?:in)?|Kontaktperson)\s*[:\-]\s*([^\n\r<]{3,60})",
                    text_content,
                    re.I,
                )
                if anspr:
                    ok, c_name, _ = sanitize_contact_person(anspr.group(1))
                    if ok:
                        contact_out = c_name
        except Exception as exc:
            logger.debug("[AusbildungDe] Scoped phone/contact extraction error: %s", exc)

        return phone_out, contact_out

    def _extract_via_fast_http(
        self,
        job: Dict[str, Any],
        session: requests.Session,
        worker_id: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Fast HTTP parser extracting Next.js applicationOptions and static contact info."""
        job_url = job.get("url") or job.get("job_listing_url") or ""
        employer = str(job.get("company") or job.get("firma") or "N/A").strip()
        job_id = str(job.get("job_id") or job.get("reference") or job_url[:60]).strip()

        if not job_url or not job_url.startswith("http"):
            return None

        try:
            resp = session.get(job_url, timeout=8, allow_redirects=True)
            if resp.status_code != 200 or not resp.text:
                return None
            html = resp.text

            # Extract scoped phone and contact person for the job
            scoped_phone, scoped_contact = self._extract_scoped_phone_and_contact(html, job_url)
            if scoped_phone and not job.get("phone"):
                job["phone"] = scoped_phone
                job["telefon"] = scoped_phone
                job["phone_source_url"] = job_url
                job["phone_source_section"] = "ausbildung_de_job_detail"
            if scoped_contact and (not job.get("contact_person") or job.get("contact_person") == "N/A"):
                job["contact_person"] = scoped_contact
                job["ansprechpartner"] = scoped_contact

            # Parse Next.js App Router server component applicationOptions payload
            app_opts = self._parse_application_options_from_html(html)

            # Step 2: Prioritize "Weitere Bewerbungsoptionen" -> "Per E-Mail bewerben"
            if app_opts and app_opts.get("email"):
                cand_email = str(app_opts["email"]).strip()
                if is_valid_application_email(cand_email):
                    clean_email = cand_email.lower()
                    job["email"] = clean_email
                    job["email_extracted"] = True
                    job["email_type"] = "recruitment"
                    job["has_form"] = False
                    job["form_link"] = ""
                    job["direct_application_url"] = ""
                    job["bewerbung_link"] = ""
                    job["application_method"] = "email"
                    job["bewerbung_art"] = "E-Mail"
                    job["extraction_method"] = "fast_http"
                    job["extraction_status"] = "success"
                    attach_contact_provenance(
                        job,
                        source_url=job_url,
                        section="weitere_bewerbungsoptionen_per_email",
                        extraction_method="fast_http",
                        verified=True,
                    )
                    job["extraction_status"] = "success"

                    self._record_audit_log(
                        worker_id=worker_id,
                        job_id=job_id,
                        url=job_url,
                        employer=employer,
                        weitere_optionen_found=True,
                        weitere_optionen_expanded=True,
                        per_email_bewerben_found=True,
                        extracted_email=clean_email,
                        email_source_location="Weitere Bewerbungsoptionen (applicationOptions.email)",
                        full_page_fallback_used=False,
                        jetzt_bewerben_clicked=False,
                        final_destination="",
                        extraction_status="success",
                        status_reason="Email found in applicationOptions",
                    )
                    return job

            # Step 3: Search entire page (HTML mailto links and structured text in main content)
            mailtos = re.findall(r'href=["\']mailto:([^"\'\s>]+)["\']', html, re.I)
            if not mailtos:
                # Fallback to labeled contact email in body text
                mailtos = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", html)
            for m_cand in mailtos:
                clean_cand = str(m_cand).strip().split("?")[0].strip().lower()
                if is_valid_application_email(clean_cand):
                    job["email"] = clean_cand
                    job["email_extracted"] = True
                    job["email_type"] = "recruitment"
                    job["has_form"] = False
                    job["form_link"] = ""
                    job["direct_application_url"] = ""
                    job["bewerbung_link"] = ""
                    job["application_method"] = "email"
                    job["bewerbung_art"] = "E-Mail"
                    job["extraction_method"] = "fast_http"
                    job["extraction_status"] = "success"
                    attach_contact_provenance(
                        job,
                        source_url=job_url,
                        section="ausbildung_de_full_page_contact",
                        extraction_method="fast_http",
                        verified=True,
                    )
                    job["extraction_status"] = "success"

                    self._record_audit_log(
                        worker_id=worker_id,
                        job_id=job_id,
                        url=job_url,
                        employer=employer,
                        weitere_optionen_found=False,
                        weitere_optionen_expanded=False,
                        per_email_bewerben_found=False,
                        extracted_email=clean_cand,
                        email_source_location="Full page contact section (mailto)",
                        full_page_fallback_used=True,
                        jetzt_bewerben_clicked=False,
                        final_destination="",
                        extraction_status="success",
                        status_reason="Email found in full-page HTML mailto links",
                    )
                    return job

            # Step 4: Check if direct application form URL is present in applicationOptions
            if app_opts and app_opts.get("url"):
                target_url = str(app_opts["url"]).strip()
                if target_url.startswith("/"):
                    target_url = urllib.parse.urljoin("https://www.ausbildung.de", target_url)
                elif is_shortener_domain(target_url):
                    try:
                        s_resp = session.get(target_url, timeout=4, allow_redirects=True, stream=True)
                        resolved_target = str(s_resp.url or "").strip()
                        s_resp.close()
                        if resolved_target and not is_shortener_domain(resolved_target):
                            target_url = resolved_target
                    except Exception:
                        pass

                if target_url.startswith("http") and not target_url.endswith("/ratgeber/bewerbung/"):
                    job["email"] = ""
                    job["email_extracted"] = False
                    job["has_form"] = True
                    job["form_link"] = target_url
                    job["direct_application_url"] = target_url
                    job["bewerbung_link"] = target_url
                    job["extraction_method"] = "fast_http"
                    if "ausbildung.de/direktbewerbung" in target_url:
                        job["application_method"] = "portal_form"
                        job["application_url_type"] = "internal_direktbewerbung"
                        job["bewerbung_art"] = "Online-Formular (Ausbildung.de Direktbewerbung)"
                    else:
                        job["application_method"] = "external_form"
                        job["application_url_type"] = "external_ats"
                        job["bewerbung_art"] = "Online-Formular (Arbeitgeber / ATS)"
                    attach_contact_provenance(
                        job,
                        source_url=job_url,
                        section="ausbildung_de_application_options_url",
                        extraction_method="fast_http",
                        verified=True,
                    )
                    job["extraction_status"] = "form_found"

                    self._record_audit_log(
                        worker_id=worker_id,
                        job_id=job_id,
                        url=job_url,
                        employer=employer,
                        weitere_optionen_found=False,
                        weitere_optionen_expanded=False,
                        per_email_bewerben_found=False,
                        extracted_email="",
                        email_source_location="N/A",
                        full_page_fallback_used=True,
                        jetzt_bewerben_clicked=False,
                        final_destination=target_url,
                        extraction_status="form_found",
                        status_reason="Application destination URL found in applicationOptions.url",
                    )
                    return job

        except Exception as exc:
            logger.debug("[AusbildungDe] Fast HTTP extraction exception for %s: %s", job_url, exc)

        return None

    def _extract_via_selenium(
        self,
        job: Dict[str, Any],
        driver: Any,
        on_stage_change: Optional[Callable[[str], None]] = None,
        worker_id: int = 1,
    ) -> Dict[str, Any]:
        """Interactive browser extraction with full DOM expansion and application form tracing."""
        job_url = job.get("url") or job.get("job_listing_url") or ""
        employer = str(job.get("company") or job.get("firma") or "N/A").strip()
        job_id = str(job.get("job_id") or job.get("reference") or job_url[:60]).strip()

        # Step 1: Open and isolate listing
        self._isolate_browser_state(driver)

        try:
            driver.get(job_url)
        except Exception as get_err:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            logger.debug("[AusbildungDe] WebDriver get() timed out/stopped for %s: %s", job_url, get_err)

        accept_cookies(driver)

        try:
            WebDriverWait(driver, 5.0).until(
                lambda d: d.find_elements(By.TAG_NAME, "h1") or d.find_elements(By.TAG_NAME, "body")
            )
        except Exception:
            pass

        try:
            scoped_phone, scoped_contact = self._extract_scoped_phone_and_contact(driver.page_source or "", job_url)
            if scoped_phone and not job.get("phone"):
                job["phone"] = scoped_phone
                job["telefon"] = scoped_phone
                job["phone_source_url"] = job_url
                job["phone_source_section"] = "ausbildung_de_job_detail"
            if scoped_contact and (not job.get("contact_person") or job.get("contact_person") == "N/A"):
                job["contact_person"] = scoped_contact
                job["ansprechpartner"] = scoped_contact
        except Exception:
            pass

        weitere_optionen_found = False
        weitere_optionen_expanded = False
        per_email_bewerben_found = False
        extracted_email = ""
        email_source_location = ""
        full_page_fallback_used = False
        jetzt_bewerben_clicked = False
        final_destination = ""

        # Step 2: Prioritize "Weitere Bewerbungsoptionen"
        opt_buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(., 'Weitere Bewerbungsoptionen') "
            "or @data-testid='application-options-button' "
            "or contains(@class, 'applicationOptionsButton') "
            "or contains(@aria-label, 'Bewerbungsoptionen')]",
        )

        if opt_buttons:
            weitere_optionen_found = True
            btn = opt_buttons[0]
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", btn)
                time.sleep(0.3)
                try:
                    btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", btn)
                weitere_optionen_expanded = True
                time.sleep(0.6)
            except Exception as click_err:
                logger.debug("[AusbildungDe] Error expanding Weitere Bewerbungsoptionen button: %s", click_err)

            if weitere_optionen_expanded:
                # Look specifically for "Per E-Mail bewerben"
                email_labels = driver.find_elements(By.XPATH, "//*[contains(text(), 'Per E-Mail bewerben')]")
                if email_labels:
                    per_email_bewerben_found = True
                    try:
                        container = email_labels[0].find_element(By.XPATH, "..")
                        # 1. Search mailto link under container
                        mailto_links = container.find_elements(By.XPATH, ".//a[starts-with(@href, 'mailto:')]")
                        for ml in mailto_links:
                            cand = ml.get_attribute("href").replace("mailto:", "").split("?")[0].strip().lower()
                            if is_valid_application_email(cand):
                                extracted_email = cand
                                email_source_location = "Weitere Bewerbungsoptionen → Per E-Mail bewerben (mailto)"
                                break

                        # 2. Text fallback in container
                        if not extracted_email:
                            m_text = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", container.text)
                            if m_text and is_valid_application_email(m_text.group(0)):
                                extracted_email = m_text.group(0).lower()
                                email_source_location = "Weitere Bewerbungsoptionen → Per E-Mail bewerben (text)"
                    except Exception as label_err:
                        logger.debug("[AusbildungDe] Error parsing Per E-Mail bewerben container: %s", label_err)

                # Fallback: check any mailto inside the options dropdown
                if not extracted_email:
                    opt_mailtos = driver.find_elements(
                        By.XPATH,
                        "//*[contains(@class, 'optionWrapper') or contains(@class, 'applicationOptions')]//a[starts-with(@href, 'mailto:')]",
                    )
                    for ml in opt_mailtos:
                        cand = ml.get_attribute("href").replace("mailto:", "").split("?")[0].strip().lower()
                        if is_valid_application_email(cand):
                            extracted_email = cand
                            email_source_location = "Weitere Bewerbungsoptionen dropdown container"
                            break

        if extracted_email:
            job["email"] = extracted_email
            job["email_extracted"] = True
            job["email_type"] = "recruitment"
            job["has_form"] = False
            job["form_link"] = ""
            job["direct_application_url"] = ""
            job["bewerbung_link"] = ""
            job["application_method"] = "email"
            job["bewerbung_art"] = "E-Mail"
            job["extraction_method"] = "selenium"
            attach_contact_provenance(
                job,
                source_url=job_url,
                section="weitere_bewerbungsoptionen_per_email",
                extraction_method="selenium",
                verified=True,
            )
            job["extraction_status"] = "success"

            self._record_audit_log(
                worker_id=worker_id,
                job_id=job_id,
                url=job_url,
                employer=employer,
                weitere_optionen_found=weitere_optionen_found,
                weitere_optionen_expanded=weitere_optionen_expanded,
                per_email_bewerben_found=per_email_bewerben_found,
                extracted_email=extracted_email,
                email_source_location=email_source_location,
                full_page_fallback_used=False,
                jetzt_bewerben_clicked=False,
                final_destination="",
                extraction_status="success",
                status_reason="Email successfully extracted from Weitere Bewerbungsoptionen",
            )
            return job

        # Step 3: Search entire job page
        full_page_fallback_used = True
        try:
            # Check all mailto links in the rendered page
            all_mailtos = driver.find_elements(By.XPATH, "//a[starts-with(@href, 'mailto:')]")
            for ml in all_mailtos:
                cand = ml.get_attribute("href").replace("mailto:", "").split("?")[0].strip().lower()
                if is_valid_application_email(cand):
                    extracted_email = cand
                    email_source_location = "Full page rendered DOM (mailto)"
                    break

            # If not in mailto, check text in contact / recruiter sections
            if not extracted_email:
                contact_nodes = driver.find_elements(
                    By.XPATH,
                    "//*[contains(translate(text(), 'BEWERBUNG', 'bewerbung'), 'bewerb') "
                    "or contains(translate(text(), 'KONTAKT', 'kontakt'), 'kontakt') "
                    "or contains(translate(text(), 'ANSPRECHPARTNER', 'ansprechpartner'), 'ansprechpartner') "
                    "or contains(translate(text(), 'PERSONAL', 'personal'), 'personal')]",
                )
                for cnode in contact_nodes:
                    node_text = getattr(cnode, "text", "") or ""
                    m_txt = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", node_text)
                    if m_txt and is_valid_application_email(m_txt.group(0)):
                        extracted_email = m_txt.group(0).lower()
                        email_source_location = "Full page contact section (labeled text)"
                        break

            # Check Next.js applicationOptions embedded script
            if not extracted_email:
                page_src = driver.page_source or ""
                app_opts = self._parse_application_options_from_html(page_src)
                if app_opts and app_opts.get("email"):
                    cand = str(app_opts["email"]).strip().lower()
                    if is_valid_application_email(cand):
                        extracted_email = cand
                        email_source_location = "Full page embedded JSON (applicationOptions.email)"

        except Exception as full_err:
            logger.debug("[AusbildungDe] Error searching full page for email: %s", full_err)

        if extracted_email:
            job["email"] = extracted_email
            job["email_extracted"] = True
            job["email_type"] = "recruitment"
            job["has_form"] = False
            job["form_link"] = ""
            job["direct_application_url"] = ""
            job["bewerbung_link"] = ""
            job["application_method"] = "email"
            job["bewerbung_art"] = "E-Mail"
            job["extraction_method"] = "selenium"
            attach_contact_provenance(
                job,
                source_url=job_url,
                section="weitere_bewerbungsoptionen_per_email",
                extraction_method="selenium",
                verified=True,
            )
            job["extraction_status"] = "success"

            self._record_audit_log(
                worker_id=worker_id,
                job_id=job_id,
                url=job_url,
                employer=employer,
                weitere_optionen_found=weitere_optionen_found,
                weitere_optionen_expanded=weitere_optionen_expanded,
                per_email_bewerben_found=per_email_bewerben_found,
                extracted_email=extracted_email,
                email_source_location=email_source_location,
                full_page_fallback_used=True,
                jetzt_bewerben_clicked=False,
                final_destination="",
                extraction_status="success",
                status_reason="Email found in full page contact / recruiter section",
            )
            return job

        # Step 4: Click "Jetzt bewerben" when no email is found
        if on_stage_change:
            on_stage_change("Finding Application Form")

        apply_btns = driver.find_elements(
            By.XPATH,
            "//*[contains(translate(text(), 'JETZTBEWERBEN', 'jetztbewerben'), 'jetzt bewerben') "
            "and (self::a or self::button)]",
        )

        if apply_btns:
            ab = apply_btns[0]
            raw_href = (ab.get_attribute("href") or "").strip()
            orig_handles = list(driver.window_handles)
            orig_url = driver.current_url

            # Direct external ATS URL on the link itself
            if raw_href and raw_href.startswith("http") and "ausbildung.de" not in raw_href:
                final_destination = raw_href
            elif raw_href and "/direktbewerbung/" in raw_href:
                final_destination = urllib.parse.urljoin("https://www.ausbildung.de", raw_href)
            else:
                # Interactive click
                jetzt_bewerben_clicked = True
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", ab)
                    time.sleep(0.3)
                    try:
                        ab.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", ab)
                    time.sleep(1.8)

                    # Check for opened tabs
                    if len(driver.window_handles) > len(orig_handles):
                        new_h = [h for h in driver.window_handles if h not in orig_handles][0]
                        driver.switch_to.window(new_h)
                        final_destination = driver.current_url
                        driver.close()
                        driver.switch_to.window(orig_handles[0])
                    elif driver.current_url != orig_url:
                        final_destination = driver.current_url
                    else:
                        # Check modal or iframe
                        modals = driver.find_elements(By.XPATH, "//div[contains(@class, 'modal') or contains(@role, 'dialog')]//form")
                        if modals:
                            final_destination = orig_url
                        else:
                            final_destination = raw_href or orig_url
                except Exception as click_err:
                    logger.debug("[AusbildungDe] Error clicking Jetzt bewerben button: %s", click_err)
                    final_destination = raw_href or ""

        # Also fallback to Next.js applicationOptions.url if element click was empty
        if not final_destination or final_destination == job_url:
            app_opts = self._parse_application_options_from_html(driver.page_source or "")
            if app_opts and app_opts.get("url"):
                cand_u = str(app_opts["url"]).strip()
                if cand_u.startswith("/"):
                    cand_u = urllib.parse.urljoin("https://www.ausbildung.de", cand_u)
                if cand_u.startswith("http"):
                    final_destination = cand_u

        # Step 5: Excel output mapping
        if final_destination and not final_destination.endswith("/ratgeber/bewerbung/"):
            job["email"] = ""
            job["email_extracted"] = False
            job["has_form"] = True
            job["form_link"] = final_destination
            job["direct_application_url"] = final_destination
            job["bewerbung_link"] = final_destination
            job["extraction_method"] = "selenium"
            job["extraction_status"] = "form_found"
            if "ausbildung.de/direktbewerbung" in final_destination:
                job["application_method"] = "portal_form"
                job["application_url_type"] = "internal_direktbewerbung"
                job["bewerbung_art"] = "Online-Formular (Ausbildung.de Direktbewerbung)"
            else:
                job["application_method"] = "external_form"
                job["application_url_type"] = "external_ats"
                job["bewerbung_art"] = "Online-Formular (Arbeitgeber / ATS)"
            attach_contact_provenance(
                job,
                source_url=job_url,
                section="ausbildung_de_jetzt_bewerben",
                extraction_method="selenium",
                verified=True,
            )
            job["extraction_status"] = "form_found"

            self._record_audit_log(
                worker_id=worker_id,
                job_id=job_id,
                url=job_url,
                employer=employer,
                weitere_optionen_found=weitere_optionen_found,
                weitere_optionen_expanded=weitere_optionen_expanded,
                per_email_bewerben_found=per_email_bewerben_found,
                extracted_email="",
                email_source_location="N/A",
                full_page_fallback_used=full_page_fallback_used,
                jetzt_bewerben_clicked=jetzt_bewerben_clicked,
                final_destination=final_destination,
                extraction_status="form_found",
                status_reason=f"Application destination captured via Jetzt bewerben: {final_destination}",
            )
            return job

        # No application method discovered -> mark for review
        job["email"] = ""
        job["email_extracted"] = False
        job["has_form"] = False
        job["form_link"] = ""
        job["direct_application_url"] = ""
        job["bewerbung_link"] = ""
        job["application_method"] = "none"
        job["bewerbung_art"] = "Keine Bewerbungsmethode gefunden"
        job["manual_review_required"] = True
        job["extraction_status"] = "review_required"
        job["manual_review_reason"] = "No application method (email or form) could be discovered on Ausbildung.de"

        self._record_audit_log(
            worker_id=worker_id,
            job_id=job_id,
            url=job_url,
            employer=employer,
            weitere_optionen_found=weitere_optionen_found,
            weitere_optionen_expanded=weitere_optionen_expanded,
            per_email_bewerben_found=per_email_bewerben_found,
            extracted_email="",
            email_source_location="N/A",
            full_page_fallback_used=full_page_fallback_used,
            jetzt_bewerben_clicked=jetzt_bewerben_clicked,
            final_destination="",
            extraction_status="review_required",
            status_reason="Neither email nor application form was discovered on the listing",
        )
        return job

    def _isolate_browser_state(self, driver: Any) -> None:
        """Step 1 & 6: Close any stray secondary tabs and ensure clean window context."""
        try:
            handles = list(driver.window_handles)
            if len(handles) > 1:
                for h in handles[1:]:
                    driver.switch_to.window(h)
                    driver.close()
                driver.switch_to.window(handles[0])
        except Exception as exc:
            logger.debug("[AusbildungDe] Error isolating browser tabs: %s", exc)

    def _parse_application_options_from_html(self, html: str) -> Optional[Dict[str, Any]]:
        """Parses the Next.js App Router applicationOptions payload embedded in the HTML."""
        if not html or "applicationOptions" not in html:
            return None

        # Pattern 1: JSON inside self.__next_f.push with escaped quotes
        m1 = re.search(r'applicationOptions\\*":\s*\\*({.+?})', html)
        if m1:
            raw = m1.group(1).replace(r'\"', '"').replace('\\"', '"')
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        # Pattern 2: Regex extraction of individual keys
        email_m = re.search(r'applicationOptions\\*":\s*\\*{[^}]*?\\*"email\\*":\s*\\*"([^\\"]+)', html)
        url_m = re.search(r'applicationOptions\\*":\s*\\*{[^}]*?\\*"url\\*":\s*\\*"([^\\"]+)', html)

        email_val = email_m.group(1).strip() if email_m and email_m.group(1) != "null" else None
        url_val = url_m.group(1).strip() if url_m and url_m.group(1) != "null" else None

        if email_val or url_val:
            return {"email": email_val, "url": url_val}

        return None

    def _record_audit_log(
        self,
        worker_id: int,
        job_id: str,
        url: str,
        employer: str,
        weitere_optionen_found: bool,
        weitere_optionen_expanded: bool,
        per_email_bewerben_found: bool,
        extracted_email: str,
        email_source_location: str,
        full_page_fallback_used: bool,
        jetzt_bewerben_clicked: bool,
        final_destination: str,
        extraction_status: str,
        status_reason: str,
    ) -> None:
        """Step 9: Logs structured diagnostic information for Ausbildung.de."""
        logger.info(
            "[AusbildungDe] [Worker %s] Job %s (%s) | "
            "Weitere Optionen found: %s | Expanded: %s | Per E-Mail bewerben found: %s | "
            "Email: '%s' (Source: %s) | Full-page fallback: %s | Jetzt bewerben clicked: %s | "
            "Final destination: '%s' | Status: %s (%s)",
            worker_id,
            job_id,
            employer,
            weitere_optionen_found,
            weitere_optionen_expanded,
            per_email_bewerben_found,
            extracted_email or "None",
            email_source_location or "N/A",
            full_page_fallback_used,
            jetzt_bewerben_clicked,
            final_destination or "None",
            extraction_status,
            status_reason,
        )
