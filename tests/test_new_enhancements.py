import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import app
from email_sender.follow_up import FollowUpManager
from email_sender.spam_analyzer import SpamScoreAnalyzer
from scraper.career_crawler import CareerPageCrawler
from scraper.tech_detector import TechDetector


class TestNewEnhancements(unittest.TestCase):
    """Test suite for Tech Detection, Career Crawling, Spam Scoring, and Follow-Up Management."""

    def setUp(self):
        self.client = app.test_client()

    def test_tech_detector(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="generator" content="WordPress 6.4.3" />
            <link rel="stylesheet" href="/wp-content/themes/twentytwentyfour/style.css" />
            <script src="/_next/static/chunks/main.js"></script>
        </head>
        <body data-reactroot="">
            <h1>Willkommen</h1>
        </body>
        </html>
        """
        tech_data = TechDetector.detect(html)
        self.assertIn("WordPress", tech_data["technologies"])
        self.assertIn("React", tech_data["technologies"])
        self.assertEqual(tech_data["primary_cms"], "WordPress")

    def test_career_page_crawler(self):
        html = """
        <html>
        <body>
            <a href="/karriere">Karriere & Jobs</a>
            <a href="/kontakt">Kontakt</a>
            <div>
                <h2>Vertriebsmitarbeiter (m/w/d)</h2>
                <p>Initiativbewerbungen sind bei uns jederzeit herzlich willkommen!</p>
                <p>Senden Sie Ihre Unterlagen an: <a href="mailto:bewerbung@tech-unternehmen.de">E-Mail</a></p>
            </div>
        </body>
        </html>
        """
        urls = CareerPageCrawler.find_career_urls("https://tech-unternehmen.de", html)
        self.assertTrue(any("karriere" in u for u in urls))

        parsed = CareerPageCrawler.parse_career_page(html, career_url="https://tech-unternehmen.de/karriere")
        self.assertTrue(parsed["initiativ_welcomed"])
        self.assertIn("bewerbung@tech-unternehmen.de", parsed["hr_emails"])
        self.assertTrue(any("Vertriebsmitarbeiter" in j for j in parsed["jobs_found"]))

    def test_spam_score_analyzer(self):
        # High risk spam message
        bad_subject = "WICHTIG: 100% KOSTENLOS GELD VERDIENEN JETZT HANDELN!!!"
        bad_body = "Exklusives Angebot! Klicken Sie hier und verdienen Sie ohne Risiko sofort Geld!"
        bad_res = SpamScoreAnalyzer.analyze(bad_subject, bad_body)

        self.assertLess(bad_res["score"], 60)
        self.assertEqual(bad_res["risk"], "HIGH")
        self.assertFalse(bad_res["is_safe"])
        self.assertTrue(len(bad_res["warnings"]) > 0)

        # Clean professional outreach message
        clean_subject = "Bewerbung als Python Backend Entwickler - Max Mustermann"
        clean_body = (
            "Sehr geehrte Damen und Herren,\n\n"
            "mit großem Interesse habe ich Ihre Stellenausschreibung gelesen. "
            "Meine vollständigen Bewerbungsunterlagen finden Sie im Anhang.\n\n"
            "Mit freundlichen Grüßen\nMax Mustermann"
        )
        clean_res = SpamScoreAnalyzer.analyze(clean_subject, clean_body)
        self.assertGreaterEqual(clean_res["score"], 80)
        self.assertEqual(clean_res["risk"], "LOW")
        self.assertTrue(clean_res["is_safe"])

    def test_follow_up_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "outreach_history.json"
            now = datetime.now()
            eight_days_ago = (now - timedelta(days=8)).isoformat()

            fake_history = {
                "example-corp.de": {
                    "last_sent": eight_days_ago,
                    "last_email": "hr@example-corp.de",
                    "history": [
                        {
                            "timestamp": eight_days_ago,
                            "email": "hr@example-corp.de",
                            "subject": "Bewerbung als Softwareentwickler",
                        }
                    ],
                }
            }

            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(fake_history, f)

            manager = FollowUpManager(history_file=history_file)
            eligible = manager.find_eligible_follow_ups(min_days=5, max_days=14)

            self.assertEqual(len(eligible), 1)
            candidate = eligible[0]
            self.assertEqual(candidate["domain"], "example-corp.de")
            self.assertEqual(candidate["days_ago"], 8)

            draft = FollowUpManager.generate_follow_up(
                candidate_entry=candidate,
                sender_name="Anna Schmidt",
                job_title="Softwareentwickler",
                salutation="Sehr geehrte Frau Müller,",
            )
            self.assertIn("Softwareentwickler", draft["subject"])
            self.assertIn("Sehr geehrte Frau Müller,", draft["body"])
            self.assertIn("Anna Schmidt", draft["body"])

    def test_api_routes(self):
        # 1. Map data endpoint
        map_resp = self.client.get("/api/map-data")
        self.assertEqual(map_resp.status_code, 200)
        data = map_resp.get_json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["markers"], list)

        # 2. Spam analysis API
        spam_resp = self.client.post(
            "/api/email/analyze-spam",
            json={"subject": "Bewerbung", "body": "Sehr geehrte Damen und Herren,\nMit freundlichen Grüßen"},
        )
        self.assertEqual(spam_resp.status_code, 200)
        spam_data = spam_resp.get_json()
        self.assertTrue(spam_data["success"])
        self.assertIn("score", spam_data["analysis"])

        # 3. Follow up draft API
        draft_resp = self.client.post(
            "/api/email/follow-up/draft",
            json={
                "email": "jobs@startup.de",
                "days_ago": 7,
                "job_title": "Frontend Entwickler",
                "sender_name": "Tom Weber",
            },
        )
        self.assertEqual(draft_resp.status_code, 200)
        draft_data = draft_resp.get_json()
        self.assertTrue(draft_data["success"])
        self.assertIn("Frontend Entwickler", draft_data["draft"]["subject"])


if __name__ == "__main__":
    unittest.main()
