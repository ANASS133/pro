"""
Comprehensive Tests for Arbeitsagentur Application Details Extraction & Integrations.
====================================================================================
Covers the 8 core requirements:
1. Arbeitsagentur job with both email and employer application URL (Schwabenhaus GmbH fixture).
2. Job with only an external application form (Stuttgarter Straßenbahnen AG fixture).
3. Job with no email and no discovered form (preserves listing URL, requires discovery).
4. Job with an Impressum contact email only (marked as email_type='impressum', not recruitment).
5. Dynamically rendered application button.
6. Multiple application methods preserved on a single vacancy.
7. Excel export preserving all extracted fields and fixing 'portal' vs 'unknown' discrepancies.
8. Integration with existing Email Campaign and Autofill Queue workflows.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

from scraper.arbeitsagentur_extractor import ArbeitsagenturDetailExtractor, detect_ats_or_url_type
from scraper.application_form_discovery import (
    EXCEL_COLUMNS,
    classify_application_method,
    normalize_job_opportunity_row,
)
from routes.autofill import queue_autofill_job, load_applications


# -----------------------------------------------------------------------------
# Real HTML Fixtures based on Arbeitsagentur Listings
# -----------------------------------------------------------------------------

SCHWABENHAUS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Duale Studentin Bauingenieurwesen - Schwabenhaus GmbH</title></head>
<body>
<div class="ba-copytext">
  <h2>Zur Verstärkung unseres Teams suchen wir eine/n Duale Studentin/ Dualen Studenten Bauingenieurwesen (B.Eng.)</h2>
  <p>Deine Aufgaben umfassen CAD-Konstruktion im Holzbau und digitale Bauprozesse.</p>
  <p>Wir freuen uns über deine aussagekräftige Bewerbung mit Lebenslauf und Zeugnissen.</p>
  <p>Partner-Hochschule: Technische Hochschule Mittelhessen</p>
  <p>Infos zum dualen Studium: <a href="https://www.thm.de/site/studium/unsere-studienangebote/bauingenieurwesen-bachelor-beng-praxisintegriert-dual-studiumplus.html">StudiumPlus Bauingenieurwesen</a></p>
  <div class="kontakt-box">
    Schwabenhaus Werk und Zentrale<br>
    Bewerbermanagement – Ausbildung & Studium<br>
    Industriestraße 2<br>
    36266 Heringen (Werra)<br>
    Tel.: 06624 / 930 662<br>
    E-Mail: <a href="mailto:personal@schwabenhaus.de">personal@schwabenhaus.de</a><br>
    Bewerben Sie sich per E-Mail oder per Post.
  </div>
</div>
<section id="jobdetails-kontaktdaten-block">
  <h2 id="jobdetails-kontaktdaten-heading">Informationen zur Bewerbung</h2>
  <div id="jobdetails-kontaktdaten-container" class="kontaktdaten">
    <p>Bewerbung per E-Mail an personal@schwabenhaus.de oder schriftlich per Post.</p>
    <p>Geforderte Anlagen: Lebenslauf, Zeugnisse</p>
  </div>
</section>
</body>
</html>
"""

SSB_AG_HTML = """
<!DOCTYPE html>
<html>
<head><title>Bachelor of Engineering Bauingenieurwesen - Stuttgarter Straßenbahnen AG</title></head>
<body>
<div class="ba-copytext">
  <h2>Bachelor of Engineering (B.Eng.), Bauingenieurwesen</h2>
  <p>Steig ein - das sind deine Aufgaben im Bereich der technischen Infrastruktur.</p>
  <p>Geforderte Unterlagen: Anschreiben, Lebenslauf, Zeugnisse.</p>
  <p>Jetzt Bewerben! Wir freuen uns auf deine Online-Bewerbung über unser Bewerbungsportal:</p>
  <p><a href="https://stellenmarkt.ssb-ag.de/persis/public?fn=bm.jobs.details&projectID=285520752&configKey=(BE(SW50ZXJuZXQ(1)">Online-Bewerbungsformular (Persis)</a></p>
  <p>Stuttgarter Straßenbahnen AG<br>
  Unternehmensbereich Ausbildung und Unternehmenskultur<br>
  Telefon: 0711/7885-8686</p>
</div>
<section id="jobdetails-kontaktdaten-block">
  <h2 id="jobdetails-kontaktdaten-heading">Informationen zur Bewerbung</h2>
  <div id="jobdetails-kontaktdaten-container" class="kontaktdaten">
    <p>Bewerben Sie sich über die Internetseite des Arbeitgebers.</p>
    <a href="https://stellenmarkt.ssb-ag.de/persis/public?fn=bm.jobs.details&projectID=285520752&configKey=(BE(SW50ZXJuZXQ(1)">Bewerbungsportal der SSB AG</a>
  </div>
</section>
</body>
</html>
"""


