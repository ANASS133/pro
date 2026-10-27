import unittest
from unittest.mock import MagicMock, patch

from scraper.google_maps_scraper import (
    GoogleMapsBusinessScraper,
    _decode_cloudflare_email,
    _deobfuscate_email_text,
    _extract_emails_from_html,
)


class TestGoogleMapsConcurrencyAndDeobfuscation(unittest.TestCase):
    def test_deobfuscate_email_text(self):
        self.assertEqual(_deobfuscate_email_text("contact [at] firma.de"), "contact@firma.de")
        self.assertEqual(_deobfuscate_email_text("info(at)firma.com"), "info@firma.com")
        self.assertEqual(_deobfuscate_email_text("bewerbung [AT] domain [DOT] de"), "bewerbung@domain.de")
        self.assertEqual(_deobfuscate_email_text("karriere&#64;firma.de"), "karriere@firma.de")

    def test_decode_cloudflare_email(self):
        # Sample Cloudflare protected hex for "test@example.org" (not excluded domain)
        # key = 0x12 -> 't'^0x12 = 0x66
        key = 0x2a
        raw = "recruiting@firma.de"
        cf_hex = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in raw)
        decoded = _decode_cloudflare_email(cf_hex)
        self.assertEqual(decoded, "recruiting@firma.de")

    def test_extract_emails_from_html_with_deobfuscation(self):
        html = """
        <html>
            <body>
                <p>Impressum: kontakt [at] company-hamburg.de</p>
                <p>Bewerbung: karriere&#64;company-hamburg.de</p>
                <a href="/cdn-cgi/l/email-protection#6e070008012e"></a>
            </body>
        </html>
        """
        emails = _extract_emails_from_html(html)
        self.assertIn("kontakt@company-hamburg.de", emails)
        self.assertIn("karriere@company-hamburg.de", emails)

    def test_process_businesses_concurrent(self):
        scraper = GoogleMapsBusinessScraper(headless=True)
        # Mock enrich_business_details to avoid launching real Selenium browser
        scraper.enrich_business_details = MagicMock(side_effect=lambda biz: biz)

        businesses = [
            {"name": "Company A", "website": "https://company-a.de", "status": "pending"},
            {"name": "Company B", "website": "https://company-b.de", "status": "pending"},
            {"name": "Company C", "website": "", "maps_url": "https://maps.google.com/?cid=1", "status": "pending"},
            {"name": "Company D", "website": "https://company-d.de", "status": "pending"},
        ]

        # Mock extract_emails_from_website to return synthetic emails
        def mock_extract(url):
            if "company-a" in url:
                return ["info@company-a.de"]
            if "company-d" in url:
                return ["jobs@company-d.de"]
            return []

        scraper.extract_emails_from_website = MagicMock(side_effect=mock_extract)

        progress_calls = []
        def on_prog(idx, biz):
            progress_calls.append((idx, biz["name"], biz["status"]))

        results = scraper.process_businesses_concurrent(
            businesses,
            max_workers=4,
            on_progress=on_prog,
        )

        self.assertEqual(len(results), 4)
        comp_a = next(b for b in results if b["name"] == "Company A")
        self.assertEqual(comp_a["status"], "success")
        self.assertIn("info@company-a.de", comp_a["emails"])

        comp_b = next(b for b in results if b["name"] == "Company B")
        self.assertEqual(comp_b["status"], "no_email")

        comp_c = next(b for b in results if b["name"] == "Company C")
        self.assertEqual(comp_c["status"], "no_website")

        comp_d = next(b for b in results if b["name"] == "Company D")
        self.assertEqual(comp_d["status"], "success")
        self.assertIn("jobs@company-d.de", comp_d["emails"])

        self.assertEqual(len(progress_calls), 4)
        scraper.close()


if __name__ == "__main__":
    unittest.main()
