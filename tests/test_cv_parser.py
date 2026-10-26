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

if __name__ == '__main__':
    unittest.main()
