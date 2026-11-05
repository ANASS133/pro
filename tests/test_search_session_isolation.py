"""
Regression and Isolation Tests for JobScout Search Session Isolation.

Validates:
1. Unique search_run_id assigned to every search.
2. Association of extraction tasks, progress, and queues with originating search_run_id.
3. Search B (3,718 jobs) displays only its own status while Search A (963 jobs) extraction runs.
4. Previous Tasks history accurately tracking historical jobs, status, and source search.
5. Preventing duplicate extraction tasks for the same search run.
6. Absolute isolation: No emails, forms, or counters mixed between Search A and Search B.
7. Independent task control: Pause, resume, and stop operations scoped to target task.
8. Download endpoints scoped to correct search run and extraction dataset.
"""

import io
import json
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

from app import (
    app,
    auto_extraction_jobs,
    auto_extraction_jobs_lock,
    search_runs,
    search_runs_lock,
    search_cache,
    _create_auto_extraction_job,
)


class TestSearchSessionIsolation(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.search_a_run_id = "run_test_search_a_123"
        self.search_b_run_id = "run_test_search_b_456"

        # Search A: 963 job listings
        self.jobs_a = [
            {
                "id": f"job_a_{i}",
                "title": f"Ausbildung Hotelfachmann #{i}",
                "company": f"Hotel A {i}",
                "city": "Berlin",
                "location": "Berlin",
                "email": "",
                "has_form": False,
                "application_method": "missing",
            }
            for i in range(963)
        ]

        # Search B: 3,718 job listings
        self.jobs_b = [
            {
                "id": f"job_b_{i}",
                "title": f"Ausbildung Fachinformatiker #{i}",
                "company": f"TechCorp B {i}",
                "city": "München",
                "location": "München",
                "email": "",
                "has_form": False,
                "application_method": "missing",
            }
            for i in range(3718)
        ]

    def tearDown(self):
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.clear()
        with search_runs_lock:
            search_runs.clear()

    def test_search_run_id_assignment_and_runs_cache(self):
        """Every search assigns or accepts a unique search_run_id and stores isolated records."""
        with patch("app._fetch_combined_jobs") as mock_fetch:
            mock_fetch.return_value = (self.jobs_a[:10], {"total": 10})
            resp = self.client.get(f"/api/search?keyword=Hotel&location=Berlin&search_run_id={self.search_a_run_id}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get("search_run_id"), self.search_a_run_id)
            self.assertEqual(data.get("total"), 10)

        with search_runs_lock:
            self.assertIn(self.search_a_run_id, search_runs)
            s_run = search_runs[self.search_a_run_id]
            self.assertEqual(s_run["keyword"], "Hotel")
            self.assertEqual(s_run["location"], "Berlin")
            self.assertEqual(len(s_run["jobs"]), 10)

    def test_two_searches_with_active_extraction_isolation(self):
        """
        Acceptance Test:
        - Search A returns 963 jobs and starts extraction.
        - Search B returns 3,718 jobs while Search A extraction is still running (158/963).
        - Search B displays only its own results and extraction status (has_active=False for Run B).
        - Search A extraction remains accessible in Previous Tasks.
        - No progress counters or records are mixed.
        """
        # 1. Register Search A (963 jobs)
        with search_runs_lock:
            search_runs[self.search_a_run_id] = {
                "search_run_id": self.search_a_run_id,
                "keyword": "Hotelfachmann",
                "location": "Berlin",
                "jobs": [dict(j) for j in self.jobs_a],
                "total": 963,
                "audit": {},
                "created_at": "2026-11-05T09:00:00",
                "auto_job_id": None,
            }

        # Start extraction on Search A
        job_a_id = _create_auto_extraction_job(
            self.jobs_a, "Hotelfachmann", "Berlin", "all", search_run_id=self.search_a_run_id
        )

        # Simulate Search A extraction progress: 158 of 963 processed, with some discovered emails
        with auto_extraction_jobs_lock:
            job_a = auto_extraction_jobs[job_a_id]
            job_a["is_running"] = True
            job_a["status_label"] = "Running"
            job_a["current_index"] = 158
            job_a["emails_found"] = 42
            job_a["forms_found"] = 18
            job_a["jobs"][0]["email"] = "karriere@hotel-a-0.test"
            job_a["jobs"][0]["email_extracted"] = True
            job_a["jobs"][0]["application_method"] = "email"

        # 2. User now runs Search B (3,718 jobs)
        with search_runs_lock:
            search_runs[self.search_b_run_id] = {
                "search_run_id": self.search_b_run_id,
                "keyword": "Fachinformatiker",
                "location": "München",
                "jobs": [dict(j) for j in self.jobs_b],
                "total": 3718,
                "audit": {},
                "created_at": "2026-11-05T09:05:00",
                "auto_job_id": None,
            }

        # Search B checks for active extraction jobs scoped to its search_run_id
        resp_b_active = self.client.get(f"/api/inline/auto-jobs/active?search_run_id={self.search_b_run_id}")
        self.assertEqual(resp_b_active.status_code, 200)
        data_b_active = resp_b_active.get_json()
        # Search B has NOT started extraction, so it must NOT inherit Search A's task!
        self.assertFalse(data_b_active.get("has_active"))
        self.assertIsNone(data_b_active.get("job_id"))

        # 3. Check that Search A extraction task is still running and intact
        resp_a_status = self.client.get(f"/api/inline/auto-jobs/status/{job_a_id}")
        self.assertEqual(resp_a_status.status_code, 200)
        data_a_status = resp_a_status.get_json()
        self.assertTrue(data_a_status.get("success"))
        j_data = data_a_status["job"]
        self.assertEqual(j_data.get("search_run_id"), self.search_a_run_id)
        self.assertEqual(j_data.get("total_jobs"), 963)
        self.assertEqual(j_data.get("processed_jobs"), 158)
        self.assertEqual(j_data.get("emails_found"), 42)
        self.assertEqual(j_data.get("forms_found"), 18)
        self.assertTrue(j_data.get("is_running"))

        # 4. Check Previous Tasks history endpoint
        resp_hist = self.client.get("/api/inline/auto-jobs/history")
        self.assertEqual(resp_hist.status_code, 200)
        hist_data = resp_hist.get_json()
        self.assertTrue(hist_data.get("success"))
        self.assertEqual(len(hist_data.get("tasks", [])), 1)

        task_entry = hist_data["tasks"][0]
        self.assertEqual(task_entry["job_id"], job_a_id)
        self.assertEqual(task_entry["search_run_id"], self.search_a_run_id)
        self.assertEqual(task_entry["keyword"], "Hotelfachmann")
        self.assertEqual(task_entry["location"], "Berlin")
        self.assertEqual(task_entry["processed_jobs"], 158)
        self.assertEqual(task_entry["total_jobs"], 963)
        self.assertEqual(task_entry["status_label"], "Running")

        # 5. Verify NO cross-session data contamination between Search A and Search B
        with search_runs_lock:
            run_b_jobs = search_runs[self.search_b_run_id]["jobs"]
            self.assertEqual(len(run_b_jobs), 3718)
            # Ensure none of Search A's emails or companies leaked into Search B
            emails_in_b = [j.get("email") for j in run_b_jobs if j.get("email")]
            self.assertEqual(len(emails_in_b), 0)
            self.assertNotIn("Hotel A 0", [j.get("company") for j in run_b_jobs])

    def test_prevent_duplicate_extraction_tasks_for_same_search(self):
        """Starting extraction twice on the same search_run_id returns the existing task without duplicate threads."""
        with search_runs_lock:
            search_runs[self.search_a_run_id] = {
                "search_run_id": self.search_a_run_id,
                "keyword": "Hotelfachmann",
                "location": "Berlin",
                "jobs": self.jobs_a[:10],
                "total": 10,
                "audit": {},
                "created_at": "2026-11-05T09:00:00",
                "auto_job_id": None,
            }

        # Start first task
        resp1 = self.client.post("/api/inline/auto-jobs/start", json={
            "search_run_id": self.search_a_run_id,
            "jobs": self.jobs_a[:10],
            "keyword": "Hotelfachmann",
            "location": "Berlin",
        })
        self.assertEqual(resp1.status_code, 200)
        job_id_1 = resp1.get_json().get("job_id")
        self.assertTrue(job_id_1)

        # Mark it actively running
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[job_id_1]["is_running"] = True

        # Attempt to start second task for same search_run_id
        resp2 = self.client.post("/api/inline/auto-jobs/start", json={
            "search_run_id": self.search_a_run_id,
            "jobs": self.jobs_a[:10],
            "keyword": "Hotelfachmann",
            "location": "Berlin",
        })
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        # Returns existing task ID rather than creating a duplicate
        self.assertEqual(data2.get("job_id"), job_id_1)
        self.assertIn("already active", data2.get("message", ""))

    def test_pause_resume_stop_isolation(self):
        """Pausing, resuming, or stopping task A does not interfere with other runs."""
        job_a_id = _create_auto_extraction_job(
            self.jobs_a[:5], "Job A", "Berlin", "all", search_run_id=self.search_a_run_id
        )
        job_b_id = _create_auto_extraction_job(
            self.jobs_b[:5], "Job B", "München", "all", search_run_id=self.search_b_run_id
        )

        with auto_extraction_jobs_lock:
            auto_extraction_jobs[job_a_id]["is_running"] = True
            auto_extraction_jobs[job_b_id]["is_running"] = True

        # Pause Task A
        pause_resp = self.client.post(f"/api/inline/auto-jobs/pause/{job_a_id}")
        self.assertEqual(pause_resp.status_code, 200)

        with auto_extraction_jobs_lock:
            self.assertTrue(auto_extraction_jobs[job_a_id]["paused"])
            self.assertFalse(auto_extraction_jobs[job_a_id]["is_running"])
            # Task B remains completely unaffected
            self.assertTrue(auto_extraction_jobs[job_b_id]["is_running"])
            self.assertFalse(auto_extraction_jobs[job_b_id]["paused"])

        # Stop Task A
        stop_resp = self.client.post(f"/api/inline/auto-jobs/stop/{job_a_id}")
        self.assertEqual(stop_resp.status_code, 200)

        with auto_extraction_jobs_lock:
            self.assertTrue(auto_extraction_jobs[job_a_id]["stop_requested"])
            # Task B still unaffected
            self.assertTrue(auto_extraction_jobs[job_b_id]["is_running"])

    def test_download_scoped_to_search_run(self):
        """Excel downloads export data strictly from the requested search_run_id or extraction task."""
        # Setup Search A with extracted email
        with auto_extraction_jobs_lock:
            job_a_id = _create_auto_extraction_job(
                self.jobs_a[:2], "Hotel", "Berlin", "all", search_run_id=self.search_a_run_id
            )
            auto_extraction_jobs[job_a_id]["jobs"][0]["email"] = "hotel_a@test.de"
            auto_extraction_jobs[job_a_id]["jobs"][0]["application_method"] = "email"

        # Setup Search B
        with search_runs_lock:
            search_runs[self.search_b_run_id] = {
                "search_run_id": self.search_b_run_id,
                "keyword": "Informatik",
                "location": "München",
                "jobs": [
                    {
                        "id": "b1",
                        "title": "Software Dev",
                        "company": "ByteCorp",
                        "location": "München",
                        "email": "dev@bytecorp.test",
                    }
                ],
                "total": 1,
            }

        # 1. Download Auto-Extraction results for Task A
        resp_a = self.client.get(f"/api/inline/auto-jobs/download/{job_a_id}?filter=all")
        self.assertEqual(resp_a.status_code, 200)
        df_a = pd.read_excel(io.BytesIO(resp_a.data))
        self.assertIn("hotel_a@test.de", df_a["email"].dropna().tolist())
        self.assertNotIn("dev@bytecorp.test", df_a["email"].dropna().tolist())

        # 2. Download Search results for Run B
        resp_b = self.client.get(f"/api/search/download?search_run_id={self.search_b_run_id}&filter=all")
        self.assertEqual(resp_b.status_code, 200)
        df_b = pd.read_excel(io.BytesIO(resp_b.data))
        self.assertIn("dev@bytecorp.test", df_b["email"].dropna().tolist())
        self.assertNotIn("hotel_a@test.de", df_b["email"].dropna().tolist())


if __name__ == "__main__":
    unittest.main()

