import json
import unittest
from pathlib import Path
from app import app, auto_extraction_jobs, auto_extraction_jobs_lock, _save_auto_extraction_jobs_to_disk


class TestDeletePreviousTasks(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_job_ids = []

    def tearDown(self):
        with auto_extraction_jobs_lock:
            for jid in self.created_job_ids:
                auto_extraction_jobs.pop(jid, None)
                p_file = Path("data") / "progress" / f"auto_extraction_progress_{jid}.json"
                if p_file.exists():
                    p_file.unlink()
            _save_auto_extraction_jobs_to_disk()

    def test_delete_single_previous_task(self):
        test_jid = "test_del_job_001"
        self.created_job_ids.append(test_jid)
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[test_jid] = {
                "job_id": test_jid,
                "keyword": "Test Koch",
                "location": "Berlin",
                "total_jobs": 10,
                "current_index": 10,
                "is_running": False,
                "status_label": "Completed",
            }
            _save_auto_extraction_jobs_to_disk()

        p_file = Path("data") / "progress" / f"auto_extraction_progress_{test_jid}.json"
        p_file.parent.mkdir(parents=True, exist_ok=True)
        p_file.write_text(json.dumps({"test": 123}), encoding="utf-8")
        self.assertTrue(p_file.exists())

        # Call delete endpoint
        resp = self.client.post(f"/api/inline/auto-jobs/delete/{test_jid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("job_id"), test_jid)

        # Verify task is deleted from memory
        with auto_extraction_jobs_lock:
            self.assertNotIn(test_jid, auto_extraction_jobs)

        # Verify progress file is unlinked
        self.assertFalse(p_file.exists())

    def test_delete_single_task_http_delete_method(self):
        test_jid = "test_del_job_002"
        self.created_job_ids.append(test_jid)
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[test_jid] = {
                "job_id": test_jid,
                "keyword": "Test Fachinformatiker",
                "total_jobs": 5,
                "current_index": 2,
                "is_running": False,
                "status_label": "Stopped",
            }

        resp = self.client.delete(f"/api/inline/auto-jobs/{test_jid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        with auto_extraction_jobs_lock:
            self.assertNotIn(test_jid, auto_extraction_jobs)

    def test_delete_nonexistent_task_returns_404(self):
        resp = self.client.post("/api/inline/auto-jobs/delete/non_existent_id_9999")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data.get("success"))

    def test_clear_all_auto_jobs(self):
        j1 = "test_clear_001"
        j2 = "test_clear_002"
        self.created_job_ids.extend([j1, j2])
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[j1] = {"job_id": j1, "is_running": False, "status_label": "Stopped"}
            auto_extraction_jobs[j2] = {"job_id": j2, "is_running": False, "status_label": "Completed"}

        resp = self.client.post("/api/inline/auto-jobs/clear?all=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(data.get("deleted_count", 0), 2)

        with auto_extraction_jobs_lock:
            self.assertNotIn(j1, auto_extraction_jobs)
            self.assertNotIn(j2, auto_extraction_jobs)


if __name__ == "__main__":
    unittest.main()

