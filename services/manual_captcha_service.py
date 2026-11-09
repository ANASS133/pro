"""
Manual CAPTCHA Review Service for JobScout.

Coordinates human verification when workers encounter CAPTCHAs or bot challenges:
1. Captures challenge state (platform, job, worker ID, source URL, challenge type, base64 image).
2. Manages thread-safe synchronization between background workers and user actions.
3. Submits manual code through legitimate website form inputs and submit buttons.
4. Supports interactive challenge verification in browser sessions.
5. Guarantees other workers continue processing uninterrupted.
6. Verifies website unblocking before confirming success.
"""

import base64
import binascii
import io
import logging
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CHALLENGE_TYPES = {"image_text", "recaptcha", "turnstile", "login_required", "unknown"}


def validate_captcha_image(data_uri: str) -> Tuple[bool, str]:
    """Validate that a payload is an actual raster image, not a blank placeholder or page screenshot marker."""
    if not data_uri:
        return False, "CAPTCHA image is missing."
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/") or ";base64," not in data_uri:
        return False, "CAPTCHA image payload is invalid."
    mime, encoded = data_uri.split(",", 1)
    if not any(kind in mime.lower() for kind in ("image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp")):
        return False, "Unsupported CAPTCHA image format."
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False, "CAPTCHA image data is corrupt."
    if len(raw) < 64:
        return False, "CAPTCHA image is empty or incomplete."
    signatures = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"RIFF")
    if not raw.startswith(signatures):
        return False, "CAPTCHA payload is not a recognized image."
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.width < 20 or image.height < 10:
                return False, "CAPTCHA image dimensions are too small."
            extrema = image.convert("L").getextrema()
            if extrema[0] == extrema[1]:
                return False, "CAPTCHA image is blank."
    except ImportError:
        pass
    except Exception:
        return False, "CAPTCHA image cannot be decoded."
    return True, ""


