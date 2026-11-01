import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as app_module
from app import (
    app,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
    _recover_auto_job_from_progress,
)


class AutoExtractionRecoveryTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_job_id = "2a5baf14-6136-4a97-a3ba-f326bbd71bbf"

        self._orig_cwd = Path.cwd()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._tmp_dir.name)

        progress_dir = self.temp_root / "data" / "progress"
        export_dir = self.temp_root / "data" / "auto_extraction_exports"
        progress_dir.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)

        fixture_jobs = [
            {
                "title": "Fachinformatiker Anwendungsentwicklung (m/w/d)",
                "company": "Beispiel IT GmbH",
                "location": "Berlin",
                "email": "bewerbung@beispiel-it.test",
                "url": "https://beispiel-it.test/jobs/1",
                "source": "arbeitsagentur",
            },
            {
                "title": "Junior Softwareentwickler (m/w/d)",
                "company": "Nord Digital AG",
                "location": "Hamburg",
                "email": "",
                "url": "https://nord-digital.test/jobs/2",
                "source": "arbeitsagentur",
            },
        ]

        progress_payload = {
            "timestamp": "2026-10-31T12:00:00",
            "last_index": 0,
            "total": 2,
            "stats": {
                "total_processed": 1,
                "emails_found": 1,
                "captchas_solved": 0,
                "failed": 0,
            },
            "jobs": fixture_jobs,
        }
        (progress_dir / "auto_extraction_progress.json").write_text(
            json.dumps(progress_payload), encoding="utf-8"
        )

        cache_payload = {
            "jobs": fixture_jobs,
            "keyword": "Fachinformatiker",
            "location": "Berlin",
            "published_since": "all",
        }
        (self.temp_root / "data" / "search_cache.json").write_text(
            json.dumps(cache_payload), encoding="utf-8"
        )

        with auto_extraction_jobs_lock:
            self._saved_jobs = dict(auto_extraction_jobs)

        self._patches = [
            patch.object(
                app_module,
                "AUTO_JOBS_STORE_PATH",
                progress_dir / "auto_extraction_jobs.json",
            ),
            patch.object(
                app_module,
                "SEARCH_CACHE_FILE",
                self.temp_root / "data" / "search_cache.json",
            ),
            patch.object(
                app_module,
                "AUTO_EXTRACTION_EXPORT_DIR",
                export_dir,
            ),
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
        self._tmp_dir.cleanup()

    def test_recover_auto_job_from_progress(self):
        # Clear in-memory dict
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(self.test_job_id, None)

        recovered = _recover_auto_job_from_progress(self.test_job_id)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["job_id"], self.test_job_id)
        self.assertGreaterEqual(recovered["emails_found"], 1)
        self.assertGreater(recovered["total_jobs"], 0)
        self.assertTrue(recovered["paused"])
        self.assertFalse(recovered["is_running"])

    def test_status_endpoint_recovers_job(self):
        # Clear in-memory dict to simulate server restart
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(self.test_job_id, None)

        response = self.client.get(f"/api/inline/auto-jobs/status/{self.test_job_id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        job = data.get("job")
        self.assertIsNotNone(job)
        self.assertEqual(job.get("job_id"), self.test_job_id)
        self.assertGreaterEqual(job.get("emails_found"), 1)
        self.assertGreater(job.get("total_jobs"), 0)
        self.assertGreaterEqual(job.get("current_index"), 1)
        self.assertTrue(job.get("paused"))

    def test_download_endpoint_with_recovered_job(self):
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(self.test_job_id, None)

        response = self.client.get(f"/api/inline/auto-jobs/download/{self.test_job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response.content_type)
        response.close()

    def test_stop_endpoint_with_recovered_job(self):
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(self.test_job_id, None)

        response = self.client.post(f"/api/inline/auto-jobs/stop/{self.test_job_id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))


if __name__ == "__main__":
    unittest.main()
