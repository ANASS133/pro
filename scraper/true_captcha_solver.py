import base64
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class TrueCaptchaSolver:
    def __init__(self, userid: str, apikey: str):
        self.userid = str(userid or "").strip()
        self.apikey = str(apikey or "").strip()
        self.api_url = "https://api.apitruecaptcha.org/one/gettext"
        self.timeout = 30

    def solve_captcha(self, image_data: bytes) -> Optional[str]:
        if not self.userid or not self.apikey:
            logger.error("TrueCAPTCHA credentials are missing")
            return None

        try:
            payload = {
                "userid": self.userid,
                "apikey": self.apikey,
                "data": base64.b64encode(image_data).decode("utf-8"),
            }

            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                logger.error("TrueCAPTCHA API error: %s", response.status_code)
                return None

            result = response.json()
            logger.info("TrueCAPTCHA response: %s", result)

            possible_fields = [
                "result",
                "text",
                "code",
                "captcha",
                "captcha_text",
                "answer",
                "solution",
            ]
            for field in possible_fields:
                value = result.get(field)
                if value:
                    return str(value).strip()

            logger.error("No solution text in response")
            return None

        except requests.RequestException as exc:
            logger.error("TrueCAPTCHA request failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("Error solving CAPTCHA: %s", exc)
            return None

    def solve_from_screenshot(self, driver, element=None) -> Optional[str]:
        image_data = element.screenshot_as_png if element is not None else driver.get_screenshot_as_png()
        return self.solve_captcha(image_data)

    def solve_from_file(self, image_path: str) -> Optional[str]:
        with open(image_path, "rb") as f:
            return self.solve_captcha(f.read())
