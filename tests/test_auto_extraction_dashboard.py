import unittest
from unittest.mock import patch, MagicMock
import json
import time

from app import (
    app,
    _create_auto_extraction_job,
    _recover_auto_job_from_progress,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
)


class AutoExtractionDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.clear()

    def test_job_structure_contains_all_dashboard_metrics(self):
        dummy_jobs = [{"title": f"Dev {i}", "company": f"Corp {i}", "url": f"https://corp{i}.test"} for i in range(10)]
        job_id = _create_auto_extraction_job(
            jobs=dummy_jobs,
            keyword="Softwareentwickler",
            location="Berlin",
            published_since="all",
        )

        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs[job_id]

        # Check primary & secondary metric fields
        self.assertEqual(job["job_id"], job_id)
        self.assertEqual(job["total_jobs"], 10)
        self.assertEqual(job["current_index"], 0)
        self.assertEqual(job["emails_found"], 0)
        self.assertEqual(job["recruitment_emails"], 0)
        self.assertEqual(job["forms_found"], 0)
        self.assertEqual(job["external_links"], 0)
        self.assertEqual(job["fast_path_hits"], 0)
        self.assertEqual(job["selenium_fallbacks"], 0)
        self.assertEqual(job["rate_limited_count"], 0)
        self.assertEqual(job["failed"], 0)
        self.assertEqual(job["captchas_solved"], 0)
        self.assertEqual(job["avg_time_per_job"], 0.0)
        self.assertEqual(job["estimated_remaining_seconds"], 0.0)
        self.assertEqual(job["status_label"], "Idle")
        self.assertEqual(job["active_workers"], 0)

        # Check 4 workers initialization
        self.assertIn("workers", job)
        self.assertEqual(len(job["workers"]), 4)
        for w_id in range(1, 5):
            w_key = f"worker_{w_id}"
            self.assertIn(w_key, job["workers"])
            self.assertEqual(job["workers"][w_key]["id"], f"Worker {w_id}")
            self.assertEqual(job["workers"][w_key]["status"], "idle")
            self.assertEqual(job["workers"][w_key]["completed_count"], 0)

        # Check activity feed
        self.assertIn("activity_feed", job)
        self.assertIsInstance(job["activity_feed"], list)

    def test_status_endpoint_returns_all_dashboard_fields(self):
        dummy_jobs = [{"title": f"Nurse {i}", "company": f"Hospital {i}", "url": f"https://hosp{i}.test"} for i in range(25)]
        job_id = _create_auto_extraction_job(
            jobs=dummy_jobs,
            keyword="Pflegefachkraft",
            location="München",
            published_since="all",
        )

        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs[job_id]
            # Simulate running job with extraction progress
            job["is_running"] = True
            job["current_index"] = 15
            job["emails_found"] = 12
            job["recruitment_emails"] = 9
            job["forms_found"] = 4
            job["external_links"] = 3
            job["fast_path_hits"] = 11
            job["selenium_fallbacks"] = 4
            job["rate_limited_count"] = 1
            job["avg_time_per_job"] = 1.6
            job["estimated_remaining_seconds"] = 16.0
            job["active_workers"] = 4
            job["workers"]["worker_1"]["status"] = "Active"
            job["workers"]["worker_1"]["company"] = "Klinikum München"
            job["activity_feed"].append({
                "time": "12:00:00",
                "text": "Found direct email: karriere@klinikum.de",
                "type": "recruitment",
                "company": "Klinikum München",
            })

        response = self.client.get(f"/api/inline/auto-jobs/status/{job_id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertTrue(data.get("success"))
        j = data.get("job")
        self.assertIsNotNone(j)

        # Verify all metrics present in response
        self.assertEqual(j["current_index"], 15)
        self.assertEqual(j["total_jobs"], 25)
        self.assertEqual(j["processed_jobs"], 15)
        self.assertEqual(j["pending_jobs"], 10)
        self.assertEqual(j["emails_found"], 12)
        self.assertEqual(j["recruitment_emails"], 9)
        self.assertEqual(j["forms_found"], 4)
        self.assertEqual(j["external_links"], 3)
        self.assertEqual(j["fast_path_hits"], 11)
        self.assertEqual(j["selenium_fallbacks"], 4)
        self.assertEqual(j["rate_limited_count"], 1)
        self.assertEqual(j["avg_time_per_job"], 1.6)
        self.assertEqual(j["estimated_remaining_seconds"], 16.0)
        self.assertEqual(j["percentage"], 60.0)
        self.assertEqual(j["active_workers"], 4)

        # Verify workers and activity feed
        self.assertEqual(j["workers"]["worker_1"]["company"], "Klinikum München")
        self.assertGreaterEqual(len(j["activity_feed"]), 1)
        self.assertEqual(j["activity_feed"][-1]["company"], "Klinikum München")


if __name__ == "__main__":
    unittest.main()
