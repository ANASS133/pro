"""
Comprehensive Test Suite for JobScout Intelligent Profession-to-Employer Discovery Engine.
Verifies:
- Taxonomy and intelligent classification for all required roles:
  * Koch -> Restaurants, Hotels, Catering, Kantinen
  * Pflegefachmann -> Krankenhäuser, Pflegeheime, Pflegedienste
  * Fachinformatiker -> IT-Systemhäuser, Softwareunternehmen, Rechenzentren
  * Kfz-Mechatroniker -> Autohäuser, Werkstätten
  * Verkäufer -> Einzelhandel, Kaufhäuser, Supermärkte
  * Elektroniker -> Elektrohandwerk, Gebäudetechnik
- Misspelled profession normalization and typo correction
- Multilingual inputs (EN, FR)
- Unknown profession AI/heuristic fallback
- Empty city nationwide geographic batching
- Smart relevance ranking & separation of verified vacancies vs potential employers
- Flask API endpoint /api/profession/classify
"""

import unittest
from services.profession_intelligence import profession_intelligence
from services.geographic_batching import geographic_batching
from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
from app import app


class TestProfessionIntelligenceEngine(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.verifier = GoogleMapsAusbildungVerifier()

    def test_koch_classification(self):
        res = profession_intelligence.classify_profession("Ausbildung als Koch")
        self.assertEqual(res["normalized_profession"], "Koch")
        self.assertEqual(res["sector"], "Gastronomie & Hotellerie")
        cats = [c["category"].lower() for c in res["employer_categories"]]
        
        # Verify relevant employer categories
        self.assertTrue(any("restaurant" in c for c in cats))
        self.assertTrue(any("hotel" in c for c in cats))
        self.assertTrue(any("catering" in c for c in cats))
        self.assertTrue(any("kantine" in c for c in cats))

        # Check search queries helper
        queries = profession_intelligence.get_search_queries("Ausbildung als Koch", location="Berlin")
        self.assertTrue(len(queries) >= 3)
        self.assertTrue(any("Berlin" in q["query"] for q in queries))

    def test_pflegefachmann_classification(self):
        res = profession_intelligence.classify_profession("Ausbildung als Pflegefachmann")
        self.assertEqual(res["normalized_profession"], "Pflegefachmann")
        self.assertEqual(res["sector"], "Gesundheitswesen & Pflege")
        cats = [c["category"].lower() for c in res["employer_categories"]]

        self.assertTrue(any("krankenhaus" in c or "klinik" in c for c in cats))
        self.assertTrue(any("pflegeheim" in c or "seniorenheim" in c for c in cats))
        self.assertTrue(any("ambulanten pflegedienst" in c or "pflegedienst" in c for c in cats))
        self.assertTrue(any("reha" in c for c in cats))

    def test_fachinformatiker_classification(self):
        res = profession_intelligence.classify_profession("Fachinformatiker Systemintegration")
        self.assertEqual(res["normalized_profession"], "Fachinformatiker Systemintegration")
        self.assertIn("IT", res["sector"])
        cats = [c["category"].lower() for c in res["employer_categories"]]

        self.assertTrue(any("systemhaus" in c or "it-dienstleister" in c for c in cats))
        self.assertTrue(any("software" in c for c in cats))
        self.assertTrue(any("rechenzentrum" in c or "cloud" in c for c in cats))

    def test_kfz_mechatroniker_classification(self):
        res = profession_intelligence.classify_profession("Ausbildung als Kfz-Mechatroniker")
        self.assertEqual(res["normalized_profession"], "Kfz-Mechatroniker")
        self.assertIn("Automobil", res["sector"])
        cats = [c["category"].lower() for c in res["employer_categories"]]

        self.assertTrue(any("werkstatt" in c for c in cats))
        self.assertTrue(any("autohaus" in c for c in cats))

    def test_verkaeufer_classification(self):
        res = profession_intelligence.classify_profession("Verkäufer")
        self.assertEqual(res["normalized_profession"], "Verkäufer")
        self.assertIn("Handel", res["sector"])
        cats = [c["category"].lower() for c in res["employer_categories"]]

        self.assertTrue(any("einzelhandel" in c for c in cats))
        self.assertTrue(any("supermarkt" in c or "discounter" in c for c in cats))

    def test_elektroniker_classification(self):
        res = profession_intelligence.classify_profession("Elektroniker für Energie- und Gebäudetechnik")
        self.assertIn("Elektroniker", res["normalized_profession"])
        self.assertIn("Elektrotechnik", res["sector"])
        cats = [c["category"].lower() for c in res["employer_categories"]]

        self.assertTrue(any("elektro" in c or "installation" in c for c in cats))

    def test_misspelled_normalization(self):
        # Typo: 'fachinforamtiker' -> Fachinformatiker
        res1 = profession_intelligence.classify_profession("Ausbildung als fachinforamtiker")
        self.assertIn("Fachinformatiker", res1["normalized_profession"])

        # Typo: 'kochh' -> Koch
        res2 = profession_intelligence.classify_profession("kochh")
        self.assertEqual(res2["normalized_profession"], "Koch")

        # Typo: 'pflegfachmann' -> Pflegefachmann
        res3 = profession_intelligence.classify_profession("pflegfachmann")
        self.assertEqual(res3["normalized_profession"], "Pflegefachmann")

    def test_multilingual_inputs(self):
        # English: 'nurse' -> Pflegefachmann
        res_en_nurse = profession_intelligence.classify_profession("nurse")
        self.assertEqual(res_en_nurse["normalized_profession"], "Pflegefachmann")

        # French: 'cuisinier' -> Koch
        res_fr_cook = profession_intelligence.classify_profession("cuisinier")
        self.assertEqual(res_fr_cook["normalized_profession"], "Koch")

        # French: 'developpeur' -> Fachinformatiker
        res_fr_dev = profession_intelligence.classify_profession("developpeur")
        self.assertEqual(res_fr_dev["normalized_profession"], "Fachinformatiker")

    def test_unknown_profession_fallback(self):
        # Unknown non-taxonomy title: should use AI gateway or heuristic fallback
        res = profession_intelligence.classify_profession("Quanten-Nanotechnologe Spezialist")
        self.assertIsNotNone(res)
        self.assertIn("normalized_profession", res)
        self.assertIn("sector", res)
        self.assertTrue(len(res.get("employer_categories", [])) >= 1)

    def test_geographic_batching_empty_and_state(self):
        # Empty city -> nationwide batching across German metropolitan hubs
        plan_empty = geographic_batching.resolve_targets("")
        self.assertEqual(plan_empty["scope"], "nationwide_sample")
        self.assertTrue(len(plan_empty["targets"]) >= 3)
        self.assertIn("Berlin", plan_empty["targets"])
        self.assertIn("Hamburg", plan_empty["targets"])

        # None -> same as empty
        plan_none = geographic_batching.resolve_targets(None)
        self.assertEqual(plan_none["scope"], "nationwide_sample")

        # 'Deutschland' -> nationwide batching
        plan_de = geographic_batching.resolve_targets("Deutschland")
        self.assertEqual(plan_de["scope"], "nationwide_sample")

        # Federal state 'Bayern'
        plan_bayern = geographic_batching.resolve_targets("Bayern")
        self.assertEqual(plan_bayern["scope"], "federal_state")
        self.assertIn("München", plan_bayern["targets"])

        # Specific city 'Köln'
        plan_koeln = geographic_batching.resolve_targets("Köln")
        self.assertEqual(plan_koeln["scope"], "city")
        self.assertEqual(plan_koeln["targets"], ["Köln"])

    def test_smart_ranking_verified_vs_potential(self):
        sample_jobs = [
            {
                "title": "Potenzieller Betrieb",
                "company": "Klinik Nord",
                "opportunity_type": "POTENTIAL_EMPLOYER",
                "is_verified_vacancy": False,
                "email": "kontakt@klinik-nord.de",
                "profession_relevance": 1.0,
            },
            {
                "title": "Ausbildung Pflegefachmann 2026",
                "company": "St. Marien Hospital",
                "opportunity_type": "VERIFIED_AUSBILDUNG",
                "is_verified_vacancy": True,
                "email": "ausbildung@st-marien.de",
                "apply_url": "https://st-marien.de/bewerbung",
                "profession_relevance": 1.0,
            },
            {
                "title": "Unbekannte Firma",
                "company": "GmbH",
                "opportunity_type": "POTENTIAL_EMPLOYER",
                "is_verified_vacancy": False,
                "email": "",
                "profession_relevance": 0.5,
            },
        ]

        ranked = self.verifier.smart_rank_employers(sample_jobs, profession="Pflegefachmann")
        
        # 1st place must be VERIFIED_AUSBILDUNG
        self.assertEqual(ranked[0]["opportunity_type"], "VERIFIED_AUSBILDUNG")
        self.assertEqual(ranked[0]["company"], "St. Marien Hospital")

        # 2nd place must be POTENTIAL_EMPLOYER with email & high relevance
        self.assertEqual(ranked[1]["company"], "Klinik Nord")
        self.assertTrue(ranked[1]["smart_relevance_score"] > ranked[2]["smart_relevance_score"])

    def test_api_profession_classify_endpoint(self):
        # GET request
        resp = self.client.get("/api/profession/classify?keyword=Ausbildung als Koch&location=Köln")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["normalized_profession"], "Koch")
        self.assertEqual(data["sector"], "Gastronomie & Hotellerie")
        self.assertTrue(len(data["employer_categories"]) >= 3)
        self.assertEqual(data["geographic_coverage"]["targets"], ["Köln"])

        # POST request
        resp_post = self.client.post("/api/profession/classify", json={"keyword": "Pflegefachmann"})
        self.assertEqual(resp_post.status_code, 200)
        data_post = resp_post.get_json()
        self.assertEqual(data_post["normalized_profession"], "Pflegefachmann")
        self.assertEqual(data_post["sector"], "Gesundheitswesen & Pflege")

    def test_api_profession_classify_validation(self):
        # Empty keyword should return 400
        resp = self.client.get("/api/profession/classify?keyword=")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
