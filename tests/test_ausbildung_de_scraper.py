import unittest
from unittest.mock import MagicMock, patch
import bs4
from app import app
from scraper.ausbildung_de_scraper import AusbildungDeScraper


MOCK_HTML_PAGE = """
<!DOCTYPE html>
<html>
<body>
  <article data-testid="jp-card">
    <a href="/stellen/fachinformatiker-anwendungsentwicklung-12345/">
      <h3 data-testid="jp-title">Fachinformatiker fuer Anwendungsentwicklung (m/w/d)</h3>
    </a>
    <div data-testid="jp-customer">bei <!-- --> Musterfirma GmbH</div>
    <div data-testid="jp-branches">50667 Koeln + 3 weitere</div>
    <div data-testid="jp-starting-at">01.08.2025</div>
    <div data-testid="jp-vacancies">2 freie Plaetze</div>
  </article>
  <article data-testid="jp-card">
    <a href="/stellen/kaufmann-fuer-it-system-management-67890/">
      <h3 data-testid="jp-title">Informatikkaufmann fuer IT-System-Management (m/w/d)</h3>
    </a>
    <div data-testid="jp-customer">Tech Solutions AG</div>
    <div data-testid="jp-branches">Berlin</div>
  </article>
</body>
</html>
"""


class AusbildungDeScraperTestCase(unittest.TestCase):
    def setUp(self):
        self.scraper = AusbildungDeScraper()

    def test_parse_cards_standard(self):
        soup = bs4.BeautifulSoup(MOCK_HTML_PAGE, "html.parser")
        cards = soup.find_all("article", attrs={"data-testid": "jp-card"})
        jobs = self.scraper._parse_cards(cards)

        self.assertEqual(len(jobs), 2)

        # Test first job
        job1 = jobs[0]
        self.assertEqual(job1["title"], "Fachinformatiker fuer Anwendungsentwicklung (m/w/d)")
        self.assertEqual(job1["company"], "Musterfirma GmbH")
        self.assertEqual(job1["postal_code"], "50667")
        self.assertEqual(job1["city"], "Koeln")
        self.assertEqual(job1["start_date"], "01.08.2025")
        self.assertEqual(job1["vacancies"], "2 freie Plaetze")
        self.assertEqual(job1["source"], "ausbildung.de")
        self.assertTrue(job1["url"].startswith("https://www.ausbildung.de/stellen/fachinformatiker"))
        self.assertEqual(job1["reference"], "ausbildung_de_fachinformatiker-anwendungsentwicklung-12345")

        # Test second job with fallback fields
        job2 = jobs[1]
        self.assertEqual(job2["title"], "Informatikkaufmann fuer IT-System-Management (m/w/d)")
        self.assertEqual(job2["company"], "Tech Solutions AG")
        self.assertEqual(job2["location"], "Berlin")
        self.assertEqual(job2["postal_code"], "N/A")
        self.assertEqual(job2["city"], "Berlin")
        self.assertEqual(job2["start_date"], "nach Absprache")
        self.assertEqual(job2["vacancies"], "1 Platz")
        self.assertEqual(job2["source"], "ausbildung.de")

    @patch("requests.Session.get")
    def test_fetch_jobs_mocked(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_HTML_PAGE
        mock_get.return_value = mock_resp

        results = self.scraper.fetch_jobs(keyword="Informatik", location="Koeln", max_jobs=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["company"], "Musterfirma GmbH")

    def test_flask_api_ausbildung_de_search(self):
        app.config["TESTING"] = True
        client = app.test_client()

        with patch.object(AusbildungDeScraper, "fetch_jobs") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "title": "Kaufmann im E-Commerce",
                    "company": "E-Com Shop GmbH",
                    "city": "Hamburg",
                    "postal_code": "20095",
                    "location": "Hamburg",
                    "start_date": "01.09.2025",
                    "vacancies": "1",
                    "url": "https://www.ausbildung.de/stellen/123",
                    "source": "ausbildung.de",
                }
            ]

            res = client.get("/api/ausbildung-de/search?keyword=E-Commerce&location=Hamburg&max_jobs=5")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("source"), "ausbildung.de")
            self.assertEqual(len(data.get("jobs", [])), 1)
            self.assertEqual(data["jobs"][0]["company"], "E-Com Shop GmbH")


if __name__ == "__main__":
    unittest.main()
