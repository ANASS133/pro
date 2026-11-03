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
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        # Generate a small valid PDF in memory
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('helvetica', '', 12)
        pdf.cell(0, 10, 'Anass Sibbi - Softwareentwickler', ln=1)
        pdf.cell(0, 10, 'anass.sibbi@example.com - 50667 Koeln', ln=1)
        pdf.cell(0, 10, 'Skills: Python, React, Docker, Git, SQL', ln=1)
        pdf_bytes = io.BytesIO(pdf.output())

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch('routes.autofill.PROFILES_DIR', Path(tmp_dir)):
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
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from services.client_manager import ClientManager

        corrupt_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length 999 >>\nstream\n(corrupt incomplete stream without EOF"
        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_path = Path(tmp_root)
            isolated_mgr = ClientManager(
                clients_dir=tmp_path / "clients",
                autofill_dir=tmp_path / "autofill",
            )
            with patch("routes.clients.client_manager", isolated_mgr):
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


    def test_pymupdf_metadata_and_thumbnail(self):
        """Verifies PyMuPDF-powered metadata extraction and page thumbnail rendering."""
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('helvetica', '', 12)
        pdf.cell(0, 10, 'Test Candidate - Fullstack Developer', new_x='LMARGIN', new_y='NEXT')
        pdf.cell(0, 10, 'dev@example.de', new_x='LMARGIN', new_y='NEXT')
        pdf_bytes = bytes(pdf.output())

        # Test metadata
        meta = CVParser.extract_cv_metadata(pdf_bytes)
        self.assertEqual(meta['page_count'], 1)
        self.assertTrue(meta['has_text'])
        self.assertGreater(meta['file_size'], 100)

        # Test thumbnail rendering (returns valid PNG bytes)
        thumb = CVParser.render_pdf_thumbnail(pdf_bytes, page_num=0, dpi=100)
        self.assertIsNotNone(thumb)
        self.assertTrue(thumb.startswith(b'\x89PNG\r\n\x1a\n'), "Thumbnail should be a valid PNG image")

    def test_extract_tables_with_pdfplumber(self):
        """Verifies structured table extraction using pdfplumber."""
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page()
        
        # Draw a simple table grid with text
        rect = pymupdf.Rect(50, 50, 300, 150)
        page.draw_rect(rect)
        page.insert_text(pymupdf.Point(60, 80), "Zeitraum\tRolle\tUnternehmen\n2020-2023\tEntwickler\tTech GmbH")
        pdf_bytes = doc.tobytes()
        doc.close()

        # Text extraction should succeed
        text = CVParser.extract_text_from_pdf(pdf_bytes)
        self.assertIn("Tech GmbH", text)

        # Table extraction should execute without crashing
        tables = CVParser.extract_tables_from_pdf(pdf_bytes)
        self.assertIsInstance(tables, list)

    def test_extract_profile_photo_with_pymupdf(self):
        """Verifies portrait photo extraction from CV."""
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page()

        # Insert a 150x150 dummy portrait image
        from PIL import Image
        img = Image.new('RGB', (150, 150), color=(73, 109, 137))
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format='PNG')
        img_bytes = img_bytes_io.getvalue()

        img_rect = pymupdf.Rect(50, 50, 200, 200)
        page.insert_image(img_rect, stream=img_bytes)
        pdf_bytes = doc.tobytes()
        doc.close()

        extracted_photo = CVParser.extract_profile_photo(pdf_bytes)
        self.assertIsNotNone(extracted_photo, "Should detect and extract candidate portrait photo")
        self.assertGreater(len(extracted_photo), 100)

if __name__ == '__main__':
    unittest.main()
