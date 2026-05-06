import unittest

from pdf_generator.services.template_service import TemplateService


class TemplateServiceTests(unittest.TestCase):
    def test_replace_placeholders_supports_case_and_builtin_date(self):
        service = TemplateService()
        row = {"Unternehmen": "Beispiel GmbH", "Email": "jobs@example.com"}
        columns = ["Unternehmen", "Email"]

        rendered = service.replace_placeholders(
            "Firma {{ unternehmen }} - {{todayDate}} - {{email}}",
            row,
            columns,
        )

        self.assertIn("Beispiel GmbH", rendered)
        self.assertIn("jobs@example.com", rendered)
        self.assertNotIn("{{", rendered)

    def test_generate_filename_sanitizes_invalid_characters(self):
        service = TemplateService()
        filename = service.generate_filename(
            "{{Unternehmen}}",
            {"Unternehmen": 'ACME:/Test*'},
            ["Unternehmen"],
            0,
        )

        self.assertTrue(filename.endswith(".pdf"))
        self.assertNotIn(":", filename)
        self.assertNotIn("*", filename)
