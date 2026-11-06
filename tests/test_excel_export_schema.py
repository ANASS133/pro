import io
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import openpyxl

import app as app_module


EXPECTED_EXCEL_COLUMNS = [
    "title",
    "company",
    "arbeitsgeber",
    "city",
    "location",
    "start_date",
    "email",
    "email_type",
    "phone",
    "contact_person",
    "anrede",
    "job_listing_url",
    "employer_website",
    "direct_application_url",
    "form_link",
    "application_method",
    "source",
    "extraction_status",
]

REMOVED_EXCEL_COLUMNS = {
    "hauptberuf",
    "published_date",
    "salary",
    "apply_url",
    "bewerbung_link",
    "bewerbung_art",
    "has_form",
    "application_url_type",
    "vacancies",
    "scraped_at",
    "required_documents",
}


def export_job():
    return {
        "title": "Fachinformatiker/in",
        "company": "Schema GmbH",
        "arbeitsgeber": "Schema GmbH",
        "city": "Berlin",
        "location": "10115 Berlin",
        "start_date": "2027-08-01",
        "email": "jobs@schema.test",
        "email_type": "recruitment",
        "phone": "+49 30 123456",
        "contact_person": "Erika Muster",
        "anrede": "Frau Muster",
        "job_listing_url": "https://schema.test/jobs/valid-listing",
        "employer_website": "https://schema.test",
        "direct_application_url": "https://schema.test/apply/valid",
        "form_link": "https://schema.test/apply/form-valid",
        "application_method": "both",
        "source": "Arbeitsagentur",
        "extraction_status": "completed",
        # Redundant/removed values must not overwrite the valid canonical links.
        "url": "javascript:void(0)",
        "apply_url": "#",
        "bewerbung_link": "not-a-url",
        "hauptberuf": "Fachinformatiker/in",
        "published_date": "2026-11-01",
        "salary": "1200 EUR",
        "bewerbung_art": "Online",
        "has_form": True,
        "application_url_type": "ats",
        "vacancies": 2,
        "scraped_at": "2026-11-06",
        "required_documents": "Lebenslauf",
    }


class ExcelExportSchemaTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.saved_search_cache = deepcopy(app_module.search_cache)
        with app_module.status_lock:
            self.saved_auto_status = deepcopy(app_module.auto_extraction_status)
        self.created_job_ids = []

    def tearDown(self):
        app_module.search_cache.clear()
        app_module.search_cache.update(self.saved_search_cache)
        with app_module.status_lock:
            app_module.auto_extraction_status.clear()
            app_module.auto_extraction_status.update(self.saved_auto_status)
        with app_module.auto_extraction_jobs_lock:
            for job_id in self.created_job_ids:
                app_module.auto_extraction_jobs.pop(job_id, None)

    def assert_exact_schema(self, response):
        if response.status_code != 200:
            self.fail(response.get_data(as_text=True))
        payload = response.get_data()
        response.close()
        frame = pd.read_excel(io.BytesIO(payload), sheet_name=0)
        self.assertEqual(list(frame.columns), EXPECTED_EXCEL_COLUMNS)
        self.assertEqual(len(frame.columns), 18)
        self.assertTrue(REMOVED_EXCEL_COLUMNS.isdisjoint(frame.columns))
        row = frame.iloc[0]
        self.assertEqual(row["job_listing_url"], "https://schema.test/jobs/valid-listing")
        self.assertEqual(row["direct_application_url"], "https://schema.test/apply/valid")
        self.assertEqual(row["form_link"], "https://schema.test/apply/form-valid")

    def add_task(self, job_id, *, running):
        self.created_job_ids.append(job_id)
        with app_module.auto_extraction_jobs_lock:
            app_module.auto_extraction_jobs[job_id] = {
                "job_id": job_id,
                "keyword": "Fachinformatiker",
                "is_running": running,
                "stop_requested": False,
                "paused": False,
                "current_index": 1,
                "total_jobs": 1,
                "jobs": [export_job()],
                "created_at": "2026-11-06T12:00:00",
                "updated_at": "2026-11-06T12:00:00",
                "workers": {},
            }

    def test_search_export_has_exact_18_column_schema(self):
        app_module.search_cache["jobs"] = [export_job()]
        app_module.search_cache["keyword"] = "Fachinformatiker"
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            app_module, "AUTO_EXTRACTION_EXPORT_DIR", Path(tmp_dir)
        ):
            response = self.client.get("/api/search/download?filter=all")
            self.assert_exact_schema(response)

    def test_auto_extraction_export_has_exact_18_column_schema(self):
        with app_module.status_lock:
            app_module.auto_extraction_status["jobs"] = [export_job()]
        app_module.search_cache["keyword"] = "Fachinformatiker"
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            app_module, "AUTO_EXTRACTION_EXPORT_DIR", Path(tmp_dir)
        ):
            response = self.client.get("/download_auto_results?filter=all")
            self.assert_exact_schema(response)

    def test_previous_task_export_has_exact_18_column_schema(self):
        job_id = "schema-previous-task"
        self.add_task(job_id, running=False)
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            app_module, "AUTO_EXTRACTION_EXPORT_DIR", Path(tmp_dir)
        ):
            response = self.client.get(f"/api/inline/auto-jobs/download/{job_id}?filter=all")
            self.assert_exact_schema(response)

    def test_stop_and_download_export_has_exact_18_column_schema(self):
        job_id = "schema-stop-download"
        self.add_task(job_id, running=True)
        stop_response = self.client.post(f"/api/inline/auto-jobs/stop/{job_id}")
        self.assertEqual(stop_response.status_code, 200)
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            app_module, "AUTO_EXTRACTION_EXPORT_DIR", Path(tmp_dir)
        ):
            response = self.client.get(f"/api/inline/auto-jobs/download/{job_id}?filter=all")
            self.assert_exact_schema(response)

    def test_valid_legacy_application_link_is_promoted_when_canonical_link_is_invalid(self):
        record = export_job()
        record.update({
            "direct_application_url": "javascript:void(0)",
            "form_link": "#",
            "bewerbung_link": "not-a-url",
            "apply_url": "https://schema.test/apply/legacy-valid",
        })

        frame = app_module._build_excel_export_dataframe([record])

        self.assertEqual(list(frame.columns), EXPECTED_EXCEL_COLUMNS)
        self.assertEqual(
            frame.iloc[0]["direct_application_url"],
            "https://schema.test/apply/legacy-valid",
        )

    def test_formula_like_export_text_is_written_as_plain_text(self):
        record = export_job()
        record["title"] = '=HYPERLINK("https://attacker.test","click")'
        frame = app_module._build_excel_export_dataframe([record])
        workbook_bytes = io.BytesIO()
        frame.to_excel(workbook_bytes, index=False)
        workbook_bytes.seek(0)

        workbook = openpyxl.load_workbook(workbook_bytes, data_only=False)
        cell = workbook.active.cell(row=2, column=1)
        self.assertEqual(cell.data_type, "s")
        self.assertTrue(str(cell.value).startswith("'="))
        workbook.close()

    def test_listing_url_is_not_promoted_to_direct_application_url(self):
        record = export_job()
        listing = record["job_listing_url"]
        record.update({
            "direct_application_url": "",
            "form_link": "",
            "bewerbung_link": listing,
            "apply_url": listing,
        })

        frame = app_module._build_excel_export_dataframe([record])

        self.assertEqual(frame.iloc[0]["job_listing_url"], listing)
        self.assertEqual(frame.iloc[0]["direct_application_url"], "")

    def test_google_maps_background_export_has_exact_18_column_schema(self):
        businesses = [{
            "name": "Maps Betrieb GmbH",
            "address": "Berlin",
            "website": "https://maps-betrieb.test",
            "phone": "+49 30 123456",
            "emails": ["jobs@maps-betrieb.test"],
            "maps_url": "https://maps.google.com/?cid=123",
            "status": "verified",
        }]
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            app_module, "GOOGLE_MAPS_EXPORT_DIR", Path(tmp_dir)
        ):
            export_path = app_module._save_google_maps_export("gmaps-schema-job", businesses, "Berlin")
            frame = pd.read_excel(export_path)

        self.assertEqual(list(frame.columns), EXPECTED_EXCEL_COLUMNS)

    def test_google_maps_download_endpoint_has_exact_18_column_schema(self):
        job_id = "gmaps-schema-endpoint"
        with app_module.google_maps_jobs_lock:
            app_module.google_maps_jobs[job_id] = {
                "query": "Berlin",
                "results": [{
                    "name": "Maps Download GmbH",
                    "address": "Berlin",
                    "website": "https://maps-download.test",
                    "emails": ["jobs@maps-download.test"],
                    "status": "verified",
                }],
            }
        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
                app_module, "GOOGLE_MAPS_EXPORT_DIR", Path(tmp_dir)
            ):
                response = self.client.get(f"/api/google-maps/export/{job_id}/xlsx")
                self.assertEqual(response.status_code, 200)
                frame = pd.read_excel(io.BytesIO(response.get_data()))
                response.close()
                self.assertEqual(list(frame.columns), EXPECTED_EXCEL_COLUMNS)
        finally:
            with app_module.google_maps_jobs_lock:
                app_module.google_maps_jobs.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
