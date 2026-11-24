"""
Cover Letter Studio & PDF Generator Blueprint.
Handles Cover Letter Studio workspace, PDF sessions, template management,
batch generation, Excel imports, and AI-powered Anschreiben generation/refinement.
"""

import copy
import io
import json
import logging
import os
import random
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from flask import Blueprint, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from services.pdf_session_store import (
    PDF_GENERATOR_FRONTEND_DIR,
    PDF_GENERATOR_OUTPUT_DIR,
    PDF_GENERATOR_RUNTIME_DIR,
    PDF_GENERATOR_TEMP_DIR,
    PDF_GENERATOR_UPLOAD_DIR,
    PDF_LAYOUT_DEFAULTS,
    _create_pdf_session_from_rows,
    _load_pdf_backend_services,
    _normalize_pdf_layout_options,
    _normalize_rows_for_pdf_session,
    _pdf_sessions,
    _read_binary_file_as_base64,
    _restore_design_pdf_for_session,
)
from services.ai_provider_manager import ai_manager
from services.cover_letter_engine import CoverLetterEngine

logger = logging.getLogger(__name__)

cover_letters_bp = Blueprint("cover_letters", __name__)


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _render_app_shell(initial_section: str = "create-anschreibens"):
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    return render_template(
        "app_shell.html",
        initial_section=initial_section,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
    )


def _has_meaningful_text(value: Any) -> bool:
    if not value:
        return False
    val_str = str(value).strip()
    return bool(re.search(r"[a-zA-Z0-9äöüÄÖÜß]", val_str))


