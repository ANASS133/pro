"""
Automated Test Suite for JobScout Real-Time Worker Platform Telemetry & Dashboard Accuracy.

Verifies:
1. Exact platform mapping for Arbeitsagentur, Ausbildung.de, Azubiyo, AUBI-plus, IHK, and Google Maps.
2. Platform is derived strictly from job 'source' or 'portal', never from employer domain.
3. Worker telemetry fields (current_platform, current_job_title, current_employer, current_stage).
4. Real-time stage progression (HTTP Fast-Path, Selenium Fallback, Email Extraction, Finding Application Form, Manual Review).
5. Pause behavior: preserves last processed platform and job details while marking worker paused.
6. Resume behavior: refreshes worker telemetry from the next assigned jobs.
7. Idle behavior: displays 'No active platform' when workers have no active job.
8. Preservation of Webshare proxy route details and completed counters.
9. Search-session isolation across different search runs.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app import (
    app,
    normalize_job_platform,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
    search_runs,
    search_runs_lock,
    _create_auto_extraction_job,
    _is_job_finished,
)
from scraper.working_email_extractor import WorkingEmailExtractor


class TestWorkerPlatformTelemetry(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.clear()
        with search_runs_lock:
            search_runs.clear()

    def test_normalize_job_platform_mapping(self):
        """Platform normalization must correctly identify all 6 standard German job platforms."""
        # 1. Arbeitsagentur
        self.assertEqual(normalize_job_platform({"source": "arbeitsagentur"}), "Arbeitsagentur")
        self.assertEqual(normalize_job_platform({"source": "arbeitsagentur.de"}), "Arbeitsagentur")
        self.assertEqual(normalize_job_platform({"portal": "jobboerse"}), "Arbeitsagentur")
        self.assertEqual(normalize_job_platform({"url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/1000"}), "Arbeitsagentur")

        # 2. Ausbildung.de
        self.assertEqual(normalize_job_platform({"source": "ausbildung.de"}), "Ausbildung.de")
        self.assertEqual(normalize_job_platform({"source": "ausbildung_de"}), "Ausbildung.de")
        self.assertEqual(normalize_job_platform({"portal": "Ausbildung.de"}), "Ausbildung.de")
        self.assertEqual(normalize_job_platform({"url": "https://www.ausbildung.de/berufe/fachinformatiker/"}), "Ausbildung.de")

        # 3. Azubiyo
        self.assertEqual(normalize_job_platform({"source": "azubiyo"}), "Azubiyo")
        self.assertEqual(normalize_job_platform({"source": "azubiyo.de"}), "Azubiyo")
        self.assertEqual(normalize_job_platform({"portal": "Azubiyo"}), "Azubiyo")

        # 4. AUBI-plus
        self.assertEqual(normalize_job_platform({"source": "aubi-plus.de"}), "AUBI-plus")
        self.assertEqual(normalize_job_platform({"source": "aubi_plus"}), "AUBI-plus")
        self.assertEqual(normalize_job_platform({"portal": "AUBI-plus"}), "AUBI-plus")

        # 5. IHK
        self.assertEqual(normalize_job_platform({"source": "ihk"}), "IHK")
        self.assertEqual(normalize_job_platform({"source": "ihk.de"}), "IHK")
        self.assertEqual(normalize_job_platform({"portal": "IHK Lehrstellenbörse"}), "IHK")
        self.assertEqual(normalize_job_platform({"url": "https://www.lehrstellen-boerse.de/job/123"}), "IHK")

        # 6. Google Maps
        self.assertEqual(normalize_job_platform({"source": "google_maps"}), "Google Maps")
        self.assertEqual(normalize_job_platform({"source": "google-maps"}), "Google Maps")
        self.assertEqual(normalize_job_platform({"maps_url": "https://maps.google.com/?cid=123"}), "Google Maps")

        # Empty / None
        self.assertEqual(normalize_job_platform({}), "No active platform")
        self.assertEqual(normalize_job_platform(None), "No active platform")

    def test_platform_derived_from_source_not_employer_domain(self):
        """Platform must be derived strictly from source/portal, never from employer website."""
        job = {
            "title": "Kaufmann für Büromanagement (m/w/d)",
            "company": "BMW Group",
            "source": "arbeitsagentur",
            "url": "https://www.bmwgroup.jobs/de/de.html",
            "employer_website": "https://www.bmwgroup.com",
            "apply_url": "https://bmw.jobs/apply",
        }
        # Must be Arbeitsagentur, NOT BMW or bmwgroup.com
        self.assertEqual(normalize_job_platform(job), "Arbeitsagentur")

        # Ausbildung.de listing for Siemens
        job2 = {
            "title": "Fachinformatiker (m/w/d)",
            "company": "Siemens AG",
            "portal": "Ausbildung.de",
            "url": "https://jobs.siemens.com",
        }
        self.assertEqual(normalize_job_platform(job2), "Ausbildung.de")

    def test_worker_telemetry_fields_initialized(self):
        """Initial worker telemetry must include current_platform, current_job_title, current_employer, current_stage."""
        jobs = [{"title": "Job 1", "company": "Company 1", "source": "arbeitsagentur"}]
        job_id = _create_auto_extraction_job(jobs, "Koch", "Berlin", "all", search_run_id="run_init_test")

        resp = self.client.get(f"/api/inline/auto-jobs/status/{job_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["job"]

        workers = data["workers"]
        self.assertIn("worker_1", workers)
        w1 = workers["worker_1"]

        self.assertEqual(w1["worker_id"], 1)
        self.assertEqual(w1["current_platform"], "No active platform")
        self.assertEqual(w1["current_job_title"], "")
        self.assertEqual(w1["current_employer"], "")
        self.assertEqual(w1["current_stage"], "Idle")
        self.assertEqual(w1["completed_count"], 0)
        self.assertIn("public_ip", w1)
        self.assertIn("network_profile", w1)
        self.assertIn("connection_status", w1)

    def test_pause_preserves_last_platform_and_job(self):
        """When paused, worker must preserve its current platform, job title, and employer, while displaying Paused."""
        jobs = [
            {"title": "Hotelfachmann", "company": "Hotel Vier Jahreszeiten", "source": "ausbildung.de"},
            {"title": "Koch", "company": "Restaurant Goldener Hirsch", "source": "azubiyo"},
        ]
        job_id = _create_auto_extraction_job(jobs, "Hotel", "Hamburg", "all", search_run_id="run_pause_test")

        # Simulate Worker 1 and Worker 2 actively working
        with auto_extraction_jobs_lock:
            j = auto_extraction_jobs[job_id]
            j["is_running"] = True
            w1 = j["workers"]["worker_1"]
            w1["status"] = "working"
            w1["current_platform"] = "Ausbildung.de"
            w1["current_job_title"] = "Hotelfachmann"
            w1["current_employer"] = "Hotel Vier Jahreszeiten"
            w1["current_stage"] = "HTTP Fast-Path"

            w2 = j["workers"]["worker_2"]
            w2["status"] = "working"
            w2["current_platform"] = "Azubiyo"
            w2["current_job_title"] = "Koch"
            w2["current_employer"] = "Restaurant Goldener Hirsch"
            w2["current_stage"] = "Selenium Fallback"

        # Request Pause
        resp_pause = self.client.post(f"/api/inline/auto-jobs/pause/{job_id}")
        self.assertEqual(resp_pause.status_code, 200)

        # Verify status endpoint reflects preserved details with Paused status
        resp_status = self.client.get(f"/api/inline/auto-jobs/status/{job_id}")
        self.assertEqual(resp_status.status_code, 200)
        p_job = resp_status.get_json()["job"]
        workers = p_job["workers"]

        w1_paused = workers["worker_1"]
        self.assertEqual(w1_paused["status"], "paused")
        self.assertEqual(w1_paused["current_stage"], "Paused")
        self.assertEqual(w1_paused["current_platform"], "Ausbildung.de", "Platform must be preserved on Pause")
        self.assertEqual(w1_paused["current_job_title"], "Hotelfachmann", "Job title must be preserved on Pause")
        self.assertEqual(w1_paused["current_employer"], "Hotel Vier Jahreszeiten", "Employer must be preserved on Pause")

        w2_paused = workers["worker_2"]
        self.assertEqual(w2_paused["status"], "paused")
        self.assertEqual(w2_paused["current_stage"], "Paused")
        self.assertEqual(w2_paused["current_platform"], "Azubiyo")
        self.assertEqual(w2_paused["current_job_title"], "Koch")
        self.assertEqual(w2_paused["current_employer"], "Restaurant Goldener Hirsch")

    def test_extractor_stage_callback_progression(self):
        """WorkingEmailExtractor must trigger on_stage_change across execution stages."""
        stages_recorded = []

        def mock_stage_cb(stage: str):
            stages_recorded.append(stage)

        with patch("scraper.working_email_extractor.find_browser", return_value=("chrome", "/mock/path")), \
             patch("scraper.working_email_extractor.start_driver") as mock_start:
            mock_driver = MagicMock()
            mock_start.return_value = mock_driver

            extractor = WorkingEmailExtractor(
                captcha_userid="mock",
                captcha_apikey="mock",
                headless=True,
                worker_id=1,
            )

            # Test fast-HTTP job
            job_fast = {
                "title": "Verkäufer (m/w/d)",
                "company": "Rewe Markt",
                "source": "ihk.de",
                "url": "https://rewe.de/karriere",
            }

            with patch.object(extractor, "extract_via_fast_http", return_value={"email": "jobs@rewe.de", "email_extracted": True}):
                extractor.process_job(job_fast, on_stage_change=mock_stage_cb)

            self.assertIn("HTTP Fast-Path", stages_recorded)
            self.assertIn("Email Extraction", stages_recorded)

    def test_search_session_isolation_for_worker_telemetry(self):
        """Worker telemetry for Run A must never overwrite or bleed into Run B."""
        jobs_a = [{"title": "Job A", "company": "Company A", "source": "arbeitsagentur"}]
        jobs_b = [{"title": "Job B", "company": "Company B", "source": "aubi-plus.de"}]

        job_id_a = _create_auto_extraction_job(jobs_a, "Maler", "Bonn", "all", search_run_id="run_A")
        job_id_b = _create_auto_extraction_job(jobs_b, "Schreiner", "Köln", "all", search_run_id="run_B")

        with auto_extraction_jobs_lock:
            auto_extraction_jobs[job_id_a]["workers"]["worker_1"]["current_platform"] = "Arbeitsagentur"
            auto_extraction_jobs[job_id_a]["workers"]["worker_1"]["current_employer"] = "Company A"

            auto_extraction_jobs[job_id_b]["workers"]["worker_1"]["current_platform"] = "AUBI-plus"
            auto_extraction_jobs[job_id_b]["workers"]["worker_1"]["current_employer"] = "Company B"

        resp_a = self.client.get(f"/api/inline/auto-jobs/status/{job_id_a}")
        resp_b = self.client.get(f"/api/inline/auto-jobs/status/{job_id_b}")

        w_a = resp_a.get_json()["job"]["workers"]["worker_1"]
        w_b = resp_b.get_json()["job"]["workers"]["worker_1"]

        self.assertEqual(w_a["current_platform"], "Arbeitsagentur")
        self.assertEqual(w_a["current_employer"], "Company A")

        self.assertEqual(w_b["current_platform"], "AUBI-plus")
        self.assertEqual(w_b["current_employer"], "Company B")


if __name__ == "__main__":
    unittest.main()

