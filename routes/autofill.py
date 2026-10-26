"""
AI Job Autofill routes for Flask.
Integrates the Chrome extension and candidate profile management directly on port 5000.
"""

import os
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, send_from_directory, Response
from werkzeug.utils import secure_filename

autofill_bp = Blueprint("autofill", __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTOFILL_DIR = os.path.join(BASE_DIR, "ai-job-autofill")
SERVER_DIR = os.path.join(AUTOFILL_DIR, "server")
PROFILES_DIR = os.path.join(SERVER_DIR, "profiles")
CORRECTIONS_FILE = os.path.join(SERVER_DIR, "corrections.json")
APPLICATIONS_FILE = os.path.join(BASE_DIR, "data", "autofill_applications.json")

os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

SUPPORTED_DOC_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png"
}


def sanitize_profile_id(profile_id: str) -> str:
    if not profile_id or not isinstance(profile_id, str):
        return ""
    return re.sub(r"[^a-zA-Z0-9_-]", "", profile_id)


def get_safe_profile_dir(profile_id: str) -> str:
    clean_id = sanitize_profile_id(profile_id)
    if not clean_id:
        return ""
    target_dir = os.path.abspath(os.path.join(PROFILES_DIR, clean_id))
    if not target_dir.startswith(os.path.abspath(PROFILES_DIR)):
        raise ValueError("Path traversal detected")
    return target_dir


def load_corrections():
    if not os.path.exists(CORRECTIONS_FILE):
        return []
    try:
        with open(CORRECTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_corrections(corrections):
    with open(CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(corrections, f, indent=2, ensure_ascii=False)


def load_applications():
    if not os.path.exists(APPLICATIONS_FILE):
        return []
    try:
        with open(APPLICATIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_applications(apps):
    with open(APPLICATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, ensure_ascii=False)


# --- Profiles Endpoints ---

@autofill_bp.route("/api/autofill/profiles", methods=["GET"])
@autofill_bp.route("/api/profiles", methods=["GET"])
def get_profiles():
    """Returns all available candidate profiles."""
    profiles = []
    if os.path.exists(PROFILES_DIR):
        for fname in os.listdir(PROFILES_DIR):
            if fname.endswith(".json") and fname != "template.json":
                pid = fname[:-5]
                filepath = os.path.join(PROFILES_DIR, fname)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    applicant = data.get("applicant", {})
                    personal = applicant.get("personal", {})
                    contact = applicant.get("contact", {})
                    prof = applicant.get("professional_profile", {})
                    name = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip() or pid
                    profiles.append({
                        "id": pid,
                        "name": name,
                        "email": contact.get("email", ""),
                        "phone": contact.get("phone_display") or contact.get("phone", ""),
                        "title": prof.get("current_title") or prof.get("headline", ""),
                        "language": data.get("profile_language", "de"),
                        "city": contact.get("address", {}).get("city", "")
                    })
                except Exception:
                    profiles.append({"id": pid, "name": pid})
    from services.client_manager import client_manager
    active_id = client_manager.get_active_client_id()
    for p in profiles:
        p["is_active"] = (p["id"] == active_id)
    return jsonify({"profiles": profiles, "active_profile_id": active_id})


@autofill_bp.route("/api/autofill/ingest-cv", methods=["POST"])
def autofill_ingest_cv():
    from services.client_manager import client_manager
    file = request.files.get("cv_file") or request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    pdf_bytes = file.read()
    custom_id = request.form.get("client_id", "").strip() or None
    result = client_manager.ingest_cv(pdf_bytes, filename=file.filename, client_id=custom_id)
    return jsonify(result)


@autofill_bp.route("/api/autofill/profiles/<profile_id>", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>", methods=["GET"])
def get_profile_detail(profile_id):
    """Returns the full JSON for a specific applicant profile."""
    clean_id = sanitize_profile_id(profile_id)
    filepath = os.path.join(PROFILES_DIR, f"{clean_id}.json")
    if not os.path.exists(filepath):
        return jsonify({"error": "Profile not found"}), 404
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@autofill_bp.route("/api/autofill/profiles/<profile_id>/matching-data", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/matching-data", methods=["GET"])
def get_matching_data(profile_id):
    """Returns applicant profile, documents list, and domain corrections."""
    clean_id = sanitize_profile_id(profile_id)
    filepath = os.path.join(PROFILES_DIR, f"{clean_id}.json")
    if not os.path.exists(filepath):
        return jsonify({"error": "Profile not found"}), 404

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Failed to load profile: {e}"}), 500

    applicant = profile_data.get("applicant", {})

    # Discover documents in candidate directory
    docs = []
    pdir = get_safe_profile_dir(clean_id)
    if pdir and os.path.exists(pdir):
        for fname in sorted(os.listdir(pdir)):
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_DOC_EXTS:
                fpath = os.path.join(pdir, fname)
                size = os.path.getsize(fpath)
                lower_name = fname.lower()
                is_sensitive = any(kw in lower_name for kw in ["cin", "passport", "id_card", "pass", "identity"])
                category = "cv" if "cv" in lower_name or "resume" in lower_name or "lebenslauf" in lower_name else ("diploma" if "diplom" in lower_name or "certif" in lower_name else "other")
                docs.append({
                    "fileName": fname,
                    "file_name": fname,
                    "extension": ext.lstrip("."),
                    "size": size,
                    "category": category,
                    "isSensitive": is_sensitive,
                    "is_sensitive": is_sensitive,
                    "downloadUrl": f"/api/autofill/profiles/{clean_id}/documents/{fname}",
                    "previewUrl": f"/api/autofill/profiles/{clean_id}/documents/{fname}/preview"
                })

    # Domain corrections
    domain = request.args.get("domain", "").strip()
    all_corrections = load_corrections()
    domain_corrections = [
        c for c in all_corrections
        if not domain or c.get("domain") == domain or not c.get("domain")
    ]

    return jsonify({
        "profile_id": clean_id,
        "applicant": applicant,
        "profile_language": profile_data.get("profile_language", "de"),
        "documents": docs,
        "corrections": domain_corrections
    })


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/documents", methods=["GET"])
def get_documents(profile_id):
    """Returns document list for an applicant."""
    clean_id = sanitize_profile_id(profile_id)
    pdir = get_safe_profile_dir(clean_id)
    if not pdir or not os.path.exists(pdir):
        return jsonify({"documents": []})

    docs = []
    for fname in sorted(os.listdir(pdir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in SUPPORTED_DOC_EXTS:
            fpath = os.path.join(pdir, fname)
            size = os.path.getsize(fpath)
            lower = fname.lower()
            docs.append({
                "fileName": fname,
                "file_name": fname,
                "extension": ext.lstrip("."),
                "size": size,
                "isSensitive": any(kw in lower for kw in ["cin", "pass", "id_card"]),
                "downloadUrl": f"/api/autofill/profiles/{clean_id}/documents/{fname}",
                "previewUrl": f"/api/autofill/profiles/{clean_id}/documents/{fname}/preview"
            })
    return jsonify({"documents": docs})


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents/<filename>", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/documents/<filename>", methods=["GET"])
def download_document(profile_id, filename):
    """Downloads a document."""
    clean_id = sanitize_profile_id(profile_id)
    pdir = get_safe_profile_dir(clean_id)
    if not pdir:
        return jsonify({"error": "Invalid profile"}), 400
    return send_from_directory(pdir, filename, as_attachment=True)


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents/<filename>/preview", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/documents/<filename>/preview", methods=["GET"])
def preview_document(profile_id, filename):
    """Serves document inline for browser preview."""
    clean_id = sanitize_profile_id(profile_id)
    pdir = get_safe_profile_dir(clean_id)
    if not pdir or not os.path.exists(os.path.join(pdir, filename)):
        return jsonify({"error": "Document not found"}), 404
    ext = os.path.splitext(filename)[1].lower()
    mime = MIME_TYPES.get(ext, "application/octet-stream")
    with open(os.path.join(pdir, filename), "rb") as f:
        content = f.read()
    return Response(content, mimetype=mime, headers={"Content-Disposition": f"inline; filename={filename}"})


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents", methods=["POST"])
@autofill_bp.route("/api/profiles/<profile_id>/documents", methods=["POST"])
def upload_document(profile_id):
    """Uploads a document for a profile."""
    clean_id = sanitize_profile_id(profile_id)
    pdir = get_safe_profile_dir(clean_id)
    if not pdir:
        return jsonify({"error": "Invalid profile"}), 400
    os.makedirs(pdir, exist_ok=True)

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_DOC_EXTS:
        return jsonify({"error": f"Unsupported format {ext}. Supported: PDF, JPG, PNG"}), 400

    fpath = os.path.join(pdir, filename)
    file.save(fpath)
    return jsonify({"success": True, "fileName": filename, "message": "Document uploaded successfully"})


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents/<filename>", methods=["DELETE"])
@autofill_bp.route("/api/profiles/<profile_id>/documents/<filename>", methods=["DELETE"])
def delete_document(profile_id, filename):
    """Deletes a document from a profile."""
    clean_id = sanitize_profile_id(profile_id)
    pdir = get_safe_profile_dir(clean_id)
    if not pdir:
        return jsonify({"error": "Invalid profile"}), 400
    safe_filename = secure_filename(filename)
    fpath = os.path.join(pdir, safe_filename)
    if os.path.exists(fpath):
        os.remove(fpath)
        return jsonify({"success": True, "message": f"{safe_filename} deleted"})
    return jsonify({"error": "File not found"}), 404


@autofill_bp.route("/api/autofill/profiles", methods=["POST"])
@autofill_bp.route("/api/profiles", methods=["POST"])
def save_profile():
    """Creates or updates a profile."""
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profileId") or body.get("id") or body.get("profile_id")
    if not profile_id:
        # Generate ID from name
        name = body.get("applicant", {}).get("personal", {}).get("full_name") or "new_applicant"
        profile_id = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())

    clean_id = sanitize_profile_id(profile_id)
    if not clean_id:
        return jsonify({"error": "Invalid profile ID"}), 400

    target_file = os.path.join(PROFILES_DIR, f"{clean_id}.json")
    target_dir = os.path.join(PROFILES_DIR, clean_id)
    os.makedirs(target_dir, exist_ok=True)

    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)

    return jsonify({"success": True, "profileId": clean_id, "message": "Profile saved successfully"})


# --- Corrections Memory Endpoints ---

@autofill_bp.route("/api/autofill/corrections", methods=["GET"])
@autofill_bp.route("/api/corrections", methods=["GET"])
def get_corrections():
    corrections = load_corrections()
    return jsonify({"corrections": corrections})


@autofill_bp.route("/api/autofill/corrections", methods=["POST"])
@autofill_bp.route("/api/corrections", methods=["POST"])
def save_correction():
    body = request.get_json(silent=True) or {}
    corrections = load_corrections()
    new_corr = {
        "id": f"corr_{int(datetime.now().timestamp() * 1000)}",
        "domain": body.get("domain", ""),
        "fieldSignature": body.get("fieldSignature") or body.get("fieldName") or body.get("field_id", ""),
        "fieldLabel": body.get("fieldLabel", ""),
        "correctedValue": body.get("correctedValue", ""),
        "createdAt": datetime.now().isoformat()
    }
    corrections.append(new_corr)
    save_corrections(corrections)
    return jsonify({"success": True, "correction": new_corr})


@autofill_bp.route("/api/autofill/corrections/<corr_id>", methods=["DELETE"])
@autofill_bp.route("/api/corrections/<corr_id>", methods=["DELETE"])
def delete_correction(corr_id):
    corrections = load_corrections()
    filtered = [c for c in corrections if c.get("id") != corr_id]
    save_corrections(filtered)
    return jsonify({"success": True})


@autofill_bp.route("/api/autofill/corrections", methods=["DELETE"])
@autofill_bp.route("/api/corrections", methods=["DELETE"])
def clear_all_corrections():
    save_corrections([])
    return jsonify({"success": True})


# --- Map-Fields Endpoint (Proxy to Node or Native Python Matcher) ---

def python_deterministic_matcher(field, applicant, documents):
    """
    Fast deterministic matching engine in Python for standard fields (German, English, French).
    """
    label = (field.get("label") or "").lower().strip()
    name = (field.get("name") or "").lower().strip()
    fid = (field.get("field_id") or field.get("id") or "").lower().strip()
    placeholder = (field.get("placeholder") or "").lower().strip()
    combined = f"{label} {name} {fid} {placeholder}"

    personal = applicant.get("personal", {})
    contact = applicant.get("contact", {})
    addr = contact.get("address", {})

    # First Name
    if any(k in combined for k in ["vorname", "first name", "firstname", "prénom", "prenom"]) and not any(k in combined for k in ["nachname", "last name", "nom"]):
        val = personal.get("first_name", "")
        if val:
            return {"value": val, "confidence": 0.98, "reason": "First name exact match", "source": "applicant.personal.first_name", "status": "approved"}

    # Last Name
    if any(k in combined for k in ["nachname", "last name", "lastname", "familienname", "nom de famille", "nom"]):
        val = personal.get("last_name", "")
        if val:
            return {"value": val, "confidence": 0.98, "reason": "Last name exact match", "source": "applicant.personal.last_name", "status": "approved"}

    # Full Name
    if any(k in combined for k in ["vollständiger name", "full name", "fullname", "nom complet", "name"]) and not any(k in combined for k in ["vorname", "nachname", "unternehmensname", "firmenname"]):
        val = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
        if val:
            return {"value": val, "confidence": 0.95, "reason": "Full name match", "source": "applicant.personal.full_name", "status": "approved"}

    # Email
    if "email" in combined or "e-mail" in combined or "courriel" in combined:
        val = contact.get("email", "")
        if val:
            return {"value": val, "confidence": 0.99, "reason": "Email address match", "source": "applicant.contact.email", "status": "approved"}

    # Phone / Mobile
    if any(k in combined for k in ["telefon", "phone", "mobile", "handy", "téléphone", "tel"]):
        val = contact.get("phone_display") or contact.get("phone", "")
        if val:
            return {"value": val, "confidence": 0.97, "reason": "Phone number match", "source": "applicant.contact.phone", "status": "approved"}

    # City / Ort
    if any(k in combined for k in ["stadt", "ort", "city", "ville", "wohnort"]):
        val = addr.get("city", "")
        if val:
            return {"value": val, "confidence": 0.95, "reason": "City match", "source": "applicant.contact.address.city", "status": "approved"}

    # Postal Code / PLZ
    if any(k in combined for k in ["plz", "postleitzahl", "postal code", "zip", "code postal"]):
        val = addr.get("postal_code") or addr.get("zip", "")
        if val:
            return {"value": str(val), "confidence": 0.96, "reason": "Postal code match", "source": "applicant.contact.address.postal_code", "status": "approved"}

    # Country
    if any(k in combined for k in ["land", "country", "pays"]):
        val = addr.get("country", "")
        if val:
            return {"value": val, "confidence": 0.95, "reason": "Country match", "source": "applicant.contact.address.country", "status": "approved"}

    # CV / Resume Upload
    if field.get("type") == "file" or any(k in combined for k in ["cv", "lebenslauf", "resume"]):
        cv_doc = next((d for d in documents if d.get("category") == "cv" or "cv" in d.get("fileName", "").lower()), None)
        if cv_doc:
            return {"value": cv_doc.get("fileName"), "confidence": 0.98, "reason": "Primary CV document match", "source": "documents.cv", "status": "approved", "isFile": True}

    return None


@autofill_bp.route("/api/autofill/map-fields", methods=["POST"])
@autofill_bp.route("/api/map-fields", methods=["POST"])
def map_fields():
    """Matches form fields against candidate profile."""
    body = request.get_json(silent=True) or {}
    fields = body.get("fields", [])
    profile_id = body.get("profileId") or body.get("profile_id", "anass_sibbi")

    # 1. Try Node.js server on :8787 first if running
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8787/api/map-fields",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            if resp.status == 200:
                node_data = json.loads(resp.read().decode("utf-8"))
                return jsonify(node_data)
    except Exception:
        # Node server is not active on :8787, use Flask native matching engine
        pass

    # 2. Native Python matching engine
    clean_id = sanitize_profile_id(profile_id)
    filepath = os.path.join(PROFILES_DIR, f"{clean_id}.json")
    if not os.path.exists(filepath):
        # Fallback to first profile
        all_json = [f for f in os.listdir(PROFILES_DIR) if f.endswith(".json") and f != "template.json"]
        if all_json:
            clean_id = all_json[0][:-5]
            filepath = os.path.join(PROFILES_DIR, all_json[0])

    applicant = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                applicant = json.load(f).get("applicant", {})
        except Exception:
            pass

    # Load docs
    docs = []
    pdir = get_safe_profile_dir(clean_id)
    if pdir and os.path.exists(pdir):
        for fname in os.listdir(pdir):
            docs.append({"fileName": fname, "category": "cv" if "cv" in fname.lower() else "other"})

    actions = []
    for f in fields:
        matched = python_deterministic_matcher(f, applicant, docs)
        if matched:
            actions.append({
                "field_id": f.get("field_id") or f.get("id"),
                "value": matched["value"],
                "confidence": matched["confidence"],
                "reason": matched["reason"],
                "source": matched["source"],
                "status": matched["status"],
                "is_file": matched.get("isFile", False)
            })

    return jsonify({"actions": actions, "unresolved": [], "engine": "flask_deterministic"})


# --- Application Logging & Tracking ---

@autofill_bp.route("/api/autofill/log-application", methods=["POST"])
def log_application():
    """Logs an application filled via the extension."""
    data = request.get_json(silent=True) or {}
    apps = load_applications()
    new_app = {
        "id": f"app_{int(datetime.now().timestamp() * 1000)}",
        "company": data.get("company") or data.get("domain") or "Unbekanntes Unternehmen",
        "title": data.get("title") or data.get("position") or "Bewerbung",
        "position": data.get("position") or data.get("title") or "Bewerbung",
        "url": data.get("url") or data.get("portal_url", ""),
        "domain": data.get("domain") or "",
        "profile": data.get("profile") or data.get("profile_id") or data.get("profileId", "anass_sibbi"),
        "profileId": data.get("profileId") or data.get("profile_id") or data.get("profile", "anass_sibbi"),
        "fields_filled": data.get("fields_filled") or data.get("fieldsFilled") or data.get("count", 0),
        "fieldsFilled": data.get("fieldsFilled") or data.get("fields_filled") or data.get("count", 0),
        "status": data.get("status") or "Ausgefüllt & Überprüft",
        "date": data.get("date") or datetime.now().strftime("%d.%m.%Y"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    apps.insert(0, new_app)
    save_applications(apps)
    return jsonify({"success": True, "application": new_app})


@autofill_bp.route("/api/autofill/applications", methods=["GET"])
def get_logged_applications():
    """Returns list of logged autofill applications."""
    apps = load_applications()
    return jsonify({"applications": apps, "total": len(apps)})


# --- Test Forms Routes ---

@autofill_bp.route("/test-form", methods=["GET"])
def serve_test_form():
    """Serves the trilingual test form from ai-job-autofill."""
    form_path = os.path.join(SERVER_DIR, "test-form.html")
    if not os.path.exists(form_path):
        form_path = os.path.join(AUTOFILL_DIR, "test-form.html")
    if os.path.exists(form_path):
        with open(form_path, "r", encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/html")
    return "Test form not found", 404


@autofill_bp.route("/french-form", methods=["GET"])
def serve_french_form():
    """Serves the french test form."""
    form_path = os.path.join(SERVER_DIR, "french-form.html")
    if not os.path.exists(form_path):
        form_path = os.path.join(AUTOFILL_DIR, "french-form.html")
    if os.path.exists(form_path):
        with open(form_path, "r", encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/html")
    return "French form not found", 404


@autofill_bp.route("/api/autofill/upload-cv", methods=["POST"])
@autofill_bp.route("/api/profiles/upload-cv", methods=["POST"])
def upload_and_parse_cv():
    """Uploads a PDF resume, parses candidate information, and syncs into candidate profile JSON."""
    if "cv_file" not in request.files and "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files.get("cv_file") or request.files.get("file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "Only PDF files are supported"}), 400

    profile_id = request.form.get("profile_id") or request.form.get("profileId") or "anass_sibbi"
    clean_id = sanitize_profile_id(profile_id)
    profile_path = Path(PROFILES_DIR) / f"{clean_id}.json"

    try:
        from services.cv_parser import CVParser
        pdf_bytes = file.read()
        extracted_text = CVParser.extract_text_from_pdf(pdf_bytes)
        if not extracted_text:
            return jsonify({"success": False, "error": "Could not extract text from PDF"}), 400

        parsed_data = CVParser.parse_cv_text(extracted_text)
        updated_profile = CVParser.update_profile_from_cv(profile_path, parsed_data)

        return jsonify({
            "success": True,
            "profile_id": clean_id,
            "parsed_data": parsed_data,
            "skills_count": len(parsed_data["skills"]["technologies_from_cv"]),
            "message": f"Successfully parsed and updated profile for {clean_id}"
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

