import unittest
from unittest.mock import MagicMock, patch
from app import app, _fetch_combined_jobs
from services.profession_intelligence import profession_intelligence


class TestSimplifiedSearchEmailsUI(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = app.test_client()
        self.app.config["TESTING"] = True

    def test_app_shell_simplified_structure(self):
        """Verify the simplified search structure in templates/app_shell.html."""
        with open("templates/app_shell.html", "r", encoding="utf-8") as f:
            html = f.read()

        # 1. Primary visible search inputs
        self.assertIn('id="keyword"', html)
        self.assertIn('id="location"', html)
        self.assertIn('id="search_source_1"', html)
        self.assertIn('id="search_btn_1"', html)

        # 2. Search Source options inside the form
        self.assertIn('value="all"', html)
        self.assertIn('value="job_portals"', html)
        self.assertIn('value="google_maps"', html)

        # 3. AI Employer Detection section (minimal & elegant)
        self.assertIn('id="ai_employer_detection_section"', html)
        self.assertIn('AI Employer Detection', html)
        self.assertIn('id="prof_summary_badge"', html)
        self.assertIn('id="toggle_custom_categories_btn"', html)
        self.assertIn('id="custom_categories_drawer"', html)
        self.assertIn('id="new_custom_category_input"', html)
        self.assertIn('id="add_custom_category_btn"', html)
        self.assertIn('id="restore_default_categories_btn"', html)
        self.assertIn('id="employer_categories_chips"', html)
        self.assertIn('id="custom_categories"', html)

        # 4. Hidden backward compatibility elements (to prevent JS null errors)
        self.assertIn('id="auto_categories_toggle"', html)
        self.assertIn('id="prof_recognized_name"', html)
        self.assertIn('id="prof_sector_name"', html)
        self.assertIn('id="geo_coverage_indicator"', html)

        # 5. Advanced Filters items
        self.assertIn('id="advanced_filters_toggle"', html)
        self.assertIn('id="advanced_filters_content"', html)
        self.assertIn('id="filter_item_published_since"', html)
        self.assertIn('id="filter_item_radius"', html)
        self.assertIn('name="published_since"', html)
        self.assertIn('name="radius"', html)

        # 6. Verify Opportunity Scope is NOT in the UI
        self.assertNotIn('name="search_scope"', html)
        self.assertNotIn('Opportunity Scope', html)

    def test_search_js_source_toggling_logic(self):
        """Verify JavaScript functions for source toggling, chip customization, and restore."""
        with open("static/spa/sections/search.js", "r", encoding="utf-8") as f:
            js = f.read()

        # Source change visibility logic
        self.assertIn('handleSearchSourceChange', js)
        self.assertIn('filter_item_published_since', js)
        self.assertIn('ai_employer_detection_section', js)

        # Custom categories handlers
        self.assertIn('addCustomCategoryAction', js)
        self.assertIn('restore_default_categories_btn', js)
        self.assertIn('defaultCategoriesList', js)
        self.assertIn('activeCategoriesList', js)

    def test_automatic_profession_classification(self):
        """Verify the underlying profession intelligence engine works accurately."""
        res = profession_intelligence.classify_profession("Fachinformatiker", "Berlin")
        self.assertIsNotNone(res)
        self.assertEqual(res.get("normalized_profession"), "Fachinformatiker")
        self.assertTrue(len(res.get("employer_categories", [])) > 0)

        # Test synonym & typo normalization
        res_typo = profession_intelligence.classify_profession("fachinforamtiker", "Hamburg")
        self.assertEqual(res_typo.get("normalized_profession"), "Fachinformatiker")

    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", return_value=[])
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", return_value=[])
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", return_value=[])
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", return_value=[])
    @patch("scraper.overpass_scraper.OverpassBusinessScraper.search_businesses")
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs")
    def test_job_portals_only_search(
        self, mock_fetch_aa, mock_overpass, mock_ausb_de, mock_azubiyo, mock_aubi, mock_ihk
    ):
        """Test search with source='job_portals'."""
        mock_fetch_aa.return_value = [
            {"title": "Softwareentwickler", "company": "Co", "city": "Berlin", "source": "Arbeitsagentur"}
        ]
        jobs = _fetch_combined_jobs(
            keyword="Softwareentwickler",
            location="Berlin",
            source="job_portals",
            mode="arbeit",
            max_jobs=5,
        )
        self.assertTrue(mock_fetch_aa.called)
        self.assertFalse(mock_overpass.called, "Google Maps/Overpass should NOT be executed when source is job_portals")

    @patch("scraper.overpass_scraper.OverpassBusinessScraper.search_businesses")
    @patch("scraper.google_maps_ausbildung_verifier.GoogleMapsAusbildungVerifier.verify_business")
    def test_google_maps_only_search_with_custom_categories(self, mock_verify, mock_overpass):
        """Test search with source='google_maps' and custom_categories parameter."""
        mock_overpass.return_value = [
            {"name": "Custom Agency", "city": "München", "website": "https://agency.de"}
        ]
        mock_verify.return_value = {
            "title": "Ausbildung Fachinformatiker",
            "company": "Custom Agency",
            "city": "München",
            "source": "Google Maps (Verifiziert)",
            "is_verified_vacancy": True,
            "apply_url": "https://agency.de/jobs",
        }

        jobs = _fetch_combined_jobs(
            keyword="Fachinformatiker",
            location="München",
            source="google_maps",
            mode="ausbildung",
            custom_categories=["IT-Consulting", "Softwarehaus"],
            max_jobs=5,
        )
        self.assertTrue(len(jobs) >= 1)
        self.assertEqual(jobs[0]["company"], "Custom Agency")

    def test_search_stream_parameter_contracts(self):
        """Test /api/search/stream endpoint accepts the simplified parameters."""
        response = self.client.get(
            "/api/search/stream?keyword=Koch&location=Köln&source=all&mode=ausbildung&radius=10&auto_categories=true"
        )
        # Endpoint returns an SSE stream (200 OK)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("text/event-stream" in response.content_type)


if __name__ == "__main__":
    unittest.main()
