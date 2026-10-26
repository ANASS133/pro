"""
Background PDF templates generator for JobScout Anschreiben.
Generates and manages beautiful, professional A4 letterhead/stationery templates.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
from fpdf import FPDF

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "backgrounds"

BACKGROUND_TEMPLATES: List[Dict] = [
    {
        "id": "modern_indigo",
        "name": "Modern Indigo",
        "category": "Tech & Modern",
        "description": "Sleeker Indigoblau-Header mit feiner Akzentlinie, dezenten DIN 5008 Falzmarken und minimalistischer Fußzeile.",
        "primaryColor": "#4F46E5",
        "secondaryColor": "#818CF8",
        "recommendedMargins": {
            "font_size": 11,
            "line_height": 5,
            "margin_top": 36,
            "margin_left": 25,
            "margin_right": 20,
            "margin_bottom": 26,
            "text_width": 165,
            "text_height": 235,
        },
    },
    {
        "id": "executive_navy",
        "name": "Executive Navy & Gold",
        "category": "Management & Executive",
        "description": "Edles Mitternachtsblau mit champagnergoldener Kontrastleiste und klassischem Kanzlei-/Vorstands-Briefkopf.",
        "primaryColor": "#0F2439",
        "secondaryColor": "#D4AF37",
        "recommendedMargins": {
            "font_size": 11,
            "line_height": 5,
            "margin_top": 38,
            "margin_left": 25,
            "margin_right": 20,
            "margin_bottom": 28,
            "text_width": 165,
            "text_height": 230,
        },
    },
    {
        "id": "minimalist_swiss",
        "name": "Minimalist Swiss Emerald",
        "category": "Clean & Architektur",
        "description": "Ultra-cleanes Schweizer Design mit smaragdgrünem Akzentstreifen, feinen DIN 5008 Markierungen und dezentem Trenner.",
        "primaryColor": "#059669",
        "secondaryColor": "#34D399",
        "recommendedMargins": {
            "font_size": 11,
            "line_height": 5,
            "margin_top": 34,
            "margin_left": 25,
            "margin_right": 20,
            "margin_bottom": 24,
            "text_width": 165,
            "text_height": 238,
        },
    },
    {
        "id": "creative_teal",
        "name": "Creative Teal & Cyan",
        "category": "Kreativ & Start-up",
        "description": "Frisches Petrol- und Mint-Design mit modernem Dual-Tone-Footer, ideal für Agenturen und dynamische Rollen.",
        "primaryColor": "#0D9488",
        "secondaryColor": "#2DD4BF",
        "recommendedMargins": {
            "font_size": 11,
            "line_height": 5,
            "margin_top": 36,
            "margin_left": 25,
            "margin_right": 20,
            "margin_bottom": 26,
            "text_width": 165,
            "text_height": 235,
        },
    },
    {
        "id": "burgundy_elegance",
        "name": "Burgundy Elegance",
        "category": "Consulting & Finanzen",
        "description": "Tiefes Bordeaux-Rot mit warmer Roségold-Akzentlinie. Repräsentativ, souverän und zeitlos stilvoll.",
        "primaryColor": "#831843",
        "secondaryColor": "#FDA4AF",
        "recommendedMargins": {
            "font_size": 11,
            "line_height": 5,
            "margin_top": 36,
            "margin_left": 25,
            "margin_right": 20,
            "margin_bottom": 26,
            "text_width": 165,
            "text_height": 235,
        },
    },
    {
        "id": "slate_graphite",
        "name": "Slate Graphite ATS",
        "category": "Allrounder & Engineering",
        "description": "Dezente Schiefergrau-Optik mit maximalem Kontrast und 100 % ATS-Sicherheit für alle Branchen.",
        "primaryColor": "#1E293B",
        "secondaryColor": "#94A3B8",
        "recommendedMargins": {
            "font_size": 11,
            "line_height": 5,
            "margin_top": 32,
            "margin_left": 25,
            "margin_right": 20,
            "margin_bottom": 24,
            "text_width": 165,
            "text_height": 240,
        },
    },
]


def _hex_to_rgb(hex_code: str) -> tuple:
    s = hex_code.strip().lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _draw_din_marks(pdf: FPDF, x: float = 4.0, color: tuple = (203, 213, 225)):
    """Draw standard DIN 5008 folding and punch markers on the left edge."""
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.35)
    # Upper fold mark at 105 mm
    pdf.line(x, 105.0, x + 4.5, 105.0)
    # Punch mark (center) at 148.5 mm
    pdf.line(x, 148.5, x + 7.5, 148.5)
    # Lower fold mark at 210 mm
    pdf.line(x, 210.0, x + 4.5, 210.0)


def generate_modern_indigo_pdf(output_path: Path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()

    # Top Header Banner - Clean geometric styling without distracting titles
    p_rgb = _hex_to_rgb("#4338CA")
    s_rgb = _hex_to_rgb("#818CF8")
    pdf.set_fill_color(*p_rgb)
    pdf.rect(0, 0, 210, 14, style="F")

    pdf.set_fill_color(*s_rgb)
    pdf.rect(0, 14, 210, 2.0, style="F")

    # DIN marks
    _draw_din_marks(pdf, x=3.5, color=(203, 213, 225))

    # Footer Divider & Text
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.4)
    pdf.line(20, 274, 190, 274)

    pdf.set_text_color(148, 163, 184)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.text(78, 280, "Vertrauliche Bewerbungsunterlagen")

    # Bottom slim accent
    pdf.set_fill_color(*p_rgb)
    pdf.rect(0, 294, 210, 3, style="F")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def generate_executive_navy_pdf(output_path: Path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()

    navy_rgb = _hex_to_rgb("#0F2439")
    gold_rgb = _hex_to_rgb("#D4AF37")

    # Deep Navy Header - Clean corporate bar without text titles
    pdf.set_fill_color(*navy_rgb)
    pdf.rect(0, 0, 210, 15, style="F")

    # Gold Accent Line
    pdf.set_fill_color(*gold_rgb)
    pdf.rect(0, 15, 210, 1.8, style="F")

    # Left subtle pinstripe
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.3)
    pdf.line(14, 26, 14, 265)

    # DIN marks
    _draw_din_marks(pdf, x=3.5, color=(203, 213, 225))

    # Gold footer hairline
    pdf.set_draw_color(*gold_rgb)
    pdf.set_line_width(0.4)
    pdf.line(20, 273, 190, 273)

    # Deep Navy Footer Bar
    pdf.set_fill_color(*navy_rgb)
    pdf.rect(0, 281, 210, 16, style="F")

    pdf.set_text_color(*gold_rgb)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.text(76, 289, "Persoenlich & Vertraulich | Zur direkten Vorlage")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def generate_minimalist_swiss_pdf(output_path: Path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()

    emerald_rgb = _hex_to_rgb("#059669")
    mint_rgb = _hex_to_rgb("#34D399")
    slate_muted = _hex_to_rgb("#64748B")

    # Clean Top Emerald Accent Bar
    pdf.set_fill_color(*emerald_rgb)
    pdf.rect(0, 0, 210, 6, style="F")

    # Mint Accent Hairline
    pdf.set_fill_color(*mint_rgb)
    pdf.rect(0, 6, 210, 1.5, style="F")

    # Left Vertical Accent Tab
    pdf.set_fill_color(*emerald_rgb)
    pdf.rect(16, 15, 3.2, 14, style="F")

    # Subtle horizontal line under top section
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.4)
    pdf.line(24, 25, 195, 25)

    # DIN marks
    _draw_din_marks(pdf, x=3.5, color=(203, 213, 225))

    # Minimalist Footer
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.3)
    pdf.line(20, 276, 190, 276)

    pdf.set_text_color(*slate_muted)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.text(80, 283, "Dokumenten-Status: Vertraulich")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def generate_creative_teal_pdf(output_path: Path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()

    teal_rgb = _hex_to_rgb("#0D9488")
    cyan_rgb = _hex_to_rgb("#2DD4BF")
    dark_rgb = _hex_to_rgb("#0F172A")

    # Teal Header Banner - Clean without titles
    pdf.set_fill_color(*teal_rgb)
    pdf.rect(0, 0, 210, 14, style="F")

    # Cyan Accent Stripe
    pdf.set_fill_color(*cyan_rgb)
    pdf.rect(0, 14, 210, 2.2, style="F")

    # DIN marks
    _draw_din_marks(pdf, x=3.5, color=(203, 213, 225))

    # Dual-tone Footer Bar
    pdf.set_fill_color(*dark_rgb)
    pdf.rect(0, 285, 105, 12, style="F")
    pdf.set_fill_color(*teal_rgb)
    pdf.rect(105, 285, 105, 12, style="F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.text(82, 292, "Bewerbungsunterlagen | Modern & Digital")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def generate_burgundy_elegance_pdf(output_path: Path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()

    burgundy_rgb = _hex_to_rgb("#831843")
    rose_rgb = _hex_to_rgb("#FDA4AF")

    # Burgundy Header Bar - Pure color and accent line
    pdf.set_fill_color(*burgundy_rgb)
    pdf.rect(0, 0, 210, 14, style="F")

    # Rose Accent Strip
    pdf.set_fill_color(*rose_rgb)
    pdf.rect(0, 14, 210, 2.0, style="F")

    # DIN marks
    _draw_din_marks(pdf, x=3.5, color=(203, 213, 225))

    # Footer Hairline
    pdf.set_draw_color(*burgundy_rgb)
    pdf.set_line_width(0.4)
    pdf.line(20, 274, 190, 274)

    # Footer subtle bar
    pdf.set_fill_color(*burgundy_rgb)
    pdf.rect(0, 288, 210, 9, style="F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 7)
    pdf.text(82, 293.5, "Vertrauliche Bewerbungsunterlagen")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def generate_slate_graphite_pdf(output_path: Path):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()

    slate_rgb = _hex_to_rgb("#1E293B")
    silver_rgb = _hex_to_rgb("#94A3B8")

    # Slate Header Bar - Minimalist and ATS-optimized
    pdf.set_fill_color(*slate_rgb)
    pdf.rect(0, 0, 210, 12, style="F")

    # Silver line
    pdf.set_fill_color(*silver_rgb)
    pdf.rect(0, 12, 210, 1.5, style="F")

    # DIN marks
    _draw_din_marks(pdf, x=3.5, color=(203, 213, 225))

    # Footer line
    pdf.set_draw_color(203, 213, 225)
    pdf.set_line_width(0.35)
    pdf.line(20, 275, 190, 275)

    pdf.set_text_color(148, 163, 184)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.text(85, 281, "Vertrauliche Unterlagen")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


GENERATOR_MAP = {
    "modern_indigo": generate_modern_indigo_pdf,
    "executive_navy": generate_executive_navy_pdf,
    "minimalist_swiss": generate_minimalist_swiss_pdf,
    "creative_teal": generate_creative_teal_pdf,
    "burgundy_elegance": generate_burgundy_elegance_pdf,
    "slate_graphite": generate_slate_graphite_pdf,
}


def ensure_templates_generated(force: bool = False) -> None:
    """Ensure all background template PDF files exist on disk."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for template in BACKGROUND_TEMPLATES:
        t_id = template["id"]
        t_path = TEMPLATES_DIR / f"{t_id}.pdf"
        if force or not t_path.exists():
            generator = GENERATOR_MAP.get(t_id)
            if generator:
                generator(t_path)


def get_template_by_id(template_id: str) -> Optional[Dict]:
    for t in BACKGROUND_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


def get_template_pdf_path(template_id: str) -> Optional[Path]:
    ensure_templates_generated()
    t_path = TEMPLATES_DIR / f"{template_id}.pdf"
    if t_path.exists():
        return t_path
    return None