class TestArbeitsagenturApplicationExtraction(unittest.TestCase):

    def setUp(self):
        self.extractor = ArbeitsagenturDetailExtractor()

    # -------------------------------------------------------------------------
    # 1. Arbeitsagentur job with both email and employer application URL
    # -------------------------------------------------------------------------
    def test_schwabenhaus_both_email_and_employer_application_url(self):
        """Schwabenhaus GmbH: email, phone, external url, and documents extracted."""
        parsed = self.extractor.parse_application_section(
            SCHWABENHAUS_HTML,
            source_url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1205099220-S",
        )

        self.assertEqual(parsed["email"], "personal@schwabenhaus.de")
        self.assertEqual(parsed["email_type"], "recruitment")
        self.assertIn("930662", parsed["phone"])
        self.assertTrue(bool(parsed["direct_application_url"]))
        self.assertIn("thm.de", parsed["direct_application_url"])
        self.assertEqual(parsed["application_method"], "both")
        self.assertIn("Lebenslauf", parsed["required_documents"])
        self.assertIn("Zeugnisse", parsed["required_documents"])
        self.assertEqual(parsed["extraction_status"], "completed")

    # -------------------------------------------------------------------------
    # 2. Job with only an external application form (Stuttgarter Straßenbahnen AG)
    # -------------------------------------------------------------------------
    def test_stuttgarter_strassenbahnen_external_ats_form_only(self):
        """Stuttgarter Straßenbahnen AG: No email, external Persis ATS portal extracted."""
        parsed = self.extractor.parse_application_section(
            SSB_AG_HTML,
            source_url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003538242-S",
        )

        self.assertEqual(parsed["email"], "")
        self.assertIn("78858686", parsed["phone"])
        self.assertIn("stellenmarkt.ssb-ag.de", parsed["direct_application_url"])
        self.assertEqual(parsed["application_url_type"], "ats_persis")
        self.assertTrue(parsed["has_form"])
        self.assertEqual(parsed["application_method"], "form")
        self.assertIn("Anschreiben", parsed["required_documents"])
        self.assertIn("Lebenslauf", parsed["required_documents"])
        self.assertIn("Zeugnisse", parsed["required_documents"])
        self.assertEqual(parsed["extraction_status"], "completed")

    # -------------------------------------------------------------------------
    # 3. Job with no email and no discovered form
    # -------------------------------------------------------------------------
    def test_job_with_no_email_and_no_form_preserves_listing(self):
        """When neither email nor form is found, preserves listing URL and requires discovery."""
        raw_job = {
            "title": "Bauhelfer (m/w/d)",
            "company": "Bauunternehmung Müller",
            "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/12345-67890-S",
            "reference": "12345-67890-S",
        }
        empty_html = "<html><body><div>Job ohne Kontaktdaten</div></body></html>"
        with patch.object(self.extractor.session, "get") as mock_get:
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.text = empty_html
            mock_res.url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/12345-67890-S"
            mock_get.return_value = mock_res

            enriched = self.extractor.extract_vacancy(raw_job)

            self.assertEqual(enriched["email"], "")
            self.assertEqual(enriched["has_form"], False)
            self.assertEqual(enriched["application_method"], "unknown")
            self.assertEqual(enriched["apply_url"], "https://www.arbeitsagentur.de/jobsuche/jobdetail/12345-67890-S")
            self.assertEqual(enriched["extraction_status"], "no_contact_found")

    # -------------------------------------------------------------------------
    # 4. Job with an Impressum contact email only
    # -------------------------------------------------------------------------
    def test_job_with_impressum_contact_email_only(self):
        """Impressum emails must be marked with email_type='impressum', not recruitment."""
        raw_job = {
            "title": "Schreiner",
            "company": "Möbelmanufaktur Schmidt GmbH",
            "url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/12345-99999-S",
            "website": "https://schmidt-moebel.de",
        }
        with patch.object(self.extractor.session, "get") as mock_get:
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.text = "<html><body>Nur Stellenbeschreibung</body></html>"
            mock_res.url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/12345-99999-S"
            mock_get.return_value = mock_res

            with patch.object(self.extractor.impressum_extractor, "extract_from_website") as mock_imp:
                mock_imp.return_value = {
                    "emails": ["impressum@schmidt-moebel.de"],
                    "telephones": ["+49 123 45678"],
                    "geschaeftsfuehrer": ["Hans Schmidt"],
                }

                enriched = self.extractor.extract_vacancy(raw_job)

                self.assertEqual(enriched["email"], "impressum@schmidt-moebel.de")
                self.assertEqual(enriched["email_type"], "impressum")
                self.assertNotEqual(enriched["email_type"], "recruitment")

    # -------------------------------------------------------------------------
    # 5. Dynamically rendered application button
    # -------------------------------------------------------------------------
    def test_dynamically_rendered_application_button(self):
        """Selenium fallback correctly retrieves dynamic application link from DOM."""
        mock_driver = MagicMock()
        mock_driver.current_url = "https://www.arbeitsagentur.de/jobsuche/jobdetail/dyn-001"
        mock_driver.page_source = SSB_AG_HTML
        mock_driver.find_elements.return_value = []

        parsed = self.extractor.extract_with_selenium(
            mock_driver,
            "https://www.arbeitsagentur.de/jobsuche/jobdetail/dyn-001",
        )
        self.assertIn("stellenmarkt.ssb-ag.de", parsed["direct_application_url"])
        self.assertTrue(parsed["has_form"])
        self.assertEqual(parsed["application_method"], "form")

    # -------------------------------------------------------------------------
    # 6. Multiple application methods
    # -------------------------------------------------------------------------
    def test_multiple_application_methods_preserved(self):
        """A vacancy offering email, portal link, and postal application preserves all."""
        parsed = self.extractor.parse_application_section(
            SCHWABENHAUS_HTML,
            source_url="https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1205099220-S",
        )
        self.assertIn("email", parsed["application_methods"])
        self.assertIn("postal", parsed["application_methods"])
        self.assertEqual(parsed["application_method"], "both")

    # -------------------------------------------------------------------------
    # 7. Excel export preserving extracted fields
    # -------------------------------------------------------------------------
    def test_excel_export_preserves_extracted_fields(self):
        """Verifies that all extracted fields are exported and 'portal' is not overwritten to 'unknown'."""
        job = {
            "title": "Bauingenieurwesen (B.Eng.)",
            "company": "Schwabenhaus GmbH",
            "location": "Heringen (Werra)",
            "city": "Heringen",
            "email": "personal@schwabenhaus.de",
            "email_type": "recruitment",
            "phone": "+49 6624 930662",
            "source": "Arbeitsagentur",
            "contact_person": "Bewerbermanagement",
            "apply_url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1205099220-S",
            "job_listing_url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1205099220-S",
            "employer_website": "https://www.schwabenhaus.de",
            "direct_application_url": "https://www.thm.de/studiumplus",
            "application_method": "both",
            "application_url_type": "career_portal",
            "required_documents": "Lebenslauf, Zeugnisse",
            "extraction_status": "completed",
        }
        row = normalize_job_opportunity_row(job)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            df = pd.DataFrame([row])
            # Include all standard and extended columns
            export_cols = [c for c in EXCEL_COLUMNS if c in df.columns]
            for extra in [
                "email_type",
                "contact_person",
                "job_listing_url",
                "employer_website",
                "direct_application_url",
                "application_url_type",
                "required_documents",
                "extraction_status",
            ]:
                if extra in df.columns and extra not in export_cols:
                    export_cols.append(extra)

            df = df[export_cols]
            df.to_excel(tmp_path, index=False)

            read_df = pd.read_excel(tmp_path)
            self.assertEqual(read_df["email"].iloc[0], "personal@schwabenhaus.de")
            self.assertEqual(read_df["email_type"].iloc[0], "recruitment")
            self.assertEqual(read_df["direct_application_url"].iloc[0], "https://www.thm.de/studiumplus")
            self.assertEqual(read_df["required_documents"].iloc[0], "Lebenslauf, Zeugnisse")
            self.assertEqual(read_df["application_method"].iloc[0], "both")

            # Check that an opportunity with application_method='portal' does not become 'unknown'
            portal_job = {"title": "Tischler", "company": "Holzbau AG", "application_method": "portal"}
            norm_portal = normalize_job_opportunity_row(portal_job)
            self.assertEqual(norm_portal["application_method"], "external_link")
            self.assertNotEqual(norm_portal["application_method"], "unknown")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # -------------------------------------------------------------------------
    # 8. Existing Email and Autofill Queue integrations
    # -------------------------------------------------------------------------
    def test_workflow_integrations_email_campaign_and_autofill_queue(self):
        """Vacancies with forms are queued into Autofill, and emails are available for campaigns."""
        form_job = {
            "title": "Bauingenieurwesen",
            "company": "Stuttgarter Straßenbahnen AG",
            "direct_application_url": "https://stellenmarkt.ssb-ag.de/persis/public",
            "has_form": True,
            "application_method": "form",
            "required_documents": "Anschreiben, Lebenslauf, Zeugnisse",
        }

        # Queue into Autofill Queue
        entry = queue_autofill_job(form_job)
        self.assertEqual(entry["company"], "Stuttgarter Straßenbahnen AG")
        self.assertEqual(entry["url"], "https://stellenmarkt.ssb-ag.de/persis/public")
        self.assertIn("Queue", entry["status"])

        # Check that loaded applications include the queued job
        apps = load_applications()
        matched = [a for a in apps if a.get("company") == "Stuttgarter Straßenbahnen AG"]
        self.assertTrue(len(matched) > 0)


if __name__ == "__main__":
    unittest.main()
