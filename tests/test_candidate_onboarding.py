"""
Comprehensive Automated Test Suite for Supabase Candidate Onboarding Pipeline.
Covers 16 core scenarios:
1. Valid paid application with a valid CV.
2. Unpaid application (rejected with 400 PaymentUnverifiedError).
3. Application without documents (creates candidate dossier from submitted form data).
4. Application with multiple PDFs (verifies CV is prioritized over certificates and diplomas).
5. Invalid or corrupted CV (handles text extraction failure gracefully).
6. Supabase Storage download failure (returns error without crashing).
7. Duplicate onboarding request (idempotent, returns existing candidate without re-creation).
8. Two concurrent requests for the same application (mutex lock prevents double creation).
9. Multiple different clients processed concurrently (collision-free directories).
10. CV and form data inconsistencies (authoritative form data takes precedence).
11. Invalid / non-standard package name (normalized correctly).
12. Missing application_id (returns appropriate 400 error).
13. Backend restart persistence (reloads from onboarding_records.json).
14. Existing candidate re-import with force_reimport=True.
15. Autofill profile synchronization (verifies ai-job-autofill mirrors candidate profile).
16. Cover Letter Studio candidate resolution route (/api/supabase/candidate-by-application/<id>).
"""

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fpdf import FPDF

from app import app
from services.client_manager import ClientManager
from services.cv_parser import CVParser
from services.onboarding_tracker import OnboardingTracker, OnboardingStatus
from services.onboarding_service import CandidateOnboardingService, PaymentUnverifiedError
from services.supabase_service import SupabaseService


def _create_synthetic_cv_pdf(name: str = "Tarik Bennani", email: str = "tarik@example.com", phone: str = "+212 600 112233") -> bytes:
    """Generate synthetic in-memory CV PDF with complete personal and address markers."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    pdf.cell(0, 10, f"Lebenslauf - {name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 7, f"E-Mail: {email}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Telefon: {phone}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Geburtsdatum: 15.05.1998", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Adresse: Musterstrasse 10, 10115 Berlin, Deutschland", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=13)
    pdf.cell(0, 9, "Berufserfahrung", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, "2021 - 2024: IT-Systemelektroniker bei Tech GmbH", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Aufgaben: Netzwerk-Administration, Python-Automatisierung, Kundensupport", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=13)
    pdf.cell(0, 9, "Ausbildung & Kenntnisse", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, "Sprachen: Deutsch (B2 Goethe Zertifikat), Englisch (fliessend), Arabisch", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Kenntnisse: Python, Linux, SQL, Docker, FastAPI", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _create_synthetic_certificate_pdf(title: str = "Goethe B2 Zertifikat") -> bytes:
    """Generate synthetic certificate PDF (not a CV)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, "Hiermit wird bestaetigt, dass die Sprachpruefung erfolgreich bestanden wurde.", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Notenstufe: Gut (82/100)", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


class CandidateOnboardingPipelineTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.flask_client = app.test_client()

        # Temporary directories for isolation
        self.test_clients_dir = Path(tempfile.mkdtemp(prefix="test_clients_"))
        self.test_autofill_dir = Path(tempfile.mkdtemp(prefix="test_af_"))
        self.test_tracker_file = Path(tempfile.mktemp(prefix="test_tracker_", suffix=".json"))

        self.client_manager = ClientManager(clients_dir=self.test_clients_dir, autofill_dir=self.test_autofill_dir)
        self.cv_parser = CVParser()
        self.tracker = OnboardingTracker(storage_file=self.test_tracker_file)
        self.mock_supabase = MagicMock(spec=SupabaseService)

        self.service = CandidateOnboardingService(
            client_manager=self.client_manager,
            supabase_service=self.mock_supabase,
            cv_parser=self.cv_parser,
            tracker=self.tracker,
        )

    def tearDown(self):
        shutil.rmtree(self.test_clients_dir, ignore_errors=True)
        shutil.rmtree(self.test_autofill_dir, ignore_errors=True)
        if self.test_tracker_file.exists():
            try:
                self.test_tracker_file.unlink()
            except OSError:
                pass

    # --- Scenario 1: Valid Paid Application with Valid CV ---
    def test_01_valid_paid_application_with_valid_cv(self):
        app_id = "app-uuid-001"
        cv_bytes = _create_synthetic_cv_pdf(name="Amine El Fassi", email="amine@form-authoritative.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Amine El Fassi",
            "email": "amine@form-authoritative.de",
            "whatsapp": "+212 611 223344",
            "language_level": "B2",
            "field": "Informatik",
            "pack": "500 Bewerbung",
            "bank": "CIH Bank",
            "documents": ["users/amine/Lebenslauf.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv_bytes, "Lebenslauf.pdf", "application/pdf")

        result = self.service.onboard_candidate(app_id)

        self.assertTrue(result["success"])
        self.assertTrue(result["profile_ready"])
        self.assertTrue(result["cv_parsed"])
        self.assertEqual(result["onboarding_status"], OnboardingStatus.READY)
        self.assertEqual(result["documents_imported"], 1)

        # Check candidate directory
        client_id = result["client_id"]
        client_profile = self.client_manager.get_client(client_id)
        self.assertIsNotNone(client_profile)
        self.assertEqual(client_profile["applicant"]["contact"]["email"], "amine@form-authoritative.de")
        self.assertEqual(client_profile["package"]["total_limit"], 500)
        self.assertEqual(client_profile["metadata"]["supabase_application_id"], app_id)

    # --- Scenario 2: Unpaid Application (Must Reject) ---
    def test_02_unpaid_application_rejection(self):
        app_id = "app-uuid-unpaid"
        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Unpaid Candidate",
            "email": "unpaid@test.de",
            "whatsapp": "+49 151 000000",
            "documents": [],
            "is_payed": False,  # Not verified
        }

        with self.assertRaises(PaymentUnverifiedError):
            self.service.onboard_candidate(app_id)

        # Ensure no candidate profile was created
        record = self.tracker.get_record(app_id)
        self.assertIsNotNone(record)
        self.assertEqual(record["status"], OnboardingStatus.PENDING_PAYMENT)
        self.assertFalse(record["payment_verified"])

    # --- Scenario 3: Application Without Documents ---
    def test_03_application_without_documents(self):
        app_id = "app-uuid-nodocs"
        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Nora Mansour",
            "email": "nora@test.de",
            "whatsapp": "+49 170 1234567",
            "language_level": "C1",
            "field": "Pflege",
            "pack": "1000",
            "documents": [],
            "is_payed": True,
        }

        result = self.service.onboard_candidate(app_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["documents_imported"], 0)
        self.assertFalse(result["cv_parsed"])
        # Should flag review required because no CV was uploaded
        self.assertEqual(result["onboarding_status"], OnboardingStatus.PROFILE_REVIEW_REQUIRED)
        self.assertIn("cv_document", result["missing_fields"])

    # --- Scenario 4: Multiple PDFs - Verify CV Identification ---
    def test_04_multiple_pdfs_cv_prioritization(self):
        app_id = "app-uuid-multipdf"
        cert1_bytes = _create_synthetic_certificate_pdf("Abiturzeugnis")
        cert2_bytes = _create_synthetic_certificate_pdf("Goethe B1 Zertifikat")
        cv_bytes = _create_synthetic_cv_pdf("Karim Benzema", "karim@benzema.de")

        # Documents list has certificates before CV
        docs = [
            "uploads/karim/Abitur.pdf",
            "uploads/karim/B1_Zertifikat.pdf",
            "uploads/karim/Mein_Lebenslauf_2025.pdf",
        ]

        def fake_download(path):
            if "Lebenslauf" in path:
                return (cv_bytes, "Mein_Lebenslauf_2025.pdf", "application/pdf")
            if "Abitur" in path:
                return (cert1_bytes, "Abitur.pdf", "application/pdf")
            return (cert2_bytes, "B1_Zertifikat.pdf", "application/pdf")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Karim Benzema",
            "email": "karim@benzema.de",
            "whatsapp": "+33 600 000000",
            "pack": "2000",
            "documents": docs,
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.side_effect = fake_download

        result = self.service.onboard_candidate(app_id)

        self.assertTrue(result["success"])
        self.assertTrue(result["cv_parsed"])
        self.assertEqual(result["documents_imported"], 3)

        # Check that CV document was saved as Lebenslauf.pdf
        client_dir = self.test_clients_dir / result["client_id"] / "documents"
        cv_file = client_dir / "Lebenslauf.pdf"
        self.assertTrue(cv_file.exists())

    # --- Scenario 5: Invalid / Corrupted CV Handled Gracefully ---
    def test_05_corrupted_cv_pdf(self):
        app_id = "app-uuid-corrupt"
        corrupted_bytes = b"%PDF-1.4 ... truncated / corrupted data [bad-eof]"

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Broken File Candidate",
            "email": "broken@test.de",
            "documents": ["uploads/broken/Lebenslauf.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (corrupted_bytes, "Lebenslauf.pdf", "application/pdf")

        result = self.service.onboard_candidate(app_id)

        self.assertTrue(result["success"])
        # Parsing failed gracefully without unhandled crash
        self.assertFalse(result["cv_parsed"])
        self.assertEqual(result["onboarding_status"], OnboardingStatus.PROFILE_REVIEW_REQUIRED)

    # --- Scenario 6: Storage Download Failure Handled Gracefully ---
    def test_06_storage_download_failure(self):
        app_id = "app-uuid-dl-fail"
        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Missing Doc User",
            "email": "missing@test.de",
            "documents": ["non_existent_bucket/doc.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.side_effect = RuntimeError("Supabase Storage 404: Not Found")

        result = self.service.onboard_candidate(app_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["documents_imported"], 0)
        self.assertEqual(result["onboarding_status"], OnboardingStatus.PROFILE_REVIEW_REQUIRED)

    # --- Scenario 7: Duplicate Onboarding Request (Idempotency) ---
    def test_07_duplicate_request_idempotency(self):
        app_id = "app-uuid-dup"
        cv_bytes = _create_synthetic_cv_pdf("Yassine Bounou", "yassine@bounou.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Yassine Bounou",
            "email": "yassine@bounou.de",
            "pack": "500",
            "documents": ["yassine/CV.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv_bytes, "CV.pdf", "application/pdf")

        # First call
        res1 = self.service.onboard_candidate(app_id)
        first_client_id = res1["client_id"]

        # Second call with same application
        res2 = self.service.onboard_candidate(app_id)
        second_client_id = res2["client_id"]

        # Must return same candidate without duplicating
        self.assertEqual(first_client_id, second_client_id)
        self.assertTrue(res2.get("already_imported"))

    # --- Scenario 8: Concurrent Requests for Same Application ---
    def test_08_concurrent_requests_same_application(self):
        app_id = "app-uuid-concur"
        cv_bytes = _create_synthetic_cv_pdf("Hakim Ziyech", "hakim@chelsea.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Hakim Ziyech",
            "email": "hakim@ziyech.de",
            "pack": "1000",
            "documents": ["ziyech/CV.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv_bytes, "CV.pdf", "application/pdf")

        results = []
        errors = []

        def worker():
            try:
                res = self.service.onboard_candidate(app_id)
                results.append(res)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 2)
        # Both threads must resolve to the identical client ID
        self.assertEqual(results[0]["client_id"], results[1]["client_id"])

    # --- Scenario 9: Multiple Different Clients Processed Concurrently ---
    def test_09_multiple_clients_concurrency_no_collision(self):
        client_names = [f"Client {i}" for i in range(5)]
        results = {}

        def worker(idx, name):
            app_id = f"app-uuid-multi-{idx}"
            cv = _create_synthetic_cv_pdf(name, f"client{idx}@example.de")

            local_mock = MagicMock(spec=SupabaseService)
            local_mock.get_application.return_value = {
                "id": app_id,
                "full_name": name,
                "email": f"client{idx}@example.de",
                "pack": "500",
                "documents": [f"c{idx}/CV.pdf"],
                "is_payed": True,
            }
            local_mock.get_document_bytes.return_value = (cv, "CV.pdf", "application/pdf")

            srv = CandidateOnboardingService(
                client_manager=self.client_manager,
                supabase_service=local_mock,
                cv_parser=self.cv_parser,
                tracker=self.tracker,
            )
            res = srv.onboard_candidate(app_id)
            results[idx] = res

        threads = [threading.Thread(target=worker, args=(i, name)) for i, name in enumerate(client_names)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)
        client_ids = [r["client_id"] for r in results.values()]
        # All client IDs must be unique
        self.assertEqual(len(set(client_ids)), 5)

    # --- Scenario 10: Inconsistency Between CV and Form (Form Wins Contact) ---
    def test_10_cv_form_inconsistency_authoritative_form(self):
        app_id = "app-uuid-inconsistency"
        # CV text has old email and old phone
        cv_bytes = _create_synthetic_cv_pdf(name="Sofyan Amrabat", email="old_cv_email@yahoo.com", phone="+31 600000")

        # Form submission has authoritative current contact
        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Sofyan Amrabat",
            "email": "authoritative_form@manutd.com",
            "whatsapp": "+44 700 112233",
            "language_level": "B2",
            "pack": "1000",
            "documents": ["cv.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv_bytes, "cv.pdf", "application/pdf")

        result = self.service.onboard_candidate(app_id)

        client = self.client_manager.get_client(result["client_id"])
        contact = client["applicant"]["contact"]

        # Form data must override CV for contact information
        self.assertEqual(contact["email"], "authoritative_form@manutd.com")
        self.assertEqual(contact["phone"], "+44 700 112233")

    # --- Scenario 11: Invalid / Non-standard Package Normalization ---
    def test_11_invalid_package_normalization(self):
        app_id = "app-uuid-pack"
        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Package Tester",
            "email": "pack@test.de",
            "pack": "custom-vip-pack-unrecognized",
            "documents": [],
            "is_payed": True,
        }

        result = self.service.onboard_candidate(app_id)
        client = self.client_manager.get_client(result["client_id"])

        # Default fallback package is 500 Bewerbungen
        self.assertEqual(client["package"]["total_limit"], 500)
        self.assertEqual(client["package"]["original_label"], "custom-vip-pack-unrecognized")

    # --- Scenario 12: Missing Application ID Validation ---
    def test_12_missing_application_id_api_validation(self):
        resp = self.flask_client.post(
            "/api/supabase/onboard-candidate",
            json={},  # Missing application_id
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "INVALID_REQUEST")

    # --- Scenario 13: Restart Persistence (Reloads Records) ---
    def test_13_restart_persistence(self):
        app_id = "app-uuid-restart"
        cv = _create_synthetic_cv_pdf("Persistence Test", "pers@test.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Persistence Test",
            "email": "pers@test.de",
            "pack": "500",
            "documents": ["cv.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv, "cv.pdf", "application/pdf")

        self.service.onboard_candidate(app_id)

        # Simulate backend restart by instantiating a fresh tracker pointing to same file
        fresh_tracker = OnboardingTracker(storage_file=self.test_tracker_file)
        fresh_rec = fresh_tracker.get_record(app_id)

        self.assertIsNotNone(fresh_rec)
        self.assertEqual(fresh_rec["application_id"], app_id)
        self.assertEqual(fresh_rec["status"], OnboardingStatus.READY)

    # --- Scenario 14: Existing Candidate Re-Import (force_reimport=True) ---
    def test_14_force_reimport(self):
        app_id = "app-uuid-reimport"
        cv1 = _create_synthetic_cv_pdf("Reimport User", "v1@test.de")
        cv2 = _create_synthetic_cv_pdf("Reimport User", "v2@test.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Reimport User",
            "email": "v1@test.de",
            "pack": "500",
            "documents": ["cv.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv1, "cv.pdf", "application/pdf")

        res1 = self.service.onboard_candidate(app_id)
        cid = res1["client_id"]

        # Update application data
        self.mock_supabase.get_application.return_value["email"] = "v2@test.de"
        self.mock_supabase.get_document_bytes.return_value = (cv2, "cv.pdf", "application/pdf")

        res2 = self.service.onboard_candidate(app_id, force_reimport=True)
        self.assertEqual(res2["client_id"], cid)

        client = self.client_manager.get_client(cid)
        self.assertEqual(client["applicant"]["contact"]["email"], "v2@test.de")

    # --- Scenario 15: Autofill Profile Synchronization ---
    def test_15_autofill_profile_mirroring(self):
        app_id = "app-uuid-af-sync"
        cv = _create_synthetic_cv_pdf("Bilal El Khannouss", "bilal@sync.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "Bilal El Khannouss",
            "email": "bilal@sync.de",
            "whatsapp": "+32 400 998877",
            "language_level": "B2",
            "field": "Sportmanagement",
            "pack": "1000",
            "documents": ["cv.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv, "cv.pdf", "application/pdf")

        res = self.service.onboard_candidate(app_id)
        cid = res["client_id"]

        # Verify mirrored file in autofill directory
        af_profile_path = self.test_autofill_dir / f"{cid}.json"
        self.assertTrue(af_profile_path.exists())
        with open(af_profile_path, "r", encoding="utf-8") as f:
            af_data = json.load(f)
        self.assertEqual(af_data["applicant"]["contact"]["email"], "bilal@sync.de")
        self.assertEqual(af_data["applicant"]["personal"]["full_name"], "Bilal El Khannouss")

    # --- Scenario 16: Cover Letter Studio Candidate Resolution Route ---
    def test_16_candidate_by_application_route(self):
        # 1. Non-existent application returns 404
        resp = self.flask_client.get("/api/supabase/candidate-by-application/non-existent-uuid")
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertFalse(data["success"])

        # 2. Existing onboarded application
        app_id = "app-uuid-cls-compat"
        cv = _create_synthetic_cv_pdf("CLS Compat Candidate", "cls@test.de")

        self.mock_supabase.get_application.return_value = {
            "id": app_id,
            "full_name": "CLS Compat Candidate",
            "email": "cls@test.de",
            "pack": "500",
            "documents": ["cv.pdf"],
            "is_payed": True,
        }
        self.mock_supabase.get_document_bytes.return_value = (cv, "cv.pdf", "application/pdf")

        # Ingest through onboarding service
        self.service.onboard_candidate(app_id)

        # Patch onboarding_tracker and client_manager in routes.supabase_onboarding
        with patch("routes.supabase_onboarding.onboarding_tracker", self.tracker), \
             patch("routes.supabase_onboarding.client_manager", self.client_manager):
            resp = self.flask_client.get(f"/api/supabase/candidate-by-application/{app_id}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertIn("profile", data)
            self.assertEqual(data["profile"]["applicant"]["contact"]["email"], "cls@test.de")


if __name__ == "__main__":
    unittest.main()
