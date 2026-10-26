"""
Automated Regression Tests for:
Final Ausbildung Discovery Logic & Google Maps Mandatory Exception.

Tests:
1. Google Maps Mandatory Exception:
   - Always visits and inspects official website, regardless of email availability.
   - Missing website -> unconfirmed potential employer (not verified vacancy).
   - Inaccessible website -> unconfirmed potential employer (not verified vacancy).
   - Website with matching Ausbildung ad -> verified vacancy with extracted title, URL, email/form.
   - Website with NO matching Ausbildung ad -> unconfirmed potential employer.
2. Job Portals Rule:
   - Email first -> saved alongside job info.
   - Missing email -> discovers application form.
   - Missing both -> preserves opportunity.
3. Excel Export:
   - Sheet 1 (Ausbildungsplätze): Exactly 21 columns in exact order.
   - Sheet 2 (Unbestätigte Betriebe (Maps)): Separately identifies unconfirmed Google Maps employers.
   - No unconfirmed Google Maps company classified as active Ausbildung provider in Sheet 1.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import openpyxl
import pandas as pd

from app import (
    _prepare_download_jobs,
    _save_auto_extraction_export_records,
)
from scraper.application_form_discovery import EXCEL_COLUMNS, FormDiscoveryResult
from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
from scraper.working_email_extractor import WorkingEmailExtractor


class TestGoogleMapsAusbildungException(unittest.TestCase):

    def setUp(self):
        self.verifier = GoogleMapsAusbildungVerifier(timeout=5)

    def test_gmaps_missing_website_retained_as_unconfirmed(self):
        """A Google Maps company without a website is retained as unconfirmed employer."""
        biz = {
            "name": "Restaurant Münsterland",
            "address": "Markt 5, 48683 Ahaus",
            "phone": "02561 9999",
            "website": "",
            "source": "Google Maps",
        }
        res = self.verifier.verify_business(biz, profession_keyword="Koch")
        self.assertFalse(res.get("is_verified_vacancy"))
        self.assertEqual(res.get("verification_status"), "missing_website")
        self.assertIn("Keine Website", res.get("status", ""))

    def test_gmaps_inaccessible_website_records_unsuccessful_verification(self):
        """Inaccessible website must record verification unsuccessful, not assumed valid."""
        biz = {
            "name": "Gasthof Zur Mühle",
            "address": "Mühlenweg 1, 48683 Ahaus",
            "phone": "02561 1111",
            "website": "https://www.flaky-broken-hotel-xyz.de",
            "source": "Google Maps",
        }
        with patch.object(self.verifier, "_fetch_page", return_value=None):
            res = self.verifier.verify_business(biz, profession_keyword="Koch")
            self.assertFalse(res.get("is_verified_vacancy"))
            self.assertEqual(res.get("verification_status"), "inaccessible_website")
            self.assertIn("nicht erreichbar", res.get("status", ""))

    def test_gmaps_matching_ausbildung_verified_with_email(self):
        """Company with matching Ausbildung on website and contact email is confirmed."""
        biz = {
            "name": "Hotel & Restaurant Am See",
            "address": "Seestr. 10, 48683 Ahaus",
            "phone": "02561 2222",
            "website": "https://www.hotel-am-see-ahaus.de",
            "source": "Google Maps",
        }
        sample_html = """
        <html>
            <body>
                <h1>Willkommen im Hotel Am See</h1>
                <nav><a href="/karriere">Karriere & Ausbildung</a></nav>
            </body>
        </html>
        """
        career_html = """
        <html>
            <body>
                <h2>Unsere Stellenangebote</h2>
                <div class="job-card">
                    <h3>Ausbildung zum Koch (m/w/d) 2026</h3>
                    <p>Werde Teil unseres Küchenteams! Bewerbungen bitte an: karriere@hotel-am-see-ahaus.de</p>
                    <a href="/jobs/koch-ausbildung">Details zur Ausbildung</a>
                </div>
            </body>
        </html>
        """

        def mock_fetch(url):
            if "karriere" in url:
                return career_html
            return sample_html

        with patch.object(self.verifier, "_fetch_page", side_effect=mock_fetch):
            res = self.verifier.verify_business(biz, profession_keyword="Koch")
            self.assertTrue(res.get("is_verified_vacancy"))
            self.assertEqual(res.get("verification_status"), "verified_ausbildung")
            self.assertIn("Koch", res.get("title", ""))
            self.assertEqual(res.get("email"), "karriere@hotel-am-see-ahaus.de")
            self.assertTrue(res.get("email_extracted"))

    def test_gmaps_matching_ausbildung_without_email_discovers_form(self):
        """Company with matching Ausbildung but no email discovers online application form."""
        biz = {
            "name": "Gourmet Catering Ahaus",
            "address": "Industriestr. 4, 48683 Ahaus",
            "website": "https://www.gourmet-catering.de",
            "source": "Google Maps",
        }
        sample_html = """
        <html>
            <body>
                <h1>Gourmet Catering</h1>
                <div class="job-item">
                    <h3>Auszubildender Koch (m/w/d) gesucht</h3>
                    <a href="https://jobs.personio.de/apply/12345">Jetzt online bewerben</a>
                </div>
            </body>
        </html>
        """
        mock_discovery = FormDiscoveryResult(
            status="verified_form",
            has_form=True,
            form_link="https://jobs.personio.de/apply/12345",
            bewerbung_link="https://jobs.personio.de/apply/12345",
        )

        with patch.object(self.verifier, "_fetch_page", return_value=sample_html):
            with patch.object(self.verifier.form_discovery, "discover_application_form", return_value=mock_discovery):
                res = self.verifier.verify_business(biz, profession_keyword="Koch")
                self.assertTrue(res.get("is_verified_vacancy"))
                self.assertTrue(res.get("has_form"))
                self.assertEqual(res.get("form_link"), "https://jobs.personio.de/apply/12345")
                self.assertEqual(res.get("application_method"), "form")

    def test_gmaps_website_with_no_matching_ausbildung_retained_as_unconfirmed(self):
        """Company website that has no matching Ausbildung is retained as unconfirmed."""
        biz = {
            "name": "Steuerberatung Müller",
            "address": "Bahnhofstr. 8, 48683 Ahaus",
            "website": "https://www.steuer-mueller-ahaus.de",
            "source": "Google Maps",
        }
        career_html = """
        <html>
            <body>
                <h2>Karriere</h2>
                <div class="job-item">Ausbildung Steuerfachangestellte (m/w/d)</div>
                <div class="job-item">Bilanzbuchhalter (m/w/d)</div>
            </body>
        </html>
        """
        with patch.object(self.verifier, "_fetch_page", return_value=career_html):
            res = self.verifier.verify_business(biz, profession_keyword="Koch")
            self.assertFalse(res.get("is_verified_vacancy"))
            self.assertEqual(res.get("verification_status"), "no_matching_ausbildung")
            self.assertIn("Keine passende", res.get("status", ""))

    def test_job_portal_email_first_rule(self):
        """Job portal with existing email does not run heavy form crawling; saves email directly."""
        extractor = WorkingEmailExtractor(captcha_userid="", captcha_apikey="")
        portal_job = {
            "title": "Ausbildung zum Koch (m/w/d)",
            "company": "Hotel Central",
            "location": "48683 Ahaus",
            "city": "Ahaus",
            "source": "Arbeitsagentur",
            "url": "https://www.arbeitsagentur.de/job/12345",
        }

        with patch.object(extractor, "open_job"):
            with patch.object(extractor, "is_blocked_page", return_value=False):
                with patch.object(extractor, "check_for_captcha", return_value=False):
                    with patch.object(extractor, "extract_contact_info", return_value=("bewerbung@hotel-central.de", "02561 123", "Herr Meyer")):
                        with patch.object(extractor, "extract_application_link", return_value="https://www.hotel-central.de"):
                            with patch.object(extractor.form_discovery, "discover_application_form") as mock_disc:
                                processed = extractor.process_job(portal_job)
                                # Email first: form discovery was skipped because email was found
                                mock_disc.assert_not_called()
                                self.assertEqual(processed.get("email"), "bewerbung@hotel-central.de")
                                self.assertEqual(processed.get("application_method"), "email")
                                self.assertFalse(processed.get("has_form"))

    def test_job_portal_missing_email_discovers_application_form(self):
        """Job portal without email inspects website and discovers application form."""
        extractor = WorkingEmailExtractor(captcha_userid="", captcha_apikey="")
        portal_job = {
            "title": "Koch / Köchin Ausbildung 2026",
            "company": "Residenz Hotel",
            "location": "48683 Ahaus",
            "city": "Ahaus",
            "source": "Ausbildung.de",
            "url": "https://www.ausbildung.de/berufe/koch/stellen/123",
        }
        mock_discovery = FormDiscoveryResult(
            status="verified_form",
            has_form=True,
            form_link="https://residenz.softgarden.io/apply",
            bewerbung_link="https://residenz.softgarden.io/apply",
        )

        with patch.object(extractor, "open_job"):
            with patch.object(extractor, "is_blocked_page", return_value=False):
                with patch.object(extractor, "check_for_captcha", return_value=False):
                    with patch.object(extractor, "extract_contact_info", return_value=(None, "02561 987", None)):
                        with patch.object(extractor, "extract_application_link", return_value="https://residenz.softgarden.io/apply"):
                            with patch.object(extractor.form_discovery, "discover_application_form", return_value=mock_discovery):
                                processed = extractor.process_job(portal_job)
                                self.assertEqual(processed.get("email"), "")
                                self.assertTrue(processed.get("has_form"))
                                self.assertEqual(processed.get("form_link"), "https://residenz.softgarden.io/apply")
                                self.assertEqual(processed.get("application_method"), "form")

    def test_excel_export_multi_sheet_and_21_columns(self):
        """Excel export writes verified vacancies into Sheet 1 (21 columns) and unconfirmed Maps in Sheet 2."""
        verified_portal_job = {
            "title": "Ausbildung zum Koch (m/w/d)",
            "company": "Gasthof Epe",
            "location": "48599 Gronau",
            "city": "Gronau",
            "published_date": "2026-10-20",
            "start_date": "2026-08-01",
            "hauptberuf": "Koch",
            "email": "info@gasthof-epe.de",
            "phone": "02565 111",
            "source": "Arbeitsagentur",
            "arbeitsgeber": "Herr Schulte",
            "apply_url": "https://www.gasthof-epe.de",
            "form_link": "",
            "has_form": False,
            "application_method": "email",
            "bewerbung_art": "E-Mail",
            "bewerbung_link": "https://www.gasthof-epe.de",
            "anrede": "Herr Schulte",
            "vacancies": "1 Platz",
            "scraped_at": "2026-10-26 10:00:00",
            "salary": "1.100 €",
        }

        verified_gmaps_job = {
            "title": "Ausbildung Koch 2026",
            "company": "Brauhaus Ahaus",
            "location": "48683 Ahaus",
            "city": "Ahaus",
            "published_date": "k. A.",
            "start_date": "nach Absprache",
            "hauptberuf": "Koch",
            "email": "brauhaus@ahaus.de",
            "phone": "02561 333",
            "source": "Google Maps",
            "is_verified_vacancy": True,
            "apply_url": "https://www.brauhaus-ahaus.de/karriere",
            "form_link": "",
            "has_form": False,
            "application_method": "email",
            "bewerbung_art": "E-Mail",
            "bewerbung_link": "https://www.brauhaus-ahaus.de/karriere",
            "anrede": "Sehr geehrte Damen und Herren",
            "vacancies": "1",
            "scraped_at": "2026-10-26 10:00:00",
            "salary": "k. A.",
        }

        unconfirmed_gmaps_biz = {
            "company": "Café Central Ahaus",
            "location": "Markt 2, 48683 Ahaus",
            "city": "Ahaus",
            "website": "https://www.cafe-central.de",
            "email": "kontakt@cafe-central.de",
            "phone": "02561 555",
            "source": "Google Maps",
            "is_verified_vacancy": False,
            "status": "Unbestätigt: Keine offene Ausbildung gefunden",
            "verification_notes": "Website geprüft, keine offene Stelle für Koch gefunden",
            "maps_url": "https://maps.google.com/?cid=123",
        }

        all_records = [verified_portal_job, verified_gmaps_job, unconfirmed_gmaps_biz]

        excel_path = _save_auto_extraction_export_records(
            records=all_records,
            keyword="Ausbildung zum Koch",
            fallback_slug="test_multi_sheet",
        )
        self.assertTrue(Path(excel_path).exists())

        # Inspect Excel workbook structure
        wb = openpyxl.load_workbook(str(excel_path))
        sheet_names = wb.sheetnames

        self.assertIn("Ausbildungsplätze", sheet_names)
        self.assertIn("Unbestätigte Betriebe (Maps)", sheet_names)

        # Inspect Sheet 1: Exactly 21 columns
        sheet1 = wb["Ausbildungsplätze"]
        headers1 = [cell.value for cell in sheet1[1]]
        self.assertEqual(headers1, EXCEL_COLUMNS)
        self.assertEqual(len(headers1), 21)

        # Sheet 1 must contain the 2 verified vacancies and NOT the unconfirmed café
        sheet1_companies = [sheet1.cell(row=r, column=2).value for r in range(2, sheet1.max_row + 1)]
        self.assertIn("Gasthof Epe", sheet1_companies)
        self.assertIn("Brauhaus Ahaus", sheet1_companies)
        self.assertNotIn("Café Central Ahaus", sheet1_companies)

        # Sheet 2 must contain the unconfirmed Google Maps company
        sheet2 = wb["Unbestätigte Betriebe (Maps)"]
        sheet2_companies = [sheet2.cell(row=r, column=1).value for r in range(2, sheet2.max_row + 1)]
        self.assertIn("Café Central Ahaus", sheet2_companies)

        wb.close()
        try:
            os.remove(excel_path)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
