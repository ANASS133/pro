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

    def test_app_shell_scripts_and_progress_elements(self):
        """Verify app_shell has search progress elements and all SPA script tags."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html_text = response.get_data(as_text=True)

        # Check search button and progress card elements
        self.assertIn('id="search_btn_1"', html_text)
        self.assertIn('id="search_btn_bar_1"', html_text)
        self.assertIn('id="search_progress_card_1"', html_text)
        self.assertIn('id="search_progress_fill_1"', html_text)
        self.assertIn('id="search_progress_stages_1"', html_text)

        # Check SPA scripts are loaded
        self.assertIn('static/spa/sections/search.js', html_text)
        self.assertIn('static/spa/app.js', html_text)
        self.assertIn('static/spa/utils.js', html_text)

    def test_api_search_stream_endpoint(self):
        """Verify /api/search/stream SSE streaming validation and execution."""
        # 1. Validation error on missing keyword
        res_err = self.client.get("/api/search/stream?keyword=")
        self.assertEqual(res_err.status_code, 400)

        # 2. Mocked stream execution
        from unittest.mock import patch
        mock_jobs = [
            {"title": "Koch Azubi", "company": "Hotel Grand", "location": "Berlin", "source": "Arbeitsagentur"}
        ]
        with patch("app._fetch_combined_jobs") as mock_fetch:
            def side_effect(*args, **kwargs):
                cb = kwargs.get("progress_callback")
                if callable(cb):
                    cb({"source": "arbeitsagentur", "stage": "Arbeitsagentur wird durchsucht...", "percent": 25, "found": 1})
                return mock_jobs

            mock_fetch.side_effect = side_effect
            res_stream = self.client.get("/api/search/stream?keyword=Koch&location=Berlin&source=arbeitsagentur")
            self.assertEqual(res_stream.status_code, 200)
            self.assertEqual(res_stream.mimetype, "text/event-stream")
            body = res_stream.get_data(as_text=True)
            self.assertIn("event: start", body)
            self.assertIn("event: progress", body)
            self.assertIn("event: complete", body)
            self.assertIn("Hotel Grand", body)

    def test_preview_bulk_upload_file(self):
        """Verify /api/send-bulk/preview-file correctly detects columns and email statistics."""
        import io
        csv_content = "name,email,company\nMax,max@example.com,Firma A\nAnna,anna@example.com,Firma B\nMax2,max@example.com,Firma C\n"
        data = {
            "data_file": (io.BytesIO(csv_content.encode("utf-8")), "recipients.csv")
        }
        res = self.client.post("/api/send-bulk/preview-file", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total_rows"], 3)
        self.assertEqual(payload["detected_recipient_column"], "email")
        self.assertEqual(payload["valid_email_count"], 3)
        self.assertEqual(payload["duplicate_count"], 1)
        self.assertEqual(len(payload["preview_rows"]), 3)

    def test_send_test_email_validation(self):
        """Verify /api/send-bulk/test-email validates required parameters."""
        # Missing sender email
        res = self.client.post("/api/send-bulk/test-email", data={})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Absender-E-Mail", res.get_json()["message"])

        # Missing password
        res = self.client.post("/api/send-bulk/test-email", data={"sender_email": "test@gmail.com"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("App-Passwort", res.get_json()["message"])


if __name__ == "__main__":
    unittest.main()

