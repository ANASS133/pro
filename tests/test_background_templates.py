import unittest
from pathlib import Path
from pypdf import PdfReader

from pdf_generator.services.background_templates import (
    BACKGROUND_TEMPLATES,
    ensure_templates_generated,
    get_template_by_id,
    get_template_pdf_path,
)
from pdf_generator.services.pdf_service import PDFService


class BackgroundTemplatesTests(unittest.TestCase):
    def setUp(self):
        ensure_templates_generated()

    def test_all_templates_defined_and_generated(self):
        self.assertGreaterEqual(len(BACKGROUND_TEMPLATES), 6)
        for t in BACKGROUND_TEMPLATES:
            t_id = t["id"]
            path = get_template_pdf_path(t_id)
            self.assertIsNotNone(path, f"Template {t_id} path should not be None")
            self.assertTrue(Path(path).exists(), f"File for {t_id} should exist")
            
            # Verify valid PDF structure
            reader = PdfReader(str(path))
            self.assertGreaterEqual(len(reader.pages), 1, f"Template {t_id} should have at least 1 page")
            self.assertGreater(float(reader.pages[0].mediabox.width), 0)
            self.assertGreater(float(reader.pages[0].mediabox.height), 0)

    def test_get_template_by_id(self):
        indigo = get_template_by_id("modern_indigo")
        self.assertIsNotNone(indigo)
        self.assertEqual(indigo["name"], "Modern Indigo")
        self.assertIn("recommendedMargins", indigo)

        nonexistent = get_template_by_id("invalid_id")
        self.assertIsNone(nonexistent)

    def test_create_pdf_with_background_template(self):
        path = get_template_pdf_path("modern_indigo")
        service = PDFService()
        stream = service.create_pdf_stream(
            content="Sehr geehrte Damen und Herren,\n\nTest-Anschreiben Text.",
            design_pdf_path=str(path),
        )
        self.assertIsNotNone(stream)
        reader = PdfReader(stream)
        self.assertGreaterEqual(len(reader.pages), 1)
    def test_background_headers_have_no_text_titles(self):
        unwanted_header_terms = [
            "BEWERBUNG | ANSCHREIBEN",
            "CURRICULUM VITAE",
            "EXECUTIVE DOSSIER",
            "BEWERBUNGSSCHREIBEN",
            "BERUFLICHER WERDEGANG",
            "KREATIVBEWERBUNG",
            "PORTFOLIO & PROFILE",
            "ATS-OPTIMIERT",
            "JS",
        ]
        for t in BACKGROUND_TEMPLATES:
            path = get_template_pdf_path(t["id"])
            reader = PdfReader(str(path))
            text = reader.pages[0].extract_text()
            for term in unwanted_header_terms:
                self.assertNotIn(
                    term,
                    text,
                    f"Background template {t['id']} should not contain '{term}' in the header",
                )


if __name__ == "__main__":
    unittest.main()
