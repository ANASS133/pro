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

        # Job 1
        j1 = jobs[0]
        self.assertEqual(j1["title"], "Fachinformatiker Anwendungsentwicklung (m/w/d)")
        self.assertEqual(j1["company"], "Muster GmbH & Co. KG")
        self.assertEqual(j1["postal_code"], "50668")
        self.assertEqual(j1["city"], "Köln")
        self.assertEqual(j1["start_date"], "01.09.2025")
        self.assertEqual(j1["source"], "aubi-plus.de")
        self.assertTrue(j1["url"].startswith("https://www.aubi-plus.de/ausbildung/fachinformatiker"))

        # Job 2
        j2 = jobs[1]
        self.assertEqual(j2["title"], "Kaufmann fuer Bueromanagement (m/w/d)")
        self.assertEqual(j2["company"], "Bürohelden GmbH")
        self.assertEqual(j2["postal_code"], "10115")
        self.assertEqual(j2["city"], "Berlin")
        self.assertEqual(j2["start_date"], "01.08.2025")
        self.assertEqual(j2["source"], "aubi-plus.de")

    @patch("requests.Session.get")
    def test_fetch_jobs_mocked(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_AUBI_HTML
        mock_get.return_value = mock_resp

        results = self.scraper.fetch_jobs(keyword="Fachinformatiker", location="Köln", max_jobs=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["company"], "Muster GmbH & Co. KG")

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