def capture_loaded_captcha(driver, element, timeout=5.0):
    """Capture only a loaded image in this browser; validate each fallback."""
    from selenium.webdriver.support.ui import WebDriverWait
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.execute_script(
            "return arguments[0].complete === true && arguments[0].naturalWidth > 0 && arguments[0].naturalHeight > 0;",
            element,
        ) is True)
    except Exception:
        return "", "CAPTCHA image did not load in the worker browser. Restart workers created with image blocking enabled."

    # Put the element in a deterministic desktop layout before reading its source
    # or rasterizing it. Require two consecutive identical rectangles so a lazy
    # image, sticky header, or responsive reflow cannot move it mid-capture.
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            element,
        )
        previous_rect = [None]
        stable_reads = [0]

        def same_rectangle(first, second):
            if not isinstance(first, (list, tuple)) or not isinstance(second, (list, tuple)):
                return first == second
            if len(first) != len(second):
                return False
            try:
                return all(abs(float(a) - float(b)) <= 0.25 for a, b in zip(first, second))
            except (TypeError, ValueError):
                return first == second

        def layout_is_stable(active_driver):
            rect = active_driver.execute_script("""
                const r = arguments[0].getBoundingClientRect();
                return [r.left, r.top, r.width, r.height];
            """, element)
            if same_rectangle(rect, previous_rect[0]):
                stable_reads[0] += 1
            else:
                previous_rect[0] = rect
                stable_reads[0] = 1
            return stable_reads[0] >= 2

        WebDriverWait(driver, timeout, poll_frequency=0.05).until(layout_is_stable)
    except Exception:
        return "", "CAPTCHA image layout did not stabilize before capture."

    error = "CAPTCHA image capture failed."

    # Strategy 1 & 2: If element has a valid src URL, capture the original unclipped raster image
    src = None
    try:
        raw_src = element.get_attribute("src")
        if isinstance(raw_src, str) and raw_src.strip():
            src = raw_src.strip()
    except Exception:
        pass

    if src:
        # 1. Direct data URI
        if src.startswith("data:image/"):
            valid, _ = validate_captcha_image(src)
            if valid:
                return src, ""

        # 2. In-browser async fetch (exact pixels, zero clipping, session authenticated)
        if src.startswith("http") and hasattr(driver, "execute_async_script"):
            try:
                b64_uri = driver.execute_async_script("""
                    const done = arguments[arguments.length - 1];
                    const url = arguments[0];
                    fetch(url, {credentials: 'include'})
                        .then(r => {
                            if (!r.ok) throw new Error('HTTP ' + r.status);
                            return r.blob();
                        })
                        .then(blob => {
                            const reader = new FileReader();
                            reader.onloadend = () => done(reader.result);
                            reader.readAsDataURL(blob);
                        })
                        .catch(e => done(null));
                """, src)
                if isinstance(b64_uri, str) and b64_uri.startswith("data:image/"):
                    valid, _ = validate_captcha_image(b64_uri)
                    if valid:
                        return b64_uri, ""
            except Exception:
                pass

        # 3. Direct HTTP GET using driver session cookies and headers
        if src.startswith("http"):
            try:
                import requests
                cookies = {}
                try:
                    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
                except Exception:
                    pass
                user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                try:
                    user_agent = driver.execute_script("return navigator.userAgent;") or user_agent
                except Exception:
                    pass
                current_url = getattr(driver, "current_url", "") or ""
                headers = {
                    "User-Agent": user_agent,
                    "Referer": current_url,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                }
                resp = requests.get(src, cookies=cookies, headers=headers, timeout=5)
                if resp.status_code == 200 and resp.content:
                    mime = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
                    if not mime.startswith("image/"):
                        mime = "image/png"
                    candidate = f"data:{mime};base64," + base64.b64encode(resp.content).decode("ascii")
                    valid, _ = validate_captcha_image(candidate)
                    if valid:
                        return candidate, ""
            except Exception:
                pass

    # Selenium element screenshots are browser-native raster captures and avoid
    # canvas tainting/CORS failures. Try both exposed element screenshot forms.
    for capture in (
        lambda: "data:image/png;base64," + element.screenshot_as_base64,
        lambda: "data:image/png;base64," + base64.b64encode(element.screenshot_as_png).decode("ascii"),
    ):
        try:
            candidate = capture()
            valid, error = validate_captcha_image(candidate)
            if valid:
                return candidate, ""
        except Exception:
            continue
    return "", error


