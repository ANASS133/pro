import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from pdf_generator.services.html_template import is_html_template
from pdf_generator.services.pdf_service import PDFService
from pdf_generator.services.template_service import TemplateService


class HTMLTemplateTests(unittest.TestCase):
    def test_detect_documents_and_fragments_without_changing_basic_text(self):
        for value in ['<!DOCTYPE html><html></html>', '<STYLE>p {color:red}</STYLE>', '<p>Hello</p>']:
            self.assertTrue(is_html_template(value))
        for value in ['Hello {{company}}', '<b>Hello</b><br><i>World</i>', '3 < 5']:
            self.assertFalse(is_html_template(value))

    def test_placeholder_values_cannot_change_html_structure(self):
        service = TemplateService()
        value = 'A & B <img src=x> "C"'
        rendered = service.replace_placeholders('<p>{{company}}</p>', {'company': value}, ['company'])
        self.assertEqual(rendered, '<p>A &amp; B &lt;img src=x&gt; &quot;C&quot;</p>')
        self.assertEqual(service.replace_placeholders('{{company}}', {'company': value}, ['company']), value)

    def test_html_uses_css_instead_of_text_layout_or_background(self):
        service = PDFService()
        with patch.object(service, 'create_html_pdf', return_value='result.pdf') as render:
            result = service.create_pdf('<div>Hello</div>', 'result.pdf',
                                        design_pdf_path='unused.pdf', layout_options={'font_size': 40})
        self.assertEqual(result, 'result.pdf')
        render.assert_called_once_with('<div>Hello</div>', 'result.pdf', metadata=None)

    def test_plain_and_basic_formatted_text_still_generate_pdfs(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, content in enumerate(['Hello world', '<b>Hello</b><br>world']):
                path = Path(directory) / f'{index}.pdf'
                PDFService().create_pdf(content, str(path))
                text = ''.join(page.extract_text() for page in PdfReader(path).pages)
                self.assertIn('Hello', text)
                self.assertIn('world', text)


if __name__ == '__main__':
    unittest.main()
