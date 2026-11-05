"""
Arbeitsagentur Application Details Extractor & Multi-Stage Application Resolver.
================================================================================
Implements smart 4-stage extraction for Arbeitsagentur and German job portal vacancies:
  Stage 1: Official API / SSR embedded JSON data
  Stage 2: High-speed HTML parsing ("Informationen zur Bewerbung" & description)
  Stage 3: Selenium browser fallback (reusing active sessions & handling in-page captchas)
  Stage 4: Employer website discovery (career pages, ATS detection, Kontakt, Impressum)

Never discards an opportunity because an email is missing. Preserves all available
application channels: email, form, external_link, phone, postal.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .application_form_discovery import (
    APPLICATION_BUTTON_KEYWORDS,
    KNOWN_ATS_DOMAINS,
    ApplicationFormDiscovery,
    classify_application_method,
    normalize_job_opportunity_row,
)
from .impressum_extractor import ImpressumExtractor

logger = logging.getLogger(__name__)

# Common regex patterns for German contact information
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
PHONE_REGEX = re.compile(
    r"(?:\+49|0049|0)\s*(?:\(0\)\s*)?[1-9][0-9\s/().\-]{5,22}[0-9]"
)
POSTAL_CODE_CITY_REGEX = re.compile(
    r"\b(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+(?:[\s\-][A-ZÄÖÜ][a-zäöüß]+)*)\b"
)

# Known ATS provider signatures for classification
EXTENDED_ATS_SIGNATURES: Dict[str, str] = {
    "persis": "ats_persis",
    "personio": "ats_personio",
    "workday": "ats_workday",
    "myworkdayjobs": "ats_workday",
    "softgarden": "ats_softgarden",
    "recruitee": "ats_recruitee",
    "greenhouse": "ats_greenhouse",
    "lever": "ats_lever",
    "d.vinci": "ats_dvinci",
    "d-vinci": "ats_dvinci",
    "covider": "ats_covider",
    "rexx": "ats_rexx",
    "rexx-systems": "ats_rexx",
    "smartrecruiters": "ats_smartrecruiters",
    "successfactors": "ats_successfactors",
    "talention": "ats_talention",
    "join.com": "ats_join",
    "stepstone": "external_listing",
    "indeed": "external_listing",
    "arbeitsagentur": "portal",
}

# Exclusion patterns for false-positive emails
PORTAL_EXCLUDED_EMAILS = {
    "jobboerse@arbeitsagentur.de",
    "noreply@arbeitsagentur.de",
    "service@arbeitsagentur.de",
    "datenschutz@arbeitsagentur.de",
    "impressum@arbeitsagentur.de",
}


def detect_ats_or_url_type(url: str) -> Tuple[str, bool]:
    """
    Classifies a destination URL into its type and indicates if it represents a direct form.
    Returns (url_type, has_form).
    """
    if not url:
        return "none", False

    u_lower = url.lower()
    for signature, ats_type in EXTENDED_ATS_SIGNATURES.items():
        if signature in u_lower:
            is_form = ats_type.startswith("ats_")
            return ats_type, is_form

    # Check for known form indicators in query parameters or paths
    form_indicators = ["/bewerb", "/apply", "form", "bewerbung", "stellenmarkt", "jobs."]
    if any(ind in u_lower for ind in form_indicators):
        return "direct_form", True

    if any(ind in u_lower for ind in ["karriere", "career", "jobs"]):
        return "career_portal", False

    return "external_link", False


def normalize_phone_number(raw_phone: Optional[str]) -> str:
    """Standardizes German phone numbers to +49 format when clean."""
    if not raw_phone:
        return ""
    cleaned = re.sub(r"[^\d+]", "", raw_phone.strip())
    if not cleaned:
        return ""
    if cleaned.startswith("0049"):
        return "+49" + cleaned[4:]
    if cleaned.startswith("0") and len(cleaned) > 5:
        return "+49" + cleaned[1:]
    if cleaned.startswith("+"):
        return cleaned
    return raw_phone.strip()


class ArbeitsagenturDetailExtractor:
    """
    Specialized extractor for Arbeitsagentur listings and German vocational vacancies.
    Resolves official application details across API, SSR, static HTML, browser DOM,
    and employer website discovery.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        if "User-Agent" not in self.session.headers:
            self.session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "de,de-DE;q=0.9,en;q=0.8",
                }
            )
        self.form_discovery = ApplicationFormDiscovery(session=self.session)
        self.impressum_extractor = ImpressumExtractor(session=self.session)

    def resolve_partner_redirect(self, partner_url: str, timeout: float = 5.0) -> Tuple[str, str, bool]:
        """
        Resolves outbound partner redirects with a strict bounded timeout.
        Returns (terminal_url, state, is_manual_required).
        state: 'resolved' | 'unresolved' | 'blocked'
        """
        clean_url = str(partner_url or "").strip()
        if not clean_url or not clean_url.startswith("http"):
            return clean_url, "unresolved", False

        try:
            # Fast HEAD request first to catch HTTP 301/302 redirects
            resp = self.session.head(clean_url, timeout=timeout, allow_redirects=True)
            term_url = resp.url
            domain = urlparse(term_url).netloc.lower()
            if "arbeitsagentur.de" not in domain:
                return term_url, "resolved", False

            # If still on arbeitsagentur, follow GET with stream to avoid downloading full body
            with self.session.get(clean_url, timeout=timeout, allow_redirects=True, stream=True) as get_resp:
                term_url = get_resp.url
                domain = urlparse(term_url).netloc.lower()
                if "arbeitsagentur.de" not in domain:
                    return term_url, "resolved", False

                if get_resp.status_code in (403, 429):
                    return clean_url, "blocked", True
        except Exception as e:
            logger.debug("Partner redirect resolution timeout/error for %s: %s", clean_url, e)
            is_timeout = "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower()
            return clean_url, "unresolved" if is_timeout else "blocked", True

        return clean_url, "unresolved", False

    # -------------------------------------------------------------------------
    # Stage 1: Official API / SSR Embedded JSON
    # -------------------------------------------------------------------------

    def extract_from_ssr_script(self, html: str) -> Dict[str, Any]:
        """Extracts pre-rendered jobdetail JSON data embedded by Angular SSR."""
        data: Dict[str, Any] = {}
        if not html or "jobdetail" not in html:
            return data

        soup = BeautifulSoup(html, "html.parser")
        for s in soup.find_all("script"):
            content = s.string or ""
            if "jobdetail" in content and "from-ssr" in content:
                try:
                    parsed = json.loads(content)
                    jd = parsed.get("jobdetail", {})
                    if isinstance(jd, dict):
                        data["ssr_jobdetail"] = jd
                        data["firma"] = jd.get("firma")
                        data["allianzpartnerUrl"] = jd.get("allianzpartnerUrl")
                        data["allianzpartnerName"] = jd.get("allianzpartnerName")
                        data["referenznummer"] = jd.get("referenznummer")
                        data["arbeitsorte"] = jd.get("stellenlokationen", [])
                        data["description"] = jd.get("stellenangebotsBeschreibung")
                        break
                except Exception as exc:
                    logger.debug("Failed to parse SSR jobdetail JSON: %s", exc)

        return data

    # -------------------------------------------------------------------------
    # Stage 2: HTML Extraction ("Informationen zur Bewerbung" & Copytext)
    # -------------------------------------------------------------------------

    def parse_application_section(self, html: str, source_url: str = "") -> Dict[str, Any]:
        """
        Parses the official 'Informationen zur Bewerbung' section and full copytext.
        Extracts email, phone, contact person, postal address, accepted methods,
        required documents, and employer URLs.
        """
        result: Dict[str, Any] = {
            "email": "",
            "email_type": "",
            "phone": "",
            "contact_person": "",
            "postal_address": "",
            "employer_website": "",
            "direct_application_url": "",
            "application_url_type": "none",
            "has_form": False,
            "application_methods": [],
            "required_documents": "",
            "extraction_status": "partial",
            "logs": [],
            "manual_review_required": False,
            "manual_review_reason": "",
        }

        if not html:
            result["extraction_status"] = "no_content"
            return result

        soup = BeautifulSoup(html, "html.parser")

        # 1. Locate the application section and copytext
        kontaktdaten_block = (
            soup.find(id="jobdetails-kontaktdaten-block")
            or soup.find(id="jobdetails-kontaktdaten-container")
            or soup.find(lambda el: el.name in ["section", "div"] and "Informationen zur Bewerbung" in el.get_text())
        )
        copytext_block = soup.find("div", class_="ba-copytext")

        # Combine text regions with priority given to kontaktdaten & copytext
        contact_text = kontaktdaten_block.get_text("\n", strip=True) if kontaktdaten_block else ""
        copy_text = copytext_block.get_text("\n", strip=True) if copytext_block else ""
        full_text = soup.get_text("\n", strip=True)

        combined_focused_text = f"{contact_text}\n{copy_text}"

        # 2. Extract Email & Email Type
        # Priority: mailto links inside contact or copytext
        emails: List[str] = []
        target_blocks = [b for b in [kontaktdaten_block, copytext_block] if b is not None]
        for blk in target_blocks:
            for mailto in blk.find_all("a", href=lambda h: h and h.startswith("mailto:")):
                raw_addr = mailto.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
                if raw_addr and "@" in raw_addr and raw_addr not in PORTAL_EXCLUDED_EMAILS:
                    emails.append(raw_addr)

        if not emails:
            # Fallback to regex across focused text
            found = EMAIL_REGEX.findall(combined_focused_text)
            emails = [e.lower() for e in found if e.lower() not in PORTAL_EXCLUDED_EMAILS]

        if emails:
            result["email"] = emails[0]
            result["email_type"] = "recruitment"
            result["logs"].append(f"Email extracted: {result['email']} (recruitment)")

        # 3. Extract Phone Number
        phone_match = None
        for blk in target_blocks:
            for tel in blk.find_all("a", href=lambda h: h and h.startswith("tel:")):
                phone_match = tel.get("href", "").replace("tel:", "").strip()
                if phone_match:
                    break
            if phone_match:
                break

        if not phone_match:
            # Search telephone cues: "Tel.:", "Telefon:", "Fon:"
            tel_cue = re.search(r"(?:tel(?:efon)?\.?|fon)\s*[:\-\s]\s*([+0-9\s/().\-]{6,25})", combined_focused_text, re.IGNORECASE)
            if tel_cue:
                phone_match = tel_cue.group(1).strip()
            else:
                phones = PHONE_REGEX.findall(combined_focused_text)
                if phones:
                    phone_match = phones[0]

        if phone_match:
            result["phone"] = normalize_phone_number(phone_match)
            result["logs"].append(f"Phone extracted: {result['phone']}")

        # 4. Extract Contact Person
        contact_person = ""
        cp_match = re.search(
            r"(?:ansprechpartner(?:in)?|kontaktperson|bewerbermanagement)\s*[:\-\s]\s*([^\n\r<]{3,80})",
            combined_focused_text,
            re.IGNORECASE,
        )
        if cp_match:
            contact_person = cp_match.group(1).strip()
        else:
            # Search for Herr / Frau salutation patterns
            salut_match = re.search(r"\b((?:Herr|Frau|Dr\.|Prof\.)\s+[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)\b", combined_focused_text)
            if salut_match:
                contact_person = salut_match.group(1).strip()

        result["contact_person"] = contact_person
        if contact_person:
            result["logs"].append(f"Contact person detected: {contact_person}")

        # 5. Extract Postal Address
        postal_match = POSTAL_CODE_CITY_REGEX.search(combined_focused_text)
        if postal_match:
            # Look backwards for street
            result["postal_address"] = postal_match.group(0).strip()

        # 6. Extract Required Application Documents
        docs: List[str] = []
        if re.search(r"\blebenslauf\b", combined_focused_text, re.IGNORECASE):
            docs.append("Lebenslauf")
        if re.search(r"\banschreiben\b|\bbewerbungsanschreiben\b", combined_focused_text, re.IGNORECASE):
            docs.append("Anschreiben")
        if re.search(r"\bzeugnisse?\b|\babschlusszeugnis\b|\bnotenspiegel\b", combined_focused_text, re.IGNORECASE):
            docs.append("Zeugnisse")

        # Explicit Geforderte Anlagen line
        anlagen_match = re.search(r"(?:geforderte\s+anlagen|anlagen)\s*[:\-\s]\s*([^\n\r<]{3,120})", combined_focused_text, re.IGNORECASE)
        if anlagen_match:
            result["required_documents"] = anlagen_match.group(1).strip()
        elif docs:
            result["required_documents"] = ", ".join(docs)

        if result["required_documents"]:
            result["logs"].append(f"Required documents detected: {result['required_documents']}")

        # 7. Extract Application Links & Employer URLs
        candidate_links: List[str] = []

        # Find external anchor links in application & copytext sections
        for blk in target_blocks:
            for a in blk.find_all("a", href=True):
                href = a.get("href", "").strip()
                if not href or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
                    continue
                abs_url = urljoin(source_url, href)
                # Filter out Arbeitsagentur internal navigation and social shares
                domain = urlparse(abs_url).netloc.lower()
                if "arbeitsagentur.de" in domain:
                    continue
                candidate_links.append(abs_url)

        # Check allianzpartnerUrl or partner redirects
        ssr_data = self.extract_from_ssr_script(html)
        ssr_allianz = ssr_data.get("allianzpartnerUrl")
        if ssr_allianz:
            if "arbeitsagentur.de" not in ssr_allianz:
                candidate_links.insert(0, ssr_allianz)
            else:
                # Safely resolve bounded partner redirect
                resolved_url, res_state, needs_manual = self.resolve_partner_redirect(ssr_allianz, timeout=5.0)
                if res_state == "resolved":
                    candidate_links.insert(0, resolved_url)
                    result["logs"].append(f"Resolved partner redirect to: {resolved_url}")
                elif needs_manual:
                    result["manual_review_required"] = True
                    result["manual_review_reason"] = "Partner portal requires human verification"
                    result["extraction_status"] = "manual_required"
                    result["direct_application_url"] = ssr_allianz
                    result["application_url_type"] = "partner_portal"
                    result["logs"].append(f"Partner portal redirect unresolved/blocked: {ssr_allianz}")

        # Classify candidate links
        for url in candidate_links:
            url_type, has_form = detect_ats_or_url_type(url)
            if has_form or url_type.startswith("ats_") or url_type == "direct_form":
                result["direct_application_url"] = url
                result["application_url_type"] = url_type
                result["has_form"] = True
                result["logs"].append(f"ATS/Application form found: {url} ({url_type})")
                break
            elif not result["employer_website"]:
                result["employer_website"] = url
                result["application_url_type"] = url_type
                result["logs"].append(f"Employer website found: {url}")

        if not result["direct_application_url"] and candidate_links:
            # If no direct ATS form, use first external candidate as employer application website
            result["direct_application_url"] = candidate_links[0]
            if result["application_url_type"] == "none":
                result["application_url_type"] = "career_portal"

        # 8. Identify Accepted Application Methods
        methods: List[str] = []
        text_lower = combined_focused_text.lower()

        # Check for web portal application cues
        if (
            result["has_form"]
            or result["direct_application_url"]
            or "über internetseite des arbeitgebers" in text_lower
            or "bewerbungsportal" in text_lower
            or "online-bewerbung" in text_lower
            or "online bewerben" in text_lower
            or "jetzt bewerben" in text_lower
        ):
            if result["has_form"]:
                methods.append("form")
            else:
                methods.append("external_link")

        # Check for email application cues
        if result["email"] or "per e-mail" in text_lower or "e-mail-bewerbung" in text_lower:
            methods.append("email")

        # Check for postal application cues
        if "per post" in text_lower or "postalisch" in text_lower or "schriftlich" in text_lower:
            methods.append("postal")

        # Check for phone application cues
        if "telefonisch" in text_lower or (result["phone"] and "bewerbung" in text_lower and "telefon" in text_lower):
            methods.append("phone")

        # Deduplicate while preserving order
        unique_methods = []
        for m in methods:
            if m not in unique_methods:
                unique_methods.append(m)

        result["application_methods"] = unique_methods

        # Calculate primary application_method
        has_email = bool(result["email"] and "@" in result["email"])
        has_verified_form = bool(result["has_form"])
        has_ext_link = bool(result["direct_application_url"] or "external_link" in unique_methods)

        if has_email and (has_verified_form or has_ext_link):
            result["application_method"] = "both"
        elif has_email:
            result["application_method"] = "email"
        elif has_verified_form:
            result["application_method"] = "form"
        elif has_ext_link:
            result["application_method"] = "external_link"
        elif "phone" in unique_methods:
            result["application_method"] = "phone"
        elif "postal" in unique_methods:
            result["application_method"] = "postal"
        else:
            result["application_method"] = "unknown"

        # Update extraction status
        if result.get("manual_review_required"):
            result["extraction_status"] = "manual_required"
        elif has_email or has_verified_form or has_ext_link:
            result["extraction_status"] = "completed"
        elif result["phone"] or contact_person:
            result["extraction_status"] = "partial"
        else:
            result["extraction_status"] = "no_contact_found"

        return result

    # -------------------------------------------------------------------------
    # Stage 3: Selenium Browser Fallback
    # -------------------------------------------------------------------------

    def extract_with_selenium(
        self,
        driver,
        job_url: str,
        solver=None,
    ) -> Dict[str, Any]:
        """
        Reuses an existing Selenium WebDriver session to handle dynamic JavaScript rendering
        and solve in-page contact captchas without starting a new browser process.
        """
        result: Dict[str, Any] = {
            "email": "",
            "phone": "",
            "contact_person": "",
            "employer_website": "",
            "direct_application_url": "",
            "has_form": False,
            "application_methods": [],
            "required_documents": "",
            "extraction_status": "partial",
            "logs": [],
        }

        if driver is None or not job_url:
            return result

        try:
            current_url = getattr(driver, "current_url", "")
            if not current_url or job_url not in current_url:
                driver.get(job_url)
                time.sleep(1.5)

            # Dismiss cookies
            try:
                from .cookie_handler import accept_cookies
                accept_cookies(driver, wait_after_click=0.5)
            except Exception:
                pass

            # Check for in-page captcha
            from selenium.webdriver.common.by import By
            captcha_imgs = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-image'] | //img[contains(@src, 'captcha')]")
            captcha_inputs = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-input'] | //input[contains(@name, 'captcha')]")
            submit_btns = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-absenden-button'] | //button[@type='submit']")

            if captcha_imgs and captcha_inputs and solver:
                result["logs"].append("In-page captcha encountered in contact section")
                from services.captcha_monitor import get_captcha_tracker, generate_challenge_fingerprint
                job_id = getattr(solver, "job_id", "")
                worker_id = getattr(solver, "worker_id", 1)
                tracker = get_captcha_tracker(job_id)
                ch_fp = generate_challenge_fingerprint("arbeitsagentur.de", "kontaktdaten-inpage-captcha")
                corr_id = tracker.record_challenge_detected(
                    domain="arbeitsagentur.de",
                    worker_id=worker_id,
                    challenge_fingerprint=ch_fp,
                    details="In-page contact captcha encountered on Arbeitsagentur",
                )
                try:
                    img_src = captcha_imgs[0].get_attribute("src") or ""
                    captcha_text = None
                    if img_src.startswith("http"):
                        img_res = self.session.get(img_src, timeout=10)
                        if img_res.status_code == 200:
                            solver_ctx = {
                                "job_id": job_id,
                                "worker_id": worker_id,
                                "domain": "arbeitsagentur.de",
                                "correlation_id": corr_id,
                            }
                            captcha_text = solver.solve_captcha(img_res.content, context=solver_ctx)

                    if captcha_text:
                        captcha_inputs[0].clear()
                        captcha_inputs[0].send_keys(captcha_text)
                        if submit_btns:
                            submit_btns[0].click()
                        time.sleep(2.0)
                        # Confirm whether target website accepted the solution
                        still_present = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-image'] | //img[contains(@src, 'captcha')]")
                        if not still_present:
                            tracker.record_website_verification(
                                correlation_id=corr_id,
                                worker_id=worker_id,
                                domain="arbeitsagentur.de",
                                details="Target website accepted in-page verification",
                            )
                            result["logs"].append("Target website confirmed in-page captcha verification")
                        else:
                            reason = "Target website still presents captcha after submit"
                            tracker.record_manual_verification_required(
                                correlation_id=corr_id,
                                worker_id=worker_id,
                                domain="arbeitsagentur.de",
                                reason=reason,
                            )
                            result["manual_review_required"] = True
                            result["manual_review_reason"] = reason
                            result["extraction_status"] = "manual_required"
                            result["logs"].append("Target website did NOT accept captcha (manual verification required)")
                    else:
                        reason = "No solution text returned by recognition service"
                        tracker.record_manual_verification_required(
                            correlation_id=corr_id,
                            worker_id=worker_id,
                            domain="arbeitsagentur.de",
                            reason=reason,
                        )
                        result["manual_review_required"] = True
                        result["manual_review_reason"] = reason
                        result["extraction_status"] = "manual_required"
                except Exception as c_err:
                    logger.debug("Captcha solving error: %s", c_err)
                    tracker.record_manual_verification_required(
                        correlation_id=corr_id,
                        worker_id=worker_id,
                        domain="arbeitsagentur.de",
                        reason=f"Captcha submission failed: {c_err}",
                    )
                    result["logs"].append(f"Captcha handling failed: {c_err}")
                    result["manual_review_required"] = True
                    result["manual_review_reason"] = f"Captcha submission failed: {c_err}"
                    result["extraction_status"] = "manual_required"

            # Extract rendered DOM page source
            rendered_html = driver.page_source
            parsed = self.parse_application_section(rendered_html, source_url=job_url)
            parsed["extraction_method"] = "selenium"
            if result.get("manual_review_required"):
                parsed["manual_review_required"] = True
                parsed["manual_review_reason"] = result.get("manual_review_reason", "")
                parsed["extraction_status"] = "manual_required"
            return parsed

        except Exception as exc:
            logger.debug("Selenium fallback failed for %s: %s", job_url, exc)
            result["logs"].append(f"Selenium extraction error: {exc}")
            return result

    # -------------------------------------------------------------------------
    # Stage 4: Employer Website Discovery Fallback
    # -------------------------------------------------------------------------

    def discover_employer_website_fallback(
        self,
        company: str,
        location: str = "",
        existing_website: str = "",
        driver=None,
    ) -> Dict[str, Any]:
        """
        Discovers company career pages, contact details, and ATS forms
        when the official Arbeitsagentur listing does not contain direct contact details.
        """
        result: Dict[str, Any] = {
            "email": "",
            "email_type": "",
            "phone": "",
            "employer_website": existing_website,
            "direct_application_url": "",
            "has_form": False,
            "application_method": "unknown",
            "application_url_type": "none",
            "logs": ["Attempting employer website discovery fallback"],
        }

        target_website = existing_website
        if not target_website and company:
            # Clean company name
            clean_comp = re.sub(r"\b(gmbh|ag|kg|e\.v\.|ohg|gbr|co\.)\b", "", company, flags=re.IGNORECASE).strip()
            # Try basic domain heuristic
            domain_guess = re.sub(r"[^a-zA-Z0-9]", "", clean_comp).lower()
            if domain_guess:
                target_website = f"https://www.{domain_guess}.de"

        if not target_website:
            return result

        result["employer_website"] = target_website

        # 1. Discover application form via ApplicationFormDiscovery
        dummy_job = {
            "company": company,
            "url": target_website,
            "apply_url": target_website,
        }
        discovery_res = self.form_discovery.discover_application_form(dummy_job, driver=driver)
        if discovery_res and discovery_res.has_form:
            result["has_form"] = True
            result["direct_application_url"] = discovery_res.form_link or discovery_res.bewerbung_link
            url_type, _ = detect_ats_or_url_type(result["direct_application_url"])
            result["application_url_type"] = url_type
            result["application_method"] = "form"
            result["logs"].append(f"Discovered external application form: {result['direct_application_url']}")

        # 2. Extract legal notice (Impressum) as non-recruitment contact fallback
        try:
            impressum_info = self.impressum_extractor.extract_from_website(target_website)
            if impressum_info:
                if impressum_info.get("emails"):
                    # Explicit rule: Do not classify Impressum email as recruitment email
                    result["email"] = impressum_info["emails"][0]
                    result["email_type"] = "impressum"
                    result["logs"].append(f"Impressum email extracted: {result['email']} (email_type=impressum)")
                if not result["phone"] and impressum_info.get("telephones"):
                    result["phone"] = normalize_phone_number(impressum_info["telephones"][0])
                if impressum_info.get("geschaeftsfuehrer"):
                    result["contact_person"] = impressum_info["geschaeftsfuehrer"][0]
        except Exception as imp_err:
            logger.debug("Impressum fallback failed: %s", imp_err)

        return result

    # -------------------------------------------------------------------------
    # Main Orchestrator: Multi-Stage Extraction
    # -------------------------------------------------------------------------

    def extract_vacancy(
        self,
        job: Dict[str, Any],
        driver=None,
        captcha_solver=None,
        on_stage_change=None,
    ) -> Dict[str, Any]:
        """
        Executes the 4-stage smart extraction workflow for an Arbeitsagentur vacancy.
        Preserves all existing attributes and integrates discovered application methods.
        Never discards a vacancy solely for missing email.
        """
        if on_stage_change:
            on_stage_change("HTTP Fast-Path")
        enriched = dict(job or {})
        source_url = str(enriched.get("apply_url") or enriched.get("url") or "").strip()
        reference = str(enriched.get("reference") or enriched.get("referenznummer") or "").strip()
        company = str(enriched.get("company") or enriched.get("firma") or "").strip()
        location = str(enriched.get("location") or enriched.get("city") or "").strip()

        logs: List[str] = []

        if not source_url and reference:
            source_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
            enriched["url"] = source_url

        parsed_details: Dict[str, Any] = {}

        # ---------------------------------------------------------------------
        # Stage 1 & 2: Fast HTTP Fetch & HTML / SSR Parsing
        # ---------------------------------------------------------------------
        if source_url and "arbeitsagentur.de" in source_url:
            try:
                t0 = time.time()
                from .rate_limiter import safe_http_get
                resp = safe_http_get(self.session, source_url, timeout=12)
                elapsed = time.time() - t0
                if resp is not None and resp.status_code == 200 and resp.text:
                    parsed_details = self.parse_application_section(resp.text, source_url=source_url)
                    logs.extend(parsed_details.get("logs", []))
                    logs.append(f"Stage 2 HTML parsed in {elapsed:.2f}s")
            except Exception as http_err:
                logger.debug("Fast HTTP fetch failed for %s: %s", source_url, http_err)
                logs.append(f"Stage 2 HTTP error: {http_err}")

        # Check if Stage 2 extracted sufficient application details
        has_email = bool(parsed_details.get("email") and "@" in parsed_details.get("email"))
        has_form = bool(parsed_details.get("has_form"))
        has_ext_link = bool(parsed_details.get("direct_application_url"))

        # ---------------------------------------------------------------------
        # Stage 3: Browser Fallback (Selenium)
        # ---------------------------------------------------------------------
        if not (has_email or has_form or has_ext_link) and driver is not None:
            if on_stage_change:
                on_stage_change("Selenium Fallback")
            logs.append("Stage 2 missing direct application channels, falling back to Stage 3 (Selenium)")
            sel_details = self.extract_with_selenium(driver, source_url, solver=captcha_solver)
            logs.extend(sel_details.get("logs", []))

            # Merge Selenium results over Stage 2
            for key, val in sel_details.items():
                if val and not parsed_details.get(key):
                    parsed_details[key] = val

            has_email = bool(parsed_details.get("email") and "@" in parsed_details.get("email"))
            has_form = bool(parsed_details.get("has_form"))
            has_ext_link = bool(parsed_details.get("direct_application_url"))

            if parsed_details.get("manual_review_required"):
                if on_stage_change:
                    on_stage_change("Manual Review")
                enriched.update(parsed_details)
                enriched["extraction_status"] = "manual_required"
                enriched["manual_review_required"] = True
                enriched["manual_review_reason"] = parsed_details.get("manual_review_reason") or "Human verification required"
                enriched["extraction_logs"] = logs
                return enriched

        # ---------------------------------------------------------------------
        # Stage 4: Employer Website Discovery
        # ---------------------------------------------------------------------
        if not (has_email or has_form or has_ext_link):
            if on_stage_change:
                on_stage_change("Finding Application Form")
            logs.append("Stage 3 yielded no application channels, attempting Stage 4 (Employer Website Discovery)")
            discovery_details = self.discover_employer_website_fallback(
                company=company,
                location=location,
                existing_website=parsed_details.get("employer_website") or enriched.get("website") or "",
                driver=driver,
            )
            logs.extend(discovery_details.get("logs", []))

            for key, val in discovery_details.items():
                if val and not parsed_details.get(key):
                    parsed_details[key] = val

        # ---------------------------------------------------------------------
        # Consolidate and Normalize
        # ---------------------------------------------------------------------
        # Update enriched dictionary with extracted attributes
        enriched["email"] = parsed_details.get("email") or enriched.get("email") or ""
        enriched["email_type"] = parsed_details.get("email_type") or ("recruitment" if enriched["email"] else "")
        enriched["phone"] = parsed_details.get("phone") or enriched.get("phone") or ""
        enriched["contact_person"] = parsed_details.get("contact_person") or enriched.get("arbeitsgeber") or ""
        enriched["arbeitsgeber"] = enriched["contact_person"]
        enriched["postal_address"] = parsed_details.get("postal_address") or ""
        enriched["employer_website"] = parsed_details.get("employer_website") or ""
        enriched["direct_application_url"] = parsed_details.get("direct_application_url") or ""
        enriched["form_link"] = enriched["direct_application_url"] if parsed_details.get("has_form") else ""
        enriched["has_form"] = bool(parsed_details.get("has_form"))
        enriched["application_url_type"] = parsed_details.get("application_url_type") or "none"
        enriched["required_documents"] = parsed_details.get("required_documents") or ""
        enriched["application_methods"] = parsed_details.get("application_methods") or []
        enriched["apply_url"] = source_url or enriched.get("apply_url") or enriched.get("url") or ""
        enriched["job_listing_url"] = enriched["apply_url"]
        enriched["bewerbung_link"] = enriched["direct_application_url"] or enriched["apply_url"]

        # Final application_method calculation
        app_method, bewerbung_art = classify_application_method(
            email=enriched["email"],
            has_form=enriched["has_form"],
            existing_method=parsed_details.get("application_method") or enriched.get("application_method") or "",
            direct_url=enriched["direct_application_url"],
        )
        enriched["application_method"] = app_method
        enriched["bewerbung_art"] = bewerbung_art

        if enriched["email"] or enriched["has_form"] or enriched["direct_application_url"]:
            enriched["extraction_status"] = "completed"
        elif enriched["phone"] or enriched["contact_person"]:
            enriched["extraction_status"] = "partial"
        else:
            enriched["extraction_status"] = "no_contact_found"

        if parsed_details.get("extraction_method"):
            enriched["extraction_method"] = parsed_details["extraction_method"]
        elif driver is not None and not (has_email or has_form or has_ext_link):
            enriched["extraction_method"] = "selenium"
        else:
            enriched["extraction_method"] = "fast_http"

        enriched["extraction_logs"] = logs
        return normalize_job_opportunity_row(enriched)
