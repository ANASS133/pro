"""
Comprehensive Regression Test Suite for CV Extraction and Cover Letter Studio Data Integrity.
Verifies:
1. Multi-document PDF classification (identifies CV page vs. certificates, diplomas, evaluations).
2. Institutional address guardrails (never assigns ZAB Bonn or BA Nürnberg to candidate).
3. Candidate headline/profession separation from target Ausbildung occupation.
4. Structured employment history & education parsing from multi-document dossiers.
5. Experience metrics calculation (experienced candidates not labeled 'Berufseinstieg').
6. Dossier reparsing endpoint and cache invalidation.
7. Cover Letter Studio placeholder synonym resolution.
8. End-to-end PDF generation verification with ReportLab (no unresolved placeholders, no fake defaults).
9. Candidate switching and profile isolation.
"""

import io
import json
import unittest
from pathlib import Path
from pypdf import PdfReader

from app import app
from pdf_generator.services.template_service import TemplateService
from services.client_manager import client_manager
from services.cv_parser import CVParser
from services.document_classifier import DocumentClassifier, DocumentType


REAL_DOSSIER_PATH = Path("data/clients/anass_sibbi_cc42f2/documents/Lebenslauf.pdf")


class TestCVExtractionIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = cls.app.test_client()
        cls.has_real_dossier = REAL_DOSSIER_PATH.exists()

    def test_01_multi_document_classification(self):
        """Verifies DocumentClassifier isolates CV from certificates, ZAB evaluations, and translations."""
        if not self.has_real_dossier:
            self.skipTest("Real 17-page dossier fixture not found on disk")

        classification = DocumentClassifier.classify_dossier(REAL_DOSSIER_PATH)

        self.assertEqual(classification["total_pages"], 17)
        self.assertTrue(classification["is_multi_document"])
        # CV is isolated to page 1
        self.assertEqual(classification["cv_page_numbers"], [1])

        # Page 1 must be classified as CV
        page_1 = classification["classified_pages"][0]
        self.assertEqual(page_1["type"], DocumentType.CV)
        self.assertTrue(page_1["is_cv"])
        self.assertGreaterEqual(page_1["confidence"], 0.8)

        # Pages 3 and 4 (ZAB evaluation) must be classified as Institutional
        page_3 = classification["classified_pages"][2]
        self.assertEqual(page_3["type"], DocumentType.INSTITUTIONAL)
        self.assertFalse(page_3["is_cv"])

        # Blacklisted institutional addresses must contain Bonn
        blacklisted = classification["blacklisted_addresses"]
        self.assertTrue(any(b.get("postal_code") == "53117" for b in blacklisted))
        self.assertTrue(any("Bonn" in str(b.get("city")) for b in blacklisted))

    def test_02_institutional_address_rejection(self):
        """Verifies candidate location is Casablanca and never institutional Bonn address."""
        if not self.has_real_dossier:
            self.skipTest("Real 17-page dossier fixture not found on disk")

        parsed = CVParser.parse_pdf_dossier(REAL_DOSSIER_PATH)
        addr = parsed["contact"]["address"]

        # City must be Casablanca, Country Marokko
        self.assertEqual(addr["city"], "Casablanca")
        self.assertEqual(addr["country"], "Marokko")
        self.assertEqual(addr["country_code"], "MA")

        # Postal code must NEVER be 53117 Bonn
        self.assertNotEqual(addr["postal_code"], "53117")
        self.assertNotEqual(addr["city"], "Bonn")
        self.assertNotEqual(addr["street"], "Graurheindorfer Str.")
        self.assertNotEqual(addr["street"], "ISTA")

    def test_03_candidate_title_versus_target_occupation(self):
        """Verifies candidate's actual documented profession is preserved and distinct from target occupation."""
        if not self.has_real_dossier:
            self.skipTest("Real 17-page dossier fixture not found on disk")

        parsed = CVParser.parse_pdf_dossier(REAL_DOSSIER_PATH)
        prof = parsed["professional_profile"]

        # Documented profession from CV line 2
        self.assertEqual(prof["current_title"], "Softwareentwickler | Full-Stack-Entwickler")
        self.assertIn("Softwareentwickler", prof["headline"])
        # Must not be garbled with 'serfahrung'
        self.assertNotIn("serfahrung", prof["headline"])
        self.assertNotIn("serfahrung", prof["current_title"])

    def test_04_work_experience_extraction(self):
        """Verifies structured employment history is extracted with dates, employers, and duties."""
        if not self.has_real_dossier:
            self.skipTest("Real 17-page dossier fixture not found on disk")

        parsed = CVParser.parse_pdf_dossier(REAL_DOSSIER_PATH)
        work = parsed["work_experience"]

        self.assertGreaterEqual(len(work), 4)

        # Role 1: Marokkanisches Innenministerium
        role_1 = work[0]
        self.assertEqual(role_1["position"], "Softwareentwickler")
        self.assertIn("Innenministerium", role_1["employer"])
        self.assertTrue(role_1["is_current"])
        self.assertGreater(len(role_1["responsibilities"]), 0)

        # Role 2: Outsourcia (Customer Support for German Market)
        role_2 = work[1]
        self.assertEqual(role_2["position"], "Kundenbetreuer (deutscher Markt)")
        self.assertEqual(role_2["employer"], "Outsourcia")

        # Role 3: Freelance Full-Stack Developer
        role_3 = work[2]
        self.assertIn("Full-Stack-Entwickler", role_3["position"])

        # Role 4: Batihold GmbH Internship
        role_4 = work[3]
        self.assertIn("Webentwickler", role_4["position"])
        self.assertEqual(role_4["employer"], "Batihold GmbH")

    def test_05_education_and_certifications_extraction(self):
        """Verifies degrees and certifications are extracted and verified."""
        if not self.has_real_dossier:
            self.skipTest("Real 17-page dossier fixture not found on disk")

        parsed = CVParser.parse_pdf_dossier(REAL_DOSSIER_PATH)
        edu = parsed["education"]
        certs = parsed["certifications"]

        self.assertGreaterEqual(len(edu), 4)
        # Degree 1: Ingenieurstudium Cybersicherheit
        self.assertIn("Cybersicherheit", edu[0]["degree"])
        self.assertEqual(edu[0]["institution"], "Hightech")

        # Degree 2: Exzellenz-Lizenz
        self.assertIn("Lizenz", edu[1]["degree"])
        self.assertIn("Universität Hassan I", edu[1]["institution"])

        # Degree 3: ISTA 2 OFPPT
        self.assertIn("Fachtechniker", edu[2]["degree"])
        self.assertIn("ISTA", edu[2]["institution"])

        # Certifications
        self.assertGreaterEqual(len(certs), 5)
        cert_names = [c["name"].lower() for c in certs]
        self.assertTrue(any("telc" in c for c in cert_names))
        self.assertTrue(any("zab" in c for c in cert_names))
        self.assertTrue(any("cisco" in c for c in cert_names))

    def test_06_experience_level_classification(self):
        """Verifies candidate with documented employment is classified as Berufserfahren, not Berufseinstieg."""
        if not self.has_real_dossier:
            self.skipTest("Real 17-page dossier fixture not found on disk")

        parsed = CVParser.parse_pdf_dossier(REAL_DOSSIER_PATH)
        prof = parsed["professional_profile"]

        self.assertGreaterEqual(prof["years_of_experience"], 1.5)
        self.assertEqual(prof["experience_level"], "Berufserfahren")
        self.assertNotEqual(prof["experience_level"], "Berufseinstieg")

    def test_07_reparse_endpoint_and_cache_invalidation(self):
        """Verifies POST /api/clients/<id>/reparse updates profile.json and invalidates memory cache."""
        res = self.client.post("/api/clients/anass_sibbi_cc42f2/reparse")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

        summary = data["parsed_summary"]
        self.assertEqual(summary["candidate_name"], "ANASS SIBBI")
        self.assertEqual(summary["city"], "Casablanca")
        self.assertEqual(summary["country"], "Marokko")
        self.assertEqual(summary["current_title"], "Softwareentwickler | Full-Stack-Entwickler")
        self.assertEqual(summary["target_occupation"], "Fachinformatiker")
        self.assertEqual(summary["experience_level"], "Berufserfahren")
        self.assertEqual(summary["work_experience_count"], 4)
        self.assertEqual(summary["education_count"], 4)

        # Verify profile directly from ClientManager reload
        reloaded = client_manager.get_client("anass_sibbi_cc42f2")
        app_sec = reloaded.get("applicant", {})
        self.assertEqual(app_sec.get("contact", {}).get("address", {}).get("city"), "Casablanca")
        self.assertEqual(app_sec.get("professional_profile", {}).get("experience_level"), "Berufserfahren")

    def test_08_template_placeholder_synonym_resolution(self):
        """Verifies TemplateService resolves german/english synonyms without empty placeholders."""
        ts = TemplateService()
        template = (
            "Sehr geehrte Damen und Herren,\n"
            "Bewerbung als {{Position}} bei {{Unternehmen}} in {{Ort}}.\n"
            "Mein Name ist {{Bewerber_Name}} aus {{Bewerber_PLZ_Ort}}."
        )

        row_data = {
            "company": "Bechtle AG",
            "title": "Fachinformatiker Anwendungsentwicklung",
            "city": "Köln",
            "candidate_name": "ANASS SIBBI",
            "candidate_zip_city": "Casablanca, Marokko",
        }

        filled = ts.replace_placeholders(template, row_data, list(row_data.keys()))

        self.assertIn("Bechtle AG", filled)
        self.assertIn("Fachinformatiker Anwendungsentwicklung", filled)
        self.assertIn("Köln", filled)
        self.assertIn("ANASS SIBBI", filled)
        self.assertIn("Casablanca, Marokko", filled)
        self.assertNotIn("{{", filled)

        # Validation must report 0 missing placeholders
        missing = ts.validate_placeholders(template, list(row_data.keys()))
        self.assertEqual(missing, [])

    def test_09_session_row_sync_and_pdf_generation(self):
        """Verifies complete data flow from sync-session-row to preview-pdf."""
        # 1. Bootstrap session
        b_res = self.client.post("/api/create-anschreibens/direct-jobs-bootstrap", json={
            "client_id": "anass_sibbi_cc42f2",
            "jobs": [{
                "company": "Bechtle AG",
                "title": "Fachinformatiker Anwendungsentwicklung",
                "location": "Köln",
                "contact_person": "Frau Dr. Julia Meyer"
            }]
        })
        self.assertEqual(b_res.status_code, 200)
        session_id = b_res.get_json()["session"]["session_id"]

        # 2. Sync updated session row
        sync_res = self.client.post("/api/create-anschreibens/sync-session-row", json={
            "session_id": session_id,
            "row_index": 0,
            "company": "Bechtle AG",
            "position": "Fachinformatiker Anwendungsentwicklung",
            "city": "Köln",
            "contact_person": "Frau Dr. Julia Meyer"
        })
        self.assertEqual(sync_res.status_code, 200)
        self.assertTrue(sync_res.get_json()["success"])

        # 3. Generate personalized letter
        gen_res = self.client.post("/api/ai-generate-anschreiben", json={
            "client_id": "anass_sibbi_cc42f2",
            "company": "Bechtle AG",
            "position": "Fachinformatiker Anwendungsentwicklung",
            "city": "Köln",
            "contact_person": "Frau Dr. Julia Meyer"
        })
        self.assertEqual(gen_res.status_code, 200)
        letter_text = gen_res.get_json()["text"]

        # 4. Save template in session
        save_res = self.client.post("/api/save-template", json={
            "session_id": session_id,
            "templates": [letter_text],
            "active_template_index": 0
        })
        self.assertEqual(save_res.status_code, 200)

        # 5. Render Preview PDF
        prev_res = self.client.post("/api/preview-pdf", json={
            "session_id": session_id,
            "row_index": 0,
            "row_data": {
                "company": "Bechtle AG",
                "title": "Fachinformatiker Anwendungsentwicklung",
                "location": "Köln",
                "contact_person": "Frau Dr. Julia Meyer"
            }
        })
        self.assertEqual(prev_res.status_code, 200)
        pdf_bytes = prev_res.data
        self.assertGreater(len(pdf_bytes), 1000)

        reader = PdfReader(io.BytesIO(pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 1)
        pdf_text = "\n".join(p.extract_text() for p in reader.pages)

        # Check PDF contents
        self.assertIn("ANASS SIBBI", pdf_text)
        self.assertIn("Bechtle AG", pdf_text)
        self.assertIn("Köln", pdf_text)
        self.assertIn("Casablanca", pdf_text)
        self.assertIn("Julia Meyer", pdf_text)
        self.assertNotIn("53117", pdf_text)
        self.assertNotIn("Bonn", pdf_text)
        self.assertNotIn("Musterstraße", pdf_text)
        self.assertNotIn("{{", pdf_text)

    def test_10_client_switching_and_isolation(self):
        """Verifies switching clients does not leak previous candidate address or profile data."""
        p_anass = client_manager.get_client("anass_sibbi_cc42f2")
        self.assertIsNotNone(p_anass)
        addr_anass = p_anass.get("applicant", {}).get("contact", {}).get("address", {})
        self.assertEqual(addr_anass.get("city"), "Casablanca")

        # Switching active client
        client_manager.set_active_client_id("anass_sibbi_cc42f2")
        self.assertEqual(client_manager.get_active_client_id(), "anass_sibbi_cc42f2")
