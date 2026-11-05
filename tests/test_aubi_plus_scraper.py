import unittest
from unittest.mock import MagicMock, patch
import bs4
from app import app
from scraper.aubi_plus_scraper import AubiPlusScraper

MOCK_AUBI_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="col-12">
    <div class="bg-white position-relative p-4 rounded-3 h-100 shadow-sm">
      <h2>Fachinformatiker Anwendungsentwicklung (m/w/d)</h2>
      <a href="/premium/muster-gmbh-1234/">Muster GmbH &amp; Co. KG</a>
      <div>50668 Köln</div>
      <div>Start: 01.09.2025</div>
      <a href="/ausbildung/fachinformatiker-anwendungsentwicklung-koeln-muster-gmbh-56789/">Zur Bewerbung</a>
    </div>
  </div>
  <div class="col-12">
    <div class="bg-white position-relative p-4 rounded-3 h-100 shadow-sm">
      <h2>Kaufmann fuer Bueromanagement (m/w/d)</h2>
      <img src="/logo.png" alt="Logo Bürohelden GmbH" />
      <div>10115 Berlin</div>
      <div>Start: 01.08.2025</div>
      <a href="/ausbildung/kaufmann-bueromanagement-berlin-buerohelden-11223/">Zur Bewerbung</a>
    </div>
  </div>
