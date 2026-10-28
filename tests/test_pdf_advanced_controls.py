import io
import os
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader

from pdf_generator.services.pdf_service import (
    DIN_5008_PRESETS,
    PDFService,
    _parse_color,
)
from app import app


class PDFAdvancedControlsTests(unittest.TestCase):
    def setUp(self):
        self.service = PDFService()
        self.client = app.test_client()

    def test_parse_color_hex_and_tuple(self):
        self.assertEqual(_parse_color("#1e3a8a"), (30, 58, 138))
        self.assertEqual(_parse_color("#fff"), (255, 255, 255))
        self.assertEqual(_parse_color((20, 40, 60)), (20, 40, 60))
        self.assertEqual(_parse_color("invalid", default=(0, 0, 0)), (0, 0, 0))

    def test_din_5008_presets_definitions(self):
        self.assertIn("form_a", DIN_5008_PRESETS)
        self.assertIn("form_b", DIN_5008_PRESETS)
        form_a = DIN_5008_PRESETS["form_a"]
        form_b = DIN_5008_PRESETS["form_b"]

        self.assertEqual(form_a["margin_left"], 25.0)
        self.assertEqual(form_a["fold_mark_1"], 87.0)
        self.assertEqual(form_a["punch_mark"], 105.0)

        self.assertEqual(form_b["margin_left"], 25.0)
        self.assertEqual(form_b["fold_mark_1"], 105.0)
        self.assertEqual(form_b["punch_mark"], 148.5)

    def test_din5008_api_endpoint(self):
        response = self.client.get("/api/pdf/din5008-presets")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("presets", data)
        self.assertIn("form_a", data["presets"])
        self.assertIn("form_b", data["presets"])

    def test_fonts_api_endpoint_includes_custom_and_supported(self):
        response = self.client.get("/api/pdf/fonts")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("helvetica", data.get("supported_fonts", []))
        self.assertIsInstance(data.get("custom_fonts"), list)

    def test_create_pdf_with_din5008_form_b(self):
        content = "Sehr geehrte Damen und Herren,\n\nDies ist ein standardisiertes DIN 5008 Anschreiben."
        stream = self.service.create_pdf_stream(
            content=content,
            layout_options={
                "din_5008_preset": "form_b",
                "show_fold_marks": True,
            },
        )
        self.assertIsNotNone(stream)
        reader = PdfReader(stream)
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("DIN 5008 Anschreiben", text)

    def test_auto_fit_text_scales_down_font_size(self):
        # A long letter that would normally overflow a short text box
        long_text = "Dies ist ein wichtiger Absatz über meine Qualifikationen. " * 30
        stream = self.service.create_pdf_stream(
            content=long_text,
            layout_options={
                "font_size": 14.0,
                "line_height": 7.0,
                "text_height": 50.0,  # restricted height
                "auto_fit": True,
                "min_font_size": 8.0,
            },
        )
        reader = PdfReader(stream)
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("Qualifikationen", text)

    def test_custom_header_footer_and_branding(self):
        content = "Bewerbungstext mit individuellem Briefkopf und Fußzeile."
        stream = self.service.create_pdf_stream(
            content=content,
            layout_options={
                "text_color": "#1f2937",
                "watermark": "VERTRAULICH",
                "header": {
                    "enabled": True,
                    "text": "Max Mustermann • Bewerbung",
                    "show_line": True,
                    "color": "#3b82f6",
                },
                "footer": {
                    "enabled": True,
                    "text": "Tel: 0123-456789 • info@muster.de",
                    "template": "Seite {page}",
                    "show_date": True,
                    "show_line": True,
                },
            },
        )
        reader = PdfReader(stream)
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("Max Mustermann", text)
        self.assertIn("0123-456789", text)
        self.assertIn("VERTRAULICH", text)

    def test_stream_preview_endpoint_with_custom_controls(self):
        response = self.client.post(
            "/api/pdf/stream-preview",
            json={
                "content": "Hallo Welt! Live-Stream Vorschau Test.",
                "layout_options": {
                    "din_5008_preset": "form_a",
                    "show_fold_marks": True,
                    "text_color": "#111827",
                    "watermark": "VORSCHAU",
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        reader = PdfReader(io.BytesIO(response.data))
        self.assertGreaterEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("Live-Stream Vorschau", text)
        self.assertIn("VORSCHAU", text)

    def test_html_custom_css_injection_and_scale(self):
        html_content = "<!DOCTYPE html><html><body><h1 style='color: navy;'>HTML Title</h1><p>HTML Test Body</p></body></html>"
        stream = self.service.create_pdf_stream(
            content=html_content,
            layout_options={
                "scale": 0.9,
                "custom_css": "h1 { font-size: 24px !important; }",
            },
        )
        self.assertIsNotNone(stream)
        reader = PdfReader(stream)
        self.assertGreaterEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("HTML Title", text)


if __name__ == "__main__":
    unittest.main()
