import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from email_sender.sender import EmailSender
from email_sender.throttler import DomainThrottler
from email_sender.validator import EmailValidator
from pdf_generator.services.template_service import TemplateService
from scraper.email_pattern_guesser import EmailPatternGuesser
from scraper.fast_web_crawler import FastWebCrawler
from scraper.hook_generator import DynamicHookGenerator
from scraper.impressum_extractor import ImpressumExtractor
from scraper.overpass_scraper import OverpassBusinessScraper


class TestIdea1ContactQualityAndImpressum(unittest.TestCase):
    """Tests for Idea 1: Impressum Extractor and Email Pattern Guesser."""

    def test_impressum_extraction_german_html(self):
        sample_impressum_html = """
        <html>
        <head><title>Impressum - Schmidt IT GmbH</title></head>
        <body>
            <h1>Impressum</h1>
            <p>Angaben gemäß § 5 TMG:</p>
            <p>Schmidt IT GmbH<br>Musterstraße 12<br>50667 Köln</p>
            <p><strong>Geschäftsführer:</strong> Dr. Thomas Müller, Melanie Weber</p>
            <p>Registergericht: Amtsgericht Köln, HRB 12345</p>
            <p>Kontakt:<br>Telefon: +49 (0) 221 9876543<br>E-Mail: kontakt@schmidt-it.de</p>
        </body>
        </html>
        """
        extractor = ImpressumExtractor()
        data = extractor.extract_from_html(sample_impressum_html, source_url="https://schmidt-it.de/impressum")

        self.assertIn("Dr. Thomas Müller", data["geschaeftsfuehrer_liste"])
        self.assertEqual(data["geschaeftsfuehrer"], "Dr. Thomas Müller")
        self.assertEqual(data["primary_email"], "kontakt@schmidt-it.de")
        self.assertIn("+49 (0) 221 9876543", data["phone"])
        self.assertIn("Dr. Müller", data["salutation"])

    def test_impressum_salutation_generation(self):
        self.assertEqual(
            ImpressumExtractor.generate_salutation("Dr. med. Johannes Weber"),
            "Sehr geehrte/r Dr. Weber,",
        )
        self.assertEqual(
            ImpressumExtractor.generate_salutation("Herr Markus Schmidt"),
            "Sehr geehrter Herr Schmidt,",
        )
        self.assertEqual(
            ImpressumExtractor.generate_salutation("Frau Dr. Julia Wagner"),
            "Sehr geehrte Frau Dr. Wagner,",
        )
        self.assertEqual(
            ImpressumExtractor.generate_salutation(""),
            "Sehr geehrte Damen und Herren,",
        )

    def test_email_pattern_guesser_with_umlauts(self):
        candidates = EmailPatternGuesser.generate_candidates(
            full_name="Frau Dr. Julia Müller-Lüdenscheidt",
            domain_or_website="https://www.mueller-tech.de",
        )
        emails = [c["email"] for c in candidates]
        self.assertIn("julia.mueller-luedenscheidt@mueller-tech.de", emails)
        self.assertIn("j.mueller-luedenscheidt@mueller-tech.de", emails)

    def test_email_pattern_guesser_lastname_only(self):
        candidates = EmailPatternGuesser.generate_candidates(
            full_name="Herr Schneider",
            domain_or_website="schneider-bau.de",
        )
        emails = [c["email"] for c in candidates]
        self.assertIn("schneider@schneider-bau.de", emails)