@dataclass
class ManualCaptchaChallenge:
    challenge_id: str
    job_id: str
    search_run_id: str
    job_index: int
    worker_id: int
    platform: str
    job_title: str
    employer: str
    source_url: str
    challenge_type: str  # image_text | recaptcha | turnstile | login_required | unknown
    captcha_image_base64: str  # data:image/png;base64,...
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: str = field(default_factory=lambda: (datetime.now() + timedelta(minutes=10)).isoformat())
    status: str = "pending"  # "pending", "solved", "failed", "expired", "dismissed"
    attempts: int = 0
    max_attempts: int = 5
    last_error: str = ""
    image_valid: bool = False
    image_error: str = ""
    recognized_code: str = ""
    resolved_at: Optional[str] = None
    
    # Internal sync hooks (not serialized to json)
    completion_event: threading.Event = field(default_factory=threading.Event, repr=False)
    submit_handler: Optional[Callable[[str], Tuple[bool, str]]] = field(default=None, repr=False)
    verify_interactive_handler: Optional[Callable[[], Tuple[bool, str]]] = field(default=None, repr=False)
    driver_ref: Optional[Any] = field(default=None, repr=False)

    def is_expired(self) -> bool:
        if self.status != "pending":
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.now() > exp
        except Exception:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "job_id": self.job_id,
            "search_run_id": self.search_run_id,
            "job_index": self.job_index,
            "worker_id": self.worker_id,
            "platform": self.platform,
            "job_title": self.job_title,
            "employer": self.employer,
            "source_url": self.source_url,
            "challenge_type": self.challenge_type,
            "captcha_image_base64": self.captcha_image_base64,
            "image_valid": self.image_valid,
            "image_error": self.image_error,
            "recognized_code": getattr(self, "recognized_code", "") or "",
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": "expired" if self.is_expired() else self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "last_error": self.last_error,
            "can_retry": self.attempts < self.max_attempts and self.status in ("pending", "failed"),
            "resolved_at": self.resolved_at,
        }

    def wait_for_resolution(self, timeout: float = 300.0) -> str:
        """Called by the worker thread to wait for human review."""
        start = time.time()
        while time.time() - start < timeout:
            if self.completion_event.wait(timeout=1.0):
                return self.status
            if self.is_expired():
                self.status = "expired"
                return "expired"
        self.status = "expired"
        return "expired"

    def refresh_image(self) -> str:
        """Attempts to re-capture or extract a higher quality captcha image from live driver."""
        if not self.driver_ref:
            return self.captcha_image_base64
        try:
            from selenium.webdriver.common.by import By
            selectors = [
                "//*[@id='kontaktdaten-captcha-image']",
                "//div[contains(@class,'captcha-container-image')]//img",
                "//img[contains(@src, 'captcha')]",
                "//img[contains(@alt, 'captcha')]",
                "//img[contains(@id, 'captcha')]",
                "//img[contains(@class, 'captcha')]",
                "//div[contains(@class, 'captcha')]//img",
            ]
            def find_image_element():
                for sel in selectors:
                    try:
                        els = self.driver_ref.find_elements(By.XPATH, sel)
                        for candidate in els:
                            try:
                                size = candidate.size
                                if size and (size.get("width", 0) < 30 or size.get("height", 0) < 10):
                                    continue
                            except Exception:
                                pass
                            return candidate
                    except Exception:
                        continue
                return None

            img_el = find_image_element()
            old_src = ""
            if img_el is not None:
                try:
                    old_src = str(img_el.get_attribute("src") or "")
                except Exception:
                    old_src = ""

            # Ask the authenticated Arbeitsagentur session for a fresh image;
            # wait for its source identity to change instead of guessing a delay.
            reload_buttons = self.driver_ref.find_elements(By.CSS_SELECTOR, "#kontaktdaten-captcha-reload-button")
            if reload_buttons:
                from selenium.common.exceptions import TimeoutException
                from selenium.webdriver.support.ui import WebDriverWait

                try:
                    reload_buttons[0].click()
                except Exception as exc:
                    self.captcha_image_base64 = ""
                    self.image_valid = False
                    self.image_error = f"CAPTCHA reload request failed: {exc}"
                    return ""

                def refreshed_element(_driver):
                    candidate = find_image_element()
                    if candidate is None:
                        return False
                    try:
                        new_src = str(candidate.get_attribute("src") or "")
                    except Exception:
                        return False
                    return candidate if new_src and new_src != old_src else False

                try:
                    img_el = WebDriverWait(self.driver_ref, 5.0, poll_frequency=0.05).until(refreshed_element)
                except TimeoutException:
                    self.captcha_image_base64 = ""
                    self.image_valid = False
                    self.image_error = "CAPTCHA image source did not change before the refresh timeout."
                    return ""

            if img_el is not None:
                try:
                    self.driver_ref.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", img_el)
                except Exception:
                    pass
                new_b64, error = capture_loaded_captcha(self.driver_ref, img_el)
            else:
                new_b64, error = "", "CAPTCHA image element is missing."
            self.captcha_image_base64 = new_b64
            self.image_valid = bool(new_b64)
            self.image_error = error
        except Exception as exc:
            logger.debug("[ManualCaptcha] Failed refreshing image for challenge %s: %s", self.challenge_id, exc)

        return self.captcha_image_base64


