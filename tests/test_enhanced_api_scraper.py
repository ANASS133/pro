import unittest

from scraper.enhanced_api_scraper import EnhancedJobScraper


class EnhancedApiScraperTests(unittest.TestCase):
    def test_parse_jobs_normalizes_expected_fields(self):
        scraper = EnhancedJobScraper()

        raw_jobs = [
            {
                "stellenangebotsTitel": "Ausbildung Fachinformatiker",
                "firma": "Beispiel GmbH",
                "referenznummer": "12345",
                "arbeitszeitVollzeit": True,
                "veroeffentlichungszeitraum": {"von": "2026-04-01"},
                "eintrittszeitraum": {"von": "2026-08-01"},
                "hauptberuf": "Fachinformatiker/in",
                "stellenlokationen": [{"adresse": {"ort": "Berlin", "plz": "10115"}}],
            }
        ]

        parsed = scraper.parse_jobs(raw_jobs)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Ausbildung Fachinformatiker")
        self.assertEqual(parsed[0]["company"], "Beispiel GmbH")
        self.assertEqual(parsed[0]["location"], "10115 Berlin")
        self.assertEqual(parsed[0]["reference"], "12345")
        self.assertEqual(parsed[0]["job_type"], "Vollzeit")
        self.assertTrue(parsed[0]["url"].endswith("/12345"))
