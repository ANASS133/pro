import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from .true_captcha_solver import TrueCaptchaSolver

logger = logging.getLogger(__name__)
NAME_PATTERN = r"[A-ZÃ„Ã–Ãœ][A-Za-zÃ„Ã–ÃœÃ¤Ã¶Ã¼ÃŸ'.-]+"
ARBEITGEBER_PATTERN = re.compile(
    rf"\b(?:Frau|Herr|Herrn)\s+{NAME_PATTERN}(?:\s+{NAME_PATTERN}){{0,3}}\b"
)
ARBEITGEBER_NAME_TOKEN_PATTERN = r"[^\W\d_][\w'.-]*"
ARBEITGEBER_PATTERN = re.compile(
    rf"\b(?:Frau|Herr|Herrn)\s+{ARBEITGEBER_NAME_TOKEN_PATTERN}\b",
    re.IGNORECASE,
)
PROGRESS_DIR = Path("data") / "progress"


def normalize_arbeitsgeber(value: Optional[str]) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw:
        return ""

    match = ARBEITGEBER_PATTERN.search(raw)
    if not match:
        return raw

    return re.sub(r"\s+", " ", match.group(0)).strip().lower()


class WorkingEmailExtractor:
    def __init__(
        self,
        captcha_userid: str,
        captcha_apikey: str,
        headless: bool = False,
        known_emails: Optional[Set[str]] = None,
    ):
        self.captcha_solver = TrueCaptchaSolver(captcha_userid, captcha_apikey)
        self.setup_driver(headless)
        self.known_emails = {self._normalize_email(e) for e in (known_emails or set()) if e}
        self.stats = {
            "processed": 0,
            "emails_found": 0,
            "captchas_encountered": 0,
            "captchas_solved": 0,
            "failed": 0,
        }
        PROGRESS_DIR.mkdir(parents=True, exist_ok=True)

    def _normalize_email(self, value: Optional[str]) -> str:
        if not value:
            return ""
        return str(value).strip().strip(".,;:").lower()

    def setup_driver(self, headless: bool):
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )

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
            "ungewÃ¶hnlicher verkehr",
        ]
        return any(ind in text for ind in indicators)

    def save_captcha_snapshot(self, static_dir: str = "static") -> str:
        target_dir = Path(static_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = target_dir / "captcha_latest.png"
        self.driver.save_screenshot(str(snapshot_path))
        return str(snapshot_path)

    def handle_captcha(self) -> bool:
        has_image_captcha = self.check_for_captcha()
        has_recaptcha = self.has_recaptcha_marker()
        blocked = self.is_blocked_page()

        if not blocked:
            return True

        if has_recaptcha and not has_image_captcha:
            logger.warning("Blocked by reCAPTCHA/hCaptcha challenge, unsupported by OCR flow")
            return False

        for _ in range(3):
            captcha_img = self._find_captcha_image()
            captcha_input = self._find_captcha_input()
            if not captcha_img or not captcha_input:
                return False

            captcha_text = self._solve_captcha_from_element(captcha_img)
            if not captcha_text:
                time.sleep(1.5)
                continue

            try:
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
            except Exception:
                try:
                    self.driver.execute_script(
                        "arguments[0].value = arguments[1];"
                        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                        captcha_input,
                        captcha_text,
                    )
                except Exception:
                    time.sleep(1.5)
                    continue

            submit_btn = self._find_submit_button()
            if submit_btn:
                try:
                    submit_btn.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", submit_btn)
            time.sleep(2)

            if not self.is_blocked_page():
                self.stats["captchas_solved"] += 1
                return True

        return False

    def _find_captcha_image(self):
        selectors = [
            "//*[@id='kontaktdaten-captcha-image']",
            "//img[contains(@src, 'captcha')]",
            "//img[contains(@alt, 'captcha')]",
            "//img[contains(@id, 'captcha')]",
            "//img[contains(@class, 'captcha')]",
            "//div[contains(@class, 'captcha')]//img",
        ]
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.XPATH, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def _find_captcha_input(self):
        selectors = [
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

    def _solve_captcha_from_element(self, captcha_img) -> Optional[str]:
        try:
            img_src = captcha_img.get_attribute("src")
            if img_src and img_src.startswith("data:image"):
                image_bytes = base64.b64decode(img_src.split(",", 1)[1])
                return self.captcha_solver.solve_captcha(image_bytes)
            if img_src and img_src.startswith("http"):
                img_response = requests.get(img_src, timeout=20)
                if img_response.status_code == 200 and img_response.content:
                    return self.captcha_solver.solve_captcha(img_response.content)
            return self.captcha_solver.solve_from_screenshot(self.driver, captcha_img)
        except Exception as exc:
            logger.error("Error solving CAPTCHA: %s", exc)
            return None

    def extract_contact_info(self):
        page_text = self.driver.find_element(By.TAG_NAME, "body").text

        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        emails = re.findall(email_pattern, page_text)

        phone_patterns = [
            r"\+49[-\s]?\(?0?\)?[-\s]?\d{1,4}[-\s]?\d{1,8}",
            r"0\d{1,4}[-\s]?\d{1,8}",
            r"\(0\d{1,4}\)[-\s]?\d{1,8}",
        ]
        phones = []
        for pattern in phone_patterns:
            phones.extend(re.findall(pattern, page_text))

        phones = list(set(phones))
        arbeitsgeber_match = ARBEITGEBER_PATTERN.search(page_text)
        arbeitsgeber = normalize_arbeitsgeber(
            arbeitsgeber_match.group(0) if arbeitsgeber_match else None
        ) or None
        return (emails[0] if emails else None, phones[0] if phones else None, arbeitsgeber)

    def open_job(self, job: Dict, delay_seconds: float = 3.0) -> None:
        self.driver.get(job.get("url", ""))
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    def process_job(self, job: Dict, delay_seconds: float = 3.0) -> Dict:
        try:
            self.open_job(job, delay_seconds=delay_seconds)

            if self.is_blocked_page() or self.check_for_captcha():
                self.stats["captchas_encountered"] += 1
                if self.handle_captcha():
                    time.sleep(2)
                else:
                    job["email"] = "CAPTCHA_FAILED"
                    job["phone"] = None
                    job["email_extracted"] = False
                    self.stats["failed"] += 1
                    return job

            email, phone, arbeitsgeber = self.extract_contact_info()
            normalized_email = self._normalize_email(email)
            if normalized_email and normalized_email in self.known_emails:
                job["email"] = "DUPLICATE_EMAIL_SKIPPED"
                job["phone"] = phone
                job["arbeitsgeber"] = arbeitsgeber
                job["email_extracted"] = False
                self.stats["processed"] += 1
                return job

            job["email"] = email
            job["phone"] = phone
            job["arbeitsgeber"] = arbeitsgeber
            job["email_extracted"] = bool(normalized_email)

            self.stats["processed"] += 1
            if normalized_email:
                self.stats["emails_found"] += 1
                self.known_emails.add(normalized_email)

        except Exception as exc:
            logger.error("Error processing job: %s", exc)
            job["email"] = f"ERROR: {exc}"
            job["phone"] = None
            job["arbeitsgeber"] = None
            job["email_extracted"] = False
            self.stats["failed"] += 1

        return job

    def save_progress(
        self, jobs: List[Dict], index: int, base_name: str = "auto_extraction_progress"
    ):
        json_path = PROGRESS_DIR / f"{base_name}.json"
        csv_path = PROGRESS_DIR / f"{base_name}.csv"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_index": index,
                    "total": len(jobs),
                    "stats": self.stats,
                    "jobs": jobs[: index + 1],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        pd.DataFrame(jobs[: index + 1]).to_csv(csv_path, index=False, encoding="utf-8")

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass
