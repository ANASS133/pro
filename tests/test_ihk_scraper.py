import unittest
from unittest.mock import MagicMock, patch
import bs4
from app import app
from scraper.ihk_scraper import IhkScraper

MOCK_IHK_HTML = """
<!DOCTYPE html>
<html>
<body>
  <section class="job">
    <h3 class="job_title">
      <a href="/index.php?page=detail&amp;id=998877">Fachinformatiker/in - Anwendungsentwicklung</a>
    </h3>
    <p class="firma">
      <a href="/index.php?page=firmendetail&amp;id=111">Muster Software Solutions GmbH</a>
    </p>
    <p class="job-region">Region Frankfurt am Main (Hessen)</p>
  </section>
  <section class="job">
    <h3 class="job_title">
      <a href="/index.php?page=detail&amp;id=665544">Industriekaufmann/-frau</a>
    </h3>
    <p class="firma">
      <span>Großhandel &amp; Logistik AG</span>
    </p>
    <p class="job-region">Region München (Bayern)</p>
  </section>
</body>
</html>
"""


class IhkScraperTestCase(unittest.TestCase):
    def setUp(self):
        self.scraper = IhkScraper()

    def test_parse_cards_standard(self):
        soup = bs4.BeautifulSoup(MOCK_IHK_HTML, "html.parser")
        cards = soup.find_all("section", class_="job")
        jobs = self.scraper._parse_cards(cards)

        self.assertEqual(len(jobs), 2)

        # Job 1
        j1 = jobs[0]
        self.assertEqual(j1["title"], "Fachinformatiker/in - Anwendungsentwicklung")
        self.assertEqual(j1["company"], "Muster Software Solutions GmbH")
        self.assertEqual(j1["city"], "Frankfurt am Main")
        self.assertEqual(j1["source"], "ihk.de")
        self.assertEqual(j1["reference"], "ihk_998877")
        self.assertTrue("index.php?page=detail&id=998877" in j1["url"])

        # Job 2
        j2 = jobs[1]
        self.assertEqual(j2["title"], "Industriekaufmann/-frau")
        self.assertEqual(j2["company"], "Großhandel & Logistik AG")
        self.assertEqual(j2["city"], "München")
        self.assertEqual(j2["source"], "ihk.de")
        self.assertEqual(j2["reference"], "ihk_665544")

    @patch("requests.Session.get")
    def test_fetch_jobs_mocked(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = MOCK_IHK_HTML
        mock_get.return_value = mock_resp

        results = self.scraper.fetch_jobs(keyword="Fachinformatiker", location="Frankfurt", max_jobs=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["company"], "Muster Software Solutions GmbH")

    def test_flask_api_ihk_search(self):
        app.config["TESTING"] = True
        client = app.test_client()

        with patch.object(IhkScraper, "fetch_jobs") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "title": "Fachinformatiker (m/w/d)",
                    "company": "IHK Testfirma",
                    "city": "Frankfurt",
                    "postal_code": "N/A",
                    "location": "Frankfurt",
                    "start_date": "nach Absprache",
                    "url": "https://jobs.meine-ausbildung-in-deutschland.de/index.php?page=detail&id=123",
                    "source": "ihk-lehrstellenboerse.de",
                }
            ]

            resp = client.get("/api/ihk/search?keyword=Informatik&location=Frankfurt")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(len(data["jobs"]), 1)
            self.assertEqual(data["jobs"][0]["source"], "ihk-lehrstellenboerse.de")


if __name__ == "__main__":
    unittest.main()
