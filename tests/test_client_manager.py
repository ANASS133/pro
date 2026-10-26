"""
Unit tests for ClientManager service and /api/clients endpoints.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from fpdf import FPDF

from app import app
from services.client_manager import ClientManager, client_manager


def _create_sample_pdf(name: str = "Max Mustermann", email: str = "max.mustermann@example.com", city: str = "50667 Koeln") -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, f"Lebenslauf - {name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"E-Mail: {email}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Telefon: +49 171 9876543", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Wohnort: {city}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Kenntnisse: Python, JavaScript, Docker, Git, SQL", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Sprachen: Deutsch (Muttersprache), Englisch (fließend)", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


class ClientManagerTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp(prefix="test_clients_")
        self.test_af_dir = tempfile.mkdtemp(prefix="test_af_")
        self.mgr = ClientManager(clients_dir=Path(self.test_dir), autofill_dir=Path(self.test_af_dir))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        shutil.rmtree(self.test_af_dir, ignore_errors=True)

    def test_create_and_get_client(self):
        sample = {
            "applicant": {
                "personal": {"first_name": "Erika", "last_name": "Musterfrau", "full_name": "Erika Musterfrau"},
                "contact": {"email": "erika@example.de", "phone": "+49151234567"}
            }
        }
        saved = self.mgr.save_client("erika_musterfrau", sample)
        self.assertTrue(saved)

        loaded = self.mgr.get_client("erika_musterfrau")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["applicant"]["personal"]["first_name"], "Erika")

        # Test listing
        clients = self.mgr.list_clients()
        ids = [c["id"] for c in clients]
        self.assertIn("erika_musterfrau", ids)

    def test_active_client_switching(self):
        self.mgr.save_client("client_a", {"applicant": {"personal": {"full_name": "Client A"}}})
        self.mgr.save_client("client_b", {"applicant": {"personal": {"full_name": "Client B"}}})

        self.mgr.set_active_client_id("client_a")
        self.assertEqual(self.mgr.get_active_client_id(), "client_a")

        self.mgr.set_active_client_id("client_b")
        self.assertEqual(self.mgr.get_active_client_id(), "client_b")

    def test_cv_ingestion(self):
        pdf_bytes = _create_sample_pdf(name="Klaus Schmidt", email="klaus.schmidt@test.de", city="10115 Berlin")
        result = self.mgr.ingest_cv(pdf_bytes, filename="Lebenslauf_Klaus.pdf")

        self.assertTrue(result["success"])
        self.assertEqual(result["client_id"], "klaus_schmidt")
        self.assertEqual(self.mgr.get_active_client_id(), "klaus_schmidt")

        # Verify documents
        docs = self.mgr.list_documents("klaus_schmidt")
        self.assertTrue(len(docs) >= 1)
        self.assertEqual(docs[0]["file_name"], "Lebenslauf_Klaus.pdf")

    def test_api_clients_list_and_active(self):
        # API listing test
        resp = self.client.get("/api/clients")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("clients", data)
        self.assertIn("active_client_id", data)

    def test_api_active_client_switching(self):
        # Setup an active client
        client_manager.save_client("test_switch_client", {
            "applicant": {
                "personal": {"first_name": "Test", "last_name": "Switch", "full_name": "Test Switch"},
                "contact": {"email": "switch@test.de"}
            }
        })
        resp = self.client.post("/api/clients/active", json={"client_id": "test_switch_client"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["active_client_id"], "test_switch_client")

        # Get active
        active_resp = self.client.get("/api/clients/active")
        self.assertEqual(active_resp.status_code, 200)
        active_data = active_resp.get_json()
        self.assertEqual(active_data["client_id"], "test_switch_client")

        # Clean up
        client_manager.delete_client("test_switch_client")

    def test_api_cv_ingest(self):
        pdf_bytes = _create_sample_pdf(name="Sara Berg", email="sara.berg@agency.de", city="20095 Hamburg")
        data = {
            "cv_file": (io.BytesIO(pdf_bytes), "Sara_Berg_CV.pdf")
        }
        resp = self.client.post("/api/clients/ingest-cv", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        res = resp.get_json()
        self.assertTrue(res["success"])
        self.assertEqual(res["client_id"], "sara_berg")
        self.assertEqual(client_manager.get_active_client_id(), "sara_berg")

        # Clean up
        client_manager.delete_client("sara_berg")


if __name__ == "__main__":
    unittest.main()
