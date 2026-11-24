"""
Dedicated Detail Extractor for Azubiyo.de.

Implements the reliable "Jetzt bewerben" extraction workflow:
1. Open and isolate each job listing with immutable job ID.
2. Locate and inspect "Jetzt bewerben" button/anchor, JS navigation functions, and subpage routes:
   - /stellenanzeigen/<slug>/bewerben/
   - /stellenanzeigen/<slug>/bewerben-email/
   - /stellenanzeigen/<slug>/schnellbewerbung/
3. Handle all navigation outcomes:
   - Scenario A: External employer recruitment website
   - Scenario B: Internal Azubiyo application page followed to final destination
   - Scenario C: Multiple redirects followed to canonical ATS/form endpoint
   - Scenario D: New browser tab/window safely inspected and closed
   - Scenario E: Same-page application (Schnellbewerbung / modal)
   - Scenario F: Email application (prioritized over form/link)
   - Scenario G: Login required (captures entry URL, portal_login_required)
   - Scenario H: No usable destination (marks manual_review_required)
4. Enforces strict consistency invariants preventing false verified statuses without URLs.
"""

import html as html_lib
import logging
import re
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from scraper.application_form_discovery import (
    ApplicationFormDiscovery,
    normalize_job_opportunity_row,
)
from scraper.cookie_handler import accept_cookies
from services.application_url_validator import (
    ApplicationDestinationType,
    classify_and_validate_destination,
)
from services.contamination_detector import (
    attach_contact_provenance,
    classify_extraction_outcome,
    is_email_compatible_with_employer,
    is_url_compatible_with_job,
)
from services.data_validator import (
    is_advice_or_generic_page,
    sanitize_contact_person,
    validate_phone_number,
)
from services.employer_cache import is_non_employer_domain, is_shortener_domain

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def unescape_js_unicode(val: str) -> str:
    """Decodes JavaScript unicode escapes like \\u0026 into '&'."""
    if not val:
        return ""
    val = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), val)
    val = val.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    return val.strip()


def extract_cf_emails_from_text(text: str) -> List[str]:
    """Decodes Cloudflare email-protection hex strings."""
    if not text:
        return []
    emails = []
    cf_matches = re.findall(r'data-cfemail=[\'"]([0-9a-fA-F]+)[\'"]', text)
    for hex_str in cf_matches:
        try:
            k = int(hex_str[:2], 16)
            email = "".join([chr(int(hex_str[i : i + 2], 16) ^ k) for i in range(2, len(hex_str), 2)])
            if EMAIL_PATTERN.match(email):
                emails.append(email.lower())
        except Exception:
            continue
    return emails


