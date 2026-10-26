"""
Test suite for JobScout Deep Application Form Discovery and Excel Export.
Covers all 10 required test scenarios:
1. Job with email only.
2. Job with online application only.
3. Job with both methods.
4. Job without either method.
5. Multi-page Bewerbungsformular discovery.
6. JavaScript application buttons.
7. External ATS redirects.
8. Unverified generic careers pages.
9. Duplicate opportunities.
10. Complete Excel export with all 21 original columns in exact order.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from app import _build_job_dedupe_key, _merge_job_records, _prepare_download_jobs
from scraper.application_form_discovery import (
    EXCEL_COLUMNS,
    STATUS_GENERIC_CAREERS_PAGE,
    STATUS_JOB_AD_ONLY,
    STATUS_VERIFIED_ENTRY_POINT,
    STATUS_VERIFIED_FORM,
    ApplicationFormDiscovery,
    FormDiscoveryResult,
    classify_application_method,
    normalize_job_opportunity_row,
)


class TestDeepApplicationDiscovery(unittest.TestCase):
    def setUp(self):
        self.discovery = ApplicationFormDiscovery(timeout=2.0, max_hops=3)

    # 1. Job with email only
    def test_job_with_email_only(self):
        method, art = classify_application_method("hr@beispiel.de", has_form=False)
        self.assertEqual(method, "email")
        self.assertEqual(art, "E-Mail")

        job = {
            "title": "Koch (m/w/d)",
            "company": "Hotel Stern",
            "email": "hr@beispiel.de",
            "apply_url": "https://www.arbeitsagentur.de/jobboerse/123",
        }
        row = normalize_job_opportunity_row(job)
        self.assertEqual(row["application_method"], "email")
        self.assertEqual(row["bewerbung_art"], "E-Mail")
        self.assertEqual(row["email"], "hr@beispiel.de")
        self.assertFalse(row["has_form"])
        self.assertEqual(row["form_link"], "")
        self.assertEqual(row["apply_url"], "https://www.arbeitsagentur.de/jobboerse/123")

    # 2. Job with online application only
    def test_job_with_online_application_only(self):
        method, art = classify_application_method("", has_form=True)
        self.assertEqual(method, "form")
        self.assertEqual(art, "Online-Formular")

        job = {
            "title": "Koch (m/w/d)",
            "company": "Gastro GmbH",
            "email": "",
            "apply_url": "https://www.arbeitsagentur.de/jobboerse/456",
        }
        mock_result = FormDiscoveryResult(
            has_form=True,
            form_link="https://gastro-gmbh.jobs.personio.de/job/987?apply=true",
            bewerbung_link="https://gastro-gmbh.jobs.personio.de/job/987?apply=true",
            status=STATUS_VERIFIED_FORM,
            evidence=["ats_apply_endpoint", "input_candidate_email"],
        )
        row = normalize_job_opportunity_row(job, discovery_result=mock_result)
        self.assertEqual(row["application_method"], "form")
        self.assertEqual(row["bewerbung_art"], "Online-Formular")
        self.assertTrue(row["has_form"])
        self.assertEqual(row["form_link"], "https://gastro-gmbh.jobs.personio.de/job/987?apply=true")
        self.assertEqual(row["apply_url"], "https://www.arbeitsagentur.de/jobboerse/456")

    # 3. Job with both methods
    def test_job_with_both_methods(self):
        method, art = classify_application_method("jobs@gastro.de", has_form=True)
        self.assertEqual(method, "both")
        self.assertEqual(art, "E-Mail + Online-Formular")

        job = {
            "title": "Hotelfachmann (m/w/d)",
            "company": "Grand Hotel",
            "email": "jobs@gastro.de",
            "apply_url": "https://www.arbeitsagentur.de/jobboerse/789",
        }
        mock_result = FormDiscoveryResult(
            has_form=True,
            form_link="https://grandhotel.de/karriere/online-bewerbung-hotelfachmann",
            bewerbung_link="https://grandhotel.de/karriere/online-bewerbung-hotelfachmann",
            status=STATUS_VERIFIED_FORM,
            evidence=["input_file_upload", "input_candidate_name"],
        )
        row = normalize_job_opportunity_row(job, discovery_result=mock_result)
        self.assertEqual(row["application_method"], "both")
        self.assertEqual(row["bewerbung_art"], "E-Mail + Online-Formular")
        self.assertEqual(row["email"], "jobs@gastro.de")
        self.assertTrue(row["has_form"])
        self.assertEqual(row["form_link"], "https://grandhotel.de/karriere/online-bewerbung-hotelfachmann")

    # 4. Job without either method
    def test_job_without_either_method(self):
        method, art = classify_application_method("", has_form=False)
        self.assertEqual(method, "unknown")
        self.assertEqual(art, "Unbekannt")

        job = {
            "title": "Küchenhilfe (m/w/d)",
            "company": "Kantine West",
            "email": "",
            "apply_url": "https://www.arbeitsagentur.de/jobboerse/001",
        }
        row = normalize_job_opportunity_row(job)
        self.assertEqual(row["application_method"], "unknown")
        self.assertEqual(row["bewerbung_art"], "Unbekannt")
        self.assertEqual(row["email"], "")
        self.assertFalse(row["has_form"])
        self.assertEqual(row["form_link"], "")
        # Preserved in export!
        self.assertEqual(row["bewerbung_link"], "https://www.arbeitsagentur.de/jobboerse/001")
        self.assertEqual(row["apply_url"], "https://www.arbeitsagentur.de/jobboerse/001")

    # 5. Multi-page Bewerbungsformular discovery
    def test_multi_page_form_discovery(self):
        """
        Simulate:
        Listing page -> button 'Jetzt online bewerben' (hop 1)
        -> intermediate career page with button 'Bewerbungsformular' (hop 2)
        -> authentic form with candidate input fields and file upload
        """
        listing_html = """
        <html>
            <body>
                <h1>Ausbildung Koch 2026</h1>
                <a href="/jobs/koch-details">Jetzt online bewerben</a>
            </body>
        </html>
        """
        intermediate_html = """
        <html>
            <body>
                <h2>Koch bei Gourmet AG</h2>
                <a href="/jobs/koch/apply-form">Bewerbungsformular starten</a>
            </body>
        </html>
        """
        actual_form_html = """
        <html>
            <body>
                <form action="/submit-application" method="POST">
                    <input type="text" name="vorname" placeholder="Vorname">
                    <input type="text" name="nachname" placeholder="Nachname">
                    <input type="email" name="email" placeholder="E-Mail-Adresse">
                    <input type="file" name="cv_upload" accept=".pdf">
                    <button type="submit">Bewerbung absenden</button>
                </form>
            </body>
        </html>
        """

        def mock_fetch(url):
            if "job-listing" in url:
                return "https://gourmet.de/job-listing", listing_html
            if "koch-details" in url:
                return "https://gourmet.de/jobs/koch-details", intermediate_html
            if "apply-form" in url:
                return "https://gourmet.de/jobs/koch/apply-form", actual_form_html
            return url, ""

        with patch.object(self.discovery, "fetch_page", side_effect=mock_fetch):
            job = {
                "title": "Koch",
                "company": "Gourmet AG",
                "apply_url": "https://gourmet.de/job-listing",
            }
            res = self.discovery.discover_application_form(job)
            self.assertTrue(res.has_form)
            self.assertEqual(res.status, STATUS_VERIFIED_FORM)
            self.assertEqual(res.form_link, "https://gourmet.de/jobs/koch/apply-form")
            self.assertIn("input_file_upload", res.evidence)

    # 6. JavaScript application buttons
    def test_javascript_application_button_extraction(self):
        html = """
        <html>
            <body>
                <button onclick="window.location.href='/karriere/bewerben?job_id=44';">Jetzt bewerben</button>
                <button onclick="location.assign('https://jobs.partner.de/apply/44');">Online bewerben</button>
            </body>
        </html>
        """
        links = self.discovery.extract_application_links_from_html(html, "https://firma.de/jobs/44")
        self.assertTrue(any("bewerben" in link for link in links))
        self.assertTrue(any("partner.de" in link for link in links))

    # 7. External ATS redirects
    def test_external_ats_redirects(self):
        """
        Listing page link redirects to external Personio/Softgarden apply endpoint.
        """
        listing_html = """
        <html>
            <body>
                <a href="https://firmenportal.de/apply-redirect">Jetzt bewerben</a>
            </body>
        </html>
        """
        ats_html = """
        <html>
            <head><title>Bewerbung - Personio</title></head>
            <body>
                <div class="application-form">
                    <input type="text" name="applicant_name">
                    <input type="email" name="applicant_email">
                    <input type="file" name="resume">
                </div>
            </body>
        </html>
        """

        def mock_fetch(url):
            if "firmenportal.de" in url:
                # Redirects to personio.de apply endpoint
                return "https://firma.jobs.personio.de/job/123/apply", ats_html
            return url, ""

        with patch.object(self.discovery, "fetch_page", side_effect=mock_fetch):
            job = {
                "title": "Koch",
                "company": "Firma",
                "apply_url": "https://firmenportal.de/job/1",
            }
            res = self.discovery.discover_application_form(job)
            self.assertTrue(res.has_form)
            self.assertIn("personio.de", res.form_link)
            self.assertEqual(res.status, STATUS_VERIFIED_FORM)

    # 8. Unverified generic careers pages
    def test_unverified_generic_careers_page_fallback(self):
        """
        If only a generic careers page is found (no form inputs), has_form must be FALSE,
        form_link must be empty, and bewerbung_link points to the careers page as fallback.
        """
        generic_career_html = """
        <html>
            <body>
                <h1>Karriere bei Hotel Sonne</h1>
                <p>Willkommen auf unserer Karriereseite. Entdecken Sie offene Stellen.</p>
                <p>Kontakt: info@hotel-sonne.de</p>
            </body>
        </html>
        """

        is_verified, status, _ = self.discovery.verify_form_page(
            generic_career_html, "https://hotel-sonne.de/karriere"
        )
        self.assertFalse(is_verified)
        self.assertEqual(status, STATUS_GENERIC_CAREERS_PAGE)

        # In discovery result:
        mock_result = FormDiscoveryResult(
            has_form=False,
            form_link="",
            bewerbung_link="https://hotel-sonne.de/karriere",
            status=STATUS_GENERIC_CAREERS_PAGE,
            evidence=["company_career_page_fallback"],
        )
        row = normalize_job_opportunity_row(
            {"title": "Koch", "company": "Hotel Sonne", "apply_url": "https://arbeitsagentur.de/job/1"},
            discovery_result=mock_result,
        )
        self.assertFalse(row["has_form"])
        self.assertEqual(row["form_link"], "")
        self.assertEqual(row["bewerbung_link"], "https://hotel-sonne.de/karriere")
        self.assertEqual(row["application_method"], "unknown")
        self.assertEqual(row["bewerbung_art"], "Unbekannt")

    # 9. Duplicate opportunities
    def test_deduplication_preserves_distinct_positions_from_same_employer(self):
        """
        Tests that different positions from the same employer (even with the same email or company)
        are NOT merged or dropped, but genuine duplicates are excluded.
        """
        jobs = [
            # Job A: Position 1
            {
                "refnr": "REF-001",
                "company": "Hotel Central",
                "title": "Ausbildung zum Koch (m/w/d)",
                "location": "Köln",
                "email": "karriere@hotel-central.de",
            },
            # Job B: Position 2 at SAME employer with SAME email
            {
                "refnr": "REF-002",
                "company": "Hotel Central",
                "title": "Ausbildung Hotelfachmann (m/w/d)",
                "location": "Köln",
                "email": "karriere@hotel-central.de",
            },
            # Job C: Genuine duplicate of Job A
            {
                "refnr": "REF-001",
                "company": "Hotel Central",
                "title": "Ausbildung zum Koch (m/w/d)",
                "location": "Köln",
                "email": "karriere@hotel-central.de",
            },
            # Job D: Opportunity without email at same company
            {
                "refnr": "REF-003",
                "company": "Hotel Central",
                "title": "Ausbildung Restaurantfachmann (m/w/d)",
                "location": "Köln",
                "email": "",
            },
        ]

        prepared = _prepare_download_jobs(jobs)
        # Should have exactly 3 jobs (REF-001, REF-002, REF-003), genuine duplicate C dropped,
        # position without email D preserved, and positions A & B both kept!
        self.assertEqual(len(prepared), 3)
        titles = [j["title"] for j in prepared]
        self.assertIn("Ausbildung zum Koch (m/w/d)", titles)
        self.assertIn("Ausbildung Hotelfachmann (m/w/d)", titles)
        self.assertIn("Ausbildung Restaurantfachmann (m/w/d)", titles)

        # Test _merge_job_records
        merged = _merge_job_records(prepared[:2], [jobs[3]])
        self.assertEqual(len(merged), 3)

    # 10. Complete Excel export with all 21 original columns in exact order
    def test_complete_excel_export_schema(self):
        jobs = [
            {
                "title": "Ausbildung zum Koch",
                "company": "Gastro Stern GmbH",
                "location": "Köln",
                "city": "Köln",
                "published_date": "2026-10-20",
                "start_date": "2026-08-01",
                "hauptberuf": "Koch/Köchin",
                "email": "info@gastro-stern.de",
                "phone": "+49 221 123456",
                "source": "Arbeitsagentur",
                "arbeitsgeber": "Herr Klaus Schmidt",
                "apply_url": "https://www.arbeitsagentur.de/jobboerse/1000",
                "form_link": "https://gastro-stern.de/bewerbungsformular",
                "has_form": True,
                "application_method": "both",
                "bewerbung_art": "E-Mail + Online-Formular",
                "bewerbung_link": "https://gastro-stern.de/bewerbungsformular",
                "anrede": "Sehr geehrter",
                "vacancies": "2",
                "scraped_at": "2026-10-26 12:00",
                "salary": "1050 EUR",
            },
            # Record without email
            {
                "title": "Beikoch (m/w/d)",
                "company": "Kantine West",
                "location": "Bonn",
                "apply_url": "https://www.arbeitsagentur.de/jobboerse/2000",
            },
        ]

        prepared = _prepare_download_jobs(jobs)
        self.assertEqual(len(prepared), 2)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            df = pd.DataFrame(prepared)
            # Ensure exact 21 columns
            existing_cols = [c for c in EXCEL_COLUMNS if c in df.columns]
            df = df[existing_cols]
            df.to_excel(tmp_path, index=False)

            # Re-read and verify
            read_df = pd.read_excel(tmp_path)
            self.assertEqual(list(read_df.columns), EXCEL_COLUMNS)
            self.assertEqual(len(read_df.columns), 21)
            self.assertEqual(len(read_df), 2)

            # Verify exact column order
            expected_21_columns = [
                "title",
                "company",
                "location",
                "city",
                "published_date",
                "start_date",
                "hauptberuf",
                "email",
                "phone",
                "source",
                "arbeitsgeber",
                "apply_url",
                "form_link",
                "has_form",
                "application_method",
                "bewerbung_art",
                "bewerbung_link",
                "anrede",
                "vacancies",
                "scraped_at",
                "salary",
            ]
            self.assertEqual(list(read_df.columns), expected_21_columns)

            # Row 0: email + form (both)
            self.assertEqual(read_df.iloc[0]["application_method"], "both")
            self.assertEqual(read_df.iloc[0]["bewerbung_art"], "E-Mail + Online-Formular")
            self.assertTrue(bool(read_df.iloc[0]["has_form"]))
            self.assertEqual(read_df.iloc[0]["form_link"], "https://gastro-stern.de/bewerbungsformular")

            # Row 1: no email (preserved in export!)
            self.assertFalse(bool(read_df.iloc[1]["has_form"]))
            self.assertEqual(read_df.iloc[1]["title"], "Beikoch (m/w/d)")
            self.assertEqual(read_df.iloc[1]["company"], "Kantine West")
            self.assertEqual(read_df.iloc[1]["apply_url"], "https://www.arbeitsagentur.de/jobboerse/2000")
            self.assertEqual(read_df.iloc[1]["application_method"], "unknown")
            self.assertEqual(read_df.iloc[1]["bewerbung_art"], "Unbekannt")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