class TestIdea2FastCrawlerAndOverpass(unittest.TestCase):
    """Tests for Idea 2: Fast Web Crawler and OpenStreetMap Overpass Scraper."""

    def test_fast_web_crawler_html_parsing(self):
        crawler = FastWebCrawler()
        html = """
        <div>
            <a href="mailto:karriere@web-agentur.de?subject=Bewerbung">Jobs</a>
            <p>Direktkontakt: info@web-agentur.de</p>
            <p>Ignorieren: noreply@web-agentur.de und tracker@sentry.io</p>
        </div>
        """
        emails = crawler._extract_emails_from_html(html)
        self.assertIn("karriere@web-agentur.de", emails)
        self.assertIn("info@web-agentur.de", emails)
        self.assertNotIn("noreply@web-agentur.de", emails)
        self.assertNotIn("tracker@sentry.io", emails)

    def test_overpass_query_builder(self):
        scraper = OverpassBusinessScraper()
        query = scraper.build_query(city="Köln", category="handwerk", limit=50)
        self.assertIn('area["name"="Köln"]', query)
        self.assertIn("node['craft']", query)
        self.assertIn("out body 50;", query)

    def test_overpass_elements_parser(self):
        elements = [
            {
                "type": "node",
                "id": 101,
                "lat": 50.9375,
                "lon": 6.9603,
                "tags": {
                    "name": "Malerbetrieb Bunt GmbH",
                    "craft": "painter",
                    "addr:street": "Farbenweg",
                    "addr:housenumber": "7",
                    "addr:postcode": "50678",
                    "addr:city": "Köln",
                    "contact:phone": "+49 221 112233",
                    "contact:email": "info@maler-bunt.de",
                    "website": "https://www.maler-bunt.de",
                },
            }
        ]
        scraper = OverpassBusinessScraper()
        parsed = scraper.parse_elements(elements, default_city="Köln")
        self.assertEqual(len(parsed), 1)
        item = parsed[0]
        self.assertEqual(item["name"], "Malerbetrieb Bunt GmbH")
        self.assertEqual(item["address"], "Farbenweg 7")
        self.assertEqual(item["email"], "info@maler-bunt.de")
        self.assertEqual(item["website"], "https://www.maler-bunt.de")


class TestIdea3DynamicHooksAndCoverLetters(unittest.TestCase):
    """Tests for Idea 3: Dynamic Opening Hooks and TemplateService Placeholders."""

    def test_hook_generation(self):
        hook = DynamicHookGenerator.generate_hook(
            job_title="Python Backend Developer",
            company="Digital Solutions GmbH",
            city="Berlin",
        )
        self.assertIn("Python Backend Developer", hook)
        self.assertIn("Digital Solutions GmbH", hook)
        self.assertIn("Berlin", hook)

    def test_template_service_dynamic_placeholder_replacement(self):
        service = TemplateService()
        template = "Hallo,\n\n{{salutation}}\n\n{{custom_hook}}\n\nMit freundlichen Grüßen"
        row = {
            "title": "IT-Systemadministrator",
            "company": "TechCorp GmbH",
            "city": "München",
            "ansprechpartner": "Herr Thomas Bauer",
        }
        rendered = service.replace_placeholders(template, row, ["title", "company", "city", "ansprechpartner"])
        self.assertIn("Sehr geehrter Herr Bauer,", rendered)
        self.assertIn("TechCorp GmbH", rendered)
        self.assertIn("IT-Systemadministrator", rendered)
        self.assertIn("München", rendered)


class TestIdea4DeliverabilityAndThrottling(unittest.TestCase):
    """Tests for Idea 4: Email Validation and Domain Throttling."""

    def test_email_syntax_and_unmonitored_check(self):
        self.assertTrue(EmailValidator.check_syntax("bewerbung@musterfirma.de")[0])
        self.assertFalse(EmailValidator.check_syntax("ungueltig@")[0])

        is_bad, _ = EmailValidator.is_unmonitored_or_disposable("noreply@musterfirma.de")
        self.assertTrue(is_bad)

        is_disposable, _ = EmailValidator.is_unmonitored_or_disposable("test@mailinator.com")
        self.assertTrue(is_disposable)

        is_valid, _ = EmailValidator.is_unmonitored_or_disposable("personal@musterfirma.de")
        self.assertFalse(is_valid)

    def test_domain_throttler_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "test_history.json"
            throttler = DomainThrottler(history_file=history_file, default_cooldown_days=7)

            email = "hr@startup-berlin.de"
            allowed, _ = throttler.can_send(email)
            self.assertTrue(allowed)

            # Record send
            throttler.record_send(email, subject="Bewerbung")

            # Immediate next send should be throttled
            allowed_next, reason = throttler.can_send(email)
            self.assertFalse(allowed_next)
            self.assertIn("cooldown", reason.lower())

            # Different domain should be allowed
            allowed_other, _ = throttler.can_send("jobs@another-company.de")
            self.assertTrue(allowed_other)


if __name__ == "__main__":
    unittest.main()
