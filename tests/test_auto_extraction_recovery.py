import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import (
    app,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
    _recover_auto_job_from_progress,
    _save_auto_extraction_jobs_to_disk,
    _load_auto_extraction_jobs_from_disk,
)


class AutoExtractionRecoveryTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_job_id = "2a5baf14-6136-4a97-a3ba-f326bbd71bbf"

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
        response = self.client.get(f"/api/inline/auto-jobs/download/{self.test_job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response.content_type)

    def test_stop_endpoint_with_recovered_job(self):
        response = self.client.post(f"/api/inline/auto-jobs/stop/{self.test_job_id}")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))


if __name__ == "__main__":
    unittest.main()
