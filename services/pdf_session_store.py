"""
PDF Generator Session Store and Runtime Directory Configuration.
Manages in-memory and disk-persisted session data for cover letter generation and preview.
"""

import base64
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

# Base Paths
PDF_GENERATOR_DIR = Path("pdf_generator").resolve()
PDF_GENERATOR_FRONTEND_DIR = PDF_GENERATOR_DIR / "frontend"
PDF_GENERATOR_SERVICES_DIR = PDF_GENERATOR_DIR / "services"
PDF_GENERATOR_RUNTIME_DIR = (Path("data") / "pdf_generator").resolve()
PDF_GENERATOR_UPLOAD_DIR = PDF_GENERATOR_RUNTIME_DIR / "uploads"
PDF_GENERATOR_TEMP_DIR = PDF_GENERATOR_RUNTIME_DIR / "temp"
PDF_GENERATOR_OUTPUT_DIR = PDF_GENERATOR_RUNTIME_DIR / "generated_pdfs"
EMAIL_CAMPAIGN_ASSET_DIR = (Path("data") / "campaign_assets").resolve()

# Ensure runtime directories exist
for _dir in [
    PDF_GENERATOR_RUNTIME_DIR,
    PDF_GENERATOR_UPLOAD_DIR,
    PDF_GENERATOR_TEMP_DIR,
    PDF_GENERATOR_OUTPUT_DIR,
    EMAIL_CAMPAIGN_ASSET_DIR,
]:
    _dir.mkdir(parents=True, exist_ok=True)

# Central in-memory PDF editor sessions
_pdf_sessions: Dict[str, Dict] = {}

# Backend services cache (ExcelService, PDFService, TemplateService)
_pdf_backend_services: Optional[Tuple[Any, Any, Any]] = None

PDF_LAYOUT_DEFAULTS = {
    "font_family": "Helvetica",
    "font_size_pt": 11,
    "line_height": 1.25,
    "top_margin_cm": 2.5,
    "bottom_margin_cm": 2.0,
    "left_margin_cm": 2.5,
    "right_margin_cm": 2.0,
    "include_header": False,
    "header_text": "",
    "include_footer": True,
    "footer_format": "Seite {page} von {total}",
    "include_fold_marks": False,
    "color_scheme": "standard",
    "primary_color": "#111827",
    "secondary_color": "#4B5563",
    "accent_color": "#2563EB",
    "design_background_path": "",
    "design_background_mode": "first_page",
    "design_background_opacity": 1.0,
}


def _load_pdf_backend_services():
    global _pdf_backend_services
    if _pdf_backend_services is not None:
        return _pdf_backend_services

    if not PDF_GENERATOR_SERVICES_DIR.exists():
        raise RuntimeError(
            f"Missing PDF generator services folder: {PDF_GENERATOR_SERVICES_DIR}"
        )

    try:
        from pdf_generator.services.excel_service import ExcelService
        from pdf_generator.services.pdf_service import PDFService
        from pdf_generator.services.template_service import TemplateService
    except Exception as exc:
        raise RuntimeError(
            f"Could not load PDF generator services from {PDF_GENERATOR_DIR}. ({exc})"
        )

    _pdf_backend_services = (
        ExcelService,
        PDFService,
        TemplateService,
    )
    return _pdf_backend_services


def _normalize_rows_for_pdf_session(rows: List[Dict]) -> Dict:
    if not rows:
        raise ValueError("No rows available")

    df = pd.DataFrame(rows).fillna("")
    if df.empty:
        raise ValueError("No rows available")

    df.columns = [str(c).strip() for c in df.columns]
    columns = [c for c in df.columns if c]
    if not columns:
        raise ValueError("No columns found")

    normalized_rows: List[Dict[str, str]] = []
    for _, row in df.iterrows():
        normalized_rows.append({col: str(row.get(col, "")).strip() for col in columns})

    return {
        "columns": columns,
        "rows": normalized_rows,
        "row_count": len(normalized_rows),
        "column_count": len(columns),
    }


def _create_pdf_session_from_rows(rows: List[Dict]) -> Dict:
    parsed = _normalize_rows_for_pdf_session(rows)
    session_id = str(uuid.uuid4())

    _pdf_sessions[session_id] = {
        "excel_data": parsed,
        "filepath": "",
        "columns": parsed["columns"],
        "rows": parsed["rows"],
        "template": "",
        "templates": [""],
        "active_template_index": 0,
        "filename_format": "{{Unternehmen}}",
        "design_pdf_path": None,
        "layout_options": dict(PDF_LAYOUT_DEFAULTS),
    }

    return {
        "success": True,
        "session_id": session_id,
        "columns": parsed["columns"],
        "row_count": len(parsed["rows"]),
        "preview": parsed["rows"][:3],
        "templates": [""],
        "active_template_index": 0,
        "filename_format": "{{Unternehmen}}",
        "layout_options": dict(PDF_LAYOUT_DEFAULTS),
    }


def _normalize_pdf_layout_options(options: Optional[Dict]) -> Dict:
    payload = dict(PDF_LAYOUT_DEFAULTS)
    if not isinstance(options, dict):
        return payload
    for key, default_value in PDF_LAYOUT_DEFAULTS.items():
        if key not in options:
            continue
        val = options[key]
        if isinstance(default_value, bool):
            payload[key] = bool(val)
        elif isinstance(default_value, (int, float)):
            try:
                payload[key] = float(val) if isinstance(default_value, float) else int(val)
            except (ValueError, TypeError):
                payload[key] = default_value
        else:
            payload[key] = str(val or "")
    return payload


def _read_binary_file_as_base64(path_value: str) -> Dict[str, str]:
    file_path = Path(str(path_value or "")).expanduser()
    if not file_path.exists() or not file_path.is_file():
        return {}

    try:
        payload = file_path.read_bytes()
    except OSError:
        return {}

    if not payload:
        return {}

    return {
        "filename": file_path.name,
        "content_b64": base64.b64encode(payload).decode("ascii"),
    }


def _restore_design_pdf_for_session(session_id: str, design_payload: Dict) -> str:
    if not isinstance(design_payload, dict):
        return ""

    encoded = str(design_payload.get("content_b64") or "").strip()
    if not encoded:
        return ""

    filename = str(design_payload.get("filename") or "design.pdf").strip() or "design.pdf"
    safe_suffix = Path(filename).suffix or ".pdf"
    target_path = PDF_GENERATOR_UPLOAD_DIR / secure_filename(f"{session_id}_design{safe_suffix}")
    try:
        target_path.write_bytes(base64.b64decode(encoded))
    except Exception:
        return ""
    return str(target_path)