def _normalize_pdf_base_name(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    clean = re.sub(r'[\\/*?:"<>|]', "", raw)
    clean = re.sub(r"\s+", "_", clean).strip("_.")
    return clean or fallback


def _sanitize_pdf_name(value: Any, fallback: str) -> str:
    return _normalize_pdf_base_name(value, str(fallback or "").strip() or "dokument")


def _extract_email_from_row(row: Dict) -> str:
    if not isinstance(row, dict):
        return ""
    for k in ["email", "e-mail", "E-Mail", "EMail", "recipient", "Empfänger"]:
        val = row.get(k)
        if val and "@" in str(val):
            return str(val).strip()
    return ""


def _extract_company_from_row(row: Dict) -> str:
    if not isinstance(row, dict):
        return ""
    for k in ["company", "Unternehmen", "Firma", "arbeitgeber", "arbeitsgeber"]:
        val = row.get(k)
        if val:
            return str(val).strip()
    return ""


def _is_valid_email(value: Any) -> bool:
    if not value:
        return False
    val = str(value).strip()
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", val))


def _build_job_dedupe_key(job: Dict) -> str:
    if not isinstance(job, dict):
        return f"invalid:{id(job)}"
    for id_field in ("refnr", "job_id", "reference", "id", "external_id"):
        val = job.get(id_field)
        if val:
            source = str(job.get("source") or "").strip().lower()
            return f"ref:{source}:{str(val).strip().lower()}"
    company = str(job.get("company") or "").strip().lower()
    title = str(job.get("title") or "").strip().lower()
    loc = str(job.get("city") or job.get("location") or "").strip().lower()
    start = str(job.get("start_date") or "").strip().lower()
    if company and title:
        return f"tuple:{company}|{title}|{loc}|{start}"
    url = str(job.get("apply_url") or job.get("form_link") or job.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"
    return f"raw:{hash(frozenset(str(k)+':'+str(v) for k,v in job.items() if isinstance(v, (str,int,float))))}"


def _prepare_download_jobs(jobs: List[Dict]) -> List[Dict]:
    from scraper.application_form_discovery import normalize_job_opportunity_row
    prepared = []
    seen = set()
    for j in jobs:
        if not isinstance(j, dict):
            continue
        row = normalize_job_opportunity_row(j)
        key = _build_job_dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        prepared.append(row)
    return prepared


def _build_pdf_autoload_session_payload(source: str = "latest") -> Tuple[Dict, int]:
    from services.search_state import search_cache
    jobs = search_cache.get("jobs", [])
    if not jobs:
        from services.search_state import _load_search_cache_from_disk
        persisted = _load_search_cache_from_disk()
        jobs = persisted.get("jobs", [])
    if not jobs:
        return {"error": "Keine gesammelten Stellen mit gültigen E-Mails gefunden."}, 400
    prepared = _prepare_download_jobs(jobs)
    payload = _create_pdf_session_from_rows(prepared)
    return payload, 200


def _build_pdf_campaign_editor_session_payload(campaign_id: str) -> Tuple[Dict, int]:
    normalized_id = str(campaign_id or "").strip()
    from services.campaign_store import campaign_store
    camp = campaign_store.get_campaign(normalized_id)
    if not camp:
        return {"error": f"Kampagne {campaign_id} nicht gefunden."}, 404
    rows = camp.get("rows") or []
    if not rows:
        return {"error": "Keine Empfänger in der Kampagne vorhanden."}, 400
    editor_rows = []
    for r in rows:
        if isinstance(r, dict):
            ctx = dict(r.get("context") or r)
            editor_rows.append({str(k): str(v or "") for k, v in ctx.items()})
    payload = _create_pdf_session_from_rows(editor_rows)
    return payload, 200


def _build_pdf_export_file_session_payload(filename: str, application_id: str = "") -> Tuple[Dict, int]:
    clean_fn = secure_filename(filename)
    path = Path("data") / "auto_extractions" / clean_fn
    if not path.exists():
        path = Path("data") / "exports" / clean_fn
    if not path.exists():
        return {"error": f"Export-Datei {clean_fn} nicht gefunden."}, 404
    try:
        if clean_fn.endswith(".csv"):
            df = pd.read_csv(str(path)).fillna("")
        else:
            df = pd.read_excel(str(path)).fillna("")
        rows = df.to_dict(orient="records")
        payload = _create_pdf_session_from_rows(rows)
        return payload, 200
    except Exception as exc:
        return {"error": f"Fehler beim Laden der Datei: {exc}"}, 500


def _build_pdf_application_session_payload(application_payload: Dict, application_id: str = "", source_label: str = "Supabase") -> Tuple[Dict, int]:
    row = {
        "Unternehmen": application_payload.get("company") or "Unternehmen",
        "Position": application_payload.get("position") or application_payload.get("job_title") or "Fachkraft",
        "Ort": application_payload.get("city") or application_payload.get("location") or "",
        "E-Mail": application_payload.get("email") or "",
        "Bewerber_Name": application_payload.get("full_name") or application_payload.get("applicant_name") or "",
    }
    payload = _create_pdf_session_from_rows([row])
    return payload, 200


def _list_auto_extraction_export_files() -> List[Dict[str, Any]]:
    files = []
    export_dirs = [Path("data") / "auto_extractions", Path("data") / "exports"]
    for ed in export_dirs:
        if not ed.exists():
            continue
        for p in ed.glob("*.*"):
            if p.suffix.lower() in [".xlsx", ".xls", ".csv"]:
                try:
                    stat = p.stat()
                    files.append({
                        "filename": p.name,
                        "size": stat.st_size,
                        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
                except OSError:
                    continue
    return files


# ---------------------------------------------------------------------------
# Cover Letter Studio Routes
# ---------------------------------------------------------------------------

@cover_letters_bp.route("/create-anschreibens")
def create_anschreibens():
    """Render the Cover Letter Studio directly inside the shared SPA shell."""
    return _render_app_shell("create-anschreibens")


@cover_letters_bp.route("/pdf")
def pdf_frontend_root():
    """Standalone fallback PDF generator UI."""
    if not (PDF_GENERATOR_FRONTEND_DIR / "index.html").exists():
        return render_template(
            "error.html",
            error=f"PDF generator frontend not found in {PDF_GENERATOR_FRONTEND_DIR}",
        )
    return send_from_directory(str(PDF_GENERATOR_FRONTEND_DIR), "index.html")


@cover_letters_bp.route("/pdf/<path:filename>")
def pdf_frontend_assets(filename):
    return send_from_directory(str(PDF_GENERATOR_FRONTEND_DIR), filename)


@cover_letters_bp.route("/api/campaign-anschreiben/<campaign_id>", methods=["GET"])
def load_campaign_anschreiben_editor(campaign_id: str):
    payload, status_code = _build_pdf_campaign_editor_session_payload(campaign_id)
    return jsonify(payload), status_code


@cover_letters_bp.route("/api/create-anschreibens/bootstrap", methods=["GET"])
def create_anschreibens_bootstrap_api():
    session_id_arg = (request.args.get("session_id") or "").strip()
    edit_campaign_id = (request.args.get("edit_campaign") or "").strip()
    autoload_source = (request.args.get("autoload") or "").strip()
    filename = (request.args.get("filename") or "").strip()
    application_id = (request.args.get("application_id") or "").strip()

    if session_id_arg and session_id_arg in _pdf_sessions:
        session_data = _pdf_sessions[session_id_arg]
        payload = {
            "session_id": session_id_arg,
            "columns": session_data.get("columns", []),
            "preview": session_data.get("rows", [])[:20],
            "row_count": len(session_data.get("rows", [])),
            "templates": session_data.get("templates", [""]),
            "active_template_index": session_data.get("active_template_index", 0),
            "filename_format": session_data.get("filename_format", "{{Unternehmen}}"),
            "layout_options": session_data.get("layout_options", {}),
            "client_id": session_data.get("client_id", ""),
            "client_name": session_data.get("client_name", ""),
        }
        return jsonify({"success": True, "mode": "direct_session", "session": payload})

    if edit_campaign_id:
        payload, status_code = _build_pdf_campaign_editor_session_payload(edit_campaign_id)
        if status_code != 200:
            return jsonify(payload), status_code
        return jsonify({"success": True, "mode": "edit_campaign", "session": payload})

    if autoload_source:
        payload, status_code = _build_pdf_autoload_session_payload(autoload_source)
        if status_code != 200:
            return jsonify(payload), status_code
        return jsonify({"success": True, "mode": "autoload", "session": payload})

    if filename:
        payload, status_code = _build_pdf_export_file_session_payload(filename, application_id=application_id)
        if status_code != 200:
            return jsonify(payload), status_code
        return jsonify({"success": True, "mode": "export_file", "session": payload})

    return jsonify({"success": True, "mode": "empty", "session": None})


@cover_letters_bp.route("/api/create-anschreibens/direct-jobs-bootstrap", methods=["POST"])
def create_anschreibens_direct_jobs_bootstrap_api():
    """
    Directly transfers selected job listings from Search to Cover Letter Studio
    without requiring manual export to Excel and re-upload.
    Links candidate profile data when client_id is provided.
    """
    data = request.get_json(silent=True) or {}
    raw_jobs = data.get("jobs") or []
    client_id = str(data.get("client_id") or "").strip()

    if not raw_jobs:
        return jsonify({"success": False, "error": "Keine Stellen zur Übertragung ausgewählt."}), 400

    prepared_jobs = _prepare_download_jobs(raw_jobs)
    if not prepared_jobs:
        prepared_jobs = []
        for j in raw_jobs:
            if isinstance(j, dict):
                prepared_jobs.append({
                    "Unternehmen": j.get("company") or j.get("Unternehmen") or "Unternehmen",
                    "Position": j.get("title") or j.get("Position") or j.get("Titel") or "Fachkraft",
                    "Titel": j.get("title") or j.get("Position") or j.get("Titel") or "Fachkraft",
                    "Ort": j.get("location") or j.get("city") or j.get("Ort") or "",
                    "E-Mail": j.get("email") or j.get("E-Mail") or "",
                    "EMail": j.get("email") or j.get("E-Mail") or "",
                    "Bewerbungslink": j.get("apply_url") or j.get("bewerbung_link") or j.get("url") or "",
                    "Quelle": j.get("source") or j.get("Quelle") or "Suche",
                })

    client_name = ""
    client_profile = None
    if client_id:
        from services.client_manager import client_manager
        client_profile = client_manager.get_client(client_id)
        if client_profile:
            applicant = client_profile.get("applicant", {})
            personal = applicant.get("personal", {})
            contact = applicant.get("contact", {})
            address = contact.get("address", {})
            prof = applicant.get("professional_profile", {})

            client_name = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
            applicant_street = f"{address.get('street', '')} {address.get('house_number', '')}".strip()
            applicant_city = f"{address.get('postal_code', '')} {address.get('city', '')}".strip()
            applicant_email = contact.get("email", "")
            applicant_phone = contact.get("phone_display") or contact.get("phone", "")
            applicant_title = prof.get("current_title") or prof.get("headline", "")

            for r in prepared_jobs:
                r["Bewerber_Name"] = client_name
                r["Bewerber_Strasse"] = applicant_street
                r["Bewerber_PLZ_Ort"] = applicant_city
                r["Bewerber_Email"] = applicant_email
                r["Bewerber_Telefon"] = applicant_phone
                r["Bewerber_Titel"] = applicant_title

    payload = _create_pdf_session_from_rows(prepared_jobs)
    session_id = payload["session_id"]

    if client_profile and client_name:
        default_tpl = (
            f"{{{{Bewerber_Name}}}}\n"
            f"{{{{Bewerber_Strasse}}}}\n"
            f"{{{{Bewerber_PLZ_Ort}}}}\n"
            f"{{{{Bewerber_Email}}}} | {{{{Bewerber_Telefon}}}}\n\n"
            f"{{{{Unternehmen}}}}\n"
            f"{{{{Ort}}}}\n\n"
            f"Bewerbung als {{{{Position}}}}\n\n"
            f"Sehr geehrte Damen und Herren,\n\n"
            f"mit großem Interesse bewerbe ich mich bei {{{{Unternehmen}}}} auf die offene Stelle als {{{{Position}}}} in {{{{Ort}}}}.\n\n"
            f"Als engagierter Kandidat bringe ich fundierte Fachkenntnisse und Begeisterung für diesen Aufgabenbereich mit. "
            f"Gerne möchte ich meine Fähigkeiten aktiv in Ihr Team einbringen und zum Erfolg Ihres Unternehmens beitragen.\n\n"
            f"Über die Gelegenheit zu einem persönlichen Kennenlernen freue ich mich sehr.\n\n"
            f"Mit freundlichen Grüßen\n\n"
            f"{{{{Bewerber_Name}}}}"
        )
        if session_id in _pdf_sessions:
            _pdf_sessions[session_id]["templates"] = [default_tpl]
            _pdf_sessions[session_id]["template"] = default_tpl
            _pdf_sessions[session_id]["client_id"] = client_id
            _pdf_sessions[session_id]["client_name"] = client_name
        payload["templates"] = [default_tpl]
        payload["template"] = default_tpl

    if session_id in _pdf_sessions:
        _pdf_sessions[session_id]["client_id"] = client_id
        _pdf_sessions[session_id]["client_name"] = client_name

    payload["client_id"] = client_id
    payload["client_name"] = client_name
    payload["row_count"] = len(prepared_jobs)

    return jsonify({
        "success": True,
        "session_id": session_id,
        "client_id": client_id,
        "client_name": client_name,
        "session": payload,
        "redirect_url": f"/create-anschreibens?session_id={session_id}",
    })


@cover_letters_bp.route("/api/create-anschreibens/exports", methods=["GET"])
def create_anschreibens_exports_api():
    return jsonify({
        "success": True,
        "files": _list_auto_extraction_export_files(),
        "updated_at": datetime.now().isoformat(),
    })


@cover_letters_bp.route("/api/create-anschreibens/firebase-bootstrap", methods=["POST"])
def create_anschreibens_firebase_bootstrap_api():
    data = request.get_json(silent=True) or {}
    application_payload = data.get("application") if isinstance(data.get("application"), dict) else {}
    application_id = str(data.get("application_id") or "").strip()

    payload, status_code = _build_pdf_application_session_payload(application_payload, application_id)
    return jsonify({"success": True, "mode": "firebase_application", "session": payload}), status_code


@cover_letters_bp.route("/api/create-anschreibens/application-bootstrap", methods=["POST"])
def create_anschreibens_application_bootstrap_api():
    data = request.get_json(silent=True) or {}
    application_payload = data.get("application") if isinstance(data.get("application"), dict) else {}
    application_id = str(data.get("application_id") or "").strip()
    filename = str(data.get("filename") or "").strip()
    source_label = str(data.get("source_label") or application_payload.get("source_label") or "Supabase").strip()

    if filename:
        payload, status_code = _build_pdf_export_file_session_payload(filename, application_id=application_id)
    else:
        payload, status_code = _build_pdf_application_session_payload(
            application_payload, application_id, source_label=source_label
        )
    return jsonify(payload), status_code


@cover_letters_bp.route("/api/create-anschreibens/sync-session-row", methods=["POST"])
def api_create_anschreibens_sync_session_row():
    """Synchronizes vacancy and candidate inputs into the active PDF session row."""
    try:
        data = request.get_json(silent=True) or {}
        session_id = str(data.get("session_id") or "").strip()
        row_index = int(data.get("row_index", 0))
        row_data = data.get("row_data") or {}

        if not session_id or session_id not in _pdf_sessions:
            return jsonify({"success": False, "error": "PDF session not found"}), 404

        session = _pdf_sessions[session_id]
        rows = session.setdefault("rows", [])
        if row_index < 0:
            return jsonify({"success": False, "error": "Invalid row_index"}), 400

        while len(rows) <= row_index:
            rows.append({})

        comp = str(data.get("company") or row_data.get("company") or row_data.get("Unternehmen") or "").strip()
        pos = str(data.get("position") or row_data.get("position") or row_data.get("Position") or "").strip()
        city = str(data.get("city") or row_data.get("city") or row_data.get("Ort") or "").strip()
        contact = str(data.get("contact_person") or row_data.get("contact_person") or row_data.get("Ansprechpartner") or "").strip()

        target_row = rows[row_index]
        if comp:
            target_row["company"] = comp
            target_row["Unternehmen"] = comp
            target_row["Firma"] = comp
            target_row["arbeitgeber"] = comp
        if pos:
            target_row["position"] = pos
            target_row["Position"] = pos
            target_row["title"] = pos
            target_row["job_title"] = pos
            target_row["stelle"] = pos
        if city:
            target_row["city"] = city
            target_row["Ort"] = city
            target_row["location"] = city
            target_row["standort"] = city
        if contact:
            target_row["contact_person"] = contact
            target_row["Ansprechpartner"] = contact
            target_row["ansprechpartner"] = contact

        for k, v in row_data.items():
            target_row[k] = v

        cols = session.setdefault("columns", [])
        for k in target_row.keys():
            if k not in cols:
                cols.append(k)

        return jsonify({
            "success": True,
            "session_id": session_id,
            "row_index": row_index,
            "updated_row": target_row
        })
    except Exception as exc:
        logger.error("api_sync_session_row error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@cover_letters_bp.route("/api/upload-excel", methods=["POST"])
def pdf_upload_excel():
    try:
        ExcelService, _, _ = _load_pdf_backend_services()
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400
        if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
            return jsonify({"error": "File must be one of: .xlsx, .xls, .csv"}), 400

        session_id = str(uuid.uuid4())
        filename = secure_filename(f"{session_id}_{file.filename}")
        filepath = PDF_GENERATOR_UPLOAD_DIR / filename
        file.save(str(filepath))

        excel_service = ExcelService()
        parsed = excel_service.parse_excel(str(filepath))

        _pdf_sessions[session_id] = {
            "excel_data": parsed,
            "filepath": str(filepath),
            "columns": parsed["columns"],
            "rows": parsed["rows"],
            "template": "",
            "templates": [""],
            "active_template_index": 0,
            "filename_format": "{{Unternehmen}}",
            "design_pdf_path": None,
            "layout_options": dict(PDF_LAYOUT_DEFAULTS),
        }

        return jsonify({
            "success": True,
            "session_id": session_id,
            "columns": parsed["columns"],
            "row_count": len(parsed["rows"]),
            "preview": parsed["rows"][:3],
            "templates": [""],
            "active_template_index": 0,
            "filename_format": "{{Unternehmen}}",
            "layout_options": dict(PDF_LAYOUT_DEFAULTS),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/load-collected-jobs", methods=["POST"])
def pdf_load_collected_jobs():
    try:
        data = request.get_json(silent=True) or {}
        payload, status_code = _build_pdf_autoload_session_payload(data.get("source", "latest"))
        return jsonify(payload), status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/save-template", methods=["POST"])
def pdf_save_template():
    try:
        _, _, TemplateService = _load_pdf_backend_services()
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        raw_templates = data.get("templates")
        if isinstance(raw_templates, list):
            templates = [str(item or "") for item in raw_templates]
        else:
            templates = [str(data.get("template", "") or "")]
        if not templates:
            templates = [""]
        active_template_index = int(data.get("active_template_index", 0) or 0)
        active_template_index = max(0, min(active_template_index, len(templates) - 1))

        if session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        _pdf_sessions[session_id]["template"] = templates[active_template_index]
        _pdf_sessions[session_id]["templates"] = templates
        _pdf_sessions[session_id]["active_template_index"] = active_template_index

        template_service = TemplateService()
        missing_placeholders = sorted(
            {
                placeholder
                for template in templates
                for placeholder in template_service.validate_placeholders(
                    template, _pdf_sessions[session_id]["columns"]
                )
            }
        )

        return jsonify({
            "success": True,
            "message": "Template saved successfully",
            "missing_placeholders": missing_placeholders,
            "template_count": len(templates),
            "active_template_index": active_template_index,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/upload-design-pdf", methods=["POST"])
def pdf_upload_design_pdf():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        session_id = request.form.get("session_id")
        if not session_id or session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "File must be PDF format (.pdf)"}), 400

        old_path = _pdf_sessions[session_id].get("design_pdf_path")
        if old_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

        filename = secure_filename(f"{session_id}_design.pdf")
        filepath = PDF_GENERATOR_UPLOAD_DIR / filename
        file.save(str(filepath))

        _pdf_sessions[session_id]["design_pdf_path"] = str(filepath)
        return jsonify({"success": True, "filename": filepath.name})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/pdf-background-templates", methods=["GET"])
def pdf_list_background_templates():
    try:
        from pdf_generator.services.background_templates import BACKGROUND_TEMPLATES, ensure_templates_generated
        ensure_templates_generated()
        return jsonify({"success": True, "templates": BACKGROUND_TEMPLATES})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/pdf-background-templates/<template_id>/pdf", methods=["GET"])
def pdf_get_background_template_pdf(template_id):
    try:
        from pdf_generator.services.background_templates import get_template_pdf_path
        path = get_template_pdf_path(template_id)
        if not path or not path.exists():
            return jsonify({"error": "Template not found"}), 404
        return send_file(str(path), mimetype="application/pdf", as_attachment=False, download_name=f"{template_id}.pdf")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/set-background-template", methods=["POST"])
def pdf_set_background_template():
    try:
        from pdf_generator.services.background_templates import get_template_by_id, get_template_pdf_path
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        template_id = data.get("template_id")

        if not session_id or session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        if not template_id:
            _pdf_sessions[session_id]["design_pdf_path"] = ""
            return jsonify({"success": True, "template_id": None})

        tpl_meta = get_template_by_id(template_id)
        if not tpl_meta:
            return jsonify({"error": f"Unknown template: {template_id}"}), 404

        source_path = get_template_pdf_path(template_id)
        if not source_path or not source_path.exists():
            return jsonify({"error": "Template file not found on disk"}), 404

        filename = secure_filename(f"{session_id}_{template_id}.pdf")
        target_path = PDF_GENERATOR_UPLOAD_DIR / filename
        shutil.copy2(str(source_path), str(target_path))

        _pdf_sessions[session_id]["design_pdf_path"] = str(target_path)
        return jsonify({"success": True, "template_id": template_id, "filename": filename})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/preview-pdf", methods=["POST"])
def pdf_preview_pdf():
    try:
        _, PDFService, TemplateService = _load_pdf_backend_services()
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        template = data.get("template")
        row_index = int(data.get("row_index", 0))
        layout_options = data.get("layout_options") or {}

        if session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        session_data = _pdf_sessions[session_id]
        if row_index >= len(session_data["rows"]):
            return jsonify({"error": "Row index out of range"}), 400

        row_data = session_data["rows"][row_index]
        template_service = TemplateService()
        effective_template = template if template is not None else session_data.get("template", "")
        filled_content = template_service.replace_placeholders(
            effective_template, row_data, session_data["columns"]
        )

        pdf_service = PDFService()
        pdf_filename = f"preview_{session_id}_{row_index}.pdf"
        pdf_path = PDF_GENERATOR_TEMP_DIR / pdf_filename

        session_layout = session_data.get("layout_options") or {}
        active_layout = {**session_layout, **layout_options}

        pdf_service.create_pdf(
            content=filled_content,
            output_path=str(pdf_path),
            metadata={"title": f"Preview - Row {row_index + 1}"},
            design_pdf_path=session_data.get("design_pdf_path"),
            layout_options=active_layout,
        )

        return send_file(
            str(pdf_path),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=pdf_filename,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/generate-pdfs", methods=["POST"])
def pdf_generate_pdfs():
    try:
        _, PDFService, TemplateService = _load_pdf_backend_services()
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        layout_options = data.get("layout_options") or {}

        if session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        session_data = _pdf_sessions[session_id]
        session_data["layout_options"] = _normalize_pdf_layout_options(layout_options)
        templates = [
            str(t or "")
            for t in (session_data.get("templates") or [session_data.get("template", "")])
        ]
        available_templates = [
            (idx, t) for idx, t in enumerate(templates) if t.strip()
        ]
        if not available_templates:
            return jsonify({"error": "No template saved"}), 400

        output_dir_name = f"pdfs_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:8]}"
        output_dir = PDF_GENERATOR_OUTPUT_DIR / output_dir_name
        output_dir.mkdir(parents=True, exist_ok=True)

        template_service = TemplateService()
        pdf_service = PDFService()

        generated_files = []
        generated_records = []
        used_names = set()
        generation_errors = []

        for idx, row_data in enumerate(session_data["rows"]):
            try:
                chosen_template_index, chosen_template = random.choice(available_templates)
                filled_content = template_service.replace_placeholders(
                    chosen_template, row_data, session_data["columns"]
                )
                if not _has_meaningful_text(filled_content):
                    generation_errors.append(
                        f"Zeile {idx + 1}: Anschreiben-Inhalt ist leer nach Platzhalter-Ersatz."
                    )
                    continue

                company_raw = _extract_company_from_row(row_data)
                if not company_raw:
                    generation_errors.append(
                        f"Zeile {idx + 1}: Firmenname fehlt. PDF wurde nicht erstellt."
                    )
                    continue

                base_name = _sanitize_pdf_name(company_raw, f"firma_{idx + 1}")
                filename = f"{base_name}.pdf"
                duplicate_counter = 2
                while filename in used_names:
                    filename = f"{base_name}_{duplicate_counter}.pdf"
                    duplicate_counter += 1
                used_names.add(filename)

                pdf_path = output_dir / filename
                pdf_service.create_pdf(
                    content=filled_content,
                    output_path=str(pdf_path),
                    metadata={
                        "title": f"Bewerbung - {base_name}",
                        "author": "PDF Generator",
                        "subject": "Bewerbung",
                    },
                    design_pdf_path=session_data.get("design_pdf_path"),
                    layout_options=session_data.get("layout_options") or {},
                )
                if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
                    generation_errors.append(
                        f"Zeile {idx + 1} ({company_raw}): PDF-Datei wurde nicht korrekt erstellt."
                    )
                    continue
                generated_files.append(str(pdf_path))

                # Save generated PDF to client dossier if client is active
                target_client_id = session_data.get("client_id") or data.get("client_id")
                if target_client_id:
                    try:
                        from services.client_manager import client_manager
                        with open(pdf_path, "rb") as pf:
                            client_manager.save_document(target_client_id, pf.read(), f"Anschreiben_{filename}")
                    except Exception as sync_exc:
                        logger.warning("Could not sync generated PDF to client %s: %s", target_client_id, sync_exc)

                generated_records.append({
                    "row_index": idx,
                    "pdf_path": str(pdf_path),
                    "filename": filename,
                    "recipient": _extract_email_from_row(row_data),
                    "company": company_raw,
                    "template_index": chosen_template_index,
                    "template_label": f"Variante {chosen_template_index + 1}",
                    "context": dict(row_data),
                })
            except Exception as row_exc:
                logger.error("Error generating PDF for row %s: %s", idx, row_exc)
                generation_errors.append(f"Zeile {idx + 1}: {row_exc}")

        if not generated_files:
            error_text = "No PDFs were generated"
            if generation_errors:
                error_text = f"{error_text}. {generation_errors[0]}"
            return jsonify({"error": error_text}), 500

        session_data["last_generated_output_dir"] = str(output_dir)
        session_data["generated_records"] = generated_records

        return jsonify({
            "success": True,
            "message": "PDFs generated in data/pdf_generator",
            "output_folder": str(output_dir),
            "count": len(generated_files),
            "transfer_ready": sum(
                1
                for item in generated_records
                if _is_valid_email(item.get("recipient"))
                and item.get("pdf_path")
                and os.path.exists(item.get("pdf_path"))
            ),
            "skipped": len(generation_errors),
            "errors": generation_errors[:20],
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/prepare-email-transfer", methods=["POST"])
def prepare_email_transfer():
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        if not session_id or session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        session_data = _pdf_sessions[session_id]
        records = session_data.get("generated_records", [])
        transfer_ready = [
            r for r in records
            if _is_valid_email(r.get("recipient"))
            and r.get("pdf_path")
            and os.path.exists(r.get("pdf_path"))
        ]
        return jsonify({
            "success": True,
            "session_id": session_id,
            "transfer_count": len(transfer_ready),
            "records": transfer_ready,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/update-filename-format", methods=["POST"])
def pdf_update_filename_format():
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        filename_format = data.get("filename_format")
        if not session_id or session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404
        _pdf_sessions[session_id]["filename_format"] = filename_format
        return jsonify({"success": True, "filename_format": filename_format})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@cover_letters_bp.route("/api/clear-session/<session_id>", methods=["DELETE"])
def pdf_clear_session(session_id):
    try:
        if session_id in _pdf_sessions:
            del _pdf_sessions[session_id]
        return jsonify({"success": True, "message": "Session cleared"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# AI Cover Letter Generation & Refinement
# ---------------------------------------------------------------------------

@cover_letters_bp.route("/api/extract-pdf-text", methods=["POST"])
def extract_pdf_text():
    try:
        import requests
        from pypdf import PdfReader

        data = request.get_json() or {}
        pdf_url = data.get("pdf_url")
        page_num = data.get("page", 1)

        if not pdf_url:
            return jsonify({"error": "No PDF URL provided"}), 400

        page_index = max(0, int(page_num) - 1)
        response = requests.get(pdf_url, timeout=15)
        response.raise_for_status()

        pdf_file = io.BytesIO(response.content)
        reader = PdfReader(pdf_file)

        if page_index >= len(reader.pages):
            return jsonify({"error": f"Page {page_num} does not exist (Total: {len(reader.pages)})"}), 400

        page = reader.pages[page_index]
        extracted_text = (page.extract_text() or "").strip()
        return jsonify({"text": extracted_text})

    except Exception as e:
        logger.error("Error extracting PDF text: %s", e)
        return jsonify({"error": f"Failed to extract text: {str(e)}"}), 500


_AI_TEMPLATIZE_SYSTEM_PROMPT = (
    "You are an expert HR template editor.\n"
    "Your task is to convert an extracted Anschreiben / motivation letter page into a reusable template.\n"
    "Preserve structure, insert placeholders from the list (e.g. {{company}}, {{city}}, {{anrede}} {{arbeitsgeber}}).\n"
    "Return only the final editable template text without code fences."
)


@cover_letters_bp.route("/api/ai-templatize", methods=["POST"])
def ai_templatize():
    """Convert extracted text into a template with placeholders."""
    try:
        data = request.get_json(silent=True) or {}
        raw_text = str(data.get("text") or "").strip()
        if not raw_text:
            return jsonify({"error": "Kein Text zum Verarbeiten vorhanden."}), 400

        placeholders = ["city", "company", "hauptberuf", "start_date", "arbeitsgeber", "anrede", "heutigenDatum"]
        placeholder_list = "\n".join(f"- {{{{{p}}}}}" for p in placeholders)
        user_prompt = (
            f"Available placeholders:\n{placeholder_list}\n\n"
            f"Extracted text:\n\"\"\"\n{raw_text}\n\"\"\"\n\n"
            f"Convert this text into an Anschreiben template with matching placeholders."
        )

        ai_res = ai_manager.complete(
            prompt=user_prompt,
            system_prompt=_AI_TEMPLATIZE_SYSTEM_PROMPT,
            max_output_tokens=700,
            temperature=0.2,
        )

        if not ai_res.get("success"):
            return jsonify({"error": f"KI-Verarbeitung fehlgeschlagen: {ai_res.get('error')}"}), 502

        return jsonify({
            "success": True,
            "text": str(ai_res.get("text") or "").strip(),
            "model": ai_res.get("model", "gpt-6-luna"),
            "usage": ai_res.get("usage", {}),
        })

    except Exception as exc:
        logger.error("AI templatize error: %s", exc)
        return jsonify({"error": f"KI-Verarbeitung fehlgeschlagen: {exc}"}), 500


@cover_letters_bp.route("/api/ai-status", methods=["GET"])
def api_ai_status():
    """Returns real-time status and active configuration of the AI engine."""
    provider = ai_manager.get_active_provider()
    model = ai_manager.get_active_model()
    is_configured = ai_manager.is_configured()

    return jsonify({
        "is_configured": is_configured,
        "primary_provider": provider,
        "active_model": model,
        "status": "connected" if is_configured else "offline",
        "description": f"AI Engine: {provider.upper()} ({model})",
    })


@cover_letters_bp.route("/api/ai-generate-anschreiben", methods=["POST"])
def api_ai_generate_anschreiben():
    """Generates an individualized German cover letter using CoverLetterEngine."""
    try:
        data = request.get_json(silent=True) or {}
        client_id = str(data.get("client_id") or "").strip()
        company = str(data.get("company") or "Unternehmen").strip()
        position = str(data.get("position") or "Auszubildender").strip()
        city = str(data.get("city") or "Deutschland").strip()
        contact_person = str(data.get("contact_person") or "").strip()
        job_description = str(data.get("job_description") or data.get("vacancy_text") or "").strip()
        mode = str(data.get("mode") or "ai").lower()

        from services.client_manager import client_manager
        client_data = {}
        if client_id:
            client_data = client_manager.get_client(client_id) or {}
            if not client_data:
                from services.onboarding_tracker import onboarding_tracker
                rec = onboarding_tracker.get_record(client_id)
                if rec and rec.get("client_id"):
                    client_data = client_manager.get_client(rec["client_id"]) or {}
            if not client_data:
                try:
                    from services.supabase_service import supabase_service
                    from services.onboarding_service import candidate_onboarding_service
                    sup_app = supabase_service.get_application(client_id)
                    if sup_app:
                        onb = candidate_onboarding_service.onboard_candidate(client_id)
                        actual_cid = onb.get("client_id")
                        if actual_cid:
                            client_data = client_manager.get_client(actual_cid) or {}
                except Exception:
                    pass

        # Template fallback mode if explicitly requested
        if mode == "template":
            applicant = client_data.get("applicant") or client_data
            personal = applicant.get("personal") or {}
            full_name = data.get("candidate_name") or personal.get("full_name") or "Bewerber"
            email = data.get("candidate_email") or applicant.get("contact", {}).get("email") or ""
            phone = data.get("candidate_phone") or applicant.get("contact", {}).get("phone_display") or ""
            city_cand = applicant.get("contact", {}).get("address", {}).get("city") or "Casablanca"
            country_cand = applicant.get("contact", {}).get("address", {}).get("country") or "Marokko"
            location_header = f"{city_cand}, {country_cand}"
            today_str = datetime.now().strftime("%d.%m.%Y")
            salutation = f"Sehr geehrte(r) {contact_person}," if contact_person else "Sehr geehrte Damen und Herren,"
            betreff = f"Bewerbung um einen Ausbildungsplatz als {position}" if "ausbildung" in position.lower() else f"Bewerbung als {position}"
            tpl_text = (
                f"{full_name}\n{location_header}\n{email} | {phone}\n\n"
                f"{company}\n{'z. H. ' + contact_person if contact_person else 'Personalabteilung'}\n{city}\n\n"
                f"{city_cand}, den {today_str}\n\n"
                f"{betreff}\n\n"
                f"{salutation}\n\n"
                f"gerne bewerbe ich mich bei {company} auf die ausgeschriebene Position als {position}.\n\n"
                f"Mit freundlichen Grüßen\n\n{full_name}"
            )
            return jsonify({
                "success": True,
                "text": tpl_text,
                "is_ai_generated": False,
                "engine_used": "deterministic_template",
                "model_used": "deterministic_template",
                "validation": {"quality_score": 75, "is_valid": True},
            })

        # Generate personalized letter via CoverLetterEngine
        candidate_overrides = {
            "candidate_name": data.get("candidate_name"),
            "candidate_email": data.get("candidate_email"),
            "candidate_phone": data.get("candidate_phone"),
            "candidate_address": data.get("candidate_address"),
            "skills": data.get("skills"),
        }

        result = CoverLetterEngine.generate_cover_letter(
            candidate_profile=client_data,
            company=company,
            position=position,
            city=city,
            contact_person=contact_person,
            job_description=job_description,
            candidate_overrides=candidate_overrides,
        )

        status_code = 200 if result.get("success") else 503
        return jsonify(result), status_code

    except Exception as exc:
        logger.error("api_ai_generate_anschreiben error: %s", exc)
        return jsonify({"success": False, "is_ai_generated": False, "generation_mode": "error", "error": str(exc)}), 500


@cover_letters_bp.route("/api/ai-refine-anschreiben", methods=["POST"])
def api_ai_refine_anschreiben():
    """Targeted refinement of cover letter text via CoverLetterEngine."""
    try:
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()
        action = str(data.get("action") or "improve").strip().lower()
        candidate_name = str(data.get("candidate_name") or "").strip()
        company = str(data.get("company") or "").strip()
        position = str(data.get("position") or "").strip()
        location_header = str(data.get("location_header") or "").strip()

        if not text:
            return jsonify({"success": False, "error": "Kein Text zur Überarbeitung übergeben."}), 400

        refined = CoverLetterEngine.refine_letter(
            existing_text=text,
            action=action,
            candidate_name=candidate_name,
            company=company,
            position=position,
            location_header=location_header,
        )

        status_code = 200 if refined.get("success") else 502
        return jsonify(refined), status_code

    except Exception as exc:
        logger.error("api_ai_refine_anschreiben error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
