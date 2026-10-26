import tempfile
import unittest
from pathlib import Path
from services.job_store import JobStore


class JobStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_jobs.db"
        self.store = JobStore(db_path=self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_save_and_get_job(self):
        job = self.store.save_job(
            job_id="job-123",
            job_type="scrape",
            phase="running",
            progress=5,
            total=10,
            payload={"keyword": "python"},
        )
        self.assertIsNotNone(job)
        self.assertEqual(job["job_id"], "job-123")
        self.assertEqual(job["progress"], 5)
        self.assertEqual(job["total"], 10)
        self.assertTrue(job["is_running"])
        self.assertEqual(job["payload"], {"keyword": "python"})

    def test_update_job(self):
        self.store.save_job(job_id="job-456", job_type="email_send", progress=0, total=50)
        updated = self.store.update_job("job-456", progress=25, phase="sending")
        self.assertEqual(updated["progress"], 25)
        self.assertEqual(updated["phase"], "sending")

    def test_list_and_delete_jobs(self):
        self.store.save_job(job_id="j1", job_type="type_a")
        self.store.save_job(job_id="j2", job_type="type_b")
        jobs_a = self.store.list_jobs(job_type="type_a")
        self.assertEqual(len(jobs_a), 1)
        self.assertEqual(jobs_a[0]["job_id"], "j1")

        deleted = self.store.delete_job("j1")
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get_job("j1"))

    def test_reset_stale_jobs(self):
        self.store.save_job(job_id="j_stale", job_type="scrape", is_running=True)
        count = self.store.reset_stale_jobs()
        self.assertEqual(count, 1)
        job = self.store.get_job("j_stale")
        self.assertFalse(job["is_running"])
        self.assertEqual(job["phase"], "interrupted")


if __name__ == "__main__":
    unittest.main()
