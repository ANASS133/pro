import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as app_module
from app import (
    app,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
    auto_extraction_threads,
    auto_extraction_threads_lock,
    _create_auto_extraction_job,
    _run_auto_extraction_job,
    _is_job_finished,
    _recover_auto_job_from_progress,
)


class AutoExtractionPauseResumeTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self._orig_cwd = Path.cwd()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._tmp_dir.name)

        self.progress_dir = self.temp_root / "data" / "progress"
        self.export_dir = self.temp_root / "data" / "exports"
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

        with auto_extraction_jobs_lock:
            self._saved_jobs = dict(auto_extraction_jobs)
            auto_extraction_jobs.clear()

        self._patches = [
            patch.object(app_module, "PROGRESS_DIR", self.progress_dir),
            patch.object(app_module, "AUTO_JOBS_STORE_PATH", self.progress_dir / "auto_extraction_jobs.json"),
            patch.object(app_module, "SEARCH_RUNS_STORE_PATH", self.progress_dir / "search_runs.json"),
            patch.object(app_module, "SEARCH_CACHE_FILE", self.temp_root / "data" / "search_cache.json"),
            patch.object(app_module, "DOWNLOAD_EXPORT_DIR", self.export_dir),
        ]
        for p in self._patches:
            p.start()
        os.chdir(self.temp_root)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        for p in reversed(self._patches):
            p.stop()
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.clear()
            auto_extraction_jobs.update(self._saved_jobs)
        with auto_extraction_threads_lock:
            auto_extraction_threads.clear()
        self._tmp_dir.cleanup()

    def _generate_mock_jobs(self, count=963):
        return [
            {
                "title": f"Job Title {i}",
                "company": f"Company {i}",
                "location": "Berlin",
                "url": f"https://example.com/jobs/{i}",
                "source": "arbeitsagentur",
            }
            for i in range(count)
        ]

    def test_reproduction_pause_at_114_of_963_and_resume(self):
        """
        Exact Reproduction:
        Create an extraction task containing 963 jobs. Pause after 114 are processed, then resume.
        - Original total remains 963.
        - Processed count remains 114 until additional jobs finish.
        - Previously found emails and forms remain intact.
        - Remaining 849 jobs are restored correctly.
        - Workers continue processing.
        - Completion occurs only after all 963 jobs reach valid terminal states.
        """
        mock_jobs = self._generate_mock_jobs(963)
        job_id = _create_auto_extraction_job(mock_jobs, "Software", "Berlin", "all", search_run_id="run_963")

        # Simulate 114 jobs processed before pausing
        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs[job_id]
            for i in range(114):
                job["jobs"][i]["_extracted"] = True
                job["jobs"][i]["extracted"] = True
                job["jobs"][i]["email_extracted"] = True
                job["jobs"][i]["extraction_status"] = "completed"
                if i % 2 == 0:
                    job["jobs"][i]["email"] = f"kontakt{i}@company{i}.de"
                if i % 3 == 0:
                    job["jobs"][i]["has_form"] = True
                    job["jobs"][i]["form_link"] = f"https://example.com/apply/{i}"

            job["current_index"] = 114
            job["total_jobs"] = 963
            job["emails_found"] = 57
            job["forms_found"] = 38
            job["is_running"] = True
            job["status_label"] = "Running"

        # 1. Trigger Pause
        resp_pause = self.client.post(f"/api/inline/auto-jobs/pause/{job_id}")
        self.assertEqual(resp_pause.status_code, 200)

        # Verify state immediately after pause
        resp_status_paused = self.client.get(f"/api/inline/auto-jobs/status/{job_id}")
        self.assertEqual(resp_status_paused.status_code, 200)
        pdata = resp_status_paused.get_json()["job"]

        self.assertEqual(pdata["total_jobs"], 963, "Total jobs must remain 963, never replaced by 114")
        self.assertEqual(pdata["processed_jobs"], 114)
        self.assertEqual(pdata["pending_jobs"], 849)
        self.assertTrue(pdata["paused"])
        self.assertFalse(pdata["is_running"])
        self.assertEqual(pdata["status_label"], "Paused")
        self.assertEqual(pdata["emails_found"], 57)
        self.assertEqual(pdata["forms_found"], 38)
        self.assertEqual(pdata["finished_at"], "", "Must not have finished_at timestamp when paused")

        # 2. Trigger Resume/Continue
        # Mock WorkingEmailExtractor so worker loop processes remaining jobs safely and quickly
        def mock_process_job(job_record, profession_keyword=""):
            res = dict(job_record)
            res["email"] = f"resumed_{res.get('title')}@test.de"
            res["email_extracted"] = True
            res["extraction_status"] = "completed"
            res["_extracted"] = True
            return res

        with patch("app.WorkingEmailExtractor") as MockExtractor, \
             patch("services.worker_network_router.load_worker_network_profiles") as mock_profiles, \
             patch("services.worker_network_router.verify_all_worker_connections"):
            mock_inst = MagicMock()
            mock_inst.process_job.side_effect = mock_process_job
            MockExtractor.return_value = mock_inst

            mock_prof_obj = MagicMock()
            mock_prof_obj.connection_status = "active"
            mock_prof_obj.profile_name = "MockNet"
            mock_prof_obj.public_ip = "1.2.3.4"
            mock_prof_obj.allow_direct_fallback = True
            mock_profiles.return_value = {w: mock_prof_obj for w in range(1, 5)}

            resp_continue = self.client.post(f"/api/inline/auto-jobs/continue/{job_id}")
            self.assertEqual(resp_continue.status_code, 200)

            # Wait briefly for worker thread to finish execution
            time.sleep(0.5)
            with auto_extraction_threads_lock:
                th = auto_extraction_threads.get(job_id)
                if th and th.is_alive():
                    th.join(timeout=3.0)

        # 3. Verify state after full resumption
        resp_status_after = self.client.get(f"/api/inline/auto-jobs/status/{job_id}")
        self.assertEqual(resp_status_after.status_code, 200)
        adata = resp_status_after.get_json()["job"]

        self.assertEqual(adata["total_jobs"], 963)
        self.assertEqual(adata["processed_jobs"], 963)
        self.assertEqual(adata["pending_jobs"], 0)
        self.assertFalse(adata["paused"])
        self.assertFalse(adata["is_running"])
        self.assertEqual(adata["status_label"], "Completed")
        self.assertNotEqual(adata["finished_at"], "")
        self.assertGreater(adata["emails_found"], 57)

    def test_pause_resume_idempotency_and_duplicate_clicks(self):
        """Verifies Pause and Resume are idempotent against repeated button clicks."""
        mock_jobs = self._generate_mock_jobs(50)
        job_id = _create_auto_extraction_job(mock_jobs, "Test", "Hamburg", "all")

        # Multiple pause calls
        r1 = self.client.post(f"/api/inline/auto-jobs/pause/{job_id}")
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post(f"/api/inline/auto-jobs/pause/{job_id}")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.get_json()["success"])

        # Multiple resume calls
        with patch("app.WorkingEmailExtractor"), \
             patch("services.worker_network_router.load_worker_network_profiles") as mock_profiles, \
             patch("services.worker_network_router.verify_all_worker_connections"):
            mock_prof_obj = MagicMock()
            mock_prof_obj.connection_status = "active"
            mock_prof_obj.profile_name = "Direct"
            mock_prof_obj.public_ip = "1.1.1.1"
            mock_prof_obj.allow_direct_fallback = True
            mock_profiles.return_value = {w: mock_prof_obj for w in range(1, 5)}

            c1 = self.client.post(f"/api/inline/auto-jobs/continue/{job_id}")
            self.assertEqual(c1.status_code, 200)
            c2 = self.client.post(f"/api/inline/auto-jobs/continue/{job_id}")
            self.assertEqual(c2.status_code, 200)

            time.sleep(0.3)
            with auto_extraction_threads_lock:
                th = auto_extraction_threads.get(job_id)
                if th and th.is_alive():
                    th.join(timeout=3.0)

    def test_disk_recovery_preserves_paused_state_and_all_records(self):
        """Verifies that simulating a page refresh / disk recovery preserves all 963 records and paused state."""
        mock_jobs = self._generate_mock_jobs(963)
        job_id = _create_auto_extraction_job(mock_jobs, "Developer", "München", "all")

        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs[job_id]
            for i in range(114):
                job["jobs"][i]["_extracted"] = True
                job["jobs"][i]["email"] = f"dev{i}@muc.de"
            job["current_index"] = 114
            job["emails_found"] = 114
            job["forms_found"] = 10

        # Pause and save to disk
        self.client.post(f"/api/inline/auto-jobs/pause/{job_id}")

        # Clear in-memory dict to simulate restart / refresh
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(job_id, None)

        # Recover from disk
        recovered = _recover_auto_job_from_progress(job_id)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["total_jobs"], 963, "Must not truncate total to 114 on disk recovery")
        self.assertEqual(recovered["current_index"], 114)
        self.assertEqual(recovered["emails_found"], 114)
        self.assertEqual(recovered["forms_found"], 10)
        self.assertTrue(recovered["paused"])
        self.assertFalse(recovered["is_running"])
        self.assertEqual(recovered["finished_at"], "")

    def test_prevent_duplicate_extraction_when_task_paused(self):
        """Starting a new extraction for a search that has a paused task restores existing task ID."""
        mock_jobs = self._generate_mock_jobs(20)
        job_id = _create_auto_extraction_job(mock_jobs, "Admin", "Köln", "all", search_run_id="run_paused_test")

        self.client.post(f"/api/inline/auto-jobs/pause/{job_id}")

        # Frontend clicks 'Start Auto-Extraction' again
        resp = self.client.post(
            "/api/inline/auto-jobs/start",
            json={"jobs": mock_jobs, "search_run_id": "run_paused_test", "keyword": "Admin"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["job_id"], job_id, "Must return existing paused job ID rather than spawning duplicate")

    def test_raw_scraped_jobs_not_treated_as_finished(self):
        """Raw jobs from portal scraper have email_extracted=False; must not be treated as finished."""
        from app import _is_job_finished

        # Raw job listing fresh from scraper
        raw_job = {
            "title": "Hotelfachmann (m/w/d)",
            "company": "Grand Hotel",
            "email_extracted": False,
            "email": "",
            "has_form": False,
            "extraction_status": None,
        }
        self.assertFalse(_is_job_finished(raw_job), "Raw job with email_extracted=False must not be considered finished")

        # Finished job with email
        finished_with_email = dict(raw_job)
        finished_with_email["email"] = "karriere@grandhotel.de"
        finished_with_email["email_extracted"] = True
        self.assertTrue(_is_job_finished(finished_with_email))

        # Finished job marked status completed without email
        finished_no_email = dict(raw_job)
        finished_no_email["extraction_status"] = "completed"
        self.assertTrue(_is_job_finished(finished_no_email))

        # Finished job with form link
        finished_form = dict(raw_job)
        finished_form["form_link"] = "https://grandhotel.de/apply"
        finished_form["has_form"] = True
        self.assertTrue(_is_job_finished(finished_form))


if __name__ == "__main__":
    unittest.main()

