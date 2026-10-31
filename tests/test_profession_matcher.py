"""
Tests for JobScout Profession Matcher and Dataset Availability Evaluation.
Validates:
- Exact matches (Green 'Vorhanden')
- Related/cluster matches (Yellow 'Ähnlich')
- Missing/unrelated matches (Red 'Nicht vorhanden')
- Endpoint /api/ausbildungen/availability
"""

import unittest
from services.profession_matcher import evaluate_profession_match


class TestProfessionMatcher(unittest.TestCase):
    def setUp(self):
        self.mock_datasets = [
            {
                "domain_name": "ausbildung als pflegefachmann",
                "filename": "20261027_190029_ausbildung_als_pflegefachmann_1065afa8.xlsx",
                "row_count": 673,
            },
            {
                "domain_name": "ausbildung zur fachkraft f r lagerlogistik",
                "filename": "20260902_164900_ausbildung_zur_fachkraft_f_r_lagerlogistik_22e591ee.xlsx",
                "row_count": 1003,
            },
            {
                "domain_name": "ausbildung als fachinformatiker",
                "filename": "20260901_142602_ausbildung_als_fachinformatiker_c644036f.xlsx",
                "row_count": 260,
            },
        ]

    def test_direct_exact_matches(self):
        # Fachinformatiker variations
        res1 = evaluate_profession_match("Ausbildung zum Fachinformatiker", self.mock_datasets)
        self.assertEqual(res1["status"], "available")
        self.assertEqual(res1["label"], "Vorhanden")

        res2 = evaluate_profession_match("Fachinformatikerin fuer Anwendungsentwicklung", self.mock_datasets)
        self.assertEqual(res2["status"], "available")
        self.assertEqual(res2["label"], "Vorhanden")

        # Pflegefachmann variations
        res3 = evaluate_profession_match("Pflegefachmann", self.mock_datasets)
        self.assertEqual(res3["status"], "available")
        self.assertEqual(res3["label"], "Vorhanden")

        res4 = evaluate_profession_match("Pflegefachfrau (m/w/d)", self.mock_datasets)
        self.assertEqual(res4["status"], "available")
        self.assertEqual(res4["label"], "Vorhanden")

        # Lagerlogistik variations
        res5 = evaluate_profession_match("Fachkraft fuer Lagerlogistik", self.mock_datasets)
        self.assertEqual(res5["status"], "available")
        self.assertEqual(res5["label"], "Vorhanden")

    def test_related_similar_matches(self):
        # Related to Lagerlogistik
        res1 = evaluate_profession_match("Fachlagerist", self.mock_datasets)
        self.assertEqual(res1["status"], "similar")
        self.assertEqual(res1["label"], "Ähnlich")

        # Related to Fachinformatiker (IT branch)
        res2 = evaluate_profession_match("Softwareentwickler", self.mock_datasets)
        self.assertEqual(res2["status"], "similar")
        self.assertEqual(res2["label"], "Ähnlich")

        res3 = evaluate_profession_match("Informatikkaufmann", self.mock_datasets)
        self.assertEqual(res3["status"], "similar")
        self.assertEqual(res3["label"], "Ähnlich")

        # Related to Pflegefachmann
        res4 = evaluate_profession_match("Altenpflegerin", self.mock_datasets)
        self.assertEqual(res4["status"], "similar")
        self.assertEqual(res4["label"], "Ähnlich")

    def test_missing_unrelated_matches(self):
        # No gastro dataset available
        res1 = evaluate_profession_match("Koch", self.mock_datasets)
        self.assertEqual(res1["status"], "missing")
        self.assertEqual(res1["label"], "Nicht vorhanden")

        # No baker dataset
        res2 = evaluate_profession_match("Baecker", self.mock_datasets)
        self.assertEqual(res2["status"], "missing")
        self.assertEqual(res2["label"], "Nicht vorhanden")

        # No commercial dataset
        res3 = evaluate_profession_match("Industriekaufmann", self.mock_datasets)
        self.assertEqual(res3["status"], "missing")
        self.assertEqual(res3["label"], "Nicht vorhanden")

        # Empty or placeholder
        res4 = evaluate_profession_match("", self.mock_datasets)
        self.assertEqual(res4["status"], "missing")
        self.assertEqual(res4["label"], "Nicht vorhanden")

        res5 = evaluate_profession_match("k. A.", self.mock_datasets)
        self.assertEqual(res5["status"], "missing")
        self.assertEqual(res5["label"], "Nicht vorhanden")

    def test_multiple_dataset_matches(self):
        multi_datasets = self.mock_datasets + [
            {
                "domain_name": "ausbildung als fachinformatiker",
                "filename": "20261026_185227_637990_ausbildung_als_fachinformatiker.xlsx",
                "row_count": 140,
            }
        ]
        res = evaluate_profession_match("Fachinformatiker", multi_datasets)
        self.assertEqual(res["status"], "available")
        self.assertEqual(res["match_type"], "Exakt")
        self.assertEqual(len(res["matched_datasets"]), 2)
        self.assertEqual(res["total_listings"], 400) # 260 + 140

    def test_empty_dataset_list(self):
        res = evaluate_profession_match("Fachinformatiker", [])
        self.assertEqual(res["status"], "missing")
        self.assertEqual(res["label"], "Nicht vorhanden")
        self.assertEqual(res["details"], "Kein passender Datensatz gefunden.")


if __name__ == "__main__":
    unittest.main()
