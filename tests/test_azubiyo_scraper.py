import unittest
from unittest.mock import MagicMock, patch
import bs4
from app import app
from scraper.azubiyo_scraper import AzubiyoScraper, slugify_german


MOCK_AZUBIYO_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="job-offer-teaser card card-clickable">
    <a href="/stellenanzeigen/fachinformatiker-anwendungsentwicklung_tech-solutions_abc123/">
      <span class="h3 mb-0 fs-6 fw-bold">Ausbildung Fachinformatiker fuer Anwendungsentwicklung (m/w/d)</span>
    </a>
    <span class="text-secondary font-size-14">Tech Solutions GmbH</span>
    <ul>
      <li>01.08.2025</li>
      <li>50667 Koeln</li>
      <li>1.150 EUR pro Monat</li>
    </ul>
  </div>
  <div class="job-offer-teaser card card-clickable">
    <a href="/stellenanzeigen/kaufmann-e-commerce_shop-ag_def456/">
      <span class="h3 mb-0 fs-6 fw-bold">Kaufmann im E-Commerce (m/w/d)</span>
    </a>
    <span class="text-secondary font-size-14">Online Shop AG</span>
    <ul>
      <li>01.09.2025</li>
      <li>Berlin (u.a.)</li>
    </ul>
  </div>
</body>
</html>
"""


class AzubiyoScraperTestCase(unittest.TestCase):
    def setUp(self):
        self.scraper = AzubiyoScraper()

    def test_slugify_german(self):
        self.assertEqual(slugify_german("Köln"), "koeln")
        self.assertEqual(slugify_german("München"), "muenchen")
        self.assertEqual(slugify_german("Groß-Gerau"), "gross-gerau")
        self.assertEqual(slugify_german("Büromanagement"), "bueromanagement")

    def test_parse_cards_standard(self):
        soup = bs4.BeautifulSoup(MOCK_AZUBIYO_HTML, "html.parser")
        cards = soup.find_all("div", class_=lambda c: c and "job-offer-teaser" in c)
        jobs = self.scraper._parse_cards(cards)

        self.assertEqual(len(jobs), 2)

        # Test job 1
        job1 = jobs[0]
        self.assertEqual(job1["title"], "Ausbildung Fachinformatiker fuer Anwendungsentwicklung (m/w/d)")
        self.assertEqual(job1["company"], "Tech Solutions GmbH")
        self.assertEqual(job1["city"], "Koeln")
        self.assertEqual(job1["postal_code"], "50667")
        self.assertEqual(job1["start_date"], "01.08.2025")
        self.assertEqual(job1["salary"], "1.150 EUR pro Monat")
        self.assertEqual(job1["source"], "azubiyo.de")
        self.assertTrue(job1["url"].startswith("https://www.azubiyo.de/stellenanzeigen/fachinformatiker"))
        self.assertEqual(job1["reference"], "azubiyo_fachinformatiker-anwendungsentwicklung_tech-solutions_abc123")

        # Test job 2
        job2 = jobs[1]
        self.assertEqual(job2["title"], "Kaufmann im E-Commerce (m/w/d)")
        self.assertEqual(job2["company"], "Online Shop AG")
        self.assertEqual(job2["city"], "Berlin")
        self.assertEqual(job2["postal_code"], "N/A")
        self.assertEqual(job2["start_date"], "01.09.2025")
        self.assertIsNone(job2["salary"])
        self.assertEqual(job2["source"], "azubiyo.de")

    @patch("requests.Session.get")
    def test_fetch_jobs_mocked(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_AZUBIYO_HTML
        mock_get.return_value = mock_resp

        results = self.scraper.fetch_jobs(keyword="Informatik", location="Koeln", max_jobs=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["company"], "Tech Solutions GmbH")

    def test_flask_api_azubiyo_search(self):
        app.config["TESTING"] = True
        client = app.test_client()

        with patch.object(AzubiyoScraper, "fetch_jobs") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "title": "Ausbildung Fachinformatiker",
                    "company": "Test IT GmbH",
                    "city": "Koeln",
                    "postal_code": "50667",
                    "location": "50667 Koeln",
                    "start_date": "01.08.2025",
                    "url": "https://www.azubiyo.de/stellenanzeigen/test",
                    "source": "azubiyo.de",
                }
            ]

            res = client.get("/api/azubiyo/search?keyword=Informatik&location=Koeln&max_jobs=5")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("source"), "azubiyo.de")
            self.assertEqual(len(data.get("jobs", [])), 1)
            self.assertEqual(data["jobs"][0]["company"], "Test IT GmbH")


if __name__ == "__main__":
    unittest.main()
