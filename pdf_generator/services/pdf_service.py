from datetime import datetime
import html
import os
import re
import tempfile

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
MM_TO_PT = PT_PER_INCH / MM_PER_INCH
PT_TO_MM = MM_PER_INCH / PT_PER_INCH


class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        self.set_font('helvetica', 'B', 11)
        self.cell(80)
        self.cell(30, 10, 'Bewerbung', 0, 0, 'C')
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Seite {self.page_no()}', 0, 0, 'C')
        self.cell(0, 10, datetime.now().strftime('%d.%m.%Y'), 0, 0, 'R')


class PDFService:
    def __init__(self):
        self.page_size = 'A4'
        self.margin = 20
        self.font = 'helvetica'
        self.font_size = 11

    def _prepare_html_content(self, content):
        escaped = html.escape(content or '')
        tag_replacements = {
            '&lt;b&gt;': '<b>',
            '&lt;/b&gt;': '</b>',
            '&lt;strong&gt;': '<strong>',
            '&lt;/strong&gt;': '</strong>',
            '&lt;i&gt;': '<i>',
            '&lt;/i&gt;': '</i>',
            '&lt;em&gt;': '<em>',
            '&lt;/em&gt;': '</em>',
            '&lt;u&gt;': '<u>',
            '&lt;/u&gt;': '</u>',
            '&lt;br&gt;': '<br>',
            '&lt;br/&gt;': '<br>',
            '&lt;br /&gt;': '<br>',
        }
        for source, target in tag_replacements.items():
            escaped = escaped.replace(source, target)
        return escaped.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>\n')

    def _contains_rich_text(self, content):
        return bool(re.search(r'</?(?:b|strong|i|em|u|br)\s*/?>', content or '', flags=re.IGNORECASE))

    def _write_content(self, pdf, content, width=None, line_height=5):
        if self._contains_rich_text(content):
            original_right_margin = pdf.r_margin
            if width is not None:
                new_right_margin = max(0.0, pdf.w - pdf.get_x() - width)
                pdf.set_right_margin(new_right_margin)
            pdf.write_html(self._prepare_html_content(content))
            if width is not None:
                pdf.set_right_margin(original_right_margin)
            return

        target_width = 0 if width is None else width
        pdf.multi_cell(target_width, line_height, content)

    def create_pdf(self, content, output_path, metadata=None, design_pdf_path=None, layout_options=None):
        try:
            if design_pdf_path:
                return self._create_pdf_with_design(
                    content=content,
                    output_path=output_path,
                    metadata=metadata,
                    design_pdf_path=design_pdf_path,
                    layout_options=layout_options,
                )

            if layout_options:
                return self._create_pdf_custom(
                    content=content,
                    output_path=output_path,
                    metadata=metadata,
                    layout_options=layout_options,
                )

            pdf = PDF(orientation='P', unit='mm', format=self.page_size)
            pdf.set_left_margin(self.margin)
            pdf.set_right_margin(self.margin)

            if metadata:
                pdf.set_title(metadata.get('title', 'Document'))
                pdf.set_author(metadata.get('author', 'PDF Generator'))
                pdf.set_subject(metadata.get('subject', ''))

            pdf.add_page()
            pdf.set_font(self.font, '', self.font_size)
            self._write_content(pdf, content, line_height=5)
            pdf.output(output_path)
            return output_path
        except Exception as exc:
            raise Exception(f"Error creating PDF: {exc}")

    def _to_float(self, value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _normalize_layout_options(self, layout_options, page_width_mm, page_height_mm):
        options = layout_options or {}
        margin_left = max(0.0, min(page_width_mm - 5.0, self._to_float(options.get('margin_left'), self.margin)))
        margin_right = max(0.0, min(page_width_mm - 5.0, self._to_float(options.get('margin_right'), self.margin)))
        margin_top = max(0.0, min(page_height_mm - 5.0, self._to_float(options.get('margin_top'), self.margin)))
        margin_bottom = max(0.0, min(page_height_mm - 5.0, self._to_float(options.get('margin_bottom'), self.margin)))

        default_text_width = max(20.0, page_width_mm - margin_left - margin_right)
        default_text_height = max(20.0, page_height_mm - margin_top - margin_bottom)

        text_width = self._to_float(options.get('text_width'), default_text_width)
        text_height = self._to_float(options.get('text_height'), default_text_height)
        text_width = max(20.0, min(text_width, max(20.0, page_width_mm - margin_left)))
        text_height = max(20.0, min(text_height, max(20.0, page_height_mm - margin_top)))

        return {
            'font_size': max(6.0, min(48.0, self._to_float(options.get('font_size'), self.font_size))),
            'line_height': max(2.0, min(30.0, self._to_float(options.get('line_height'), 5.0))),
            'margin_left': margin_left,
            'margin_right': margin_right,
            'margin_top': margin_top,
            'margin_bottom': margin_bottom,
            'text_width': text_width,
            'text_height': text_height,
        }

    def _clip_text_to_height(self, pdf_obj, content, width, line_height, max_height):
        if max_height <= 0:
            return content
        lines = pdf_obj.multi_cell(
            w=width,
            h=line_height,
            text=content,
            dry_run=True,
            output='LINES',
        )
        if not isinstance(lines, list):
            return content
        max_lines = int(max_height // line_height)
        if max_lines <= 0:
            return ''
        return '\n'.join(lines[:max_lines])

    def _create_pdf_custom(self, content, output_path, metadata, layout_options):
        pdf = FPDF(orientation='P', unit='mm', format=self.page_size)
        pdf.set_auto_page_break(auto=False)

        if metadata:
            pdf.set_title(metadata.get('title', 'Document'))
            pdf.set_author(metadata.get('author', 'PDF Generator'))
            pdf.set_subject(metadata.get('subject', ''))

        pdf.add_page()
        opts = self._normalize_layout_options(layout_options, pdf.w, pdf.h)
        pdf.set_font(self.font, '', opts['font_size'])

        pdf.set_xy(opts['margin_left'], opts['margin_top'])
        if self._contains_rich_text(content):
            self._write_content(pdf, content, width=opts['text_width'], line_height=opts['line_height'])
        else:
            clipped_text = self._clip_text_to_height(
                pdf_obj=pdf,
                content=content,
                width=opts['text_width'],
                line_height=opts['line_height'],
                max_height=opts['text_height'],
            )
            self._write_content(pdf, clipped_text, width=opts['text_width'], line_height=opts['line_height'])
        pdf.output(output_path)
        return output_path

    def _create_pdf_with_design(self, content, output_path, metadata, design_pdf_path, layout_options):
        if not os.path.exists(design_pdf_path):
            raise Exception(f"Design PDF not found: {design_pdf_path}")

        reader = PdfReader(design_pdf_path)
        if not reader.pages:
            raise Exception('Design PDF has no pages')

        base_page = reader.pages[0]
        page_width_pt = float(base_page.mediabox.width)
        page_height_pt = float(base_page.mediabox.height)
        page_width_mm = page_width_pt * PT_TO_MM
        page_height_mm = page_height_pt * PT_TO_MM
        opts = self._normalize_layout_options(layout_options, page_width_mm, page_height_mm)

        overlay_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        overlay_path = overlay_file.name
        overlay_file.close()

        try:
            overlay_pdf = FPDF(orientation='P', unit='pt', format=(page_width_pt, page_height_pt))
            overlay_pdf.set_auto_page_break(auto=False)
            overlay_pdf.add_page()
            overlay_pdf.set_font(self.font, '', opts['font_size'])

            x_pt = opts['margin_left'] * MM_TO_PT
            y_pt = opts['margin_top'] * MM_TO_PT
            width_pt = opts['text_width'] * MM_TO_PT
            line_height_pt = opts['line_height'] * MM_TO_PT
            max_height_pt = opts['text_height'] * MM_TO_PT

            overlay_pdf.set_xy(x_pt, y_pt)
            if self._contains_rich_text(content):
                self._write_content(overlay_pdf, content, width=width_pt, line_height=line_height_pt)
            else:
                clipped_text = self._clip_text_to_height(
                    pdf_obj=overlay_pdf,
                    content=content,
                    width=width_pt,
                    line_height=line_height_pt,
                    max_height=max_height_pt,
                )
                self._write_content(
                    overlay_pdf,
                    clipped_text,
                    width=width_pt,
                    line_height=line_height_pt,
                )
            overlay_pdf.output(overlay_path)

            overlay_reader = PdfReader(overlay_path)
            if not overlay_reader.pages:
                raise Exception('Failed to build overlay PDF')

            base_page.merge_page(overlay_reader.pages[0])

            writer = PdfWriter()
            writer.add_page(base_page)
            if metadata:
                writer.add_metadata(
                    {
                        '/Title': metadata.get('title', 'Document'),
                        '/Author': metadata.get('author', 'PDF Generator'),
                        '/Subject': metadata.get('subject', ''),
                    }
                )

            with open(output_path, 'wb') as out_file:
                writer.write(out_file)
            return output_path
        finally:
            try:
                os.remove(overlay_path)
            except OSError:
                pass

    def create_html_pdf(self, html_content, output_path):
        raise NotImplementedError('Use pdfkit/weasyprint if HTML to PDF is required.')

    def set_font_style(self, font='helvetica', size=11):
        self.font = font
        self.font_size = size

    def get_supported_fonts(self):
        return ['helvetica', 'times', 'courier', 'symbol', 'zapfdingbats']