class ManualCaptchaManager:
    """Thread-safe manager for manual CAPTCHA review challenges."""

    def __init__(self):
        self._lock = threading.Lock()
        self._challenges: Dict[str, ManualCaptchaChallenge] = {}

    def create_challenge(
        self,
        job_id: str,
        search_run_id: str,
        job_index: int,
        worker_id: int,
        platform: str,
        job_title: str,
        employer: str,
        source_url: str,
        challenge_type: str,
        captcha_image_base64: str,
        submit_handler: Optional[Callable[[str], Tuple[bool, str]]] = None,
        verify_interactive_handler: Optional[Callable[[], Tuple[bool, str]]] = None,
        driver_ref: Optional[Any] = None,
        timeout_seconds: float = 600.0,
    ) -> ManualCaptchaChallenge:
        with self._lock:
            ch_id = f"mch_{job_id[:8]}_{int(time.time()*1000)%100000}_w{worker_id}"
            exp_time = (datetime.now() + timedelta(seconds=timeout_seconds)).isoformat()
            challenge = ManualCaptchaChallenge(
                challenge_id=ch_id,
                job_id=job_id,
                search_run_id=search_run_id,
                job_index=job_index,
                worker_id=worker_id,
                platform=platform or "Unknown",
                job_title=job_title or "Apprenticeship Position",
                employer=employer or "Employer",
                source_url=source_url or "",
                challenge_type=challenge_type if challenge_type in CHALLENGE_TYPES else "unknown",
                captcha_image_base64=captcha_image_base64 or "",
                expires_at=exp_time,
                submit_handler=submit_handler,
                verify_interactive_handler=verify_interactive_handler,
                driver_ref=driver_ref,
            )
            challenge.image_valid, challenge.image_error = validate_captcha_image(challenge.captcha_image_base64)
            if not challenge.image_valid:
                challenge.captcha_image_base64 = ""
            self._challenges[ch_id] = challenge
            logger.info(
                "[ManualCaptcha] Created %s challenge %s for Job %s on Worker %s (%s)",
                challenge_type, ch_id, job_id[:8], worker_id, platform
            )
            return challenge

    def get_challenge(self, challenge_id: str) -> Optional[ManualCaptchaChallenge]:
        with self._lock:
            ch = self._challenges.get(challenge_id)
            if ch and ch.is_expired():
                ch.status = "expired"
            return ch

    def get_challenges_for_job(self, job_id: str, active_only: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            results = []
            for ch in self._challenges.values():
                if ch.job_id == job_id:
                    if ch.is_expired():
                        ch.status = "expired"
                    if active_only and ch.status not in ("pending", "failed", "expired"):
                        continue
                    results.append(ch.to_dict())
            return sorted(results, key=lambda x: x["created_at"], reverse=True)

    def submit_solution(self, challenge_id: str, solution_text: str) -> Tuple[bool, str]:
        """
        Submits human-entered solution text to the website through the worker's active session.
        Returns (success, message).
        """
        ch = self.get_challenge(challenge_id)
        if not ch:
            return False, "Challenge not found."
        if ch.status == "solved":
            return True, "Challenge already solved."
        if ch.challenge_type != "image_text" or not ch.image_valid:
            return False, ch.image_error or "This challenge does not accept a text code."
        if ch.is_expired():
            ch.status = "expired"
            ch.completion_event.set()
            return False, "Challenge has expired."

        ch.attempts += 1
        clean_code = (solution_text or "").strip()
        if not clean_code:
            ch.last_error = "Please enter the CAPTCHA code."
            return False, ch.last_error

        if not ch.submit_handler:
            ch.last_error = "No active submission handler available for this session."
            return False, ch.last_error

        try:
            success, msg = ch.submit_handler(clean_code)
            if success:
                ch.status = "solved"
                ch.resolved_at = datetime.now().isoformat()
                ch.last_error = ""
                ch.completion_event.set()
                logger.info("[ManualCaptcha] Challenge %s verified successfully!", challenge_id)
                return True, msg or "Verification successful."
            else:
                ch.status = "failed" if ch.attempts >= ch.max_attempts else "pending"
                ch.last_error = msg or "Verification failed. Target website rejected the code."
                # Most image CAPTCHA providers rotate the challenge after a
                # rejected answer.  Refresh the dashboard payload immediately
                # so the next attempt is made against the current live image.
                if ch.status == "pending" and ch.driver_ref:
                    refreshed = ch.refresh_image()
                    if not refreshed and ch.image_error:
                        ch.last_error = f"{ch.last_error} {ch.image_error}"
                if ch.status == "failed":
                    ch.completion_event.set()
                return False, ch.last_error
        except Exception as exc:
            ch.last_error = f"Error during verification: {exc}"
            logger.error("[ManualCaptcha] Exception submitting solution for %s: %s", challenge_id, exc)
            return False, ch.last_error

    def verify_interactive(self, challenge_id: str) -> Tuple[bool, str]:
        """
        Verifies whether an interactive challenge (reCAPTCHA, Cloudflare) has been completed in the browser.
        Returns (success, message).
        """
        ch = self.get_challenge(challenge_id)
        if not ch:
            return False, "Challenge not found."
        if ch.status == "solved":
            return True, "Challenge already verified."
        if ch.is_expired():
            ch.status = "expired"
            ch.completion_event.set()
            return False, "Challenge has expired."

        if not ch.verify_interactive_handler:
            return False, "No interactive verification handler registered."

        try:
            unblocked, msg = ch.verify_interactive_handler()
            if unblocked:
                ch.status = "solved"
                ch.resolved_at = datetime.now().isoformat()
                ch.last_error = ""
                ch.completion_event.set()
                logger.info("[ManualCaptcha] Interactive challenge %s verified unblocked!", challenge_id)
                return True, msg or "Website verification confirmed."
            else:
                ch.last_error = msg or "Website remains blocked. Please complete the verification in browser."
                return False, ch.last_error
        except Exception as exc:
            ch.last_error = f"Verification error: {exc}"
            return False, ch.last_error

    def skip_or_mark_manual(self, challenge_id: str, reason: str = "Skipped by user") -> bool:
        """User chose to skip the challenge and mark the job as Manual Required."""
        ch = self.get_challenge(challenge_id)
        if not ch:
            return False
        ch.status = "dismissed"
        ch.last_error = reason
        ch.resolved_at = datetime.now().isoformat()
        ch.completion_event.set()
        logger.info("[ManualCaptcha] Challenge %s marked as manual required / skipped", challenge_id)
        return True

    def open_in_system_browser(self, challenge_id: str) -> Tuple[bool, str]:
        """Opens the challenge URL in the user's desktop browser."""
        ch = self.get_challenge(challenge_id)
        if not ch or not ch.source_url:
            return False, "Challenge or source URL not found."
        try:
            webbrowser.open(ch.source_url)
            return True, ch.source_url
        except Exception as exc:
            return False, str(exc)

    def refresh_challenge_image(self, challenge_id: str) -> Tuple[bool, str]:
        """Requests a refreshed image for the specified challenge from the live browser session."""
        ch = self.get_challenge(challenge_id)
        if not ch:
            return False, "Challenge nicht gefunden."
        if ch.status == "expired":
            # A refresh is a new attempt in the same authenticated worker
            # session; preserve all job/session identity while resetting only
            # the challenge attempt state.
            if not ch.driver_ref:
                return False, "Challenge expired; no authenticated browser session is available for refresh."
            ch.status = "pending"
            ch.attempts = 0
            ch.expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()
        if ch.challenge_type != "image_text":
            return False, "This challenge has no refreshable image."
        img_b64 = ch.refresh_image()
        return ch.image_valid, img_b64 if ch.image_valid else ch.image_error

    def cancel_all_for_job(self, job_id: str) -> None:
        """Unblocks all waiting workers if a task is cancelled, paused, or stopped."""
        with self._lock:
            for ch in self._challenges.values():
                if ch.job_id == job_id and ch.status == "pending":
                    ch.status = "dismissed"
                    ch.completion_event.set()


# Global Singleton
_global_captcha_manager = ManualCaptchaManager()


def get_manual_captcha_manager() -> ManualCaptchaManager:
    return _global_captcha_manager

