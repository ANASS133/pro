import json
import io
import unittest
from pathlib import Path
import pandas as pd

EXPECTED_EXCEL_COLUMNS = [
    "title", "company", "arbeitsgeber", "city", "location", "start_date",
    "email", "email_type", "phone", "contact_person", "anrede",
    "job_listing_url", "employer_website", "direct_application_url",
    "form_link", "application_method", "source", "extraction_status",
]

from app import (
    app,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
    auto_extraction_status,
    status_lock,
    _sync_progress_into_job,
)


class StopAndDownloadTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.job_id = "test-stop-download-12345"
        self.progress_dir = Path("data") / "progress"
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        self.progress_file = self.progress_dir / "auto_extraction_progress.json"

        # Mock jobs data
        self.initial_jobs = [
            {
                "title": "Azubi Hotelfachmann",
                "company": "Grand Hotel Berlin",
                "location": "Berlin",
                "url": "https://grandhotel.test/job/1",
                "email": None,
                "email_extracted": False,
                "has_form": False,
            },
            {
                "title": "Koch Ausbildung",
                "company": "Gasthof Alpenblick",
                "location": "München",
                "url": "https://alpenblick.test/job/2",
                "email": None,
                "email_extracted": False,
                "has_form": False,
            },
        ]

        with auto_extraction_jobs_lock:
            auto_extraction_jobs[self.job_id] = {
                "job_id": self.job_id,
                "keyword": "Hotelfachmann",
                "location": "Berlin",
                "published_since": "all",
                "is_running": True,
                "stop_requested": False,
                "paused": False,
                "continue_requested": False,
                "current_index": 0,
                "total_jobs": 2,
                "emails_found": 0,
                "recruitment_emails": 0,
                "forms_found": 0,
                "external_links": 0,
                "fast_path_hits": 0,
                "selenium_fallbacks": 0,
                "rate_limited_count": 0,
                "captchas_solved": 0,
                "failed": 0,
                "avg_time_per_job": 0.0,
                "estimated_remaining_seconds": 0.0,
                "active_workers": 4,
                "status_label": "Running",
                "workers": {},
                "activity_feed": [],
                "jobs": [dict(j) for j in self.initial_jobs],
                "last_error": "",
                "created_at": "9999-12-31T23:59:58",
                "updated_at": "9999-12-31T23:59:59",
                "finished_at": "",
            }

    def tearDown(self):
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(self.job_id, None)
        if self.progress_file.exists():
            self.progress_file.unlink(missing_ok=True)

    def test_sync_progress_into_job(self):
        # Write progress with extracted email to disk
        progress_data = {
            "last_index": 0,
            "total": 2,
            "stats": {"emails_found": 1},
            "jobs": [
                {
                    "title": "Azubi Hotelfachmann",
                    "company": "Grand Hotel Berlin",
                    "email": "karriere@grandhotel.test",
                    "email_extracted": True,
                    "email_type": "recruitment",
                    "has_form": True,
                    "form_link": "https://grandhotel.test/apply",
                    "direct_application_url": "https://grandhotel.test/apply",
                    "application_method": "both",
                    "extraction_status": "success",
                    "extraction_method": "fast_http",
                }
            ],
        }
        self.progress_file.write_text(json.dumps(progress_data), encoding="utf-8")

        # Sync into job
        with auto_extraction_jobs_lock:
            _sync_progress_into_job(self.job_id)
            job = auto_extraction_jobs[self.job_id]
            first_job = job["jobs"][0]
            self.assertEqual(first_job.get("email"), "karriere@grandhotel.test")
            self.assertTrue(first_job.get("has_form"))
            self.assertEqual(first_job.get("application_method"), "both")

    def test_stop_endpoint_stops_and_syncs(self):
        # Progress on disk with newly extracted email
        progress_data = {
            "last_index": 0,
            "total": 2,
            "stats": {"emails_found": 1},
            "jobs": [
                {
                    "title": "Azubi Hotelfachmann",
                    "company": "Grand Hotel Berlin",
                    "email": "info@grandhotel.test",
                    "email_extracted": True,
                    "email_type": "official",
                    "has_form": False,
                    "application_method": "email",
                    "extraction_status": "success",
                }
            ],
        }
        self.progress_file.write_text(json.dumps(progress_data), encoding="utf-8")

        resp = self.client.post(f"/api/inline/auto-jobs/stop/{self.job_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs[self.job_id]
            self.assertFalse(job.get("is_running"))
            self.assertTrue(job.get("stop_requested"))
            # Verified email was synced from progress
            self.assertEqual(job["jobs"][0].get("email"), "info@grandhotel.test")

    def test_download_endpoint_returns_excel_with_extracted_data(self):
        # Set up job with an extracted email
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[self.job_id]["jobs"][0]["email"] = "bewerbung@grandhotel.test"
            auto_extraction_jobs[self.job_id]["jobs"][0]["application_method"] = "email"

        resp = self.client.get(f"/api/inline/auto-jobs/download/{self.job_id}?filter=all")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", resp.content_type)

        # Parse Excel to verify content
        excel_bytes = io.BytesIO(resp.data)
        df = pd.read_excel(excel_bytes)
        self.assertGreaterEqual(len(df), 1)
        self.assertEqual(list(df.columns), EXPECTED_EXCEL_COLUMNS)
        self.assertIn("email", df.columns)
        emails = df["email"].dropna().tolist()
        self.assertIn("bewerbung@grandhotel.test", emails)

    def test_active_job_discovery_endpoint(self):
        # With running job (has highest timestamp)
        resp = self.client.get("/api/inline/auto-jobs/active")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("has_active"))
        self.assertEqual(data.get("job_id"), self.job_id)
        self.assertEqual(data.get("status"), "running")

        # After stop
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[self.job_id]["is_running"] = False
            auto_extraction_jobs[self.job_id]["updated_at"] = "9999-12-31T23:59:59"
        resp = self.client.get("/api/inline/auto-jobs/active")
        data = resp.get_json()
        self.assertTrue(data.get("has_active"))
        self.assertEqual(data.get("job_id"), self.job_id)
        self.assertEqual(data.get("status"), "idle")

    def test_jobs_list_endpoint(self):
        resp = self.client.get(f"/api/inline/auto-jobs/jobs/{self.job_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(len(data.get("jobs", [])), 2)
        self.assertEqual(data["jobs"][0]["company"], "Grand Hotel Berlin")


if __name__ == "__main__":
    unittest.main()
