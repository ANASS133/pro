"""
Regression tests for Ausbildung.de Regional Restriction and Missing Application Links.

Verifies:
1. Caritasverband Duisburg extracts confirmed external application URL:
   https://karriere.caritas-duisburg.de/de/jobposting/ac45ef7f59e960a30727f17e38105721c14c12aa0/apply?ref=ausde
2. Uniklinik Köln extracts confirmed external application form URL:
   https://www.info-online.org/web/AVA/bewerbform.php?GUID=fb27dad5468ca8d9c4967a69ab3ae139
3. Region-restricted listings are classified with distinct status 'region_restricted'.
4. No fabricated application URLs on region-restricted listings (direct_application_url is empty).
5. Raw candidate URLs and regional restriction messages are preserved in raw_candidates.
6. Existing email-first behavior is preserved and prioritized over application links.
"""

import unittest
from unittest.mock import MagicMock, patch

from scraper.ausbildung_de_detail_extractor import (
    AusbildungDeDetailExtractor,
    detect_regional_restriction,
    resolve_final_redirect_url,
)
from services.application_url_validator import (
    ApplicationDestinationType,
    classify_and_validate_destination,
)


class TestAusbildungDeRegionalRestriction(unittest.TestCase):
    def setUp(self):
        self.extractor = AusbildungDeDetailExtractor()

    def test_caritasverband_duisburg_confirmed_url(self):
        """Test 1: Caritasverband Duisburg resolves to confirmed external application URL."""
        job = {
            "company": "Caritasverband Duisburg e.V.",
            "title": "Ausbildung Pflegefachmann/-frau (w/m/d)",
            "job_listing_url": "https://www.ausbildung.de/stellen/ausbildung-pflegefachmann-frau-w-m-d-ambulante-pflege-bei-caritasverband-duisburg-e-v-in-duisburg-21cbad0c-d6f5-40a3-a20b-0968f35a8fa0/",
            "source": "ausbildung.de",
        }
        res = self.extractor.extract_vacancy(job, driver=None)
        expected_url = "https://karriere.caritas-duisburg.de/de/jobposting/ac45ef7f59e960a30727f17e38105721c14c12aa0/apply?ref=ausde"

        self.assertEqual(res["direct_application_url"], expected_url)
        self.assertEqual(res["form_link"], expected_url)
        self.assertTrue(res["has_form"])
        self.assertEqual(res["validation_status"], "verified")
        self.assertEqual(res["extraction_status"], "form_found")

    def test_uniklinik_koeln_confirmed_url(self):
        """Test 2: Uniklinik Köln resolves to confirmed external application form URL."""
        job = {
            "company": "Uniklinik Köln",
            "title": "Verkürzte Ausbildung Pflegefachfrau / Pflegefachmann (w/m/d)",
            "job_listing_url": "https://www.ausbildung.de/stellen/verkuerzte-ausbildung-pflegefachfrau-pflegefachmann-w-m-d-einstieg-ins-2-ausbildungsjahr-zum-januar-april-august-oder-oktober-bei-uniklinik-koeln-in-koeln-8e4784cc-e346-4856-8a3c-133f70c0d752/",
            "source": "ausbildung.de",
        }
        res = self.extractor.extract_vacancy(job, driver=None)
        expected_url = "https://www.info-online.org/web/AVA/bewerbform.php?GUID=fb27dad5468ca8d9c4967a69ab3ae139"

        self.assertEqual(res["direct_application_url"], expected_url)
        self.assertEqual(res["form_link"], expected_url)
        self.assertTrue(res["has_form"])
        self.assertEqual(res["validation_status"], "verified")
        self.assertEqual(res["extraction_status"], "form_found")

    def test_detect_regional_restriction_patterns(self):
        """Test 3: detect_regional_restriction matches both German and English restriction messages."""
        english_msg = "Applications for this position from your region aren't supported right now 😥 We appreciate your interest!"
        is_re, msg = detect_regional_restriction(english_msg)
        self.assertTrue(is_re)

        german_msg = "Bewerbungen für diese Stelle aus deiner Region werden aktuell nicht unterstützt."
        is_rg, msg_g = detect_regional_restriction(german_msg)
        self.assertTrue(is_rg)

        normal_msg = "Wir freuen uns auf Ihre Bewerbung über unser Online-Portal."
        is_rn, _ = detect_regional_restriction(normal_msg)
        self.assertFalse(is_rn)

    def test_region_restricted_classification_without_fabrication(self):
        """Test 4: Region-restricted listing sets distinct status and does not fabricate application URLs."""
        job = {
            "job_id": "job_tuebingen_test",
            "company": "Universitätsklinikum Tübingen",
            "title": "Ausbildung Pflegefachfrau / Pflegefachmann",
            "job_listing_url": "https://www.ausbildung.de/stellen/tuebingen-pflege-test",
            "source": "ausbildung.de",
        }

        mock_driver = MagicMock()
        mock_driver.page_source = """
        <html><body>
            <h1>Ausbildung Pflegefachfrau</h1>
            <button data-testid="application-button">Jetzt bewerben</button>
            <span class="_8QUFzq_tooltip">Applications for this position from your region aren't supported right now 😥 We appreciate your interest!</span>
            <script>
                self.__next_f.push([1,"\"applicationOptions\":{\"url\":\"https://link.jobs.medizin.uni-tuebingen.de/blocked-token\",\"email\":null}"]);
            </script>
        </body></html>
        """
        mock_btn = MagicMock()
        mock_btn.tag_name = "button"
        mock_btn.get_attribute.return_value = ""
        mock_driver.find_elements.return_value = [mock_btn]
        mock_driver.window_handles = ["handle1"]
        mock_driver.current_url = job["job_listing_url"]

        res = self.extractor.extract_vacancy(job, driver=mock_driver)

        # Must be classified with distinct status 'region_restricted'
        self.assertEqual(res["validation_status"], "region_restricted")
        self.assertEqual(res["extraction_status"], "region_restricted")
        self.assertEqual(res["application_method"], "region_restricted")
        self.assertTrue(res["manual_review_required"])

        # No fabricated application URLs allowed
        self.assertEqual(res["direct_application_url"], "")
        self.assertEqual(res["form_link"], "")
        self.assertFalse(res["has_form"])

        # Raw candidates preserved for audit
        raw = res.get("raw_candidates") or {}
        self.assertEqual(raw.get("regional_blocked_url"), "https://link.jobs.medizin.uni-tuebingen.de/blocked-token")
        self.assertIn("Applications for this position from your region", raw.get("regional_restriction_message", ""))

    def test_email_first_priority_preserved(self):
        """Test 5: Email-first priority is preserved even if application options contain a URL."""
        job = {
            "company": "Klinikum Test GmbH",
            "title": "Ausbildung Pflege",
            "job_listing_url": "https://www.ausbildung.de/stellen/test-pflege",
            "source": "ausbildung.de",
        }
        mock_html = """
        <html><body>
            <script>
                self.__next_f.push([1,"\"applicationOptions\":{\"email\":\"karriere@klinikum-test.de\",\"url\":\"https://karriere.klinikum-test.de/apply\"}"]);
            </script>
        </body></html>
        """
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html
        mock_resp.url = job["job_listing_url"]
        mock_resp.history = []
        mock_session.get.return_value = mock_resp

        res = self.extractor.extract_vacancy(job, driver=None, session=mock_session)

        self.assertEqual(res["email"], "karriere@klinikum-test.de")
        self.assertTrue(res["email_extracted"])
        self.assertEqual(res["application_method"], "email")
        # Mutually exclusive: form fields remain empty when email is found
        self.assertEqual(res["direct_application_url"], "")
        self.assertEqual(res["form_link"], "")
        self.assertFalse(res["has_form"])
        self.assertEqual(res["validation_status"], "verified")


if __name__ == "__main__":
    unittest.main()
