import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from app import app
from services.client_manager import client_manager
from services.conductor_engine import conductor_engine
from services.conductor_store import conductor_store
from services.onboarding_tracker import onboarding_tracker


class TestConductorApplicationsIntegration(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.created_clients = []
        self.created_app_ids = []

    def tearDown(self):
        # Cleanup created test clients
        for cid in self.created_clients:
            try:
                client_manager.delete_client(cid)
            except Exception:
                pass
        # Cleanup onboarding tracker records
        records = onboarding_tracker.get_all_records()
        modified = False
        for aid in self.created_app_ids:
            if aid in records:
                del records[aid]
                modified = True
        if modified:
            onboarding_tracker._write_records_unlocked(records)

    def _create_mock_client_dossier(self, client_id: str, app_id: str, is_paid: bool = True, has_cv: bool = True, quota: int = 500):
        self.created_clients.append(client_id)
        self.created_app_ids.append(app_id)

        profile = {
            "profile_version": "1.0",
            "metadata": {
                "supabase_application_id": app_id,
                "source": "supabase_onboarding",
                "original_field": "Ausbildung als Fachinformatiker",
            },
            "package": {
                "name": f"{quota} Bewerbung",
                "total_limit": quota,
                "confirmed_applications": 0,
                "remaining": quota,
                "payment_verified": is_paid,
                "bank": "Visa / Stripe",
            },
            "applicant": {
                "personal": {
                    "first_name": "Integration",
                    "last_name": "TestCandidate",
                    "full_name": "Integration TestCandidate",
                },
                "contact": {
                    "email": "testcandidate@integration.de",
                    "phone": "+4917612349999",
                    "address": {
                        "street": "Teststrasse 1",
                        "city": "Koeln",
                        "postal_code": "50667",
                        "country": "Deutschland"
                    }
                },
                "professional_profile": {
                    "current_title": "Fachinformatiker Anwendungsentwicklung",
                    "headline": "Junior Software Developer",
                    "primary_fields": ["Softwareentwicklung", "Webentwicklung"],
                },
                "job_application": {
                    "availability": {"earliest_start_date": "asap"},
                    "relocation": {"willing_to_relocate": True, "target_cities": ["Koeln", "Bonn"]},
                    "work_model": {"remote": True, "hybrid": True},
                },
                "languages": [{"language": "Deutsch", "level": "B2"}],
                "documents": ["Lebenslauf.pdf"] if has_cv else []
            }
        }

        client_manager.save_client(client_id, profile)
        if has_cv:
            client_manager.save_document(client_id, b"%PDF-1.4 mock cv", "Lebenslauf.pdf")
        conductor_store.get_client_config(client_id)

    def test_eligible_paid_client_appears_in_conductor_with_full_dossier(self):
        cid = "test_candidate_conductor_sync"
        aid = "app-uuid-sync-1001"
        self._create_mock_client_dossier(cid, aid, is_paid=True, has_cv=True, quota=1000)

        status = conductor_engine.get_status()
        managed = {c["id"]: c for c in status.get("clients", [])}
        self.assertIn(cid, managed)

        client = managed[cid]
        # Contact and Identification
        self.assertEqual(client.get("supabase_application_id"), aid)
        self.assertEqual(client.get("email"), "testcandidate@integration.de")
        self.assertEqual(client.get("opportunity_type"), "Ausbildung")
        self.assertEqual(client.get("target_profession"), "Fachinformatiker Anwendungsentwicklung")

        # Quota and Package
        quota = client.get("quota", {})
        self.assertEqual(quota.get("total_limit"), 1000)
        self.assertEqual(quota.get("remaining"), 1000)
        self.assertFalse(quota.get("is_exhausted"))

        # Payment
        payment = client.get("payment", {})
        self.assertTrue(payment.get("is_paid"))
        self.assertEqual(payment.get("status"), "paid")

        # Readiness
        readiness = client.get("readiness", {})
        self.assertTrue(readiness.get("is_ready_for_automation"))
        self.assertEqual(readiness.get("blocking_reasons"), [])
        self.assertTrue(readiness.get("premium_followup_eligible"))

        # Documents
        self.assertTrue(client.get("has_cv"))
        self.assertGreaterEqual(len(client.get("documents", [])), 1)

    def test_preflight_safety_blocks_unpaid_client(self):
        cid = "test_unpaid_candidate"
        aid = "app-uuid-unpaid-2002"
        self._create_mock_client_dossier(cid, aid, is_paid=False, has_cv=True)
        # Explicitly ensure package is marked unverified
        p = client_manager.get_client(cid)
        p["package"]["payment_verified"] = False
        p["metadata"]["supabase_application_id"] = ""
        client_manager.save_client(cid, p)

        res = conductor_engine.run_cycle_for_client(cid)
        self.assertFalse(res.get("success"))
        self.assertTrue(res.get("skipped"))
        self.assertEqual(res.get("reason"), "unpaid_client")

    def test_preflight_safety_blocks_missing_cv(self):
        cid = "test_missing_cv_candidate"
        aid = "app-uuid-no-cv-3003"
        self._create_mock_client_dossier(cid, aid, is_paid=True, has_cv=False)

        res = conductor_engine.run_cycle_for_client(cid)
        self.assertFalse(res.get("success"))
        self.assertTrue(res.get("skipped"))
        self.assertEqual(res.get("reason"), "incomplete_dossier")

    def test_preflight_safety_blocks_exhausted_quota(self):
        cid = "test_exhausted_quota_candidate"
        aid = "app-uuid-quota-4004"
        self._create_mock_client_dossier(cid, aid, is_paid=True, has_cv=True, quota=2)

        # Mock that 2 applications are already marked as applied
        conductor_store.save_match({
            "client_id": cid,
            "job_title": "Job 1",
            "company": "Company A",
            "status": "applied",
            "created_at": "2026-11-01T12:00:00Z"
        })
        conductor_store.save_match({
            "client_id": cid,
            "job_title": "Job 2",
            "company": "Company B",
            "status": "applied",
            "created_at": "2026-11-01T12:01:00Z"
        })

        res = conductor_engine.run_cycle_for_client(cid)
        self.assertFalse(res.get("success"))
        self.assertTrue(res.get("skipped"))
        self.assertEqual(res.get("reason"), "quota_exhausted")

    @patch("services.supabase_service.supabase_service.list_applications")
    def test_sync_applications_endpoint(self, mock_list_apps):
        mock_list_apps.return_value = []
        resp = self.client.post("/api/conductor/sync-applications")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("total_managed_clients", data)


if __name__ == "__main__":
    unittest.main()

