"""
Unit tests validating JobScout Architectural Problems #8, #9, and #10:
- #8. Autofill AI Integration: Native AI question answering, deterministic matching, no Node.js required
- #9. Centralized AI Configuration: Single AI Gateway, unified config across WhatsApp, Autofill, and Cover Letters
- #10. Ausbildung Datasets <-> Search Integration: Auto-saving discovered Ausbildung results, search discovery linkage
"""

import os
import json
import unittest
from unittest.mock import patch, MagicMock
from app import app
from services.ai_provider_manager import AIProviderManager
from routes.autofill import python_deterministic_matcher, python_ai_answer_questions


class TestArch8AutofillAIIntegration(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.applicant = {
            "personal": {
                "first_name": "Max",
                "last_name": "Mustermann",
                "full_name": "Max Mustermann",
                "date_of_birth": "1998-04-12",
                "nationality": "Deutsch"
            },
            "contact": {
                "email": "max@example.com",
                "phone": "+491701234567",
                "address": {
                    "street": "Hauptstraße 42",
                    "city": "Berlin",
                    "postal_code": "10115",
                    "country": "Deutschland"
                },
                "linkedin": {
                    "url": "https://linkedin.com/in/max-mustermann"
                }
            },
            "professional_profile": {
                "target_profession": "Fachinformatiker Anwendungsentwicklung",
                "summary": "Engagierter Entwickler mit guten Python- und Web-Kenntnissen.",
                "skills": ["Python", "Flask", "JavaScript"]
            }
        }
        self.documents = [
            {"fileName": "Lebenslauf_Max_Mustermann.pdf", "category": "cv"}
        ]

    def test_deterministic_matcher_standard_fields(self):
        # 1. First name
        res = python_deterministic_matcher({"label": "Vorname", "type": "text"}, self.applicant, self.documents)
        self.assertIsNotNone(res)
        self.assertEqual(res["value"], "Max")
        self.assertEqual(res["status"], "approved")

        # 2. Email
        res = python_deterministic_matcher({"label": "E-Mail", "type": "email"}, self.applicant, self.documents)
        self.assertIsNotNone(res)
        self.assertEqual(res["value"], "max@example.com")

        # 3. City
        res = python_deterministic_matcher({"label": "Wohnort", "type": "text"}, self.applicant, self.documents)
        self.assertIsNotNone(res)
        self.assertEqual(res["value"], "Berlin")

        # 4. CV file
        res = python_deterministic_matcher({"label": "Lebenslauf hochladen", "type": "file"}, self.applicant, self.documents)
        self.assertIsNotNone(res)
        self.assertEqual(res["value"], "Lebenslauf_Max_Mustermann.pdf")
        self.assertTrue(res.get("isFile"))

    @patch("services.ai_provider_manager.ai_manager.complete")
    def test_ai_question_answering_custom_questions(self, mock_complete):
        mock_complete.return_value = {
            "success": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "parsed_json": {
                "actions": [
                    {
                        "field_id": "motivation_question",
                        "proposed_value": "Ich interessiere mich leidenschaftlich für Anwendungsentwicklung und bringe fundierte Python-Kenntnisse mit.",
                        "confidence": 0.92,
                        "reason": "Antwort abgeleitet aus Bewerberprofil",
                        "review_required": False
                    }
                ]
            }
        }

        unresolved = [
            {"field_id": "motivation_question", "label": "Warum bewerben Sie sich bei uns?", "type": "textarea"}
        ]
        answers = python_ai_answer_questions(unresolved, self.applicant, {})
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]["field_id"], "motivation_question")
        self.assertIn("Python-Kenntnisse", answers[0]["proposed_value"])
        self.assertTrue(mock_complete.called)

    def test_map_fields_endpoint_without_node(self):
        response = self.client.post(
            "/api/autofill/map-fields",
            json={
                "fields": [
                    {"field_id": "first_name", "label": "Vorname", "type": "text"},
                    {"field_id": "last_name", "label": "Nachname", "type": "text"},
                    {"field_id": "email", "label": "E-Mail-Adresse", "type": "email"}
                ],
                "profileId": "anass_sibbi"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        actions = data.get("actions", [])
        self.assertTrue(len(actions) >= 2)
        field_ids = [a["field_id"] for a in actions]
        self.assertIn("first_name", field_ids)
        self.assertIn("email", field_ids)


class TestArch9CentralizedAIConfiguration(unittest.TestCase):
    def setUp(self):
        self.manager = AIProviderManager()
        self.orig_config = dict(self.manager.config)
        self.orig_env_key = os.environ.get("OPENAI_API_KEY")
        self.orig_env_model = os.environ.get("OPENAI_MODEL")

    def tearDown(self):
        self.manager.save_config(self.orig_config)
        if self.orig_env_key is not None:
            os.environ["OPENAI_API_KEY"] = self.orig_env_key
        elif "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
        if self.orig_env_model is not None:
            os.environ["OPENAI_MODEL"] = self.orig_env_model
        elif "OPENAI_MODEL" in os.environ:
            del os.environ["OPENAI_MODEL"]

    def test_unified_gateway_config_sync(self):
        test_key = "sk-test-centralized-key-jobscout-999"
        res = self.manager.save_config({
            "openai_api_key": test_key,
            "primary_provider": "openai",
            "openai_model": "gpt-4o"
        })
        self.assertTrue(res.get("success"))
        self.assertEqual(self.manager.config["openai_api_key"], test_key)
        self.assertEqual(os.environ.get("OPENAI_API_KEY"), test_key)
        self.assertEqual(os.environ.get("OPENAI_MODEL"), "gpt-4o")

    def test_status_endpoint_returns_unified_config(self):
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.get("/api/ai/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        settings = data.get("settings", {})
        self.assertIn("primary_provider", settings)
        self.assertIn("openai", settings)
        self.assertIn("gemini", settings)


class TestArch10AusbildungDatasetsSearchIntegration(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("app._save_auto_extraction_export_records")
    @patch("app._fetch_combined_jobs")
    def test_search_ausbildung_mode_auto_saves_dataset(self, mock_fetch, mock_save_export):
        # Mock search pipeline returning valid Ausbildung results
        mock_fetch.return_value = (
            [
                {
                    "title": "Ausbildung zum Kaufmann für Büromanagement",
                    "company": "Muster GmbH",
                    "location": "Köln",
                    "link": "https://example.com/job/1",
                    "source": "ausbildung_de"
                }
            ],
            {"total": 1, "sources": ["ausbildung_de"]}
        )

        resp = self.client.get(
            "/api/search?keyword=Ausbildung+als+Kaufmann+fuer+Bueromanagement&location=Koeln&mode=ausbildung"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        # Verify that auto-saving to Ausbildung dataset was triggered
        self.assertTrue(mock_save_export.called)
        args, kwargs = mock_save_export.call_args
        self.assertIn("kaufmann", str(args[1]).lower())


if __name__ == "__main__":
    unittest.main()
