import unittest
from app import app


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_index_route(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_add_redirects_to_index(self):
        response = self.client.get("/add", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers.get("Location", ""))

    def test_dashboard_route(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)

    def test_ausbildungen_route(self):
        response = self.client.get("/ausbildungen")
        self.assertEqual(response.status_code, 200)

    def test_money_route(self):
        response = self.client.get("/money")
        self.assertEqual(response.status_code, 200)

    def test_ausbildungen_files_api(self):
        response = self.client.get("/api/ausbildungen/files")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("files", data)

    def test_send_emails_campaigns_api(self):
        response = self.client.get("/api/send-emails/campaigns")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("active_send_job", data)

    def test_health_route(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertIn("services", data)
        self.assertIn("storage", data)

    def test_jobs_api_and_sse_stream(self):
        from services.job_store import job_store
        job_store.save_job(
            job_id="test-sse-job",
            job_type="test",
            phase="completed",
            is_running=False,
            progress=10,
            total=10,
        )

        # Test list jobs
        res = self.client.get("/api/jobs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreater(len(data.get("jobs", [])), 0)

        # Test get single job
        res_single = self.client.get("/api/jobs/test-sse-job")
        self.assertEqual(res_single.status_code, 200)
        self.assertEqual(res_single.get_json()["job"]["phase"], "completed")

        # Test SSE Stream
        res_stream = self.client.get("/api/jobs/test-sse-job/stream")
        self.assertEqual(res_stream.status_code, 200)
        self.assertEqual(res_stream.mimetype, "text/event-stream")
        output_text = res_stream.get_data(as_text=True)
        self.assertIn("data: ", output_text)
        self.assertIn("test-sse-job", output_text)

    def test_pdf_fonts_and_stream_preview(self):
        # Test fonts endpoint
        res = self.client.get("/api/pdf/fonts")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("helvetica", data.get("supported_fonts", []))

        # Test stream preview endpoint
        res_preview = self.client.post(
            "/api/pdf/stream-preview",
            json={"content": "<b>Bewerbung</b> fuer Software Entwickler", "metadata": {"title": "Preview"}},
        )
        self.assertEqual(res_preview.status_code, 200)
        self.assertEqual(res_preview.mimetype, "application/pdf")
        self.assertGreater(len(res_preview.data), 100)


if __name__ == "__main__":
    unittest.main()
