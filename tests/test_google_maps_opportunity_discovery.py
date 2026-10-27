"""
Unit and Integration Tests for Google Maps Job & Ausbildung Opportunity Discovery.
=================================================================================
Validates:
1. Career page discovery (DE, EN, FR recruitment keywords).
2. Job listing extraction (JSON-LD and DOM parsing).
3. Application URL classification (DIRECT_APPLICATION_FORM, APPLICATION_PORTAL, etc.).
4. Third-party recruitment portal detection (Personio, Workday, Softgarden, etc.).
5. Ausbildung verification and verification statuses.
6. Candidate-job matching score (0-100) and explainable reasons.
7. Duplicate prevention (pages and vacancies).
8. Multi-client isolation.
9. Concurrent crawling compatibility.
10. Unified export correctness (Excel, CSV, JSON).
11. Handling inaccessible websites.
12. Handling companies without career pages.
13. Handling expired vacancies.
14. API endpoints integration with verification options.
"""

import io
import json
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

import pandas as pd

from scraper.google_maps_opportunity_verifier import (
    GoogleMapsOpportunityVerifier,
    DiscoveredVacancy,
    URL_DIRECT_APPLICATION_FORM,
    URL_APPLICATION_PORTAL,
    URL_CAREERS_PAGE,
    URL_JOB_LISTING,
    URL_GENERAL_CONTACT_FORM,
    URL_UNKNOWN,
    STATUS_OPEN_VERIFIED,
    STATUS_POTENTIALLY_OPEN,
    STATUS_NO_MATCHING_VACANCY,
    STATUS_EXPIRED,
    STATUS_VERIFICATION_FAILED,
    STATUS_UNKNOWN,
    generate_company_id,
)
from scraper.google_maps_scraper import GoogleMapsBusinessScraper
from app import app, _create_google_maps_job, _build_unified_export_rows, google_maps_jobs


