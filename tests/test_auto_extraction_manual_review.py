import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as app_module


class _FakeExtractor:
    active_workers = set()
    overlap = False
    lock = threading.Lock()

    def __init__(self, *args, worker_id=1, **kwargs):
        self.worker_id = worker_id
        self.stats = {"captchas_solved": 0}

    def process_job(self, job, profession_keyword=""):
        with self.lock:
            if self.worker_id in self.active_workers:
                self.__class__.overlap = True
            self.active_workers.add(self.worker_id)
        try:
            time.sleep(0.01)
            result = dict(job)
            if 80 <= result["id"] < 84:
                result.update(
                    extraction_status="manual_required",
                    manual_review_required=True,
                    manual_review_reason="Human verification required",
                )
            else:
                result.update(
                    extraction_status="completed",
                    email=f"job{result['id']}@example.test",
                    email_extracted=True,
                )
            return result
        finally:
            with self.lock:
                self.active_workers.remove(self.worker_id)

    def save_progress(self, *args, **kwargs):
        return None

    def close(self):
        return None


class AutoExtractionManualReviewRegressionTest(unittest.TestCase):
    def setUp(self):
        self.saved_jobs = dict(app_module.auto_extraction_jobs)
        self.saved_runs = dict(app_module.search_runs)
        app_module.auto_extraction_jobs.clear()
        app_module.search_runs.clear()
        _FakeExtractor.active_workers.clear()
        _FakeExtractor.overlap = False
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.path_patches = [
            patch.object(app_module, "AUTO_JOBS_STORE_PATH", root / "jobs.json"),
            patch.object(app_module, "SEARCH_RUNS_STORE_PATH", root / "runs.json"),
            patch.object(app_module, "PROGRESS_DIR", root / "progress"),
        ]
        for item in self.path_patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.path_patches):
            item.stop()
        app_module.auto_extraction_jobs.clear()
        app_module.auto_extraction_jobs.update(self.saved_jobs)
        app_module.search_runs.clear()
        app_module.search_runs.update(self.saved_runs)
        self.tempdir.cleanup()

    def test_manual_jobs_checkpoint_and_release_slots_while_queue_continues(self):
        jobs = [
            {"id": i, "title": f"Job {i}", "company": f"Company {i}", "url": f"https://example.test/{i}"}
            for i in range(90)
        ]
        job_id = app_module._create_auto_extraction_job(jobs, "Nurse", "Berlin", "all")
        profiles = {
            i: SimpleNamespace(
                worker_id=i,
                profile_name=f"Worker-{i}",
                connection_status="connected",
                allow_direct_fallback=True,
                public_ip="127.0.0.1",
            )
            for i in range(1, 5)
        }

        with patch.object(app_module, "WorkingEmailExtractor", _FakeExtractor), \
             patch("services.worker_network_router.load_worker_network_profiles", return_value=profiles), \
             patch("services.worker_network_router.verify_all_worker_connections", return_value=profiles):
            app_module._run_auto_extraction_job(job_id)

        result = app_module.auto_extraction_jobs[job_id]
        self.assertFalse(_FakeExtractor.overlap, "a worker slot was assigned to concurrent attempts")
        self.assertEqual(result["current_index"], 90)
        self.assertEqual(len(result["manual_review_queue"]), 4)
        self.assertEqual(result["status_label"], "Completed with Manual Review")
        self.assertEqual([row["id"] for row in result["jobs"]], list(range(90)))
        for row in result["jobs"][80:84]:
            self.assertEqual(row["extraction_status"], "manual_required")
            self.assertFalse(row["_extracted"])
            self.assertFalse(row["extracted"])
        for row in result["jobs"][84:]:
            self.assertEqual(row["extraction_status"], "completed")
            self.assertTrue(row["_extracted"])
            self.assertIn("@example.test", row["email"])

        result["is_running"] = True
        result["last_progress_at"] = (datetime.now() - timedelta(seconds=61)).isoformat()
        status = app_module.app.test_client().get(f"/api/inline/auto-jobs/status/{job_id}").get_json()["job"]
        self.assertTrue(status["stalled"])
        self.assertEqual(status["status_label"], "Stalled")
        self.assertEqual(status["estimated_remaining_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
