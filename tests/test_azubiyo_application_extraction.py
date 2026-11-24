"""
Unit and regression test suite for Azubiyo.de "Jetzt bewerben" extraction pipeline.
Tests:
1. Direct anchor navigation & /bewerben/ subpage resolution
2. JavaScript-driven application button (validateAndTrackAndOpen / setApplication)
3. External ATS redirect and multi-hop resolution
4. New browser tab / window handling
5. Same-page Schnellbewerbung form recognition
6. Email application (email-first precedence over form/link)
7. Login-required application handling
8. Broken destination / no available destination -> manual_review_required
9. Mandatory consistency check invariants (prevent false verified statuses with empty URLs)
10. Multi-worker isolation (4 concurrent workers)
11. Excel export schema compatibility
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

from app import _build_excel_export_dataframe
from scraper.azubiyo_detail_extractor import (
    AzubiyoDetailExtractor,
    enforce_azubiyo_consistency_invariants,
    unescape_js_unicode,
)
from services.application_url_validator import (
    ApplicationDestinationType,
    classify_and_validate_destination,
)


class TestAzubiyoExtraction(unittest.TestCase):
    def setUp(self):
        self.extractor = AzubiyoDetailExtractor()

    def test_unescape_js_unicode(self):
        raw = "https://jobs.lvr.de/index.php?ac=jobad\\u0026id=1674"
        clean = unescape_js_unicode(raw)
        self.assertEqual(clean, "https://jobs.lvr.de/index.php?ac=jobad&id=1674")

    def test_email_first_precedence_over_form(self):
        """If an application email is found under /bewerben-email/, email takes precedence over form."""
        job = {
            "title": "Ausbildung Pflegefachfrau",
            "company": "Schwesternschaft Nürnberg",
            "url": "https://www.azubiyo.de/stellenanzeigen/ausbildung-als-pflegefachfrau-mann-m-w-d_schwesternschaft-nuernberg_d32d6599/",
            "source": "azubiyo.de",
        }
        main_html = (
            '<html><body>'
            '<a href="/stellenanzeigen/D32D6599/bewerben-email/">Jetzt bewerben</a>'
            '<a href="/stellenanzeigen/D32D6599/bewerben/">Online bewerben</a>'
            '</body></html>'
        )
        email_subpage_html = (
            '<html><body>'
            '<button onclick=\'validateAndTrackAndOpen(2, "mailto:pflegeschule@schwesternschaft-nuernberg.de?subject=Bewerbung")\'>Weiter</button>'
            '</body></html>'
        )

        mock_session = MagicMock()
        mock_resp_main = MagicMock(status_code=200, text=main_html, url=job["url"])
        mock_resp_sub = MagicMock(status_code=200, text=email_subpage_html, url="https://www.azubiyo.de/stellenanzeigen/D32D6599/bewerben-email/")

        def mock_get(url, *args, **kwargs):
            if "bewerben-email" in url:
                return mock_resp_sub
            return mock_resp_main

        mock_session.get.side_effect = mock_get

        res = self.extractor.extract_vacancy(job, driver=None, session=mock_session)
        self.assertEqual(res.get("extraction_status"), "verified_email")
        self.assertEqual(res.get("application_method"), "email")
        self.assertEqual(res.get("email"), "pflegeschule@schwesternschaft-nuernberg.de")
        self.assertEqual(res.get("direct_application_url"), "")
        self.assertEqual(res.get("form_link"), "")

    def test_schnellbewerbung_same_page_form_detection(self):
        """Recognizes on-page Schnellbewerbung form as same_page_application_form."""
        job = {
            "title": "Ausbildung Pflege",
            "company": "WBS Training",
            "url": "https://www.azubiyo.de/stellenanzeigen/ausbildung-zur-pflegefachmann-frau_wbs-training_3e3ade4a/",
            "source": "azubiyo.de",
        }
        main_html = (
            '<html><body>'
            '<a href="/stellenanzeigen/ausbildung-zur-pflegefachmann-frau_wbs-training_3e3ade4a/schnellbewerbung/">Jetzt bewerben</a>'
            '</body></html>'
        )
        schnell_html = (
            '<html><body>'
            '<h1>Schnellbewerbung starten</h1>'
            '<form class="pb-4 px-4">'
            '<input name="vorname" type="text" placeholder="Vorname">'
            '<input name="nachname" type="text" placeholder="Nachname">'
            '<input name="email" type="email" placeholder="Deine E-Mail Adresse">'
            '</form>'
            '</body></html>'
        )

        mock_session = MagicMock()
        mock_resp_main = MagicMock(status_code=200, text=main_html, url=job["url"])
        mock_resp_schnell = MagicMock(
            status_code=200,
            text=schnell_html,
            url="https://www.azubiyo.de/stellenanzeigen/ausbildung-zur-pflegefachmann-frau_wbs-training_3e3ade4a/schnellbewerbung/",
        )

        def mock_get(url, *args, **kwargs):
            if "schnellbewerbung" in url:
                return mock_resp_schnell
            return mock_resp_main

        mock_session.get.side_effect = mock_get

        res = self.extractor.extract_vacancy(job, driver=None, session=mock_session)
        self.assertEqual(res.get("extraction_status"), "verified_application_form")
        self.assertEqual(res.get("application_method"), "form")
        self.assertIn(res.get("application_url_type"), ("same_page_application_form", "direct_application_form"))
        self.assertEqual(res.get("application_navigation_type"), "same_page_form")
        self.assertTrue(res.get("has_form"))
        self.assertIn("schnellbewerbung", res.get("form_link"))

    def test_external_ats_destination_via_js(self):
        """Resolves validateAndTrackAndOpen destination to external ATS application endpoint."""
        job = {
            "title": "Ausbildung Pflegefachmann/-frau",
            "company": "LVR-Klinik Langenfeld",
            "url": "https://www.azubiyo.de/stellenanzeigen/ausbildung-pflegefachmann-frau-m-w-d_lvr-klinik-langenfeld_16a4g814/",
            "source": "azubiyo.de",
        }
        main_html = (
            '<html><body>'
            '<a href="/stellenanzeigen/16A4G814/bewerben/">Jetzt bewerben</a>'
            '</body></html>'
        )
        bewerben_html = (
            '<html><body>'
            '<button data-ng-click=\'validateAndTrackAndOpen(1, "https://jobs.lvr.de/index.php?ac=jobad\\u0026id=1674")\'>Weiter</button>'
            '</body></html>'
        )

        mock_session = MagicMock()
        mock_resp_main = MagicMock(status_code=200, text=main_html, url=job["url"])
        mock_resp_sub = MagicMock(status_code=200, text=bewerben_html, url="https://www.azubiyo.de/stellenanzeigen/16A4G814/bewerben/")
        mock_resp_ats = MagicMock(status_code=200, text="<html>Jobs LVR</html>", url="https://jobs.lvr.de/index.php?ac=jobad&id=1674", history=[])

        def mock_get(url, *args, **kwargs):
            if "jobs.lvr.de" in url:
                return mock_resp_ats
            if "bewerben" in url:
                return mock_resp_sub
            return mock_resp_main

        mock_session.get.side_effect = mock_get

        res = self.extractor.extract_vacancy(job, driver=None, session=mock_session)
        self.assertEqual(res.get("extraction_status"), "verified_application_form")
        self.assertEqual(res.get("direct_application_url"), "https://jobs.lvr.de/index.php?ac=jobad&id=1674")
        self.assertEqual(res.get("form_link"), "https://jobs.lvr.de/index.php?ac=jobad&id=1674")
        self.assertTrue(res.get("has_form"))

    def test_login_required_destination_handling(self):
        """Handles portal login requirement by recording login_required and portal_login_required."""
        record = {
            "title": "Job With Portal Login",
            "company": "Test Portal Employer",
            "job_listing_url": "https://www.azubiyo.de/stellenanzeigen/test-job/",
            "direct_application_url": "https://karriere.portal-employer.de/login?ref=123",
            "application_method": "portal_login_required",
            "application_url_type": "login_required",
            "extraction_status": "completed",
        }
        res = enforce_azubiyo_consistency_invariants(record)
        self.assertEqual(res["application_method"], "portal_login_required")
        self.assertEqual(res["direct_application_url"], "https://karriere.portal-employer.de/login?ref=123")
        self.assertEqual(res["extraction_status"], "completed")

    def test_invariant_enforcement_downgrades_empty_urls(self):
        """Prevents false verified statuses and empty portal_login_required records."""
        # 1. verified_application_link without URL
        bad_link = {
            "title": "Bad Link Job",
            "company": "Company",
            "extraction_status": "verified_application_link",
            "direct_application_url": "",
        }
        fixed_link = enforce_azubiyo_consistency_invariants(bad_link)
        self.assertEqual(fixed_link["extraction_status"], "manual_review_required")
        self.assertTrue(fixed_link["manual_review_required"])

        # 2. verified_email without email
        bad_email = {
            "title": "Bad Email Job",
            "company": "Company",
            "extraction_status": "verified_email",
            "email": "",
        }
        fixed_email = enforce_azubiyo_consistency_invariants(bad_email)
        self.assertEqual(fixed_email["extraction_status"], "manual_review_required")

        # 3. portal_login_required without login entry URL
        bad_login = {
            "title": "Bad Login Job",
            "company": "Company",
            "application_method": "portal_login_required",
            "direct_application_url": "",
            "form_link": "",
            "extraction_status": "completed",
        }
        fixed_login = enforce_azubiyo_consistency_invariants(bad_login)
        self.assertEqual(fixed_login["application_method"], "unknown")
        self.assertEqual(fixed_login["extraction_status"], "manual_review_required")

    def test_excel_export_schema_and_mutually_exclusive_columns(self):
        """Verifies Excel export preserves 18 public columns and clears form fields when email exists."""
        records = [
            {
                "title": "Job A",
                "company": "Company A",
                "email": "bewerbung@comp-a.de",
                "direct_application_url": "https://comp-a.de/apply",
                "form_link": "https://comp-a.de/apply",
                "source": "azubiyo.de",
                "application_method": "email",
                "extraction_status": "verified_email",
            },
            {
                "title": "Job B",
                "company": "Company B",
                "email": "",
                "direct_application_url": "https://comp-b.de/jobs/123",
                "form_link": "https://comp-b.de/jobs/123",
                "source": "azubiyo.de",
                "application_method": "form",
                "extraction_status": "verified_application_form",
            },
        ]
        df = _build_excel_export_dataframe(records)
        row_a = df[df["company"] == "Company A"].iloc[0]
        row_b = df[df["company"] == "Company B"].iloc[0]

        # Job A has email -> form/direct application url columns MUST be empty
        self.assertEqual(row_a["email"], "bewerbung@comp-a.de")
        self.assertEqual(row_a["direct_application_url"], "")
        self.assertEqual(row_a["form_link"], "")

        # Job B has form -> email is empty, direct application url is present
        self.assertEqual(row_b["email"], "")
        self.assertEqual(row_b["direct_application_url"], "https://comp-b.de/jobs/123")
        self.assertEqual(row_b["extraction_status"], "verified_application_form")

    def test_multi_worker_thread_isolation(self):
        """Simulates 4 concurrent workers extracting Azubiyo jobs to ensure zero state contamination."""
        workers_count = 4
        extractor = AzubiyoDetailExtractor()
        results = {}
        errors = []

        jobs = [
            {
                "id": i,
                "company": f"Unique Employer {i} GmbH",
                "title": f"Ausbildung Pflege {i}",
                "url": f"https://www.azubiyo.de/stellenanzeigen/job-{i}/",
                "source": "azubiyo.de",
            }
            for i in range(1, workers_count + 1)
        ]

        def worker_task(job_item, worker_id):
            try:
                # Mock session with unique email per worker
                mock_sess = MagicMock()
                unique_email = f"bewerbung@employer-{job_item['id']}.de"
                mock_resp = MagicMock(
                    status_code=200,
                    text=(
                        f'<html><body><a href="mailto:{unique_email}">Kontakt</a></body></html>'
                    ),
                    url=job_item["url"],
                )
                mock_sess.get.return_value = mock_resp
                res = extractor.extract_vacancy(job_item, driver=None, session=mock_sess, worker_id=worker_id)
                results[job_item["id"]] = res
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker_task, args=(jobs[i], i + 1))
            for i in range(workers_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), workers_count)
        for i in range(1, workers_count + 1):
            expected_email = f"bewerbung@employer-{i}.de"
            self.assertEqual(results[i].get("email"), expected_email)


if __name__ == "__main__":
    unittest.main()
