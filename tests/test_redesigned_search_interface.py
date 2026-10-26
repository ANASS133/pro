import io
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

from app import app, _fetch_combined_jobs


class TestRedesignedSearchInterface(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = app.test_client()
        self.app.config["TESTING"] = True

    # -------------------------------------------------------------------------
    # Scenario A: Ausbildung mode + all sources
    # -------------------------------------------------------------------------
    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", return_value=[])
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", return_value=[])
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", return_value=[])
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", return_value=[])
    @patch("scraper.overpass_scraper.OverpassBusinessScraper.search_businesses")
    @patch("scraper.google_maps_ausbildung_verifier.GoogleMapsAusbildungVerifier.verify_business")
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs")
    def test_scenario_a_ausbildung_all_sources(
        self, mock_fetch_aa, mock_verify_ausb, mock_overpass, mock_ausb_de, mock_azubiyo, mock_aubi, mock_ihk
    ):
        mock_fetch_aa.return_value = [
            {
                "title": "Ausbildung zum Fachinformatiker",
                "company": "Tech AG",
                "city": "Ahaus",
                "source": "Arbeitsagentur",
                "email": "ausbildung@tech.de",
                "apply_url": "https://tech.de/karriere",
            }
        ]
        mock_overpass.return_value = [
            {"name": "Muster Betrieb", "city": "Ahaus", "website": "https://muster-ahaus.de"}
        ]
        mock_verify_ausb.return_value = {
            "title": "Ausbildung Fachinformatiker Anwendungsentwicklung",
            "company": "Muster Betrieb",
            "city": "Ahaus",
            "source": "Google Maps (Verifiziert)",
            "is_verified_vacancy": True,
            "apply_url": "https://muster-ahaus.de/karriere",
            "email": "jobs@muster-ahaus.de",
        }

        jobs = _fetch_combined_jobs(
            keyword="Fachinformatiker",
            location="Ahaus",
            source="all",
            mode="ausbildung",
            max_jobs=10,
        )

        self.assertTrue(len(jobs) >= 2)
        # Verify Arbeitsagentur called with angebotsart=4 (Ausbildung)
        self.assertTrue(mock_fetch_aa.called)
        _, kwargs = mock_fetch_aa.call_args
        self.assertEqual(kwargs.get("angebotsart"), 4)
        # Verify Google Maps Ausbildung verifier was called
        self.assertTrue(mock_verify_ausb.called)

    # -------------------------------------------------------------------------
    # Scenario B: Arbeit mode + all sources
    # -------------------------------------------------------------------------
    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", return_value=[])
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", return_value=[])
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", return_value=[])
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", return_value=[])
    @patch("scraper.overpass_scraper.OverpassBusinessScraper.search_businesses")
    @patch("scraper.google_maps_ausbildung_verifier.GoogleMapsAusbildungVerifier.verify_business_for_arbeit")
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs")
    def test_scenario_b_arbeit_all_sources(
        self, mock_fetch_aa, mock_verify_arbeit, mock_overpass, mock_ausb_de, mock_azubiyo, mock_aubi, mock_ihk
    ):
        mock_fetch_aa.return_value = [
            {
                "title": "Senior Softwareentwickler",
                "company": "Berlin Tech GmbH",
                "city": "Berlin",
                "source": "Arbeitsagentur",
                "email": "jobs@berlin-tech.de",
                "apply_url": "https://berlin-tech.de/jobs",
            }
        ]
        mock_overpass.return_value = [
            {"name": "Berlin IT Solutions", "city": "Berlin", "website": "https://berlin-it.de"}
        ]
        mock_verify_arbeit.return_value = {
            "title": "Softwareentwickler - Berlin IT Solutions",
            "company": "Berlin IT Solutions",
            "city": "Berlin",
            "source": "Google Maps (Arbeitgeber)",
            "email": "kontakt@berlin-it.de",
            "apply_url": "https://berlin-it.de",
        }

        jobs = _fetch_combined_jobs(
            keyword="Softwareentwickler",
            location="Berlin",
            source="all",
            mode="arbeit",
            max_jobs=10,
        )

        self.assertTrue(len(jobs) >= 2)
        # Verify Arbeitsagentur called with angebotsart=1 (Arbeit)
        self.assertTrue(mock_fetch_aa.called)
        _, kwargs = mock_fetch_aa.call_args
        self.assertEqual(kwargs.get("angebotsart"), 1)
        # Verify Google Maps verify_business_for_arbeit was called
        self.assertTrue(mock_verify_arbeit.called)

    # -------------------------------------------------------------------------
    # Scenario C: Nur Jobbörsen (Google Maps must not be called)
    # -------------------------------------------------------------------------
    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", return_value=[])
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", return_value=[])
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", return_value=[])
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", return_value=[])
    @patch("scraper.overpass_scraper.OverpassBusinessScraper.search_businesses")
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs")
    def test_scenario_c_job_portals_only(
        self, mock_fetch_aa, mock_overpass, mock_ausb_de, mock_azubiyo, mock_aubi, mock_ihk
    ):
        mock_fetch_aa.return_value = []

        _fetch_combined_jobs(
            keyword="Koch",
            location="München",
            source="job_portals",
            mode="ausbildung",
            max_jobs=5,
        )

        self.assertTrue(mock_fetch_aa.called)
        self.assertFalse(mock_overpass.called, "Google Maps/Overpass should NOT be executed when source is job_portals")

    # -------------------------------------------------------------------------
    # Scenario D: Nur Google Maps (Portals must not be called)
    # -------------------------------------------------------------------------
    @patch("scraper.overpass_scraper.OverpassBusinessScraper.search_businesses")
    @patch("scraper.google_maps_ausbildung_verifier.GoogleMapsAusbildungVerifier.verify_business_for_arbeit")
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs")
    def test_scenario_d_google_maps_only(self, mock_fetch_aa, mock_verify_arbeit, mock_overpass):
        mock_overpass.return_value = [
            {"name": "Lokale Firma", "city": "Köln", "website": "https://lokale-firma.de"}
        ]
        mock_verify_arbeit.return_value = {
            "title": "Industriekaufmann - Lokale Firma",
            "company": "Lokale Firma",
            "city": "Köln",
            "source": "Google Maps (Arbeitgeber)",
            "email": "kontakt@lokale-firma.de",
            "apply_url": "https://lokale-firma.de",
        }

        jobs = _fetch_combined_jobs(
            keyword="Industriekaufmann",
            location="Köln",
            source="google_maps",
            mode="arbeit",
            max_jobs=5,
        )

        self.assertFalse(mock_fetch_aa.called, "Arbeitsagentur should NOT be executed when source is google_maps")
        self.assertTrue(mock_overpass.called, "Google Maps search_businesses should be executed when source is google_maps")
        self.assertEqual(len(jobs), 1)

    # -------------------------------------------------------------------------
    # Scenario E: Empty location (Nationwide)
    # -------------------------------------------------------------------------
    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", return_value=[])
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", return_value=[])
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", return_value=[])
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", return_value=[])
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs")
    def test_scenario_e_empty_location(self, mock_fetch_aa, mock_ausb_de, mock_azubiyo, mock_aubi, mock_ihk):
        mock_fetch_aa.return_value = [
            {
                "title": "Softwareentwickler Remote",
                "company": "Deutschlandweit GmbH",
                "city": "",
                "source": "Arbeitsagentur",
                "email": "jobs@deutschlandweit.de",
            }
        ]

        jobs = _fetch_combined_jobs(
            keyword="Softwareentwickler",
            location="",
            source="job_portals",
            mode="arbeit",
            radius="25",  # Radius given without location
            max_jobs=5,
        )

        self.assertTrue(mock_fetch_aa.called)
        _, kwargs = mock_fetch_aa.call_args
        # Location None means nationwide search in Arbeitsagentur
        self.assertIn(kwargs.get("location"), ["", None])
        self.assertTrue(len(jobs) >= 1)

    # -------------------------------------------------------------------------
    # Scenario F: Excel export with canonical 21 columns
    # -------------------------------------------------------------------------
    def test_scenario_f_excel_export_schema(self):
        from app import search_cache

        canonical_columns = [
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

        # Seed sample job into search_cache
        search_cache["jobs"] = [
            {
                "title": "Fachinformatiker Anwendungsentwicklung",
                "company": "Beispiel GmbH",
                "location": "Berlin",
                "city": "Berlin",
                "published_date": "2026-10-20",
                "start_date": "2026-09-01",
                "hauptberuf": "Fachinformatiker/in",
                "email": "bewerbung@beispiel.de",
                "phone": "+49 30 123456",
                "source": "Ausbildung.de",
                "arbeitsgeber": "Frau Schmidt",
                "apply_url": "https://beispiel.de/stellen",
                "form_link": "https://beispiel.de/apply",
                "has_form": True,
                "application_method": "both",
                "bewerbung_art": "Online",
                "bewerbung_link": "https://beispiel.de/apply",
                "anrede": "Frau Schmidt",
                "vacancies": 2,
                "scraped_at": "2026-10-26",
                "salary": "1100 €",
            }
        ]

        response = self.client.get("/api/search/download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response.content_type)

        excel_data = io.BytesIO(response.data)
        df = pd.read_excel(excel_data, sheet_name=0)
        exported_cols = list(df.columns)
        self.assertEqual(exported_cols, canonical_columns, "Exported columns must match the 21 canonical columns in exact order")

    # -------------------------------------------------------------------------
    # Scenario G: Template & UI Specification Checks
    # -------------------------------------------------------------------------
    def test_scenario_g_template_elements(self):
        with open("templates/app_shell.html", "r", encoding="utf-8") as f:
            content = f.read()

        # Row 1: Mode segmented control with Ausbildung / Arbeit
        self.assertIn('name="mode"', content)
        self.assertIn('value="ausbildung"', content)
        self.assertIn('value="arbeit"', content)
        self.assertIn('class="segmented-control"', content)

        # Row 2: Profession / Keyword
        self.assertIn('id="keyword"', content)
        self.assertIn('Beruf oder Stichwort', content)

        # Row 3: City / Postal Code
        self.assertIn('id="location"', content)
        self.assertIn('Stadt oder PLZ', content)

        # Row 4: Collapsible Advanced Filters
        self.assertIn('id="advanced_filters_toggle"', content)
        self.assertIn('id="advanced_filters_content"', content)
        self.assertIn('Erweiterte Filter', content)

        # Search Sources options
        self.assertIn('value="all"', content)
        self.assertIn('value="job_portals"', content)
        self.assertIn('value="google_maps"', content)

        # Publication Period options
        self.assertIn('value="7days"', content)
        self.assertIn('value="14days"', content)
        self.assertIn('value="30days"', content)

        # Radius options
        self.assertIn('name="radius"', content)
        self.assertIn('value="5"', content)
        self.assertIn('value="10"', content)
        self.assertIn('value="25"', content)
        self.assertIn('value="50"', content)
        self.assertIn('value="100"', content)

        # Row 5: Prominent search button
        self.assertIn('id="search_btn_1"', content)
        self.assertIn('Suche starten', content)

        # Confirm no duplicate second search card
        self.assertNotIn('id="search_form_2"', content)
        self.assertNotIn('id="keyword_2"', content)


if __name__ == "__main__":
    unittest.main()