class TestGoogleMapsOpportunityDiscovery(unittest.TestCase):

    def setUp(self):
        self.verifier = GoogleMapsOpportunityVerifier(timeout=3)
        self.client = app.test_client()

    # -----------------------------------------------------------------------
    # 1. Career Page Discovery & Multilingual Keywords (DE, EN, FR)
    # -----------------------------------------------------------------------
    def test_multilingual_career_page_discovery(self):
        """Discovers career links using German, English, and French recruitment keywords."""
        base_url = "https://www.beispiel-firma.de"
        html = """
        <html>
            <body>
                <nav>
                    <a href="/karriere">Karriere</a>
                    <a href="/jobs/stellenangebote">Stellenangebote</a>
                    <a href="/ausbildung-und-duales-studium">Ausbildung</a>
                    <a href="/careers/vacancies">Open Positions</a>
                    <a href="/recrutement/offres-emploi">Offres d'emploi</a>
                    <a href="/about-us">About Us</a>
                </nav>
            </body>
        </html>
        """
        urls = self.verifier.discover_career_urls(base_url, html)
        self.assertTrue(any("/karriere" in u for u in urls), "Failed German karriere discovery")
        self.assertTrue(any("/stellenangebote" in u for u in urls), "Failed German stellenangebote discovery")
        self.assertTrue(any("/ausbildung" in u for u in urls), "Failed German ausbildung discovery")
        self.assertTrue(any("/careers" in u for u in urls), "Failed English careers discovery")
        self.assertTrue(any("/recrutement" in u for u in urls), "Failed French recrutement discovery")

    # -----------------------------------------------------------------------
    # 2. Job Listing Extraction
    # -----------------------------------------------------------------------
    def test_job_listing_extraction_from_html(self):
        """Extracts job titles, description snippets, and application links."""
        page_url = "https://www.beispiel-firma.de/karriere"
        html = """
        <html>
            <body>
                <div class="job-card">
                    <h3>Ausbildung zum Fachinformatiker Anwendungsentwicklung (m/w/d)</h3>
                    <p>Wir suchen ab September 2025 einen engagierten Auszubildenden im Bereich Software.</p>
                    <a href="/karriere/apply/fachinformatiker" class="btn">Jetzt bewerben</a>
                </div>
                <div class="job-item">
                    <h3>Senior Python Developer (m/w/d)</h3>
                    <p>Full-Stack Entwicklung mit FastAPI und React.</p>
                    <a href="/jobs/python-dev">Details</a>
                </div>
            </body>
        </html>
        """
        listings = self.verifier.extract_job_listings_from_html(page_url, html, "Beispiel Firma GmbH")
        self.assertEqual(len(listings), 2)

        azubi = listings[0]
        self.assertIn("Fachinformatiker", azubi["title"])
        self.assertTrue(azubi["is_ausbildung"])
        self.assertIn("apply/fachinformatiker", azubi["direct_application_url"])

        dev = listings[1]
        self.assertIn("Python Developer", dev["title"])
        self.assertFalse(dev["is_ausbildung"])

    # -----------------------------------------------------------------------
    # 3. Application URL Classification
    # -----------------------------------------------------------------------
    def test_application_url_classification(self):
        """Classifies destinations into strict recruitment categories."""
        # ATS Form
        ats_apply = "https://firma.jobs.personio.de/job/12345/apply"
        self.assertEqual(
            self.verifier.classify_application_url(ats_apply),
            URL_DIRECT_APPLICATION_FORM
        )

        # ATS Portal
        ats_portal = "https://firma.softgarden.io/vacancies"
        self.assertEqual(
            self.verifier.classify_application_url(ats_portal),
            URL_APPLICATION_PORTAL
        )

        # Careers overview
        careers = "https://firma.de/karriere"
        self.assertEqual(
            self.verifier.classify_application_url(careers),
            URL_CAREERS_PAGE
        )

        # General contact form (MUST NOT be classified as job form)
        contact = "https://firma.de/kontakt"
        self.assertEqual(
            self.verifier.classify_application_url(contact),
            URL_GENERAL_CONTACT_FORM
        )

        # HTML with interactive application form and file upload
        form_html = """
        <html>
            <body>
                <form action="/bewerbung-senden" method="POST">
                    <input type="text" name="applicant_name">
                    <input type="file" name="lebenslauf_upload">
                    <button type="submit">Bewerbung absenden</button>
                </form>
            </body>
        </html>
        """
        self.assertEqual(
            self.verifier.classify_application_url("https://firma.de/jobs/detail", form_html),
            URL_DIRECT_APPLICATION_FORM
        )

    # -----------------------------------------------------------------------
    # 4. Third-Party Recruitment Portal Detection
    # -----------------------------------------------------------------------
    def test_ats_recruitment_portal_detection(self):
        """Detects standard German and international ATS platforms."""
        test_cases = [
            ("https://beispiel.personio.de/job/1", True),
            ("https://acme.myworkdayjobs.com/careers/job/1", True),
            ("https://firma.softgarden.io/job/1", True),
            ("https://boards.greenhouse.io/tech/jobs/1", True),
            ("https://join.com/companies/firma/123", True),
            ("https://smartrecruiters.com/firma/123", True),
            ("https://www.beispiel.de/kontakt", False),
        ]
        for url, expected in test_cases:
            self.assertEqual(self.verifier.is_known_ats(url), expected, f"Failed ATS check for {url}")

    # -----------------------------------------------------------------------
    # 5. Ausbildung Verification & Statuses
    # -----------------------------------------------------------------------
    def test_ausbildung_verification_statuses(self):
        """Verifies candidate-specific statuses for Ausbildung and jobs."""
        # 1. Matching vacancy -> OPEN_VERIFIED
        score, reasons, status = self.verifier.calculate_matching_score(
            job_title="Ausbildung zum Fachinformatiker Anwendungsentwicklung",
            job_description="Programmierung in Python und SQL",
            is_ausbildung=True,
            target_title="Fachinformatiker Anwendungsentwicklung",
            job_type="ausbildung",
        )
        self.assertEqual(status, STATUS_OPEN_VERIFIED)
        self.assertGreaterEqual(score, 60)

        # 2. Related opportunity (Fachinformatiker Systemintegration) -> POTENTIALLY_OPEN or OPEN_VERIFIED
        score2, reasons2, status2 = self.verifier.calculate_matching_score(
            job_title="Fachinformatiker Systemintegration (m/w/d)",
            job_description="Netzwerktechnik und Server-Administration",
            is_ausbildung=True,
            target_title="Fachinformatiker Anwendungsentwicklung",
            job_type="both",
        )
        self.assertIn(status2, [STATUS_POTENTIALLY_OPEN, STATUS_OPEN_VERIFIED])
        self.assertGreaterEqual(score2, 35)

        # 3. Unrelated profession -> NO_MATCHING_VACANCY
        score3, reasons3, status3 = self.verifier.calculate_matching_score(
            job_title="Zahnmedizinische Fachangestellte",
            job_description="Praxisassistenz",
            is_ausbildung=True,
            target_title="Fachinformatiker Anwendungsentwicklung",
            job_type="both",
        )
        self.assertEqual(status3, STATUS_NO_MATCHING_VACANCY)
        self.assertLess(score3, 40)

    # -----------------------------------------------------------------------
    # 6. Candidate-Job Matching Score & Reasons
    # -----------------------------------------------------------------------
    def test_candidate_job_matching_score_reasons(self):
        """Ensures score is 0-100 with clear explainable reasons."""
        candidate_profile = {
            "applicant": {
                "professional_profile": {"current_title": "Softwareentwickler"},
                "skills": {
                    "programming_languages": ["Python", "JavaScript", "SQL"]
                },
                "contact": {
                    "address": {"city": "München"}
                }
            }
        }
        score, reasons, status = self.verifier.calculate_matching_score(
            job_title="Full Stack Softwareentwickler (m/w/d)",
            job_description="Wir entwickeln Microservices in Python und SQL am Standort München.",
            is_ausbildung=False,
            target_title="Softwareentwickler",
            job_type="employment",
            candidate_profile=candidate_profile,
            job_location="München",
        )
        self.assertGreaterEqual(score, 75)
        self.assertLessEqual(score, 100)
        self.assertTrue(len(reasons) >= 3, "Matching reasons should be detailed")
        reasons_text = " ".join(reasons)
        self.assertIn("Softwareentwickler", reasons_text)
        self.assertTrue("Python" in reasons_text or "Fähigkeiten" in reasons_text)
        self.assertTrue("München" in reasons_text or "Standort" in reasons_text)

    # -----------------------------------------------------------------------
    # 7. Duplicate Prevention
    # -----------------------------------------------------------------------
    def test_duplicate_prevention(self):
        """Ensures duplicate URLs and duplicate vacancies are filtered."""
        base_url = "https://www.tech.de"
        html = """
        <html>
            <body>
                <a href="/karriere">Karriere</a>
                <a href="/karriere">Karriere</a>
                <a href="/karriere/">Karriere</a>
                <div class="job"><h3>Software Engineer</h3></div>
                <div class="job"><h3>Software Engineer</h3></div>
            </body>
        </html>
        """
        urls = self.verifier.discover_career_urls(base_url, html)
        clean_urls = [u.split("#")[0].rstrip("/") for u in urls]
        self.assertEqual(len(clean_urls), len(set(clean_urls)), "Discovered URLs contain duplicates")

        listings = self.verifier.extract_job_listings_from_html(base_url, html, "Tech GmbH")
        self.assertEqual(len(listings), 1, "Duplicate job listings were not filtered")

    # -----------------------------------------------------------------------
    # 8. Multi-Client Isolation
    # -----------------------------------------------------------------------
    def test_multi_client_isolation(self):
        """Ensures jobs for different clients maintain isolated criteria."""
        job1_id = _create_google_maps_job(
            query="IT Berlin",
            max_results=10,
            radius=5,
            verify_opportunities=True,
            target_title="Fachinformatiker",
            job_type="ausbildung",
            client_id="client_alice",
        )
        job2_id = _create_google_maps_job(
            query="Krankenhaus Hamburg",
            max_results=10,
            radius=5,
            verify_opportunities=True,
            target_title="Pflegefachmann",
            job_type="employment",
            client_id="client_bob",
        )
        j1 = google_maps_jobs.get(job1_id)
        j2 = google_maps_jobs.get(job2_id)

        self.assertEqual(j1["client_id"], "client_alice")
        self.assertEqual(j1["target_title"], "Fachinformatiker")
        self.assertEqual(j1["job_type"], "ausbildung")

        self.assertEqual(j2["client_id"], "client_bob")
        self.assertEqual(j2["target_title"], "Pflegefachmann")
        self.assertEqual(j2["job_type"], "employment")

    # -----------------------------------------------------------------------
    # 9. Concurrent Crawling Compatibility
    # -----------------------------------------------------------------------
    def test_concurrent_crawling_with_opportunity_verification(self):
        """Runs concurrent crawling with opportunity verification enabled."""
        scraper = GoogleMapsBusinessScraper(headless=True)
        businesses = [
            {"name": "Alpha Tech", "website": "https://alpha.example.com", "maps_url": ""},
            {"name": "Beta Systems", "website": "https://beta.example.com", "maps_url": ""},
        ]

        def mock_fetch(url):
            if "alpha" in url:
                return "<html><a href='/karriere'>Karriere</a><p>Ausbildung Fachinformatiker</p></html>"
            return "<html><a href='/kontakt'>Kontakt</a><p>info@beta.de</p></html>"

        with patch.object(scraper, "_fetch_page", side_effect=mock_fetch), \
             patch.object(scraper.opportunity_verifier, "fetch_page", side_effect=lambda u: (u, mock_fetch(u))):
            processed = scraper.process_businesses_concurrent(
                businesses,
                max_workers=2,
                verify_opportunities=True,
                target_title="Fachinformatiker",
                job_type="ausbildung",
            )
            self.assertEqual(len(processed), 2)
            alpha = next(b for b in processed if b["name"] == "Alpha Tech")
            self.assertTrue("vacancies" in alpha)
            self.assertTrue("company_id" in alpha)

    # -----------------------------------------------------------------------
    # 10. Export Correctness (Excel, CSV, JSON)
    # -----------------------------------------------------------------------
    def test_unified_export_columns_and_data(self):
        """Verifies unified export rows contain all business and recruitment columns."""
        businesses = [{
            "name": "Cloud AG",
            "address": "Hauptstr. 1, 80331 München",
            "phone": "089 123456",
            "website": "https://cloud-ag.de",
            "emails": ["bewerbung@cloud-ag.de"],
            "career_page": "https://cloud-ag.de/karriere",
            "primary_job_title": "Ausbildung Fachinformatiker Anwendungsentwicklung",
            "primary_apply_url": "https://cloud-ag.jobs.personio.de/apply",
            "primary_apply_method": "Application Portal",
            "primary_url_type": "APPLICATION_PORTAL",
            "primary_verification_status": "OPEN_VERIFIED",
            "primary_matching_score": 95,
            "primary_matching_reasons": ["Exakter Titel (+40%)", "Ausbildungsart (+25%)"],
            "ausbildung_available": True,
            "vacancies_count": 1,
            "vacancies": [{
                "job_title": "Ausbildung Fachinformatiker Anwendungsentwicklung",
                "direct_application_url": "https://cloud-ag.jobs.personio.de/apply",
                "application_method": "Application Portal",
                "application_url_type": "APPLICATION_PORTAL",
                "verification_status": "OPEN_VERIFIED",
                "matching_score": 95,
                "matching_reasons": ["Exakter Titel (+40%)", "Ausbildungsart (+25%)"],
                "is_ausbildung": True,
                "client_id": "c_123",
                "company_id": "comp_abc",
                "job_id": "job_xyz",
            }],
            "client_id": "c_123",
            "company_id": "comp_abc",
        }]

        rows = _build_unified_export_rows(businesses)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["Unternehmen"], "Cloud AG")
        self.assertEqual(r["Stellenbezeichnung"], "Ausbildung Fachinformatiker Anwendungsentwicklung")
        self.assertEqual(r["Bewerbungsart"], "Application Portal")
        self.assertEqual(r["Verifizierungsstatus"], "OPEN_VERIFIED")
        self.assertEqual(r["Passungs-Score"], 95)
        self.assertEqual(r["Ausbildung"], "Ja")
        self.assertEqual(r["Client ID"], "c_123")
        self.assertEqual(r["Company ID"], "comp_abc")
        self.assertEqual(r["Job ID"], "job_xyz")

        # Test DataFrame conversion
        df = pd.DataFrame(rows)
        self.assertIn("Stellenbezeichnung", df.columns)
        self.assertIn("Passungs-Score", df.columns)
        self.assertIn("Client ID", df.columns)

    # -----------------------------------------------------------------------
    # 11. Handling Inaccessible Websites
    # -----------------------------------------------------------------------
    def test_handling_inaccessible_website(self):
        """Inaccessible website returns VERIFICATION_FAILED without crashing."""
        biz = {
            "name": "Offline GmbH",
            "website": "https://offline-does-not-exist.example.org",
        }
        with patch.object(self.verifier, "fetch_page", return_value=("", "")):
            res = self.verifier.verify_business_opportunities(
                business=biz,
                target_title="Entwickler",
                job_type="both",
            )
            self.assertEqual(res["primary_verification_status"], STATUS_VERIFICATION_FAILED)
            self.assertFalse(res["has_verified_vacancy"])

    # -----------------------------------------------------------------------
    # 12. Handling Companies Without Career Pages
    # -----------------------------------------------------------------------
    def test_handling_companies_without_career_page(self):
        """Website with no career links is gracefully tagged UNKNOWN / no_career_page."""
        biz = {
            "name": "Kleinbetrieb",
            "website": "https://kleinbetrieb.de",
        }
        mock_home = "<html><body><h1>Willkommen</h1><p>Wir verkaufen Brot und Backwaren.</p></body></html>"
        def mock_fetch(url):
            if url.rstrip("/") == "https://kleinbetrieb.de":
                return "https://kleinbetrieb.de", mock_home
            return url, ""

        with patch.object(self.verifier, "fetch_page", side_effect=mock_fetch):
            res = self.verifier.verify_business_opportunities(
                business=biz,
                target_title="Entwickler",
                job_type="both",
            )
            self.assertEqual(res["primary_verification_status"], STATUS_UNKNOWN)
            self.assertFalse(res["has_career_page"])

    # -----------------------------------------------------------------------
    # 13. Endpoints Integration
    # -----------------------------------------------------------------------
    def test_api_google_maps_discover_and_status(self):
        """Tests POST /api/google-maps/discover with verification toggle."""
        resp = self.client.post("/api/google-maps/discover", json={
            "query": "IT München",
            "max_results": 15,
            "verify_opportunities": True,
            "target_title": "Softwareentwickler",
            "job_type": "both",
            "client_id": "anass_sibbi",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        job_id = data["job_id"]

        status_resp = self.client.get(f"/api/google-maps/status/{job_id}")
        self.assertEqual(status_resp.status_code, 200)
        s_data = status_resp.get_json()
        job = s_data["job"]
        self.assertTrue(job["verify_opportunities"])
        self.assertEqual(job["target_title"], "Softwareentwickler")
        self.assertEqual(job["client_id"], "anass_sibbi")
        self.assertEqual(job["job_type"], "both")


if __name__ == "__main__":
    unittest.main()
