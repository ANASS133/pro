"""
Comprehensive Automated Test Suite for Central AI Provider Manager
Tests:
- Configuration saving, updating, and persistence
- Secret masking and credential protection
- Official OpenAI API request formatting (/v1/responses format)
- Correct model selection (gpt-6-luna, gpt-5.6-luna, gpt-4o-mini)
- CV JSON extraction
- ATS optimization and zero-cost caching
- Golden hook & cover letter generation
- Autofill AI question bridge
- Gemini fallback behavior (only when enabled)
- Rate-limit and API error handling
- Token accounting and cost calculation
- Candidate profile isolation (no hardcoded names)
- Complete elimination of OpenRouter from the codebase
"""

import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure utf-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import app as flask_app
from services.ai_provider_manager import AIProviderManager, ai_manager
from pdf_generator.services.ats_service import (
    load_candidate_info,
    tailor_ats_keywords,
    generate_golden_hook,
    generate_ats_heatmap,
    detect_culture_vibe,
)


class TestAIProviderManager(unittest.TestCase):

    def setUp(self):
        self.app = flask_app.app
        self.client = self.app.test_client()
        self.client.testing = True

    def test_01_secret_masking(self):
        """Verify API keys are never exposed in plaintext."""
        self.assertEqual(AIProviderManager.mask_key("sk-proj-1234567890abcdef"), "sk-proj••••••••cdef")
        self.assertEqual(AIProviderManager.mask_key("short"), "••••••••")
        self.assertEqual(AIProviderManager.mask_key(""), "")
        self.assertEqual(AIProviderManager.mask_key(None), "")

        # Verify public status never returns raw keys
        status = ai_manager.get_public_status()
        self.assertNotIn("sk-proj-1234", json.dumps(status))
        self.assertIn("openai_has_key", status)
        self.assertIn("openai_masked_key", status)
        self.assertIn("primary_provider", status)

    def test_02_save_and_update_configuration(self):
        """Verify configuration update and protection against overwriting with masked strings."""
        resp = self.client.post("/api/ai/settings", json={
            "primary_provider": "openai",
            "openai_model": "gpt-6-luna",
            "enable_gemini_fallback": True
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        settings = data.get("settings", {})
        self.assertEqual(settings.get("primary_provider"), "openai")
        self.assertEqual(settings.get("openai_model"), "gpt-6-luna")
        self.assertTrue(settings.get("enable_gemini_fallback"))

        # Verify masked key does NOT overwrite real key
        real_key = ai_manager.config.get("openai_api_key")
        self.client.post("/api/ai/settings", json={
            "openai_api_key": "sk-proj-••••••••a8F9"
        })
        # Key must remain unchanged
        self.assertEqual(ai_manager.config.get("openai_api_key"), real_key)

    def test_03_connection_test_uses_zero_inference_tokens(self):
        """Verify connection test calls GET /v1/models (zero cost), never inference endpoints."""
        with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: {"data": [{"id": "gpt-6-luna"}]})
            
            resp = self.client.post("/api/ai/test-connection", json={
                "provider": "openai",
                "api_key": "sk-test-dummy-key-for-unit-test"
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("status"), "connected")
            
            # Verify GET /v1/models was called
            mock_get.assert_called_once()
            called_url = mock_get.call_args[0][0]
            self.assertIn("/v1/models", called_url)
            
            # Verify no paid inference call was made
            mock_post.assert_not_called()

    def test_04_official_openai_responses_request_formatting(self):
        """Verify payload formatting for /v1/responses endpoint."""
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "resp-12345",
                "model": "gpt-6-luna",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Optimierter Text."}]
                    }
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}
            }
            mock_post.return_value = mock_resp

            # Temporarily set dummy test key
            with patch.dict(ai_manager.config, {"openai_api_key": "sk-dummy-test", "openai_model": "gpt-6-luna"}):
                res = ai_manager._call_openai_api(
                    prompt="Test Prompt",
                    system_prompt="Test System",
                    model="gpt-6-luna",
                    max_output_tokens=100,
                    temperature=0.2
                )
                self.assertTrue(res.get("success"))
                self.assertEqual(res.get("text"), "Optimierter Text.")

                # Inspect payload sent to OpenAI
                called_args = mock_post.call_args
                payload = called_args[1].get("json", {})
                self.assertEqual(payload.get("model"), "gpt-6-luna")
                self.assertEqual(payload.get("reasoning"), {"effort": "none"})
                self.assertIsInstance(payload.get("input"), list)
                self.assertEqual(payload.get("max_output_tokens"), 100)

    def test_05_configurable_model_selection(self):
        """Verify user can select between gpt-6-luna, gpt-5.6-luna, gpt-4o-mini."""
        for test_model in ["gpt-6-luna", "gpt-5.6-luna", "gpt-4o-mini"]:
            ai_manager.config["openai_model"] = test_model
            self.assertEqual(ai_manager.config["openai_model"], test_model)
            status = ai_manager.get_public_status()
            self.assertEqual(status["openai_model"], test_model)

    def test_06_cv_json_extraction(self):
        """Verify CV JSON extraction cleans markdown code blocks and returns dict."""
        with patch.object(ai_manager, "complete") as mock_comp:
            mock_comp.return_value = {
                "success": True,
                "text": '```json\n{"personal_information": {"first_name": "Max", "last_name": "Mustermann"}}\n```',
                "model": "gpt-6-luna",
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
            }
            res = ai_manager.extract_cv_json("Lebenslauf Text")
            self.assertTrue(res.get("success"))
            self.assertIn("parsed_profile", res)
            self.assertEqual(res["parsed_profile"]["personal_information"]["first_name"], "Max")

    def test_07_ats_optimization_with_zero_cost_cache(self):
        """Verify ATS tailoring produces tailored bullets and caches repeated queries."""
        with patch.object(ai_manager, "complete") as mock_comp:
            mock_comp.return_value = {
                "success": True,
                "text": "• Erfahrung in moderner Full-Stack-Entwicklung.\n• Sichere Konzeption von RESTful Schnittstellen.",
                "model": "gpt-6-luna",
                "usage": {"input_tokens": 80, "output_tokens": 30, "total_tokens": 110, "estimated_cost_usd": 0.000052}
            }

            res1 = tailor_ats_keywords(
                job_title="Software Architect",
                company_name="Innovatech GmbH",
                job_requirements="Microservices, Cloud, Python"
            )
            self.assertTrue(res1.get("success"))
            self.assertGreaterEqual(len(res1.get("tailored_bullets", [])), 1)

            # Repeat call should be served 100% from cache with 0 tokens and 0 cost
            res2 = tailor_ats_keywords(
                job_title="Software Architect",
                company_name="Innovatech GmbH",
                job_requirements="Microservices, Cloud, Python"
            )
            self.assertTrue(res2.get("success"))
            self.assertTrue(res2.get("from_cache"))
            self.assertEqual(res2.get("usage", {}).get("estimated_cost_usd"), 0.0)

    def test_08_candidate_isolation_and_no_hardcoded_names(self):
        """Verify ATS heatmap and profile loader dynamically load candidates by profile_id."""
        # Test default candidate
        cand_default = load_candidate_info("anass_sibbi")
        self.assertIn("name", cand_default)
        self.assertIn("skills", cand_default)

        # Test another candidate (mohamed_mohamed_elamrani)
        cand_mohamed = load_candidate_info("mohamed_mohamed_elamrani")
        self.assertIn("Mohamed", cand_mohamed["name"])
        self.assertNotEqual(cand_mohamed["name"], "Anass Sibbi")

        # Test non-existent candidate gracefully returns clean fallback
        cand_unknown = load_candidate_info("unknown_candidate_999")
        self.assertEqual(cand_unknown["name"], "Bewerber")

    def test_09_gemini_fallback_behavior(self):
        """Verify fallback from OpenAI to Gemini triggers ONLY when explicitly enabled."""
        # 1. Fallback disabled -> fails with OpenAI error
        ai_manager.config["primary_provider"] = "openai"
        ai_manager.config["enable_gemini_fallback"] = False
        ai_manager.config["openai_api_key"] = "invalid-key"

        with patch.object(ai_manager, "_call_openai") as mock_openai, \
             patch.object(ai_manager, "_call_gemini") as mock_gemini:
            mock_openai.return_value = {"success": False, "error": "Rate limit 429"}
            mock_gemini.return_value = {
                "success": True,
                "text": "Gemini Fallback Result",
                "content": "Gemini Fallback Result",
                "model": "gemini-2.5-flash",
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
            }

            res = ai_manager.complete("Test Prompt", use_cache=False)
            self.assertFalse(res.get("success"))
            mock_gemini.assert_not_called()

        # 2. Fallback enabled -> gracefully falls back to Gemini
        ai_manager.config["enable_gemini_fallback"] = True
        ai_manager.config["gemini_api_key"] = "dummy-gemini-key"

        with patch.object(ai_manager, "_call_openai") as mock_openai, \
             patch.object(ai_manager, "_call_gemini") as mock_gemini:
            mock_openai.return_value = {"success": False, "error": "Rate limit 429"}
            mock_gemini.return_value = {
                "success": True,
                "text": "Gemini Fallback Result",
                "content": "Gemini Fallback Result",
                "model": "gemini-2.5-flash",
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
            }

            res = ai_manager.complete("Test Prompt", use_cache=False)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("text"), "Gemini Fallback Result")
            mock_gemini.assert_called_once()

    def test_10_cost_tracking_and_usage_accounting(self):
        """Verify token usage calculations and USD price estimations."""
        initial_usage = ai_manager.get_usage_summary()
        initial_reqs = initial_usage.get("total_requests", 0)

        # Record a test inference call
        ai_manager._record_usage(
            provider="openai",
            model="gpt-6-luna",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.0008,
            success=True
        )

        updated_usage = ai_manager.get_usage_summary()
        self.assertEqual(updated_usage["total_requests"], initial_reqs + 1)
        self.assertGreaterEqual(updated_usage["input_tokens"], 1000)
        self.assertGreaterEqual(updated_usage["output_tokens"], 500)
        self.assertGreaterEqual(updated_usage["estimated_cost_usd"], 0.0008)

    def test_11_autofill_bridge_route(self):
        """Verify internal bridge endpoint used by node.js autofill server."""
        with patch.object(ai_manager, "complete") as mock_comp:
            mock_comp.return_value = {
                "success": True,
                "text": "Answer for autofill question",
                "model": "gpt-6-luna",
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
            }
            resp = self.client.post("/api/ai/bridge-autofill", json={
                "prompt": "Why are you interested in this position?",
                "system_prompt": "You are a career assistant.",
                "max_output_tokens": 100
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("text"), "Answer for autofill question")
            self.assertEqual(data.get("model"), "gpt-6-luna")

    def test_12_no_remaining_openrouter_calls_in_codebase(self):
        """Verify zero remaining OpenRouter references across python, js, html, and env files."""
        base_dir = Path(__file__).resolve().parent.parent
        target_exts = {".py", ".js", ".html", ".env"}
        skip_dirs = {"node_modules", ".git", ".venv", "__pycache__", "brain", ".tempmediaStorage", "dist", "build"}
        found_violations = []

        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                if file == os.path.basename(__file__):
                    continue
                ext = os.path.splitext(file)[1]
                if ext in target_exts or file == ".env":
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            for line_no, line in enumerate(f, 1):
                                if "openrouter" in line.lower():
                                    if "zero openrouter" in line.lower() or "remove openrouter" in line.lower():
                                        continue
                                    rel = os.path.relpath(filepath, base_dir)
                                    found_violations.append(f"{rel}:{line_no} -> {line.strip()}")
                    except Exception:
                        pass

        self.assertEqual(
            len(found_violations),
            0,
            f"Found forbidden OpenRouter references:\n" + "\n".join(found_violations)
        )


if __name__ == "__main__":
    unittest.main()
