import threading
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import pandas as pd
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from selenium.webdriver.common.by import By

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
from services.employer_cache import (
    get_employer_cache,
    get_job_cache,
    is_non_employer_domain,
    is_portal_domain,
    is_shortener_domain,
)
from services.contamination_detector import (
    PORTAL_SUPPORT_PHONES,
    attach_contact_provenance,
    is_email_compatible_with_employer,
    is_url_compatible_with_job,
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

        # High-performance requests.Session with connection pooling & retries
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=50,
            pool_maxsize=50,
            max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        })

        if self.network_profile and self.network_profile.proxy_url:
            self.session.proxies.update({
                "http": self.network_profile.proxy_url,
                "https": self.network_profile.proxy_url,
            })

        self.form_discovery = ApplicationFormDiscovery(session=self.session)
        from .arbeitsagentur_extractor import ArbeitsagenturDetailExtractor
        self.aa_extractor = ArbeitsagenturDetailExtractor(session=self.session)
        from .ausbildung_de_detail_extractor import AusbildungDeDetailExtractor
        self.ausbildung_extractor = AusbildungDeDetailExtractor(session=self.session)
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
        self.employer_cache = get_employer_cache()
        self.job_cache = get_job_cache()
        self._cache_lock = threading.Lock()
        self.selenium_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._worker_profile_dir: Optional[Path] = None
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
        # Eager strategy returns as soon as DOM is interactive (DOMContentLoaded), saving 3-8s per page
        options.page_load_strategy = "eager"
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-component-update")
        options.add_argument("--disable-domain-reliability")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--mute-audio")
        options.add_argument("--no-first-run")
        options.add_argument("--metrics-recording-only")

        # Unique worker profile dir to prevent Windows Chrome SingletonLock collision
        worker_dir = Path(tempfile.gettempdir()) / f"jobscout_profile_w{self.worker_id}_{os.getpid()}"
        worker_dir.mkdir(parents=True, exist_ok=True)
        self._worker_profile_dir = worker_dir
        options.add_argument(f"--user-data-dir={str(worker_dir)}")

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
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        self.driver = start_driver(browser_name, options)

        # Block fonts, media, and heavy analytics trackers via Chrome DevTools Protocol
        try:
            self.driver.execute_cdp_cmd("Network.setBlockedURLs", {
                "urls": [
                    "*.woff*", "*.ttf*", "*.otf*", "*.eot*",
                    "*google-analytics.com*", "*googletagmanager.com*",
                    "*doubleclick.net*", "*facebook.net*", "*hotjar.com*",
                    "*.mp4", "*.webm", "*.avi"
                ]
            })
            self.driver.execute_cdp_cmd("Network.enable", {})
        except Exception:
            pass

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

            # A rejected submission commonly rotates the CAPTCHA and replaces
            # the <img> node.  Never hand the pre-submit element to manual
            # review, otherwise the dashboard can show a code that no longer
            # belongs to the live form.
            captcha_img = self._find_captcha_image()
            captcha_input = self._find_captcha_input()
            challenge_type = self._classify_manual_challenge(captcha_img, captcha_input)

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

        curr_job = getattr(self, "current_job", {}) or {}
        curr_company = str(curr_job.get("company") or curr_job.get("firma") or "").strip()

        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        raw_emails = re.findall(email_pattern, page_text)
        emails = []
        for e_cand in raw_emails:
            e_low = e_cand.strip().lower()
            ok_e, _ = is_email_compatible_with_employer(e_low, curr_company)
            if ok_e and e_low not in emails:
                emails.append(e_low)

        # Phone extraction: prioritize tel: links (outside nav/header/footer), then labeled cues, then validate
        from services.data_validator import validate_phone_number
        phones = []
        try:
            tel_elements = self.driver.find_elements(
                By.XPATH,
                "//a[starts-with(@href, 'tel:') and not(ancestor::nav) and not(ancestor::header) and not(ancestor::footer)]",
            )
            for tel_el in tel_elements:
                href = (tel_el.get_attribute("href") or "").replace("tel:", "").strip()
                ok, clean_p, _ = validate_phone_number(href)
                if ok and clean_p not in PORTAL_SUPPORT_PHONES and clean_p not in phones:
                    phones.append(clean_p)
        except Exception:
            pass

        if not phones:
            tel_cues = re.findall(
                r"(?:tel(?:efon)?\.?|fon|phone|mobil)\s*[:\-\s]\s*([+0-9\s/().\-]{7,25})",
                page_text,
                re.IGNORECASE,
            )
            for cue in tel_cues:
                ok, clean_p, _ = validate_phone_number(cue)
                if ok and clean_p not in PORTAL_SUPPORT_PHONES and clean_p not in phones:
                    phones.append(clean_p)

        if not phones:
            phone_patterns = [
                r"(?:\+49|0049)(?:[-\s/().]*\d){7,13}\b",
                r"\b0[1-9](?:[-\s/().]*\d){6,12}\b",
            ]
            for pattern in phone_patterns:
                for match in re.findall(pattern, page_text):
                    ok, clean_p, _ = validate_phone_number(match)
                    if ok and clean_p not in PORTAL_SUPPORT_PHONES and clean_p not in phones:
                        phones.append(clean_p)

        arbeitsgeber_match = ARBEITGEBER_PATTERN.search(page_text)
        arbeitsgeber = normalize_arbeitsgeber(
            arbeitsgeber_match.group(0) if arbeitsgeber_match else None
        ) or None
        return (emails[0] if emails else None, phones[0] if phones else None, arbeitsgeber)

    def _resolve_shortener_url(self, short_url: str, timeout: float = 5.0) -> str:
        """Resolves URL shorteners like short.sg to the actual employer/ATS destination URL."""
        clean_u = str(short_url or "").strip()
        if not clean_u or not clean_u.startswith("http"):
            return clean_u
        if not is_shortener_domain(clean_u):
            return clean_u
        try:
            resp = self.session.get(clean_u, timeout=timeout, allow_redirects=True, stream=True)
            resolved = str(resp.url or "").strip()
            resp.close()
            if resolved and resolved.startswith("http") and not is_shortener_domain(resolved):
                return resolved
        except Exception as exc:
            logger.debug("Shortener resolution failed for %s: %s", clean_u, exc)
        return clean_u

    @staticmethod
    def _decode_cf_emails(html: str) -> List[str]:
        """Decodes Cloudflare data-cfemail / email-protection hex strings in HTML."""
        decoded: List[str] = []
        if not html or "cfemail" not in html and "email-protection#" not in html:
            return decoded
        hex_candidates = re.findall(r'(?:data-cfemail=["\']|email-protection#)([0-9a-fA-F]{10,128})', html)
        for h in hex_candidates:
            try:
                key = int(h[:2], 16)
                out_chars = [chr(int(h[i:i + 2], 16) ^ key) for i in range(2, len(h), 2)]
                cand = "".join(out_chars).strip().lower()
                if "@" in cand and "." in cand.split("@")[-1]:
                    decoded.append(cand)
            except Exception:
                continue
        return decoded

    def extract_application_link(self, fallback_url: str = "") -> str:
        from services.data_validator import is_advice_or_generic_page, validate_application_url
        try:
            # Exclude navbar, header, footer, and recommended job teaser links
            links = self.driver.find_elements(
                By.XPATH,
                "//a[@href and not(starts-with(@href, 'mailto:')) and not(starts-with(@href, 'tel:')) "
                "and not(ancestor::nav) and not(ancestor::header) and not(ancestor::footer) "
                "and not(ancestor::*[contains(@class, 'job-offer-teaser')])]",
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

                    if any(bad in haystack for bad in [
                        "ratgeber", "tipps", "magazin", "faq", "hilfe",
                        "unterrichtsmaterial", "arbeitshefte", "berufswahl",
                        "orientieren", "bewerbung2go", "stellenmarkt",
                    ]):
                        continue

                    if any(kw in haystack for kw in ["bewerb", "apply", "online-bewerb", "formular"]) or is_shortener_domain(href):
                        target_href = self._resolve_shortener_url(href) if is_shortener_domain(href) else href
                        if is_advice_or_generic_page(target_href):
                            continue
                        ok, clean_app_url, _ = validate_application_url(target_href)
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

    def _extract_scoped_dom_contacts(self, html: str, company: str = "") -> tuple:
        """
        Extracts (emails, phones, contact_person, main_soup) strictly from the current job listing body,
        after removing <nav>, <header>, <footer>, and recommended-job teasers.
        """
        from bs4 import BeautifulSoup
        from services.data_validator import validate_phone_number, sanitize_contact_person

        soup = BeautifulSoup(html or "", "html.parser")
        for noise in soup.find_all(["nav", "header", "footer", "aside"]):
            noise.decompose()
        for teaser in soup.find_all(
            lambda el: el.name in ("div", "section", "article", "li")
            and el.get("class")
            and any(
                c in " ".join(el.get("class", [])).lower()
                for c in (
                    "job-offer-teaser", "similar-jobs", "recommended-jobs",
                    "related-jobs", "other-jobs", "more-jobs", "sidebar-ad",
                )
            )
        ):
            teaser.decompose()

        scoped_html = str(soup)
        scoped_text = soup.get_text("\n", strip=True)

        # 1. Emails (mailto + CF email decode + text regex)
        cand_emails: List[str] = []
        for m in re.findall(r'href=["\']mailto:([^"\'\s>?]+)', scoped_html, re.I):
            cand_emails.append(m.strip().lower())
        cand_emails.extend(self._decode_cf_emails(scoped_html))
        for m in re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", scoped_text):
            cand_emails.append(m.strip().lower())

        valid_emails: List[str] = []
        for e in cand_emails:
            if not e or "@" not in e:
                continue
            ok_e, _ = is_email_compatible_with_employer(e, company)
            if ok_e and e not in valid_emails:
                valid_emails.append(e)

        # 2. Phones (tel: links + labeled cues + JSON-LD JobPosting description)
        valid_phones: List[str] = []
        for t in re.findall(r'href=["\']tel:([^"\']+)["\']', scoped_html, re.I):
            ok_p, clean_p, _ = validate_phone_number(t)
            if ok_p and clean_p not in PORTAL_SUPPORT_PHONES and clean_p not in valid_phones:
                valid_phones.append(clean_p)

        if not valid_phones:
            for cue in re.findall(r"(?:tel(?:efon)?\.?|fon|phone|mobil)\s*[:\-\s]\s*([+0-9\s/().\-]{7,25})", scoped_text, re.I):
                ok_p, clean_p, _ = validate_phone_number(cue)
                if ok_p and clean_p not in PORTAL_SUPPORT_PHONES and clean_p not in valid_phones:
                    valid_phones.append(clean_p)

        # 3. Contact person (JSON-LD + labeled Ansprechpartner + Frau/Herr salutation)
        contact_person = ""
        anspr_m = re.search(
            r"(?:Ansprechpartner(?:in)?|Kontaktperson)\s*[:\-]\s*([^\n\r<]{3,65})",
            scoped_text,
            re.I,
        )
        if anspr_m:
            ok_c, clean_c, _ = sanitize_contact_person(anspr_m.group(1))
            if ok_c:
                contact_person = clean_c

        if not contact_person:
            salut_m = ARBEITGEBER_PATTERN.search(scoped_text)
            if salut_m:
                ok_c, clean_c, _ = sanitize_contact_person(salut_m.group(0))
                if ok_c:
                    contact_person = clean_c

        # Check JSON-LD JobPosting in original HTML for phone/contact fallback
        ld_scripts = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html or "", re.DOTALL | re.I)
        for script in ld_scripts:
            try:
                ld_raw = json.loads(script.strip())
                ld_list = ld_raw if isinstance(ld_raw, list) else [ld_raw]
                for item in ld_list:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        desc = str(item.get("description") or "")
                        if desc and not valid_phones:
                            for cue in re.findall(r"(?:tel(?:efon)?\.?|fon|phone|mobil)\s*[:\-\s]\s*([+0-9\s/().\-]{7,25})", desc, re.I):
                                ok_p, clean_p, _ = validate_phone_number(cue)
                                if ok_p and clean_p not in PORTAL_SUPPORT_PHONES and clean_p not in valid_phones:
                                    valid_phones.append(clean_p)
                        if desc and not contact_person:
                            anspr = re.search(r"(?:Ansprechpartner(?:in)?|Kontaktperson)\s*[:\-]\s*([^\n\r<]{3,60})", desc, re.I)
                            if anspr:
                                ok_c, clean_c, _ = sanitize_contact_person(anspr.group(1))
                                if ok_c:
                                    contact_person = clean_c
            except Exception:
                pass

        return valid_emails, valid_phones, contact_person, soup

    def _extract_azubiyo_fast(self, job: Dict, html: str, final_url: str) -> Optional[Dict]:
        """
        Dedicated Azubiyo detail extractor:
        1. Inspects /stellenanzeigen/<slug>/bewerben-email/ for setApplication(1, 'mailto:...') or CF email.
        2. Inspects /stellenanzeigen/<slug>/bewerben/ for validateAndTrackAndOpen(..., 'https://...') or setApplication(2, 'https://...').
        3. Scopes phone & contact person to main job container, rejecting navbar /unterrichtsmaterial/ and portal hotline.
        """
        company = str(job.get("company") or job.get("firma") or "").strip()
        city = str(job.get("city") or job.get("location") or "").strip()

        # Recover real employer name from JSON-LD hiringOrganization if input company is a 1-letter badge (e.g. "M")
        if len(company) < 3 or company.lower() in {"n/a", "unknown", "unbekannt"}:
            m_org = re.search(r'"hiringOrganization"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"]{3,120})"', html, re.I)
            if m_org:
                company = m_org.group(1).strip()
                job["company"] = company
                job["firma"] = company

        valid_emails, valid_phones, contact_person, soup = self._extract_scoped_dom_contacts(html, company=company)
        email_source_section = "azubiyo_job_detail"
        external_apply_url = ""
        form_source_section = ""

        # 1. Check /bewerben-email/ subpage (or main page setApplication mailto)
        m_email_sub = re.search(r'href=[\'"](/stellenanzeigen/[^\'"]+/bewerben-email/?)[\'"]', html, re.I)
        if m_email_sub:
            try:
                b_url = urllib.parse.urljoin(final_url, m_email_sub.group(1))
                b_resp = self.session.get(b_url, timeout=4)
                if b_resp.status_code == 200 and b_resp.text:
                    sub_html = b_resp.text
                    # Look for setApplication(1, "mailto:...")
                    for m_js in re.findall(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', sub_html, re.I):
                        e_low = m_js.strip().lower()
                        ok_e, _ = is_email_compatible_with_employer(e_low, company)
                        if ok_e and e_low not in valid_emails:
                            valid_emails.insert(0, e_low)
                            email_source_section = "azubiyo_bewerben_email_endpoint"
                    for cf_e in self._decode_cf_emails(sub_html):
                        ok_e, _ = is_email_compatible_with_employer(cf_e, company)
                        if ok_e and cf_e not in valid_emails:
                            valid_emails.insert(0, cf_e)
                            email_source_section = "azubiyo_bewerben_email_cf"
            except Exception as exc:
                logger.debug("Azubiyo bewerben-email fetch error: %s", exc)

        # 2. If no email, check /bewerben/ subpage OR inline JS on main page for external employer application URL
        if not valid_emails:
            # First check inline validateAndTrackAndOpen / setApplication on main page HTML
            inline_js_urls = re.findall(
                r'(?:validateAndTrackAndOpen|setApplication)\s*\(\s*\d+\s*,\s*[\'"](https?://[^\'"]+)[\'"]',
                html,
                re.I,
            )
            for ju in inline_js_urls:
                ju_clean = ju.strip()
                if "azubiyo.de" not in ju_clean.lower():
                    external_apply_url = self._resolve_shortener_url(ju_clean)
                    form_source_section = "azubiyo_inline_js_target"
                    break

            m_apply_sub = re.search(r'href=[\'"](/stellenanzeigen/[^\'"]+/bewerben/?)[\'"]', html, re.I)
            if not external_apply_url and m_apply_sub:
                try:
                    a_url = urllib.parse.urljoin(final_url, m_apply_sub.group(1))
                    a_resp = self.session.get(a_url, timeout=4, allow_redirects=True)
                    if a_resp.status_code == 200 and a_resp.text:
                        a_html = a_resp.text
                        # Check if redirected off azubiyo.de directly
                        if a_resp.url and "azubiyo.de" not in a_resp.url.lower():
                            external_apply_url = a_resp.url
                            form_source_section = "azubiyo_bewerben_redirect"
                        else:
                            # Look for validateAndTrackAndOpen(1, "https://...") or setApplication(2, "https://...", false)
                            js_urls = re.findall(
                                r'(?:validateAndTrackAndOpen|setApplication)\s*\(\s*\d+\s*,\s*[\'"](https?://[^\'"]+)[\'"]',
                                a_html,
                                re.I,
                            )
                            for ju in js_urls:
                                ju_clean = ju.strip()
                                if "azubiyo.de" not in ju_clean.lower():
                                    external_apply_url = self._resolve_shortener_url(ju_clean)
                                    form_source_section = "azubiyo_bewerben_js_target"
                                    break
                except Exception as exc:
                    logger.debug("Azubiyo bewerben subpage fetch error: %s", exc)

        # 3. Also check scoped links on the main Azubiyo listing if no external_apply_url yet
        if not valid_emails and not external_apply_url:
            scoped_links = ApplicationFormDiscovery.extract_application_links_from_html(str(soup), final_url)
            for sl in scoped_links:
                if "azubiyo.de" not in sl.lower():
                    external_apply_url = self._resolve_shortener_url(sl)
                    form_source_section = "azubiyo_scoped_apply_button"
                    break

        norm = dict(job)
        norm["job_listing_url"] = final_url
        norm["apply_url"] = final_url
        if valid_phones:
            norm["phone"] = valid_phones[0]
        if contact_person:
            norm["contact_person"] = contact_person
            norm["arbeitsgeber"] = contact_person

        if valid_emails:
            norm["email"] = valid_emails[0]
            norm["email_extracted"] = True
            norm["email_type"] = "recruitment"
            norm["has_form"] = False
            norm["form_link"] = ""
            norm["direct_application_url"] = ""
            norm["bewerbung_link"] = final_url
            norm["application_method"] = "email"
            norm["extraction_method"] = "fast_http"
            attach_contact_provenance(
                norm,
                source_url=final_url,
                section=email_source_section,
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            self.job_cache.put(final_url, norm, company=company)
            return norm

        if external_apply_url:
            norm["email"] = ""
            norm["email_extracted"] = False
            norm["has_form"] = True
            norm["form_link"] = external_apply_url
            norm["direct_application_url"] = external_apply_url
            norm["bewerbung_link"] = external_apply_url
            norm["application_method"] = "form"
            norm["application_url_type"] = "direct_form"
            norm["extraction_method"] = "fast_http"
            attach_contact_provenance(
                norm,
                source_url=final_url,
                section=form_source_section,
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            self.job_cache.put(final_url, norm, company=company)
            self.employer_cache.put(company=company, city=city, url_or_domain=external_apply_url, data=norm)
            return norm

        # Check for Per Post or internal Azubiyo portal application only
        scoped_text_low = soup.get_text(" ", strip=True).lower()
        if "per post" in scoped_text_low and "online bewerben" not in scoped_text_low:
            norm["postal_only"] = True
            norm["application_method"] = "postal"
            norm["extraction_method"] = "fast_http"
            attach_contact_provenance(
                norm,
                source_url=final_url,
                section="azubiyo_postal_only",
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            self.job_cache.put(final_url, norm, company=company)
            return norm

        if "/bewerben/" in html or "über azubiyo" in scoped_text_low or "jetzt bewerben" in scoped_text_low:
            norm["portal_login_required"] = True
            norm["application_method"] = "portal_login_required"
            norm["extraction_method"] = "fast_http"
            attach_contact_provenance(
                norm,
                source_url=final_url,
                section="azubiyo_internal_portal",
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            self.job_cache.put(final_url, norm, company=company)
            return norm

        return None

    def _extract_aubi_plus_fast(self, job: Dict, html: str, final_url: str) -> Optional[Dict]:
        """
        Dedicated AUBI-plus detail extractor:
        1. Strips footer/header noise (bewerbung2go.de, empty mailto:?body=... share links).
        2. Resolves short.sg external apply URLs per job to the real employer ATS destination.
        3. Extracts scoped phone and contact person from the current job listing only.
        """
        company = str(job.get("company") or job.get("firma") or "").strip()
        city = str(job.get("city") or job.get("location") or "").strip()

        valid_emails, valid_phones, contact_person, soup = self._extract_scoped_dom_contacts(html, company=company)
        external_apply_url = ""
        form_section = ""

        # Look for short.sg or external apply button in scoped DOM
        for a_tag in soup.find_all("a", href=True):
            href = (a_tag.get("href") or "").strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full_href = urllib.parse.urljoin(final_url, href)
            if "bewerbung2go.de" in full_href.lower():
                continue
            text_low = (a_tag.get_text(" ", strip=True) or "").lower()
            if is_shortener_domain(full_href) or any(
                kw in text_low for kw in ("online-bewerbung", "jetzt bewerben", "online bewerben", "zur bewerbung")
            ):
                if "aubi-plus.de" not in full_href.lower() or "/bewerbung/" in full_href.lower():
                    external_apply_url = self._resolve_shortener_url(full_href)
                    form_section = "aubi_plus_apply_button"
                    break

        if not external_apply_url:
            # Regex fallback for short.sg links in HTML
            short_m = re.search(r'https?://short\.sg/[A-Za-z0-9/_-]+', str(soup), re.I)
            if short_m:
                external_apply_url = self._resolve_shortener_url(short_m.group(0))
                form_section = "aubi_plus_short_sg_resolved"

        if not valid_emails and not external_apply_url and not valid_phones:
            return None

        norm = dict(job)
        norm["job_listing_url"] = final_url
        norm["apply_url"] = final_url
        if valid_phones:
            norm["phone"] = valid_phones[0]
        if contact_person:
            norm["contact_person"] = contact_person
            norm["arbeitsgeber"] = contact_person

        if valid_emails:
            norm["email"] = valid_emails[0]
            norm["email_extracted"] = True
            norm["email_type"] = "recruitment"
            norm["has_form"] = False
            norm["form_link"] = ""
            norm["direct_application_url"] = ""
            norm["bewerbung_link"] = final_url
            norm["application_method"] = "email"
            norm["extraction_method"] = "fast_http"
            attach_contact_provenance(
                norm,
                source_url=final_url,
                section="aubi_plus_job_detail_email",
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            self.job_cache.put(final_url, norm, company=company)
            return norm

        if external_apply_url:
            norm["email"] = ""
            norm["email_extracted"] = False
            norm["has_form"] = True
            norm["form_link"] = external_apply_url
            norm["direct_application_url"] = external_apply_url
            norm["bewerbung_link"] = external_apply_url
            norm["application_method"] = "form"
            norm["application_url_type"] = "direct_form"
            norm["extraction_method"] = "fast_http"
            attach_contact_provenance(
                norm,
                source_url=final_url,
                section=form_section,
                extraction_method="fast_http",
                verified=True,
            )
            norm = normalize_job_opportunity_row(norm)
            self.job_cache.put(final_url, norm, company=company)
            self.employer_cache.put(company=company, city=city, url_or_domain=external_apply_url, data=norm)
            return norm

        return None

    def extract_via_fast_http(self, job: Dict) -> Optional[Dict]:
        """
        Rapid HTTP-first extraction in ~150ms.
        Bypasses Selenium completely when valid contact info is discovered in raw HTML or cache.
        """
        company = str(job.get("company") or job.get("firma") or "").strip()
        city = str(job.get("city") or job.get("location") or "").strip()
        source_url = str(job.get("apply_url") or job.get("url") or "").strip()

        # 0a. Tier 1 Job-Specific Cache lookup (exact canonical job URL + company match)
        job_cached = self.job_cache.get(source_url, company=company)
        if job_cached and (job_cached.get("email") or job_cached.get("has_form") or job_cached.get("direct_application_url")):
            cached_res = dict(job)
            for k, v in job_cached.items():
                if v and not cached_res.get(k):
                    cached_res[k] = v
            cached_res["extraction_method"] = "cache"
            return normalize_job_opportunity_row(cached_res)

        # 0b. Tier 2 Verified Employer Cache lookup (only short-circuits before page fetch
        # if explicitly populated or if source_url is an employer's own domain, NEVER a portal domain)
        cached = self.employer_cache.get(
            company=company,
            city=city,
            url_or_domain=source_url,
            require_explicit_or_non_portal=True,
        )
        if cached and (cached.get("email") or cached.get("has_form") or cached.get("direct_application_url")):
            cached_res = dict(job)
            for k, v in cached.items():
                if v and not cached_res.get(k):
                    cached_res[k] = v
            cached_res["extraction_method"] = "cache"
            attach_contact_provenance(
                cached_res,
                source_url=source_url,
                section="verified_employer_cache",
                extraction_method="cache",
                verified=True,
            )
            return normalize_job_opportunity_row(cached_res)

        if not source_url or not source_url.startswith("http"):
            return None

        # 1. For Arbeitsagentur, run high-speed Stage 1 & 2
        source = str(job.get("source") or "").lower()
        if "arbeitsagentur" in source or "arbeitsagentur.de" in source_url:
            try:
                res = self.aa_extractor.extract_vacancy(job, driver=None, captcha_solver=self.captcha_solver)
                res["extraction_method"] = "fast_http"
                if res.get("email") or res.get("has_form") or res.get("direct_application_url"):
                    self.job_cache.put(source_url, res, company=company)
                    emp_site = str(res.get("employer_website") or "").strip()
                    self.employer_cache.put(company=company, city=city, url_or_domain=emp_site, data=res)
                    return res
            except Exception as exc:
                logger.debug("Fast HTTP aa_extractor error for %s: %s", source_url, exc)

        # 1b. For Ausbildung.de, run high-speed Stage 1 & 2
        if "ausbildung.de" in source or "ausbildung.de" in source_url:
            try:
                res = self.ausbildung_extractor.extract_vacancy(job, driver=None, session=self.session, worker_id=self.worker_id)
                if res and (res.get("email") or res.get("has_form") or res.get("direct_application_url")):
                    self.job_cache.put(source_url, res, company=company)
                    emp_site = str(res.get("employer_website") or "").strip()
                    self.employer_cache.put(company=company, city=city, url_or_domain=emp_site, data=res)
                    return res
            except Exception as exc:
                logger.debug("Fast HTTP ausbildung_extractor error for %s: %s", source_url, exc)

        # 2. Generic portals fast HTTP fetch (Azubiyo, AUBI-plus, IHK, or direct employer URL)
        try:
            resp = self.session.get(source_url, timeout=6, allow_redirects=True)
            if resp.status_code == 200 and resp.text:
                html = resp.text
                final_url = resp.url or source_url
                if any(ind in html.lower() for ind in ["sicherheitsabfrage", "security check", "cf-chl-bypass"]):
                    return None

                # Redirected to Arbeitsagentur detail page (e.g. from IHK klick_zaehler.cfm)?
                if "arbeitsagentur.de/jobsuche/jobdetail" in final_url:
                    try:
                        aa_job = dict(job)
                        aa_job["url"] = final_url
                        res = self.aa_extractor.extract_vacancy(aa_job, driver=None, captcha_solver=self.captcha_solver)
                        res["extraction_method"] = "fast_http"
                        if res.get("email") or res.get("has_form") or res.get("direct_application_url"):
                            self.job_cache.put(source_url, res, company=company)
                            return res
                    except Exception:
                        pass

                # Redirected to Ausbildung.de detail page (e.g. from IHK)?
                if "ausbildung.de/stellen/" in final_url:
                    try:
                        aus_job = dict(job)
                        aus_job["url"] = final_url
                        res = self.ausbildung_extractor.extract_vacancy(aus_job, driver=None, session=self.session, worker_id=self.worker_id)
                        if res and (res.get("email") or res.get("has_form") or res.get("direct_application_url")):
                            self.job_cache.put(source_url, res, company=company)
                            return res
                    except Exception:
                        pass

                # Safe meta-refresh redirect detection (e.g., partner/ATS redirect)
                meta_match = re.search(r'<meta[^>]*http-equiv=["\']?refresh["\']?[^>]*content=["\']?[^"\'>]*url=([^"\'\s;>]+)', html, re.IGNORECASE)
                if meta_match:
                    raw_target = meta_match.group(1).strip(" '\"")
                    resolved_target = urllib.parse.urljoin(final_url, raw_target)
                    parsed_target = urllib.parse.urlparse(resolved_target)
                    if parsed_target.scheme in ("http", "https") and parsed_target.netloc:
                        try:
                            redir_resp = self.session.get(resolved_target, timeout=5, allow_redirects=True)
                            if redir_resp.status_code == 200 and redir_resp.text:
                                html = redir_resp.text
                                final_url = redir_resp.url
                        except Exception as redir_err:
                            logger.debug("Fast HTTP meta-refresh error for %s -> %s: %s", final_url, resolved_target, redir_err)

                # 2a. Dedicated Azubiyo extraction
                if "azubiyo.de" in final_url.lower():
                    az_res = self._extract_azubiyo_fast(job, html, final_url)
                    if az_res is not None:
                        return az_res

                # 2b. Dedicated AUBI-plus extraction
                if "aubi-plus.de" in final_url.lower():
                    aubi_res = self._extract_aubi_plus_fast(job, html, final_url)
                    if aubi_res is not None:
                        return aubi_res

                # 2c. Scoped DOM extraction for IHK / external employer destination pages
                clean_emails, phones, contact_person, scoped_soup = self._extract_scoped_dom_contacts(html, company=company)

                # Check if destination is a known ATS, external IHK redirect target, or contains a verifiable application form
                is_ats = ApplicationFormDiscovery.is_known_ats_url(final_url)
                has_form, form_type, _ = ApplicationFormDiscovery.verify_form_page(html, final_url)
                discovered_form_url = final_url if (has_form or is_ats) else ""

                # If IHK redirected off-portal to an external employer/ATS page, also check for explicit apply links on that page
                is_ihk_external_redirect = (
                    ("meine-ausbildung-in-deutschland.de" in source_url.lower() or "ihk" in source)
                    and not is_portal_domain(final_url)
                )
                if not discovered_form_url and not clean_emails:
                    ext_links = ApplicationFormDiscovery.extract_application_links_from_html(str(scoped_soup), final_url)
                    for elink in ext_links:
                        resolved_elink = self._resolve_shortener_url(elink)
                        if ApplicationFormDiscovery.is_known_ats_url(resolved_elink) or any(
                            k in resolved_elink.lower() for k in ("/apply", "/bewerb", "formular", "talentcommunity", "karriere", "jobs")
                        ):
                            discovered_form_url = resolved_elink
                            has_form = True
                            break
                    if not discovered_form_url and is_ihk_external_redirect:
                        # The IHK klick_zaehler redirect target IS the employer's external application/vacancy page
                        discovered_form_url = final_url
                        has_form = True

                if clean_emails or has_form or is_ats or discovered_form_url:
                    norm = dict(job)
                    if clean_emails:
                        norm["email"] = clean_emails[0]
                        norm["email_extracted"] = True
                        norm["email_type"] = "recruitment"
                    if phones:
                        norm["phone"] = phones[0]
                    if contact_person:
                        norm["contact_person"] = contact_person
                        norm["arbeitsgeber"] = contact_person
                    if (has_form or is_ats or discovered_form_url) and not clean_emails:
                        target_f = discovered_form_url or final_url
                        norm["has_form"] = True
                        norm["form_link"] = target_f
                        norm["direct_application_url"] = target_f
                        norm["bewerbung_link"] = target_f
                        norm["application_method"] = "form"
                        norm["application_url_type"] = "direct_form"
                    elif (has_form or is_ats or discovered_form_url) and clean_emails:
                        target_f = discovered_form_url or final_url
                        norm["has_form"] = True
                        norm["form_link"] = target_f
                        norm["direct_application_url"] = target_f
                        norm["bewerbung_link"] = target_f
                        norm["application_method"] = "both"
                        norm["application_url_type"] = "direct_form"
                    norm["extraction_method"] = "fast_http"
                    attach_contact_provenance(
                        norm,
                        source_url=final_url,
                        section="ihk_redirect_destination" if is_ihk_external_redirect else "generic_fast_http_scoped",
                        extraction_method="fast_http",
                        verified=True,
                    )
                    norm = normalize_job_opportunity_row(norm)
                    self.job_cache.put(source_url, norm, company=company)
                    if not is_non_employer_domain(final_url):
                        self.employer_cache.put(company=company, city=city, url_or_domain=final_url, data=norm)
                    return norm
        except Exception as http_err:
            logger.debug("Fast HTTP generic error for %s: %s", source_url, http_err)

        return None

    def open_job(self, job: Dict, delay_seconds: float = 1.0) -> None:
        url = job.get("url", "")
        if url and getattr(self, "driver", None):
            # Close stray secondary windows/popups to reclaim browser RAM immediately
            try:
                handles = self.driver.window_handles
                if len(handles) > 1:
                    for h in handles[1:]:
                        self.driver.switch_to.window(h)
                        self.driver.close()
                    self.driver.switch_to.window(handles[0])
            except Exception:
                pass

            try:
                self.driver.get(url)
            except Exception as get_err:
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                logger.debug("WebDriver get() timed out or stopped: %s", get_err)

            self.accept_cookies()
            # Smart wait: poll for content/email up to max 1.0s instead of hard sleep
            t0 = time.time()
            max_wait = min(delay_seconds, 1.0)
            while time.time() - t0 < max_wait:
                try:
                    body = self.driver.find_element(By.TAG_NAME, "body").text
                    if "@" in body or "bewerb" in body.lower():
                        break
                except Exception:
                    pass
                time.sleep(0.1)
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
        job = dict(job or {})
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
                    manual_captcha_handler=self._request_manual_captcha_review,
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
        # 3. Ausbildung.de Vacancies (Dedicated 5-Step Pipeline)
        # ----------------------------------------------------------------------
        is_ausbildung_de = (
            "ausbildung.de" in source
            or "ausbildung.de" in str(job.get("url") or "").lower()
        )
        if is_ausbildung_de:
            # 1. Fast HTTP first
            if on_stage_change:
                on_stage_change("HTTP Fast-Path")
            fast_res = self.extract_via_fast_http(job)
            if fast_res is not None and (fast_res.get("email") or fast_res.get("has_form") or fast_res.get("direct_application_url")):
                if on_stage_change:
                    on_stage_change("Email Extraction" if fast_res.get("email") else "Finding Application Form")
                norm_email = self._normalize_email(fast_res.get("email"))
                if norm_email and "@" in norm_email:
                    with self._stats_lock:
                        if norm_email not in self.known_emails:
                            self.stats["emails_found"] += 1
                            self.known_emails.add(norm_email)
                with self._stats_lock:
                    self.stats["processed"] += 1
                    self.stats["fast_path_hits"] += 1
                return fast_res

            # 2. Interactive Selenium fallback for Ausbildung.de
            try:
                with self._stats_lock:
                    self.stats["selenium_fallbacks"] += 1
                if on_stage_change:
                    on_stage_change("Selenium Fallback")
                self.recycle_driver_if_needed()
                with self.selenium_lock:
                    enriched = self.ausbildung_extractor.extract_vacancy(
                        job,
                        driver=getattr(self, "driver", None),
                        session=self.session,
                        on_stage_change=on_stage_change,
                        worker_id=self.worker_id,
                    )
                with self._stats_lock:
                    self.stats["processed"] += 1
                norm_email = self._normalize_email(enriched.get("email"))
                if norm_email and "@" in norm_email:
                    if on_stage_change:
                        on_stage_change("Email Extraction")
                    with self._stats_lock:
                        if norm_email not in self.known_emails:
                            self.stats["emails_found"] += 1
                            self.known_emails.add(norm_email)
                return enriched
            except Exception as aus_err:
                logger.error("[AusbildungDe] Error in extraction: %s", aus_err)

        # ----------------------------------------------------------------------
        # 4. Generic Job Portals (Azubiyo, AUBI-plus, IHK)
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
                attach_contact_provenance(
                    job,
                    source_url=job_listing_url,
                    section="selenium_dom_extraction",
                    extraction_method="selenium",
                    verified=True,
                )
                job = normalize_job_opportunity_row(job, discovery_result=None)
            else:
                # If no email exists, inspect original job ad & company website for application form
                if on_stage_change:
                    on_stage_change("Finding Application Form")
                discovery = self.form_discovery.discover_application_form(
                    job,
                    driver=getattr(self, "driver", None),
                )
                attach_contact_provenance(
                    job,
                    source_url=job_listing_url,
                    section="selenium_form_discovery",
                    extraction_method="selenium",
                    verified=True,
                )
                job = normalize_job_opportunity_row(job, discovery_result=discovery)

            # Store discovered contact info in Tier 1 job cache and Tier 2 verified employer cache
            comp_name = str(job.get("company") or job.get("firma") or "")
            city_name = str(job.get("city") or job.get("location") or "")
            if job.get("email") or job.get("has_form") or job.get("direct_application_url"):
                self.job_cache.put(job_listing_url, job, company=comp_name)
                emp_site = str(job.get("employer_website") or "").strip()
                if emp_site and not is_non_employer_domain(emp_site):
                    self.employer_cache.put(
                        company=comp_name,
                        city=city_name,
                        url_or_domain=emp_site,
                        data=job,
                    )

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
        from services.debounced_writer import get_debounced_writer
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
        # Debounce progress writes to eliminate disk thrashing; force immediate flush if complete
        is_finished = (index >= len(jobs) - 1)
        writer = get_debounced_writer(json_path, min_interval_seconds=1.5)
        writer.schedule_write(payload, immediate=is_finished)

        # Also save job-specific checkpoint file if job_id is available
        w_job_id = getattr(self, "job_id", "")
        if w_job_id:
            specific_json = PROGRESS_DIR / f"{base_name}_{w_job_id}.json"
            spec_writer = get_debounced_writer(specific_json, min_interval_seconds=1.5)
            spec_writer.schedule_write(payload, immediate=is_finished)

        if is_finished and index >= 0 and jobs[: index + 1]:
            try:
                pd.DataFrame(jobs[: index + 1]).to_csv(csv_path, index=False, encoding="utf-8")
            except Exception:
                pass

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
        # Clean up temporary worker profile directory
        if self._worker_profile_dir and self._worker_profile_dir.exists():
            try:
                shutil.rmtree(self._worker_profile_dir, ignore_errors=True)
            except Exception:
                pass
