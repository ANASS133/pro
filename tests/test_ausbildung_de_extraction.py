import concurrent.futures
import unittest
from unittest.mock import MagicMock, patch

from scraper.ausbildung_de_detail_extractor import AusbildungDeDetailExtractor
from scraper.working_email_extractor import WorkingEmailExtractor
from services.employer_cache import EmployerDomainCache, is_portal_domain


class TestAusbildungDeExtraction(unittest.TestCase):
    """
    Step 8 Regression Tests for Ausbildung.de Extraction Pipeline:
    - Test A: CODAN Medizinische Geräte GmbH -> personal@codan.de (NOT claudia.guenther@nordwasser.de)
    - Test B: Nordwasser GmbH -> legitimate email claudia.guenther@nordwasser.de not blocked
    - Test C: Another unrelated employer -> does not inherit Nordwasser contact
    - Test D: No email available -> captures application form destination (Jetzt bewerben)
    - Test E: Multiple concurrent workers -> zero cross-job data contamination
    - Test F: Missing application information -> marked for review, no stale data
    """

    def setUp(self):
        self.extractor = AusbildungDeDetailExtractor()

    def test_employer_cache_does_not_poison_portal_domains(self):
        """EmployerDomainCache must reject portal domains like ausbildung.de from domain cache."""
        cache = EmployerDomainCache()
        self.assertTrue(is_portal_domain("ausbildung.de"))
        self.assertTrue(is_portal_domain("www.ausbildung.de"))
        self.assertTrue(is_portal_domain("sub.arbeitsagentur.de"))

        # Put Nordwasser with ausbildung.de listing URL
        cache.put(
            company="Nordwasser GmbH",
            city="Rostock",
            url_or_domain="https://www.ausbildung.de/stellen/ausbildung-nordwasser-12345",
            data={
                "email": "claudia.guenther@nordwasser.de",
                "phone": "+49 381 12345",
            },
        )

        # 1. Lookup with another employer on ausbildung.de must NOT return Nordwasser's email!
        res_codan = cache.get(
            company="CODAN Medizinische Geräte GmbH",
            city="Lensahn",
            url_or_domain="https://www.ausbildung.de/stellen/ausbildung-codan-67890",
        )
        self.assertIsNone(res_codan, "CODAN must not receive Nordwasser's cached email via ausbildung.de domain!")

        # 2. Lookup for the SAME company should work via company key
        res_nw = cache.get(
            company="Nordwasser GmbH",
            city="Rostock",
            url_or_domain="https://www.ausbildung.de/stellen/ausbildung-nordwasser-12345",
        )
        self.assertIsNotNone(res_nw)
        self.assertEqual(res_nw["email"], "claudia.guenther@nordwasser.de")

    def test_a_codan_medizinische_geraete_extracts_correct_email(self):
        """Test A: CODAN must extract personal@codan.de and NOT claudia.guenther@nordwasser.de."""
        job = {
            "title": "Ausbildung zum Fachinformatiker für Anwendungsentwicklung / Softwaretechnik (m/w/d) 2027",
            "company": "CODAN Medizinische Geräte GmbH",
            "city": "Lensahn",
            "url": "https://www.ausbildung.de/stellen/ausbildung-zum-fachinformatiker-fuer-anwendungsentwicklung-softwaretechnik-m-w-d-bei-codan-medizinische-geraete-gmbh-in-lensahn-066f76fe-273d-409a-84cd-26393ebf1fe0/",
            "source": "ausbildung.de",
        }

        # Deterministic test with HTML containing applicationOptions and Weitere Bewerbungsoptionen
        mock_html = """
        <html>
        <body>
            <h1>Ausbildung zum Fachinformatiker</h1>
            <div class="v8QoTq_applicationOptionsWrapper">
                <button data-testid="application-options-button">Weitere Bewerbungsoptionen</button>
            </div>
            <script>
                self.__next_f.push([1,"7:[\"$\",\"div\",null,{\"children\":{\"applicationOptions\":{\"url\":null,\"email\":\"personal@codan.de\",\"postalAddress\":null,\"referenceNumber\":null}}}]"]);
            </script>
        </body>
        </html>
        """
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_session.get.return_value = mock_resp

        result = self.extractor.extract_vacancy(job, driver=None, session=mock_session)

        self.assertEqual(result["email"], "personal@codan.de")
        self.assertNotEqual(result["email"], "claudia.guenther@nordwasser.de")
        self.assertTrue(result["email_extracted"])
        self.assertFalse(result["has_form"])
        self.assertEqual(result["form_link"], "")
        self.assertEqual(result["direct_application_url"], "")

    def test_b_nordwasser_listing_extracts_legitimate_contact(self):
        """Test B: Nordwasser listing must extract claudia.guenther@nordwasser.de and not block legitimate contact."""
        job = {
            "title": "Ausbildung zum Leitungsbauer (m/w/d)",
            "company": "Nordwasser GmbH",
            "city": "Rostock",
            "url": "https://www.ausbildung.de/stellen/ausbildung-zum-leitungsbauer-m-w-d-oder-kanalbauer-m-w-d-fuer-infrastrukturtechnik-bei-nordwasser-gmbh-in-rostock-181588db-9eea-401a-929f-4f0bf89607bd/",
            "source": "ausbildung.de",
        }

        mock_html = """
        <html>
        <body>
            <h1>Ausbildung zum Leitungsbauer</h1>
            <div class="contact-section">
                <span>Ansprechpartner</span>
                <a href="mailto:claudia.guenther@nordwasser.de">claudia.guenther@nordwasser.de</a>
            </div>
            <script>
                self.__next_f.push([1,"\"applicationOptions\":{\"url\":\"https://www.nordwasser.de/ausbildung\",\"email\":null}"]);
            </script>
        </body>
        </html>
        """
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_session.get.return_value = mock_resp

        result = self.extractor.extract_vacancy(job, driver=None, session=mock_session)

        self.assertEqual(result["email"], "claudia.guenther@nordwasser.de")
        self.assertTrue(result["email_extracted"])
        self.assertFalse(result["has_form"])
        self.assertEqual(result["form_link"], "")

    def test_c_unrelated_employer_does_not_inherit_nordwasser_contact(self):
        """Test C: An unrelated employer must not inherit Nordwasser's email."""
        job = {
            "title": "Ausbildung Elektroniker (m/w/d)",
            "company": "Siemens AG",
            "city": "München",
            "url": "https://www.ausbildung.de/stellen/ausbildung-elektroniker-siemens-9999",
            "source": "ausbildung.de",
        }

        mock_html = """
        <html>
        <body>
            <h1>Ausbildung Elektroniker</h1>
            <div class="contact-card">
                <a href="mailto:ausbildung@siemens.com">ausbildung@siemens.com</a>
            </div>
        </body>
        </html>
        """
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_session.get.return_value = mock_resp

        result = self.extractor.extract_vacancy(job, driver=None, session=mock_session)

        self.assertEqual(result["email"], "ausbildung@siemens.com")
        self.assertNotEqual(result["email"], "claudia.guenther@nordwasser.de")

    def test_d_no_email_available_captures_jetzt_bewerben_form_url(self):
        """Test D: If no email is available, captures application form URL from Jetzt bewerben."""
        job = {
            "title": "Ausbildung Fachinformatiker/in für Systemintegration (m/w/d)",
            "company": "GOLDBECK GmbH",
            "city": "Bielefeld",
            "url": "https://www.ausbildung.de/stellen/ausbildung-goldbeck-123",
            "source": "ausbildung.de",
        }

        ats_url = "https://goldbeck.wd103.myworkdayjobs.com/de-DE/goldbeck-jobs/job/Bielefeld/Auszubildende"
        mock_html = f"""
        <html>
        <body>
            <h1>Ausbildung Fachinformatiker</h1>
            <a href="{ats_url}" class="v8QoTq_applicationButton">Jetzt bewerben</a>
            <script>
                self.__next_f.push([1,"\"applicationOptions\":{{\"url\":\"{ats_url}\",\"email\":null}}"]);
            </script>
        </body>
        </html>
        """
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_session.get.return_value = mock_resp

        result = self.extractor.extract_vacancy(job, driver=None, session=mock_session)

        # Step 5 Excel Output Rules: Email is empty, Application form/link column has the URL
        self.assertEqual(result["email"], "")
        self.assertFalse(result["email_extracted"])
        self.assertTrue(result["has_form"])
        self.assertEqual(result["form_link"], ats_url)
        self.assertEqual(result["direct_application_url"], ats_url)

    def test_e_multiple_concurrent_workers_isolation(self):
        """Test E: Process multiple Ausbildung.de jobs concurrently without cross-job contamination."""
        jobs = [
            {
                "job_id": f"job_{i}",
                "title": f"Ausbildung Fachinformatiker {i}",
                "company": f"Company {i}",
                "city": f"City {i}",
                "url": f"https://www.ausbildung.de/stellen/job-{i}",
                "source": "ausbildung.de",
                "_expected_email": f"recruiting@company{i}.de",
            }
            for i in range(1, 9)
        ]

        def process_mock_job(job_item):
            exp_email = job_item["_expected_email"]
            mock_html = f"""
            <html><body>
                <script>
                    self.__next_f.push([1,"\"applicationOptions\":{{\"url\":null,\"email\":\"{exp_email}\"}}"]);
                </script>
            </body></html>
            """
            s = MagicMock()
            r = MagicMock()
            r.status_code = 200
            r.text = mock_html
            s.get.return_value = r
            ext = AusbildungDeDetailExtractor(session=s)
            return ext.extract_vacancy(job_item, driver=None, session=s, worker_id=(hash(job_item["job_id"]) % 4) + 1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(process_mock_job, jobs))

        for idx, res in enumerate(results, start=1):
            expected = f"recruiting@company{idx}.de"
            self.assertEqual(res["email"], expected)
            self.assertNotEqual(res["email"], "claudia.guenther@nordwasser.de")
            self.assertFalse(res["has_form"])
            self.assertEqual(res["form_link"], "")

    def test_f_missing_application_information_records_review_required(self):
        """Test F: When neither email nor form can be discovered, marked for review with empty contacts."""
        job = {
            "title": "Ausbildung Maler",
            "company": "Unbekannter Betrieb",
            "city": "Dorf",
            "url": "https://www.ausbildung.de/stellen/job-no-contact",
            "source": "ausbildung.de",
        }

        mock_html = """
        <html><body>
            <h1>Ausbildung Maler</h1>
            <p>Keine Kontaktdaten angegeben.</p>
        </body></html>
        """
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_session.get.return_value = mock_resp

        result = self.extractor.extract_vacancy(job, driver=None, session=mock_session)

        self.assertEqual(result["email"], "")
        self.assertFalse(result["email_extracted"])
        self.assertFalse(result["has_form"])
        self.assertEqual(result["form_link"], "")
        self.assertTrue(result.get("manual_review_required"))
        self.assertEqual(result["extraction_status"], "review_required")

    def test_selenium_interactive_weitere_bewerbungsoptionen_expansion(self):
        """Test Selenium interactive flow expanding Weitere Bewerbungsoptionen and extracting email."""
        job = {
            "title": "Fachinformatiker Anwendungsentwicklung",
            "company": "Interactive Test GmbH",
            "city": "Hamburg",
            "url": "https://www.ausbildung.de/stellen/interactive-test",
            "source": "ausbildung.de",
        }

        mock_driver = MagicMock()
        mock_driver.window_handles = ["win1"]
        mock_driver.page_source = "<html><body></body></html>"

        opt_btn = MagicMock()
        opt_btn.text = "Weitere Bewerbungsoptionen"
        mock_driver.find_elements.side_effect = lambda by, sel: (
            [opt_btn] if "Weitere Bewerbungsoptionen" in sel else []
        )

        email_label = MagicMock()
        email_label.text = "Per E-Mail bewerben"
        parent_container = MagicMock()
        mailto_link = MagicMock()
        mailto_link.get_attribute.return_value = "mailto:bewerbung@interactive-test.de"
        parent_container.find_elements.return_value = [mailto_link]
        email_label.find_element.return_value = parent_container

        def custom_find_elements(by, sel):
            if "Weitere Bewerbungsoptionen" in sel:
                return [opt_btn]
            if "Per E-Mail bewerben" in sel:
                return [email_label]
            return []

        mock_driver.find_elements = custom_find_elements

        # Disable fast HTTP so Selenium runs
        with patch.object(self.extractor, "_extract_via_fast_http", return_value=None):
            result = self.extractor.extract_vacancy(job, driver=mock_driver)

        self.assertEqual(result["email"], "bewerbung@interactive-test.de")
        self.assertTrue(result["email_extracted"])
        self.assertFalse(result["has_form"])
        self.assertEqual(result["form_link"], "")
        self.assertEqual(result["direct_application_url"], "")


if __name__ == "__main__":
    unittest.main()
