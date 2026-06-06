import copy
import csv
import io
import base64
import html
import logging
import os
import threading
import time
import json
import smtplib
import re
import shutil
import uuid
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

import pandas as pd
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from email_sender import EmailSender
from scraper.enhanced_api_scraper import EnhancedJobScraper
from scraper.google_maps_scraper import GoogleMapsBusinessScraper
from scraper.working_email_extractor import WorkingEmailExtractor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-local")

CAPTCHA_USERID = os.getenv("TRUECAPTCHA_USERID", "").strip()
CAPTCHA_APIKEY = os.getenv("TRUECAPTCHA_APIKEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
SUPABASE_URL = os.getenv("VITE_SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
SUPABASE_ANON_KEY = os.getenv("VITE_SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))

if not CAPTCHA_USERID:
    raise RuntimeError("TRUECAPTCHA_USERID is not set")

if not CAPTCHA_APIKEY:
    raise RuntimeError("TRUECAPTCHA_APIKEY is not set")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY is not set")

status_lock = threading.Lock()
search_cache = {
    "jobs": [],
    "keyword": "",
    "location": "",
    "published_since": "all",
}

extraction_status = {
    "is_running": False,
    "stop_requested": False,
    "paused": False,
    "continue_requested": False,
    "current_index": 0,
    "total_jobs": 0,
    "captcha_needed": False,
    "captcha_solved": False,
    "jobs": [],
    "last_error": "",
}

auto_extraction_status = {
    "is_running": False,
    "stop_requested": False,
    "paused": False,
    "continue_requested": False,
    "current_index": 0,
    "total_jobs": 0,
    "emails_found": 0,
    "captchas_solved": 0,
    "failed": 0,
    "jobs": [],
    "last_error": "",
}

PDF_GENERATOR_DIR = Path("pdf_generator").resolve()
PDF_GENERATOR_FRONTEND_DIR = PDF_GENERATOR_DIR / "frontend"
PDF_GENERATOR_SERVICES_DIR = PDF_GENERATOR_DIR / "services"
PDF_GENERATOR_RUNTIME_DIR = (Path("data") / "pdf_generator").resolve()
PDF_GENERATOR_UPLOAD_DIR = PDF_GENERATOR_RUNTIME_DIR / "uploads"
PDF_GENERATOR_TEMP_DIR = PDF_GENERATOR_RUNTIME_DIR / "temp"
PDF_GENERATOR_OUTPUT_DIR = PDF_GENERATOR_RUNTIME_DIR / "generated_pdfs"
DATA_DIR = Path("data")
PROGRESS_DIR = DATA_DIR / "progress"
DOWNLOAD_EXPORT_DIR = DATA_DIR / "exports"

_pdf_backend_services = None
_pdf_sessions: Dict[str, Dict] = {}
_email_sender_default = None
_email_transfer_sessions: Dict[str, Dict] = {}
email_send_jobs_lock = threading.Lock()
email_send_jobs: Dict[str, Dict] = {}
parallel_scrape_jobs_lock = threading.Lock()
parallel_scrape_jobs: Dict[str, Dict] = {}
PARALLEL_EXPORT_DIR = Path("data") / "parallel_exports"
auto_extraction_jobs_lock = threading.Lock()
auto_extraction_jobs: Dict[str, Dict] = {}
ausbildungen_update_jobs_lock = threading.Lock()
ausbildungen_update_jobs: Dict[str, Dict] = {}
captcha_context_lock = threading.Lock()
captcha_context = {"scope": "", "job_id": ""}
AUTO_EXTRACTION_EXPORT_DIR = Path("data") / "auto_extraction_exports"
EMAIL_CAMPAIGN_ASSET_DIR = Path("data") / "email_campaign_assets"
google_maps_jobs_lock = threading.Lock()
google_maps_jobs: Dict[str, Dict] = {}
GOOGLE_MAPS_EXPORT_DIR = Path("data") / "google_maps_exports"

# Firebase configuration
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw",
    "authDomain": "clients-9d7fe.firebaseapp.com",
    "projectId": "clients-9d7fe",
    "storageBucket": "clients-9d7fe.firebasestorage.app",
    "messagingSenderId": "489647859812",
    "appId": "1:489647859812:web:6f0f06a20beef2ea6a9771",
}

_firebase_db = None

def _get_firebase_db():
    """Initialize and return Firebase Firestore database."""
    global _firebase_db
    if _firebase_db is not None:
        return _firebase_db
    
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        # Try to get default credentials or use service account
        try:
            cred = credentials.Certificate("firebase-service-account.json") if Path("firebase-service-account.json").exists() else credentials.ApplicationDefault()
        except Exception:
            # Fallback: initialize with config directly
            from firebase_admin import credentials
            cred = credentials.Certificate("firebase-service-account.json") if Path("firebase-service-account.json").exists() else credentials.ApplicationDefault()
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _firebase_db = firestore.client()
        return _firebase_db
    except Exception as e:
        logger.warning(f"Firebase initialization failed: {e}")
        return None

def _coerce_firebase_datetime(value):
    """Best-effort conversion for Firestore timestamps and legacy values."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    to_datetime = getattr(value, "to_datetime", None)
    if callable(to_datetime):
        try:
            return to_datetime()
        except Exception:
            pass

    seconds = getattr(value, "seconds", None)
    nanoseconds = getattr(value, "nanoseconds", None)
    if isinstance(seconds, (int, float)):
        try:
            if isinstance(nanoseconds, (int, float)):
                return datetime.fromtimestamp(float(seconds) + (float(nanoseconds) / 1_000_000_000))
            return datetime.fromtimestamp(float(seconds))
        except Exception:
            pass

    if isinstance(value, dict):
        raw_seconds = value.get("_seconds", value.get("seconds"))
        raw_nanos = value.get("_nanoseconds", value.get("nanoseconds", 0))
        if isinstance(raw_seconds, (int, float)):
            try:
                return datetime.fromtimestamp(float(raw_seconds) + (float(raw_nanos) / 1_000_000_000))
            except Exception:
                pass

        raw_timestamp = value.get("timestamp")
        if isinstance(raw_timestamp, str):
            try:
                return datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            except ValueError:
                pass

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return None

def _format_firebase_datetime(value) -> str:
    timestamp = _coerce_firebase_datetime(value)
    if timestamp is None:
        return "k. A."
    return timestamp.strftime("%d.%m.%Y %H:%M")

def _firebase_sort_timestamp(value) -> float:
    timestamp = _coerce_firebase_datetime(value)
    if timestamp is None:
        return 0.0
    try:
        return float(timestamp.timestamp())
    except Exception:
        return 0.0

def _normalize_firebase_application(document_id: str, data: Optional[Dict]) -> Dict:
    payload = dict(data or {})
    documents = payload.get("documents")
    if not isinstance(documents, list):
        documents = []
    created_at = _coerce_firebase_datetime(payload.get("createdAt"))

    payload["id"] = document_id
    payload["_source"] = "firebase"
    payload["source_label"] = "Firebase"
    payload["documents"] = documents
    payload["document_count"] = len(documents)
    payload["created_at_iso"] = created_at.isoformat() if created_at else ""
    payload["created_at_display"] = _format_firebase_datetime(created_at)
    payload["_sort_timestamp"] = _firebase_sort_timestamp(created_at)
    payload.pop("createdAt", None)
    return payload

def _get_firebase_applications():
    """Fetch all applications from Firebase Firestore."""
    try:
        db = _get_firebase_db()
        if db is None:
            return []

        docs = db.collection("applications").stream()

        applications = []
        for doc in docs:
            applications.append(_normalize_firebase_application(doc.id, doc.to_dict()))

        applications.sort(
            key=lambda item: float(item.get("_sort_timestamp") or 0.0),
            reverse=True,
        )
        return applications
    except Exception as e:
        logger.warning(f"Failed to fetch Firebase applications: {e}")
        return []


def _format_auto_export_domain_name(file_path: Path) -> str:
    stem = str(file_path.stem or "").strip()
    if not stem:
        return "unbekannt"

    parts = stem.split("_")
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        parts = parts[2:]
    if parts and re.fullmatch(r"[0-9a-fA-F]{8}", parts[-1]):
        parts = parts[:-1]

    normalized = " ".join(part for part in parts if part).strip().lower()
    if normalized.startswith("ausbildung als ausbildung "):
        normalized = "ausbildung als " + normalized[len("ausbildung als ausbildung "):]
    if normalized.startswith("ausbildungsplatz als ausbildungsplatz "):
        normalized = "ausbildungsplatz als " + normalized[len("ausbildungsplatz als ausbildungsplatz "):]
    return normalized or stem.replace("_", " ").strip().lower() or "unbekannt"


def _count_auto_export_rows(file_path: Path) -> Optional[int]:
    try:
        suffix = str(file_path.suffix or "").lower()
        if suffix == ".csv":
            return int(pd.read_csv(file_path).shape[0])
        if suffix in {".xlsx", ".xls"}:
            return int(pd.read_excel(file_path).shape[0])
    except Exception as exc:
        logger.warning("Could not count rows for auto extraction export %s: %s", file_path, exc)
    return None


def _list_auto_extraction_export_files() -> List[Dict]:
    exports: List[Dict] = []
    supported_suffixes = {".xlsx", ".xls", ".csv"}

    if not AUTO_EXTRACTION_EXPORT_DIR.exists():
        return exports

    for file_path in sorted(
        AUTO_EXTRACTION_EXPORT_DIR.iterdir(),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        if not file_path.is_file():
            continue
        if str(file_path.suffix or "").lower() not in supported_suffixes:
            continue

        row_count = _count_auto_export_rows(file_path)
        exports.append(
            {
                "filename": file_path.name,
                "domain_name": _format_auto_export_domain_name(file_path),
                "row_count": row_count,
                "row_count_display": row_count if row_count is not None else "k. A.",
                "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
                "size_kb": round(file_path.stat().st_size / 1024, 1),
            }
        )

    return exports


def _list_available_ausbildung_domains() -> List[str]:
    domains: List[str] = []
    seen: Set[str] = set()

    for item in _list_auto_extraction_export_files():
        domain_name = str(item.get("domain_name") or "").strip()
        if not domain_name or domain_name in seen:
            continue
        seen.add(domain_name)
        domains.append(domain_name)

    return domains


def _resolve_auto_extraction_export_path(filename: str) -> Optional[Path]:
    candidate_name = str(filename or "").strip()
    if not candidate_name:
        return None

    base_dir = AUTO_EXTRACTION_EXPORT_DIR.resolve()
    try:
        resolved = (base_dir / candidate_name).resolve()
    except Exception:
        return None

    try:
        resolved.relative_to(base_dir)
    except ValueError:
        return None

    return resolved if resolved.exists() and resolved.is_file() else None


def _load_spreadsheet_records(file_path: Path) -> List[Dict]:
    suffix = str(file_path.suffix or "").lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path, dtype=str)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(file_path, dtype=str)
    else:
        raise ValueError(f"Unsupported spreadsheet type: {file_path.suffix}")

    df = df.fillna("")
    rows: List[Dict] = []
    columns = [str(column).strip() for column in df.columns]
    for _, row in df.iterrows():
        record = {column: str(row.get(column, "")).strip() for column in columns if column}
        if any(record.values()):
            rows.append(record)
    return rows


def _write_spreadsheet_records(file_path: Path, records: List[Dict]) -> None:
    df = pd.DataFrame(records or [])
    suffix = str(file_path.suffix or "").lower()
    if suffix == ".csv":
        df.to_csv(file_path, index=False, encoding="utf-8")
        return
    if suffix in {".xlsx", ".xls"}:
        df.to_excel(file_path, index=False)
        return
    raise ValueError(f"Unsupported spreadsheet type: {file_path.suffix}")


def _merge_records_by_email(existing_rows: List[Dict], new_rows: List[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    seen_emails: Set[str] = set()

    for source_rows in (existing_rows or [], new_rows or []):
        for row in source_rows:
            email = _normalize_email((row or {}).get("email"))
            if not _is_valid_email(email):
                continue
            if email in seen_emails:
                continue
            seen_emails.add(email)
            normalized_row = dict(row or {})
            normalized_row["email"] = email
            merged.append(normalized_row)

    return merged


def _get_running_ausbildungen_update_for_file(filename: str) -> Optional[Dict]:
    target_name = str(filename or "").strip()
    if not target_name:
        return None
    with ausbildungen_update_jobs_lock:
        for job in ausbildungen_update_jobs.values():
            if (
                str(job.get("filename") or "").strip() == target_name
                and bool(job.get("is_running"))
            ):
                return dict(job)
    return None


def _create_ausbildungen_update_job(file_path: Path) -> Dict:
    existing_rows = _load_spreadsheet_records(file_path)
    domain_name = _format_auto_export_domain_name(file_path)
    existing_row_count = len(existing_rows)
    existing_email_count = len(_extract_valid_emails_from_records(existing_rows))
    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    payload = {
        "job_id": job_id,
        "filename": file_path.name,
        "file_path": str(file_path),
        "keyword": domain_name,
        "domain_name": domain_name,
        "phase": "queued",
        "is_running": False,
        "stop_requested": False,
        "paused": False,
        "continue_requested": False,
        "captcha_needed": False,
        "current_index": 0,
        "total_jobs": 0,
        "emails_found": 0,
        "captchas_solved": 0,
        "failed": 0,
        "duplicate_emails": 0,
        "new_rows_added": 0,
        "existing_rows": existing_row_count,
        "result_rows": existing_row_count,
        "last_error": "",
        "created_at": now,
        "updated_at": now,
        "finished_at": "",
    }

    with ausbildungen_update_jobs_lock:
        ausbildungen_update_jobs[job_id] = payload

    return dict(payload)


def _wait_for_continue_ausbildungen_update(job_id: str, error_message: str) -> bool:
    if not _set_ausbildungen_update_job(
        job_id,
        phase="captcha",
        paused=True,
        captcha_needed=True,
        continue_requested=False,
        last_error=error_message,
    ):
        return False

    _set_captcha_context("ausbildungen_update", job_id)

    while True:
        time.sleep(1)
        with ausbildungen_update_jobs_lock:
            job = ausbildungen_update_jobs.get(job_id)
            if not job:
                _clear_captcha_context("ausbildungen_update", job_id)
                return False

            if job.get("stop_requested") or not job.get("is_running"):
                job["paused"] = False
                job["captcha_needed"] = False
                job["updated_at"] = datetime.now().isoformat()
                _clear_captcha_context("ausbildungen_update", job_id)
                return False

            if job.get("continue_requested"):
                job["paused"] = False
                job["captcha_needed"] = False
                job["continue_requested"] = False
                job["last_error"] = ""
                job["updated_at"] = datetime.now().isoformat()
                _clear_captcha_context("ausbildungen_update", job_id)
                return True


def _set_ausbildungen_update_job(job_id: str, **kwargs) -> bool:
    with ausbildungen_update_jobs_lock:
        job = ausbildungen_update_jobs.get(job_id)
        if not job:
            return False
        job.update(kwargs)
        job["updated_at"] = datetime.now().isoformat()
        return True


def _set_captcha_context(scope: str, job_id: str = "") -> None:
    with captcha_context_lock:
        captcha_context["scope"] = str(scope or "").strip()
        captcha_context["job_id"] = str(job_id or "").strip()


def _get_captcha_context() -> Dict[str, str]:
    with captcha_context_lock:
        return {
            "scope": str(captcha_context.get("scope") or "").strip(),
            "job_id": str(captcha_context.get("job_id") or "").strip(),
        }


def _clear_captcha_context(scope: str = "", job_id: str = "") -> None:
    with captcha_context_lock:
        current_scope = str(captcha_context.get("scope") or "").strip()
        current_job_id = str(captcha_context.get("job_id") or "").strip()
        expected_scope = str(scope or "").strip()
        expected_job_id = str(job_id or "").strip()
        if expected_scope and current_scope != expected_scope:
            return
        if expected_job_id and current_job_id != expected_job_id:
            return
        captcha_context["scope"] = ""
        captcha_context["job_id"] = ""

for directory in (
    PDF_GENERATOR_RUNTIME_DIR,
    PDF_GENERATOR_UPLOAD_DIR,
    PDF_GENERATOR_TEMP_DIR,
    PDF_GENERATOR_OUTPUT_DIR,
    PROGRESS_DIR,
    DOWNLOAD_EXPORT_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)

PARALLEL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
AUTO_EXTRACTION_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
EMAIL_CAMPAIGN_ASSET_DIR.mkdir(parents=True, exist_ok=True)
GOOGLE_MAPS_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_JOBS = 8000
SEARCH_CACHE_FILE = Path("search_cache.json")
PUBLISHED_SINCE_MAP = {
    "all": None,
    "today": 1,
    "yesterday": 0,
    "1week": 7,
    "2weeks": 14,
    "4weeks": 28,
}
PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
NAME_PATTERN = r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'.-]+"
ARBEITGEBER_PATTERN = re.compile(
    rf"\b(?:Frau|Herr|Herrn)\s+{NAME_PATTERN}\b"
)
ARBEITGEBER_NAME_TOKEN_PATTERN = r"[^\W\d_][\w'.-]*"
ARBEITGEBER_PATTERN = re.compile(
    rf"\b(?:Frau|Herr|Herrn)\s+{ARBEITGEBER_NAME_TOKEN_PATTERN}\b",
    re.IGNORECASE,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
PDF_INVALID_FILENAME_CHARS_PATTERN = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
PDF_FILENAME_SPACE_PATTERN = re.compile(r"\s+")
PDF_FILENAME_DASH_PATTERN = re.compile(r"-{2,}")
WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
EXCLUDED_DOWNLOAD_FIELDS = {
    "postalcode",
    "jobtype",
    "url",
    "emailextracted",
    "reference",
}
EMAIL_TEMPLATE_VAR_PATTERN = PLACEHOLDER_PATTERN
EMAIL_CAMPAIGN_STORE_FILE = Path("email_campaigns.json")
EMAIL_CAMPAIGN_STORE_VERSION = 1
_email_campaign_store_lock = threading.Lock()
ONE_DOCUMENT_ACTIONS = {"replace", "add"}
PDF_LAYOUT_DEFAULTS = {
    "font_size": 11.0,
    "line_height": 5.0,
    "margin_top": 20.0,
    "margin_left": 20.0,
    "margin_right": 20.0,
    "margin_bottom": 20.0,
    "text_width": 170.0,
    "text_height": 257.0,
}


def _empty_email_campaign_store() -> Dict:
    return {"version": EMAIL_CAMPAIGN_STORE_VERSION, "campaigns": []}


def _coerce_positive_int(value) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_nonnegative_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _normalize_pdf_layout_options(layout_options) -> Dict[str, float]:
    if not isinstance(layout_options, dict):
        layout_options = {}

    normalized: Dict[str, float] = {}
    for key, default_value in PDF_LAYOUT_DEFAULTS.items():
        normalized[key] = _coerce_nonnegative_float(
            layout_options.get(key), default=float(default_value)
        )
    return normalized


def _normalize_campaign_anschreiben_metadata(anschreiben) -> Dict:
    if not isinstance(anschreiben, dict):
        anschreiben = {}

    raw_templates = anschreiben.get("templates")
    if isinstance(raw_templates, list):
        templates = [str(item or "") for item in raw_templates]
    else:
        templates = [str(anschreiben.get("template") or "")]
    if not templates:
        templates = [""]

    try:
        active_template_index = int(anschreiben.get("active_template_index") or 0)
    except (TypeError, ValueError):
        active_template_index = 0
    active_template_index = max(0, min(active_template_index, len(templates) - 1))

    return {
        "templates": templates,
        "active_template_index": active_template_index,
        "layout_options": _normalize_pdf_layout_options(
            anschreiben.get("layout_options") or {}
        ),
        "filename_format": str(anschreiben.get("filename_format") or "{{Unternehmen}}").strip()
        or "{{Unternehmen}}",
        "design_pdf_path": str(anschreiben.get("design_pdf_path") or "").strip(),
    }


def _normalize_published_since(value: str) -> str:
    key = str(value or "all").strip().lower()
    return key if key in PUBLISHED_SINCE_MAP else "all"


def _published_since_to_days(value: str) -> Optional[int]:
    return PUBLISHED_SINCE_MAP.get(_normalize_published_since(value))


def _serialize_campaign_attachments(
    attachments: Iterable[Tuple[str, bytes, str]],
) -> List[Dict[str, str]]:
    serialized = []
    for item in attachments or []:
        try:
            filename, data, mimetype = item
        except (TypeError, ValueError):
            continue
        if not filename or data is None:
            continue
        payload = data if isinstance(data, bytes) else bytes(data)
        serialized.append(
            {
                "filename": str(filename),
                "content_b64": base64.b64encode(payload).decode("ascii"),
                "mimetype": str(mimetype or "application/octet-stream"),
            }
        )
    return serialized


def _deserialize_campaign_attachments(stored_attachments: Iterable[Dict]) -> List[Tuple[str, bytes, str]]:
    attachments: List[Tuple[str, bytes, str]] = []
    for item in stored_attachments or []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "").strip()
        encoded = str(item.get("content_b64") or "").strip()
        mimetype = str(item.get("mimetype") or "application/octet-stream")
        if not filename or not encoded:
            continue
        try:
            data = base64.b64decode(encoded)
        except Exception:
            continue
        attachments.append((filename, data, mimetype))
    return attachments


def _normalize_campaign_attachments(attachments) -> List[Dict[str, str]]:
    if not attachments:
        return []
    if isinstance(attachments, list) and attachments and isinstance(attachments[0], dict):
        return _serialize_campaign_attachments(_deserialize_campaign_attachments(attachments))
    return _serialize_campaign_attachments(attachments)


def _serialize_single_campaign_attachment(
    attachment: Optional[Tuple[str, bytes, str]],
) -> Dict[str, str]:
    if not attachment:
        return {}
    items = _serialize_campaign_attachments([attachment])
    return items[0] if items else {}


def _deserialize_single_campaign_attachment(
    stored_attachment: Optional[Dict],
) -> Optional[Tuple[str, bytes, str]]:
    if not isinstance(stored_attachment, dict):
        return None
    items = _deserialize_campaign_attachments([stored_attachment])
    return items[0] if items else None


def _normalize_one_document_config(config) -> Dict:
    if not isinstance(config, dict):
        config = {}

    action = str(config.get("action") or "replace").strip().lower()
    if action not in ONE_DOCUMENT_ACTIONS:
        action = "replace"

    page = _coerce_positive_int(config.get("page")) or 1
    base_document = config.get("base_document")
    if isinstance(base_document, dict):
        base_document = _serialize_single_campaign_attachment(
            _deserialize_single_campaign_attachment(base_document)
        )
    else:
        base_document = {}

    return {
        "enabled": bool(config.get("enabled")),
        "page": page,
        "action": action,
        "base_document": base_document,
    }


def _campaign_has_saved_anschreiben(campaign: Dict) -> bool:
    anschreiben = _normalize_campaign_anschreiben_metadata(campaign.get("anschreiben") or {})
    return any(str(template or "").strip() for template in anschreiben.get("templates") or [])


def _normalize_email_campaign(campaign: Dict) -> Optional[Dict]:
    if not isinstance(campaign, dict):
        return None

    rows = campaign.get("rows")
    if not isinstance(rows, list):
        rows = []
    attachments = _normalize_campaign_attachments(campaign.get("attachments") or [])

    mode = str(campaign.get("mode") or "upload").strip().lower()
    if mode not in {"transfer", "upload"}:
        mode = "upload"

    recipient_column = str(campaign.get("recipient_column") or "email").strip() or "email"
    sent_indices_set: Set[int] = set()
    for raw_index in campaign.get("sent_indices") or []:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(rows):
            sent_indices_set.add(index)

    delay_seconds = _coerce_nonnegative_float(campaign.get("delay_seconds"), default=0.0)
    jitter_min_seconds = _coerce_nonnegative_float(
        campaign.get("jitter_min_seconds"), default=0.0
    )
    jitter_max_seconds = _coerce_nonnegative_float(
        campaign.get("jitter_max_seconds"), default=0.0
    )
    if jitter_max_seconds < jitter_min_seconds:
        jitter_max_seconds = jitter_min_seconds

    last_limit = _coerce_positive_int(campaign.get("last_limit"))
    batch_size = _coerce_positive_int(campaign.get("batch_size"))
    batch_pause_seconds = _coerce_nonnegative_float(
        campaign.get("batch_pause_seconds"), default=0.0
    )
    campaign_id = str(campaign.get("id") or uuid.uuid4())
    created_at = str(campaign.get("created_at") or datetime.now().isoformat())
    updated_at = str(campaign.get("updated_at") or created_at)
    anschreiben = _normalize_campaign_anschreiben_metadata(campaign.get("anschreiben") or {})
    one_document = _normalize_one_document_config(campaign.get("one_document") or {})
    default_name = (
        f"Anschreiben {campaign_id[:8]}"
        if mode == "transfer"
        else f"Email Template {campaign_id[:8]}"
    )
    full_name = str(campaign.get("full_name") or "").strip()
    display_name = full_name or str(campaign.get("name") or "").strip() or default_name

    return {
        "id": campaign_id,
        "name": display_name,
        "full_name": full_name,
        "mode": mode,
        "rows": rows,
        "attachments": attachments,
        "sent_indices": sorted(sent_indices_set),
        "sender_email": str(campaign.get("sender_email") or "").strip(),
        "app_password": str(campaign.get("app_password") or "").strip(),
        "recipient_column": recipient_column,
        "subject_template": str(campaign.get("subject_template") or ""),
        "body_template": str(campaign.get("body_template") or ""),
        "delay_seconds": delay_seconds,
        "jitter_min_seconds": jitter_min_seconds,
        "jitter_max_seconds": jitter_max_seconds,
        "last_limit": last_limit,
        "batch_size": batch_size,
        "batch_pause_seconds": batch_pause_seconds,
        "anschreiben": anschreiben,
        "one_document": one_document,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _load_email_campaign_store_unlocked() -> Dict:
    if not EMAIL_CAMPAIGN_STORE_FILE.exists():
        return _empty_email_campaign_store()

    try:
        with EMAIL_CAMPAIGN_STORE_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.warning("Could not load email campaign store: %s", exc)
        return _empty_email_campaign_store()

    if not isinstance(payload, dict):
        return _empty_email_campaign_store()

    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list):
        campaigns = []

    normalized_campaigns = []
    for campaign in campaigns:
        normalized = _normalize_email_campaign(campaign)
        if normalized:
            normalized_campaigns.append(normalized)

    return {
        "version": EMAIL_CAMPAIGN_STORE_VERSION,
        "campaigns": normalized_campaigns,
    }


def _save_email_campaign_store_unlocked(store: Dict) -> None:
    safe_store = {
        "version": EMAIL_CAMPAIGN_STORE_VERSION,
        "campaigns": store.get("campaigns", []),
    }
    temp_path = EMAIL_CAMPAIGN_STORE_FILE.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(safe_store, fh, ensure_ascii=False, indent=2)
    temp_path.replace(EMAIL_CAMPAIGN_STORE_FILE)


def _find_email_campaign_unlocked(store: Dict, campaign_id: str) -> Optional[Dict]:
    for campaign in store.get("campaigns", []):
        if str(campaign.get("id")) == campaign_id:
            return campaign
    return None


def _campaign_progress(campaign: Dict) -> Dict:
    rows = campaign.get("rows") or []
    sent_indices = campaign.get("sent_indices") or []
    sent_count = len(sent_indices)
    total = len(rows)
    remaining = max(total - sent_count, 0)
    return {"total": total, "sent": sent_count, "remaining": remaining}


def _list_saved_email_campaigns() -> List[Dict]:
    with _email_campaign_store_lock:
        store = _load_email_campaign_store_unlocked()

    summaries = []
    for campaign in store.get("campaigns", []):
        progress = _campaign_progress(campaign)
        summaries.append(
            {
                "id": campaign["id"],
                "name": campaign["name"],
                "full_name": campaign.get("full_name", ""),
                "mode": campaign["mode"],
                "sender_email": campaign.get("sender_email", ""),
                "attachment_count": len(campaign.get("attachments") or []),
                "has_anschreiben_data": _campaign_has_saved_anschreiben(campaign),
                "created_at": campaign.get("created_at", ""),
                "updated_at": campaign.get("updated_at", ""),
                "total_rows": progress["total"],
                "sent_rows": progress["sent"],
                "remaining_rows": progress["remaining"],
            }
        )

    summaries.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return summaries


def _get_saved_email_campaign(campaign_id: str) -> Optional[Dict]:
    with _email_campaign_store_lock:
        store = _load_email_campaign_store_unlocked()
        campaign = _find_email_campaign_unlocked(store, campaign_id)
        if not campaign:
            return None
        return copy.deepcopy(campaign)


def _delete_saved_email_campaign(campaign_id: str) -> bool:
    with _email_campaign_store_lock:
        store = _load_email_campaign_store_unlocked()
        campaigns = store.get("campaigns", [])
        original_count = len(campaigns)
        store["campaigns"] = [
            campaign for campaign in campaigns if str(campaign.get("id")) != campaign_id
        ]
        if len(store["campaigns"]) == original_count:
            return False
        _save_email_campaign_store_unlocked(store)
        return True


def _delete_saved_email_campaign_with_guard(campaign_id: str) -> Tuple[bool, str, int]:
    normalized_campaign_id = str(campaign_id or "").strip()
    if not normalized_campaign_id:
        return False, "Ungültige Vorlagen-ID.", 400

    if _get_active_email_send_job_for_campaign(normalized_campaign_id):
        return (
            False,
            "Die Vorlage kann während eines laufenden oder pausierten Versands nicht gelöscht werden.",
            409,
        )

    if not _delete_saved_email_campaign(normalized_campaign_id):
        return False, "Gespeicherte Vorlage nicht gefunden.", 404

    return True, "Gespeicherte Vorlage wurde gelöscht.", 200


def _save_new_email_campaign(
    *,
    mode: str,
    rows: List[Dict],
    sender_email: str,
    app_password: str,
    full_name: str,
    recipient_column: str,
    subject_template: str,
    body_template: str,
    delay_seconds: float,
    jitter_min_seconds: float,
    jitter_max_seconds: float,
    last_limit: Optional[int],
    batch_size: Optional[int],
    batch_pause_seconds: float,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    anschreiben: Optional[Dict] = None,
    one_document: Optional[Dict] = None,
    name: str = "",
) -> Dict:
    now = datetime.now().isoformat()
    campaign_id = str(uuid.uuid4())
    default_name = (
        f"Anschreiben {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        if mode == "transfer"
        else f"Email Template {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    campaign = _normalize_email_campaign(
        {
            "id": campaign_id,
            "name": (name or "").strip() or default_name,
            "full_name": full_name,
            "mode": mode,
            "rows": list(rows),
            "attachments": list(attachments or []),
            "sent_indices": [],
            "sender_email": sender_email,
            "app_password": app_password,
            "recipient_column": recipient_column,
            "subject_template": subject_template,
            "body_template": body_template,
            "delay_seconds": delay_seconds,
            "jitter_min_seconds": jitter_min_seconds,
            "jitter_max_seconds": jitter_max_seconds,
            "last_limit": last_limit,
            "batch_size": batch_size,
            "batch_pause_seconds": batch_pause_seconds,
            "anschreiben": anschreiben or {},
            "one_document": one_document or {},
            "created_at": now,
            "updated_at": now,
        }
    )
    if not campaign:
        raise ValueError("Failed to create campaign payload")

    with _email_campaign_store_lock:
        store = _load_email_campaign_store_unlocked()
        store.setdefault("campaigns", []).append(campaign)
        _save_email_campaign_store_unlocked(store)

    return copy.deepcopy(campaign)


def _update_saved_email_campaign(campaign: Dict) -> Dict:
    normalized = _normalize_email_campaign(campaign)
    if not normalized:
        raise ValueError("Invalid campaign payload")

    with _email_campaign_store_lock:
        store = _load_email_campaign_store_unlocked()
        existing = _find_email_campaign_unlocked(store, normalized["id"])
        if not existing:
            raise ValueError("Campaign not found")

        existing.clear()
        existing.update(normalized)
        _save_email_campaign_store_unlocked(store)

    return copy.deepcopy(normalized)


def _build_send_page_campaign_info(campaign: Dict) -> Dict:
    progress = _campaign_progress(campaign)
    sent_set = set(campaign.get("sent_indices") or [])
    rows = campaign.get("rows") or []
    preview = []
    recipient_column = campaign.get("recipient_column") or "email"
    one_document = _normalize_one_document_config(campaign.get("one_document") or {})
    base_document = one_document.get("base_document") if isinstance(one_document, dict) else {}

    for idx, row in enumerate(rows):
        if idx in sent_set:
            continue

        if campaign.get("mode") == "transfer":
            context = row.get("context") or {}
            recipient = _normalize_email(row.get("recipient"))
            company = str(row.get("company") or _extract_company_from_row(context) or "").strip()
            filename = str(row.get("filename") or Path(str(row.get("pdf_path") or "")).name)
        else:
            context = row if isinstance(row, dict) else {}
            recipient = _normalize_email(context.get(recipient_column))
            company = _extract_company_from_row(context)
            filename = ""

        preview.append(
            {
                "row_index": idx + 1,
                "recipient": recipient or "N/A",
                "company": company or "N/A",
                "filename": filename or "N/A",
            }
        )
        if len(preview) >= 5:
            break

    return {
        "id": campaign["id"],
        "name": campaign["name"],
        "full_name": campaign.get("full_name", ""),
        "mode": campaign.get("mode", "upload"),
        "sender_email": campaign.get("sender_email", ""),
        "app_password": campaign.get("app_password", ""),
        "attachments": [
            {"filename": item.get("filename", ""), "mimetype": item.get("mimetype", "")}
            for item in (campaign.get("attachments") or [])
        ],
        "recipient_column": campaign.get("recipient_column", "email"),
        "subject_template": campaign.get("subject_template", ""),
        "body_template": campaign.get("body_template", ""),
        "delay_seconds": campaign.get("delay_seconds", 0),
        "jitter_min_seconds": campaign.get("jitter_min_seconds", 0),
        "jitter_max_seconds": campaign.get("jitter_max_seconds", 0),
        "last_limit": campaign.get("last_limit"),
        "batch_size": campaign.get("batch_size"),
        "batch_pause_seconds": campaign.get("batch_pause_seconds", 0),
        "one_document": {
            "enabled": bool(one_document.get("enabled")),
            "page": one_document.get("page") or 1,
            "action": one_document.get("action") or "replace",
            "has_base_document": bool(base_document),
            "base_filename": str((base_document or {}).get("filename") or ""),
        },
        "total_rows": progress["total"],
        "sent_rows": progress["sent"],
        "remaining_rows": progress["remaining"],
        "preview": preview,
        "created_at": campaign.get("created_at", ""),
        "updated_at": campaign.get("updated_at", ""),
    }


def _normalize_email(value) -> str:
    if not value:
        return ""
    return str(value).strip().lower()


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_rendered_text(value) -> str:
    text = html.unescape(str(value or ""))
    text = PLACEHOLDER_PATTERN.sub(" ", text)
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = PDF_FILENAME_SPACE_PATTERN.sub(" ", text).strip()
    return text


def _has_meaningful_text(value) -> bool:
    normalized = _normalize_rendered_text(value)
    return any(ch.isalnum() for ch in normalized)


def _normalize_pdf_base_name(value, fallback: str) -> str:
    fallback_name = str(fallback or "").strip() or "dokument"
    candidate = str(value or "").strip()
    candidate = PDF_INVALID_FILENAME_CHARS_PATTERN.sub("-", candidate)
    candidate = PDF_FILENAME_DASH_PATTERN.sub("-", candidate)
    candidate = PDF_FILENAME_SPACE_PATTERN.sub(" ", candidate).strip()
    candidate = candidate.rstrip(". ")

    if not candidate:
        candidate = fallback_name

    if Path(candidate).stem.upper() in WINDOWS_RESERVED_FILENAMES:
        candidate = f"{candidate}_"

    if len(candidate) > 180:
        candidate = candidate[:180].rstrip(". ")

    candidate = candidate.strip()
    if not candidate:
        candidate = fallback_name

    return candidate


def _extract_email_from_row(row: Dict) -> str:
    candidates = {"email", "emails", "emailaddress", "e-mail", "mail", "recipient", "to"}
    for key, value in (row or {}).items():
        if _normalize_field_name(key) in candidates:
            email = _normalize_email(value)
            if _is_valid_email(email):
                return email
    return ""


def _extract_company_from_row(row: Dict) -> str:
    preferred_keys = {
        "company",
        "companyname",
        "unternehmen",
        "unternehmenname",
        "firma",
        "firmenname",
    }
    fallback_keys = {
        "arbeitgeber",
        "arbeitgebername",
        "betrieb",
        "betriebname",
    }

    for key, value in (row or {}).items():
        if _normalize_field_name(key) in preferred_keys:
            text = str(value or "").strip()
            if text:
                return text

    for key, value in (row or {}).items():
        if _normalize_field_name(key) in fallback_keys:
            text = str(value or "").strip()
            if text:
                return text

    for key, value in (row or {}).items():
        normalized_key = _normalize_field_name(key)
        if any(token in normalized_key for token in ("company", "unternehmen", "firma", "arbeitgeber")):
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _candidate_personalized_pdf_paths(row: Dict) -> List[Tuple[str, str]]:
    path_keys = {
        "pdfpath",
        "pdf",
        "pdfdatei",
        "attachment",
        "attachmentpath",
        "anschreiben",
        "anschreibenpdf",
        "anschreibenpath",
        "anschreibenpdfpath",
        "coverletter",
        "coverletterpdf",
        "coverletterpath",
        "coverpdf",
        "documentpdf",
    }
    candidates: List[Tuple[str, str]] = []
    for key, value in (row or {}).items():
        normalized_key = _normalize_field_name(key)
        if normalized_key not in path_keys and "pdfpath" not in normalized_key:
            continue
        candidate = str(value or "").strip().strip('"')
        if candidate:
            candidates.append((str(key), candidate))
    return candidates


def _load_personalized_pdf_from_row(
    row: Dict,
    row_index: int,
    *,
    default_filename: str = "",
) -> Tuple[Optional[Tuple[str, bytes, str]], str]:
    row_payload = row if isinstance(row, dict) else {}
    context = row_payload.get("context") if isinstance(row_payload.get("context"), dict) else {}
    candidates = _candidate_personalized_pdf_paths(row_payload)
    candidates.extend(_candidate_personalized_pdf_paths(context))

    for _source_key, raw_path in candidates:
        pdf_path = Path(raw_path).expanduser()
        if not pdf_path.exists() and not pdf_path.is_absolute():
            pdf_path = Path.cwd() / pdf_path
        if not pdf_path.exists() or not pdf_path.is_file():
            continue
        if pdf_path.suffix.lower() != ".pdf":
            continue
        try:
            pdf_bytes = pdf_path.read_bytes()
        except OSError as exc:
            return None, f"Zeile {row_index + 1}: Anschreiben-PDF konnte nicht gelesen werden ({exc})"
        if not pdf_bytes:
            return None, f"Zeile {row_index + 1}: Anschreiben-PDF ist leer"
        filename = default_filename or str(row_payload.get("filename") or pdf_path.name).strip()
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        return (filename, pdf_bytes, "application/pdf"), ""

    return (
        None,
        (
            f"Zeile {row_index + 1}: One Document Mode braucht pro Empfänger ein "
            "personalisiertes Anschreiben-PDF (Transfer-Zeile oder PDF-Pfad-Spalte)."
        ),
    )


def _one_document_row_filename(base_filename: str, row: Dict, row_index: int) -> str:
    row_payload = row if isinstance(row, dict) else {}
    context = row_payload.get("context") if isinstance(row_payload.get("context"), dict) else row_payload
    company = str(row_payload.get("company") or _extract_company_from_row(context) or "").strip()
    recipient = _normalize_email(row_payload.get("recipient") or _extract_email_from_row(context))
    base_stem = _normalize_pdf_base_name(Path(str(base_filename or "document.pdf")).stem, "document")
    row_stem = _sanitize_pdf_name(company or recipient or "", f"empfaenger_{row_index + 1}")
    return f"{base_stem}_{row_stem}.pdf"


def _compose_one_document_pdf(
    *,
    base_pdf_bytes: bytes,
    personalized_pdf_bytes: bytes,
    page_number: int,
    action: str,
) -> bytes:
    from pypdf import PdfReader, PdfWriter

    normalized_action = str(action or "replace").strip().lower()
    if normalized_action not in ONE_DOCUMENT_ACTIONS:
        raise ValueError("One Document Mode Aktion muss Replace oder Add sein")

    target_page = _coerce_positive_int(page_number)
    if not target_page:
        raise ValueError("One Document Mode Seite muss groesser als 0 sein")

    try:
        base_reader = PdfReader(io.BytesIO(base_pdf_bytes))
        personalized_reader = PdfReader(io.BytesIO(personalized_pdf_bytes))
    except Exception as exc:
        raise ValueError(f"PDF konnte nicht gelesen werden: {exc}") from exc

    base_page_count = len(base_reader.pages)
    personalized_page_count = len(personalized_reader.pages)
    if base_page_count <= 0:
        raise ValueError("Basis-Dokument hat keine Seiten")
    if personalized_page_count <= 0:
        raise ValueError("Anschreiben-PDF hat keine Seiten")

    target_index = target_page - 1
    if normalized_action == "replace" and target_index >= base_page_count:
        raise ValueError(
            f"Replace-Seite {target_page} existiert nicht im Basis-Dokument ({base_page_count} Seiten)"
        )
    if normalized_action == "add" and target_index > base_page_count:
        raise ValueError(
            f"Add-Seite {target_page} liegt ausserhalb des Basis-Dokuments ({base_page_count} Seiten)"
        )

    writer = PdfWriter()
    inserted = False
    for page_index, base_page in enumerate(base_reader.pages):
        if page_index == target_index:
            for personalized_page in personalized_reader.pages:
                writer.add_page(personalized_page)
            inserted = True
            if normalized_action == "replace":
                continue
        writer.add_page(base_page)

    if normalized_action == "add" and not inserted:
        for personalized_page in personalized_reader.pages:
            writer.add_page(personalized_page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _load_email_sender_class():
    return EmailSender


def _get_email_sender_instance(sender_email: str, app_password: str):
    email_sender_cls = _load_email_sender_class()
    sender_email = (sender_email or "").strip()
    app_password = (app_password or "").strip()

    if sender_email and app_password:
        return email_sender_cls(sender_email=sender_email, password=app_password)

    global _email_sender_default
    if _email_sender_default is None:
        _email_sender_default = email_sender_cls()
    return _email_sender_default


def _render_email_template_with_row(template_text: str, row: Dict) -> str:
    row_data = row if isinstance(row, dict) else {}
    exact_lookup: Dict[str, object] = {}
    lower_lookup: Dict[str, object] = {}
    normalized_lookup: Dict[str, object] = {}

    for raw_key, raw_value in row_data.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        exact_lookup[key] = raw_value
        lower_lookup[key.lower()] = raw_value
        normalized_lookup[_normalize_field_name(key)] = raw_value

    def _replace(match):
        key = str(match.group(1) or "").strip()
        value = exact_lookup.get(key)
        if value is None and key.lower() in lower_lookup:
            value = lower_lookup[key.lower()]
        if value is None:
            value = normalized_lookup.get(_normalize_field_name(key), "")
        return "" if value is None else str(value)

    return EMAIL_TEMPLATE_VAR_PATTERN.sub(_replace, template_text or "")


def _parse_csv_rows(file_bytes: bytes) -> List[Dict]:
    text = ""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: List[Dict] = []
    for raw_row in reader:
        row: Dict[str, str] = {}
        for key, value in (raw_row or {}).items():
            if key is None:
                continue
            row[str(key).strip()] = "" if value is None else str(value).strip()
        if any(row.values()):
            rows.append(row)
    return rows


def _parse_excel_rows(file_bytes: bytes) -> List[Dict]:
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not read Excel file: {exc}")

    df = df.fillna("")
    rows: List[Dict] = []
    columns = [str(c).strip() for c in df.columns]
    for _, row in df.iterrows():
        record = {col: str(row.get(col, "")).strip() for col in columns if col}
        if any(record.values()):
            rows.append(record)
    return rows


def _load_bulk_rows_from_upload(file_storage) -> List[Dict]:
    if not file_storage or not file_storage.filename:
        raise ValueError("Please upload a CSV or Excel file")

    ext = Path(file_storage.filename).suffix.lower()
    file_bytes = file_storage.read()
    if not file_bytes:
        raise ValueError("Uploaded data file is empty")

    if ext == ".csv":
        return _parse_csv_rows(file_bytes)
    if ext in {".xlsx", ".xlsm", ".xltx", ".xltm", ".xls"}:
        return _parse_excel_rows(file_bytes)

    raise ValueError("Unsupported file type. Use .csv or .xlsx")


def _parse_uploaded_attachments(files) -> List[Tuple[str, bytes, str]]:
    attachments = []
    for file_item in files:
        if not file_item or not file_item.filename:
            continue
        data = file_item.read()
        if not data:
            continue
        attachments.append(
            (file_item.filename, data, file_item.mimetype or "application/octet-stream")
        )
    return attachments


def _parse_uploaded_pdf_attachment(file_storage, label: str) -> Optional[Tuple[str, bytes, str]]:
    if not file_storage or not file_storage.filename:
        return None

    filename = str(file_storage.filename or "").strip()
    if Path(filename).suffix.lower() != ".pdf":
        raise ValueError(f"{label} muss eine PDF-Datei sein")

    data = file_storage.read()
    if not data:
        raise ValueError(f"{label} ist leer")

    return (filename, data, file_storage.mimetype or "application/pdf")


def _extract_valid_emails_from_records(records: Iterable[Dict]) -> Set[str]:
    emails: Set[str] = set()
    for job in records:
        email = _normalize_email(job.get("email"))
        if email and "@" in email and not email.startswith("error:") and email != "captcha_failed":
            emails.add(email)
    return emails


def _is_valid_email(value) -> bool:
    email = _normalize_email(value)
    return bool(email and "@" in email and not email.startswith("error:") and email != "captcha_failed")


def _normalize_arbeitsgeber_value(value: str) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw:
        return ""

    match = ARBEITGEBER_PATTERN.search(raw)
    if not match:
        return raw

    return re.sub(r"\s+", " ", match.group(0)).strip().lower()


def _extract_arbeitsgeber_from_text(value: str) -> str:
    if not value:
        return ""
    match = ARBEITGEBER_PATTERN.search(value)
    return _normalize_arbeitsgeber_value(match.group(0) if match else "")


def _build_anrede(arbeitsgeber: str) -> str:
    contact = str(arbeitsgeber or "").strip().lower()
    if contact.startswith("herr") or contact.startswith("herrn"):
        return "Sehr geehrter"
    if contact.startswith("frau"):
        return "Sehr geehrte"
    return "Sehr geehrte Damen und Herren"


def _prepare_download_jobs(jobs: Iterable[Dict]) -> List[Dict]:
    filtered: List[Dict] = []
    seen_emails: Set[str] = set()

    for job in jobs:
        raw_email = (job or {}).get("email")
        normalized_email = _normalize_email(raw_email)
        if not _is_valid_email(normalized_email):
            continue
        if normalized_email in seen_emails:
            continue
        seen_emails.add(normalized_email)

        row = dict(job or {})
        row["email"] = normalized_email

        arbeitsgeber = str(row.get("arbeitsgeber") or "").strip()
        if not arbeitsgeber:
            arbeitsgeber = _extract_arbeitsgeber_from_text(str(row.get("company") or ""))
        arbeitsgeber = _normalize_arbeitsgeber_value(arbeitsgeber)
        row["arbeitsgeber"] = arbeitsgeber
        row["anrede"] = _build_anrede(arbeitsgeber)
        cleaned_row = {
            key: value
            for key, value in row.items()
            if _normalize_field_name(key) not in EXCLUDED_DOWNLOAD_FIELDS
        }
        filtered.append(cleaned_row)

    return filtered


def _load_previously_collected_emails() -> Set[str]:
    known: Set[str] = set()
    candidates = [
        DOWNLOAD_EXPORT_DIR / "extraction_results.xlsx",
        DOWNLOAD_EXPORT_DIR / "auto_extraction_results.xlsx",
        PROGRESS_DIR / "extraction_progress.csv",
        PROGRESS_DIR / "auto_extraction_progress.csv",
        Path("extraction_results.csv"),
        Path("auto_extraction_results.csv"),
        Path("auto_extraction_progress.csv"),
    ]
    for file_path in candidates:
        if not file_path.exists():
            continue
        try:
            if file_path.suffix.lower() == ".xlsx":
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)
            if "email" in df.columns:
                for value in df["email"].dropna().tolist():
                    email = _normalize_email(value)
                    if (
                        email
                        and "@" in email
                        and not email.startswith("error:")
                        and email != "captcha_failed"
                    ):
                        known.add(email)
        except Exception as exc:
            logger.warning("Could not load previous emails from %s: %s", file_path, exc)
    return known


def _save_search_cache_to_disk(
    jobs: Iterable[Dict], keyword: str, location: str, published_since: str = "all"
) -> None:
    payload = {
        "keyword": keyword,
        "location": location,
        "published_since": _normalize_published_since(published_since),
        "jobs": list(jobs),
    }
    try:
        with SEARCH_CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not persist search cache: %s", exc)


def _load_search_cache_from_disk() -> Dict:
    if not SEARCH_CACHE_FILE.exists():
        return {"jobs": [], "keyword": "", "location": "", "published_since": "all"}
    try:
        with SEARCH_CACHE_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        jobs = payload.get("jobs", [])
        return {
            "jobs": jobs if isinstance(jobs, list) else [],
            "keyword": str(payload.get("keyword", "")),
            "location": str(payload.get("location", "")),
            "published_since": _normalize_published_since(payload.get("published_since", "all")),
        }
    except Exception as exc:
        logger.warning("Could not read persisted search cache: %s", exc)
        return {"jobs": [], "keyword": "", "location": "", "published_since": "all"}


def _get_jobs_for_extraction() -> list:
    jobs = search_cache.get("jobs", [])
    if jobs:
        return jobs

    persisted = _load_search_cache_from_disk()
    jobs = persisted.get("jobs", [])
    if jobs:
        search_cache["jobs"] = jobs
        search_cache["keyword"] = persisted.get("keyword", "")
        search_cache["location"] = persisted.get("location", "")
        search_cache["published_since"] = persisted.get("published_since", "all")
    return jobs


def _create_email_message(
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    attachment_path: str = "",
):
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    if attachment_path:
        file_path = Path(attachment_path)
        if file_path.is_file():
            with file_path.open("rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=("utf-8", "", file_path.name),
            )
            message.attach(part)
    return message


def _send_single_email(
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    recipient: str,
    subject: str,
    body: str,
    attachment_path: str = "",
) -> Tuple[bool, str]:
    try:
        message = _create_email_message(
            sender_email=sender_email,
            recipient_email=recipient,
            subject=subject,
            body=body,
            attachment_path=attachment_path,
        )
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _parse_recipient_lines(text: str) -> List[str]:
    if not text:
        return []
    candidates: List[str] = []
    for line in text.replace(",", "\n").splitlines():
        email = line.strip().lower()
        if email:
            candidates.append(email)
    deduped: List[str] = []
    seen = set()
    for email in candidates:
        if email in seen:
            continue
        seen.add(email)
        if "@" in email and "." in email.split("@")[-1]:
            deduped.append(email)
    return deduped


def _send_bulk_email_jobs(
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    jobs: List[Dict],
    attachment_path: str = "",
    max_workers: int = 3,
    submit_delay_sec: float = 0.0,
) -> Dict:
    total = len(jobs)
    details = []
    sent = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_recipient = {}
        for job in jobs:
            recipient = job.get("recipient", "")
            subject = job.get("subject", "")
            body = job.get("body", "")
            future = executor.submit(
                _send_single_email,
                smtp_server,
                smtp_port,
                sender_email,
                sender_password,
                recipient,
                subject,
                body,
                attachment_path,
            )
            future_to_recipient[future] = recipient
            if submit_delay_sec > 0:
                time.sleep(submit_delay_sec)

        for future in as_completed(future_to_recipient):
            recipient = future_to_recipient[future]
            ok, error = future.result()
            details.append({"recipient": recipient, "ok": ok, "error": error})
            if ok:
                sent += 1
            else:
                failed += 1

    return {"total": total, "sent": sent, "failed": failed, "details": details}


def _render_template_with_context(template_text: str, context: Dict) -> str:
    if not template_text:
        return ""

    context_map = {str(k).strip().lower(): str(v) for k, v in context.items() if v is not None}

    def _replace(match):
        key = match.group(1).strip().lower()
        return context_map.get(key, "")

    return PLACEHOLDER_PATTERN.sub(_replace, template_text)


def _load_recipients_from_spreadsheet(file_storage) -> Tuple[List[Dict], List[str]]:
    filename = (file_storage.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_storage)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(file_storage)
    else:
        raise ValueError("Unsupported file type. Use .csv, .xlsx, or .xls")

    if df.empty:
        return [], []

    original_columns = [str(c) for c in df.columns]
    col_lookup = {str(c).strip().lower(): str(c) for c in df.columns}
    email_candidates = ["email", "emails", "e-mail", "mail", "recipient", "to"]
    email_col = ""
    for candidate in email_candidates:
        if candidate in col_lookup:
            email_col = col_lookup[candidate]
            break

    if not email_col:
        raise ValueError(
            f"No email column found. Expected one of: {', '.join(email_candidates)}"
        )

    rows: List[Dict] = []
    seen = set()
    for _, row in df.iterrows():
        email_value = _normalize_email(row.get(email_col))
        if not email_value or "@" not in email_value:
            continue
        if email_value in seen:
            continue
        seen.add(email_value)

        context: Dict[str, str] = {}
        for col in df.columns:
            value = row.get(col)
            if pd.isna(value):
                continue
            context[str(col).strip()] = str(value).strip()
        context["email"] = email_value
        rows.append({"recipient": email_value, "context": context})

    return rows, original_columns


def _set_status(**kwargs):
    with status_lock:
        extraction_status.update(kwargs)


def _set_auto_status(**kwargs):
    with status_lock:
        auto_extraction_status.update(kwargs)


def _wait_for_continue_manual(error_message: str) -> bool:
    _set_status(paused=True, continue_requested=False, last_error=error_message)
    while True:
        time.sleep(1)
        with status_lock:
            if extraction_status["stop_requested"] or not extraction_status["is_running"]:
                extraction_status["paused"] = False
                return False
            if extraction_status["continue_requested"]:
                extraction_status["paused"] = False
                extraction_status["continue_requested"] = False
                extraction_status["last_error"] = ""
                return True


def _wait_for_continue_auto(error_message: str) -> bool:
    _set_auto_status(paused=True, continue_requested=False, last_error=error_message)
    while True:
        time.sleep(1)
        with status_lock:
            if auto_extraction_status["stop_requested"] or not auto_extraction_status["is_running"]:
                auto_extraction_status["paused"] = False
                return False
            if auto_extraction_status["continue_requested"]:
                auto_extraction_status["paused"] = False
                auto_extraction_status["continue_requested"] = False
                auto_extraction_status["last_error"] = ""
                return True


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


def _sanitize_pdf_name(value, fallback):
    return _normalize_pdf_base_name(value, str(fallback or "").strip() or "dokument")


def _company_name_from_row(row_data: Dict, index: int) -> str:
    company_name = _extract_company_from_row(row_data)
    if company_name:
        return _sanitize_pdf_name(company_name, f"firma_{index + 1}")
    return _sanitize_pdf_name("", f"firma_{index + 1}")


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


def _copy_design_pdf_to_campaign_asset(campaign_id: str, design_pdf_path: str) -> str:
    source_path = Path(str(design_pdf_path or "")).expanduser()
    if not campaign_id or not source_path.exists() or not source_path.is_file():
        return ""

    target_dir = EMAIL_CAMPAIGN_ASSET_DIR / secure_filename(campaign_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "design.pdf"
    try:
        if source_path.resolve() != target_path.resolve():
            shutil.copyfile(str(source_path), str(target_path))
    except OSError:
        return ""
    return str(target_path)


def _build_campaign_anschreiben_from_session(session_data: Dict, campaign_id: str = "") -> Dict:
    anschreiben = _normalize_campaign_anschreiben_metadata(
        {
            "templates": session_data.get("templates") or [session_data.get("template") or ""],
            "active_template_index": session_data.get("active_template_index", 0),
            "layout_options": session_data.get("layout_options") or {},
            "filename_format": session_data.get("filename_format") or "{{Unternehmen}}",
            "design_pdf_path": session_data.get("design_pdf_path") or "",
        }
    )

    if campaign_id:
        saved_design_path = _copy_design_pdf_to_campaign_asset(
            campaign_id, anschreiben.get("design_pdf_path") or ""
        )
        anschreiben["design_pdf_path"] = saved_design_path

    return anschreiben


def _persist_linked_campaign_anschreiben(session_id: str) -> None:
    session_data = _pdf_sessions.get(session_id) or {}
    campaign_id = str(session_data.get("editor_campaign_id") or "").strip()
    if not campaign_id:
        return

    campaign = _get_saved_email_campaign(campaign_id)
    if not campaign:
        return

    campaign["anschreiben"] = _build_campaign_anschreiben_from_session(
        session_data, campaign_id=campaign_id
    )
    campaign["updated_at"] = datetime.now().isoformat()
    _update_saved_email_campaign(campaign)


def _build_pdf_editor_rows_from_campaign(campaign: Dict) -> Tuple[List[Dict[str, str]], List[int]]:
    rows = list(campaign.get("rows") or [])
    sent_indices = {
        int(raw_index)
        for raw_index in (campaign.get("sent_indices") or [])
        if str(raw_index).isdigit() or isinstance(raw_index, int)
    }

    editor_rows: List[Dict[str, str]] = []
    campaign_row_indices: List[int] = []
    for row_index, row in enumerate(rows):
        if row_index in sent_indices:
            continue
        if not isinstance(row, dict):
            continue

        context = dict(row.get("context") or {})
        recipient = _normalize_email(row.get("recipient") or _extract_email_from_row(context))
        company_name = str(row.get("company") or _extract_company_from_row(context) or "").strip()

        if recipient:
            context.setdefault("email", recipient)
            context.setdefault("recipient", recipient)
        if company_name:
            context.setdefault("company", company_name)
            context.setdefault("Unternehmen", company_name)
            context.setdefault("Firma", company_name)

        if not context:
            continue

        editor_rows.append({str(key): str(value or "") for key, value in context.items()})
        campaign_row_indices.append(row_index)

    return editor_rows, campaign_row_indices


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


def run_email_extraction():
    extractor = None
    try:
        with status_lock:
            jobs = extraction_status["jobs"]
        # Only dedupe inside the current extraction run.
        seen_emails = _extract_valid_emails_from_records(jobs)
        extractor = WorkingEmailExtractor(
            captcha_userid=CAPTCHA_USERID,
            captcha_apikey=CAPTCHA_APIKEY,
            headless=False,
            known_emails=seen_emails,
        )

        for i in range(len(jobs)):
            with status_lock:
                if not extraction_status["is_running"] or extraction_status["stop_requested"]:
                    break

            with status_lock:
                extraction_status["current_index"] = i

            job = jobs[i]
            job_url = job.get("url")
            if not job_url:
                job["email_extracted"] = False
                job["email"] = "ERROR: Missing URL"
                continue

            try:
                extractor.open_job(job, delay_seconds=1.5)

                if extractor.check_for_captcha():
                    extractor.save_captcha_snapshot("static")
                    _set_captcha_context("manual_extraction")
                    _set_status(captcha_needed=True, captcha_solved=False)

                    while True:
                        time.sleep(1)
                        with status_lock:
                            solved = extraction_status["captcha_solved"]
                            running = extraction_status["is_running"]
                            stop_requested = extraction_status["stop_requested"]
                        if not running:
                            return
                        if stop_requested:
                            return
                        if solved:
                            _clear_captcha_context("manual_extraction")
                            _set_status(captcha_needed=False)
                            break

                email, phone, arbeitsgeber = extractor.extract_contact_info()
                arbeitsgeber = _normalize_arbeitsgeber_value(arbeitsgeber)
                normalized_email = _normalize_email(email)
                if normalized_email and normalized_email in seen_emails:
                    job["email"] = "DUPLICATE_EMAIL_SKIPPED"
                    job["phone"] = phone
                    job["arbeitsgeber"] = arbeitsgeber
                    job["email_extracted"] = False
                    continue

                job["email"] = email
                job["phone"] = phone
                job["arbeitsgeber"] = arbeitsgeber
                job["email_extracted"] = True
                if normalized_email:
                    seen_emails.add(normalized_email)

                if i % 10 == 0:
                    extractor.save_progress(jobs, i, base_name="extraction_progress")

            except Exception as exc:
                job["email"] = f"ERROR: {exc}"
                job["arbeitsgeber"] = None
                job["email_extracted"] = False
                logger.error("Error processing job %s: %s", job.get("reference"), exc)
                if not _wait_for_continue_manual(str(exc)):
                    break

            time.sleep(0.8)

        if jobs:
            extractor.save_progress(jobs, len(jobs) - 1, base_name="extraction_progress")

        with status_lock:
            stop_requested = extraction_status["stop_requested"]
            current_index = extraction_status["current_index"]
        _set_status(
            is_running=False,
            current_index=current_index if stop_requested else len(jobs),
            captcha_needed=False,
            paused=False,
            continue_requested=False,
        )

    except Exception as exc:
        logger.error("Extraction error: %s", exc)
        _set_status(is_running=False, last_error=str(exc), captcha_needed=False)
    finally:
        if extractor:
            extractor.close()


def run_auto_extraction():
    extractor = None
    try:
        with status_lock:
            jobs = auto_extraction_status["jobs"]
            start_index = auto_extraction_status["current_index"]

        # Only dedupe inside the current extraction run.
        existing_emails = _extract_valid_emails_from_records(jobs[:start_index])
        extractor = WorkingEmailExtractor(
            captcha_userid=CAPTCHA_USERID,
            captcha_apikey=CAPTCHA_APIKEY,
            headless=False,
            known_emails=existing_emails,
        )

        for i in range(start_index, len(jobs)):
            with status_lock:
                if not auto_extraction_status["is_running"] or auto_extraction_status["stop_requested"]:
                    break

            with status_lock:
                auto_extraction_status["current_index"] = i

            failed_before = extractor.stats["failed"]
            jobs[i] = extractor.process_job(jobs[i])
            failed_after = extractor.stats["failed"]

            _set_auto_status(
                emails_found=extractor.stats["emails_found"],
                captchas_solved=extractor.stats["captchas_solved"],
                failed=extractor.stats["failed"],
            )

            if failed_after > failed_before:
                error_message = str(jobs[i].get("email") or "Job failed")
                if not _wait_for_continue_auto(error_message):
                    break

            if (i + 1) % 10 == 0:
                extractor.save_progress(jobs, i, base_name="auto_extraction_progress")
            time.sleep(1)

        if jobs:
            extractor.save_progress(jobs, len(jobs) - 1, base_name="auto_extraction_progress")

        with status_lock:
            stop_requested = auto_extraction_status["stop_requested"]
            current_index = auto_extraction_status["current_index"]
        _set_auto_status(
            is_running=False,
            current_index=current_index if stop_requested else len(jobs),
            paused=False,
            continue_requested=False,
        )

    except Exception as exc:
        logger.error("Auto extraction error: %s", exc)
        _set_auto_status(is_running=False, last_error=str(exc))
    finally:
        if extractor:
            extractor.close()


def _create_auto_extraction_job(
    jobs: List[Dict], keyword: str, location: str, published_since: str
) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with auto_extraction_jobs_lock:
        auto_extraction_jobs[job_id] = {
            "job_id": job_id,
            "keyword": keyword,
            "location": location,
            "published_since": _normalize_published_since(published_since),
            "is_running": False,
            "stop_requested": False,
            "paused": False,
            "continue_requested": False,
            "current_index": 0,
            "total_jobs": len(jobs),
            "emails_found": 0,
            "captchas_solved": 0,
            "failed": 0,
            "jobs": [dict(job) for job in jobs],
            "last_error": "",
            "created_at": now,
            "updated_at": now,
            "finished_at": "",
        }
    return job_id


def _set_auto_job_status(job_id: str, **kwargs) -> bool:
    with auto_extraction_jobs_lock:
        job = auto_extraction_jobs.get(job_id)
        if not job:
            return False
        job.update(kwargs)
        job["updated_at"] = datetime.now().isoformat()
        return True


def _wait_for_continue_auto_job(job_id: str, error_message: str) -> bool:
    if not _set_auto_job_status(
        job_id,
        paused=True,
        continue_requested=False,
        last_error=error_message,
    ):
        return False

    while True:
        time.sleep(1)
        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs.get(job_id)
            if not job:
                return False
            if job.get("stop_requested") or not job.get("is_running"):
                job["paused"] = False
                job["updated_at"] = datetime.now().isoformat()
                return False
            if job.get("continue_requested"):
                job["paused"] = False
                job["continue_requested"] = False
                job["last_error"] = ""
                job["updated_at"] = datetime.now().isoformat()
                return True


def _run_auto_extraction_job(job_id: str):
    extractor = None
    try:
        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs.get(job_id)
            if not job:
                return
            jobs = job.get("jobs") or []
            start_index = int(job.get("current_index") or 0)
            job["is_running"] = True
            job["stop_requested"] = False
            job["paused"] = False
            job["continue_requested"] = False
            job["last_error"] = ""
            job["updated_at"] = datetime.now().isoformat()

        existing_emails = _extract_valid_emails_from_records(jobs[:start_index])
        extractor = WorkingEmailExtractor(
            captcha_userid=CAPTCHA_USERID,
            captcha_apikey=CAPTCHA_APIKEY,
            headless=False,
            known_emails=existing_emails,
        )

        for i in range(start_index, len(jobs)):
            with auto_extraction_jobs_lock:
                job = auto_extraction_jobs.get(job_id)
                if not job:
                    return
                if not job.get("is_running") or job.get("stop_requested"):
                    break
                job["current_index"] = i
                job["updated_at"] = datetime.now().isoformat()

            failed_before = int(extractor.stats.get("failed") or 0)
            jobs[i] = extractor.process_job(jobs[i])
            failed_after = int(extractor.stats.get("failed") or 0)

            _set_auto_job_status(
                job_id,
                emails_found=int(extractor.stats.get("emails_found") or 0),
                captchas_solved=int(extractor.stats.get("captchas_solved") or 0),
                failed=int(extractor.stats.get("failed") or 0),
            )

            if failed_after > failed_before:
                error_message = str(jobs[i].get("email") or "Job failed")
                if not _wait_for_continue_auto_job(job_id, error_message):
                    break

            if (i + 1) % 10 == 0:
                extractor.save_progress(jobs, i)
            time.sleep(1)

        if jobs:
            extractor.save_progress(jobs, len(jobs) - 1)

        with auto_extraction_jobs_lock:
            job = auto_extraction_jobs.get(job_id)
            if not job:
                return
            stop_requested = bool(job.get("stop_requested"))
            current_index = int(job.get("current_index") or 0)
            job["is_running"] = False
            job["paused"] = False
            job["continue_requested"] = False
            job["current_index"] = current_index if stop_requested else len(jobs)
            job["finished_at"] = datetime.now().isoformat()
            job["updated_at"] = datetime.now().isoformat()
    except Exception as exc:
        logger.error("Auto extraction job %s error: %s", job_id, exc)
        _set_auto_job_status(
            job_id,
            is_running=False,
            paused=False,
            last_error=str(exc),
            finished_at=datetime.now().isoformat(),
        )
    finally:
        if extractor:
            extractor.close()


def _run_ausbildungen_update_job(job_id: str):
    extractor = None
    try:
        with ausbildungen_update_jobs_lock:
            job = ausbildungen_update_jobs.get(job_id)
            if not job:
                return
            file_path = Path(str(job.get("file_path") or ""))
            keyword = str(job.get("keyword") or "").strip()
            job["phase"] = "loading"
            job["is_running"] = True
            job["stop_requested"] = False
            job["paused"] = False
            job["continue_requested"] = False
            job["captcha_needed"] = False
            job["last_error"] = ""
            job["updated_at"] = datetime.now().isoformat()

        if not file_path.exists():
            raise FileNotFoundError(f"Export file not found: {file_path.name}")

        existing_rows = _load_spreadsheet_records(file_path)
        existing_emails = _extract_valid_emails_from_records(existing_rows)
        _set_ausbildungen_update_job(
            job_id,
            phase="searching",
            existing_rows=len(existing_rows),
            result_rows=len(existing_rows),
        )

        scraper = EnhancedJobScraper()
        fetched_jobs = scraper.fetch_all_jobs(keyword, "", max_jobs=DEFAULT_MAX_JOBS)
        _set_ausbildungen_update_job(
            job_id,
            phase="extracting",
            total_jobs=len(fetched_jobs),
            current_index=0,
        )

        extractor = WorkingEmailExtractor(
            captcha_userid=CAPTCHA_USERID,
            captcha_apikey=CAPTCHA_APIKEY,
            headless=False,
            known_emails=existing_emails,
        )

        duplicate_emails = 0
        for index, job_row in enumerate(fetched_jobs):
            with ausbildungen_update_jobs_lock:
                job = ausbildungen_update_jobs.get(job_id)
                if not job:
                    return
                if not job.get("is_running") or job.get("stop_requested"):
                    break
                job["current_index"] = index
                job["updated_at"] = datetime.now().isoformat()

            try:
                extractor.open_job(job_row, delay_seconds=1.0)

                captcha_detected = extractor.is_blocked_page() or extractor.check_for_captcha()
                if captcha_detected:
                    extractor.stats["captchas_encountered"] += 1
                    captcha_resolved = False
                    if extractor.captcha_solver.userid and extractor.captcha_solver.apikey:
                        captcha_resolved = extractor.handle_captcha()
                        if captcha_resolved:
                            time.sleep(2)

                    if not captcha_resolved:
                        extractor.save_captcha_snapshot("static")
                        if not _wait_for_continue_ausbildungen_update(
                            job_id,
                            "CAPTCHA gefunden. Bitte im Selenium-Fenster loesen und dann unter /captcha_solve bestaetigen.",
                        ):
                            break
                        time.sleep(2)

                email, phone, arbeitsgeber = extractor.extract_contact_info()
                arbeitsgeber = _normalize_arbeitsgeber_value(arbeitsgeber)
                normalized_email = _normalize_email(email)
                if normalized_email and normalized_email in existing_emails:
                    job_row["email"] = "DUPLICATE_EMAIL_SKIPPED"
                    job_row["phone"] = phone
                    job_row["arbeitsgeber"] = arbeitsgeber
                    job_row["email_extracted"] = False
                    duplicate_emails += 1
                else:
                    job_row["email"] = email
                    job_row["phone"] = phone
                    job_row["arbeitsgeber"] = arbeitsgeber
                    job_row["email_extracted"] = bool(normalized_email)
                    if normalized_email:
                        existing_emails.add(normalized_email)
                        extractor.stats["emails_found"] += 1

                extractor.stats["processed"] += 1
                fetched_jobs[index] = job_row
            except Exception as exc:
                logger.error("Ausbildungen update job row %s failed: %s", index, exc)
                job_row["email"] = f"ERROR: {exc}"
                job_row["phone"] = None
                job_row["arbeitsgeber"] = None
                job_row["email_extracted"] = False
                fetched_jobs[index] = job_row
                extractor.stats["failed"] += 1

            _set_ausbildungen_update_job(
                job_id,
                current_index=index + 1,
                emails_found=int(extractor.stats.get("emails_found") or 0),
                captchas_solved=int(extractor.stats.get("captchas_solved") or 0),
                failed=int(extractor.stats.get("failed") or 0),
                duplicate_emails=duplicate_emails,
                paused=False,
                captcha_needed=False,
                phase="extracting",
            )
            time.sleep(1)

        new_rows = _prepare_download_jobs(fetched_jobs)
        merged_rows = _merge_records_by_email(existing_rows, new_rows)

        _set_ausbildungen_update_job(job_id, phase="saving")
        if len(merged_rows) != len(existing_rows):
            _write_spreadsheet_records(file_path, merged_rows)

        with ausbildungen_update_jobs_lock:
            job = ausbildungen_update_jobs.get(job_id)
            if not job:
                return
            stop_requested = bool(job.get("stop_requested"))

        _set_ausbildungen_update_job(
            job_id,
            phase="stopped" if stop_requested else "completed",
            is_running=False,
            paused=False,
            continue_requested=False,
            captcha_needed=False,
            new_rows_added=max(len(merged_rows) - len(existing_rows), 0),
            result_rows=len(merged_rows),
            finished_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        logger.error("Ausbildungen update %s failed: %s", job_id, exc)
        _set_ausbildungen_update_job(
            job_id,
            phase="failed",
            is_running=False,
            paused=False,
            continue_requested=False,
            captcha_needed=False,
            last_error=str(exc),
            finished_at=datetime.now().isoformat(),
        )
    finally:
        _clear_captcha_context("ausbildungen_update", job_id)
        if extractor:
            extractor.close()

@app.route("/")
def index():
    return _render_app_shell("search")


@app.route("/add")
def add():
    return redirect(url_for("index"))


@app.route("/ausbildungen")
def ausbildungen():
    return _render_app_shell("ausbildungen")


@app.route("/money")
def money():
    return _render_app_shell("money")


@app.route("/api/ausbildungen/files", methods=["GET"])
def ausbildungen_files_api():
    export_files = _list_auto_extraction_export_files()
    payload_files: List[Dict] = []

    for item in export_files:
        filename = str(item.get("filename") or "").strip()
        file_payload = dict(item)
        file_payload["active_job"] = _get_running_ausbildungen_update_for_file(filename)
        payload_files.append(file_payload)

    return jsonify(
        {
            "success": True,
            "files": payload_files,
            "updated_at": datetime.now().isoformat(),
        }
    )


@app.route("/api/ausbildungen/update", methods=["POST"])
def start_ausbildungen_update():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "").strip()
    if not filename:
        return jsonify({"success": False, "message": "Dateiname fehlt"}), 400

    existing_job = _get_running_ausbildungen_update_for_file(filename)
    if existing_job:
        return jsonify(
            {
                "success": True,
                "job_id": existing_job.get("job_id"),
                "message": "Update laeuft bereits",
            }
        )

    file_path = _resolve_auto_extraction_export_path(filename)
    if not file_path:
        return jsonify({"success": False, "message": "Exportdatei nicht gefunden"}), 404

    try:
        payload = _create_ausbildungen_update_job(file_path)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500

    thread = threading.Thread(
        target=_run_ausbildungen_update_job,
        args=(str(payload.get("job_id") or ""),),
        daemon=True,
    )
    thread.start()

    return jsonify(
        {
            "success": True,
            "job_id": payload.get("job_id"),
            "message": "Update gestartet",
        }
    )


@app.route("/api/ausbildungen/update/<job_id>", methods=["GET"])
def ausbildungen_update_status(job_id: str):
    with ausbildungen_update_jobs_lock:
        job = ausbildungen_update_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Update-Job nicht gefunden"}), 404
        payload = dict(job)
    return jsonify({"success": True, "job": payload})


@app.route("/api/ausbildungen/update/<job_id>/stop", methods=["POST"])
def stop_ausbildungen_update(job_id: str):
    with ausbildungen_update_jobs_lock:
        job = ausbildungen_update_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Update-Job nicht gefunden"}), 404
        if not job.get("is_running") and str(job.get("phase") or "") not in {"captcha", "stopping"}:
            return jsonify({"success": False, "message": "Update laeuft nicht"}), 400
        job["stop_requested"] = True
        job["paused"] = False
        job["continue_requested"] = False
        job["captcha_needed"] = False
        job["phase"] = "stopping"
        job["updated_at"] = datetime.now().isoformat()

    _clear_captcha_context("ausbildungen_update", job_id)
    return jsonify({"success": True, "message": "Stop des Updates angefordert"})


@app.route("/create-anschreibens")
def create_anschreibens():
    # Render the PDF generator directly inside the shared SPA shell.
    return _render_app_shell("create-anschreibens")


@app.route("/pdf")
def pdf_frontend_root():
    # Standalone fallback PDF generator UI.
    if not (PDF_GENERATOR_FRONTEND_DIR / "index.html").exists():
        return render_template(
            "error.html",
            error=f"PDF generator frontend not found in {PDF_GENERATOR_FRONTEND_DIR}",
        )
    return send_from_directory(str(PDF_GENERATOR_FRONTEND_DIR), "index.html")


@app.route("/pdf/<path:filename>")
def pdf_frontend_assets(filename):
    return send_from_directory(str(PDF_GENERATOR_FRONTEND_DIR), filename)


def _build_pdf_autoload_session_payload(source: str) -> Tuple[Dict, int]:
    normalized_source = str(source or "latest").strip().lower()

    with status_lock:
        manual_jobs = list(extraction_status.get("jobs", []))
        auto_jobs = list(auto_extraction_status.get("jobs", []))

    selected_jobs = []
    selected_source = "latest"

    if normalized_source == "manual":
        selected_jobs = manual_jobs
        selected_source = "manual"
    elif normalized_source == "auto":
        selected_jobs = auto_jobs
        selected_source = "auto"
    else:
        selected_jobs = auto_jobs if auto_jobs else manual_jobs
        selected_source = "auto" if auto_jobs else "manual"

    prepared_jobs = _prepare_download_jobs(selected_jobs)
    if not prepared_jobs:
        return {"error": "No collected jobs with valid emails found."}, 400

    payload = _create_pdf_session_from_rows(prepared_jobs)
    payload["source"] = selected_source
    return payload, 200


def _build_pdf_export_file_session_payload(
    filename: str,
    application_id: str = None,
    application: Optional[Dict] = None,
) -> Tuple[Dict, int]:
    file_path = _resolve_auto_extraction_export_path(filename)
    if not file_path:
        return {"error": "Exportdatei nicht gefunden."}, 404

    rows = _load_spreadsheet_records(file_path)
    prepared_rows = _prepare_download_jobs(rows)
    if not prepared_rows:
        return {"error": "Keine gültigen Datensätze in der Exportdatei gefunden."}, 400

    application_payload = dict(application or {})
    if not application_payload and application_id:
        application_payload = _get_firebase_application_by_id(application_id) or {}

    if application_payload:
        bewerbungen_str = str(
            application_payload.get("bewerbungen")
            or application_payload.get("pack")
            or ""
        ).strip()
        try:
            limit_match = re.search(r"\d+", bewerbungen_str)
            limit = int(limit_match.group(0)) if limit_match else int(bewerbungen_str)
            if limit > 0:
                prepared_rows = prepared_rows[:limit]
        except ValueError:
            pass

    payload = _create_pdf_session_from_rows(prepared_rows)
    payload["source"] = "export_file"
    payload["filename"] = file_path.name
    payload["display_name"] = _format_auto_export_domain_name(file_path)

    if application_payload:
        payload["application_data"] = application_payload
        payload["application_summary"] = _build_pdf_application_summary(application_payload)
        
    return payload, 200


def _get_firebase_application_by_id(application_id: str) -> Optional[Dict]:
    normalized_application_id = str(application_id or "").strip()
    if not normalized_application_id:
        return None

    try:
        db = _get_firebase_db()
        if db is None:
            return None

        document = db.collection("applications").document(normalized_application_id).get()
        if not getattr(document, "exists", False):
            return None
        return _normalize_firebase_application(document.id, document.to_dict())
    except Exception as exc:
        logger.warning("Failed to fetch Firebase application %s: %s", normalized_application_id, exc)
        return None


def _pick_best_first_value(payload: Dict, keys: Iterable[str]) -> str:
    if not isinstance(payload, dict):
        payload = {}
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _build_email_templates_from_anschreiben(
    anschreiben_text: str,
    job_title: str = "",
    company: str = "",
) -> Dict[str, str]:
    job_title = str(job_title or "").strip() or "einen Ausbildungsplatz"
    company_placeholder = str(company or "").strip() or "{{company}}"

    safe_subject = f"Bewerbung um einen Ausbildungsplatz als {job_title} bei {company_placeholder}"
    safe_body = (
        "{{anrede}} {{arbeitsgeber}},\n\n"
        f"hiermit bewerbe ich mich um einen Ausbildungsplatz als {job_title} bei {company_placeholder} in {{city}}.\n\n"
        "Im Anhang finden Sie meine Bewerbungsunterlagen.\n\n"
        "Ich freue mich auf Ihre Rückmeldung.\n\n"
        "Mit freundlichen Grüßen\n"
        "{{full_name}}"
    )

    source_text = _normalize_rendered_text(anschreiben_text)
    if not source_text:
        return {"subject": safe_subject, "body": safe_body}

    try:
        subject = None
        body = None

        if _has_meaningful_text(source_text):
            subject = f"Bewerbung um einen Ausbildungsplatz als {job_title} bei {company_placeholder}"

            cleaned = source_text
            greeting = "{{anrede}} {{arbeitsgeber}},"
            if "{{anrede}}" in cleaned or "{{arbeitsgeber}}" in cleaned:
                cleaned = cleaned
            elif ARBEITGEBER_PATTERN.search(cleaned):
                cleaned = ARBEITGEBER_PATTERN.sub(greeting, cleaned, count=1)

            lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
            body_lines = []
            for line in lines:
                if len(body_lines) >= 6:
                    break
                body_lines.append(line)

            body = "\n".join(body_lines).strip()
            if len(body) > 900:
                body = body[:900].rsplit("\n", 1)[0].strip()

        return {
            "subject": subject or safe_subject,
            "body": body or safe_body,
        }
    except Exception:
        return {
            "subject": safe_subject,
            "body": safe_body,
        }


def _application_document_name(item: object) -> str:
    if isinstance(item, dict):
        for key in ("name", "filename", "fileName", "path", "url", "downloadURL", "href"):
            value = str(item.get(key) or "").strip()
            if value:
                return value.split("?", 1)[0].rstrip("/").split("/")[-1] or value
        return "Dokument"

    value = str(item or "").strip()
    if not value:
        return "Dokument"
    return value.split("?", 1)[0].rstrip("/").split("/")[-1] or value


def _normalize_application_documents(documents: object) -> List[Dict[str, str]]:
    if not isinstance(documents, list):
        return []

    normalized: List[Dict[str, str]] = []
    for item in documents:
        if isinstance(item, dict):
            document = {
                str(key): str(value).strip()
                for key, value in item.items()
                if str(key or "").strip() and str(value or "").strip()
            }
            if not document:
                continue
            document.setdefault("name", _application_document_name(document))
            normalized.append(document)
            continue

        value = str(item or "").strip()
        if value:
            normalized.append({"path": value, "name": _application_document_name(value)})

    return normalized


def _format_application_datetime(value: object) -> str:
    timestamp = _coerce_firebase_datetime(value)
    if timestamp is None:
        return "k. A."
    return timestamp.strftime("%d.%m.%Y %H:%M")


def _build_pdf_application_summary(application: Optional[Dict]) -> Dict[str, object]:
    payload = dict(application or {})
    documents = _normalize_application_documents(payload.get("documents"))

    created_at_display = str(payload.get("created_at_display") or "").strip()
    if not created_at_display:
        created_at_display = _format_application_datetime(
            payload.get("createdAt") or payload.get("created_at")
        )

    document_count = payload.get("document_count")
    try:
        normalized_document_count = int(document_count)
    except Exception:
        normalized_document_count = len(documents)

    source_label = str(
        payload.get("source_label")
        or payload.get("_source")
        or payload.get("source")
        or "Application"
    ).strip()

    return {
        "id": str(payload.get("id") or "").strip(),
        "full_name": str(payload.get("fullName") or payload.get("full_name") or payload.get("name") or "").strip(),
        "email": _normalize_email(_pick_best_first_value(payload, ["email", "sender_email", "gmail"])),
        "sender_email": _normalize_email(_pick_best_first_value(payload, ["sender_email", "email", "gmail"])),
        "whatsapp": str(payload.get("whatsapp") or "").strip(),
        "bereich": str(payload.get("bereich") or payload.get("field") or "").strip(),
        "bewerbungen": str(payload.get("bewerbungen") or payload.get("pack") or "").strip(),
        "bank": str(payload.get("bank") or "").strip(),
        "language_level": str(payload.get("languageLevel") or payload.get("language_level") or "").strip(),
        "source_label": source_label,
        "document_count": max(0, normalized_document_count),
        "created_at_display": created_at_display,
        "documents": documents,
    }


def _build_pdf_firebase_application_summary(application: Optional[Dict]) -> Dict[str, object]:
    payload = dict(application or {})
    payload.setdefault("source_label", "Firebase")
    return _build_pdf_application_summary(payload)


def _build_pdf_row_from_firebase_application(application: Optional[Dict]) -> Dict[str, str]:
    summary = _build_pdf_application_summary(application)
    document_names = ", ".join(
        _application_document_name(item)
        for item in (summary.get("documents") or [])
        if _application_document_name(item)
    )
    created_at_display = str(summary.get("created_at_display") or "").strip()
    full_name = str(summary.get("full_name") or "").strip()
    email = _normalize_email(summary.get("email"))
    bereich = str(summary.get("bereich") or "").strip()
    fallback_id = str(summary.get("id") or "").strip()[:8]
    fallback_name = f"bewerber_{fallback_id}" if fallback_id else "bewerber"
    display_name = full_name or email or bereich or fallback_name

    row = {
        "id": str(summary.get("id") or "").strip(),
        "application_id": str(summary.get("id") or "").strip(),
        "fullName": full_name,
        "full_name": full_name,
        "name": full_name,
        "BewerberName": full_name,
        "email": email,
        "recipient": email,
        "whatsapp": str(summary.get("whatsapp") or "").strip(),
        "telefon": str(summary.get("whatsapp") or "").strip(),
        "phone": str(summary.get("whatsapp") or "").strip(),
        "bereich": bereich,
        "bewerbungen": str(summary.get("bewerbungen") or "").strip(),
        "bank": str(summary.get("bank") or "").strip(),
        "languageLevel": str(summary.get("language_level") or "").strip(),
        "language_level": str(summary.get("language_level") or "").strip(),
        "documents": document_names,
        "document_count": str(summary.get("document_count") or 0),
        "created_at": created_at_display,
        "created_at_display": created_at_display,
        "company": display_name,
        "Unternehmen": display_name,
        "Firma": display_name,
        "source_label": str(summary.get("source_label") or "Application").strip(),
    }

    return {
        key: str(value).strip()
        for key, value in row.items()
        if str(key or "").strip() and str(value or "").strip()
    }


def _build_pdf_firebase_application_session_payload(
    application: Optional[Dict],
    application_id: str,
) -> Tuple[Dict, int]:
    normalized_application_id = str(application_id or "").strip()
    application_payload = dict(application or {})

    if not application_payload and normalized_application_id:
        application_payload = _get_firebase_application_by_id(normalized_application_id) or {}

    if application_payload:
        application_payload.setdefault("source_label", "Firebase")

    return _build_pdf_application_session_payload(
        application_payload,
        normalized_application_id,
        source_label="Firebase",
    )


def _build_pdf_application_session_payload(
    application: Optional[Dict],
    application_id: str,
    source_label: str = "Application",
) -> Tuple[Dict, int]:
    normalized_application_id = str(application_id or "").strip()
    application_payload = dict(application or {})

    if not application_payload:
        return {"error": "Bewerbung nicht gefunden."}, 404

    if normalized_application_id and not str(application_payload.get("id") or "").strip():
        application_payload["id"] = normalized_application_id
    application_payload.setdefault("source_label", source_label)

    row = _build_pdf_row_from_firebase_application(application_payload)
    if not row:
        return {"error": "Bewerbung enthält keine gültigen Daten."}, 400

    payload = _create_pdf_session_from_rows([row])
    summary = _build_pdf_application_summary(application_payload)
    payload["source"] = "application"
    payload["application_id"] = str(summary.get("id") or normalized_application_id).strip()
    payload["display_name"] = (
        str(summary.get("full_name") or "").strip()
        or str(summary.get("email") or "").strip()
        or str(row.get("company") or "").strip()
    )
    payload["application_summary"] = summary
    payload["application_data"] = application_payload
    return payload, 200


def _build_pdf_campaign_editor_session_payload(campaign_id: str) -> Tuple[Dict, int]:
    normalized_campaign_id = str(campaign_id or "").strip()
    if not normalized_campaign_id:
        return {"error": "Ungültige Kampagnen-ID"}, 400

    if _get_active_email_send_job_for_campaign(normalized_campaign_id):
        return {
            "error": "Anschreiben kann nur bearbeitet werden, wenn der Versand gestoppt ist."
        }, 409

    campaign = _get_saved_email_campaign(normalized_campaign_id)
    if not campaign:
        return {"error": "Gespeicherte Vorlage nicht gefunden."}, 404
    if str(campaign.get("mode") or "") != "transfer":
        return {"error": "Anschreiben-Bearbeitung ist nur für PDF-Kampagnen verfügbar."}, 400
    if not _campaign_has_saved_anschreiben(campaign):
        return {"error": "Für diese Kampagne wurden keine gespeicherten Anschreiben-Daten gefunden."}, 409

    editor_rows, campaign_row_indices = _build_pdf_editor_rows_from_campaign(campaign)
    if not editor_rows:
        return {"error": "Keine offenen Empfänger mehr für diese Kampagne."}, 400

    session_payload = _create_pdf_session_from_rows(editor_rows)
    session_id = str(session_payload.get("session_id") or "").strip()
    session_data = _pdf_sessions.get(session_id)
    if not session_data:
        return {"error": "Editor-Sitzung konnte nicht erstellt werden."}, 500

    anschreiben = _normalize_campaign_anschreiben_metadata(campaign.get("anschreiben") or {})
    session_data["template"] = anschreiben["templates"][anschreiben["active_template_index"]]
    session_data["templates"] = list(anschreiben.get("templates") or [""])
    session_data["active_template_index"] = int(anschreiben.get("active_template_index") or 0)
    session_data["filename_format"] = anschreiben.get("filename_format") or "{{Unternehmen}}"
    session_data["layout_options"] = _normalize_pdf_layout_options(
        anschreiben.get("layout_options") or {}
    )
    session_data["editor_campaign_id"] = normalized_campaign_id
    session_data["campaign_row_indices"] = list(campaign_row_indices)

    design_payload = _read_binary_file_as_base64(anschreiben.get("design_pdf_path") or "")
    restored_design_path = _restore_design_pdf_for_session(session_id, design_payload)
    if restored_design_path:
        session_data["design_pdf_path"] = restored_design_path

    session_payload["templates"] = list(session_data.get("templates") or [""])
    session_payload["active_template_index"] = int(session_data.get("active_template_index") or 0)
    session_payload["layout_options"] = dict(session_data.get("layout_options") or PDF_LAYOUT_DEFAULTS)
    session_payload["filename_format"] = (
        str(session_data.get("filename_format") or "{{Unternehmen}}")
    )
    session_payload["design_pdf_name"] = (
        design_payload.get("filename")
        if isinstance(design_payload, dict)
        else ""
    )

    campaign_display_name = str(campaign.get("full_name") or campaign.get("name") or "").strip()
    campaign_sender_email = str(campaign.get("sender_email") or "").strip()
    campaign_application_summary = {
        "id": normalized_campaign_id,
        "full_name": campaign_display_name,
        "email": campaign_sender_email,
        "sender_email": campaign_sender_email,
        "whatsapp": "",
        "bereich": "",
        "bewerbungen": "",
        "bank": "",
        "language_level": "",
        "source_label": "Campaign",
        "document_count": 0,
        "created_at_display": str(campaign.get("created_at") or "").strip(),
        "documents": [],
    }
    campaign_application_data = {
        "id": normalized_campaign_id,
        "full_name": campaign_display_name,
        "email": campaign_sender_email,
        "sender_email": campaign_sender_email,
        "documents": [],
        "source_label": "Campaign",
    }
    session_data["application_summary"] = dict(campaign_application_summary)
    session_data["application_data"] = dict(campaign_application_data)
    session_payload["application_summary"] = dict(campaign_application_summary)
    session_payload["application_data"] = dict(campaign_application_data)

    session_payload["edit_campaign_id"] = normalized_campaign_id
    session_payload["display_name"] = campaign_display_name
    return session_payload, 200


@app.route("/api/campaign-anschreiben/<campaign_id>", methods=["GET"])
def load_campaign_anschreiben_editor(campaign_id: str):
    payload, status_code = _build_pdf_campaign_editor_session_payload(campaign_id)
    return jsonify(payload), status_code


@app.route("/api/create-anschreibens/bootstrap", methods=["GET"])
def create_anschreibens_bootstrap_api():
    edit_campaign_id = (request.args.get("edit_campaign") or "").strip()
    autoload_source = (request.args.get("autoload") or "").strip()
    filename = (request.args.get("filename") or "").strip()
    application_id = (request.args.get("application_id") or "").strip()

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

    if application_id:
        # Fallback to returning just the application data if no export file is chosen yet
        application = _get_firebase_application_by_id(application_id)
        if application:
            payload = {
                "session_id": "",
                "columns": [],
                "preview": [],
                "templates": [],
                "application_data": application,
                "application_summary": _build_pdf_firebase_application_summary(application)
            }
            return jsonify({"success": True, "mode": "firebase_only", "session": payload})

    return jsonify({"success": True, "mode": "empty", "session": None})


@app.route("/api/create-anschreibens/exports", methods=["GET"])
def create_anschreibens_exports_api():
    return jsonify(
        {
            "success": True,
            "files": _list_auto_extraction_export_files(),
            "updated_at": datetime.now().isoformat(),
        }
    )


@app.route("/api/create-anschreibens/firebase-bootstrap", methods=["POST"])
def create_anschreibens_firebase_bootstrap_api():
    data = request.get_json(silent=True) or {}
    application_payload = data.get("application") if isinstance(data.get("application"), dict) else {}
    application_id = str(data.get("application_id") or "").strip()

    payload, status_code = _build_pdf_firebase_application_session_payload(
        application_payload,
        application_id,
    )
    if status_code != 200:
        return jsonify(payload), status_code

    return jsonify({"success": True, "mode": "firebase_application", "session": payload})


@app.route("/api/create-anschreibens/application-bootstrap", methods=["POST"])
def create_anschreibens_application_bootstrap_api():
    data = request.get_json(silent=True) or {}
    application_payload = data.get("application") if isinstance(data.get("application"), dict) else {}
    application_id = str(data.get("application_id") or "").strip()
    filename = str(data.get("filename") or "").strip()
    source_label = str(data.get("source_label") or application_payload.get("source_label") or "Supabase").strip()

    if filename:
        payload, status_code = _build_pdf_export_file_session_payload(
            filename,
            application_id=application_id,
            application=application_payload,
        )
    else:
        payload, status_code = _build_pdf_application_session_payload(
            application_payload,
            application_id,
            source_label=source_label,
        )

    if status_code != 200:
        return jsonify(payload), status_code

    return jsonify({"success": True, "mode": "application", "session": payload})


@app.route("/send-emails", methods=["GET", "POST"])
def send_emails():
    return _render_app_shell("send-emails")


@app.route("/api/send-emails/campaigns", methods=["GET"])
def send_emails_campaigns_api():
    transfer_id = (request.args.get("transfer") or "").strip()
    campaign_id = (request.args.get("campaign") or "").strip()
    transfer_info = None
    transfer_error = ""
    campaign_info = None
    campaign_error = ""
    active_send_job = None

    if campaign_id:
        campaign = _get_saved_email_campaign(campaign_id)
        if not campaign:
            campaign_error = "Gespeicherte Vorlage nicht gefunden."
        else:
            campaign_info = _build_send_page_campaign_info(campaign)
            active_send_job = _serialize_email_send_job_for_response(
                _get_active_email_send_job_for_campaign(campaign_info["id"])
            )
    elif transfer_id:
        payload = _email_transfer_sessions.get(transfer_id)
        if not payload:
            transfer_error = "Transfer session not found or expired."
        else:
            rows = payload.get("rows", [])
            transfer_info = {
                "id": transfer_id,
                "total_rows": len(rows),
                "preview": rows[:5],
                "full_name": str(payload.get("full_name") or "").strip(),
                "sender_email": str(payload.get("sender_email") or "").strip(),
                "email_subject_template": str(payload.get("email_subject_template") or "").strip(),
                "email_body_template": str(payload.get("email_body_template") or "").strip(),
                "job_title": str(payload.get("job_title") or "").strip(),
                "company": str(payload.get("company") or "").strip(),
                "source_pdf_session_id": str(payload.get("source_pdf_session_id") or "").strip(),
            }

    return jsonify(
        {
            "success": True,
            "transfer_info": transfer_info,
            "transfer_error": transfer_error,
            "campaign_info": campaign_info,
            "campaign_error": campaign_error,
            "active_send_job": active_send_job,
            "updated_at": datetime.now().isoformat(),
        }
    )


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return _render_app_shell("dashboard")


@app.route("/firebase", methods=["GET"])
def firebase_page():
    return redirect(url_for("supabase_page"))


@app.route("/supabase", methods=["GET"])
def supabase_page():
    return _render_app_shell("supabase")


@app.route("/api/firebase/applications", methods=["GET"])
def firebase_applications_api():
    firebase_applications = _get_firebase_applications()
    return jsonify(
        {
            "success": True,
            "applications": firebase_applications,
            "updated_at": datetime.now().isoformat(),
        }
    )


@app.route("/api/dashboard/campaigns", methods=["GET"])
def dashboard_campaigns_api():
    campaigns = _list_dashboard_campaigns_with_jobs()
    return jsonify(
        {
            "success": True,
            "campaigns": campaigns,
            "updated_at": datetime.now().isoformat(),
        }
    )


@app.route("/api/campaign/delete/<campaign_id>", methods=["POST"])
def delete_campaign_template_api(campaign_id: str):
    success, message, status_code = _delete_saved_email_campaign_with_guard(campaign_id)
    return jsonify({"success": success, "message": message, "campaign_id": campaign_id}), status_code


@app.route("/dashboard/delete/<campaign_id>", methods=["POST"])
def delete_dashboard_campaign(campaign_id: str):
    success, message, _ = _delete_saved_email_campaign_with_guard(campaign_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/api/firebase/delete/<application_id>", methods=["POST"])
def delete_firebase_application(application_id: str):
    """Delete an application from Firebase Firestore."""
    try:
        db = _get_firebase_db()
        if db is None:
            return jsonify({"success": False, "message": "Firebase not available"}), 500
        
        db.collection("applications").document(application_id).delete()
        return jsonify({"success": True, "message": f"Application {application_id} deleted from Firebase"})
    except Exception as e:
        logger.error(f"Failed to delete Firebase application: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/send", methods=["POST"])
@app.route("/send-email", methods=["POST"])
def send_email():
    data = request.get_json(silent=True) or {}
    to_email = data.get("to")
    subject = data.get("subject")
    body = data.get("body")
    sender_email_input = data.get("sender_email")
    app_password_input = data.get("app_password")

    if not to_email or not subject or not body:
        return jsonify({"success": False, "message": "Bitte alle Felder ausfuellen"}), 400

    try:
        sender = _get_email_sender_instance(sender_email_input, app_password_input)
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 400

    success, message = sender.send(to_email, subject, body)
    status_code = 200 if success else 500
    return jsonify({"success": success, "message": message}), status_code


def _set_email_send_job_state(job_id: str, **kwargs) -> Dict:
    with email_send_jobs_lock:
        job = email_send_jobs.get(job_id)
        if not job:
            job = {
                "job_id": job_id,
                "status": "running",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "total": 0,
                "processed": 0,
                "sent_success": 0,
                "failed_count": 0,
                "percent": 0.0,
                "campaign_id": "",
                "message": "",
                "started_at": "",
                "estimated_remaining_seconds": None,
                "eta_at": "",
                "stop_requested": False,
                "pause_requested": False,
                "paused": False,
            }
            email_send_jobs[job_id] = job
        job.update(kwargs)
        job["updated_at"] = datetime.now().isoformat()
        return dict(job)


def _serialize_email_send_job_for_response(job: Optional[Dict]) -> Optional[Dict]:
    if not job:
        return None
    return {
        "job_id": str(job.get("job_id") or ""),
        "status": str(job.get("status") or ""),
        "created_at": str(job.get("created_at") or ""),
        "updated_at": str(job.get("updated_at") or ""),
        "started_at": str(job.get("started_at") or ""),
        "finished_at": str(job.get("finished_at") or ""),
        "campaign_id": str(job.get("campaign_id") or ""),
        "total": int(job.get("total") or 0),
        "processed": int(job.get("processed") or 0),
        "sent_success": int(job.get("sent_success") or 0),
        "failed_count": int(job.get("failed_count") or 0),
        "percent": float(job.get("percent") or 0.0),
        "message": str(job.get("message") or ""),
        "estimated_remaining_seconds": job.get("estimated_remaining_seconds"),
        "eta_at": str(job.get("eta_at") or ""),
        "stop_requested": bool(job.get("stop_requested")),
        "pause_requested": bool(job.get("pause_requested")),
        "paused": bool(job.get("paused")) or str(job.get("status") or "") == "paused",
        "success": bool(job.get("success")),
        "status_code": int(job.get("status_code") or 0),
    }


def _is_email_send_job_active(job: Optional[Dict]) -> bool:
    status = str((job or {}).get("status") or "")
    return status in {"running", "paused"}


def _get_active_email_send_job_for_campaign(campaign_id: str) -> Optional[Dict]:
    target_campaign_id = str(campaign_id or "").strip()
    if not target_campaign_id:
        return None

    latest_job = None
    with email_send_jobs_lock:
        for job in email_send_jobs.values():
            if not _is_email_send_job_active(job):
                continue
            if str(job.get("campaign_id") or "") != target_campaign_id:
                continue
            if not latest_job or str(job.get("updated_at") or "") > str(
                latest_job.get("updated_at") or ""
            ):
                latest_job = dict(job)
    return latest_job


def _get_running_email_send_job_for_campaign(campaign_id: str) -> Optional[Dict]:
    return _get_active_email_send_job_for_campaign(campaign_id)


def _list_dashboard_campaigns_with_jobs() -> List[Dict]:
    campaigns = _list_saved_email_campaigns()
    active_jobs_by_campaign: Dict[str, Dict] = {}

    with email_send_jobs_lock:
        for job in email_send_jobs.values():
            if not _is_email_send_job_active(job):
                continue
            campaign_id = str(job.get("campaign_id") or "").strip()
            if not campaign_id:
                continue
            current = active_jobs_by_campaign.get(campaign_id)
            if not current or str(job.get("updated_at") or "") > str(
                current.get("updated_at") or ""
            ):
                active_jobs_by_campaign[campaign_id] = dict(job)

    enriched_campaigns = []
    for campaign in campaigns:
        total_rows = int(campaign.get("total_rows") or 0)
        sent_rows = int(campaign.get("sent_rows") or 0)
        progress_percent = round((sent_rows / total_rows) * 100.0, 2) if total_rows else 0.0
        active_job = active_jobs_by_campaign.get(str(campaign.get("id") or ""))
        active_status = str((active_job or {}).get("status") or "")

        campaign_payload = dict(campaign)
        campaign_payload["progress_percent"] = progress_percent
        campaign_payload["is_sending"] = active_status == "running"
        campaign_payload["is_paused"] = active_status == "paused"
        campaign_payload["has_active_job"] = bool(active_job)
        campaign_payload["active_job"] = _serialize_email_send_job_for_response(active_job)
        enriched_campaigns.append(campaign_payload)

    return enriched_campaigns


def _render_app_shell(initial_section: str = "search"):
    section = str(initial_section or "search").strip().lower()
    if section not in {
        "search",
        "dashboard",
        "supabase",
        "money",
        "ausbildungen",
        "create-anschreibens",
        "send-emails",
        "google-maps",
    }:
        section = "search"
    return render_template(
        "app_shell.html",
        initial_section=section,
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
    )


def _execute_bulk_send(
    payload: Dict,
    progress_callback=None,
    stop_requested_callback=None,
    wait_if_paused_callback=None,
) -> Tuple[Dict, int]:
    save_only = bool(payload.get("save_only"))
    sender_email_input = (payload.get("sender_email_input") or "").strip()
    app_password_input = (payload.get("app_password_input") or "").strip()
    full_name_input = (payload.get("full_name_input") or "").strip()
    campaign_id = (payload.get("campaign_id") or "").strip()
    transfer_session_id = (payload.get("transfer_session_id") or "").strip()
    recipient_column = (payload.get("recipient_column") or "email").strip()
    subject_template = payload.get("subject_template") or ""
    body_template = payload.get("body_template") or ""
    limit_raw = (payload.get("limit_raw") or "").strip()
    delay_raw = str(payload.get("delay_raw") or "0").strip()
    jitter_min_raw = str(payload.get("jitter_min_raw") or "").strip()
    jitter_max_raw = str(payload.get("jitter_max_raw") or "").strip()
    batch_size_raw = str(payload.get("batch_size_raw") or "").strip()
    batch_pause_minutes_raw = str(payload.get("batch_pause_minutes_raw") or "").strip()
    payload_one_document = (
        payload.get("one_document") if isinstance(payload.get("one_document"), dict) else {}
    )

    if not subject_template or not body_template:
        return {"success": False, "message": "Betreff- und Nachrichtenvorlage sind erforderlich"}, 400

    def _estimate_remaining_send_seconds(remaining_items: int, processed_items: int = 0) -> int:
        if remaining_items <= 0:
            return 0

        if has_jitter_min and has_jitter_max:
            average_delay = (jitter_min_seconds + jitter_max_seconds) / 2.0
        else:
            average_delay = delay_seconds

        delay_events_remaining = max(remaining_items - 1, 0)
        batch_pauses_remaining = 0
        if batch_size and batch_pause_seconds > 0:
            for send_pos in range(processed_items + 1, processed_items + remaining_items):
                if send_pos % batch_size == 0:
                    batch_pauses_remaining += 1

        total_seconds = (delay_events_remaining * average_delay) + (
            batch_pauses_remaining * batch_pause_seconds
        )
        return max(0, int(round(total_seconds)))

    batch_limit: Optional[int] = None
    if limit_raw:
        try:
            limit_value = int(limit_raw)
            if limit_value <= 0:
                return {"success": False, "message": "Das Limit muss groesser als 0 sein"}, 400
            batch_limit = limit_value
        except ValueError:
            return {"success": False, "message": "Das Limit muss eine gueltige Zahl sein"}, 400

    try:
        delay_seconds = float(delay_raw)
        if delay_seconds < 0:
            return {"success": False, "message": "Die Wartezeit muss 0 oder groesser sein"}, 400
    except ValueError:
        return {"success": False, "message": "Die Wartezeit muss eine gueltige Zahl sein"}, 400

    jitter_min_seconds = 0.0
    jitter_max_seconds = 0.0
    has_jitter_min = bool(jitter_min_raw)
    has_jitter_max = bool(jitter_max_raw)
    if has_jitter_min != has_jitter_max:
        return {
            "success": False,
            "message": "Bitte Jitter-Minimum und Jitter-Maximum beide setzen oder beide leer lassen.",
        }, 400
    if has_jitter_min and has_jitter_max:
        try:
            jitter_min_seconds = float(jitter_min_raw)
            jitter_max_seconds = float(jitter_max_raw)
        except ValueError:
            return {"success": False, "message": "Jitter-Werte muessen gueltige Zahlen sein"}, 400
        if jitter_min_seconds < 0 or jitter_max_seconds < 0:
            return {"success": False, "message": "Jitter-Werte muessen 0 oder groesser sein"}, 400
        if jitter_max_seconds < jitter_min_seconds:
            return {
                "success": False,
                "message": "Jitter-Maximum muss groesser oder gleich Jitter-Minimum sein",
            }, 400

    batch_size = None
    if batch_size_raw:
        try:
            batch_size_value = int(batch_size_raw)
            if batch_size_value <= 0:
                return {"success": False, "message": "Die Batch-Groesse muss groesser als 0 sein"}, 400
            batch_size = batch_size_value
        except ValueError:
            return {"success": False, "message": "Die Batch-Groesse muss eine gueltige Zahl sein"}, 400

    batch_pause_minutes = 0.0
    if batch_pause_minutes_raw:
        try:
            batch_pause_minutes = float(batch_pause_minutes_raw)
        except ValueError:
            return {"success": False, "message": "Die Batch-Pause muss eine gueltige Zahl sein"}, 400
        if batch_pause_minutes < 0:
            return {"success": False, "message": "Die Batch-Pause muss 0 oder groesser sein"}, 400
    batch_pause_seconds = batch_pause_minutes * 60.0

    campaign = None
    transfer_anschreiben_snapshot = {}
    source_rows: List[Dict] = []
    campaign_mode = "upload"
    if campaign_id:
        campaign = _get_saved_email_campaign(campaign_id)
        if not campaign:
            return {"success": False, "message": "Gespeicherte Vorlage nicht gefunden."}, 404
        source_rows = list(campaign.get("rows") or [])
        campaign_mode = str(campaign.get("mode") or "upload")
    elif transfer_session_id:
        payload_transfer = _email_transfer_sessions.get(transfer_session_id)
        if not payload_transfer:
            return {"success": False, "message": "Transfer-Sitzung nicht gefunden."}, 400
        source_rows = list(payload_transfer.get("rows", []))
        transfer_anschreiben_snapshot = dict(
            payload_transfer.get("anschreiben_snapshot") or {}
        )
        if not source_rows:
            return {"success": False, "message": "Die Transfer-Sitzung enthält keine zu sendenden Zeilen."}, 400
        campaign_mode = "transfer"
    else:
        source_rows = list(payload.get("uploaded_rows") or [])
        if not source_rows:
            return {"success": False, "message": "Keine Datenzeilen in der hochgeladenen Datei gefunden"}, 400
        campaign_mode = "upload"

    effective_sender_email = sender_email_input
    effective_app_password = app_password_input
    if campaign:
        effective_sender_email = (
            effective_sender_email or str(campaign.get("sender_email") or "").strip()
        )
        effective_app_password = (
            effective_app_password or str(campaign.get("app_password") or "").strip()
        )
        full_name_input = full_name_input or str(campaign.get("full_name") or "").strip()

    sender = None
    if not save_only:
        sender = _get_email_sender_instance(effective_sender_email, effective_app_password)
        if not effective_sender_email:
            effective_sender_email = str(getattr(sender, "sender_email", "") or "").strip()
        if not effective_app_password:
            effective_app_password = str(getattr(sender, "password", "") or "").strip()

    attachments = list(payload.get("attachments") or [])
    existing_one_document = _normalize_one_document_config(
        campaign.get("one_document") if campaign else {}
    )
    uploaded_base_document = payload_one_document.get("base_document")
    stored_base_document = (
        _serialize_single_campaign_attachment(uploaded_base_document)
        if uploaded_base_document
        else existing_one_document.get("base_document") or {}
    )
    one_document_enabled = bool(payload_one_document.get("enabled"))
    one_document_action = str(
        payload_one_document.get("action") or existing_one_document.get("action") or "replace"
    ).strip().lower()
    if one_document_action not in ONE_DOCUMENT_ACTIONS:
        return {"success": False, "message": "One Document Mode Aktion muss Replace oder Add sein"}, 400
    one_document_page = (
        _coerce_positive_int(payload_one_document.get("page"))
        or _coerce_positive_int(existing_one_document.get("page"))
        or 1
    )
    one_document_config = _normalize_one_document_config(
        {
            "enabled": one_document_enabled,
            "page": one_document_page,
            "action": one_document_action,
            "base_document": stored_base_document,
        }
    )
    if one_document_enabled and not stored_base_document:
        return {
            "success": False,
            "message": "One Document Mode braucht ein Basis-PDF.",
        }, 400

    if not campaign:
        anschreiben = {}
        transient_design_pdf_path = ""
        if transfer_anschreiben_snapshot:
            anschreiben = _normalize_campaign_anschreiben_metadata(
                {
                    "templates": transfer_anschreiben_snapshot.get("templates") or [""],
                    "active_template_index": transfer_anschreiben_snapshot.get(
                        "active_template_index", 0
                    ),
                    "layout_options": transfer_anschreiben_snapshot.get("layout_options") or {},
                    "filename_format": transfer_anschreiben_snapshot.get(
                        "filename_format"
                    )
                    or "{{Unternehmen}}",
                }
            )

            design_payload = transfer_anschreiben_snapshot.get("design_pdf") or {}
            design_pdf_path = _restore_design_pdf_for_session(
                f"campaign_{uuid.uuid4().hex}",
                design_payload if isinstance(design_payload, dict) else {},
            )
            if design_pdf_path:
                transient_design_pdf_path = design_pdf_path
                anschreiben["design_pdf_path"] = design_pdf_path

        campaign = _save_new_email_campaign(
            mode=campaign_mode,
            rows=source_rows,
            sender_email=effective_sender_email,
            app_password=effective_app_password,
            full_name=full_name_input,
            recipient_column=recipient_column,
            subject_template=subject_template,
            body_template=body_template,
            delay_seconds=delay_seconds,
            jitter_min_seconds=jitter_min_seconds,
            jitter_max_seconds=jitter_max_seconds,
            last_limit=batch_limit,
            batch_size=batch_size,
            batch_pause_seconds=batch_pause_seconds,
            attachments=attachments,
            anschreiben=anschreiben,
            one_document=one_document_config,
        )
        campaign_id = campaign["id"]
        if campaign.get("anschreiben", {}).get("design_pdf_path"):
            campaign["anschreiben"] = _build_campaign_anschreiben_from_session(
                {
                    "templates": campaign["anschreiben"].get("templates") or [""],
                    "active_template_index": campaign["anschreiben"].get(
                        "active_template_index", 0
                    ),
                    "layout_options": campaign["anschreiben"].get("layout_options") or {},
                    "filename_format": campaign["anschreiben"].get("filename_format")
                    or "{{Unternehmen}}",
                    "design_pdf_path": campaign["anschreiben"].get("design_pdf_path") or "",
                },
                campaign_id=campaign_id,
            )
            campaign = _update_saved_email_campaign(campaign)
            if transient_design_pdf_path and os.path.exists(transient_design_pdf_path):
                try:
                    os.remove(transient_design_pdf_path)
                except OSError:
                    pass

    if campaign.get("mode") != "transfer":
        recipient_column = recipient_column or str(campaign.get("recipient_column") or "email")
    else:
        recipient_column = str(campaign.get("recipient_column") or recipient_column or "email")

    campaign["sender_email"] = effective_sender_email
    campaign["app_password"] = effective_app_password
    campaign["full_name"] = full_name_input
    campaign["name"] = full_name_input or str(campaign.get("name") or "").strip()
    campaign["subject_template"] = subject_template
    campaign["body_template"] = body_template
    campaign["delay_seconds"] = delay_seconds
    campaign["jitter_min_seconds"] = jitter_min_seconds
    campaign["jitter_max_seconds"] = jitter_max_seconds
    campaign["last_limit"] = batch_limit
    campaign["batch_size"] = batch_size
    campaign["batch_pause_seconds"] = batch_pause_seconds
    campaign["recipient_column"] = recipient_column
    campaign["one_document"] = one_document_config
    if attachments:
        campaign["attachments"] = _serialize_campaign_attachments(attachments)
    campaign["updated_at"] = datetime.now().isoformat()

    rows = list(campaign.get("rows") or [])
    total = len(rows)
    if total == 0:
        return {"success": False, "message": "Die gespeicherte Vorlage enthält keine zu sendenden Zeilen."}, 400

    if save_only:
        campaign = _update_saved_email_campaign(campaign)
        progress = _campaign_progress(campaign)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "message": (
                "Vorlage im Dashboard gespeichert.\n"
                f"Fortschritt: {progress['sent']}/{progress['total']} gesendet, {progress['remaining']} offen."
            ),
            "total": progress["total"],
            "processed": 0,
            "sent_success": 0,
            "failed_count": 0,
        }, 200

    sent_set: Set[int] = set()
    for raw_idx in campaign.get("sent_indices") or []:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < total:
            sent_set.add(idx)

    pending_indices = [idx for idx in range(total) if idx not in sent_set]
    if not pending_indices:
        _update_saved_email_campaign(campaign)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "message": f"All emails are already sent.\nProgress: {total}/{total} sent, 0 remaining.",
            "total": 0,
            "processed": 0,
            "sent_success": 0,
            "failed_count": 0,
        }, 200

    indices_to_send = pending_indices[:batch_limit] if batch_limit else pending_indices
    attachments = (
        list(payload.get("attachments") or [])
        or _deserialize_campaign_attachments(campaign.get("attachments") or [])
    )
    one_document_config = _normalize_one_document_config(campaign.get("one_document") or {})
    one_document_active = bool(one_document_config.get("enabled"))
    one_document_base_attachment = _deserialize_single_campaign_attachment(
        one_document_config.get("base_document") or {}
    )
    if one_document_active and not one_document_base_attachment:
        return {
            "success": False,
            "campaign_id": campaign_id,
            "message": "One Document Mode braucht ein gespeichertes Basis-PDF.",
            "total": 0,
            "processed": 0,
            "sent_success": 0,
            "failed_count": 0,
        }, 400

    success_count = 0
    failed = []
    processed = 0
    run_total = len(indices_to_send)

    if progress_callback:
        initial_eta_seconds = _estimate_remaining_send_seconds(run_total, processed_items=0)
        progress_callback(
            {
                "campaign_id": campaign_id,
                "total": run_total,
                "processed": 0,
                "sent_success": 0,
                "failed_count": 0,
                "message": "Starte...",
                "estimated_remaining_seconds": initial_eta_seconds,
                "eta_at": (
                    datetime.now() + timedelta(seconds=initial_eta_seconds)
                ).isoformat() if initial_eta_seconds > 0 else datetime.now().isoformat(),
            }
        )

    def _persist_campaign_progress() -> Dict:
        campaign["sent_indices"] = sorted(sent_set)
        campaign["updated_at"] = datetime.now().isoformat()
        return _update_saved_email_campaign(campaign)

    def _stop_requested() -> bool:
        return bool(stop_requested_callback and stop_requested_callback())

    def _wait_if_paused(pause_message: str = "Versand pausiert") -> bool:
        if not wait_if_paused_callback:
            return not _stop_requested()
        return bool(wait_if_paused_callback(pause_message))

    def _build_stop_response() -> Tuple[Dict, int]:
        saved_campaign = _persist_campaign_progress()
        progress = _campaign_progress(saved_campaign)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "message": (
                f"Versand gespeichert und gestoppt.\n"
                f"Fortschritt: {progress['sent']}/{progress['total']} gesendet, {progress['remaining']} offen."
            ),
            "total": run_total,
            "processed": processed,
            "sent_success": success_count,
            "failed_count": len(failed),
        }, 200

    def _sleep_between_send_attempts(send_pos: int) -> None:
        if send_pos >= run_total:
            return

        if batch_size and batch_pause_seconds > 0 and send_pos % batch_size == 0:
            if progress_callback:
                remaining_items = max(run_total - processed, 0)
                eta_seconds = _estimate_remaining_send_seconds(
                    remaining_items, processed_items=processed
                )
                progress_callback(
                    {
                        "campaign_id": campaign_id,
                        "total": run_total,
                        "processed": processed,
                        "sent_success": success_count,
                        "failed_count": len(failed),
                        "message": f"Batch pause: sleeping for {int(batch_pause_seconds)} seconds",
                        "estimated_remaining_seconds": eta_seconds,
                        "eta_at": (
                            datetime.now() + timedelta(seconds=eta_seconds)
                        ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                    }
                )
            remaining_sleep = batch_pause_seconds
            while remaining_sleep > 0:
                if not _wait_if_paused():
                    return
                if _stop_requested():
                    return
                sleep_step = min(1.0, remaining_sleep)
                time.sleep(sleep_step)
                remaining_sleep -= sleep_step
            return

        effective_delay = delay_seconds
        if jitter_max_seconds > 0 or jitter_min_seconds > 0:
            effective_delay = random.uniform(jitter_min_seconds, jitter_max_seconds)
        if effective_delay <= 0:
            return
        if progress_callback:
            remaining_items = max(run_total - processed, 0)
            eta_seconds = _estimate_remaining_send_seconds(
                remaining_items, processed_items=processed
            )
            progress_callback(
                {
                    "campaign_id": campaign_id,
                    "total": run_total,
                    "processed": processed,
                    "sent_success": success_count,
                    "failed_count": len(failed),
                    "message": f"Waiting {effective_delay:.1f}s before next email",
                    "estimated_remaining_seconds": eta_seconds,
                    "eta_at": (
                        datetime.now() + timedelta(seconds=eta_seconds)
                    ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                }
            )
        remaining_sleep = effective_delay
        while remaining_sleep > 0:
            if not _wait_if_paused():
                return
            if _stop_requested():
                return
            sleep_step = min(1.0, remaining_sleep)
            time.sleep(sleep_step)
            remaining_sleep -= sleep_step

    def _build_one_document_attachment_for_row(
        row: Dict,
        row_index: int,
        personalized_pdf: Optional[Tuple[str, bytes, str]] = None,
    ) -> Tuple[Optional[Tuple[str, bytes, str]], str]:
        if not one_document_active:
            return personalized_pdf, ""
        if not one_document_base_attachment:
            return None, "One Document Mode braucht ein Basis-PDF."

        if not personalized_pdf:
            personalized_pdf, load_error = _load_personalized_pdf_from_row(row, row_index)
            if load_error:
                return None, load_error

        try:
            base_filename, base_bytes, _base_mimetype = one_document_base_attachment
            _personalized_filename, personalized_bytes, _personalized_mimetype = personalized_pdf
            merged_bytes = _compose_one_document_pdf(
                base_pdf_bytes=base_bytes,
                personalized_pdf_bytes=personalized_bytes,
                page_number=int(one_document_config.get("page") or 1),
                action=str(one_document_config.get("action") or "replace"),
            )
        except Exception as exc:
            return None, f"Zeile {row_index + 1}: One Document PDF konnte nicht erstellt werden ({exc})"

        output_filename = _one_document_row_filename(base_filename, row, row_index)
        return (output_filename, merged_bytes, "application/pdf"), ""

    if campaign.get("mode") == "transfer":
        for send_pos, row_index in enumerate(indices_to_send, start=1):
            if not _wait_if_paused():
                return _build_stop_response()
            if _stop_requested():
                return _build_stop_response()
            row = rows[row_index]
            to_email = _normalize_email(row.get("recipient"))
            if not _is_valid_email(to_email):
                failed.append(f"Zeile {row_index + 1}: Ungültige Empfänger-E-Mail")
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            context = row.get("context") if isinstance(row.get("context"), dict) else {}
            company_name = str(row.get("company") or _extract_company_from_row(context) or "").strip()
            if not company_name:
                failed.append(f"Zeile {row_index + 1} ({to_email}): Firmenname fehlt")
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            pdf_path = str(row.get("pdf_path") or "").strip()
            if not pdf_path or not os.path.exists(pdf_path) or os.path.getsize(pdf_path) <= 0:
                failed.append(
                    f"Zeile {row_index + 1} ({to_email}): PDF fehlt für {company_name or 'Unternehmen'}"
                )
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            pdf_filename = str(row.get("filename") or "").strip() or Path(pdf_path).name
            if not pdf_filename.lower().endswith(".pdf"):
                pdf_filename = f"{pdf_filename}.pdf"

            with open(pdf_path, "rb") as fh:
                pdf_bytes = fh.read()
            if not pdf_bytes:
                failed.append(f"Zeile {row_index + 1} ({to_email}): PDF-Inhalt ist leer")
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            context.setdefault("company", company_name)
            context.setdefault("Unternehmen", company_name)
            context.setdefault("Firma", company_name)

            subject = _render_email_template_with_row(subject_template, context)
            body = _render_email_template_with_row(body_template, context)
            if not _has_meaningful_text(subject) or not _has_meaningful_text(body):
                failed.append(
                    f"Zeile {row_index + 1} ({to_email}): Betreff oder Nachricht ist nach Platzhaltern leer"
                )
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            personalized_pdf = (pdf_filename, pdf_bytes, "application/pdf")
            if one_document_active:
                row_pdf_attachment, one_document_error = _build_one_document_attachment_for_row(
                    row,
                    row_index,
                    personalized_pdf,
                )
                if one_document_error or not row_pdf_attachment:
                    failed.append(one_document_error or f"Zeile {row_index + 1}: One Document PDF fehlt")
                    processed += 1
                    if progress_callback:
                        remaining_items = max(run_total - processed, 0)
                        eta_seconds = _estimate_remaining_send_seconds(
                            remaining_items, processed_items=processed
                        )
                        progress_callback(
                            {
                                "campaign_id": campaign_id,
                                "total": run_total,
                                "processed": processed,
                                "sent_success": success_count,
                                "failed_count": len(failed),
                                "estimated_remaining_seconds": eta_seconds,
                                "eta_at": (
                                    datetime.now() + timedelta(seconds=eta_seconds)
                                ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                            }
                        )
                    continue
                row_attachments = [row_pdf_attachment] + attachments
            else:
                row_attachments = [personalized_pdf] + attachments
            ok, msg = sender.send(to_email, subject, body, attachments=row_attachments)
            if ok:
                success_count += 1
                sent_set.add(row_index)
                _persist_campaign_progress()
            else:
                failed.append(f"Row {row_index + 1} ({to_email}): {msg}")

            processed += 1
            if progress_callback:
                remaining_items = max(run_total - processed, 0)
                eta_seconds = _estimate_remaining_send_seconds(
                    remaining_items, processed_items=processed
                )
                progress_callback(
                    {
                        "campaign_id": campaign_id,
                        "total": run_total,
                        "processed": processed,
                        "sent_success": success_count,
                        "failed_count": len(failed),
                        "estimated_remaining_seconds": eta_seconds,
                        "eta_at": (
                            datetime.now() + timedelta(seconds=eta_seconds)
                        ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                    }
                )

            _sleep_between_send_attempts(send_pos)
            if _stop_requested():
                return _build_stop_response()
    else:
        for send_pos, row_index in enumerate(indices_to_send, start=1):
            if not _wait_if_paused():
                return _build_stop_response()
            if _stop_requested():
                return _build_stop_response()
            row = rows[row_index] if isinstance(rows[row_index], dict) else {}
            to_email = _normalize_email(row.get(recipient_column))
            if not _is_valid_email(to_email):
                failed.append(
                    f'Zeile {row_index + 1}: Fehlender oder ungültiger Empfänger in Spalte "{recipient_column}"'
                )
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            subject = _render_email_template_with_row(subject_template, row)
            body = _render_email_template_with_row(body_template, row)
            if not _has_meaningful_text(subject) or not _has_meaningful_text(body):
                failed.append(
                    f"Zeile {row_index + 1} ({to_email}): Betreff oder Nachricht ist nach Platzhaltern leer"
                )
                processed += 1
                if progress_callback:
                    remaining_items = max(run_total - processed, 0)
                    eta_seconds = _estimate_remaining_send_seconds(
                        remaining_items, processed_items=processed
                    )
                    progress_callback(
                        {
                            "campaign_id": campaign_id,
                            "total": run_total,
                            "processed": processed,
                            "sent_success": success_count,
                            "failed_count": len(failed),
                            "estimated_remaining_seconds": eta_seconds,
                            "eta_at": (
                                datetime.now() + timedelta(seconds=eta_seconds)
                            ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                        }
                    )
                continue

            row_attachments = attachments
            if one_document_active:
                row_pdf_attachment, one_document_error = _build_one_document_attachment_for_row(
                    row,
                    row_index,
                )
                if one_document_error or not row_pdf_attachment:
                    failed.append(one_document_error or f"Zeile {row_index + 1}: One Document PDF fehlt")
                    processed += 1
                    if progress_callback:
                        remaining_items = max(run_total - processed, 0)
                        eta_seconds = _estimate_remaining_send_seconds(
                            remaining_items, processed_items=processed
                        )
                        progress_callback(
                            {
                                "campaign_id": campaign_id,
                                "total": run_total,
                                "processed": processed,
                                "sent_success": success_count,
                                "failed_count": len(failed),
                                "estimated_remaining_seconds": eta_seconds,
                                "eta_at": (
                                    datetime.now() + timedelta(seconds=eta_seconds)
                                ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                            }
                        )
                    continue
                row_attachments = [row_pdf_attachment] + attachments

            ok, msg = sender.send(to_email, subject, body, attachments=row_attachments)
            if ok:
                success_count += 1
                sent_set.add(row_index)
                _persist_campaign_progress()
            else:
                failed.append(f"Row {row_index + 1} ({to_email}): {msg}")

            processed += 1
            if progress_callback:
                remaining_items = max(run_total - processed, 0)
                eta_seconds = _estimate_remaining_send_seconds(
                    remaining_items, processed_items=processed
                )
                progress_callback(
                    {
                        "campaign_id": campaign_id,
                        "total": run_total,
                        "processed": processed,
                        "sent_success": success_count,
                        "failed_count": len(failed),
                        "estimated_remaining_seconds": eta_seconds,
                        "eta_at": (
                            datetime.now() + timedelta(seconds=eta_seconds)
                        ).isoformat() if eta_seconds > 0 else datetime.now().isoformat(),
                    }
                )

            _sleep_between_send_attempts(send_pos)
            if _stop_requested():
                return _build_stop_response()

    campaign = _persist_campaign_progress()
    progress = _campaign_progress(campaign)

    if success_count == 0:
        details = "\n".join(failed[:20])
        summary = [
            f"0/{len(indices_to_send)} E-Mails in diesem Lauf gesendet.",
            f"Fortschritt: {progress['sent']}/{progress['total']} gesendet, {progress['remaining']} offen.",
        ]
        if details:
            summary.append(details)
        return {
            "success": False,
            "campaign_id": campaign_id,
            "message": "\n".join(summary),
            "total": run_total,
            "processed": processed,
            "sent_success": success_count,
            "failed_count": len(failed),
        }, 500

    summary = [
        f"{success_count}/{len(indices_to_send)} E-Mails in diesem Lauf erfolgreich gesendet.",
        f"Fortschritt: {progress['sent']}/{progress['total']} gesendet, {progress['remaining']} offen.",
    ]
    if failed:
        summary.append("Fehlgeschlagene Zeilen:")
        summary.extend(failed[:20])
        if len(failed) > 20:
            summary.append(f"... und {len(failed) - 20} weitere Fehler")

    return {
        "success": True,
        "campaign_id": campaign_id,
        "message": "\n".join(summary),
        "total": run_total,
        "processed": processed,
        "sent_success": success_count,
        "failed_count": len(failed),
    }, 200


def _build_bulk_payload_from_request() -> Dict:
    campaign_id = (request.form.get("campaign_id") or "").strip()
    transfer_session_id = (request.form.get("transfer_session_id") or "").strip()
    payload = {
        "full_name_input": request.form.get("full_name"),
        "sender_email_input": request.form.get("sender_email"),
        "app_password_input": request.form.get("app_password"),
        "campaign_id": campaign_id,
        "transfer_session_id": transfer_session_id,
        "recipient_column": request.form.get("recipient_column"),
        "subject_template": request.form.get("subject_template"),
        "body_template": request.form.get("body_template"),
        "limit_raw": request.form.get("limit"),
        "delay_raw": request.form.get("delay_seconds"),
        "jitter_min_raw": request.form.get("jitter_min_seconds"),
        "jitter_max_raw": request.form.get("jitter_max_seconds"),
        "batch_size_raw": request.form.get("batch_size"),
        "batch_pause_minutes_raw": request.form.get("batch_pause_minutes"),
        "attachments": _parse_uploaded_attachments(request.files.getlist("attachments")),
        "one_document": {
            "enabled": str(request.form.get("one_document_enabled") or "").lower()
            in {"1", "true", "on", "yes"},
            "page": request.form.get("one_document_page"),
            "action": request.form.get("one_document_action"),
            "base_document": _parse_uploaded_pdf_attachment(
                request.files.get("one_document_base_file"),
                "Basis-Dokument",
            ),
        },
    }
    if not campaign_id and not transfer_session_id:
        payload["uploaded_rows"] = _load_bulk_rows_from_upload(request.files.get("data_file"))
    return payload


@app.route("/send-bulk", methods=["POST"])
def send_bulk_email():
    try:
        payload = _build_bulk_payload_from_request()
        response_payload, status_code = _execute_bulk_send(payload)
        return jsonify(response_payload), status_code
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"Unerwarteter Fehler: {exc}"}), 500


@app.route("/api/campaign/save", methods=["POST"])
def save_campaign_template():
    try:
        payload = _build_bulk_payload_from_request()
        payload["save_only"] = True
        response_payload, status_code = _execute_bulk_send(payload)
        return jsonify(response_payload), status_code
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"Unerwarteter Fehler: {exc}"}), 500


def _run_async_bulk_send_job(job_id: str, payload: Dict):
    try:
        started_at = datetime.now()

        def _stop_requested():
            with email_send_jobs_lock:
                job = email_send_jobs.get(job_id) or {}
                return bool(job.get("stop_requested"))

        def _wait_if_paused(pause_message: str = "Versand pausiert") -> bool:
            pause_state_applied = False
            while True:
                with email_send_jobs_lock:
                    job = email_send_jobs.get(job_id) or {}
                    stop_requested = bool(job.get("stop_requested"))
                    pause_requested = bool(job.get("pause_requested"))
                    status = str(job.get("status") or "")

                if stop_requested:
                    return False

                if not pause_requested and status != "paused":
                    return True

                if not pause_state_applied:
                    _set_email_send_job_state(
                        job_id,
                        status="paused",
                        paused=True,
                        message=pause_message,
                        estimated_remaining_seconds=None,
                        eta_at="",
                    )
                    pause_state_applied = True

                time.sleep(0.35)

        def _progress(data: Dict):
            total = int(data.get("total") or 0)
            processed = int(data.get("processed") or 0)
            percent = round((processed / total) * 100, 2) if total else 0.0
            estimated_remaining_seconds = data.get("estimated_remaining_seconds")
            if processed > 0 and total > processed:
                elapsed_seconds = max((datetime.now() - started_at).total_seconds(), 0.0)
                rate_seconds = elapsed_seconds / processed if processed else 0.0
                runtime_eta_seconds = int(round(rate_seconds * (total - processed)))
                if estimated_remaining_seconds is None:
                    estimated_remaining_seconds = runtime_eta_seconds
                else:
                    estimated_remaining_seconds = max(
                        int(estimated_remaining_seconds), runtime_eta_seconds
                    )
            elif estimated_remaining_seconds is not None:
                estimated_remaining_seconds = int(estimated_remaining_seconds)

            eta_at = ""
            if estimated_remaining_seconds is not None:
                eta_at = (datetime.now() + timedelta(seconds=estimated_remaining_seconds)).isoformat()
            _set_email_send_job_state(
                job_id,
                status="running",
                paused=False,
                started_at=started_at.isoformat(),
                total=total,
                processed=processed,
                sent_success=int(data.get("sent_success") or 0),
                failed_count=int(data.get("failed_count") or 0),
                campaign_id=str(data.get("campaign_id") or ""),
                percent=percent,
                message=str(data.get("message") or ""),
                estimated_remaining_seconds=estimated_remaining_seconds,
                eta_at=eta_at,
            )

        response_payload, status_code = _execute_bulk_send(
            payload,
            progress_callback=_progress,
            stop_requested_callback=_stop_requested,
            wait_if_paused_callback=_wait_if_paused,
        )
        processed = int(response_payload.get("processed") or 0)
        total = int(response_payload.get("total") or 0)
        percent = round((processed / total) * 100, 2) if total else 100.0
        _set_email_send_job_state(
            job_id,
            status="completed" if status_code < 400 else "failed",
            paused=False,
            pause_requested=False,
            started_at=started_at.isoformat(),
            total=total,
            processed=processed,
            sent_success=int(response_payload.get("sent_success") or 0),
            failed_count=int(response_payload.get("failed_count") or 0),
            campaign_id=str(response_payload.get("campaign_id") or ""),
            percent=percent,
            success=bool(response_payload.get("success")),
            message=str(response_payload.get("message") or ""),
            estimated_remaining_seconds=0,
            eta_at=datetime.now().isoformat(),
            stop_requested=_stop_requested(),
            status_code=status_code,
            finished_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        _set_email_send_job_state(
            job_id,
            status="failed",
            paused=False,
            pause_requested=False,
            success=False,
            message=f"Unerwarteter Fehler: {exc}",
            estimated_remaining_seconds=None,
            eta_at="",
            status_code=500,
            finished_at=datetime.now().isoformat(),
        )


@app.route("/api/send-bulk/start", methods=["POST"])
def start_bulk_email_job():
    try:
        campaign_id = (request.form.get("campaign_id") or "").strip()
        if campaign_id:
            active_job = _get_active_email_send_job_for_campaign(campaign_id)
            if active_job:
                return jsonify(
                    {
                        "success": True,
                        "job_id": active_job["job_id"],
                        "already_running": True,
                        "message": "Für diese Vorlage existiert bereits ein laufender oder pausierter Massenversand.",
                    }
                )

        payload = _build_bulk_payload_from_request()

        job_id = str(uuid.uuid4())
        _set_email_send_job_state(
            job_id,
            status="running",
            message="Starte...",
            started_at=datetime.now().isoformat(),
            campaign_id=campaign_id,
            estimated_remaining_seconds=None,
            eta_at="",
            pause_requested=False,
            paused=False,
        )
        thread = threading.Thread(target=_run_async_bulk_send_job, args=(job_id, payload), daemon=True)
        thread.start()
        return jsonify({"success": True, "job_id": job_id})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"Unerwarteter Fehler: {exc}"}), 500


@app.route("/api/send-bulk/status/<job_id>", methods=["GET"])
def get_bulk_email_job_status(job_id: str):
    with email_send_jobs_lock:
        job = email_send_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Versandauftrag nicht gefunden"}), 404
        return jsonify({"success": True, "job": _serialize_email_send_job_for_response(job)})


@app.route("/api/send-bulk/active", methods=["GET"])
def get_active_bulk_email_job():
    campaign_id = (request.args.get("campaign_id") or "").strip()
    if not campaign_id:
        return jsonify({"success": False, "message": "campaign_id fehlt"}), 400

    job = _get_active_email_send_job_for_campaign(campaign_id)
    return jsonify({"success": True, "job": _serialize_email_send_job_for_response(job)})


@app.route("/api/send-bulk/pause/<job_id>", methods=["POST"])
def pause_bulk_email_job(job_id: str):
    with email_send_jobs_lock:
        job = email_send_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Versandauftrag nicht gefunden"}), 404
        if str(job.get("status") or "") != "running":
            return jsonify({"success": False, "message": "Versandauftrag laeuft aktuell nicht"}), 400
        job["pause_requested"] = True
        job["updated_at"] = datetime.now().isoformat()
    return jsonify({"success": True, "message": "Pause angefordert"})


@app.route("/api/send-bulk/continue/<job_id>", methods=["POST"])
def continue_bulk_email_job(job_id: str):
    with email_send_jobs_lock:
        job = email_send_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Versandauftrag nicht gefunden"}), 404
        if str(job.get("status") or "") != "paused":
            return jsonify({"success": False, "message": "Versandauftrag ist nicht pausiert"}), 400
        job["pause_requested"] = False
        job["paused"] = False
        job["status"] = "running"
        job["message"] = "Versand wird fortgesetzt..."
        job["updated_at"] = datetime.now().isoformat()
    return jsonify({"success": True, "message": "Versand wird fortgesetzt"})


@app.route("/api/send-bulk/stop/<job_id>", methods=["POST"])
def stop_bulk_email_job(job_id: str):
    with email_send_jobs_lock:
        job = email_send_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Versandauftrag nicht gefunden"}), 404
        if not _is_email_send_job_active(job):
            return jsonify({"success": False, "message": "Versandauftrag laeuft nicht mehr"}), 400
        job["stop_requested"] = True
        job["pause_requested"] = False
        job["paused"] = False
        job["updated_at"] = datetime.now().isoformat()
    return jsonify({"success": True, "message": "Speichern und Stoppen angefordert"})


def _sanitize_export_slug(value: str, fallback: str = "export") -> str:
    raw = (value or "").strip().lower()
    sanitized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return sanitized or fallback


def _build_download_filename(keyword: str, fallback: str) -> str:
    raw = str(keyword or "").strip()
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return f"{cleaned or fallback}.xlsx"


def _save_auto_extraction_export_records(
    records: List[Dict],
    keyword: str,
    fallback_slug: str,
    suffix: str = "",
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    slug = _sanitize_export_slug(keyword, fallback=fallback_slug)
    normalized_suffix = str(suffix or "").strip()
    file_stem = f"{timestamp}_{slug}"
    if normalized_suffix:
        file_stem = f"{file_stem}_{normalized_suffix}"

    file_path = AUTO_EXTRACTION_EXPORT_DIR / f"{file_stem}.xlsx"
    pd.DataFrame(records).to_excel(file_path, index=False)
    return file_path


def _run_parallel_scrape_task(
    keyword: str, location: str, max_jobs: int, published_since: str = "all"
) -> List[Dict]:
    scraper = EnhancedJobScraper()
    return scraper.fetch_all_jobs(
        keyword,
        location,
        max_jobs=max_jobs,
        published_since_days=_published_since_to_days(published_since),
    )


def _run_parallel_scrape_job(job_id: str, tasks: List[Dict], max_jobs: int):
    try:
        with parallel_scrape_jobs_lock:
            job = parallel_scrape_jobs.get(job_id) or {}
            job["status"] = "running"
            job["started_at"] = datetime.now().isoformat()
            parallel_scrape_jobs[job_id] = job

        def _set_task_state(task_id: str, **kwargs):
            with parallel_scrape_jobs_lock:
                active_job = parallel_scrape_jobs.get(job_id)
                if not active_job:
                    return
                task_state = active_job["tasks"].get(task_id) or {}
                task_state.update(kwargs)
                task_state["updated_at"] = datetime.now().isoformat()
                active_job["tasks"][task_id] = task_state
                active_job["updated_at"] = datetime.now().isoformat()

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_map = {}
            for task in tasks:
                task_id = task["task_id"]
                _set_task_state(task_id, status="running")
                future = executor.submit(
                    _run_parallel_scrape_task,
                    task["keyword"],
                    task["location"],
                    max_jobs,
                    task.get("published_since", "all"),
                )
                future_map[future] = task

            for future in as_completed(future_map):
                task = future_map[future]
                task_id = task["task_id"]
                try:
                    jobs = future.result()
                    _set_task_state(
                        task_id,
                        status="completed",
                        total_jobs=len(jobs),
                        jobs=jobs,
                        email_file_name="",
                        email_file_path="",
                        extraction_status={
                            "is_running": False,
                            "completed": False,
                            "failed": False,
                            "current_index": 0,
                            "total_jobs": len(jobs),
                            "emails_found": 0,
                            "captchas_solved": 0,
                            "failed_jobs": 0,
                            "last_error": "",
                            "started_at": "",
                            "finished_at": "",
                        },
                    )
                except Exception as exc:
                    _set_task_state(task_id, status="failed", error=str(exc))

        with parallel_scrape_jobs_lock:
            active_job = parallel_scrape_jobs.get(job_id) or {}
            task_values = list((active_job.get("tasks") or {}).values())
            all_done = bool(task_values) and all(t.get("status") in {"completed", "failed"} for t in task_values)
            has_failures = any(t.get("status") == "failed" for t in task_values)
            active_job["status"] = "failed" if has_failures and all_done else "completed"
            active_job["finished_at"] = datetime.now().isoformat()
            active_job["updated_at"] = datetime.now().isoformat()
            parallel_scrape_jobs[job_id] = active_job
    except Exception as exc:
        with parallel_scrape_jobs_lock:
            active_job = parallel_scrape_jobs.get(job_id) or {}
            active_job["status"] = "failed"
            active_job["error"] = str(exc)
            active_job["finished_at"] = datetime.now().isoformat()
            active_job["updated_at"] = datetime.now().isoformat()
            parallel_scrape_jobs[job_id] = active_job


@app.route("/api/parallel-scrape/start", methods=["POST"])
def start_parallel_scrape():
    try:
        data = request.get_json(silent=True) or {}
        raw_tasks = data.get("tasks") or []
        if not isinstance(raw_tasks, list):
            return jsonify({"success": False, "message": "tasks must be a list"}), 400

        max_jobs_raw = data.get("max_jobs", DEFAULT_MAX_JOBS)
        try:
            max_jobs = int(max_jobs_raw)
            if max_jobs <= 0:
                raise ValueError
        except Exception:
            return jsonify({"success": False, "message": "max_jobs must be a positive number"}), 400

        tasks: List[Dict] = []
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword") or "").strip()
            location = str(item.get("location") or "").strip()
            published_since = _normalize_published_since(item.get("published_since", "all"))
            if not keyword:
                continue
            task_id = str(uuid.uuid4())
            tasks.append(
                {
                    "task_id": task_id,
                    "keyword": keyword,
                    "location": location,
                    "published_since": published_since,
                }
            )

        if len(tasks) < 2:
            return jsonify({"success": False, "message": "Provide at least 2 keywords to run in parallel"}), 400

        job_id = str(uuid.uuid4())
        with parallel_scrape_jobs_lock:
            parallel_scrape_jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "max_jobs": max_jobs,
                "tasks": {
                    task["task_id"]: {
                        "task_id": task["task_id"],
                        "keyword": task["keyword"],
                        "location": task["location"],
                        "published_since": task.get("published_since", "all"),
                        "status": "queued",
                        "total_jobs": 0,
                        "jobs": [],
                        "email_file_name": "",
                        "email_file_path": "",
                        "extraction_status": {
                            "is_running": False,
                            "completed": False,
                            "failed": False,
                            "current_index": 0,
                            "total_jobs": 0,
                            "emails_found": 0,
                            "captchas_solved": 0,
                            "failed_jobs": 0,
                            "last_error": "",
                            "started_at": "",
                            "finished_at": "",
                        },
                        "error": "",
                        "updated_at": datetime.now().isoformat(),
                    }
                    for task in tasks
                },
            }

        thread = threading.Thread(
            target=_run_parallel_scrape_job,
            args=(job_id, tasks, max_jobs),
            daemon=True,
        )
        thread.start()
        return jsonify({"success": True, "job_id": job_id})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/parallel-scrape/status/<job_id>", methods=["GET"])
def parallel_scrape_status(job_id: str):
    with parallel_scrape_jobs_lock:
        job = parallel_scrape_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Parallel scrape job not found"}), 404
        tasks_raw = list((job.get("tasks") or {}).values())
        tasks = []
        for item in tasks_raw:
            extraction = item.get("extraction_status") or {}
            tasks.append(
                {
                    "task_id": item.get("task_id"),
                    "keyword": item.get("keyword"),
                    "location": item.get("location"),
                    "published_since": item.get("published_since", "all"),
                    "status": item.get("status"),
                    "total_jobs": int(item.get("total_jobs") or 0),
                    "email_file_name": item.get("email_file_name", ""),
                    "has_email_file": bool(item.get("email_file_path")),
                    "error": item.get("error", ""),
                    "updated_at": item.get("updated_at", ""),
                    "extraction_status": {
                        "is_running": bool(extraction.get("is_running")),
                        "completed": bool(extraction.get("completed")),
                        "failed": bool(extraction.get("failed")),
                        "current_index": int(extraction.get("current_index") or 0),
                        "total_jobs": int(extraction.get("total_jobs") or 0),
                        "emails_found": int(extraction.get("emails_found") or 0),
                        "captchas_solved": int(extraction.get("captchas_solved") or 0),
                        "failed_jobs": int(extraction.get("failed_jobs") or 0),
                        "last_error": extraction.get("last_error", ""),
                        "started_at": extraction.get("started_at", ""),
                        "finished_at": extraction.get("finished_at", ""),
                    },
                }
            )
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        failed = sum(1 for t in tasks if t.get("status") == "failed")
        running = sum(1 for t in tasks if t.get("status") == "running")
        payload = dict(job)
        payload["tasks"] = tasks
        payload["summary"] = {
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "running_tasks": running,
            "percent": round(((completed + failed) / total) * 100, 2) if total else 0.0,
        }
        return jsonify({"success": True, "job": payload})


@app.route("/api/parallel-scrape/download/<job_id>/<task_id>", methods=["GET"])
def download_parallel_scrape_export(job_id: str, task_id: str):
    with parallel_scrape_jobs_lock:
        job = parallel_scrape_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Parallel scrape job not found"}), 404
        task = (job.get("tasks") or {}).get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        extraction_status = task.get("extraction_status") or {}
        if not extraction_status.get("completed"):
            return jsonify({"error": "Emails are not collected yet for this task"}), 400
        file_path = str(task.get("email_file_path") or "").strip()
        file_name = str(task.get("email_file_name") or "").strip()

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "Export file not found"}), 404
    return send_file(file_path, as_attachment=True, download_name=file_name or Path(file_path).name)


def _run_parallel_task_auto_extraction(job_id: str, task_id: str):
    extractor = None
    try:
        with parallel_scrape_jobs_lock:
            job = parallel_scrape_jobs.get(job_id)
            if not job:
                return
            task = (job.get("tasks") or {}).get(task_id)
            if not task:
                return
            jobs = task.get("jobs") or []
            extraction = task.get("extraction_status") or {}
            extraction.update(
                {
                    "is_running": True,
                    "completed": False,
                    "failed": False,
                    "current_index": int(extraction.get("current_index") or 0),
                    "total_jobs": len(jobs),
                    "last_error": "",
                    "started_at": datetime.now().isoformat(),
                    "finished_at": "",
                }
            )
            task["extraction_status"] = extraction
            task["updated_at"] = datetime.now().isoformat()
            job["updated_at"] = datetime.now().isoformat()

        start_index = int(extraction.get("current_index") or 0)
        existing_emails = _extract_valid_emails_from_records(jobs[:start_index])
        extractor = WorkingEmailExtractor(
            captcha_userid=CAPTCHA_USERID,
            captcha_apikey=CAPTCHA_APIKEY,
            headless=False,
            known_emails=existing_emails,
        )

        for i in range(start_index, len(jobs)):
            jobs[i] = extractor.process_job(jobs[i])
            with parallel_scrape_jobs_lock:
                job = parallel_scrape_jobs.get(job_id)
                if not job:
                    return
                task = (job.get("tasks") or {}).get(task_id)
                if not task:
                    return
                extraction = task.get("extraction_status") or {}
                extraction["current_index"] = i + 1
                extraction["emails_found"] = int(extractor.stats.get("emails_found") or 0)
                extraction["captchas_solved"] = int(extractor.stats.get("captchas_solved") or 0)
                extraction["failed_jobs"] = int(extractor.stats.get("failed") or 0)
                task["jobs"] = jobs
                task["extraction_status"] = extraction
                task["updated_at"] = datetime.now().isoformat()
                job["updated_at"] = datetime.now().isoformat()
            time.sleep(1)

        prepared_rows = _prepare_download_jobs(jobs)
        if prepared_rows:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = _sanitize_export_slug(task.get("keyword"), fallback=f"task_{task_id[:6]}")
            file_name = f"{timestamp}_{slug}_with_emails.xlsx"
            file_path = PARALLEL_EXPORT_DIR / file_name
            pd.DataFrame(prepared_rows).to_excel(file_path, index=False)
        else:
            file_name = ""
            file_path = ""

        with parallel_scrape_jobs_lock:
            job = parallel_scrape_jobs.get(job_id)
            if not job:
                return
            task = (job.get("tasks") or {}).get(task_id)
            if not task:
                return
            extraction = task.get("extraction_status") or {}
            extraction.update(
                {
                    "is_running": False,
                    "completed": True,
                    "failed": False,
                    "current_index": len(jobs),
                    "total_jobs": len(jobs),
                    "emails_found": int(extractor.stats.get("emails_found") or 0),
                    "captchas_solved": int(extractor.stats.get("captchas_solved") or 0),
                    "failed_jobs": int(extractor.stats.get("failed") or 0),
                    "finished_at": datetime.now().isoformat(),
                }
            )
            task["jobs"] = jobs
            task["email_file_name"] = file_name
            task["email_file_path"] = str(file_path) if file_path else ""
            task["extraction_status"] = extraction
            task["updated_at"] = datetime.now().isoformat()
            job["updated_at"] = datetime.now().isoformat()
    except Exception as exc:
        with parallel_scrape_jobs_lock:
            job = parallel_scrape_jobs.get(job_id)
            if job:
                task = (job.get("tasks") or {}).get(task_id)
                if task:
                    extraction = task.get("extraction_status") or {}
                    extraction.update(
                        {
                            "is_running": False,
                            "completed": False,
                            "failed": True,
                            "last_error": str(exc),
                            "finished_at": datetime.now().isoformat(),
                        }
                    )
                    task["extraction_status"] = extraction
                    task["updated_at"] = datetime.now().isoformat()
                    job["updated_at"] = datetime.now().isoformat()
    finally:
        if extractor:
            extractor.close()


@app.route("/api/parallel-scrape/collect-emails/<job_id>/<task_id>", methods=["POST"])
def parallel_collect_emails(job_id: str, task_id: str):
    with parallel_scrape_jobs_lock:
        job = parallel_scrape_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Parallel scrape job not found"}), 404
        task = (job.get("tasks") or {}).get(task_id)
        if not task:
            return jsonify({"success": False, "message": "Task not found"}), 404
        if task.get("status") != "completed":
            return jsonify({"success": False, "message": "Task scraping is not completed yet"}), 400
        extraction = task.get("extraction_status") or {}
        if extraction.get("is_running"):
            return jsonify({"success": True, "message": "Email collection already running"})
        if extraction.get("completed"):
            return jsonify({"success": True, "message": "Emails already collected"})

    thread = threading.Thread(
        target=_run_parallel_task_auto_extraction,
        args=(job_id, task_id),
        daemon=True,
    )
    thread.start()
    return jsonify({"success": True, "message": "Email collection started"})


@app.route("/api/parallel-scrape/use-for-anschreiben/<job_id>/<task_id>", methods=["POST"])
def parallel_use_for_anschreiben(job_id: str, task_id: str):
    with parallel_scrape_jobs_lock:
        job = parallel_scrape_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Parallel scrape job not found"}), 404
        task = (job.get("tasks") or {}).get(task_id)
        if not task:
            return jsonify({"success": False, "message": "Task not found"}), 404
        extraction = task.get("extraction_status") or {}
        if not extraction.get("completed"):
            return jsonify({"success": False, "message": "Collect emails first"}), 400
        jobs = list(task.get("jobs") or [])

    prepared_jobs = _prepare_download_jobs(jobs)
    if not prepared_jobs:
        return jsonify({"success": False, "message": "No collected jobs with valid emails found"}), 400

    with status_lock:
        auto_extraction_status["jobs"] = prepared_jobs
        auto_extraction_status["total_jobs"] = len(prepared_jobs)
        auto_extraction_status["current_index"] = len(prepared_jobs)
        auto_extraction_status["emails_found"] = len(prepared_jobs)
        auto_extraction_status["is_running"] = False
        auto_extraction_status["paused"] = False
        auto_extraction_status["stop_requested"] = False
        auto_extraction_status["continue_requested"] = False
        auto_extraction_status["last_error"] = ""

    return jsonify({"success": True, "redirect_url": "/create-anschreibens"})


@app.route("/search", methods=["POST"])
def search():
    keyword = request.form.get("keyword", "").strip()
    location = request.form.get("location", "").strip()
    published_since = _normalize_published_since(request.form.get("published_since", "all"))

    try:
        scraper = EnhancedJobScraper()
        jobs = scraper.fetch_all_jobs(
            keyword,
            location,
            max_jobs=DEFAULT_MAX_JOBS,
            published_since_days=_published_since_to_days(published_since),
        )

        search_cache["jobs"] = jobs
        search_cache["keyword"] = keyword
        search_cache["location"] = location
        search_cache["published_since"] = published_since
        _save_search_cache_to_disk(jobs, keyword, location, published_since)
        session["last_search_meta"] = {
            "keyword": keyword,
            "location": location,
            "published_since": published_since,
            "total": len(jobs),
        }

        return render_template(
            "results.html",
            jobs=jobs,
            keyword=keyword,
            location=location,
            published_since=published_since,
            total=len(jobs),
        )
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@app.route("/api/search")
def api_search():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    published_since = _normalize_published_since(request.args.get("published_since", "all"))
    max_jobs = int(request.args.get("max_jobs", DEFAULT_MAX_JOBS))

    scraper = EnhancedJobScraper()
    jobs = scraper.fetch_all_jobs(
        keyword,
        location,
        max_jobs=max_jobs,
        published_since_days=_published_since_to_days(published_since),
    )

    search_cache["jobs"] = jobs
    search_cache["keyword"] = keyword
    search_cache["location"] = location
    search_cache["published_since"] = published_since
    _save_search_cache_to_disk(jobs, keyword, location, published_since)

    return jsonify(
        {
            "status": "success",
            "total": len(jobs),
            "published_since": published_since,
            "jobs": jobs,
        }
    )


@app.route("/api/inline/auto-jobs/start", methods=["POST"])
@app.route("/api/inline/start-auto-extraction", methods=["POST"])
def api_inline_start_auto_extraction():
    data = request.get_json(silent=True) or {}
    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return jsonify({"success": False, "message": "Keine Stellen für die Extraktion übergeben"}), 400

    jobs = [dict(item) for item in raw_jobs if isinstance(item, dict)]
    if not jobs:
        return jsonify({"success": False, "message": "Keine gültigen Stellen übergeben"}), 400

    keyword = str(data.get("keyword") or "").strip()
    location = str(data.get("location") or "").strip()
    published_since = _normalize_published_since(data.get("published_since", "all"))

    search_cache["jobs"] = jobs
    search_cache["keyword"] = keyword
    search_cache["location"] = location
    search_cache["published_since"] = published_since
    _save_search_cache_to_disk(jobs, keyword, location, published_since)

    job_id = _create_auto_extraction_job(jobs, keyword, location, published_since)
    thread = threading.Thread(target=_run_auto_extraction_job, args=(job_id,), daemon=True)
    thread.start()

    return jsonify(
        {
            "success": True,
            "job_id": job_id,
            "total_jobs": len(jobs),
        }
    )


@app.route("/api/inline/auto-jobs/status/<job_id>", methods=["GET"])
def api_inline_auto_job_status(job_id: str):
    with auto_extraction_jobs_lock:
        job = auto_extraction_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Auto-Extraktionsjob nicht gefunden"}), 404
        total = int(job.get("total_jobs") or 0)
        current = int(job.get("current_index") or 0)
        payload = {
            "success": True,
            "job": {
                "job_id": job.get("job_id"),
                "keyword": job.get("keyword", ""),
                "location": job.get("location", ""),
                "published_since": job.get("published_since", "all"),
                "is_running": bool(job.get("is_running")),
                "stop_requested": bool(job.get("stop_requested")),
                "paused": bool(job.get("paused")),
                "current_index": current,
                "total_jobs": total,
                "emails_found": int(job.get("emails_found") or 0),
                "captchas_solved": int(job.get("captchas_solved") or 0),
                "failed": int(job.get("failed") or 0),
                "last_error": str(job.get("last_error") or ""),
                "percentage": (current / total * 100) if total else 0,
                "updated_at": job.get("updated_at", ""),
                "finished_at": job.get("finished_at", ""),
            },
        }
    return jsonify(payload)


@app.route("/api/inline/auto-jobs/continue/<job_id>", methods=["POST"])
def api_inline_continue_auto_job(job_id: str):
    with auto_extraction_jobs_lock:
        job = auto_extraction_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Auto-Extraktionsjob nicht gefunden"}), 404
        if not job.get("paused"):
            return jsonify({"success": False, "message": "Auto-Extraktionsjob ist nicht pausiert"}), 400
        job["is_running"] = True
        job["paused"] = False
        job["continue_requested"] = True
        job["updated_at"] = datetime.now().isoformat()
    return jsonify({"success": True, "message": "Fortsetzen angefordert"})


@app.route("/api/inline/auto-jobs/stop/<job_id>", methods=["POST"])
def api_inline_stop_auto_job(job_id: str):
    with auto_extraction_jobs_lock:
        job = auto_extraction_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Auto-Extraktionsjob nicht gefunden"}), 404
        job["is_running"] = False
        job["stop_requested"] = True
        job["paused"] = False
        job["continue_requested"] = False
        job["updated_at"] = datetime.now().isoformat()
    return jsonify({"success": True, "message": "Stop der Auto-Extraktion angefordert"})


@app.route("/api/inline/auto-jobs/download/<job_id>", methods=["GET"])
def api_inline_download_auto_job(job_id: str):
    with auto_extraction_jobs_lock:
        job = auto_extraction_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Auto-Extraktionsjob nicht gefunden"}), 404
        jobs = list(job.get("jobs") or [])
        keyword = str(job.get("keyword") or "")

    prepared_jobs = _prepare_download_jobs(jobs)
    if not prepared_jobs:
        return jsonify({"success": False, "message": "Keine Stellen mit gültiger E-Mail verfügbar"}), 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _sanitize_export_slug(keyword, fallback=f"auto_{job_id[:8]}")
    file_path = AUTO_EXTRACTION_EXPORT_DIR / f"{timestamp}_{slug}_{job_id[:8]}.xlsx"
    pd.DataFrame(prepared_jobs).to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True, download_name=file_path.name)


@app.route("/api/inline/auto-jobs/use-for-anschreiben/<job_id>", methods=["POST"])
def api_inline_use_auto_job_for_anschreiben(job_id: str):
    with auto_extraction_jobs_lock:
        job = auto_extraction_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Auto-Extraktionsjob nicht gefunden"}), 404
        jobs = list(job.get("jobs") or [])

    prepared_jobs = _prepare_download_jobs(jobs)
    if not prepared_jobs:
        return jsonify({"success": False, "message": "Keine gesammelten Stellen mit gültiger E-Mail gefunden"}), 400

    with status_lock:
        auto_extraction_status["jobs"] = prepared_jobs
        auto_extraction_status["total_jobs"] = len(prepared_jobs)
        auto_extraction_status["current_index"] = len(prepared_jobs)
        auto_extraction_status["emails_found"] = len(prepared_jobs)
        auto_extraction_status["is_running"] = False
        auto_extraction_status["paused"] = False
        auto_extraction_status["stop_requested"] = False
        auto_extraction_status["continue_requested"] = False
        auto_extraction_status["last_error"] = ""

    return jsonify({"success": True, "redirect_url": "/create-anschreibens?autoload=auto"})


@app.route("/api/health", methods=["GET"])
def pdf_health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


@app.route("/api/upload-excel", methods=["POST"])
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

        return jsonify(
            {
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
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/load-collected-jobs", methods=["POST"])
def pdf_load_collected_jobs():
    try:
        data = request.get_json(silent=True) or {}
        payload, status_code = _build_pdf_autoload_session_payload(data.get("source", "latest"))
        return jsonify(payload), status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/save-template", methods=["POST"])
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
        _persist_linked_campaign_anschreiben(str(session_id))

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

        return jsonify(
            {
                "success": True,
                "message": "Template saved successfully",
                "missing_placeholders": missing_placeholders,
                "template_count": len(templates),
                "active_template_index": active_template_index,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/upload-design-pdf", methods=["POST"])
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
        _persist_linked_campaign_anschreiben(str(session_id))
        return jsonify({"success": True, "filename": filepath.name})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/preview-pdf", methods=["POST"])
def pdf_preview_pdf():
    try:
        _, PDFService, TemplateService = _load_pdf_backend_services()
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        row_index = int(data.get("row_index", 0))
        layout_options = data.get("layout_options") or {}

        if session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        session_data = _pdf_sessions[session_id]
        templates = [
            str(template or "")
            for template in (session_data.get("templates") or [session_data.get("template", "")])
        ]
        non_empty_templates = [template for template in templates if template.strip()]
        if not non_empty_templates:
            return jsonify({"error": "No template saved"}), 400

        rows = session_data["rows"]
        if row_index < 0 or row_index >= len(rows):
            return jsonify({"error": "row_index out of range"}), 400

        row_data = rows[row_index]
        active_template_index = int(session_data.get("active_template_index", 0) or 0)
        if 0 <= active_template_index < len(templates) and templates[active_template_index].strip():
            preview_template = templates[active_template_index]
        else:
            preview_template = non_empty_templates[0]

        template_service = TemplateService()
        filled_content = template_service.replace_placeholders(
            preview_template, row_data, session_data["columns"]
        )
        if not _has_meaningful_text(filled_content):
            return jsonify({"error": "Generated anschreiben content is empty for this row."}), 400

        pdf_service = PDFService()
        company_raw = _extract_company_from_row(row_data)
        if not company_raw:
            return jsonify({"error": "Missing company name in this row. PDF was not created."}), 400
        company_name = _sanitize_pdf_name(company_raw, f"firma_{row_index + 1}")
        pdf_filename = f"preview_{company_name}.pdf"
        pdf_path = PDF_GENERATOR_TEMP_DIR / pdf_filename

        pdf_service.create_pdf(
            content=filled_content,
            output_path=str(pdf_path),
            metadata={"title": f"Bewerbung - {company_name}", "author": "PDF Generator"},
            design_pdf_path=session_data.get("design_pdf_path"),
            layout_options=layout_options,
        )

        return send_file(
            str(pdf_path),
            as_attachment=False,
            download_name=pdf_filename,
            mimetype="application/pdf",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/generate-pdfs", methods=["POST"])
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
            str(template or "")
            for template in (session_data.get("templates") or [session_data.get("template", "")])
        ]
        available_templates = [
            (index, template)
            for index, template in enumerate(templates)
            if template.strip()
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
                generated_records.append(
                    {
                        "row_index": idx,
                        "pdf_path": str(pdf_path),
                        "filename": filename,
                        "recipient": _extract_email_from_row(row_data),
                        "company": company_raw,
                        "template_index": chosen_template_index,
                        "template_label": f"Variante {chosen_template_index + 1}",
                        "context": dict(row_data),
                    }
                )
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
        _persist_linked_campaign_anschreiben(str(session_id))

        updated_campaign_id = ""
        campaign_id = str(session_data.get("editor_campaign_id") or "").strip()
        if campaign_id:
            campaign = _get_saved_email_campaign(campaign_id)
            if not campaign:
                return jsonify({"error": "Linked campaign not found"}), 404

            campaign_rows = list(campaign.get("rows") or [])
            row_index_map = list(session_data.get("campaign_row_indices") or [])
            for item in generated_records:
                try:
                    editor_row_index = int(item.get("row_index"))
                except (TypeError, ValueError):
                    continue
                if editor_row_index < 0 or editor_row_index >= len(row_index_map):
                    continue

                campaign_row_index = int(row_index_map[editor_row_index])
                if campaign_row_index < 0 or campaign_row_index >= len(campaign_rows):
                    continue

                campaign_row = campaign_rows[campaign_row_index]
                if not isinstance(campaign_row, dict):
                    campaign_row = {}
                    campaign_rows[campaign_row_index] = campaign_row

                campaign_row["pdf_path"] = str(item.get("pdf_path") or "")
                campaign_row["filename"] = str(item.get("filename") or "")
                if item.get("company"):
                    campaign_row["company"] = str(item.get("company") or "")
                if isinstance(item.get("context"), dict):
                    campaign_row["context"] = dict(item.get("context") or {})

            campaign["rows"] = campaign_rows
            campaign["anschreiben"] = _build_campaign_anschreiben_from_session(
                session_data, campaign_id=campaign_id
            )
            campaign["updated_at"] = datetime.now().isoformat()
            _update_saved_email_campaign(campaign)
            updated_campaign_id = campaign_id

        return jsonify(
            {
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
                "updated_campaign_id": updated_campaign_id,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/prepare-email-transfer", methods=["POST"])
def prepare_email_transfer():
    try:
        data = request.get_json(silent=True) or {}
        session_id = str(data.get("session_id") or "").strip()

        if session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        session_data = _pdf_sessions[session_id]
        generated_records = list(session_data.get("generated_records") or [])
        if not generated_records:
            return jsonify({"error": "No generated PDFs found. Generate PDFs first."}), 400

        application_summary = dict(session_data.get("application_summary") or {})
        application_data = dict(session_data.get("application_data") or {})

        transfer_rows = []
        skipped = 0
        for item in generated_records:
            recipient = _normalize_email(item.get("recipient"))
            pdf_path = str(item.get("pdf_path") or "").strip()
            if (
                not _is_valid_email(recipient)
                or not pdf_path
                or not os.path.exists(pdf_path)
                or os.path.getsize(pdf_path) <= 0
            ):
                skipped += 1
                continue

            context = dict(item.get("context") or {})
            company_name = str(
                item.get("company")
                or _extract_company_from_row(context)
                or ""
            ).strip()
            if not company_name:
                skipped += 1
                continue

            filename = str(item.get("filename") or "").strip()
            if not filename:
                filename = f"{_sanitize_pdf_name(company_name, f'firma_{len(transfer_rows) + 1}')}.pdf"
            elif not filename.lower().endswith(".pdf"):
                filename = f"{filename}.pdf"

            context.setdefault("email", recipient)
            context.setdefault("company", company_name)
            context.setdefault("Unternehmen", company_name)
            context.setdefault("Firma", company_name)

            transfer_rows.append(
                {
                    "recipient": recipient,
                    "company": company_name,
                    "pdf_path": pdf_path,
                    "filename": filename or Path(pdf_path).name,
                    "context": context,
                }
            )

        if not transfer_rows:
            return jsonify({"error": "No transferable rows with valid email and PDF."}), 400

        transfer_id = str(uuid.uuid4())
        job_title = str(
            application_summary.get("bereich")
            or application_summary.get("job_title")
            or application_data.get("bereich")
            or application_data.get("job_title")
            or session_data.get("job_title")
            or session_data.get("title")
            or ""
        ).strip()
        company_placeholder = str(
            application_summary.get("company")
            or application_summary.get("firma")
            or application_summary.get("organisation")
            or application_data.get("company")
            or application_data.get("firma")
            or application_data.get("organisation")
            or ""
        ).strip()
        full_name = _pick_best_first_value(
            {
                **application_data,
                **application_summary,
                "fullName": application_summary.get("full_name", ""),
                "full_name": application_summary.get("full_name", ""),
                "name": application_summary.get("full_name", ""),
            },
            ["fullName", "full_name", "name"],
        )
        sender_email = _pick_best_first_value(
            {
                **application_data,
                **application_summary,
                "email": application_summary.get("email", ""),
                "sender_email": application_summary.get("sender_email", ""),
                "gmail": application_summary.get("email", ""),
            },
            ["email", "sender_email", "gmail"],
        )
        anschreiben_text = "\n\n".join(
            str(template or "").strip()
            for template in (session_data.get("templates") or [session_data.get("template") or ""])
            if str(template or "").strip()
        )
        generated_templates = _build_email_templates_from_anschreiben(
            anschreiben_text,
            job_title=job_title,
            company=company_placeholder or "{{company}}",
        )
        anschreiben_snapshot = {
            "templates": list(session_data.get("templates") or [session_data.get("template") or ""]),
            "active_template_index": int(session_data.get("active_template_index") or 0),
            "layout_options": _normalize_pdf_layout_options(
                session_data.get("layout_options") or {}
            ),
            "filename_format": str(session_data.get("filename_format") or "{{Unternehmen}}"),
            "design_pdf": _read_binary_file_as_base64(session_data.get("design_pdf_path") or ""),
        }

        _email_transfer_sessions[transfer_id] = {
            "source_pdf_session_id": session_id,
            "rows": transfer_rows,
            "created_at": datetime.now().isoformat(),
            "anschreiben_snapshot": anschreiben_snapshot,
            "full_name": full_name,
            "sender_email": sender_email,
            "email_subject_template": generated_templates["subject"],
            "email_body_template": generated_templates["body"],
            "job_title": job_title,
            "company": company_placeholder,
            "application_summary": application_summary,
            "application_data": application_data,
        }

        return jsonify(
            {
                "success": True,
                "transfer_id": transfer_id,
                "rows": len(transfer_rows),
                "skipped": skipped,
                "redirect_url": f"/send-emails?transfer={transfer_id}",
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/update-filename-format", methods=["POST"])
def pdf_update_filename_format():
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        filename_format = data.get("filename_format", "{{Unternehmen}}")

        if session_id not in _pdf_sessions:
            return jsonify({"error": "Session not found"}), 404

        _pdf_sessions[session_id]["filename_format"] = filename_format
        _persist_linked_campaign_anschreiben(str(session_id))
        return jsonify({"success": True, "message": "Filename format updated"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/clear-session/<session_id>", methods=["DELETE"])
def pdf_clear_session(session_id):
    try:
        if session_id in _pdf_sessions:
            filepath = _pdf_sessions[session_id].get("filepath")
            if filepath and os.path.exists(filepath):
                os.remove(filepath)

            design_pdf_path = _pdf_sessions[session_id].get("design_pdf_path")
            if design_pdf_path and os.path.exists(design_pdf_path):
                os.remove(design_pdf_path)

            del _pdf_sessions[session_id]
        return jsonify({"success": True, "message": "Session cleared"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/extract_emails", methods=["POST"])
def start_email_extraction():
    with status_lock:
        if extraction_status["is_running"]:
            return redirect(url_for("extraction_progress"))

    jobs = _get_jobs_for_extraction()
    if not jobs:
            return jsonify({"error": "Keine Stellen zum Verarbeiten. Bitte zuerst eine Suche ausfuehren."}), 400

    _set_status(
        is_running=True,
        stop_requested=False,
        paused=False,
        continue_requested=False,
        current_index=0,
        total_jobs=len(jobs),
        captcha_needed=False,
        captcha_solved=False,
        jobs=jobs,
        last_error="",
    )

    thread = threading.Thread(target=run_email_extraction, daemon=True)
    thread.start()

    return redirect(url_for("extraction_progress"))


@app.route("/auto_extract_emails", methods=["POST"])
def start_auto_extraction():
    with status_lock:
        if auto_extraction_status["is_running"]:
            return redirect(url_for("auto_extraction_progress"))

    jobs = _get_jobs_for_extraction()
    if not jobs:
            return jsonify({"error": "Keine Stellen zum Verarbeiten. Bitte zuerst eine Suche ausfuehren."}), 400

    _set_auto_status(
        is_running=True,
        stop_requested=False,
        paused=False,
        continue_requested=False,
        current_index=0,
        total_jobs=len(jobs),
        emails_found=0,
        captchas_solved=0,
        failed=0,
        jobs=[dict(job) for job in jobs],
        last_error="",
    )

    thread = threading.Thread(target=run_auto_extraction, daemon=True)
    thread.start()

    return redirect(url_for("auto_extraction_progress"))


@app.route("/extraction_progress")
def extraction_progress():
    with status_lock:
        status_snapshot = dict(extraction_status)
    return render_template("extraction_progress.html", status=status_snapshot)


@app.route("/auto_extraction_progress")
def auto_extraction_progress():
    with status_lock:
        status_snapshot = dict(auto_extraction_status)
    return render_template("auto_extraction_progress.html", status=status_snapshot)


@app.route("/api/extraction_status")
def api_extraction_status():
    with status_lock:
        total = extraction_status["total_jobs"]
        current = extraction_status["current_index"]
        payload = {
            "is_running": extraction_status["is_running"],
            "stop_requested": extraction_status["stop_requested"],
            "paused": extraction_status["paused"],
            "current_index": current,
            "total_jobs": total,
            "captcha_needed": extraction_status["captcha_needed"],
            "last_error": extraction_status["last_error"],
            "percentage": (current / total * 100) if total else 0,
        }
    return jsonify(payload)


@app.route("/api/auto_extraction_status")
def api_auto_extraction_status():
    with status_lock:
        total = auto_extraction_status["total_jobs"]
        current = auto_extraction_status["current_index"]
        payload = {
            "is_running": auto_extraction_status["is_running"],
            "stop_requested": auto_extraction_status["stop_requested"],
            "paused": auto_extraction_status["paused"],
            "current_index": current,
            "total_jobs": total,
            "emails_found": auto_extraction_status["emails_found"],
            "captchas_solved": auto_extraction_status["captchas_solved"],
            "failed": auto_extraction_status["failed"],
            "last_error": auto_extraction_status["last_error"],
            "percentage": (current / total * 100) if total else 0,
        }
    return jsonify(payload)


@app.route("/captcha_solve")
def captcha_solve():
    return render_template("captcha_solve.html")


@app.route("/api/captcha_solved", methods=["POST"])
def captcha_solved():
    context = _get_captcha_context()
    if context.get("scope") == "ausbildungen_update" and context.get("job_id"):
        if not _set_ausbildungen_update_job(
            context["job_id"],
            captcha_needed=False,
            paused=False,
            continue_requested=True,
            last_error="",
        ):
            return jsonify({"status": "error", "message": "Update-Job nicht gefunden"}), 404
        _clear_captcha_context("ausbildungen_update", context["job_id"])
        return jsonify({"status": "success"})

    _set_status(captcha_needed=False, captcha_solved=True)
    _clear_captcha_context("manual_extraction")
    return jsonify({"status": "success"})


@app.route("/api/stop_extraction", methods=["POST"])
def stop_extraction():
    with status_lock:
        if not extraction_status["jobs"]:
            return jsonify({"status": "error", "message": "Keine Extraktion aktiv."}), 400
    _set_status(
        is_running=False,
        stop_requested=True,
        captcha_needed=False,
        paused=False,
        continue_requested=False,
    )
    return jsonify({"status": "success", "message": "Stop der Extraktion angefordert."})


@app.route("/api/stop_auto_extraction", methods=["POST"])
def stop_auto_extraction():
    with status_lock:
        if not auto_extraction_status["jobs"]:
            return jsonify({"status": "error", "message": "Keine Auto-Extraktion aktiv."}), 400
    _set_auto_status(is_running=False, stop_requested=True, paused=False, continue_requested=False)
    return jsonify({"status": "success", "message": "Stop der Auto-Extraktion angefordert."})


@app.route("/api/continue_extraction", methods=["POST"])
def continue_extraction():
    with status_lock:
        if not extraction_status["paused"]:
            return jsonify({"status": "error", "message": "Die Extraktion ist nicht pausiert."}), 400
    _set_status(is_running=True, continue_requested=True, paused=False)
    return jsonify({"status": "success", "message": "Fortsetzen angefordert."})


@app.route("/api/continue_auto_extraction", methods=["POST"])
def continue_auto_extraction():
    with status_lock:
        if not auto_extraction_status["paused"]:
            return jsonify({"status": "error", "message": "Die Auto-Extraktion ist nicht pausiert."}), 400
    _set_auto_status(is_running=True, continue_requested=True, paused=False)
    return jsonify({"status": "success", "message": "Fortsetzen angefordert."})


@app.route("/download_results")
def download_results():
    with status_lock:
        jobs = list(extraction_status.get("jobs", []))
    keyword = str(search_cache.get("keyword") or "").strip()

    if not jobs:
        return jsonify({"error": "Keine Extraktionsergebnisse verfügbar."}), 400

    jobs = _prepare_download_jobs(jobs)
    if not jobs:
        return jsonify({"error": "Keine Stellen mit gültiger E-Mail zum Download verfügbar."}), 400

    temp_file = _save_auto_extraction_export_records(
        jobs,
        keyword,
        fallback_slug="manual_extraction",
    )

    return send_file(
        temp_file,
        as_attachment=True,
        download_name=_build_download_filename(keyword, fallback="jobs_with_emails"),
    )


@app.route("/download_auto_results")
def download_auto_results():
    with status_lock:
        jobs = list(auto_extraction_status.get("jobs", []))
    keyword = str(search_cache.get("keyword") or "").strip()

    if not jobs:
        return jsonify({"error": "Keine Auto-Extraktionsergebnisse verfügbar."}), 400

    jobs = _prepare_download_jobs(jobs)
    if not jobs:
        return jsonify({"error": "Keine Stellen mit gültiger E-Mail zum Download verfügbar."}), 400

    temp_file = _save_auto_extraction_export_records(
        jobs,
        keyword,
        fallback_slug="auto_extraction",
    )

    return send_file(
        temp_file,
        as_attachment=True,
        download_name=_build_download_filename(keyword, fallback="jobs_with_emails_auto"),
    )


@app.route("/job/<path:refnr>")
def job_detail(refnr):
    return f"Job details for reference: {refnr}"


@app.route("/api/extract-pdf-text", methods=["POST"])
def extract_pdf_text():
    try:
        import requests
        from pypdf import PdfReader
        import io
        
        data = request.get_json() or {}
        pdf_url = data.get("pdf_url")
        page_num = data.get("page", 1)
        
        if not pdf_url:
            return jsonify({"error": "No PDF URL provided"}), 400
            
        try:
            page_index = int(page_num) - 1
            if page_index < 0:
                raise ValueError()
        except ValueError:
            return jsonify({"error": "Invalid page number"}), 400
            
        # Download the PDF into memory
        response = requests.get(pdf_url, timeout=15)
        response.raise_for_status()
        
        pdf_file = io.BytesIO(response.content)
        reader = PdfReader(pdf_file)
        
        if page_index >= len(reader.pages):
            return jsonify({"error": f"Page {page_num} does not exist in the document (Total pages: {len(reader.pages)})"}), 400
            
        page = reader.pages[page_index]
        extracted_text = page.extract_text() or ""
        
        return jsonify({"text": extracted_text.strip()})
        
    except Exception as e:
        logger.error(f"Error extracting PDF text: {e}")
        return jsonify({"error": f"Failed to extract text: {str(e)}"}), 500


_AI_TEMPLATIZE_SYSTEM_PROMPT = (
    "You are an expert HR template editor.\n\n"
    "Your task is to convert an extracted Anschreiben / motivation letter page into a reusable template.\n\n"
    "The input text comes from one selected page of a PDF document. It may contain formatting issues, "
    "missing line breaks, repeated spaces, or OCR/PDF extraction errors.\n\n"
    "Your main goal:\n"
    "Keep the final letter very close to the original extracted text, but replace or insert suitable "
    "placeholders from the available placeholder list.\n\n"
    "You must:\n"
    "1. Preserve the original letter's meaning, structure, language, and tone as much as possible.\n"
    "2. Do not rewrite the letter into a completely new version.\n"
    "3. Only fix obvious extraction/formatting issues when needed.\n"
    "4. Insert placeholders using ONLY the available placeholders provided by the user.\n"
    "5. Use placeholders exactly in this format: {{placeholder_name}}.\n"
    "6. Do not invent new placeholders.\n"
    "7. Do not return explanations, comments, markdown, JSON, or code fences.\n"
    "8. Return only the final editable letter template text.\n\n"
    "Semantic placeholder rule:\n"
    "- Do not rely only on exact find-and-replace.\n"
    "- Understand the text semantically.\n"
    "- If a placeholder is useful and available, you may insert it even if the exact original value is unclear.\n"
    "- However, the final result must still look very similar to the original letter.\n\n"
    "Mandatory greeting rule:\n"
    "- If both {{anrede}} and {{arbeitsgeber}} are available, the greeting line MUST always be exactly:\n"
    "{{anrede}} {{arbeitsgeber}},\n"
    "- Do not use alternatives like 'Sehr geehrte Damen und Herren,' when both placeholders are available.\n"
    "- Do not add names, titles, company names, or extra words inside the greeting line.\n"
    "- The greeting line must appear before the body of the letter.\n\n"
"Mandatory company rule:\n- The placeholder {{company}} represents the company name / Unternehmensname.\n- You MUST ALWAYS use the {{company}} placeholder when referring to the employer, company, organization, institution, or place of work.\n- Do NOT keep or generate any specific company name. Replace it with {{company}}.\n- If the original text says \"in Ihrem Hause\", change it to \"in Ihrem Hause bei {{company}}\" or replace it entirely with \"bei {{company}}\".\n- Examples:\n  - Original: \"ich bewerbe mich um ein Praktikum bei der Firma Apple in Berlin\"\n  - Correct: \"ich bewerbe mich um ein Praktikum bei der Firma {{company}} in {{city}}\"\n  - Incorrect: \"ich bewerbe mich um ein Praktikum bei der Firma Apple in {{city}}\"\n- This is an absolute requirement.\n\n"
    "Placeholder guidance:\n"
    "- Use {{city}} for city names.\n"
    "- Use {{company}} for company names. THIS IS VERY IMPORTANT. Ensure the company placeholder is used if applicable.\n"
    "- Use {{hauptberuf}} for the applicant's main profession/current occupation when relevant.\n"
    "- Use {{start_date}} for start dates or availability dates.\n"
    "- Use {{arbeitsgeber}} for the employer/contact person in the greeting or where appropriate.\n"
    "- Use {{anrede}} for the salutation part.\n"
    "- Use {{heutigenDatum}} for today's date in the letter header/date line.\n\n"
    "Important:\n"
    "If the selected page contains a date/location header and {{city}} and {{heutigenDatum}} are available, "
    "prefer a header like:\n{{city}}, {{heutigenDatum}}\n\n"
    "If the selected page already contains a greeting, replace it according to the mandatory greeting rule.\n\n"
    "The result must be suitable to place directly into the 'Textvorlage bearbeiten' textarea."
)


@app.route("/api/ai-templatize", methods=["POST"])
def ai_templatize():
    """Send extracted text to OpenRouter AI to convert into a template with placeholders."""
    try:
        import requests as http_requests

        data = request.get_json(silent=True) or {}
        raw_text = str(data.get("text") or "").strip()
        placeholders = [
            "city", "company", "hauptberuf", 
            "start_date", "arbeitsgeber", "anrede", "heutigenDatum"
        ]

        if not raw_text:
            return jsonify({"error": "Kein Text zum Verarbeiten vorhanden."}), 400
        if not isinstance(placeholders, list) or not placeholders:
            return jsonify({"error": "Keine Platzhalter angegeben."}), 400

        api_key = OPENROUTER_API_KEY
        if not api_key:
            return jsonify({"error": "OpenRouter API Key ist nicht konfiguriert."}), 500

        placeholder_list = "\n".join(f"- {{{{{p}}}}}" for p in placeholders)
        user_prompt = (
            f"Available placeholders:\n{placeholder_list}\n\n"
            f"Extracted text from selected Anschreiben page:\n"
            f'"""\n{raw_text}\n"""\n\n'
            f"Convert this extracted text into a reusable Anschreiben template.\n\n"
            f"Remember:\n"
            f"- Keep it very close to the original.\n"
            f"- Add the available placeholders where they make sense.\n"
            f"- The {{{{company}}}} placeholder is VERY IMPORTANT. You MUST ALWAYS include it. If the text says 'in Ihrem Hause', append 'bei {{{{company}}}}' or similar. Example: 'ich bewerbe mich um ein Praktikum bei der Firma {{{{company}}}} in {{{{city}}}}'.\n"
            f"- If {{{{anrede}}}} and {{{{arbeitsgeber}}}} are available, the greeting must be exactly:\n"
            f"{{{{anrede}}}} {{{{arbeitsgeber}}}},\n"
            f"- Return only the final template text."
        )

        models = [
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-3-super-120b-a12b:free"
        ]
        max_retries = 6
        
        for attempt in range(max_retries):
            current_model = models[attempt % len(models)]
            try:
                response = http_requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": current_model,
                        "messages": [
                            {"role": "system", "content": _AI_TEMPLATIZE_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                    timeout=120,
                )
                
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        time.sleep(2 if response.status_code == 429 else 1)
                        continue
                    response.raise_for_status()
                
                result = response.json()
                choices = result.get("choices") or []
                if not choices:
                    if attempt < max_retries - 1:
                        continue
                    return jsonify({"error": "KI hat keine Antwort geliefert."}), 502
                
                ai_text = str(choices[0].get("message", {}).get("content", "")).strip()
                if not ai_text:
                    if attempt < max_retries - 1:
                        continue
                    return jsonify({"error": "KI hat leeren Text zurueckgegeben."}), 502
                
                return jsonify({"success": True, "text": ai_text})
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise e

    except Exception as exc:
        logger.error("AI templatize error: %s", exc)
        return jsonify({"error": f"KI-Verarbeitung fehlgeschlagen: {exc}"}), 500


# ---------------------------------------------------------------------------
# Google Maps Business Email Scraper
# ---------------------------------------------------------------------------

def _create_google_maps_job(query: str, max_results: int, radius: int) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    job = {
        "job_id": job_id,
        "query": query,
        "max_results": max_results,
        "radius": radius,
        "phase": "queued",
        "is_running": False,
        "stop_requested": False,
        "current_index": 0,
        "total_businesses": 0,
        "emails_found": 0,
        "no_email": 0,
        "failed": 0,
        "results": [],
        "last_error": "",
        "created_at": now,
        "updated_at": now,
        "finished_at": "",
    }
    with google_maps_jobs_lock:
        google_maps_jobs[job_id] = job
    return job_id


def _set_google_maps_job(job_id: str, **kwargs) -> bool:
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return False
        job.update(kwargs)
        job["updated_at"] = datetime.now().isoformat()
        return True


def _run_google_maps_discovery(job_id: str) -> None:
    """Phase 1 only: Search Google Maps for businesses, return count.
    Does NOT process businesses or extract emails."""
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return
        query = str(job.get("query") or "")
        max_results = int(job.get("max_results") or 50)

    if not query:
        _set_google_maps_job(job_id, phase="error", last_error="Kein Suchbegriff angegeben")
        return

    _set_google_maps_job(job_id, is_running=True, phase="scraping_maps")

    scraper = None
    try:
        scraper = GoogleMapsBusinessScraper(headless=True)

        def stop_check():
            with google_maps_jobs_lock:
                j = google_maps_jobs.get(job_id)
                return not j or j.get("stop_requested", False)

        businesses = scraper.search_businesses(
            query, max_results=max_results, stop_check=stop_check,
        )

        if stop_check():
            _set_google_maps_job(
                job_id,
                is_running=False,
                phase="stopped",
                total_businesses=len(businesses),
                results=businesses,
            )
            return

        _set_google_maps_job(
            job_id,
            is_running=False,
            phase="ready_to_extract",
            total_businesses=len(businesses),
            results=businesses,
            finished_at=datetime.now().isoformat(),
        )

    except Exception as exc:
        logger.error("Google Maps discovery %s failed: %s", job_id, exc)
        _set_google_maps_job(
            job_id,
            is_running=False,
            phase="error",
            last_error=str(exc),
            finished_at=datetime.now().isoformat(),
        )
    finally:
        if scraper:
            scraper.close()


def _run_google_maps_extraction(job_id: str) -> None:
    """Phase 2 only: Process each discovered business link by link."""
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return
        businesses = list(job.get("results") or [])

    if not businesses:
        _set_google_maps_job(job_id, phase="done", is_running=False)
        return

    _set_google_maps_job(job_id, is_running=True, phase="extracting_emails")

    scraper = None
    try:
        scraper = GoogleMapsBusinessScraper(headless=True)

        def stop_check():
            with google_maps_jobs_lock:
                j = google_maps_jobs.get(job_id)
                return not j or j.get("stop_requested", False)

        # Process each business link by link
        for idx, business in enumerate(businesses):
            if stop_check():
                _set_google_maps_job(job_id, phase="stopped", is_running=False)
                return

            scraper.process_business(business, stop_check=stop_check)

            with google_maps_jobs_lock:
                j = google_maps_jobs.get(job_id)
                if j:
                    j["current_index"] = idx + 1
                    j["results"] = businesses
                    j["emails_found"] = scraper.stats.get("emails_found", 0)
                    j["no_email"] = scraper.stats.get("no_email", 0)
                    j["failed"] = scraper.stats.get("failed", 0)
                    j["updated_at"] = datetime.now().isoformat()

        _save_google_maps_export(job_id, businesses, str(job.get("query") or ""))
        _set_google_maps_job(
            job_id,
            is_running=False,
            phase="done",
            finished_at=datetime.now().isoformat(),
        )

    except Exception as exc:
        logger.error("Google Maps extraction %s failed: %s", job_id, exc)
        _set_google_maps_job(
            job_id,
            is_running=False,
            phase="error",
            last_error=str(exc),
            finished_at=datetime.now().isoformat(),
        )
    finally:
        if scraper:
            scraper.close()


def _run_google_maps_job(job_id: str) -> None:
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return
        query = str(job.get("query") or "")
        max_results = int(job.get("max_results") or 50)

    if not query:
        _set_google_maps_job(job_id, phase="error", last_error="Kein Suchbegriff angegeben")
        return

    _set_google_maps_job(job_id, is_running=True, phase="scraping_maps")

    scraper = None
    try:
        scraper = GoogleMapsBusinessScraper(headless=True)

        def stop_check():
            with google_maps_jobs_lock:
                j = google_maps_jobs.get(job_id)
                return not j or j.get("stop_requested", False)

        # Phase 1: Search Google Maps for businesses
        businesses = scraper.search_businesses(
            query, max_results=max_results, stop_check=stop_check,
        )

        if stop_check():
            _set_google_maps_job(
                job_id,
                is_running=False,
                phase="stopped",
                total_businesses=len(businesses),
                results=businesses,
            )
            return

        _set_google_maps_job(
            job_id,
            phase="extracting_emails",
            total_businesses=len(businesses),
            results=businesses,
        )

        # Phase 2: Process each business (enrich details + extract emails)
        for idx, business in enumerate(businesses):
            if stop_check():
                _set_google_maps_job(job_id, phase="stopped", is_running=False)
                return

            scraper.process_business(business, stop_check=stop_check)

            with google_maps_jobs_lock:
                j = google_maps_jobs.get(job_id)
                if j:
                    j["current_index"] = idx + 1
                    j["results"] = businesses
                    j["emails_found"] = scraper.stats.get("emails_found", 0)
                    j["no_email"] = scraper.stats.get("no_email", 0)
                    j["failed"] = scraper.stats.get("failed", 0)
                    j["updated_at"] = datetime.now().isoformat()

        # Done — save export file
        _save_google_maps_export(job_id, businesses, query)
        _set_google_maps_job(
            job_id,
            is_running=False,
            phase="done",
            finished_at=datetime.now().isoformat(),
        )

    except Exception as exc:
        logger.error("Google Maps job %s failed: %s", job_id, exc)
        _set_google_maps_job(
            job_id,
            is_running=False,
            phase="error",
            last_error=str(exc),
            finished_at=datetime.now().isoformat(),
        )
    finally:
        if scraper:
            scraper.close()


def _save_google_maps_export(job_id: str, businesses: List[Dict], query: str) -> Optional[Path]:
    if not businesses:
        return None

    GOOGLE_MAPS_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for biz in businesses:
        emails_str = ", ".join(biz.get("emails") or [])
        rows.append({
            "Name": biz.get("name", ""),
            "Adresse": biz.get("address", ""),
            "Telefon": biz.get("phone", ""),
            "Website": biz.get("website", ""),
            "E-Mails": emails_str,
            "Bewertung": biz.get("rating", ""),
            "Rezensionen": biz.get("reviews_count", ""),
            "Kategorie": biz.get("category", ""),
            "Status": biz.get("status", ""),
            "Google Maps URL": biz.get("maps_url", ""),
        })

    df = pd.DataFrame(rows)
    safe_query = re.sub(r"[^\w\s-]", "", query)[:40].strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"gmaps_{safe_query}_{timestamp}_{job_id[:8]}.xlsx"
    file_path = GOOGLE_MAPS_EXPORT_DIR / filename
    df.to_excel(file_path, index=False)

    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if job:
            job["export_filename"] = filename

    return file_path


@app.route("/google-maps")
def google_maps_page():
    return _render_app_shell("google-maps")


@app.route("/api/google-maps/discover", methods=["POST"])
def api_google_maps_discover():
    """Phase 1 only: Search Google Maps for businesses, show count."""
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "message": "Bitte einen Suchbegriff eingeben"}), 400

    max_results = min(int(data.get("max_results") or 50), 500)
    if max_results < 1:
        max_results = 10
    radius = int(data.get("radius") or 10)

    job_id = _create_google_maps_job(query, max_results, radius)
    thread = threading.Thread(target=_run_google_maps_discovery, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "query": query,
        "max_results": max_results,
        "message": "Discovery gestartet. Status unter /api/google-maps/status/<job_id> abrufen.",
    })


@app.route("/api/google-maps/start", methods=["POST"])
def api_google_maps_start():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "message": "Bitte einen Suchbegriff eingeben"}), 400

    max_results = min(int(data.get("max_results") or 50), 500)
    if max_results < 1:
        max_results = 10
    radius = int(data.get("radius") or 10)

    job_id = _create_google_maps_job(query, max_results, radius)
    thread = threading.Thread(target=_run_google_maps_job, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "query": query,
        "max_results": max_results,
    })


@app.route("/api/google-maps/extract/<job_id>", methods=["POST"])
def api_google_maps_extract(job_id: str):
    """Phase 2: Start link-by-link email extraction for discovered businesses."""
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Job nicht gefunden"}), 404
        phase = str(job.get("phase") or "")
        if phase not in ("ready_to_extract", "done", "stopped"):
            return jsonify({
                "success": False,
                "message": f"Extraktion kann nicht gestartet werden. Aktuelle Phase: {phase}",
            }), 400
        total = int(job.get("total_businesses") or 0)

    if total == 0:
        return jsonify({"success": False, "message": "Keine Businesses zum Verarbeiten gefunden"}), 400

    thread = threading.Thread(target=_run_google_maps_extraction, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "total_businesses": total,
        "message": f"Extraktion gestartet. {total} Businesses werden verarbeitet.",
    })


@app.route("/api/google-maps/status/<job_id>", methods=["GET"])
def api_google_maps_status(job_id: str):
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Job nicht gefunden"}), 404

        total = int(job.get("total_businesses") or 0)
        current = int(job.get("current_index") or 0)

        # Build safe results payload (limit result details for polling)
        results = []
        for biz in (job.get("results") or []):
            results.append({
                "name": biz.get("name", ""),
                "address": biz.get("address", ""),
                "phone": biz.get("phone", ""),
                "website": biz.get("website", ""),
                "emails": biz.get("emails", []),
                "rating": biz.get("rating", ""),
                "reviews_count": biz.get("reviews_count", ""),
                "category": biz.get("category", ""),
                "status": biz.get("status", "pending"),
            })

        payload = {
            "success": True,
            "job": {
                "job_id": job.get("job_id"),
                "query": job.get("query", ""),
                "phase": job.get("phase", "queued"),
                "is_running": bool(job.get("is_running")),
                "stop_requested": bool(job.get("stop_requested")),
                "current_index": current,
                "total_businesses": total,
                "emails_found": int(job.get("emails_found") or 0),
                "no_email": int(job.get("no_email") or 0),
                "failed": int(job.get("failed") or 0),
                "last_error": str(job.get("last_error") or ""),
                "percentage": (current / total * 100) if total else 0,
                "results": results,
                "updated_at": job.get("updated_at", ""),
                "finished_at": job.get("finished_at", ""),
            },
        }
    return jsonify(payload)


@app.route("/api/google-maps/stop/<job_id>", methods=["POST"])
def api_google_maps_stop(job_id: str):
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Job nicht gefunden"}), 404
        job["stop_requested"] = True
        job["updated_at"] = datetime.now().isoformat()
    return jsonify({"success": True, "message": "Stop-Signal gesendet"})


@app.route("/api/google-maps/download/<job_id>", methods=["GET"])
def api_google_maps_download(job_id: str):
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Job nicht gefunden"}), 404
        export_filename = str(job.get("export_filename") or "").strip()
        results = list(job.get("results") or [])
        query = str(job.get("query") or "export")

    # If we have an export file, serve it
    if export_filename:
        file_path = GOOGLE_MAPS_EXPORT_DIR / export_filename
        if file_path.exists():
            return send_file(
                str(file_path),
                as_attachment=True,
                download_name=export_filename,
            )

    # Generate export on the fly
    if not results:
        return jsonify({"success": False, "message": "Keine Ergebnisse vorhanden"}), 404

    file_path = _save_google_maps_export(job_id, results, query)
    if file_path and file_path.exists():
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=file_path.name,
        )

    return jsonify({"success": False, "message": "Export fehlgeschlagen"}), 500


@app.route("/api/google-maps/export/<job_id>/<fmt>", methods=["GET"])
def api_google_maps_export(job_id: str, fmt: str):
    with google_maps_jobs_lock:
        job = google_maps_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "message": "Job nicht gefunden"}), 404
        results = list(job.get("results") or [])
        query = str(job.get("query") or "export")

    if not results:
        return jsonify({"success": False, "message": "Keine Ergebnisse vorhanden"}), 404

    rows = []
    for biz in results:
        emails_str = ", ".join(biz.get("emails") or [])
        rows.append({
            "Name": biz.get("name", ""),
            "Adresse": biz.get("address", ""),
            "Telefon": biz.get("phone", ""),
            "Website": biz.get("website", ""),
            "E-Mails": emails_str,
            "Bewertung": biz.get("rating", ""),
            "Rezensionen": biz.get("reviews_count", ""),
            "Kategorie": biz.get("category", ""),
            "Status": biz.get("status", ""),
        })

    df = pd.DataFrame(rows)
    safe_query = re.sub(r"[^\w\s-]", "", query)[:40].strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    fmt = str(fmt or "xlsx").strip().lower()

    if fmt == "csv":
        output = io.StringIO()
        df.to_csv(output, index=False, encoding="utf-8")
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"gmaps_{safe_query}_{timestamp}.csv",
        )

    if fmt == "json":
        json_data = json.dumps(rows, ensure_ascii=False, indent=2)
        return send_file(
            io.BytesIO(json_data.encode("utf-8")),
            mimetype="application/json",
            as_attachment=True,
            download_name=f"gmaps_{safe_query}_{timestamp}.json",
        )

    # Default: xlsx
    GOOGLE_MAPS_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = GOOGLE_MAPS_EXPORT_DIR / f"gmaps_{safe_query}_{timestamp}_{job_id[:8]}.xlsx"
    df.to_excel(file_path, index=False)
    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=file_path.name,
    )


if __name__ == "__main__":
    app.run(debug=True)
