from datetime import datetime
import base64
import html
import io
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from .html_template import is_html_template

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
MM_TO_PT = PT_PER_INCH / MM_PER_INCH
PT_TO_MM = MM_PER_INCH / PT_PER_INCH

# DIN 5008 Specifications for German Business Letters
DIN_5008_PRESETS = {
    "form_a": {
        "name": "DIN 5008 Form A (Tiefer Briefkopf)",
        "margin_left": 25.0,
        "margin_right": 20.0,
        "margin_top": 27.0,
        "margin_bottom": 20.0,
        "fold_mark_1": 87.0,
        "punch_mark": 105.0,
        "fold_mark_2": 192.0,
        "text_width": 165.0,
        "recipient_box_y": 27.0,
        "recipient_box_height": 45.0,
    },
    "form_b": {
        "name": "DIN 5008 Form B (Hoher Briefkopf / Standard)",
        "margin_left": 25.0,
        "margin_right": 20.0,
        "margin_top": 45.0,
        "margin_bottom": 20.0,
        "fold_mark_1": 105.0,
        "punch_mark": 148.5,
        "fold_mark_2": 210.0,
        "text_width": 165.0,
        "recipient_box_y": 45.0,
        "recipient_box_height": 45.0,
    },
}


def _parse_color(color_val: Any, default: Tuple[int, int, int] = (0, 0, 0)) -> Tuple[int, int, int]:
    """Parse color from RGB tuple/list or hex string (#RRGGBB / #RGB)."""
    if isinstance(color_val, (list, tuple)) and len(color_val) == 3:
        try:
            return int(color_val[0]), int(color_val[1]), int(color_val[2])
        except (ValueError, TypeError):
            return default
    if isinstance(color_val, str) and color_val.startswith("#"):
        c = color_val.lstrip("#")
        try:
            if len(c) == 6:
                return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            if len(c) == 3:
                return int(c[0] * 2, 16), int(c[1] * 2, 16), int(c[2] * 2, 16)
        except ValueError:
            return default
    return default


