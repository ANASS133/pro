import unittest

from scraper.enhanced_api_scraper import EnhancedJobScraper


class EnhancedJobScraperTests(unittest.TestCase):
    def test_corrects_common_ausbildungsplatz_typo(self):
        self.assertEqual(
            EnhancedJobScraper.normalize_keyword(
                "Ausbildungplatz als Kaufmann im Einzelhandel"
            ),
            "Ausbildungsplatz als Kaufmann im Einzelhandel",
        )

    def test_preserves_valid_keyword(self):
        self.assertEqual(
            EnhancedJobScraper.normalize_keyword("Verkäufer Ausbildung"),
            "Verkäufer Ausbildung",
        )


if __name__ == "__main__":
    unittest.main()
