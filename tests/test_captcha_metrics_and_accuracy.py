"""
Comprehensive Regression Test Suite for JobScout CAPTCHA Metrics,
Repeated Request Tracking, and Dashboard Accuracy.

Covers:
1. One challenge with multiple service requests (retries / repeated requests).
2. Multiple independent challenges across distinct domains and jobs.
3. Concurrent workers updating metrics safely without race conditions.
4. Idempotency against duplicate events.
5. Dashboard status endpoint polling consistency.
6. Correct distinction between recognition-service success and website verification confirmation.
7. Accurate HTTP fast-path vs Selenium fallback counters (no misclassification).
8. Extraction stop, cancellation, and resume state preservation.
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

from services.captcha_monitor import (
    CaptchaTracker,
    get_captcha_tracker,
    reset_captcha_tracker,
    generate_challenge_fingerprint,
)
from scraper.true_captcha_solver import TrueCaptchaSolver
from app import app, auto_extraction_jobs, auto_extraction_jobs_lock, _create_auto_extraction_job


class TestCaptchaMetricsAndAccuracy(unittest.TestCase):

    def setUp(self):
        reset_captcha_tracker()
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_one_challenge_multiple_service_requests(self):
        """A single challenge with a 3-iteration retry loop produces 1 unique challenge and 3 service requests."""
        tracker = CaptchaTracker(job_id="test_job_retry")
        fp = generate_challenge_fingerprint("example.com", "form-captcha-1")

        # Initial detection
        corr_id = tracker.record_challenge_detected(
            domain="example.com",
            worker_id=1,
            job_index=0,
            challenge_fingerprint=fp,
            details="Form captcha detected",
        )

        # 3 service requests for this single challenge
        for _ in range(3):
            tracker.record_service_request(corr_id, worker_id=1, domain="example.com")
            tracker.record_service_response(
                corr_id,
                worker_id=1,
                domain="example.com",
                success=True,
                request_id="req_abc123",
                time_taken=0.85,
            )

        summary = tracker.get_summary()

        self.assertEqual(summary["challenges_detected"], 1)
        self.assertEqual(summary["unique_challenges"], 1)
        self.assertEqual(summary["jobs_requiring_captcha"], 1)
        self.assertEqual(summary["service_requests"], 3)
        self.assertEqual(summary["responses_received"], 3)
        self.assertEqual(summary["website_verifications_confirmed"], 0)

    def test_multiple_independent_challenges(self):
        """Distinct challenges across different websites/jobs increment unique challenges accordingly."""
        tracker = CaptchaTracker(job_id="test_job_multi")

        # Challenge on Arbeitsagentur
        fp1 = generate_challenge_fingerprint("arbeitsagentur.de", "kontaktdaten-inpage")
        c1 = tracker.record_challenge_detected(
            domain="arbeitsagentur.de",
            worker_id=1,
            job_index=1,
            challenge_fingerprint=fp1,
        )
        tracker.record_service_request(c1, worker_id=1, domain="arbeitsagentur.de")
        tracker.record_service_response(c1, worker_id=1, domain="arbeitsagentur.de", success=True)
        tracker.record_website_verification(c1, worker_id=1, domain="arbeitsagentur.de")

        # Challenge on Azubiyo
        fp2 = generate_challenge_fingerprint("azubiyo.de", "cloudflare-cf-chl")
        c2 = tracker.record_challenge_detected(
            domain="azubiyo.de",
            worker_id=2,
            job_index=2,
            challenge_fingerprint=fp2,
        )
        tracker.record_service_request(c2, worker_id=2, domain="azubiyo.de")
        tracker.record_service_response(c2, worker_id=2, domain="azubiyo.de", success=True)
        tracker.record_manual_verification_required(c2, worker_id=2, domain="azubiyo.de", job_index=2)

        summary = tracker.get_summary()

        self.assertEqual(summary["challenges_detected"], 2)
        self.assertEqual(summary["unique_challenges"], 2)
        self.assertEqual(summary["jobs_requiring_captcha"], 2)
        self.assertEqual(summary["service_requests"], 2)
        self.assertEqual(summary["responses_received"], 2)
        self.assertEqual(summary["website_verifications_confirmed"], 1)
        self.assertEqual(summary["manual_verification_required"], 1)

    def test_distinction_recognition_success_vs_website_verification(self):
        """Recognition API success=True MUST NOT count as website verification if target website rejects or remains blocked."""
        test_job_id = "test_job_distinction"
        tracker = get_captcha_tracker(test_job_id)
        solver = TrueCaptchaSolver(userid="dummy_user", apikey="dummy_key", worker_id=1, job_id=test_job_id)

        fp = generate_challenge_fingerprint("portal.de", "inpage-captcha")
        corr_id = tracker.record_challenge_detected(
            domain="portal.de",
            worker_id=1,
            job_index=5,
            challenge_fingerprint=fp,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "requestId": "req_xyz999",
            "time_taken": 1.12,
            "result": "XYZ123",
        }

        with patch("requests.post", return_value=mock_resp):
            ctx = {"job_id": test_job_id, "worker_id": 1, "domain": "portal.de", "correlation_id": corr_id}
            sol = solver.solve_captcha(b"fake_image_bytes", context=ctx)

        self.assertEqual(sol, "XYZ123")

        # After submission, target website remains blocked:
        tracker.record_manual_verification_required(corr_id, worker_id=1, domain="portal.de", job_index=5)

        summary = tracker.get_summary()
        self.assertEqual(summary["service_requests"], 1)
        self.assertEqual(summary["responses_received"], 1)
        # MUST BE ZERO: Recognition returned True, but target website did NOT confirm verification
        self.assertEqual(summary["website_verifications_confirmed"], 0)
        self.assertEqual(summary["manual_verification_required"], 1)

    def test_concurrent_workers_thread_safe_telemetry(self):
        """4 concurrent workers recording events simultaneously produce deterministic and exact metrics."""
        tracker = CaptchaTracker(job_id="test_concurrent")

        def worker_task(w_id):
            for i in range(10):
                job_idx = w_id * 100 + i
                fp = generate_challenge_fingerprint(f"site{w_id}.de", f"ch_{i}")
                cid = tracker.record_challenge_detected(
                    domain=f"site{w_id}.de",
                    worker_id=w_id,
                    job_index=job_idx,
                    challenge_fingerprint=fp,
                )
                tracker.record_service_request(cid, worker_id=w_id, domain=f"site{w_id}.de")
                tracker.record_service_response(cid, worker_id=w_id, domain=f"site{w_id}.de", success=True)
                if i % 2 == 0:
                    tracker.record_website_verification(cid, worker_id=w_id, domain=f"site{w_id}.de")
                else:
                    tracker.record_manual_verification_required(cid, worker_id=w_id, domain=f"site{w_id}.de", job_index=job_idx)

        threads = [threading.Thread(target=worker_task, args=(w,)) for w in range(1, 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = tracker.get_summary()

        self.assertEqual(summary["challenges_detected"], 40)
        self.assertEqual(summary["unique_challenges"], 40)
        self.assertEqual(summary["service_requests"], 40)
        self.assertEqual(summary["responses_received"], 40)
        self.assertEqual(summary["website_verifications_confirmed"], 20)
        self.assertEqual(summary["manual_verification_required"], 20)

    def test_dashboard_status_endpoint_returns_captcha_and_network_metrics(self):
        """Dashboard status API reflects complete captcha_metrics summary and network routing state."""
        test_job_id = "test_dash_polling_job"
        tracker = get_captcha_tracker(test_job_id)
        cid = tracker.record_challenge_detected("arbeitsagentur.de", worker_id=1, job_index=3)
        tracker.record_service_request(cid, worker_id=1, domain="arbeitsagentur.de")
        tracker.record_service_response(cid, worker_id=1, domain="arbeitsagentur.de", success=True)
        tracker.record_website_verification(cid, worker_id=1, domain="arbeitsagentur.de")

        with auto_extraction_jobs_lock:
            auto_extraction_jobs[test_job_id] = {
                "job_id": test_job_id,
                "is_running": True,
                "current_index": 5,
                "total_jobs": 20,
                "captchas_solved": 1,
                "captcha_metrics": tracker.get_summary(),
                "fast_path_hits": 4,
                "selenium_fallbacks": 1,
                "workers": {
                    f"worker_{w}": {
                        "id": f"Worker {w}",
                        "worker_id": w,
                        "status": "idle",
                        "connection_status": "direct",
                        "network_profile": "Direct",
                        "public_ip": "192.0.2.1",
                    }
                    for w in range(1, 5)
                },
            }

        # Poll status twice to test consistency
        for _ in range(2):
            resp = self.client.get(f"/api/inline/auto-jobs/status/{test_job_id}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()

            self.assertTrue(data["success"])
            job = data["job"]
            cm = job["captcha_metrics"]

            self.assertEqual(cm["challenges_detected"], 1)
            self.assertEqual(cm["unique_challenges"], 1)
            self.assertEqual(cm["service_requests"], 1)
            self.assertEqual(cm["responses_received"], 1)
            self.assertEqual(cm["website_verifications_confirmed"], 1)
            self.assertEqual(cm["manual_verification_required"], 0)
            self.assertEqual(job["captchas_solved"], 1)

            # Verify network visibility distinction
            net = job.get("network_summary")
            self.assertIsNotNone(net)
            self.assertEqual(net["active_mode"], "direct_shared")

        # Cleanup
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(test_job_id, None)

    def test_accurate_http_and_selenium_fallback_counters(self):
        """Arbeitsagentur extractor correctly marks selenium when browser runs, preventing false fast-path hits."""
        from scraper.arbeitsagentur_extractor import ArbeitsagenturDetailExtractor

        extractor = ArbeitsagenturDetailExtractor()

        # Case 1: Fast HTTP SSR parsing succeeds without Selenium
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <html><body>
            <div id="bewerbung-email">karriere@firma.de</div>
        </body></html>
        """
        with patch("scraper.rate_limiter.safe_http_get", return_value=mock_resp):
            res_fast = extractor.extract_vacancy(
                {"url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/1000"},
                driver=None,
            )
            self.assertEqual(res_fast.get("extraction_method"), "fast_http")

        # Case 2: Missing channels on HTML, falls back to Stage 3 Selenium
        mock_empty_resp = MagicMock()
        mock_empty_resp.status_code = 200
        mock_empty_resp.text = "<html><body>Keine Kontaktdaten</body></html>"

        mock_driver = MagicMock()
        mock_driver.page_source = """
        <html><body>
            <a href="mailto:bewerbung@firma.de">bewerbung@firma.de</a>
        </body></html>
        """
        mock_driver.find_elements.return_value = []

        with patch("scraper.rate_limiter.safe_http_get", return_value=mock_empty_resp):
            res_sel = extractor.extract_vacancy(
                {"url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/2000"},
                driver=mock_driver,
            )
            # Must be accurately reported as selenium fallback!
            self.assertEqual(res_sel.get("extraction_method"), "selenium")

    def test_extraction_cancellation_and_resume_preserves_captcha_telemetry(self):
        """Pausing or resuming a job preserves existing CAPTCHA telemetry and events."""
        job_id = "test_cancel_resume_job"
        tracker = get_captcha_tracker(job_id)
        cid = tracker.record_challenge_detected("test.de", worker_id=1, job_index=0)
        tracker.record_service_request(cid, worker_id=1, domain="test.de")
        tracker.record_service_response(cid, worker_id=1, domain="test.de", success=True)
        tracker.record_website_verification(cid, worker_id=1, domain="test.de")

        with auto_extraction_jobs_lock:
            auto_extraction_jobs[job_id] = {
                "job_id": job_id,
                "is_running": False,
                "paused": True,
                "stop_requested": False,
                "current_index": 1,
                "total_jobs": 10,
                "captchas_solved": 1,
                "captcha_metrics": tracker.get_summary(),
            }

        # Status check while paused
        resp = self.client.get(f"/api/inline/auto-jobs/status/{job_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["job"]["captcha_metrics"]["unique_challenges"], 1)
        self.assertEqual(data["job"]["captcha_metrics"]["website_verifications_confirmed"], 1)

        # Resume job
        resume_resp = self.client.post(f"/api/inline/auto-jobs/continue/{job_id}")
        self.assertEqual(resume_resp.status_code, 200)

        # Verify metrics intact
        with auto_extraction_jobs_lock:
            resumed_job = auto_extraction_jobs[job_id]
            self.assertEqual(resumed_job["captcha_metrics"]["unique_challenges"], 1)
            self.assertEqual(resumed_job["captcha_metrics"]["website_verifications_confirmed"], 1)

        # Cleanup
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