def enforce_azubiyo_consistency_invariants(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enforces mandatory consistency checks before storing or exporting an Azubiyo record:
      - verified_email: valid email MUST exist
      - verified_application_link: usable application URL MUST exist
      - verified_application_form: usable form destination MUST exist
      - portal_login_required: login or application entry URL MUST exist
    If requirements are not met, safely downgrades the status to manual_review_required.
    """
    status = str(record.get("extraction_status") or "").strip().lower()
    app_method = str(record.get("application_method") or "").strip().lower()
    email_val = str(record.get("email") or "").strip()
    direct_url = str(record.get("direct_application_url") or "").strip()
    form_link = str(record.get("form_link") or "").strip()

    valid_email_exists = bool(email_val and "@" in email_val and not email_val.lower().startswith("error"))
    usable_app_url_exists = bool(direct_url and direct_url.startswith(("http://", "https://")))
    usable_form_exists = bool(form_link and form_link.startswith(("http://", "https://"))) or usable_app_url_exists
    login_entry_exists = usable_app_url_exists or usable_form_exists

    # 1. verified_email invariant
    if status == "verified_email" and not valid_email_exists:
        record["extraction_status"] = "manual_review_required"
        record["manual_review_required"] = True
        record["manual_review_reason"] = "Downgraded: verified_email status lacked valid email"
        status = "manual_review_required"

    # 2. verified_application_link invariant
    if status == "verified_application_link" and not usable_app_url_exists:
        record["extraction_status"] = "manual_review_required"
        record["manual_review_required"] = True
        record["manual_review_reason"] = "Downgraded: verified_application_link lacked usable application URL"
        status = "manual_review_required"

    # 3. verified_application_form invariant
    if status == "verified_application_form" and not usable_form_exists:
        record["extraction_status"] = "manual_review_required"
        record["manual_review_required"] = True
        record["manual_review_reason"] = "Downgraded: verified_application_form lacked usable form link"
        status = "manual_review_required"

    # 4. portal_login_required invariant
    if app_method == "portal_login_required" and not login_entry_exists:
        record["application_method"] = "unknown"
        record["bewerbung_art"] = "Unbekannt"
        record["portal_login_required"] = False
        if status in ("completed", "verified_application_link", "verified_application_form"):
            record["extraction_status"] = "manual_review_required"
            record["manual_review_required"] = True
            record["manual_review_reason"] = "Downgraded: portal_login_required lacked login or application entry URL"

    return record


class AzubiyoDetailExtractor:
    """
    Dedicated detail extractor for Azubiyo.de job listings.
    Follows HTTP-first strategy, resolves JS and subpage redirects,
    inspects same-page forms, handles new browser tabs, and enforces
    strict consistency invariants.
    """

    def __init__(self, job_cache: Optional[Any] = None, employer_cache: Optional[Any] = None):
        self.job_cache = job_cache
        self.employer_cache = employer_cache

    def extract_vacancy(
        self,
        job: Dict[str, Any],
        html: Optional[str] = None,
        driver: Optional[Any] = None,
        session: Optional[requests.Session] = None,
        on_stage_change: Optional[Callable[[str], None]] = None,
        worker_id: int = 1,
    ) -> Dict[str, Any]:
        """
        Main extraction entry point for an individual Azubiyo listing.
        Guarantees isolation and independent state per job listing.
        """
        job_url = str(job.get("url") or job.get("job_listing_url") or "").strip()
        company = str(job.get("company") or job.get("firma") or "").strip()
        title = str(job.get("title") or "").strip()

        logger.info(
            "[Azubiyo] [Worker %s] Starting extraction for '%s' (%s) at %s",
            worker_id,
            title,
            company,
            job_url,
        )

        if not job_url:
            job["extraction_status"] = "failed"
            job["manual_review_required"] = True
            job["validation_reason"] = "Missing job listing URL"
            return enforce_azubiyo_consistency_invariants(job)

        # ------------------------------------------------------------------
        # Step 1: HTTP Fast Path
        # ------------------------------------------------------------------
        if on_stage_change:
            on_stage_change("HTTP Fast-Path")

        fast_result = self._extract_via_fast_http(job, job_url, company, html=html, session=session, worker_id=worker_id)
        if fast_result is not None:
            # Check if Fast HTTP found a definitive outcome
            has_email = bool(fast_result.get("email") and "@" in str(fast_result.get("email")))
            has_form = bool(fast_result.get("has_form") and (fast_result.get("form_link") or fast_result.get("direct_application_url")))
            has_link = bool(fast_result.get("direct_application_url"))
            is_login = bool(fast_result.get("application_method") == "portal_login_required" and fast_result.get("direct_application_url"))

            if has_email or has_form or has_link or is_login:
                logger.info(
                    "[Azubiyo] [Worker %s] Fast HTTP succeeded for %s: email='%s', form='%s', direct_url='%s'",
                    worker_id,
                    job_url,
                    fast_result.get("email"),
                    fast_result.get("form_link"),
                    fast_result.get("direct_application_url"),
                )
                return enforce_azubiyo_consistency_invariants(fast_result)

        # ------------------------------------------------------------------
        # Step 2: Selenium Browser Automation (when Fast HTTP is insufficient)
        # ------------------------------------------------------------------
        if driver is not None:
            if on_stage_change:
                on_stage_change("Selenium Fallback")

            logger.info("[Azubiyo] [Worker %s] Invoking Selenium fallback for %s", worker_id, job_url)
            selenium_result = self._extract_via_selenium(
                job,
                job_url,
                company,
                driver=driver,
                on_stage_change=on_stage_change,
                worker_id=worker_id,
            )
            if selenium_result is not None:
                return enforce_azubiyo_consistency_invariants(selenium_result)

        # If Fast HTTP produced a partial result (e.g. contacts only or unresolved), fallback to it
        if fast_result is not None:
            return enforce_azubiyo_consistency_invariants(fast_result)

        # Step 3: Unresolved fallback
        out = dict(job)
        out["job_listing_url"] = job_url
        out["extraction_status"] = "manual_review_required"
        out["manual_review_required"] = True
        out["validation_reason"] = "No usable application destination or contact could be retrieved"
        return enforce_azubiyo_consistency_invariants(out)

    def _resolve_redirect_chain(self, start_url: str, session: Optional[requests.Session] = None) -> Tuple[str, List[str]]:
        """Follows HTTP redirects, returning (final_url, redirect_chain)."""
        chain = [start_url]
        current = start_url
        sess = session or requests.Session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
        }

        for _ in range(5):
            try:
                try:
                    resp = sess.get(current, headers=headers, timeout=8, allow_redirects=True)
                except TypeError:
                    resp = sess.get(current, timeout=8, allow_redirects=True)
                for h in getattr(resp, "history", []) or []:
                    h_url = getattr(h, "url", None)
                    if isinstance(h_url, str) and h_url not in chain:
                        chain.append(h_url)
                final = resp.url
                if isinstance(final, str) and final:
                    if final not in chain:
                        chain.append(final)
                    return final, chain
                break
            except Exception as exc:
                logger.debug("[Azubiyo] Redirect resolution error for %s: %s", current, exc)
                break
        return current, chain

    def _extract_via_fast_http(
        self,
        job: Dict[str, Any],
        job_url: str,
        company: str,
        html: Optional[str] = None,
        session: Optional[requests.Session] = None,
        worker_id: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Executes Fast HTTP examination of Azubiyo listing and application routes."""
        sess = session or requests.Session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "de,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.azubiyo.de/",
        }

        def _get_page(u: str, tm: int = 10, redir: bool = True):
            try:
                return sess.get(u, headers=headers, timeout=tm, allow_redirects=redir)
            except TypeError:
                return sess.get(u, timeout=tm, allow_redirects=redir)

        if html:
            main_html = html
            final_job_url = job_url
        else:
            try:
                resp = _get_page(job_url, tm=10, redir=True)
                if resp.status_code != 200 or not resp.text:
                    return None
                main_html = resp.text
                final_job_url = resp.url or job_url
            except Exception as exc:
                logger.debug("[Azubiyo] [Worker %s] Fast HTTP get error on %s: %s", worker_id, job_url, exc)
                return None

        soup = BeautifulSoup(main_html, "html.parser")
        main_container = soup.find("main") or soup

        # Recover true company name from JSON-LD if initial company is a single-letter avatar badge
        if len(company) < 3 or company.lower() in {"n/a", "unknown", "unbekannt"}:
            m_org = re.search(r'"hiringOrganization"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"]{3,120})"', main_html, re.I)
            if m_org:
                company = m_org.group(1).strip()
                job["company"] = company
                job["firma"] = company

        # Extract contact person and phone scoped to job container (rejecting portal hotlines)
        valid_phones = []
        contact_person = ""
        for a in main_container.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("tel:"):
                raw_tel = href.replace("tel:", "").strip()
                ok_p, clean_p, _ = validate_phone_number(raw_tel)
                if ok_p and clean_p not in valid_phones:
                    valid_phones.append(clean_p)

        # Look for contact person text blocks
        for cp_block in main_container.find_all(lambda tag: tag.name in ["div", "p", "span", "section"] and any(k in (tag.get_text() or "").lower() for k in ["ansprechpartner", "kontaktperson", "dein kontakt"])):
            cp_text = cp_block.get_text(" ", strip=True)
            ok_c, clean_c, _ = sanitize_contact_person(cp_text)
            if ok_c:
                contact_person = clean_c
                break

        unescaped_main = html_lib.unescape(main_html)

        # ------------------------------------------------------------------
        # 1. Check for Direct Application Email (Email-First Strategy)
        # ------------------------------------------------------------------
        valid_emails: List[str] = []
        email_source = ""

        # Check /bewerben-email/ subpage route
        email_subpage_links = re.findall(
            r'href=[\'"](/stellenanzeigen/[^\'"]+/bewerben-email/?)[\'"]',
            unescaped_main,
            re.I,
        )
        for rel_link in email_subpage_links:
            sub_url = urllib.parse.urljoin(final_job_url, rel_link)
            try:
                sub_r = _get_page(sub_url, tm=6, redir=True)
                if sub_r.status_code == 200 and sub_r.text:
                    sub_text = html_lib.unescape(sub_r.text)
                    # A. validateAndTrackAndOpen or setApplication mailto
                    for m_js in re.findall(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', sub_text, re.I):
                        e_low = m_js.strip().lower()
                        ok_e, _ = is_email_compatible_with_employer(e_low, company)
                        if ok_e and e_low not in valid_emails:
                            valid_emails.append(e_low)
                            email_source = "azubiyo_bewerben_email_js"

                    # B. Cloudflare protected emails
                    for cf_e in extract_cf_emails_from_text(sub_r.text):
                        ok_e, _ = is_email_compatible_with_employer(cf_e, company)
                        if ok_e and cf_e not in valid_emails:
                            valid_emails.append(cf_e)
                            email_source = "azubiyo_bewerben_email_cf"
            except Exception as exc:
                logger.debug("[Azubiyo] Error fetching bewerben-email %s: %s", sub_url, exc)

        # Also check mailto links in scoped main job HTML
        if not valid_emails:
            for a_el in main_container.find_all("a", href=True):
                ahref = a_el["href"].strip()
                if ahref.startswith("mailto:"):
                    clean_em = ahref.replace("mailto:", "").split("?")[0].strip().lower()
                    if EMAIL_PATTERN.match(clean_em) and "azubiyo.de" not in clean_em:
                        ok_e, _ = is_email_compatible_with_employer(clean_em, company)
                        if ok_e and clean_em not in valid_emails:
                            valid_emails.append(clean_em)
                            email_source = "azubiyo_job_detail_mailto"

        # If a verified application email is found -> save and return immediately (email first!)
        if valid_emails:
            norm = dict(job)
            norm["job_listing_url"] = final_job_url
            norm["email"] = valid_emails[0]
            norm["email_extracted"] = True
            norm["email_type"] = "recruitment"
            norm["has_form"] = False
            norm["form_link"] = ""
            norm["direct_application_url"] = ""
            norm["bewerbung_link"] = final_job_url
            norm["apply_url"] = final_job_url
            norm["application_method"] = "email"
            norm["bewerbung_art"] = "E-Mail-Bewerbung"
            norm["application_url_type"] = "none"
            norm["extraction_method"] = "fast_http"
            norm["extraction_status"] = "verified_email"
            norm["application_button_found"] = bool(email_subpage_links)
            norm["application_button_clicked"] = False
            if valid_phones:
                norm["phone"] = valid_phones[0]
            if contact_person:
                norm["contact_person"] = contact_person
                norm["arbeitsgeber"] = contact_person

            attach_contact_provenance(
                norm,
                source_url=final_job_url,
                section=email_source,
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            if self.job_cache:
                self.job_cache.put(final_job_url, norm, company=company)
            return norm

        # ------------------------------------------------------------------
        # 2. Check for Same-Page / On-Portal Schnellbewerbung Form
        # ------------------------------------------------------------------
        schnell_links = re.findall(
            r'href=[\'"](/stellenanzeigen/[^\'"]+/schnellbewerbung/?)[\'"]',
            unescaped_main,
            re.I,
        )
        if schnell_links:
            schnell_url = urllib.parse.urljoin(final_job_url, schnell_links[0])
            try:
                s_resp = _get_page(schnell_url, tm=6, redir=True)
                if s_resp.status_code == 200 and s_resp.text:
                    s_soup = BeautifulSoup(s_resp.text, "html.parser")
                    # Check for on-page candidate input fields
                    s_inputs = [inp.get("name") or inp.get("type") or "" for inp in s_soup.find_all(["input", "textarea"])]
                    s_text = s_soup.get_text(" ", strip=True).lower()
                    if any(req in s_text for req in ["schnellbewerbung", "vorname", "nachname", "deine e-mail"]) or any("email" in i for i in s_inputs):
                        norm = dict(job)
                        norm["job_listing_url"] = final_job_url
                        norm["email"] = ""
                        norm["email_extracted"] = False
                        norm["has_form"] = True
                        norm["form_link"] = schnell_url
                        norm["direct_application_url"] = schnell_url
                        norm["bewerbung_link"] = schnell_url
                        norm["apply_url"] = schnell_url
                        norm["application_method"] = "form"
                        norm["bewerbung_art"] = "Online-Formular"
                        norm["application_url_type"] = "same_page_application_form"
                        norm["application_form_detected"] = True
                        norm["application_form_selector"] = "form.schnellbewerbung"
                        norm["application_button_found"] = True
                        norm["application_button_clicked"] = False
                        norm["application_initial_url"] = schnell_url
                        norm["application_final_url"] = schnell_url
                        norm["application_navigation_type"] = "same_page_form"
                        norm["extraction_method"] = "fast_http"
                        norm["extraction_status"] = "verified_application_form"
                        if valid_phones:
                            norm["phone"] = valid_phones[0]
                        if contact_person:
                            norm["contact_person"] = contact_person
                            norm["arbeitsgeber"] = contact_person

                        attach_contact_provenance(
                            norm,
                            source_url=final_job_url,
                            section="azubiyo_schnellbewerbung_form",
                            extraction_method="fast_http",
                            verified=True,
                            form_link_source="azubiyo_schnellbewerbung",
                            form_link_verified=True,
                        )
                        norm = normalize_job_opportunity_row(norm)
                        if self.job_cache:
                            self.job_cache.put(final_job_url, norm, company=company)
                        return norm
            except Exception as exc:
                logger.debug("[Azubiyo] Error inspecting schnellbewerbung %s: %s", schnell_url, exc)

        # ------------------------------------------------------------------
        # 3. Check for External Application URL (/bewerben/ or inline JS)
        # ------------------------------------------------------------------
        candidate_destinations: List[Tuple[str, str, str]] = []  # (source, initial_url, final_url)

        # A. Inline JS on main page: validateAndTrackAndOpen or setApplication
        inline_matches = re.findall(
            r'(?:validateAndTrackAndOpen|setApplication)\s*\(\s*\d+\s*,\s*[\'"](https?://[^\'"]+)[\'"]',
            unescaped_main,
            re.I,
        )
        for raw_u in inline_matches:
            clean_u = unescape_js_unicode(raw_u)
            if "azubiyo.de" not in clean_u.lower():
                candidate_destinations.append(("azubiyo_inline_js", clean_u, clean_u))

        # B. Subpage /bewerben/
        apply_links = re.findall(
            r'href=[\'"](/stellenanzeigen/[^\'"]+/bewerben/?)[\'"]',
            unescaped_main,
            re.I,
        )
        for rel_link in apply_links:
            sub_url = urllib.parse.urljoin(final_job_url, rel_link)
            try:
                sub_r = _get_page(sub_url, tm=8, redir=True)
                # Did it redirect off azubiyo.de directly?
                if sub_r.url and "azubiyo.de" not in sub_r.url.lower():
                    candidate_destinations.append(("azubiyo_bewerben_http_redirect", sub_url, sub_r.url))
                elif sub_r.status_code == 200 and sub_r.text:
                    sub_text = html_lib.unescape(sub_r.text)
                    # Check JS targets or data-ng-click
                    js_targets = re.findall(
                        r'(?:validateAndTrackAndOpen|setApplication)\s*\(\s*\d+\s*,\s*[\'"](https?://[^\'"]+)[\'"]',
                        sub_text,
                        re.I,
                    )
                    for raw_ju in js_targets:
                        clean_ju = unescape_js_unicode(raw_ju)
                        if "azubiyo.de" not in clean_ju.lower():
                            candidate_destinations.append(("azubiyo_bewerben_js_target", sub_url, clean_ju))
            except Exception as exc:
                logger.debug("[Azubiyo] Error fetching bewerben subpage %s: %s", sub_url, exc)

        # Evaluate candidate destinations
        for src_label, init_dest, target_url in candidate_destinations:
            # Resolve redirects if necessary
            final_target, redir_chain = self._resolve_redirect_chain(target_url, session=sess)
            val_meta = classify_and_validate_destination(final_target, job)
            is_verified = bool(val_meta.get("application_url_verified"))
            dest_type = str(val_meta.get("application_url_type") or "")

            if is_verified or dest_type in (
                ApplicationDestinationType.DIRECT_APPLICATION_FORM.value,
                ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE.value,
                ApplicationDestinationType.RECRUITMENT_PORTAL.value,
            ):
                norm = dict(job)
                norm["job_listing_url"] = final_job_url
                norm["email"] = ""
                norm["email_extracted"] = False
                norm["has_form"] = True
                norm["form_link"] = final_target
                norm["direct_application_url"] = final_target
                norm["bewerbung_link"] = final_target
                norm["apply_url"] = final_target
                norm["application_method"] = "form"
                norm["bewerbung_art"] = "Online-Bewerbungsportal"
                norm["application_url_type"] = dest_type or "job_specific_application_page"
                norm["application_button_found"] = True
                norm["application_button_clicked"] = False
                norm["application_initial_url"] = init_dest
                norm["application_final_url"] = final_target
                norm["application_redirect_chain"] = redir_chain
                norm["application_navigation_type"] = src_label
                norm["extraction_method"] = "fast_http"
                norm["extraction_status"] = "verified_application_form"
                if valid_phones:
                    norm["phone"] = valid_phones[0]
                if contact_person:
                    norm["contact_person"] = contact_person
                    norm["arbeitsgeber"] = contact_person

                attach_contact_provenance(
                    norm,
                    source_url=final_job_url,
                    section=src_label,
                    extraction_method="fast_http",
                    verified=True,
                    form_link_source=src_label,
                    form_link_verified=True,
                    application_url_source=src_label,
                    application_url_verified=True,
                )
                norm = normalize_job_opportunity_row(norm)
                if self.job_cache:
                    self.job_cache.put(final_job_url, norm, company=company)
                if self.employer_cache and not is_non_employer_domain(final_target):
                    self.employer_cache.put(company=company, city=str(job.get("city") or ""), url_or_domain=final_target, data=norm)
                return norm

            # Check if login required
            if dest_type == ApplicationDestinationType.LOGIN_REQUIRED.value:
                norm = dict(job)
                norm["job_listing_url"] = final_job_url
                norm["email"] = ""
                norm["email_extracted"] = False
                norm["has_form"] = False
                norm["direct_application_url"] = final_target
                norm["form_link"] = final_target
                norm["bewerbung_link"] = final_target
                norm["apply_url"] = final_target
                norm["application_method"] = "portal_login_required"
                norm["bewerbung_art"] = "Portal-Registrierung erforderlich"
                norm["application_url_type"] = "login_required"
                norm["application_button_found"] = True
                norm["application_button_clicked"] = False
                norm["application_initial_url"] = init_dest
                norm["application_final_url"] = final_target
                norm["application_redirect_chain"] = redir_chain
                norm["extraction_method"] = "fast_http"
                norm["extraction_status"] = "completed"
                if valid_phones:
                    norm["phone"] = valid_phones[0]
                if contact_person:
                    norm["contact_person"] = contact_person
                    norm["arbeitsgeber"] = contact_person

                attach_contact_provenance(
                    norm,
                    source_url=final_job_url,
                    section=src_label,
                    extraction_method="fast_http",
                    verified=True,
                )
                norm = normalize_job_opportunity_row(norm)
                if self.job_cache:
                    self.job_cache.put(final_job_url, norm, company=company)
                return norm

        return None

    def _extract_via_selenium(
        self,
        job: Dict[str, Any],
        job_url: str,
        company: str,
        driver: Any,
        on_stage_change: Optional[Callable[[str], None]] = None,
        worker_id: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Executes Selenium browser automation when Fast HTTP did not resolve the application destination.
        Clicks 'Jetzt bewerben', handles new tabs/windows, tracks redirects, and inspects same-page forms.
        """
        try:
            driver.get(job_url)
            time.sleep(1.0)
            accept_cookies(driver)

            initial_url = getattr(driver, "current_url", "") or job_url
            initial_handles = list(getattr(driver, "window_handles", []))
            initial_form_count = len(driver.find_elements(By.TAG_NAME, "form"))

            # Locate "Jetzt bewerben" element
            apply_el = None
            button_found = False

            # Search priority: explicit apply anchor with href, semantic button, text match
            candidates = driver.find_elements(
                By.XPATH,
                "//a[contains(@href, '/bewerben/') or contains(@href, '/schnellbewerbung/') or contains(@href, '/bewerben-email/')]"
                " | //a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'bewerben')]"
                " | //button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'bewerben')]"
                " | //button[contains(@class, 'btn-primary')]",
            )

            for cand in candidates:
                try:
                    txt = (cand.text or "").strip().lower()
                    href = (cand.get_attribute("href") or "").strip().lower()
                    if any(bad in href for bad in ["/lebenslauf/", "/unterrichtsmaterial/", "/anschreiben/", "/vorlagen/"]):
                        continue
                    if "bewerben" in txt or "bewerben" in href or "bewerbung" in txt:
                        apply_el = cand
                        button_found = True
                        break
                except Exception:
                    continue

            if not apply_el:
                logger.info("[Azubiyo] [Worker %s] No Jetzt bewerben button found on %s", worker_id, job_url)
                return None

            # Click the button
            logger.info("[Azubiyo] [Worker %s] Clicking Jetzt bewerben on %s", worker_id, job_url)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", apply_el)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", apply_el)
            except Exception as click_err:
                logger.debug("[Azubiyo] [Worker %s] Click error, trying direct click: %s", worker_id, click_err)
                apply_el.click()

            time.sleep(2.5)

            # Check navigation outcomes
            current_handles = list(driver.window_handles)

            # --------------------------------------------------------------
            # Scenario D: New Browser Tab / Window Opened
            # --------------------------------------------------------------
            if len(current_handles) > len(initial_handles):
                new_handles = [h for h in current_handles if h not in initial_handles]
                if new_handles:
                    new_tab = new_handles[0]
                    driver.switch_to.window(new_tab)
                    time.sleep(1.5)
                    dest_url = driver.current_url
                    dest_title = driver.title

                    # If internal /bewerben/ page loaded in new tab, check for Weiter button
                    if "azubiyo.de" in dest_url.lower() and "/bewerben/" in dest_url.lower():
                        weiter_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Weiter')]")
                        if weiter_btns:
                            w_btn = weiter_btns[0]
                            ng_click = w_btn.get_attribute("data-ng-click") or w_btn.get_attribute("ng-click") or ""
                            m_ng = re.search(r'[\'"](https?://[^\'"]+)[\'"]', ng_click)
                            if m_ng:
                                dest_url = unescape_js_unicode(m_ng.group(1))
                            else:
                                driver.execute_script("arguments[0].click();", w_btn)
                                time.sleep(2.0)
                                dest_url = driver.current_url

                    val_res = classify_and_validate_destination(dest_url, job)
                    is_verified = bool(val_res.get("application_url_verified"))
                    dest_type = str(val_res.get("application_url_type") or "")

                    # Close the newly created tab safely
                    try:
                        driver.close()
                    except Exception:
                        pass
                    driver.switch_to.window(initial_handles[0])

                    if is_verified or dest_type in (
                        ApplicationDestinationType.DIRECT_APPLICATION_FORM.value,
                        ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE.value,
                        ApplicationDestinationType.RECRUITMENT_PORTAL.value,
                    ):
                        norm = dict(job)
                        norm["job_listing_url"] = initial_url
                        norm["email"] = ""
                        norm["email_extracted"] = False
                        norm["has_form"] = True
                        norm["form_link"] = dest_url
                        norm["direct_application_url"] = dest_url
                        norm["bewerbung_link"] = dest_url
                        norm["apply_url"] = dest_url
                        norm["application_method"] = "form"
                        norm["bewerbung_art"] = "Online-Bewerbungsportal"
                        norm["application_url_type"] = dest_type or "job_specific_application_page"
                        norm["application_button_found"] = True
                        norm["application_button_clicked"] = True
                        norm["application_initial_url"] = initial_url
                        norm["application_final_url"] = dest_url
                        norm["application_navigation_type"] = "new_browser_tab"
                        norm["extraction_method"] = "selenium"
                        norm["extraction_status"] = "verified_application_form"
                        attach_contact_provenance(
                            norm,
                            source_url=initial_url,
                            section="azubiyo_selenium_new_tab",
                            extraction_method="selenium",
                            verified=True,
                            form_link_source="azubiyo_selenium_new_tab",
                            form_link_verified=True,
                            application_url_source="azubiyo_selenium_new_tab",
                            application_url_verified=True,
                        )
                        norm = normalize_job_opportunity_row(norm)
                        return norm

            # --------------------------------------------------------------
            # Scenario A / C: External URL or Redirect on Same Tab
            # --------------------------------------------------------------
            curr_url = driver.current_url
            if curr_url and curr_url != initial_url and "azubiyo.de" not in curr_url.lower():
                val_res = classify_and_validate_destination(curr_url, job)
                is_verified = bool(val_res.get("application_url_verified"))
                dest_type = str(val_res.get("application_url_type") or "")

                if is_verified:
                    norm = dict(job)
                    norm["job_listing_url"] = initial_url
                    norm["email"] = ""
                    norm["email_extracted"] = False
                    norm["has_form"] = True
                    norm["form_link"] = curr_url
                    norm["direct_application_url"] = curr_url
                    norm["bewerbung_link"] = curr_url
                    norm["apply_url"] = curr_url
                    norm["application_method"] = "form"
                    norm["bewerbung_art"] = "Online-Bewerbungsportal"
                    norm["application_url_type"] = dest_type or "job_specific_application_page"
                    norm["application_button_found"] = True
                    norm["application_button_clicked"] = True
                    norm["application_initial_url"] = initial_url
                    norm["application_final_url"] = curr_url
                    norm["application_navigation_type"] = "same_tab_redirect"
                    norm["extraction_method"] = "selenium"
                    norm["extraction_status"] = "verified_application_form"
                    attach_contact_provenance(
                        norm,
                        source_url=initial_url,
                        section="azubiyo_selenium_same_tab_redirect",
                        extraction_method="selenium",
                        verified=True,
                        form_link_source="azubiyo_selenium_same_tab_redirect",
                        form_link_verified=True,
                    )
                    norm = normalize_job_opportunity_row(norm)
                    return norm

            # --------------------------------------------------------------
            # Scenario E: Same-Page Application (Schnellbewerbung / Modal)
            # --------------------------------------------------------------
            post_forms = driver.find_elements(By.TAG_NAME, "form")
            if "/schnellbewerbung/" in curr_url.lower() or len(post_forms) > initial_form_count or driver.find_elements(By.XPATH, "//input[@type='email']"):
                norm = dict(job)
                norm["job_listing_url"] = initial_url
                norm["email"] = ""
                norm["email_extracted"] = False
                norm["has_form"] = True
                norm["form_link"] = curr_url
                norm["direct_application_url"] = curr_url
                norm["bewerbung_link"] = curr_url
                norm["apply_url"] = curr_url
                norm["application_method"] = "form"
                norm["bewerbung_art"] = "Online-Formular"
                norm["application_url_type"] = "same_page_application_form"
                norm["application_form_detected"] = True
                norm["application_form_selector"] = "form.schnellbewerbung"
                norm["application_button_found"] = True
                norm["application_button_clicked"] = True
                norm["application_initial_url"] = initial_url
                norm["application_final_url"] = curr_url
                norm["application_navigation_type"] = "same_page_application_form"
                norm["extraction_method"] = "selenium"
                norm["extraction_status"] = "verified_application_form"
                attach_contact_provenance(
                    norm,
                    source_url=initial_url,
                    section="azubiyo_selenium_same_page_form",
                    extraction_method="selenium",
                    verified=True,
                    form_link_source="azubiyo_selenium_same_page_form",
                    form_link_verified=True,
                )
                norm = normalize_job_opportunity_row(norm)
                return norm

        except Exception as exc:
            logger.warning("[Azubiyo] [Worker %s] Selenium extraction error for %s: %s", worker_id, job_url, exc)

        return None
