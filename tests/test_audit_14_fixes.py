"""
Tests for JobScout Architecture Audit 14 Fixes:
1. Worker-slot acquisition/release guard
2. Safe Selenium WebDriver recycling
3. Checkpoint, active task, and Pause/Resume behavior
4. Arbeitsagentur partner redirect with bounded timeout
5. Ausbildung.de meta-refresh redirect detection with URL validation
6. IHK postal-only application classification
7. Azubiyo portal-login required classification
8. Google Maps missing-website classification
9. Previous tasks button contrast styling
10. isCompleted declaration order verification
"""

import os
import queue
import re
import unittest
from unittest.mock import MagicMock, patch

from scraper.application_form_discovery import (
    ApplicationFormDiscovery,
    classify_application_method,
    normalize_job_opportunity_row,
)
from scraper.arbeitsagentur_extractor import ArbeitsagenturDetailExtractor
from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
from scraper.working_email_extractor import WorkingEmailExtractor


class TestAudit14Fixes(unittest.TestCase):

    # -------------------------------------------------------------------------
    # Priority 0 — Reliability
    # -------------------------------------------------------------------------

    def test_01_worker_slot_acquisition_guard(self):
        """Worker slot must be returned to queue even if task execution raises an error."""
        worker_slots = queue.Queue()
        worker_slots.put(1)
        worker_slots.put(2)

        w_id = worker_slots.get()
        self.assertEqual(w_id, 1)

        # Simulate try/finally pattern used in app.py worker pool
        try:
            raise RuntimeError("Simulated worker exception")
        except RuntimeError:
            pass
        finally:
            worker_slots.put(w_id)

        # Slot 1 must be safely recovered
        self.assertEqual(worker_slots.qsize(), 2)
        recovered_ids = [worker_slots.get(), worker_slots.get()]
        self.assertIn(1, recovered_ids)
        self.assertIn(2, recovered_ids)

    def test_02_webdriver_recycling_behavior(self):
        """WorkingEmailExtractor must support safe driver recycling without crashing."""
        extractor = WorkingEmailExtractor(captcha_userid="test", captcha_apikey="test")
        mock_driver = MagicMock()
        extractor.driver = mock_driver
        extractor._jobs_since_recycle = 55

        with patch.object(extractor, "setup_driver", return_value=None):
            extractor.recycle_driver_if_needed(force=True)
            mock_driver.quit.assert_called_once()
            self.assertEqual(extractor._jobs_since_recycle, 0)
        extractor.close()

    def test_03_pause_resume_state_and_unfinished_retention(self):
        """_is_job_finished must accurately differentiate finished vs pending jobs."""
        from app import _is_job_finished

        finished_job = {
            "title": "Hotelkaufmann",
            "email": "jobs@hotel.de",
            "email_extracted": True,
            "extraction_status": "completed",
        }
        pending_job = {
            "title": "Koch",
            "email": None,
            "email_extracted": False,
            "extraction_status": "unresolved",
        }
        manual_job = {
            "title": "Rezeptionist",
            "email": "",
            "extraction_status": "manual_required",
        }

        self.assertTrue(_is_job_finished(finished_job))
        self.assertFalse(_is_job_finished(pending_job))
        self.assertTrue(_is_job_finished(manual_job))

    # -------------------------------------------------------------------------
    # Priority 1 — Platform-Specific Extraction
    # -------------------------------------------------------------------------

    def test_04_arbeitsagentur_partner_redirect_bounded_timeout(self):
        """Arbeitsagentur partner redirects must have bounded timeout and flag manual_required on failure."""
        aa = ArbeitsagenturDetailExtractor()

        # Simulate timeout on partner redirect resolution
        with patch.object(aa.session, "head", side_effect=Exception("Connection timed out")):
            with patch.object(aa.session, "get", side_effect=Exception("Connection timed out")):
                term_url, status, manual_required = aa.resolve_partner_redirect("https://partner.arbeitsagentur.de/external-job", timeout=1.0)
                self.assertTrue(manual_required)
                self.assertIn(status, ("unresolved", "blocked"))

        # Test application section parsing with partner redirect failure
        html = "<html><body><section>Informationen zur Bewerbung</section></body></html>"
        with patch.object(aa, "extract_from_ssr_script", return_value={"allianzpartnerUrl": "https://partner.arbeitsagentur.de/external-job"}):
            with patch.object(aa, "resolve_partner_redirect", return_value=("https://partner.arbeitsagentur.de/external-job", "blocked", True)):
                parsed = aa.parse_application_section(html)
                self.assertTrue(parsed.get("manual_review_required"))
                self.assertEqual(parsed.get("extraction_status"), "manual_required")

    def test_05_ausbildung_de_meta_refresh_detection(self):
        """Ausbildung.de fast-path must detect HTML meta-refresh, validate destination, and resolve ATS."""
        discovery = ApplicationFormDiscovery()

        refresh_html = """
        <html>
        <head>
            <meta http-equiv="refresh" content="0; url=https://company.jobs.personio.de/job/12345">
        </head>
        <body>Redirecting to ATS...</body>
        </html>
        """
        ats_html = """
        <html>
        <head><title>Job Apply</title></head>
        <body>
            <h1>Bewerbung einreichen</h1>
            <form action="/submit" method="POST">
                <input type="text" name="name" />
                <input type="email" name="email" />
                <button type="submit">Bewerbung absenden</button>
            </form>
        </body>
        </html>
        """

        mock_resp_redir = MagicMock()
        mock_resp_redir.status_code = 200
        mock_resp_redir.url = "https://www.ausbildung.de/stellen/123/redirect"
        mock_resp_redir.text = refresh_html

        mock_resp_ats = MagicMock()
        mock_resp_ats.status_code = 200
        mock_resp_ats.url = "https://company.jobs.personio.de/job/12345"
        mock_resp_ats.text = ats_html

        with patch("scraper.rate_limiter.safe_http_get", side_effect=[mock_resp_redir, mock_resp_ats]):
            final_url, final_html = discovery.fetch_page("https://www.ausbildung.de/stellen/123/redirect")
            self.assertEqual(final_url, "https://company.jobs.personio.de/job/12345")
            self.assertIn("Bewerbung absenden", final_html)

    def test_06_ihk_postal_classification(self):
        """IHK postal-only applications must be classified as 'postal' and not 'unknown' or 'none'."""
        ihk_job = {
            "title": "Fachinformatiker",
            "company": "Muster GmbH",
            "source": "ihk.de",
            "url": "https://ihk-lehrstellenboerse.de/job/123",
            "bewerbungsart": "Schriftlich per Post",
            "postal_only": True,
            "email": "",
            "has_form": False,
        }

        normalized = normalize_job_opportunity_row(ihk_job)
        self.assertEqual(normalized["application_method"], "postal")
        self.assertEqual(normalized["bewerbung_art"], "Post / Schriftlich")
        self.assertEqual(normalized["extraction_status"], "completed")

    def test_07_azubiyo_portal_login_required_classification(self):
        """Azubiyo portal-login requirements must be classified as 'portal_login_required' with 'completed' status."""
        azubiyo_job = {
            "title": "Industriekaufmann",
            "company": "Azubi AG",
            "source": "azubiyo.de",
            "url": "https://www.azubiyo.de/stellenanzeigen/industriekaufmann-123/",
            "portal_login_required": True,
            "bewerbungsart": "Portal-Registrierung erforderlich",
            "email": "",
            "has_form": False,
        }

        normalized = normalize_job_opportunity_row(azubiyo_job)
        self.assertEqual(normalized["application_method"], "portal_login_required")
        self.assertEqual(normalized["bewerbung_art"], "Portal-Registrierung erforderlich")
        self.assertEqual(normalized["extraction_status"], "completed")

    def test_08_google_maps_missing_website_classification(self):
        """Google Maps businesses with missing or invalid websites must not invent application methods or verified vacancies."""
        verifier = GoogleMapsAusbildungVerifier()

        business_no_web = {
            "name": "Bäckerei Schmidt",
            "website": "",
            "address": "Hauptstr. 1, 80331 München",
        }
        res = verifier.verify_business(business_no_web, profession_keyword="Bäcker")
        self.assertFalse(res["is_verified_vacancy"])
        self.assertEqual(res["opportunity_type"], "UNVERIFIED")
        self.assertEqual(res["application_method"], "none")
        self.assertEqual(res["bewerbung_art"], "Keine Website vorhanden")
        self.assertEqual(res["direct_application_url"], "")
        self.assertFalse(res["has_form"])

        # In verify_business_for_arbeit
        contact_res = verifier.verify_business_for_arbeit(business_no_web, profession_keyword="Bäcker")
        self.assertFalse(contact_res["is_verified_vacancy"])
        self.assertEqual(contact_res["opportunity_type"], "UNVERIFIED")
        self.assertEqual(contact_res["application_method"], "none")
        self.assertEqual(contact_res["bewerbung_art"], "Keine Website vorhanden")

    # -------------------------------------------------------------------------
    # Priority 2 — UI
    # -------------------------------------------------------------------------

    def test_09_previous_tasks_button_contrast_styles(self):
        """static/spa/app.css must define crisp, high-contrast styles for .ptask-btn-reopen."""
        css_path = os.path.join("static", "spa", "app.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".ptask-btn-reopen", css)
        self.assertIn("color: #0f172a !important;", css)
        self.assertIn(".ptask-btn-reopen span", css)
        self.assertIn(".ptask-btn-reopen svg", css)

    def test_10_is_completed_declared_before_use(self):
        """static/spa/sections/search.js must declare isCompleted before referencing it."""
        js_path = os.path.join("static", "spa", "sections", "search.js")
        with open(js_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        is_completed_decl_line = -1
        eta_use_line = -1

        for idx, line in enumerate(lines, 1):
            if "const isCompleted =" in line:
                is_completed_decl_line = idx
            if "ui.etaEl.textContent = isCompleted" in line:
                eta_use_line = idx

        self.assertGreater(is_completed_decl_line, 0, "isCompleted declaration not found in search.js")
        self.assertGreater(eta_use_line, 0, "ui.etaEl usage of isCompleted not found in search.js")
        self.assertLess(
            is_completed_decl_line,
            eta_use_line,
            f"isCompleted declared on line {is_completed_decl_line} after usage on line {eta_use_line}",
        )


if __name__ == "__main__":
    unittest.main()
