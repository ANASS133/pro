import base64
import logging
import time

import requests
from selenium.webdriver.common.by import By

from .true_captcha_solver import TrueCaptchaSolver

logger = logging.getLogger(__name__)


class CaptchaHandler:
    def __init__(self, userid: str, apikey: str):
        self.solver = TrueCaptchaSolver(userid, apikey)

    def find_captcha_image(self, driver):
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
                elements = driver.find_elements(By.XPATH, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def find_captcha_input(self, driver):
        selectors = [
            "//*[@id='kontaktdaten-captcha-input']",
            "//input[contains(@name, 'captcha')]",
            "//input[contains(@id, 'captcha')]",
            "//input[contains(@placeholder, 'CAPTCHA')]",
            "//input[contains(@placeholder, 'captcha')]",
        ]
        for selector in selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def find_submit_button(self, driver):
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
                elements = driver.find_elements(By.XPATH, selector)
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def _captcha_still_visible(self, driver) -> bool:
        try:
            image = self.find_captcha_image(driver)
            input_field = self.find_captcha_input(driver)
            if image or input_field:
                return True
            body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
            return "sicherheitsabfrage" in body_text or "captcha" in body_text
        except Exception:
            return False

    def _get_captcha_bytes(self, driver, captcha_img):
        img_src = captcha_img.get_attribute("src")
        if img_src and img_src.startswith("data:image"):
            return base64.b64decode(img_src.split(",", 1)[1])

        if img_src and img_src.startswith("http"):
            try:
                session = requests.Session()
                for cookie in driver.get_cookies():
                    session.cookies.set(cookie["name"], cookie["value"])
                response = session.get(img_src, timeout=20)
                response.raise_for_status()
                if response.content:
                    return response.content
            except Exception as exc:
                logger.warning("Failed to fetch captcha image via src URL: %s", exc)

        return captcha_img.screenshot_as_png

    def _fill_captcha_input(self, driver, captcha_input, solution: str):
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", captcha_input
            )
            captcha_input.click()
            captcha_input.clear()
            captcha_input.send_keys(solution)
            return True
        except Exception:
            try:
                # JS fallback for hidden/overlayed input fields.
                driver.execute_script(
                    "arguments[0].value = arguments[1];"
                    "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                    "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                    captcha_input,
                    solution,
                )
                return True
            except Exception as exc:
                logger.error("Failed to fill captcha input: %s", exc)
                return False

    def _submit_captcha(self, driver, submit_btn):
        if not submit_btn:
            return False
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", submit_btn
            )
            submit_btn.click()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", submit_btn)
                return True
            except Exception as exc:
                logger.error("Failed to click captcha submit: %s", exc)
                return False

    def handle_captcha(self, driver, max_attempts: int = 3) -> bool:
        for attempt in range(max_attempts):
            captcha_img = self.find_captcha_image(driver)
            if not captcha_img:
                return False

            try:
                image_data = self._get_captcha_bytes(driver, captcha_img)
            except Exception as exc:
                logger.error("Failed to get CAPTCHA image: %s", exc)
                continue

            solution = self.solver.solve_captcha(image_data)
            if not solution:
                time.sleep(2)
                continue
            logger.info("CAPTCHA candidate solution: %s", solution)

            captcha_input = self.find_captcha_input(driver)
            if not captcha_input:
                return False

            if not self._fill_captcha_input(driver, captcha_input, solution):
                time.sleep(1.5)
                continue

            submit_btn = self.find_submit_button(driver)
            if not self._submit_captcha(driver, submit_btn):
                time.sleep(1.5)
                continue
            time.sleep(2.5)

            # Success only when captcha input/image is gone afterwards.
            if not self._captcha_still_visible(driver):
                return True
            logger.info("CAPTCHA still visible after submit, retrying with fresh image")

        return False