def _safe_latin1_text(text: str) -> str:
    """Replaces common non-latin1 typographic characters (bullets, curly quotes, dashes) with safe equivalents."""
    if not text:
        return ""
    text = str(text)
    replacements = {
        '\u2022': '-',      # bullet -> hyphen
        '\u2023': '>',
        '\u2043': '-',
        '\u2013': '-',      # en-dash -> hyphen
        '\u2014': '--',     # em-dash
        '\u2018': "'",      # single quotes
        '\u2019': "'",
        '\u201a': "'",
        '\u201c': '"',      # double quotes
        '\u201d': '"',
        '\u201e': '"',
        '\u2026': '...',    # ellipsis
        '\u00a0': ' ',      # non-breaking space
        '\u202f': ' ',      # narrow space
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text


def _discover_system_fonts() -> Dict[str, str]:
    """Scans operating system and project directories for common TTF fonts."""
    fonts = {}
    search_paths = []
    if os.name == "nt":
        win_dir = os.environ.get("WINDIR", "C:\\Windows")
        search_paths.append(Path(win_dir) / "Fonts")
    else:
        search_paths.extend([
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path("~/.fonts").expanduser(),
        ])

    local_fonts_dir = Path(__file__).resolve().parent.parent / "fonts"
    if local_fonts_dir.exists():
        search_paths.append(local_fonts_dir)

    font_candidates = {
        "arial": ["arial.ttf", "Arial.ttf"],
        "calibri": ["calibri.ttf", "Calibri.ttf"],
        "segoe ui": ["segoeui.ttf", "SegoeUI.ttf"],
        "georgia": ["georgia.ttf", "Georgia.ttf"],
        "verdana": ["verdana.ttf", "Verdana.ttf"],
        "tahoma": ["tahoma.ttf", "Tahoma.ttf"],
        "trebuchet": ["trebuc.ttf", "Trebuchet.ttf"],
        "times new roman": ["times.ttf", "Times.ttf"],
    }

    for base_dir in search_paths:
        if not base_dir.exists():
            continue
        for font_key, filenames in font_candidates.items():
            if font_key in fonts:
                continue
            for fname in filenames:
                candidate = base_dir / fname
                if candidate.exists():
                    fonts[font_key] = str(candidate)
                    break
    return fonts


class PDF(FPDF):
    def __init__(self, *args, header_enabled=True, footer_enabled=True, header_text="Bewerbung", **kwargs):
        super().__init__(*args, **kwargs)
        self.set_auto_page_break(auto=True, margin=25)
        self.header_enabled = header_enabled
        self.footer_enabled = footer_enabled
        self.header_text = header_text

    def header(self):
        if not self.header_enabled:
            return
        self.set_font('helvetica', 'B', 11)
        self.cell(80)
        self.cell(30, 10, self.header_text, border=0, align='C')
        self.ln(15)

    def footer(self):
        if not self.footer_enabled:
            return
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Seite {self.page_no()}', border=0, align='C')
        self.cell(0, 10, datetime.now().strftime('%d.%m.%Y'), border=0, align='R')


class PDFService:
    def __init__(self):
        self.page_size = 'A4'
        self.margin = 20
        self.font = 'helvetica'
        self.font_size = 11
        self.custom_fonts: Dict[str, str] = _discover_system_fonts()

    def register_font(self, font_name: str, font_path: str) -> bool:
        """Register a custom TTF font for PDF generation."""
        if os.path.exists(font_path):
            self.custom_fonts[font_name.lower().strip()] = str(font_path)
            return True
        return False

    def get_supported_fonts(self) -> List[str]:
        core = ['helvetica', 'times', 'courier', 'symbol', 'zapfdingbats']
        custom = sorted(list(self.custom_fonts.keys()))
        return core + custom

    def _apply_font(self, pdf_obj: FPDF, font_name: str, style: str = '', size: float = 11.0) -> str:
        """Apply font by name, seamlessly registering TTF fonts in FPDF as needed."""
        font_key = (font_name or self.font).lower().strip()
        if font_key in self.custom_fonts:
            font_path = self.custom_fonts[font_key]
            family_name = font_key.title()
            try:
                if family_name not in pdf_obj.fonts:
                    pdf_obj.add_font(family_name, style='', fname=font_path)
                pdf_obj.set_font(family_name, style, size)
                return family_name
            except Exception as exc:
                logger.warning(f"Could not load custom font '{font_name}' ({exc}); falling back to helvetica.")

        target = font_key if font_key in ['helvetica', 'times', 'courier', 'symbol', 'zapfdingbats'] else 'helvetica'
        pdf_obj.set_font(target, style, size)
        return target

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
        try:
            pdf.multi_cell(target_width, line_height, content)
        except Exception as exc:
            if "outside the range of characters" in str(exc) or "latin-1" in str(exc):
                pdf.multi_cell(target_width, line_height, _safe_latin1_text(content))
            else:
                raise

    def _draw_din_marks(self, pdf_obj: FPDF, preset_key: str = "form_b", unit: str = "mm"):
        """Draw German DIN 5008 fold marks and punch mark on left edge."""
        preset = DIN_5008_PRESETS.get(str(preset_key).lower(), DIN_5008_PRESETS["form_b"])
        scale = MM_TO_PT if unit == "pt" else 1.0

        pdf_obj.set_draw_color(180, 180, 180)
        pdf_obj.set_line_width(0.2 * scale)

        # Punch mark (Lochmarke) - longer line at left margin
        pm_y = preset["punch_mark"] * scale
        pdf_obj.line(4.0 * scale, pm_y, 9.0 * scale, pm_y)

        # Fold mark 1 (Falzmarke 1)
        fm1_y = preset["fold_mark_1"] * scale
        pdf_obj.line(4.0 * scale, fm1_y, 7.0 * scale, fm1_y)

        # Fold mark 2 (Falzmarke 2)
        fm2_y = preset["fold_mark_2"] * scale
        pdf_obj.line(4.0 * scale, fm2_y, 7.0 * scale, fm2_y)

    def _draw_watermark(self, pdf_obj: FPDF, text: str, unit: str = "mm", color: Any = (220, 220, 220)):
        """Draw subtle diagonal watermark centered across the page."""
        if not text:
            return
        r, g, b = _parse_color(color, default=(220, 220, 220))
        pdf_obj.set_text_color(r, g, b)
        pdf_obj.set_font('helvetica', 'B', 46)
        safe_text = _safe_latin1_text(text)
        try:
            with pdf_obj.rotation(45, pdf_obj.w / 2, pdf_obj.h / 2):
                pdf_obj.text(pdf_obj.w * 0.22, pdf_obj.h * 0.5, safe_text)
        except Exception as exc:
            logger.warning(f"Watermark rotation error: {exc}")

    def _render_custom_header(
        self, pdf_obj: FPDF, header_cfg: Dict[str, Any], width: float, margin_left: float, margin_top: float, unit: str = "mm"
    ):
        """Render configurable header line and text."""
        if not header_cfg or not header_cfg.get("enabled"):
            return
        scale = MM_TO_PT if unit == "pt" else 1.0
        text = str(header_cfg.get("text") or "")
        align = str(header_cfg.get("align") or "R").upper()
        font_size = float(header_cfg.get("font_size", 9.0))
        color = _parse_color(header_cfg.get("color"), default=(100, 116, 139))
        show_line = bool(header_cfg.get("show_line", True))

        pdf_obj.set_xy(margin_left, max(4.0 * scale, margin_top - (12.0 * scale)))
        header_font = header_cfg.get("font")
        if header_font:
            self._apply_font(pdf_obj, header_font, '', font_size)
        else:
            pdf_obj.set_font('helvetica', '', font_size)
            text = _safe_latin1_text(text)

        pdf_obj.set_text_color(*color)
        if text:
            pdf_obj.cell(width, 6.0 * scale, text, border=0, align=align)
        if show_line:
            line_y = pdf_obj.get_y() + (7.0 * scale)
            pdf_obj.set_draw_color(*color)
            pdf_obj.set_line_width(0.2 * scale)
            pdf_obj.line(margin_left, line_y, margin_left + width, line_y)

    def _render_custom_footer(
        self, pdf_obj: FPDF, footer_cfg: Dict[str, Any], width: float, margin_left: float, page_height: float, unit: str = "mm"
    ):
        """Render configurable footer line, page numbering, and date."""
        if not footer_cfg or not footer_cfg.get("enabled"):
            return
        scale = MM_TO_PT if unit == "pt" else 1.0
        font_size = float(footer_cfg.get("font_size", 8.0))
        color = _parse_color(footer_cfg.get("color"), default=(148, 163, 184))
        show_line = bool(footer_cfg.get("show_line", True))
        show_date = bool(footer_cfg.get("show_date", True))
        date_format = str(footer_cfg.get("date_format", "%d.%m.%Y"))
        date_str = datetime.now().strftime(date_format) if show_date else ""
        text = str(footer_cfg.get("text") or "")
        raw_template = str(footer_cfg.get("template") or "Seite {page}")
        page_str = raw_template.replace("{page}", str(pdf_obj.page_no()))

        footer_y = page_height - (14.0 * scale)
        if show_line:
            pdf_obj.set_draw_color(*color)
            pdf_obj.set_line_width(0.2 * scale)
            pdf_obj.line(margin_left, footer_y - (2.0 * scale), margin_left + width, footer_y - (2.0 * scale))

        pdf_obj.set_xy(margin_left, footer_y)
        footer_font = footer_cfg.get("font")
        if footer_font:
            self._apply_font(pdf_obj, footer_font, '', font_size)
        else:
            pdf_obj.set_font('helvetica', '', font_size)
            text = _safe_latin1_text(text)
            date_str = _safe_latin1_text(date_str)

        pdf_obj.set_text_color(*color)

        if text:
            pdf_obj.cell(width * 0.5, 5.0 * scale, text, border=0, align="L")
        right_info = f"{page_str} | {date_str}" if date_str else page_str
        pdf_obj.set_xy(margin_left + (width * 0.4), footer_y)
        pdf_obj.cell(width * 0.6, 5.0 * scale, right_info, border=0, align="R")

    def _auto_fit_text(
        self,
        pdf_obj: FPDF,
        content: str,
        width: float,
        initial_font_size: float,
        initial_line_height: float,
        max_height: float,
        min_font_size: float = 8.0,
    ) -> Tuple[float, float]:
        """
        Dynamically scales down font size and line height so text fits cleanly on one page
        without truncation or overflow.
        """
        if max_height <= 0 or not content:
            return initial_font_size, initial_line_height

        font_size = float(initial_font_size)
        line_height = float(initial_line_height)
        ratio = line_height / font_size if font_size > 0 else 0.45

        def _measure_lines(txt: str, h: float) -> int:
            try:
                res = pdf_obj.multi_cell(w=width, h=h, text=txt, dry_run=True, output='LINES')
                return len(res) if isinstance(res, list) else 0
            except Exception as exc:
                if "outside the range of characters" in str(exc) or "latin-1" in str(exc):
                    safe_txt = _safe_latin1_text(txt)
                    res = pdf_obj.multi_cell(w=width, h=h, text=safe_txt, dry_run=True, output='LINES')
                    return len(res) if isinstance(res, list) else 0
                raise

        pdf_obj.set_font_size(font_size)
        line_count = _measure_lines(content, line_height)
        rendered_height = line_count * line_height

        if rendered_height <= max_height:
            return font_size, line_height

        # Scale down in smooth 0.25 pt increments
        while font_size > min_font_size:
            font_size = max(min_font_size, round(font_size - 0.25, 2))
            line_height = round(font_size * ratio, 2)
            pdf_obj.set_font_size(font_size)
            line_count = _measure_lines(content, line_height)
            rendered_height = line_count * line_height
            if rendered_height <= max_height:
                break

        return font_size, line_height

    def create_pdf_stream(self, content, metadata=None, design_pdf_path=None, layout_options=None):
        """Generate PDF in-memory and return a BytesIO stream without writing to disk."""
        return self.create_pdf(
            content=content,
            output_path=None,
            metadata=metadata,
            design_pdf_path=design_pdf_path,
            layout_options=layout_options,
        )

    def create_pdf(self, content, output_path=None, metadata=None, design_pdf_path=None, layout_options=None):
        try:
            if is_html_template(content):
                # HTML supplies its own page layout, including @page print rules.
                # If specific HTML CDP parameters are provided, pass layout_options; otherwise keep standard signature
                has_html_opts = layout_options and any(k in layout_options for k in ('scale', 'custom_css', 'print_background'))
                if has_html_opts:
                    return self.create_html_pdf(content, output_path, metadata=metadata, layout_options=layout_options)
                return self.create_html_pdf(content, output_path, metadata=metadata)

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
            if output_path:
                pdf.output(output_path)
                return output_path
            stream = io.BytesIO()
            pdf.output(stream)
            stream.seek(0)
            return stream

        except Exception as exc:
            raise RuntimeError(f"Error creating PDF: {exc}") from exc

    def _to_float(self, value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _normalize_layout_options(self, layout_options, page_width_mm, page_height_mm):
        options = layout_options or {}

        # DIN 5008 Preset handling
        din_preset_key = options.get('din_5008_preset')
        din_preset = DIN_5008_PRESETS.get(str(din_preset_key).lower()) if din_preset_key else None

        default_margin_left = din_preset['margin_left'] if din_preset else self.margin
        default_margin_right = din_preset['margin_right'] if din_preset else self.margin
        default_margin_top = din_preset['margin_top'] if din_preset else self.margin
        default_margin_bottom = din_preset['margin_bottom'] if din_preset else self.margin

        margin_left = max(0.0, min(page_width_mm - 5.0, self._to_float(options.get('margin_left'), default_margin_left)))
        margin_right = max(0.0, min(page_width_mm - 5.0, self._to_float(options.get('margin_right'), default_margin_right)))
        margin_top = max(0.0, min(page_height_mm - 5.0, self._to_float(options.get('margin_top'), default_margin_top)))
        margin_bottom = max(0.0, min(page_height_mm - 5.0, self._to_float(options.get('margin_bottom'), default_margin_bottom)))

        default_text_width = max(20.0, page_width_mm - margin_left - margin_right)
        default_text_height = max(20.0, page_height_mm - margin_top - margin_bottom)

        text_width = self._to_float(options.get('text_width'), default_text_width)
        text_height = self._to_float(options.get('text_height'), default_text_height)
        text_width = max(20.0, min(text_width, max(20.0, page_width_mm - margin_left)))
        text_height = max(20.0, min(text_height, max(20.0, page_height_mm - margin_top)))

        font_name = str(options.get('font') or self.font)
        font_size = max(6.0, min(48.0, self._to_float(options.get('font_size'), self.font_size)))
        line_height = max(2.0, min(30.0, self._to_float(options.get('line_height'), 5.0)))
        auto_fit = bool(options.get('auto_fit', True))
        min_font_size = max(6.0, min(font_size, self._to_float(options.get('min_font_size'), 8.0)))
        show_fold_marks = bool(options.get('show_fold_marks', bool(din_preset)))

        text_color = _parse_color(options.get('text_color'), default=(0, 0, 0))
        primary_color = _parse_color(options.get('primary_color'), default=(30, 58, 138))
        watermark = str(options.get('watermark') or '').strip()

        return {
            'font': font_name,
            'font_size': font_size,
            'line_height': line_height,
            'margin_left': margin_left,
            'margin_right': margin_right,
            'margin_top': margin_top,
            'margin_bottom': margin_bottom,
            'text_width': text_width,
            'text_height': text_height,
            'auto_fit': auto_fit,
            'min_font_size': min_font_size,
            'din_5008_preset': din_preset_key,
            'show_fold_marks': show_fold_marks,
            'text_color': text_color,
            'primary_color': primary_color,
            'watermark': watermark,
            'header': options.get('header'),
            'footer': options.get('footer'),
            'scale': self._to_float(options.get('scale'), 1.0),
            'custom_css': options.get('custom_css'),
            'print_background': options.get('print_background', True),
        }

    def _clip_text_to_height(self, pdf_obj, content, width, line_height, max_height):
        if max_height <= 0:
            return content
        try:
            lines = pdf_obj.multi_cell(
                w=width,
                h=line_height,
                text=content,
                dry_run=True,
                output='LINES',
            )
        except Exception as exc:
            if "outside the range of characters" in str(exc) or "latin-1" in str(exc):
                content = _safe_latin1_text(content)
                lines = pdf_obj.multi_cell(
                    w=width,
                    h=line_height,
                    text=content,
                    dry_run=True,
                    output='LINES',
                )
            else:
                raise
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
        self._apply_font(pdf, opts['font'], '', opts['font_size'])

        # Set configured text color
        tc = opts.get('text_color', (0, 0, 0))
        pdf.set_text_color(*tc)

        # Draw DIN 5008 fold and punch marks if requested
        if opts.get('show_fold_marks'):
            preset_key = opts.get('din_5008_preset') or 'form_b'
            self._draw_din_marks(pdf, preset_key, unit='mm')

        # Draw watermark if requested
        if opts.get('watermark'):
            self._draw_watermark(pdf, opts['watermark'], unit='mm')

        # Custom header
        if opts.get('header'):
            self._render_custom_header(pdf, opts['header'], opts['text_width'], opts['margin_left'], opts['margin_top'], unit='mm')

        font_size = opts['font_size']
        line_height = opts['line_height']

        # Auto-fit text dynamically to avoid clipping
        if opts.get('auto_fit') and not self._contains_rich_text(content):
            font_size, line_height = self._auto_fit_text(
                pdf_obj=pdf,
                content=content,
                width=opts['text_width'],
                initial_font_size=font_size,
                initial_line_height=line_height,
                max_height=opts['text_height'],
                min_font_size=opts['min_font_size'],
            )
            self._apply_font(pdf, opts['font'], '', font_size)

        pdf.set_xy(opts['margin_left'], opts['margin_top'])
        if self._contains_rich_text(content):
            self._write_content(pdf, content, width=opts['text_width'], line_height=line_height)
        else:
            clipped_text = self._clip_text_to_height(
                pdf_obj=pdf,
                content=content,
                width=opts['text_width'],
                line_height=line_height,
                max_height=opts['text_height'],
            )
            self._write_content(pdf, clipped_text, width=opts['text_width'], line_height=line_height)

        # Custom footer
        if opts.get('footer'):
            self._render_custom_footer(pdf, opts['footer'], opts['text_width'], opts['margin_left'], pdf.h, unit='mm')

        if output_path:
            pdf.output(output_path)
            return output_path
        stream = io.BytesIO()
        pdf.output(stream)
        stream.seek(0)
        return stream

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
            self._apply_font(overlay_pdf, opts['font'], '', opts['font_size'])

            # Set text color
            tc = opts.get('text_color', (0, 0, 0))
            overlay_pdf.set_text_color(*tc)

            # Draw fold marks if requested
            if opts.get('show_fold_marks'):
                preset_key = opts.get('din_5008_preset') or 'form_b'
                self._draw_din_marks(overlay_pdf, preset_key, unit='pt')

            # Draw watermark
            if opts.get('watermark'):
                self._draw_watermark(overlay_pdf, opts['watermark'], unit='pt')

            # Custom header
            if opts.get('header'):
                self._render_custom_header(
                    overlay_pdf,
                    opts['header'],
                    opts['text_width'] * MM_TO_PT,
                    opts['margin_left'] * MM_TO_PT,
                    opts['margin_top'] * MM_TO_PT,
                    unit='pt',
                )

            x_pt = opts['margin_left'] * MM_TO_PT
            y_pt = opts['margin_top'] * MM_TO_PT
            width_pt = opts['text_width'] * MM_TO_PT
            line_height_pt = opts['line_height'] * MM_TO_PT
            max_height_pt = opts['text_height'] * MM_TO_PT

            font_size = opts['font_size']
            # Auto-fit text dynamically
            if opts.get('auto_fit') and not self._contains_rich_text(content):
                font_size, line_height_pt = self._auto_fit_text(
                    pdf_obj=overlay_pdf,
                    content=content,
                    width=width_pt,
                    initial_font_size=font_size,
                    initial_line_height=line_height_pt,
                    max_height=max_height_pt,
                    min_font_size=opts['min_font_size'],
                )
                self._apply_font(overlay_pdf, opts['font'], '', font_size)

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

            # Custom footer
            if opts.get('footer'):
                self._render_custom_footer(
                    overlay_pdf,
                    opts['footer'],
                    width_pt,
                    x_pt,
                    page_height_pt,
                    unit='pt',
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

            if output_path:
                with open(output_path, 'wb') as out_file:
                    writer.write(out_file)
                return output_path
            stream = io.BytesIO()
            writer.write(stream)
            stream.seek(0)
            return stream
        finally:
            try:
                os.remove(overlay_path)
            except OSError:
                pass

    def create_html_pdf(self, html_content, output_path=None, metadata=None, layout_options=None):
        from bs4 import BeautifulSoup
        from scraper.browser_driver import find_browser, new_options, start_driver

        document = BeautifulSoup(html_content, 'html.parser')
        # Templates are static documents. Do not execute pasted scripts or redirects.
        for tag in document.select('script, iframe, object, embed, base, meta[http-equiv]'):
            tag.decompose()
        if document.html is None:
            wrapper = BeautifulSoup('<html><head></head><body></body></html>', 'html.parser')
            wrapper.body.extend(list(document.contents))
            document = wrapper
        if document.head is None:
            document.html.insert(0, document.new_tag('head'))
        policy = document.new_tag('meta')
        policy['http-equiv'] = 'Content-Security-Policy'
        policy['content'] = (
            "default-src 'none'; style-src 'unsafe-inline' https:; "
            "img-src data: https:; font-src data: https:; base-uri 'none'; form-action 'none'"
        )
        document.head.insert(0, policy)
        defaults = document.new_tag('style')
        defaults.string = '@page { size: A4; margin: 0; } html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }'
        document.head.insert(1, defaults)

        # Inject custom CSS if provided in layout_options
        if layout_options and layout_options.get('custom_css'):
            custom_style = document.new_tag('style')
            custom_style.string = str(layout_options['custom_css'])
            document.head.append(custom_style)

        # Build CDP print options
        cdp_options = {
            'printBackground': layout_options.get('print_background', True) if layout_options else True,
            'preferCSSPageSize': True,
            'displayHeaderFooter': False,
            'paperWidth': 210 / 25.4,
            'paperHeight': 297 / 25.4,
            'marginTop': 0,
            'marginBottom': 0,
            'marginLeft': 0,
            'marginRight': 0,
        }
        if layout_options and layout_options.get('scale'):
            cdp_options['scale'] = max(0.1, min(2.0, float(layout_options['scale'])))

        try:
            from .browser_pool import browser_pool
            pdf_raw_data = browser_pool.render_html_to_pdf(str(document), print_options=cdp_options)
            reader = PdfReader(io.BytesIO(pdf_raw_data))
        except Exception as pool_err:
            logger.warning(f"Browser pool rendering failed ({pool_err}); falling back to one-shot browser.")
            browser_name, binary = find_browser()
            options = new_options(browser_name)
            if binary:
                options.binary_location = binary
            options.add_argument('--headless=new')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-first-run')
            driver = start_driver(browser_name, options)
            try:
                driver.set_page_load_timeout(30)
                driver.set_script_timeout(30)
                driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'media': 'print'})
                encoded = base64.b64encode(str(document).encode('utf-8')).decode('ascii')
                driver.get('data:text/html;charset=utf-8;base64,' + encoded)
                driver.execute_async_script('''
                    const done = arguments[arguments.length - 1];
                    Promise.all([document.fonts.ready, ...Array.from(document.images, img =>
                        img.complete ? Promise.resolve() : new Promise(resolve => {
                            img.onload = resolve; img.onerror = resolve;
                        }))]).then(() => done());
                ''')
                result = driver.execute_cdp_cmd('Page.printToPDF', cdp_options)
                reader = PdfReader(io.BytesIO(base64.b64decode(result['data'])))
            finally:
                driver.quit()

        if not reader.pages:
            raise ValueError('HTML rendering produced an empty PDF')
        writer = PdfWriter()
        writer.append_pages_from_reader(reader)
        if metadata:
            writer.add_metadata({
                '/Title': metadata.get('title', 'Document'),
                '/Author': metadata.get('author', 'PDF Generator'),
                '/Subject': metadata.get('subject', ''),
            })
        if output_path:
            with open(output_path, 'wb') as output:
                writer.write(output)
            return output_path
        stream = io.BytesIO()
        writer.write(stream)
        stream.seek(0)
        return stream

    def set_font_style(self, font='helvetica', size=11):
        self.font = font
        self.font_size = size
