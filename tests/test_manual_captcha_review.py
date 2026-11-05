# -*- coding: utf-8 -*-
"""
Tests for JobScout Manual CAPTCHA Review Feature.

Verifies:
1. Challenge creation with platform, job ID, worker ID, source URL, and challenge type.
2. Image-text manual CAPTCHA code submission and legitimate website unblocking confirmation.
3. Interactive challenge (reCAPTCHA / bot protection) verification flow.
4. Safe retry when code is rejected vs marking Manual Required when skipped or expired.
5. Unrelated workers continue processing other jobs while one worker waits for review.
6. API endpoints for challenge retrieval, solution submission, interactive verification, and skipping.
"""

import tempfile
import threading
import time
import unittest
import base64
import io
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw

import app as app_module
from services.manual_captcha_service import (
    ManualCaptchaChallenge,
    ManualCaptchaManager,
    get_manual_captcha_manager,
    validate_captcha_image,
)
from services.captcha_monitor import get_captcha_tracker, reset_captcha_tracker
from scraper.working_email_extractor import WorkingEmailExtractor

_captcha_image = Image.new("RGB", (80, 30), "white")
ImageDraw.Draw(_captcha_image).text((5, 5), "A7K9", fill="black")
_captcha_buffer = io.BytesIO()
_captcha_image.save(_captcha_buffer, "PNG")
VALID_PNG = "data:image/png;base64," + base64.b64encode(_captcha_buffer.getvalue()).decode("ascii")


