import threading
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import pandas as pd
import requests
from selenium.webdriver.common.by import By

from .browser_driver import find_browser, new_options, start_driver
from .true_captcha_solver import TrueCaptchaSolver
from .application_form_discovery import (
    ApplicationFormDiscovery,
    normalize_job_opportunity_row,
)
from services.worker_network_router import (
    WorkerNetworkProfile,
    apply_proxy_to_browser_options,
    redact_proxy_url,
)

logger = logging.getLogger(__name__)
NAME_PATTERN = r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'.-]+"
ARBEITGEBER_PATTERN = re.compile(
    rf"\b(?:Frau|Herr|Herrn)\s+(?:(?:Dr|Prof)\.?\s+)?{NAME_PATTERN}(?:\s+{NAME_PATTERN}){{0,3}}\b",
    re.IGNORECASE,
)
PROGRESS_DIR = Path("data") / "progress"


def normalize_arbeitsgeber(value: Optional[str]) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw:
        return ""

    match = ARBEITGEBER_PATTERN.search(raw)
    candidate = match.group(0) if match else raw
    from services.data_validator import sanitize_contact_person
    ok, cleaned, _ = sanitize_contact_person(candidate)
    return cleaned if ok else ""


class WorkingEmailExtractor:
    def __init__(
        self,
        captcha_userid: str,
        captcha_apikey: str,
        headless: bool = True,
        known_emails: Optional[Set[str]] = None,
        initial_stats: Optional[Dict] = None,
        worker_id: int = 1,
        network_profile: Optional[WorkerNetworkProfile] = None,
        job_id: str = "",
    ):
        self.worker_id = worker_id
        self.job_id = job_id
        self.network_profile = network_profile
        self.headless = headless
        self._jobs_since_recycle = 0
        # Enforce fail-closed if network profile is failed and direct fallback disabled
        if network_profile and network_profile.connection_status == "failed" and not network_profile.allow_direct_fallback:
            raise RuntimeError(
                f"Fail-closed enforced for worker {worker_id}: Network route offline ({network_profile.error_message or 'Proxy unreachable'}). Direct fallback is disabled."
            )

        self.captcha_solver = TrueCaptchaSolver(captcha_userid, captcha_apikey, worker_id=worker_id, job_id=job_id)
        self.setup_driver(headless)
        try:
            self.driver.set_page_load_timeout(20)
            self.driver.set_script_timeout(15)
        except Exception:
            pass
        self.known_emails = {self._normalize_email(e) for e in (known_emails or set()) if e}

        # Isolated requests.Session for this worker
        self.session = requests.Session()
        if self.network_profile and self.network_profile.proxy_url:
            self.session.proxies.update({
                "http": self.network_profile.proxy_url,
                "https": self.network_profile.proxy_url,
            })

        self.form_discovery = ApplicationFormDiscovery(session=self.session)
        from .arbeitsagentur_extractor import ArbeitsagenturDetailExtractor
        self.aa_extractor = ArbeitsagenturDetailExtractor(session=self.session)
        self.current_job: Dict[str, Any] = {}
        self.on_stage_change: Optional[Callable[[str], None]] = None
        init_s = initial_stats or {}
        self.stats = {
            "processed": int(init_s.get("processed", 0)),
            "emails_found": int(init_s.get("emails_found", 0)),
            "recruitment_emails": int(init_s.get("recruitment_emails", 0)),
            "forms_found": int(init_s.get("forms_found", 0)),
            "external_links": int(init_s.get("external_links", 0)),
            "fast_path_hits": int(init_s.get("fast_path_hits", 0)),
            "selenium_fallbacks": int(init_s.get("selenium_fallbacks", 0)),
            "rate_limited_count": int(init_s.get("rate_limited_count", 0)),
            "captchas_encountered": int(init_s.get("captchas_encountered", 0)),
            "captchas_solved": int(init_s.get("captchas_solved", 0)),
            "failed": int(init_s.get("failed", 0)),
        }
        self.employer_cache: Dict[str, Dict] = {}
        self._cache_lock = threading.Lock()
        self.selenium_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        PROGRESS_DIR.mkdir(parents=True, exist_ok=True)

    def _normalize_email(self, value: Optional[str]) -> str:
        if not value:
            return ""
        return str(value).strip().strip(".,;:").lower()

    def setup_driver(self, headless: bool):
        browser_name, binary_path = find_browser()
        options = new_options(browser_name)
        options.binary_location = binary_path
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        # CAPTCHA images must load in the original authenticated browser.

        # Configure worker proxy if assigned
        has_auth_creds = False
        prof = getattr(self, "network_profile", None)
        if prof and prof.proxy_url:
            apply_proxy_to_browser_options(options, prof)
            has_auth_creds = bool(prof.get_credentials())

        if not has_auth_creds:
            options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        prefs = {
            "profile.managed_default_content_settings.images": 1,
            "profile.default_content_setting_values.notifications": 2,
            "profile.default_content_setting_values.media_stream": 2,
            "profile.default_content_setting_values.geolocation": 2,
        }
        try:
            options.add_experimental_option("prefs", prefs)
        except Exception:
            pass
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        self.driver = start_driver(browser_name, options)

    def recycle_driver_if_needed(self, force: bool = False) -> None:
        """
        Safely recycles the Selenium WebDriver if it has processed >= 50 jobs or if the browser process is unresponsive.
        Prevents memory leaks and process bloat across long-running extractions.
        """
        needs_recycle = force
        with self.selenium_lock:
            if not needs_recycle:
                if getattr(self, "_jobs_since_recycle", 0) >= 50:
                    needs_recycle = True
                elif not getattr(self, "driver", None):
                    needs_recycle = True
                else:
                    try:
                        _ = getattr(self.driver, "current_url", "")
                    except Exception:
                        needs_recycle = True

            if needs_recycle:
                logger.info(
                    "[Worker %s] Recycling Selenium WebDriver session (jobs processed: %s)...",
                    self.worker_id,
                    getattr(self, "_jobs_since_recycle", 0),
                )
                try:
                    if hasattr(self, "driver") and self.driver:
                        self.driver.quit()
                except Exception as e:
                    logger.debug("[Worker %s] Error quitting driver during recycling: %s", self.worker_id, e)
                finally:
                    self.driver = None

                try:
                    self.setup_driver(getattr(self, "headless", True))
                    if self.driver:
                        self.driver.set_page_load_timeout(20)
                        self.driver.set_script_timeout(15)
                    self._jobs_since_recycle = 0
                    logger.info("[Worker %s] Successfully recycled Selenium WebDriver session.", self.worker_id)
                except Exception as rec_err:
                    logger.error("[Worker %s] Failed to recreate WebDriver during recycling: %s", self.worker_id, rec_err)

    def check_for_captcha(self) -> bool:
        captcha_selectors = [
            "//img[contains(translate(@src,'CAPTCHA','captcha'), 'captcha')]",
            "//img[contains(translate(@alt,'CAPTCHA','captcha'), 'captcha')]",
            "//div[contains(translate(@class,'CAPTCHA','captcha'), 'captcha')]//img",
        ]
        for selector in captcha_selectors:
            try:
                if self.driver.find_elements(By.XPATH, selector):
                    return True
            except Exception:
                continue
        return False

    def has_recaptcha_marker(self) -> bool:
        selectors = [
            "//iframe[contains(@src, 'recaptcha')]",
            "//div[contains(@class, 'g-recaptcha')]",
            "//iframe[contains(@src, 'hcaptcha')]",
        ]
        for selector in selectors:
            try:
                if self.driver.find_elements(By.XPATH, selector):
                    return True
            except Exception:
                continue
        return False

    def is_blocked_page(self) -> bool:
        try:
            text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        except Exception:
            return False
        indicators = [
            "sicherheitsabfrage",
            "security check",
            "kein roboter",
            "captcha",
            "unusual traffic",
            "ungewöhnlicher verkehr",
        ]
        return any(ind in text for ind in indicators)

    def save_captcha_snapshot(self, static_dir: str = "static") -> str:
        target_dir = Path(static_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = target_dir / "captcha_latest.png"
        self.driver.save_screenshot(str(snapshot_path))
        return str(snapshot_path)

    def _request_manual_captcha_review(
        self,
        domain: str,
        corr_id: str,
        challenge_type: str,
        captcha_img_element: Optional[Any] = None,
        job_url: str = "",
    ) -> bool:
        from services.manual_captcha_service import get_manual_captcha_manager
        from services.captcha_monitor import get_captcha_tracker

        manager = get_manual_captcha_manager()
        tracker = get_captcha_tracker(self.job_id)

        from services.manual_captcha_service import capture_loaded_captcha
        img_b64 = ""
        capture_error = ""
        if captcha_img_element is not None and challenge_type == "image_text":
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", captcha_img_element)
            except Exception:
                pass
            img_b64, capture_error = capture_loaded_captcha(self.driver, captcha_img_element)

        curr_job = getattr(self, "current_job", {}) or {}
        platform = curr_job.get("source") or curr_job.get("portal") or "Unknown"
        job_title = curr_job.get("title") or curr_job.get("job_title") or curr_job.get("name") or "Apprenticeship Position"
        employer = curr_job.get("company") or curr_job.get("firma") or "Employer"
        target_url = job_url or curr_job.get("url") or getattr(self.driver, "current_url", "") or ""

        def submit_handler(solution_text: str) -> Tuple[bool, str]:
            input_el = self._find_captcha_input()
            if not input_el:
                return False, "CAPTCHA-Eingabefeld auf der Seite nicht gefunden."
            try:
                input_el.clear()
                input_el.send_keys(solution_text)
            except Exception:
                try:
                    self.driver.execute_script(
                        "arguments[0].value = arguments[1];"
                        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                        input_el,
                        solution_text,
                    )
                except Exception as e:
                    return False, f"Fehler beim Übertragen des Codes: {e}"

            submit_btn = self._find_submit_button()
            if submit_btn:
                try:
                    submit_btn.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", submit_btn)
            time.sleep(2)

            unblocked = not self.is_blocked_page()
            contact_visible = True
            if "arbeitsagentur.de" in domain:
                contact_visible = self._employer_contact_details_visible(timeout=3.0)
            if unblocked and contact_visible:
                tracker.record_website_verification(
                    correlation_id=corr_id,
                    worker_id=self.worker_id,
                    domain=domain,
                    details="Website unblocked after manual code entry",
                )
                with self._stats_lock:
                    self.stats["captchas_solved"] += 1
                return True, "Seite erfolgreich freigeschaltet."
            elif unblocked and not contact_visible:
                return False, "Code accepted, but employer contact details were not rendered yet. Please retry."
            else:
                return False, "Die Webseite bleibt blockiert. Bitte prüfen Sie den Code erneut."

        def verify_interactive_handler() -> Tuple[bool, str]:
            if not self.is_blocked_page() and not self.has_recaptcha_marker():
                tracker.record_website_verification(
                    correlation_id=corr_id,
                    worker_id=self.worker_id,
                    domain=domain,
                    details="Interactive challenge confirmed unblocked",
                )
                with self._stats_lock:
                    self.stats["captchas_solved"] += 1
                return True, "Website-Überprüfung erfolgreich abgeschlossen."
            return False, "Die Seite ist weiterhin blockiert. Bitte führen Sie die Prüfung im Browser zu Ende."

        stage_cb = getattr(self, "on_stage_change", None)
        if stage_cb:
            stage_cb("Manual CAPTCHA Review")

        challenge = manager.create_challenge(
            job_id=self.job_id,
            search_run_id=getattr(self, "search_run_id", "") or "",
            job_index=int(getattr(self, "current_job_index", 0) or 0),
            worker_id=self.worker_id,
            platform=platform,
            job_title=job_title,
            employer=employer,
            source_url=target_url,
            challenge_type=challenge_type,
            captcha_image_base64=img_b64,
            submit_handler=submit_handler,
            verify_interactive_handler=verify_interactive_handler,
            driver_ref=getattr(self, "driver", None),
            timeout_seconds=300.0,
        )

        if capture_error:
            challenge.image_error = capture_error
        res = challenge.wait_for_resolution(timeout=300.0)
        if res == "solved":
            return True
        else:
            tracker.record_manual_verification_required(
                correlation_id=corr_id,
                worker_id=self.worker_id,
                domain=domain,
                reason=f"Manual review challenge {res}",
            )
            return False

    def handle_captcha(self, job_url: str = "") -> bool:
        blocked = self.is_blocked_page()

        if not blocked:
            return True

        from services.captcha_monitor import get_captcha_tracker, generate_challenge_fingerprint
        from scraper.rate_limiter import extract_domain

        target_url = job_url or getattr(self.driver, "current_url", "") or ""
        domain = extract_domain(target_url) if target_url else "generic_portal"
        tracker = get_captcha_tracker(self.job_id)
        ch_fp = generate_challenge_fingerprint(domain, "generic-blocking-page")
        corr_id = tracker.record_challenge_detected(
            domain=domain,
            worker_id=self.worker_id,
            challenge_fingerprint=ch_fp,
            details=f"Blocking page detected on {domain}",
        )

        captcha_img = self._find_captcha_image()
        captcha_input = self._find_captcha_input()
        challenge_type = self._classify_manual_challenge(captcha_img, captcha_input)

        # If automated solver is configured and has API credentials, try fast recognition first
        has_auto_credentials = bool(
            self.captcha_solver
            and (getattr(self.captcha_solver, "apikey", None) or getattr(self.captcha_solver, "api_key", None))
        )
        if has_auto_credentials and captcha_img and captcha_input:
            solver_ctx = {
                "job_id": self.job_id,
                "worker_id": self.worker_id,
                "domain": domain,
                "correlation_id": corr_id,
            }
            captcha_text = self._solve_captcha_from_element(captcha_img, context=solver_ctx)
            if captcha_text:
                try:
                    captcha_input.clear()
                    captcha_input.send_keys(captcha_text)
                    submit_btn = self._find_submit_button()
                    if submit_btn:
                        submit_btn.click()
                    time.sleep(2)
                    if not self.is_blocked_page():
                        tracker.record_website_verification(
                            correlation_id=corr_id,
                            worker_id=self.worker_id,
                            domain=domain,
                            details="Website unblocked via automated recognition",
                        )
                        with self._stats_lock:
                            self.stats["captchas_solved"] += 1
                        return True
                except Exception as auto_err:
                    logger.debug("Automated solver submission error: %s", auto_err)

        # Route to Manual CAPTCHA Review
        logger.info("Routing challenge on %s to Manual CAPTCHA Review (type: %s)", domain, challenge_type)
        return self._request_manual_captcha_review(
            domain=domain,
            corr_id=corr_id,
            challenge_type=challenge_type,
            captcha_img_element=captcha_img,
            job_url=target_url,
        )

    def _employer_contact_details_visible(self, timeout: float = 3.0) -> bool:
        """Confirm Arbeitsagentur rendered contact details after verification."""
        deadline = time.time() + max(0.0, timeout)
        while time.time() <= deadline:
            try:
                body = self.driver.find_element(By.TAG_NAME, "body").text or ""
                if re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", body, re.I) or re.search(r"(?:\+49|0\d{2,})[\d\s/().\-]{5,}", body):
                    return True
                contact_nodes = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(translate(@id,'KONTAKT','kontakt'),'kontakt') or contains(translate(@class,'KONTAKT','kontakt'),'kontakt') or contains(translate(@id,'BEWERB','bewerb'),'bewerb')]",
                )
                if contact_nodes and any((getattr(node, "text", "") or "").strip() for node in contact_nodes):
                    return True
            except Exception:
                pass
            time.sleep(0.15)
        return False

    def _classify_manual_challenge(self, captcha_img=None, captcha_input=None) -> str:
        """Classify only from live DOM evidence; never infer a text CAPTCHA from a generic image alone."""
        try:
            turnstile = self.driver.find_elements(
                By.XPATH,
                "//iframe[contains(@src,'challenges.cloudflare.com')] | //*[@class and contains(@class,'cf-turnstile')] | //*[@id='cf-chl-widget']",
            )
            if turnstile:
                return "turnstile"
        except Exception:
            pass
        if self.has_recaptcha_marker():
            return "recaptcha"
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            login_markers = ("anmelden", "einloggen", "login required", "sign in", "registrieren")
            password_fields = self.driver.find_elements(By.XPATH, "//input[@type='password']")
            if password_fields and any(marker in body_text for marker in login_markers):
                return "login_required"
        except Exception:
            pass
        if captcha_img is not None and captcha_input is not None:
            return "image_text"
        return "unknown"

    def _find_captcha_image(self):
        selectors = [
            "//*[@id='kontaktdaten-captcha-image']",
            "//div[contains(@class,'captcha-container-image')]//img",
            "//img[contains(@src, 'captcha') or contains(@src, 'ct/v1/captcha') or contains(@src, 'Sicherheitsabfrage')]",
            "//img[contains(@alt, 'Sicherheitsabfrage') or contains(@alt, 'captcha')]",
            "//img[contains(@id, 'captcha')]",
            "//img[contains(@class, 'captcha')]",
            "//div[contains(@class, 'captcha')]//img",
        ]
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.XPATH, selector)
                for el in elements:
                    try:
                        size = el.size
                        if size and (size.get("width", 0) < 30 or size.get("height", 0) < 10):
                            continue
                        return el
                    except Exception:
                        return el
            except Exception:
                continue
        return None

    def _find_captcha_input(self):
        selectors = [
            "//input[@formcontrolname='captcha']",
            "//*[@id='kontaktdaten-captcha-input']",
            "//input[contains(@name, 'captcha')]",
            "//input[contains(@id, 'captcha')]",
            "//input[contains(@placeholder, 'CAPTCHA')]",
            "//input[contains(@placeholder, 'captcha')]",
        ]
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.XPATH, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def _find_submit_button(self):
        selectors = [
            "//*[@id='kontaktdaten-captcha-absenden-button']",
            "//*[@id='kontaktdaten-captcha-submit-button']",
            "//button[ancestor::*[contains(@class,'captcha')] and (@type='submit' or contains(translate(.,'ABSENDENBESTÄTIGEN','absendenbestätigen'),'absenden') or contains(translate(.,'ABSENDENBESTÄTIGEN','absendenbestätigen'),'bestätigen'))]",
            "//button[@type='submit']",
            "//input[@type='submit']",
            "//button[contains(text(), 'Weiter')]",
            "//button[contains(text(), 'Submit')]",
            "//button[contains(text(), 'Bestaetigen')]",
            "//button[contains(text(), 'Bestatigen')]",
        ]
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.XPATH, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def _solve_captcha_from_element(self, captcha_img, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        try:
            img_src = captcha_img.get_attribute("src")
            if img_src and img_src.startswith("data:image"):
                image_bytes = base64.b64decode(img_src.split(",", 1)[1])
                return self.captcha_solver.solve_captcha(image_bytes, context=context)
            if img_src and img_src.startswith("http"):
                img_response = requests.get(img_src, timeout=20)
                if img_response.status_code == 200 and img_response.content:
                    return self.captcha_solver.solve_captcha(img_response.content, context=context)
            return self.captcha_solver.solve_from_screenshot(self.driver, captcha_img, context=context)
        except Exception as exc:
            logger.error("Error solving CAPTCHA: %s", exc)
            return None

    def extract_contact_info(self):
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            page_text = ""
        self._last_page_text = page_text

        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        emails = re.findall(email_pattern, page_text)

        # Phone extraction: prioritize tel: links, then labeled cues, then validate
        from services.data_validator import validate_phone_number
        phones = []
        try:
            tel_elements = self.driver.find_elements(By.XPATH, "//a[starts-with(@href, 'tel:')]")
            for tel_el in tel_elements:
                href = (tel_el.get_attribute("href") or "").replace("tel:", "").strip()
                ok, clean_p, _ = validate_phone_number(href)
                if ok and clean_p not in phones:
                    phones.append(clean_p)
        except Exception:
            pass

        if not phones:
            tel_cues = re.findall(
                r"(?:tel(?:efon)?\.?|fon|phone|mobil|hotline)\s*[:\-\s]\s*([+0-9\s/().\-]{7,25})",
                page_text,
                re.IGNORECASE,
            )
            for cue in tel_cues:
                ok, clean_p, _ = validate_phone_number(cue)
                if ok and clean_p not in phones:
                    phones.append(clean_p)

        if not phones:
            phone_patterns = [
                r"(?:\+49|0049)(?:[-\s/().]*\d){7,13}\b",
                r"\b0[1-9](?:[-\s/().]*\d){6,12}\b",
            ]
            for pattern in phone_patterns:
                for match in re.findall(pattern, page_text):
                    ok, clean_p, _ = validate_phone_number(match)
                    if ok and clean_p not in phones:
                        phones.append(clean_p)

        arbeitsgeber_match = ARBEITGEBER_PATTERN.search(page_text)
        arbeitsgeber = normalize_arbeitsgeber(
            arbeitsgeber_match.group(0) if arbeitsgeber_match else None
        ) or None
        return (emails[0] if emails else None, phones[0] if phones else None, arbeitsgeber)

    def extract_application_link(self, fallback_url: str = "") -> str:
        from services.data_validator import is_advice_or_generic_page, validate_application_url
        try:
            links = self.driver.find_elements(
                By.XPATH,
                "//a[@href and not(starts-with(@href, 'mailto:')) and not(starts-with(@href, 'tel:'))]",
            )
            for link in links:
                try:
                    href = (link.get_attribute("href") or "").strip()
                    if not href or href.startswith("javascript:") or href == "#":
                        continue
                    if is_advice_or_generic_page(href):
                        continue
                    text = (link.text or "").strip().lower()
                    title_attr = (link.get_attribute("title") or "").strip().lower()
                    aria_label = (link.get_attribute("aria-label") or "").strip().lower()
                    haystack = f"{text} {title_attr} {aria_label} {href.lower()}"

                    if any(bad in haystack for bad in ["ratgeber", "tipps", "magazin", "faq", "hilfe"]):
                        continue

                    if any(kw in haystack for kw in ["bewerb", "apply", "online-bewerb", "formular"]):
                        ok, clean_app_url, _ = validate_application_url(href)
                        if ok:
                            return clean_app_url
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Could not extract application link: %s", exc)

        return fallback_url or ""

    def accept_cookies(self) -> bool:
        """Automatically detects and clicks 'Cookies akzeptieren' on the active page/platform."""
        try:
            from .cookie_handler import accept_cookies
            return accept_cookies(getattr(self, "driver", None))
        except Exception as exc:
            logger.debug("Failed to accept cookies: %s", exc)
            return False

    def _get_cache_key(self, job: Dict) -> str:
        company = str(job.get("company") or "").strip().lower()
        city = str(job.get("city") or job.get("location") or "").strip().lower()
        if company and len(company) > 3:
            return f"{company}|{city}"
        website = str(job.get("website") or job.get("employer_website") or "").strip().lower()
        if website:
            from urllib.parse import urlparse
            return urlparse(website).netloc or website
        return ""

    def extract_via_fast_http(self, job: Dict) -> Optional[Dict]:
        """
        Rapid HTTP-first extraction in ~150ms.
        Bypasses Selenium completely when valid contact info is discovered in raw HTML or cache.
        """
        company_key = self._get_cache_key(job)
        if company_key:
            with self._cache_lock:
                cached = self.employer_cache.get(company_key)
            if cached:
                cached_res = dict(job)
                for k, v in cached.items():
                    if v and not cached_res.get(k):
                        cached_res[k] = v
                cached_res["extraction_method"] = "cache"
                return normalize_job_opportunity_row(cached_res)

        source_url = str(job.get("apply_url") or job.get("url") or "").strip()
        if not source_url or not source_url.startswith("http"):
            return None

        # 1. For Arbeitsagentur, run high-speed Stage 1 & 2
        source = str(job.get("source") or "").lower()
        if "arbeitsagentur" in source or "arbeitsagentur.de" in source_url:
            try:
                res = self.aa_extractor.extract_vacancy(job, driver=None, captcha_solver=self.captcha_solver)
                res["extraction_method"] = "fast_http"
                if res.get("email") or res.get("has_form") or res.get("direct_application_url"):
                    if company_key:
                        with self._cache_lock:
                            self.employer_cache[company_key] = {
                                "email": res.get("email"),
                                "phone": res.get("phone"),
                                "contact_person": res.get("contact_person"),
                                "direct_application_url": res.get("direct_application_url"),
                                "has_form": res.get("has_form"),
                                "application_method": res.get("application_method"),
                            }
                    return res
            except Exception as exc:
                logger.debug("Fast HTTP aa_extractor error for %s: %s", source_url, exc)

        # 2. Generic portals fast HTTP fetch
        try:
            resp = self.session.get(source_url, timeout=5)
            if resp.status_code == 200 and resp.text:
                html = resp.text
                if any(ind in html.lower() for ind in ["sicherheitsabfrage", "security check", "cf-chl-bypass"]):
                    return None

                # Safe meta-refresh redirect detection (e.g., Ausbildung.de partner/ATS redirect)
                meta_match = re.search(r'<meta[^>]*http-equiv=["\']?refresh["\']?[^>]*content=["\']?[^"\'>]*url=([^"\'\s;>]+)', html, re.IGNORECASE)
                if meta_match:
                    raw_target = meta_match.group(1).strip(" '\"")
                    resolved_target = urllib.parse.urljoin(source_url, raw_target)
                    parsed_target = urllib.parse.urlparse(resolved_target)
                    if parsed_target.scheme in ("http", "https") and parsed_target.netloc:
                        try:
                            redir_resp = self.session.get(resolved_target, timeout=5)
                            if redir_resp.status_code == 200 and redir_resp.text:
                                html = redir_resp.text
                                source_url = redir_resp.url
                        except Exception as redir_err:
                            logger.debug("Fast HTTP meta-refresh error for %s -> %s: %s", source_url, resolved_target, redir_err)

                emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", html)
                clean_emails = [e.lower() for e in emails if not any(x in e.lower() for x in ["example", "wix", "sentry", "u003c"])]
                phones = re.findall(r"(?:\+49|0049|0)\s*(?:\(0\)\s*)?[1-9][0-9\s/().\-]{5,22}[0-9]", html)

                # Check if destination is a known ATS or contains a verifiable application form
                is_ats = ApplicationFormDiscovery.is_known_ats_url(source_url)
                has_form, form_type, _ = ApplicationFormDiscovery.verify_form_page(html, source_url)

                if clean_emails or has_form or is_ats:
                    norm = dict(job)
                    if clean_emails:
                        norm["email"] = clean_emails[0]
                        norm["email_extracted"] = True
                        norm["email_type"] = "recruitment"
                    if phones:
                        norm["phone"] = phones[0]
                    if has_form or is_ats:
                        norm["has_form"] = True
                        norm["form_link"] = source_url
                        norm["direct_application_url"] = source_url
                        norm["bewerbung_link"] = source_url
                        norm["application_method"] = "form" if not clean_emails else "both"
                        norm["application_url_type"] = "direct_form"
                    norm = normalize_job_opportunity_row(norm)
                    if company_key:
                        with self._cache_lock:
                            self.employer_cache[company_key] = {
                                "email": norm.get("email"),
                                "phone": norm.get("phone"),
                                "has_form": norm.get("has_form"),
                                "direct_application_url": norm.get("direct_application_url"),
                                "application_method": norm.get("application_method"),
                            }
                    return norm
        except Exception as http_err:
            logger.debug("Fast HTTP generic error for %s: %s", source_url, http_err)

        return None

    def open_job(self, job: Dict, delay_seconds: float = 1.0) -> None:
        url = job.get("url", "")
        if url and getattr(self, "driver", None):
            self.driver.get(url)
            self.accept_cookies()
            # Smart wait: poll for content/email up to max 1.2s instead of hard 3.0s sleep
            t0 = time.time()
            max_wait = min(delay_seconds, 1.2)
            while time.time() - t0 < max_wait:
                try:
                    body = self.driver.find_element(By.TAG_NAME, "body").text
                    if "@" in body or "bewerb" in body.lower():
                        break
                except Exception:
                    pass
                time.sleep(0.15)
            self.accept_cookies()

    def process_job(
        self,
        job: Dict,
        delay_seconds: float = 3.0,
        profession_keyword: str = "",
        on_stage_change: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        """
        Processes a job or employer opportunity following source-specific rules:

        Job portals: Email first; if missing, inspect website & discover application form.
        Google Maps: Mandatory website inspection to verify an active matching Ausbildung advertisement,
                     regardless of email availability.
        """
        source = str(job.get("source") or "").strip().lower()
        self.current_job = job
        self.on_stage_change = on_stage_change
        is_google_maps = (
            "maps" in source
            or "google" in source
            or bool(job.get("maps_url"))
            or job.get("category")
        )

        # ----------------------------------------------------------------------
        # 1. Google Maps — Mandatory Exception
        # ----------------------------------------------------------------------
        if is_google_maps:
            if on_stage_change:
                on_stage_change("Verifying Business")
            from .google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier

            search_kw = profession_keyword or str(
                job.get("hauptberuf") or job.get("keyword") or job.get("title") or ""
            ).strip()

            verifier = GoogleMapsAusbildungVerifier(
                session=getattr(self.form_discovery, "session", None)
            )
            try:
                verified_job = verifier.verify_business(
                    job,
                    profession_keyword=search_kw,
                    driver=getattr(self, "driver", None),
                )
                self.stats["processed"] += 1
                if verified_job.get("is_verified_vacancy"):
                    if on_stage_change:
                        on_stage_change("Email Extraction")
                    normalized = normalize_job_opportunity_row(verified_job)
                    normalized_email = self._normalize_email(normalized.get("email"))
                    if normalized_email and "@" in normalized_email:
                        if normalized_email not in self.known_emails:
                            self.stats["emails_found"] += 1
                            self.known_emails.add(normalized_email)
                    return normalized
                else:
                    # Retain as unconfirmed potential employer
                    return verified_job
            except Exception as exc:
                logger.error("Error verifying Google Maps business %s: %s", job.get("company") or job.get("name"), exc)
                job["is_verified_vacancy"] = False
                job["verification_status"] = "error"
                job["verification_notes"] = f"Fehler bei Website-Prüfung: {exc}"
                job["status"] = "Verifizierung fehlgeschlagen (Fehler)"
                self.stats["failed"] += 1
                return job

        # ----------------------------------------------------------------------
        # 2. Arbeitsagentur Vacancies (Smart 4-Stage Extraction)
        # ----------------------------------------------------------------------
        is_arbeitsagentur = (
            "arbeitsagentur" in source
            or "arbeitsagentur.de" in str(job.get("url") or "").lower()
            or bool(job.get("reference") and str(job.get("reference")).startswith("1000"))
        )

        if is_arbeitsagentur:
            if on_stage_change:
                on_stage_change("HTTP Fast-Path")
            try:
                enriched = self.aa_extractor.extract_vacancy(
                    job,
                    driver=getattr(self, "driver", None),
                    captcha_solver=self.captcha_solver,
                    on_stage_change=on_stage_change,
                )
                self.stats["processed"] += 1
                norm_email = self._normalize_email(enriched.get("email"))
                if norm_email and "@" in norm_email:
                    if on_stage_change:
                        on_stage_change("Email Extraction")
                    if norm_email not in self.known_emails:
                        self.stats["emails_found"] += 1
                        self.known_emails.add(norm_email)
                return enriched
            except Exception as aa_err:
                logger.error("Error in Arbeitsagentur extraction: %s", aa_err)

        # ----------------------------------------------------------------------
        # 3. Generic Job Portals (Ausbildung.de, Azubiyo, AUBI-plus, IHK)
        # ----------------------------------------------------------------------
        # Fast HTTP / Cache shortcut: skip opening Selenium if contact info is found
        if on_stage_change:
            on_stage_change("HTTP Fast-Path")
        fast_res = self.extract_via_fast_http(job)
        if fast_res is not None and (fast_res.get("email") or fast_res.get("has_form") or fast_res.get("direct_application_url")):
            if on_stage_change:
                on_stage_change("Email Extraction")
            norm_email = self._normalize_email(fast_res.get("email"))
            if norm_email and "@" in norm_email:
                with self._stats_lock:
                    if norm_email not in self.known_emails:
                        self.stats["emails_found"] += 1
                        self.known_emails.add(norm_email)
            with self._stats_lock:
                self.stats["processed"] += 1
                self.stats["fast_path_hits"] += 1
            fast_res.setdefault("extraction_method", "fast_http")
            return fast_res

        try:
            with self._stats_lock:
                self.stats["selenium_fallbacks"] += 1
            if on_stage_change:
                on_stage_change("Selenium Fallback")
            self.recycle_driver_if_needed()
            with self.selenium_lock:
                self.open_job(job, delay_seconds=delay_seconds)
                self.accept_cookies()

                captcha_blocked = False
                if self.is_blocked_page() or self.check_for_captcha():
                    with self._stats_lock:
                        self.stats["captchas_encountered"] += 1
                    if self.handle_captcha(job_url=job.get("url", "")):
                        time.sleep(1)
                        self.accept_cookies()
                    else:
                        captcha_blocked = True

                if on_stage_change:
                    on_stage_change("Email Extraction")
                email, phone, arbeitsgeber = self.extract_contact_info()
                apply_url = self.extract_application_link(fallback_url=job.get("url", ""))

            from services.data_validator import validate_job_listing_url, is_advice_or_generic_page
            orig_ad_url = job.get("url") or job.get("job_listing_url") or ""
            is_valid_list, clean_listing, _ = validate_job_listing_url(orig_ad_url)
            job_listing_url = clean_listing or orig_ad_url

            normalized_email = self._normalize_email(email)
            has_valid_email = bool(normalized_email and "@" in normalized_email)

            job["email"] = email if has_valid_email else ""
            job["phone"] = phone or ""
            job["arbeitsgeber"] = arbeitsgeber or ""
            job["contact_person"] = arbeitsgeber or ""
            job["email_extracted"] = has_valid_email
            job["job_listing_url"] = job_listing_url

            if apply_url and apply_url != job_listing_url and not is_advice_or_generic_page(apply_url):
                job["apply_url"] = apply_url
                job["direct_application_url"] = apply_url
            else:
                job["apply_url"] = job_listing_url
                job["direct_application_url"] = ""

            job.setdefault("extraction_method", "selenium")
            if captcha_blocked and not has_valid_email:
                job["extraction_status"] = "manual_required"
                job["manual_review_required"] = True
                job["manual_review_reason"] = "Human verification required"

            # Check portal-specific cues from page text if email is absent
            if not has_valid_email:
                page_text_lower = (getattr(self, "_last_page_text", "") or "").lower()
                src_lower = str(job.get("source") or "").lower()
                url_lower = str(job.get("url") or "").lower()
                if "ihk" in src_lower or "ihk" in url_lower:
                    if any(term in page_text_lower for term in ["schriftlich", "per post", "postalisch"]):
                        job["postal_only"] = True
                        job["application_method"] = "postal"
                        job["bewerbung_art"] = "Post / Schriftlich"
                elif "azubiyo" in src_lower or "azubiyo" in url_lower:
                    if any(term in page_text_lower for term in ["registrierung", "login", "profil erstellen", "konto erstellen", "jetzt bewerben"]):
                        job["portal_login_required"] = True
                        job["application_method"] = "portal_login_required"
                        job["bewerbung_art"] = "Portal-Registrierung erforderlich"

            # Job portals: Email first; if missing, discover the application form.
            if has_valid_email:
                # Valid email exists -> save alongside job info immediately
                job["has_form"] = False
                job["form_link"] = ""
                job["bewerbung_link"] = job.get("direct_application_url") or job.get("job_listing_url") or ""
                job = normalize_job_opportunity_row(job, discovery_result=None)
            else:
                # If no email exists, inspect original job ad & company website for application form
                if on_stage_change:
                    on_stage_change("Finding Application Form")
                discovery = self.form_discovery.discover_application_form(
                    job,
                    driver=getattr(self, "driver", None),
                )
                job = normalize_job_opportunity_row(job, discovery_result=discovery)

            self.stats["processed"] += 1
            self._jobs_since_recycle += 1
            if has_valid_email:
                if normalized_email not in self.known_emails:
                    self.stats["emails_found"] += 1
                    self.known_emails.add(normalized_email)

            if job.get("manual_review_required") or job.get("extraction_status") == "manual_required":
                if on_stage_change:
                    on_stage_change("Manual Review")

        except Exception as exc:
            logger.error("Error processing job: %s", exc)
            job["extraction_status"] = f"error: {exc}"
            job["email_extracted"] = False
            job["apply_url"] = job.get("url", "")
            job = normalize_job_opportunity_row(job)
            self.stats["failed"] += 1

        return job

    def save_progress(
        self, jobs: List[Dict], index: int, base_name: str = "auto_extraction_progress", custom_stats: Optional[Dict] = None
    ):
        json_path = PROGRESS_DIR / f"{base_name}.json"
        csv_path = PROGRESS_DIR / f"{base_name}.csv"
        stats_to_save = dict(custom_stats) if custom_stats else dict(self.stats)
        payload = {
            "job_id": getattr(self, "job_id", ""),
            "last_index": index,
            "total": len(jobs),
            "stats": stats_to_save,
            "jobs": jobs,
            "processed_jobs": jobs[: index + 1] if index >= 0 else [],
        }
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if index >= 0 and jobs[: index + 1]:
            pd.DataFrame(jobs[: index + 1]).to_csv(csv_path, index=False, encoding="utf-8")

        # Also save job-specific checkpoint file if job_id is available
        w_job_id = getattr(self, "job_id", "")
        if w_job_id:
            specific_json = PROGRESS_DIR / f"{base_name}_{w_job_id}.json"
            with specific_json.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    def close(self):
        try:
            if hasattr(self, "driver") and self.driver:
                self.driver.quit()
        except Exception:
            pass
        try:
            if hasattr(self, "session") and self.session:
                self.session.close()
        except Exception:
            pass
