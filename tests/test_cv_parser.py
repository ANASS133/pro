import io
import unittest
from fpdf import FPDF
from services.cv_parser import CVParser
import app as flask_app

class TestCVParser(unittest.TestCase):
    def test_parse_sample_cv_text(self):
        sample_cv = """
        Lebenslauf
        Max Mustermann
        max.mustermann@example.com
        +49 170 12345678
        50667 Köln

        Kenntnisse und Fähigkeiten:
        Programmiersprachen: Python, JavaScript, TypeScript, SQL
        Webentwicklung: React, HTML, CSS, Flask, REST APIs
        Tools & Cloud: Git, Docker, Linux

        Sprachen:
        Deutsch (Muttersprache)
        Englisch (Fließend)
        """
        parsed = CVParser.parse_cv_text(sample_cv)
        self.assertEqual(parsed["personal"]["first_name"], "Max")
        self.assertEqual(parsed["personal"]["last_name"], "Mustermann")
        self.assertEqual(parsed["contact"]["email"], "max.mustermann@example.com")
        self.assertEqual(parsed["contact"]["address"]["city"], "Köln")
        self.assertIn("Python", parsed["skills"]["technologies_from_cv"])
        self.assertIn("React", parsed["skills"]["technologies_from_cv"])
        self.assertIn("Docker", parsed["skills"]["technologies_from_cv"])

    def test_parse_full_candidate_fields_for_autofill_hub(self):
        full_cv = """
        Lebenslauf
        Sarah Schmidt
        Fachinformatikerin fuer Anwendungsentwicklung
        Geburtsdatum: 12.04.1999
        Geburtsort: Frankfurt
        Staatsangehoerigkeit: Deutsch
        Musterstrasse 42b
        60311 Frankfurt am Main
        sarah.schmidt@example.com
        +49 171 9876543
        https://linkedin.com/in/sarah-schmidt
        https://github.com/sarah-dev
        https://sarah-schmidt.io

        Profil:
        Motivierte Softwareentwicklerin mit Leidenschaft fuer Python, React und Cloud-Technologien.

        Kenntnisse:
        Python, JavaScript, TypeScript, React, Docker, Git, REST, PostgreSQL

        Sprachen:
        Deutsch (Muttersprache)
        Englisch (Fliessend)
        """
        parsed = CVParser.parse_cv_text(full_cv)

        # Personal fields
        self.assertEqual(parsed["personal"]["first_name"], "Sarah")
        self.assertEqual(parsed["personal"]["last_name"], "Schmidt")
        self.assertEqual(parsed["personal"]["full_name"], "Sarah Schmidt")
        self.assertEqual(parsed["personal"]["date_of_birth"], "1999-04-12")
        self.assertEqual(parsed["personal"]["date_of_birth_display"], "12.04.1999")
        self.assertEqual(parsed["personal"]["place_of_birth"], "Frankfurt")
        self.assertEqual(parsed["personal"]["nationality"], "Deutsch")
        self.assertEqual(parsed["personal"]["salutation"], "Frau")
        self.assertEqual(parsed["personal"]["gender"], "female")

        # Contact & Address
        self.assertEqual(parsed["contact"]["email"], "sarah.schmidt@example.com")
        self.assertEqual(parsed["contact"]["phone"], "+49 171 9876543")
        self.assertEqual(parsed["contact"]["address"]["street"], "Musterstrasse")
        self.assertEqual(parsed["contact"]["address"]["house_number"], "42b")
        self.assertEqual(parsed["contact"]["address"]["postal_code"], "60311")
        self.assertEqual(parsed["contact"]["address"]["city"], "Frankfurt am Main")
        self.assertEqual(parsed["contact"]["linkedin"]["url"], "https://linkedin.com/in/sarah-schmidt")
        self.assertEqual(parsed["contact"]["github"]["url"], "https://github.com/sarah-dev")
        self.assertEqual(parsed["contact"]["portfolio"]["url"], "https://sarah-schmidt.io")

        # Professional profile
        self.assertEqual(parsed["professional_profile"]["current_title"], "Fachinformatikerin fuer Anwendungsentwicklung")
        self.assertIn("Sarah Schmidt", parsed["professional_profile"]["headline"])
        self.assertIn("Motivierte Softwareentwicklerin", parsed["professional_profile"]["summary_de"])
        self.assertIn("Python", parsed["professional_profile"]["primary_fields"])

    def test_upload_cv_endpoint(self):
        # Generate a small valid PDF in memory
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('helvetica', '', 12)
        pdf.cell(0, 10, 'Anass Sibbi - Softwareentwickler', ln=1)
        pdf.cell(0, 10, 'anass.sibbi@example.com - 50667 Koeln', ln=1)
        pdf.cell(0, 10, 'Skills: Python, React, Docker, Git, SQL', ln=1)
        pdf_bytes = io.BytesIO(pdf.output())

        client = flask_app.app.test_client()
        resp = client.post(
            '/api/autofill/upload-cv',
            data={'cv_file': (pdf_bytes, 'lebenslauf.pdf'), 'profile_id': 'anass_sibbi'},
            content_type='multipart/form-data'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('Python', data['parsed_data']['skills']['technologies_from_cv'])

    def test_extract_text_from_pdf_corrupt_or_truncated_stream(self):
        """Verifies that truncated or malformed PDF streams do not raise PdfStreamError."""
        # Create a truncated / malformed stream with text markers
        corrupt_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length 500 >>\nstream\n(Max Mustermann) Tj\n(max@example.com) Tj\n"
        # Should gracefully return recovered text or empty string without raising Stream has ended unexpectedly
        extracted = CVParser.extract_text_from_pdf(corrupt_pdf_bytes)
        self.assertIsInstance(extracted, str)
        self.assertIn("Max Mustermann", extracted)
        self.assertIn("max@example.com", extracted)

    def test_ingest_cv_corrupt_stream_resilience(self):
        """Verifies that /api/clients/ingest-cv successfully ingests CV with malformed/truncated stream."""
        corrupt_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length 999 >>\nstream\n(corrupt incomplete stream without EOF"
        client = flask_app.app.test_client()
        resp = client.post(
            "/api/clients/ingest-cv",
            data={"cv_file": (io.BytesIO(corrupt_bytes), "Lebenslauf_Corrupt_Test.pdf")},
            content_type="multipart/form-data"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("Corrupt Test", data.get("client_name", ""))


if __name__ == '__main__':
    unittest.main()