class ManualCaptchaReviewTests(unittest.TestCase):
    def setUp(self):
        self.manager = ManualCaptchaManager()
        self.saved_manager = get_manual_captcha_manager()
        # Patch global manager with clean test instance
        self.patcher = patch(
            "services.manual_captcha_service.get_manual_captcha_manager",
            return_value=self.manager,
        )
        self.patcher.start()
        reset_captcha_tracker("test_job_123")

    def tearDown(self):
        self.patcher.stop()

    def test_challenge_creation_and_attributes(self):
        challenge = self.manager.create_challenge(
            job_id="test_job_123",
            search_run_id="run_abc123",
            job_index=5,
            worker_id=2,
            platform="Arbeitsagentur",
            job_title="Hotelfachmann (m/w/d)",
            employer="Grand Hotel Berlin",
            source_url="https://example.com/job/5",
            challenge_type="image_text",
            captcha_image_base64=VALID_PNG,
            timeout_seconds=300.0,
        )

        self.assertIsNotNone(challenge.challenge_id)
        self.assertEqual(challenge.job_id, "test_job_123")
        self.assertEqual(challenge.worker_id, 2)
        self.assertEqual(challenge.platform, "Arbeitsagentur")
        self.assertEqual(challenge.challenge_type, "image_text")
        self.assertEqual(challenge.status, "pending")
        self.assertFalse(challenge.is_expired())

        # Test to_dict serialization
        d = challenge.to_dict()
        self.assertEqual(d["worker_id"], 2)
        self.assertEqual(d["platform"], "Arbeitsagentur")
        self.assertTrue(d["can_retry"])
        self.assertIn("data:image/png;base64", d["captcha_image_base64"])

    def test_image_captcha_manual_submission_success(self):
        submitted_code = []

        def mock_submit(code: str):
            submitted_code.append(code)
            if code == "CORRECT42":
                return True, "Code accepted by website."
            return False, "Incorrect code."

        challenge = self.manager.create_challenge(
            job_id="test_job_123",
            search_run_id="run_abc123",
            job_index=1,
            worker_id=1,
            platform="Ausbildung.de",
            job_title="Koch (m/w/d)",
            employer="Restaurant Zur Post",
            source_url="https://example.com/job/1",
            challenge_type="image_text",
            captcha_image_base64=VALID_PNG,
            submit_handler=mock_submit,
        )

        # 1. Submit wrong code
        ok, msg = self.manager.submit_solution(challenge.challenge_id, "WRONG")
        self.assertFalse(ok)
        self.assertEqual(challenge.status, "pending")
        self.assertEqual(challenge.attempts, 1)
        self.assertTrue(challenge.to_dict()["can_retry"])

        # 2. Submit correct code
        ok, msg = self.manager.submit_solution(challenge.challenge_id, "CORRECT42")
        self.assertTrue(ok)
        self.assertEqual(challenge.status, "solved")
        self.assertTrue(challenge.completion_event.is_set())
        self.assertIn("CORRECT42", submitted_code)

    def test_interactive_captcha_verification(self):
        is_unblocked = [False]

        def mock_verify_interactive():
            if is_unblocked[0]:
                return True, "Website unblocked."
            return False, "Still blocked by Cloudflare."

        challenge = self.manager.create_challenge(
            job_id="test_job_123",
            search_run_id="run_abc123",
            job_index=2,
            worker_id=3,
            platform="Google Maps",
            job_title="Zahnmedizinische Fachangestellte",
            employer="Praxis Dr. Müller",
            source_url="https://praxis-mueller.test/karriere",
            challenge_type="turnstile",
            captcha_image_base64=VALID_PNG,
            verify_interactive_handler=mock_verify_interactive,
        )

        # Before unblocking
        ok, msg = self.manager.verify_interactive(challenge.challenge_id)
        self.assertFalse(ok)
        self.assertEqual(challenge.status, "pending")
        self.assertFalse(challenge.completion_event.is_set())

        # User finishes verification in browser session
        is_unblocked[0] = True
        ok, msg = self.manager.verify_interactive(challenge.challenge_id)
        self.assertTrue(ok)
        self.assertEqual(challenge.status, "solved")
        self.assertTrue(challenge.completion_event.is_set())

    def test_challenge_expiry_unblocks_worker(self):
        challenge = self.manager.create_challenge(
            job_id="test_job_123",
            search_run_id="run_abc123",
            job_index=3,
            worker_id=4,
            platform="IHK",
            job_title="Industriemechaniker",
            employer="Maschinenbau AG",
            source_url="https://ihk.test/job/3",
            challenge_type="image_text",
            captcha_image_base64="",
            timeout_seconds=0.1,  # Expire immediately
        )
        time.sleep(0.15)
        self.assertTrue(challenge.is_expired())

        # Worker wait returns expired and does not deadlock
        res = challenge.wait_for_resolution(timeout=0.2)
        self.assertEqual(res, "expired")
        ok, message = self.manager.refresh_challenge_image(challenge.challenge_id)
        self.assertFalse(ok)
        self.assertIn("expired", message.lower())

    def test_missing_or_corrupt_image_is_explicit_and_cannot_accept_code(self):
        challenge = self.manager.create_challenge(
            job_id="test_job_123", search_run_id="run_abc123", job_index=8,
            worker_id=3, platform="IHK", job_title="Koch", employer="Hotel",
            source_url="https://ihk.test/job/8", challenge_type="image_text",
            captcha_image_base64="data:image/png;base64,not-valid",
            submit_handler=lambda code: (True, "should not run"),
        )
        payload = challenge.to_dict()
        self.assertFalse(payload["image_valid"])
        self.assertEqual(payload["captcha_image_base64"], "")
        self.assertTrue(payload["image_error"])
        ok, message = self.manager.submit_solution(challenge.challenge_id, "1234")
        self.assertFalse(ok)
        self.assertIn("image", message.lower())

    def test_challenge_image_validation(self):
        self.assertTrue(validate_captcha_image(VALID_PNG)[0])
        self.assertFalse(validate_captcha_image("")[0])
        self.assertFalse(validate_captcha_image("data:image/png;base64,AAAA")[0])
        from PIL import Image
        blank = io.BytesIO()
        Image.new("RGB", (80, 30), "white").save(blank, "PNG")
        blank_uri = "data:image/png;base64," + base64.b64encode(blank.getvalue()).decode("ascii")
        valid, error = validate_captcha_image(blank_uri)
        self.assertFalse(valid)
        self.assertIn("blank", error.lower())

    def test_challenge_classification(self):
        extractor = WorkingEmailExtractor.__new__(WorkingEmailExtractor)
        extractor.driver = MagicMock()
        extractor.has_recaptcha_marker = MagicMock(return_value=False)
        extractor.driver.find_elements.side_effect = lambda by, query: [object()] if "challenges.cloudflare.com" in query else []
        self.assertEqual(extractor._classify_manual_challenge(), "turnstile")

        extractor.driver.find_elements.side_effect = lambda by, query: []
        extractor.has_recaptcha_marker.return_value = True
        self.assertEqual(extractor._classify_manual_challenge(), "recaptcha")

        extractor.has_recaptcha_marker.return_value = False
        extractor.driver.find_element.return_value.text = "Bitte anmelden"
        extractor.driver.find_elements.side_effect = lambda by, query: [object()] if "password" in query else []
        self.assertEqual(extractor._classify_manual_challenge(), "login_required")

        extractor.driver.find_elements.side_effect = lambda by, query: []
        self.assertEqual(extractor._classify_manual_challenge(object(), object()), "image_text")
        self.assertEqual(extractor._classify_manual_challenge(), "unknown")

    def test_user_skip_marks_dismissed_and_unblocks(self):
        challenge = self.manager.create_challenge(
            job_id="test_job_123",
            search_run_id="run_abc123",
            job_index=4,
            worker_id=2,
            platform="Azubiyo",
            job_title="Kaufmann für Büromanagement",
            employer="Office Solutions",
            source_url="https://azubiyo.test/job/4",
            challenge_type="image_text",
            captcha_image_base64="",
        )

        ok = self.manager.skip_or_mark_manual(challenge.challenge_id, reason="User chose to skip")
        self.assertTrue(ok)
        self.assertEqual(challenge.status, "dismissed")
        self.assertTrue(challenge.completion_event.is_set())

    def test_independent_worker_continues_processing_while_other_waits(self):
        """
        Worker 1 hits a challenge and waits on the challenge event.
        Worker 2 executes other jobs concurrently without blocking.
        """
        challenge = self.manager.create_challenge(
            job_id="test_job_multi",
            search_run_id="run_multi",
            job_index=1,
            worker_id=1,
            platform="Arbeitsagentur",
            job_title="Pflegefachkraft",
            employer="Klinikum Mitte",
            source_url="https://example.com/job/1",
            challenge_type="image_text",
            captcha_image_base64=VALID_PNG,
            submit_handler=lambda code: (True, "OK"),
        )

        worker1_finished = threading.Event()
        worker2_jobs_done = []

        def worker_1_thread():
            challenge.wait_for_resolution(timeout=5.0)
            worker1_finished.set()

        def worker_2_thread():
            for i in range(3):
                time.sleep(0.05)
                worker2_jobs_done.append(f"job_{i}")

        t1 = threading.Thread(target=worker_1_thread)
        t2 = threading.Thread(target=worker_2_thread)

        t1.start()
        t2.start()

        # Worker 2 should complete its jobs while Worker 1 is still waiting for manual CAPTCHA review
        t2.join(timeout=2.0)
        self.assertEqual(worker2_jobs_done, ["job_0", "job_1", "job_2"])
        self.assertFalse(worker1_finished.is_set())

        # Now solve Worker 1's challenge
        self.manager.submit_solution(challenge.challenge_id, "CODE123")
        t1.join(timeout=2.0)
        self.assertTrue(worker1_finished.is_set())


class ManualCaptchaEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.app = app_module.app.test_client()
        self.manager = ManualCaptchaManager()
        self.patcher = patch(
            "services.manual_captcha_service.get_manual_captcha_manager",
            return_value=self.manager,
        )
        self.patcher.start()

        # Setup in-memory auto extraction job
        with app_module.auto_extraction_jobs_lock:
            app_module.auto_extraction_jobs["job_test_api"] = {
                "job_id": "job_test_api",
                "search_run_id": "run_api_1",
                "is_running": True,
                "current_index": 1,
                "total_jobs": 10,
                "workers": {
                    "worker_1": {"worker_id": 1, "status": "working", "current_stage": "Manual CAPTCHA Review"}
                },
            }

    def tearDown(self):
        self.patcher.stop()
        with app_module.auto_extraction_jobs_lock:
            app_module.auto_extraction_jobs.pop("job_test_api", None)

    def test_status_endpoint_returns_active_challenges(self):
        ch = self.manager.create_challenge(
            job_id="job_test_api",
            search_run_id="run_api_1",
            job_index=1,
            worker_id=1,
            platform="Arbeitsagentur",
            job_title="Elektriker",
            employer="Elektro GmbH",
            source_url="https://arbeitsagentur.test/job/1",
            challenge_type="image_text",
            captcha_image_base64=VALID_PNG,
        )

        resp = self.app.get("/api/inline/auto-jobs/status/job_test_api")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        job_data = data["job"]
        self.assertIn("active_challenges", job_data)
        self.assertEqual(len(job_data["active_challenges"]), 1)
        self.assertEqual(job_data["active_challenges"][0]["challenge_id"], ch.challenge_id)

    def test_solve_and_skip_endpoints(self):
        ch = self.manager.create_challenge(
            job_id="job_test_api",
            search_run_id="run_api_1",
            job_index=1,
            worker_id=1,
            platform="Arbeitsagentur",
            job_title="Elektriker",
            employer="Elektro GmbH",
            source_url="https://arbeitsagentur.test/job/1",
            challenge_type="image_text",
            captcha_image_base64=VALID_PNG,
            submit_handler=lambda code: (True, "Code OK") if code == "777" else (False, "Wrong"),
        )

        # 1. Solve with wrong code
        r1 = self.app.post("/api/inline/auto-jobs/challenges/solve", json={
            "challenge_id": ch.challenge_id,
            "solution_text": "000",
        })
        d1 = r1.get_json()
        self.assertFalse(d1["success"])
        self.assertTrue(d1["can_retry"])

        # 2. Solve with correct code
        r2 = self.app.post("/api/inline/auto-jobs/challenges/solve", json={
            "challenge_id": ch.challenge_id,
            "solution_text": "777",
        })
        d2 = r2.get_json()
        self.assertTrue(d2["success"])
        self.assertEqual(ch.status, "solved")

        # 3. Create another challenge and test skip
        ch2 = self.manager.create_challenge(
            job_id="job_test_api",
            search_run_id="run_api_1",
            job_index=2,
            worker_id=2,
            platform="Ausbildung.de",
            job_title="Maler",
            employer="Malerbetrieb",
            source_url="https://ausbildung.test/job/2",
            challenge_type="turnstile",
            captcha_image_base64="",
        )
        r3 = self.app.post("/api/inline/auto-jobs/challenges/skip", json={
            "challenge_id": ch2.challenge_id,
        })
        d3 = r3.get_json()
        self.assertTrue(d3["success"])
        self.assertEqual(ch2.status, "dismissed")

    def test_refresh_challenge_image_endpoint(self):
        mock_driver = MagicMock()
        mock_driver.find_elements.return_value = []
        ch = self.manager.create_challenge(
            job_id="job_refresh_test",
            search_run_id="run_ref_1",
            job_index=1,
            worker_id=3,
            platform="ihk.de",
            job_title="Koch",
            employer="Hotel Gasthof",
            source_url="https://ihk.test/job/1",
            challenge_type="image_text",
            captcha_image_base64="",
            driver_ref=mock_driver,
        )

        resp = self.app.post("/api/inline/auto-jobs/challenges/refresh-image", json={
            "challenge_id": ch.challenge_id,
        })
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["captcha_image_base64"], "")
        self.assertTrue(data["message"])

    def test_refresh_valid_image_endpoint(self):
        mock_driver = MagicMock()
        image_element = MagicMock()
        image_element.get_attribute.return_value = ""
        image_element.screenshot_as_base64 = VALID_PNG.split(",", 1)[1]
        mock_driver.find_elements.return_value = [image_element]
        mock_driver.execute_script.return_value = True
        ch = self.manager.create_challenge(
            job_id="job_refresh_valid", search_run_id="run_ref_2", job_index=2,
            worker_id=2, platform="IHK", job_title="Koch", employer="Hotel",
            source_url="https://ihk.test/job/2", challenge_type="image_text",
            captcha_image_base64="", driver_ref=mock_driver,
        )
        resp = self.app.post("/api/inline/auto-jobs/challenges/refresh-image", json={"challenge_id": ch.challenge_id})
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["captcha_image_base64"], VALID_PNG)
        self.assertTrue(ch.image_valid)


if __name__ == "__main__":
    unittest.main()