</body>
</html>
"""


class AubiPlusScraperTestCase(unittest.TestCase):
    def setUp(self):
        self.scraper = AubiPlusScraper()

    def test_parse_cards_standard(self):
        soup = bs4.BeautifulSoup(MOCK_AUBI_HTML, "html.parser")
        cards = soup.find_all("div", class_=lambda c: c and "bg-white" in c and "position-relative" in c)
        jobs = self.scraper._parse_cards(cards, search_keyword="")

        self.assertEqual(len(jobs), 2)

        # Job 1 - Köln
        j1 = jobs[0]
        self.assertEqual(j1["title"], "Fachinformatiker Anwendungsentwicklung (m/w/d)")
        self.assertEqual(j1["company"], "Muster GmbH & Co. KG")
        self.assertEqual(j1["postal_code"], "50668")
        self.assertEqual(j1["city"], "Köln")
        self.assertEqual(j1["start_date"], "01.09.2025")
        self.assertEqual(j1["source"], "aubi-plus.de")
        self.assertTrue(j1["url"].startswith("https://www.aubi-plus.de/ausbildung/fachinformatiker"))

        # Job 2 - Berlin
        j2 = jobs[1]
        self.assertEqual(j2["title"], "Kaufmann fuer Bueromanagement (m/w/d)")
        self.assertEqual(j2["company"], "Bürohelden GmbH")
        self.assertEqual(j2["postal_code"], "10115")
        self.assertEqual(j2["city"], "Berlin")
        self.assertEqual(j2["start_date"], "01.08.2025")
        self.assertEqual(j2["source"], "aubi-plus.de")

    @patch("requests.Session.get")
    def test_empty_location_nationwide_search(self, mock_get):
        """1. Empty Location: Searches all of Germany and does not send aSuggest."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_AUBI_HTML
        mock_get.return_value = mock_resp

        results = self.scraper.fetch_jobs(keyword="Informatik", location="", max_jobs=10)
        self.assertEqual(len(results), 2)

        # Verify query parameters in request: aSuggest must NOT be sent
        self.assertTrue(mock_get.called)
        params_used = mock_get.call_args[1]["params"]
        self.assertEqual(params_used["mSuggest"], "Informatik")
        self.assertNotIn("aSuggest", params_used)

        # Verify metadata
        self.assertEqual(self.scraper.last_search_meta["original_location"], "")
        self.assertEqual(self.scraper.last_search_meta["normalized_location"], "")
        self.assertFalse(self.scraper.last_search_meta["fallback_triggered"])
        self.assertEqual(self.scraper.last_search_meta["final_accepted_results"], 2)

    @patch("requests.Session.get")
    def test_berlin_results_only(self, mock_get):
        """2. Explicit Location (Berlin): Returns only jobs matching Berlin."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_AUBI_HTML
        mock_get.return_value = mock_resp

        # MOCK_AUBI_HTML contains 1 Köln job and 1 Berlin job
        results = self.scraper.fetch_jobs(keyword="Informatik", location="Berlin", max_jobs=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["city"], "Berlin")
        self.assertEqual(results[0]["postal_code"], "10115")

        # Verify aSuggest was passed for explicit location
        params_used = mock_get.call_args[1]["params"]
        self.assertEqual(params_used["aSuggest"], "Berlin")
        self.assertEqual(self.scraper.last_search_meta["rejected_by_location"], 1)

    @patch.object(AubiPlusScraper, "_fetch_pages")
    def test_berlin_zero_local_results_nationwide_fallback_strict_filtering(self, mock_fetch_pages):
        """3. Zero Results: Nationwide fallback is queried, then strict Berlin filtering is applied."""
        mock_fetch_pages.side_effect = [
            [],  # Initial Berlin search returns 0
            [  # Nationwide fallback returns 3 jobs across Germany
                {"title": "Dev Berlin", "city": "Berlin", "postal_code": "10178", "location": "10178 Berlin"},
                {"title": "Dev Hamburg", "city": "Hamburg", "postal_code": "20095", "location": "20095 Hamburg"},
                {"title": "Dev München", "city": "München", "postal_code": "80331", "location": "80331 München"},
            ],
        ]

        jobs = self.scraper.fetch_jobs(keyword="Fachinformatiker", location="Berlin", max_jobs=10)

        # Only the Berlin job must be accepted; Hamburg and München must be excluded
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Dev Berlin")
        self.assertEqual(jobs[0]["city"], "Berlin")

        # Check metadata
        meta = self.scraper.last_search_meta
        self.assertTrue(meta["fallback_triggered"])
        self.assertEqual(meta["fallback_results"], 3)
        self.assertEqual(meta["rejected_by_location"], 2)
        self.assertEqual(meta["final_accepted_results"], 1)

        # Verify calls: first with 'Berlin', second nationwide ''
        self.assertEqual(mock_fetch_pages.call_count, 2)
        mock_fetch_pages.assert_any_call("Fachinformatiker", "Berlin", 10)
        mock_fetch_pages.assert_any_call("Fachinformatiker", "", 10)

    @patch.object(AubiPlusScraper, "_fetch_pages")
    def test_muenchen_results_only(self, mock_fetch_pages):
        """4. Explicit Location (München): Returns only München results and umlaut variants."""
        mock_fetch_pages.return_value = [
            {"title": "Job M1", "city": "München", "postal_code": "80331", "location": "80331 München"},
            {"title": "Job M2", "city": "Garching", "postal_code": "85748", "location": "85748 Garching bei München"},
            {"title": "Job B1", "city": "Berlin", "postal_code": "10115", "location": "10115 Berlin"},
            {"title": "Job K1", "city": "Köln", "postal_code": "50668", "location": "50668 Köln"},
        ]

        jobs = self.scraper.fetch_jobs(keyword="Informatik", location="München", max_jobs=10)
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(j["city"] in {"München", "Garching"} for j in jobs))

        # Test umlaut variant "Munchen" also matches München
        mock_fetch_pages.reset_mock()
        mock_fetch_pages.return_value = [
            {"title": "Job M1", "city": "München", "postal_code": "80331", "location": "80331 München"},
            {"title": "Job B1", "city": "Berlin", "postal_code": "10115", "location": "10115 Berlin"},
        ]
        jobs_variant = self.scraper.fetch_jobs(keyword="Informatik", location="Munchen", max_jobs=10)
        self.assertEqual(len(jobs_variant), 1)
        self.assertEqual(jobs_variant[0]["city"], "München")

    @patch.object(AubiPlusScraper, "_fetch_pages")
    def test_postal_code_and_radius_filtering(self, mock_fetch_pages):
        """5. Postal Code: Matches exact postal code or same 2-digit regional radius."""
        mock_fetch_pages.return_value = [
            {"title": "Job PLZ Exact", "city": "Köln", "postal_code": "50668", "location": "50668 Köln"},
            {"title": "Job PLZ Radius", "city": "Köln", "postal_code": "50825", "location": "50825 Köln"},
            {"title": "Job Far Away", "city": "Berlin", "postal_code": "10115", "location": "10115 Berlin"},
            {"title": "Job Munich", "city": "München", "postal_code": "80331", "location": "80331 München"},
        ]

        # Searching for 50668 accepts exact 50668 and regional 50825 (both prefix 50), excludes 10115 and 80331
        jobs = self.scraper.fetch_jobs(keyword="Informatik", location="50668", max_jobs=10)
        self.assertEqual(len(jobs), 2)
        plz_set = {j["postal_code"] for j in jobs}
        self.assertEqual(plz_set, {"50668", "50825"})
        self.assertEqual(self.scraper.last_search_meta["rejected_by_location"], 2)

    @patch.object(AubiPlusScraper, "_fetch_pages")
    def test_no_valid_local_matches_returns_zero(self, mock_fetch_pages):
        """6. No valid local matches: Must return zero results, never unrelated nationwide jobs."""
        mock_fetch_pages.side_effect = [
            [],  # Local search for KleinesDorf returns 0
            [  # Nationwide fallback returns unrelated jobs across Germany
                {"title": "Job 1", "city": "Stuttgart", "postal_code": "70173", "location": "70173 Stuttgart"},
                {"title": "Job 2", "city": "Dresden", "postal_code": "01067", "location": "01067 Dresden"},
            ],
        ]

        jobs = self.scraper.fetch_jobs(keyword="Bauingenieur", location="KleinesDorf", max_jobs=10)
        self.assertEqual(len(jobs), 0)
        self.assertEqual(self.scraper.total_jobs_fetched, 0)
        self.assertTrue(self.scraper.last_search_meta["fallback_triggered"])
        self.assertEqual(self.scraper.last_search_meta["rejected_by_location"], 2)
        self.assertEqual(self.scraper.last_search_meta["final_accepted_results"], 0)

    @patch.object(AubiPlusScraper, "_fetch_pages")
    def test_prefix_stripping_and_location_normalization(self, mock_fetch_pages):
        """Preserves prefix stripping and normalizes generic locations."""
        mock_fetch_pages.return_value = [{"title": "Bauingenieur", "city": "Berlin", "postal_code": "10115", "location": "10115 Berlin"}]

        # 1. Strip 'Ausbildung als'
        self.scraper.fetch_jobs(keyword="Ausbildung als Bauingenieurwesen", location="Berlin", max_jobs=10)
        mock_fetch_pages.assert_called_with("Bauingenieurwesen", "Berlin", 10)

        # 2. Normalize 'Bundesweit' to empty string
        mock_fetch_pages.reset_mock()
        self.scraper.fetch_jobs(keyword="Duales Studium Informatik", location="Bundesweit", max_jobs=5)
        mock_fetch_pages.assert_called_with("Informatik", "", 5)

        # 3. Normalize 'Ganz Deutschland' to empty string
        mock_fetch_pages.reset_mock()
        self.scraper.fetch_jobs(keyword="Ausbildung zum Mechatroniker", location="Ganz Deutschland", max_jobs=8)
        mock_fetch_pages.assert_called_with("Mechatroniker", "", 8)

    def test_flask_api_aubi_plus_search(self):
        app.config["TESTING"] = True
        client = app.test_client()

        with patch.object(AubiPlusScraper, "fetch_jobs") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "title": "Fachinformatiker (m/w/d)",
                    "company": "Test AG",
                    "city": "Köln",
                    "postal_code": "50668",
                    "location": "50668 Köln",
                    "start_date": "01.09.2025",
                    "url": "https://www.aubi-plus.de/ausbildung/123",
                    "source": "aubi-plus.de",
                }
            ]

            resp = client.get("/api/aubi-plus/search?keyword=Informatik&location=Koeln")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(len(data["jobs"]), 1)
            self.assertEqual(data["jobs"][0]["source"], "aubi-plus.de")


if __name__ == "__main__":
    unittest.main()
