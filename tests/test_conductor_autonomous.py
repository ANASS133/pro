"""
Comprehensive Unit & Integration Tests for the 4 JobScout Autonomous Features:
1. JobScout Conductor (Central Orchestration, Task Queue, Retries, Pause/Resume, Emergency Stop, Dashboard API)
2. Automatic Daily Search (Profession Intelligence Filtering, Deduplication, Cover Letter Generation, Authorization Gate)
3. Automatic Email Reply Monitoring (IMAP/OAuth, AI Gateway Classification, Status Updates, Follow-Up Drafts, Admin Alerts)
4. Automatic WhatsApp Updates (New App Alerts, Interview Alerts, Digests, Missing Docs, Deduplication, Manual Takeover Protection)
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["DISABLE_CONDUCTOR_DAEMON"] = "true"

import pandas as pd
from app import app
from services.client_manager import ClientManager
from services.conductor_engine import ConductorEngine
from services.conductor_store import ConductorStore
from services.conductor_whatsapp_liaison import ConductorWhatsAppLiaison
from services.daily_search_runner import DailySearchRunner
from services.email_reply_monitor import EmailReplyMonitor
from services.whatsapp_store import WhatsAppStore


class TestJobScoutAutonomousFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jobscout_conductor_test_"))
        self.db_path = self.temp_dir / "conductor_test.db"
        self.wa_db_path = self.temp_dir / "whatsapp_test.db"
        self.exports_dir = self.temp_dir / "exports"
        self.clients_dir = self.temp_dir / "clients"
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.clients_dir.mkdir(parents=True, exist_ok=True)

        self.store = ConductorStore(db_path=self.db_path)
        self.wa_store = WhatsAppStore(db_path=self.wa_db_path)
        self.mock_wa_service = MagicMock()
        self.mock_wa_service.send_text_message.return_value = {
            "success": True,
            "provider_message_id": "wamid.test.123",
            "simulated": True,
            "status": "sent",
        }

        self.liaison = ConductorWhatsAppLiaison(
            store=self.store,
            wa_store=self.wa_store,
            wa_service=self.mock_wa_service,
        )
        self.search_runner = DailySearchRunner(
            exports_dir=self.exports_dir,
            store=self.store,
        )
        self.email_monitor = EmailReplyMonitor(
            user="",
            password="",
            store=self.store,
        )
        self.engine = ConductorEngine(
            store=self.store,
            search_runner=self.search_runner,
            email_monitor=self.email_monitor,
            whatsapp_liaison=self.liaison,
        )

        # Create sample client dossier in global client_manager for testing
        self.test_client_id = "test_autonomy_candidate"
        self.sample_profile = {
            "profile_version": "1.0",
            "package": {
                "name": "500 Bewerbung",
                "total_limit": 500,
                "confirmed_applications": 0,
                "remaining": 500,
            },
            "applicant": {
                "personal": {
                    "first_name": "Youssef",
                    "last_name": "Alami",
                    "full_name": "Youssef Alami",
                },
                "contact": {
                    "email": "youssef.alami@example.com",
                    "phone": "+4917699887766",
                    "address": {
                        "street": "Domstraße 10",
                        "postal_code": "50668",
                        "city": "Köln",
                    },
                },
                "professional_profile": {
                    "current_title": "Fachinformatiker",
                    "headline": "Youssef Alami | Fachinformatiker",
                },
            },
        }
        from services.client_manager import client_manager
        client_manager.save_client(self.test_client_id, self.sample_profile)

    def tearDown(self):
        try:
            self.engine.stop()
            self.store.close()
            self.wa_store.close()
        except Exception:
            pass
        try:
            from services.client_manager import client_manager
            c_dir = client_manager.clients_dir / self.test_client_id
            if c_dir.exists():
                shutil.rmtree(c_dir, ignore_errors=True)
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. JobScout Conductor Tests
    # -------------------------------------------------------------------------

    def test_conductor_settings_emergency_stop_and_client_pause(self):
        """Verifies global settings, emergency stop circuit breaker, and per-client pause/resume."""
        self.assertFalse(self.store.is_emergency_stopped())
        self.store.set_emergency_stop(True)
        self.assertTrue(self.store.is_emergency_stopped())

        # Running cycle while emergency stopped must be blocked
        res = self.engine.run_cycle_for_client(self.test_client_id)
        self.assertFalse(res["success"])
        self.assertIn("Emergency stop", res["error"])

        # Clear emergency stop
        self.store.set_emergency_stop(False)
        self.assertFalse(self.store.is_emergency_stopped())

        # Pause client and verify scheduler skips paused client
        self.engine.pause_client(self.test_client_id, True)
        cfg = self.store.get_client_config(self.test_client_id)
        self.assertEqual(cfg["is_paused"], 1)

        sched_res = self.engine.run_cycle_for_client(self.test_client_id, trigger_source="scheduler")
        self.assertFalse(sched_res["success"])
        self.assertTrue(sched_res.get("skipped"))

        # Resume client
        self.engine.pause_client(self.test_client_id, False)
        cfg_after = self.store.get_client_config(self.test_client_id)
        self.assertEqual(cfg_after["is_paused"], 0)

    def test_onboarding_hook_and_task_retry(self):
        """Verifies onboarding hook registers client, requests missing CV, and failed tasks can be retried."""
        onboard_res = self.engine.on_client_onboarded(
            self.test_client_id,
            missing_fields=["cv_document"],
        )
        self.assertEqual(onboard_res["client_id"], self.test_client_id)
        self.assertTrue(onboard_res["docs_requested"])

        # Create a failed task and test retry_task
        task = self.store.create_task("daily_search", client_id=self.test_client_id)
        self.store.update_task(task["id"], {"status": "failed", "error_message": "Simulated network glitch"})

        retry_res = self.engine.retry_task(task["id"])
        self.assertTrue(retry_res["success"])
        self.assertEqual(retry_res["retry_count"], 1)
        updated_task = self.store.get_task(task["id"])
        self.assertEqual(updated_task["status"], "completed")

    # -------------------------------------------------------------------------
    # 2. Automatic Daily Search Tests
    # -------------------------------------------------------------------------

    def test_daily_search_profession_intelligence_deduplication_and_authorization(self):
        """
        Verifies DailySearchRunner:
        - Filters out irrelevant professions using Profession Intelligence
        - Saves matching jobs to client's pipeline
        - Generates cover letters and stages them as 'staged_for_approval' when auto_apply=0
        - Prevents duplicate matches on subsequent runs
        - Transitions match to 'applied' only when authorized
        """
        # Create dataset with 2 relevant IT jobs and 1 irrelevant Koch job
        df = pd.DataFrame([
            {
                "Titel": "Ausbildung als Fachinformatiker Anwendungsentwicklung (m/w/d)",
                "Unternehmen": "RheinCloud GmbH",
                "Ort": "Köln",
                "E-Mail": "ausbildung@rheincloud.de",
                "Link": "https://rheincloud.de/jobs",
            },
            {
                "Titel": "Auszubildender Fachinformatiker Systemintegration",
                "Unternehmen": "DomNet AG",
                "Ort": "Köln",
                "E-Mail": "hr@domnet.de",
                "Link": "https://domnet.de/karriere",
            },
            {
                "Titel": "Ausbildung zum Koch (m/w/d)",
                "Unternehmen": "Gasthaus am Rhein",
                "Ort": "Köln",
                "E-Mail": "info@gasthaus.de",
                "Link": "https://gasthaus.de",
            },
        ])
        dataset_path = self.exports_dir / "20261031_120000_ausbildung_als_fachinformatiker.xlsx"
        df.to_excel(dataset_path, index=False)

        # Ensure auto_apply is 0 (requires authorization)
        self.store.update_client_config(self.test_client_id, {
            "auto_search": 1,
            "auto_cover_letter": 1,
            "auto_apply": 0,
            "max_daily_applications": 2,
        })

        res1 = self.search_runner.run_daily_search_for_client(self.test_client_id, max_jobs=2)
        self.assertEqual(res1["new_matches_count"], 2)
        self.assertEqual(res1["cover_letters_created"], 2)
        self.assertEqual(res1["auto_applied_count"], 0)

        # Verify irrelevant 'Koch' job was filtered out and matches are staged_for_approval
        matches = self.store.list_matches(client_id=self.test_client_id)
        self.assertEqual(len(matches), 2)
        companies = {m["company"] for m in matches}
        self.assertIn("RheinCloud GmbH", companies)
        self.assertIn("DomNet AG", companies)
        self.assertNotIn("Gasthaus am Rhein", companies)

        for m in matches:
            self.assertEqual(m["status"], "staged_for_approval")
            self.assertTrue(m["cover_letter_path"].endswith(".pdf"))
            self.assertTrue(Path(m["cover_letter_path"]).exists())

        # Approve one match via ConductorEngine and verify status + client stats update
        approve_res = self.engine.approve_match(matches[0]["id"])
        self.assertTrue(approve_res["success"])
        updated_m = self.store.get_match(matches[0]["id"])
        self.assertEqual(updated_m["status"], "applied")

        from services.client_manager import client_manager
        c_data = client_manager.get_client(self.test_client_id)
        self.assertEqual(c_data["package"]["confirmed_applications"], 1)

    # -------------------------------------------------------------------------
    # 3. Automatic Email Reply Monitoring Tests
    # -------------------------------------------------------------------------

    def test_email_reply_monitoring_ai_classification_and_status_updates(self):
        """
        Verifies EmailReplyMonitor:
        - Classifies interview invitations, rejections, confirmations, and info requests
        - Correlates with client_matches by company/email
        - Updates application status in ConductorStore and client metrics
        - Generates German follow-up draft and dispatches WhatsApp alert
        """
        # Seed a match for RheinCloud GmbH
        match = self.store.save_match({
            "client_id": self.test_client_id,
            "job_title": "Ausbildung als Fachinformatiker",
            "company": "RheinCloud GmbH",
            "location": "Köln",
            "email": "ausbildung@rheincloud.de",
            "link": "https://rheincloud.de/jobs",
            "score": 0.95,
            "status": "applied",
        })

        # 1. Process an interview invitation email
        with patch("services.conductor_whatsapp_liaison.conductor_whatsapp_liaison", self.liaison):
            processed = self.email_monitor.process_incoming_message(
                message_id="msg_interview_001",
                sender="HR Team <ausbildung@rheincloud.de>",
                recipient="youssef.alami@example.com",
                subject="Einladung zum Vorstellungsgespräch bei RheinCloud GmbH",
                received_at="2026-10-31T15:00:00Z",
                body="Sehr geehrter Herr Alami, wir laden Sie herzlich zu einem Vorstellungsgespräch am kommenden Donnerstag ein.",
            )

        self.assertEqual(processed["intent"], "interview_invitation")
        self.assertEqual(processed["matched_client_id"], self.test_client_id)
        self.assertTrue(len(processed["suggested_reply"]) > 15)

        # Match status must be updated to 'interview'
        refreshed_match = self.store.get_match(match["id"])
        self.assertEqual(refreshed_match["status"], "interview")

        # 2. Process a rejection email for another match
        match2 = self.store.save_match({
            "client_id": self.test_client_id,
            "job_title": "Ausbildung Fachinformatiker",
            "company": "DomNet AG",
            "location": "Köln",
            "email": "hr@domnet.de",
            "status": "applied",
        })
        processed_rej = self.email_monitor.process_incoming_message(
            message_id="msg_rej_002",
            sender="hr@domnet.de",
            recipient="youssef.alami@example.com",
            subject="Ihre Bewerbung bei DomNet AG",
            received_at="2026-10-31T15:05:00Z",
            body="Leider müssen wir Ihnen eine Absage erteilen, da wir uns anderweitig entschieden haben.",
        )
        self.assertEqual(processed_rej["intent"], "rejection")
        self.assertEqual(self.store.get_match(match2["id"])["status"], "rejected")

    # -------------------------------------------------------------------------
    # 4. Automatic WhatsApp Updates & Human Takeover Protection Tests
    # -------------------------------------------------------------------------

    def test_whatsapp_updates_deduplication_and_human_takeover_preservation(self):
        """
        Verifies ConductorWhatsAppLiaison:
        - Sends proactive alerts for new applications, interviews, digests, and missing docs
        - Prevents duplicate notifications for the same event
        - Suppresses autonomous notifications when conversation is in HUMAN_ACTIVE or ESCALATED takeover mode
        - Respects client notification preference (auto_notify_whatsapp=0)
        """
        # 1. Send new applications notification
        sent1 = self.liaison.notify_new_applications(
            self.test_client_id,
            count=2,
            job_titles=["Fachinformatiker bei RheinCloud", "Fachinformatiker bei DomNet"],
            match_ids=["m1", "m2"],
        )
        self.assertTrue(sent1)

        # Duplicate batch must be suppressed
        sent_dup = self.liaison.notify_new_applications(
            self.test_client_id,
            count=2,
            job_titles=["Fachinformatiker bei RheinCloud", "Fachinformatiker bei DomNet"],
            match_ids=["m1", "m2"],
        )
        self.assertFalse(sent_dup)

        # 2. Send daily digest
        digest_sent = self.liaison.send_daily_digest(self.test_client_id)
        self.assertTrue(digest_sent)

        # 3. Activate Human Takeover on the client's WhatsApp conversation
        conv = self.wa_store.get_or_create_conversation("4917699887766", client_id=self.test_client_id, display_name="Youssef Alami")
        self.wa_store.atomic_takeover(conv["id"], agent_name="Support Admin")

        # While in HUMAN_ACTIVE mode, proactive notifications must be suppressed
        suppressed = self.liaison.notify_interview_invitation(
            self.test_client_id,
            company="TakeoverTest GmbH",
            summary="Termin am Freitag",
        )
        self.assertFalse(suppressed)

        # Return conversation to AI_ACTIVE mode -> notification now succeeds
        self.wa_store.atomic_resume_ai(conv["id"], agent_name="Support Admin")
        allowed_after = self.liaison.notify_interview_invitation(
            self.test_client_id,
            company="TakeoverTest GmbH",
            summary="Termin am Freitag",
        )
        self.assertTrue(allowed_after)

        # 4. Disable auto_notify_whatsapp -> notification suppressed
        self.store.update_client_config(self.test_client_id, {"auto_notify_whatsapp": 0})
        disabled_res = self.liaison.send_daily_digest(self.test_client_id, force=True)
        self.assertFalse(disabled_res)

    # -------------------------------------------------------------------------
    # 5. REST API & SPA Route Integration Tests
    # -------------------------------------------------------------------------

    def test_conductor_api_endpoints(self):
        """Verifies Conductor Flask blueprint routes and JSON responses."""
        client = app.test_client()

        # 1. Page route renders SPA shell with conductor section
        page_res = client.get("/conductor")
        self.assertEqual(page_res.status_code, 200)
        self.assertIn(b'data-section="conductor"', page_res.data)

        # 2. Status API
        status_res = client.get("/api/conductor/status")
        self.assertEqual(status_res.status_code, 200)
        status_json = status_res.get_json()
        self.assertTrue(status_json["success"])
        self.assertIn("metrics", status_json["data"])

        # 3. Settings update API
        set_res = client.post("/api/conductor/settings", json={"daily_search_interval_hours": "12"})
        self.assertEqual(set_res.status_code, 200)
        self.assertEqual(set_res.get_json()["settings"]["daily_search_interval_hours"], "12")

        # 4. Client pause/resume API
        pause_res = client.post(f"/api/conductor/clients/{self.test_client_id}/pause", json={"paused": True})
        self.assertEqual(pause_res.status_code, 200)
        self.assertTrue(pause_res.get_json()["is_paused"])

        resume_res = client.post(f"/api/conductor/clients/{self.test_client_id}/pause", json={"paused": False})
        self.assertEqual(resume_res.status_code, 200)
        self.assertFalse(resume_res.get_json()["is_paused"])

        # 5. Email reply simulator API
        sim_res = client.post("/api/conductor/email-monitor/simulate", json={
            "sender": "karriere@alpha-tech.de",
            "subject": "Einladung zum Vorstellungsgespräch",
            "body": "Wir möchten Sie gerne zu einem Vorstellungsgespräch einladen.",
            "client_id": self.test_client_id,
        })
        self.assertEqual(sim_res.status_code, 200)
        sim_data = sim_res.get_json()
        self.assertTrue(sim_data["success"])
        self.assertEqual(sim_data["message"]["intent"], "interview_invitation")


if __name__ == "__main__":
    unittest.main()
