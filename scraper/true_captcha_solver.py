import base64
import logging
from typing import Any, Dict, Optional

import requests

from services.captcha_monitor import get_captcha_tracker

logger = logging.getLogger(__name__)


class TrueCaptchaSolver:
    def __init__(self, userid: str, apikey: str, worker_id: int = 1, job_id: str = ""):
        self.userid = str(userid or "").strip()
        self.apikey = str(apikey or "").strip()
        self.worker_id = worker_id
        self.job_id = job_id
        self.api_url = "https://api.apitruecaptcha.org/one/gettext"
        self.timeout = 30

    def solve_captcha(
        self,
        image_data: bytes,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.userid or not self.apikey:
            logger.error("TrueCAPTCHA credentials are missing")
            return None

        ctx = context or {}
        job_id = ctx.get("job_id") or self.job_id
        worker_id = ctx.get("worker_id") or self.worker_id
        domain = ctx.get("domain") or "unknown"
        corr_id = ctx.get("correlation_id") or f"c_gen_w{worker_id}"

        tracker = get_captcha_tracker(job_id)
        tracker.record_service_request(
            correlation_id=corr_id,
            worker_id=worker_id,
            domain=domain,
            service_name="TrueCAPTCHA",
        )

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
                logger.error("TrueCAPTCHA API error: status=%s", response.status_code)
                tracker.record_service_response(
                    correlation_id=corr_id,
                    worker_id=worker_id,
                    domain=domain,
                    success=False,
                )
                return None

            result = response.json()
            req_id = str(result.get("requestId") or result.get("request_id") or "")
            is_success = bool(result.get("success", True))
            time_taken = result.get("time_taken")

            # Privacy-safe logging: log request metadata without logging the solution text
            logger.info(
                "TrueCAPTCHA response: requestId=%s, success=%s, time_taken=%s (worker=%s, correlation=%s)",
                req_id[:12] if req_id else "unknown",
                is_success,
                time_taken,
                worker_id,
                corr_id,
            )

            tracker.record_service_response(
                correlation_id=corr_id,
                worker_id=worker_id,
                domain=domain,
                success=is_success,
                request_id=req_id,
                time_taken=float(time_taken) if time_taken else None,
            )

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
            tracker.record_service_response(
                correlation_id=corr_id,
                worker_id=worker_id,
                domain=domain,
                success=False,
            )
            return None
        except Exception as exc:
            logger.error("Error solving CAPTCHA: %s", exc)
            tracker.record_service_response(
                correlation_id=corr_id,
                worker_id=worker_id,
                domain=domain,
                success=False,
            )
            return None

    def solve_from_screenshot(
        self,
        driver,
        element=None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        image_data = element.screenshot_as_png if element is not None else driver.get_screenshot_as_png()
        return self.solve_captcha(image_data, context=context)

    def solve_from_file(
        self,
        image_path: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        with open(image_path, "rb") as f:
            return self.solve_captcha(f.read(), context=context)
