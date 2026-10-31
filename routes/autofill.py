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
    """Returns all available candidate profiles using ClientManager as single source of truth."""
    from services.client_manager import client_manager
    clients = client_manager.list_clients()
    active_id = client_manager.get_active_client_id()
    profiles = []
    for c in clients:
        pid = c["id"]
        full_prof = client_manager.get_client(pid) or {}
        profiles.append({
            "id": pid,
            "name": c.get("name", pid),
            "email": c.get("email", ""),
            "phone": c.get("phone", ""),
            "title": c.get("title", ""),
            "city": c.get("city", ""),
            "language": full_prof.get("profile_language", "de"),
            "is_active": (pid == active_id),
            "doc_count": c.get("doc_count", 0)
        })
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
    """Returns the full JSON for a specific applicant profile from ClientManager."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    profile_data = client_manager.get_client(clean_id)
    if not profile_data:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(profile_data)


@autofill_bp.route("/api/autofill/profiles/<profile_id>/matching-data", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/matching-data", methods=["GET"])
def get_matching_data(profile_id):
    """Returns applicant profile, documents list, and domain corrections from ClientManager."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    profile_data = client_manager.get_client(clean_id)
    if not profile_data:
        return jsonify({"error": "Profile not found"}), 404

    applicant = profile_data.get("applicant", {})

    # Discover documents via ClientManager
    docs_raw = client_manager.list_documents(clean_id)
    docs = []
    for d in docs_raw:
        fname = d.get("fileName") or d.get("file_name", "")
        lower_name = fname.lower()
        is_sensitive = any(kw in lower_name for kw in ["cin", "passport", "id_card", "pass", "identity"])
        docs.append({
            "fileName": fname,
            "file_name": fname,
            "extension": d.get("extension", ""),
            "size": d.get("size", 0),
            "category": d.get("category", "other"),
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
    """Returns document list for an applicant via ClientManager."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    docs_raw = client_manager.list_documents(clean_id)
    docs = []
    for d in docs_raw:
        fname = d.get("fileName") or d.get("file_name", "")
        lower = fname.lower()
        docs.append({
            "fileName": fname,
            "file_name": fname,
            "extension": d.get("extension", ""),
            "size": d.get("size", 0),
            "isSensitive": any(kw in lower for kw in ["cin", "pass", "id_card"]),
            "downloadUrl": f"/api/autofill/profiles/{clean_id}/documents/{fname}",
            "previewUrl": f"/api/autofill/profiles/{clean_id}/documents/{fname}/preview"
        })
    return jsonify({"documents": docs})


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents/<filename>", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/documents/<filename>", methods=["GET"])
def download_document(profile_id, filename):
    """Downloads a document from client dossier or autofill directory."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    safe_filename = secure_filename(filename)

    primary_file = client_manager.clients_dir / clean_id / "documents" / safe_filename
    if primary_file.exists():
        return send_from_directory(str(primary_file.parent), safe_filename, as_attachment=True)

    pdir = get_safe_profile_dir(clean_id)
    if pdir and os.path.exists(os.path.join(pdir, safe_filename)):
        return send_from_directory(pdir, safe_filename, as_attachment=True)

    return jsonify({"error": "Document not found"}), 404


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents/<filename>/preview", methods=["GET"])
@autofill_bp.route("/api/profiles/<profile_id>/documents/<filename>/preview", methods=["GET"])
def preview_document(profile_id, filename):
    """Serves document inline for browser preview."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    safe_filename = secure_filename(filename)

    target_path = None
    primary_file = client_manager.clients_dir / clean_id / "documents" / safe_filename
    if primary_file.exists():
        target_path = primary_file
    else:
        pdir = get_safe_profile_dir(clean_id)
        if pdir and os.path.exists(os.path.join(pdir, safe_filename)):
            target_path = Path(pdir) / safe_filename

    if not target_path or not target_path.exists():
        return jsonify({"error": "Document not found"}), 404

    ext = target_path.suffix.lower()
    mime = MIME_TYPES.get(ext, "application/octet-stream")
    with open(target_path, "rb") as f:
        content = f.read()
    return Response(content, mimetype=mime, headers={"Content-Disposition": f"inline; filename={safe_filename}"})


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents", methods=["POST"])
@autofill_bp.route("/api/profiles/<profile_id>/documents", methods=["POST"])
def upload_document(profile_id):
    """Uploads a document for a profile and syncs through ClientManager."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    if not clean_id:
        return jsonify({"error": "Invalid profile"}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_DOC_EXTS:
        return jsonify({"error": f"Unsupported format {ext}. Supported: PDF, JPG, PNG"}), 400

    file_bytes = file.read()
    client_manager.save_document(clean_id, file_bytes, filename)
    return jsonify({"success": True, "fileName": filename, "message": "Document uploaded successfully"})


@autofill_bp.route("/api/autofill/profiles/<profile_id>/documents/<filename>", methods=["DELETE"])
@autofill_bp.route("/api/profiles/<profile_id>/documents/<filename>", methods=["DELETE"])
def delete_document(profile_id, filename):
    """Deletes a document from a profile using ClientManager."""
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    safe_filename = secure_filename(filename)
    deleted = client_manager.delete_document(clean_id, safe_filename)
    if deleted:
        return jsonify({"success": True, "message": f"{safe_filename} deleted"})
    return jsonify({"error": "File not found"}), 404


@autofill_bp.route("/api/autofill/profiles", methods=["POST"])
@autofill_bp.route("/api/profiles", methods=["POST"])
def save_profile():
    """Creates or updates a profile using ClientManager as the single source of truth."""
    from services.client_manager import client_manager
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profileId") or body.get("id") or body.get("profile_id")
    if not profile_id:
        name = body.get("applicant", {}).get("personal", {}).get("full_name") or "new_applicant"
        profile_id = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())

    clean_id = sanitize_profile_id(profile_id)
    if not clean_id:
        return jsonify({"error": "Invalid profile ID"}), 400

    success = client_manager.save_client(clean_id, body)
    if not success:
        return jsonify({"error": "Failed to save profile"}), 500

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
    nearby = (field.get("nearby_question") or "").lower().strip()
    combined = f"{label} {name} {fid} {placeholder} {nearby}"

    personal = applicant.get("personal", {})
    contact = applicant.get("contact", {})
    addr = contact.get("address", {})
    prof = applicant.get("professional_profile", {})

    # 1. First Name
    if any(k in combined for k in ["vorname", "first name", "firstname", "prénom", "prenom", "given name"]) and not any(k in combined for k in ["nachname", "last name", "nom", "family"]):
        val = personal.get("first_name", "")
        if val:
            return {"value": val, "confidence": 0.98, "reason": "First name exact match", "source": "applicant.personal.first_name", "status": "approved"}

    # 2. Last Name
    if any(k in combined for k in ["nachname", "last name", "lastname", "familienname", "nom de famille", "nom", "surname"]):
        val = personal.get("last_name", "")
        if val:
            return {"value": val, "confidence": 0.98, "reason": "Last name exact match", "source": "applicant.personal.last_name", "status": "approved"}

    # 3. Full Name
    if any(k in combined for k in ["vollständiger name", "full name", "fullname", "nom complet", "name"]) and not any(k in combined for k in ["vorname", "nachname", "unternehmensname", "firmenname"]):
        val = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
        if val:
            return {"value": val, "confidence": 0.95, "reason": "Full name match", "source": "applicant.personal.full_name", "status": "approved"}

    # 4. Email
    if "email" in combined or "e-mail" in combined or "courriel" in combined:
        val = contact.get("email", "")
        if val:
            return {"value": val, "confidence": 0.99, "reason": "Email address match", "source": "applicant.contact.email", "status": "approved"}

    # 5. Phone / Mobile
    if any(k in combined for k in ["telefon", "phone", "mobile", "handy", "téléphone", "tel"]):
        val = contact.get("phone_display") or contact.get("phone", "")
        if val:
            return {"value": val, "confidence": 0.97, "reason": "Phone number match", "source": "applicant.contact.phone", "status": "approved"}

    # 6. Street / Strasse / Adresse
    if any(k in combined for k in ["strasse", "straße", "street", "address", "adresse", "rue"]):
        val = addr.get("street") or addr.get("line1", "")
        if val:
            return {"value": val, "confidence": 0.96, "reason": "Street address match", "source": "applicant.contact.address.street", "status": "approved"}

    # 7. City / Ort
    if any(k in combined for k in ["stadt", "ort", "city", "ville", "wohnort"]):
        val = addr.get("city", "")
        if val:
            return {"value": val, "confidence": 0.95, "reason": "City match", "source": "applicant.contact.address.city", "status": "approved"}

    # 8. Postal Code / PLZ
    if any(k in combined for k in ["plz", "postleitzahl", "postal code", "zip", "code postal"]):
        val = addr.get("postal_code") or addr.get("zip", "")
        if val:
            return {"value": str(val), "confidence": 0.96, "reason": "Postal code match", "source": "applicant.contact.address.postal_code", "status": "approved"}

    # 9. Country
    if any(k in combined for k in ["land", "country", "pays"]):
        val = addr.get("country", "")
        if val:
            return {"value": val, "confidence": 0.95, "reason": "Country match", "source": "applicant.contact.address.country", "status": "approved"}

    # 10. Date of Birth / Geburtsdatum
    if any(k in combined for k in ["geburtsdatum", "date of birth", "birthdate", "date de naissance", "geburtstag"]):
        val = personal.get("date_of_birth", "")
        if val:
            return {"value": val, "confidence": 0.96, "reason": "Date of birth match", "source": "applicant.personal.date_of_birth", "status": "approved"}

    # 11. Nationality / Staatsangehörigkeit
    if any(k in combined for k in ["staatsangehörigkeit", "nationalität", "nationality", "nationalite"]):
        val = personal.get("nationality", "")
        if val:
            return {"value": val, "confidence": 0.95, "reason": "Nationality match", "source": "applicant.personal.nationality", "status": "approved"}

    # 12. LinkedIn / Xing / Website
    if "linkedin" in combined:
        val = contact.get("linkedin") or contact.get("social", {}).get("linkedin", "")
        if val:
            return {"value": val, "confidence": 0.98, "reason": "LinkedIn URL match", "source": "applicant.contact.linkedin", "status": "approved"}

    # 13. CV / Resume Upload
    if field.get("type") == "file" or any(k in combined for k in ["cv", "lebenslauf", "resume"]):
        cv_doc = next((d for d in documents if d.get("category") == "cv" or "cv" in d.get("fileName", "").lower()), None)
        if cv_doc:
            return {"value": cv_doc.get("fileName"), "confidence": 0.98, "reason": "Primary CV document match", "source": "documents.cv", "status": "approved", "isFile": True}

    return None


def python_ai_answer_questions(unresolved_fields, applicant_data, page_context=None):
    """
    Uses the central AIProviderManager (OpenAI GPT or Gemini) to answer custom or open-ended
    application questions strictly based on verified candidate profile data without hallucinations.
    """
    if not unresolved_fields:
        return []

    try:
        from services.ai_provider_manager import ai_manager
    except Exception as exc:
        return []

    system_prompt = (
        "You are JobScout AI Job Autofill engine. Your task is to answer job application form questions "
        "STRICTLY based on the provided candidate's real profile data.\n\n"
        "CRITICAL RULES:\n"
        "1. STRICT ANTI-HALLUCINATION: NEVER invent skills, degrees, certifications, or experience absent from the candidate data.\n"
        "2. For open-ended questions like 'Why do you want this job?' or 'Tell us about your experience', "
        "synthesize a concise, polite 1-3 sentence response based exclusively on the candidate's verified summary, target profession, and skills.\n"
        "3. Output strictly valid JSON format with schema: {\"actions\": [{\"field_id\": \"...\", \"action\": \"fill|skip|review\", \"proposed_value\": \"...\", \"confidence\": 0.9, \"reason\": \"...\", \"review_required\": true|false}]}"
    )

    clean_fields = []
    for f in unresolved_fields:
        clean_fields.append({
            "field_id": f.get("field_id") or f.get("id"),
            "label": f.get("label") or f.get("name") or "",
            "placeholder": f.get("placeholder") or "",
            "type": f.get("type") or "text",
            "nearby_question": f.get("nearby_question") or "",
            "options": f.get("options") or []
        })

    prompt_data = {
        "candidate_profile": applicant_data,
        "page_context": page_context or {},
        "fields_to_answer": clean_fields
    }

    try:
        res = ai_manager.complete(
            prompt=json.dumps(prompt_data, ensure_ascii=False),
            system_prompt=system_prompt,
            json_mode=True,
            max_output_tokens=600,
            temperature=0.2,
            use_cache=True,
        )

        content = res.get("content") or ""
        parsed = res.get("parsed_json")
        if not parsed and content:
            clean_text = content.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean_text)

        if isinstance(parsed, dict) and "actions" in parsed:
            return parsed["actions"]
        elif isinstance(parsed, list):
            return parsed
    except Exception as exc:
        logger = logging.getLogger(__name__) if "logging" in globals() else None
        if logger:
            logger.warning("Autofill AI question answering error: %s", exc)

    return []


@autofill_bp.route("/api/autofill/map-fields", methods=["POST"])
@autofill_bp.route("/api/map-fields", methods=["POST"])
def map_fields():
    """
    Matches form fields against candidate profile.
    Uses deterministic matcher for standard fields and central AIProviderManager for custom questions.
    Works natively without requiring the separate Node.js server on :8787.
    """
    body = request.get_json(silent=True) or {}
    fields = body.get("fields", [])
    profile_id = body.get("profileId") or body.get("profile_id", "anass_sibbi")
    page_context = body.get("pageContext") or {}

    # 1. Load candidate profile via ClientManager / profiles
    from services.client_manager import client_manager
    clean_id = sanitize_profile_id(profile_id)
    client_data = client_manager.get_client(clean_id) or {}

    applicant = {}
    if client_data:
        if "applicant" in client_data and isinstance(client_data["applicant"], dict):
            applicant = client_data["applicant"]
        else:
            contact = client_data.get("contact", {})
            profile_info = client_data.get("profile", {})
            full_name = client_data.get("name") or contact.get("full_name") or ""
            parts = full_name.split(None, 1) if full_name else ["", ""]
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

            applicant = {
                "personal": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": full_name,
                    "date_of_birth": contact.get("birth_date", ""),
                    "nationality": contact.get("nationality", "Marokkanisch")
                },
                "contact": {
                    "email": contact.get("email", ""),
                    "phone": contact.get("phone", ""),
                    "phone_display": contact.get("phone", ""),
                    "address": {
                        "street": contact.get("street", ""),
                        "city": contact.get("city", ""),
                        "postal_code": contact.get("zip", ""),
                        "country": contact.get("country", "Deutschland")
                    }
                },
                "professional_profile": {
                    "target_profession": profile_info.get("field") or profile_info.get("target_title") or "",
                    "skills": profile_info.get("skills") or [],
                    "summary": profile_info.get("notes") or f"Motivierter Bewerber im Bereich {profile_info.get('field', 'Ausbildung')}."
                }
            }
    else:
        # Fallback to profiles JSON file if present
        filepath = os.path.join(PROFILES_DIR, f"{clean_id}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    applicant = json.load(f).get("applicant", {})
            except Exception:
                pass

    # Load documents
    docs = []
    pdir = get_safe_profile_dir(clean_id)
    if pdir and os.path.exists(pdir):
        for fname in os.listdir(pdir):
            docs.append({"fileName": fname, "category": "cv" if "cv" in fname.lower() else "other"})
    if not docs and client_data.get("documents"):
        for d in client_data["documents"]:
            docs.append({"fileName": d.get("filename") or d.get("name", ""), "category": "cv" if d.get("is_cv") else "other"})

    # Check saved corrections first
    corrections = load_corrections()
    domain = (body.get("domain") or "").lower().strip()
    matching_corrections = [
        c for c in corrections
        if (c.get("domain") == domain or c.get("domain") == "*" or not domain)
        and (c.get("profileId") == clean_id or c.get("profileId") == "global")
    ]

    actions = []
    unresolved = []

    for f in fields:
        fid = f.get("field_id") or f.get("id")
        fname = f.get("name") or ""
        flabel = (f.get("label") or "").strip().lower()

        # Check correction memory
        corr = next(
            (c for c in matching_corrections if c.get("fieldSignature") in (fid, fname) or (flabel and c.get("fieldLabel", "").lower() == flabel)),
            None
        )
        if corr:
            actions.append({
                "field_id": fid,
                "value": corr.get("correctionValue"),
                "confidence": 1.0,
                "reason": "Applied from saved correction memory",
                "source": "correction_memory",
                "status": "approved",
                "is_file": False
            })
            continue

        # Deterministic match
        matched = python_deterministic_matcher(f, applicant, docs)
        if matched:
            actions.append({
                "field_id": fid,
                "value": matched["value"],
                "confidence": matched["confidence"],
                "reason": matched["reason"],
                "source": matched["source"],
                "status": matched["status"],
                "is_file": matched.get("isFile", False)
            })
        else:
            unresolved.append(f)

    # Use central AIProviderManager for custom / open-ended questions
    if unresolved:
        ai_answers = python_ai_answer_questions(unresolved, applicant, page_context)
        for ans in ai_answers:
            if ans.get("proposed_value") or ans.get("value"):
                actions.append({
                    "field_id": ans.get("field_id"),
                    "value": ans.get("proposed_value") or ans.get("value"),
                    "confidence": float(ans.get("confidence", 0.9)),
                    "reason": ans.get("reason", "KI-Vorschlag basierend auf Bewerberprofil"),
                    "source": "ai_provider_manager",
                    "status": "review" if ans.get("review_required") else "approved",
                    "is_file": False
                })

    return jsonify({
        "success": True,
        "actions": actions,
        "unresolved": [u.get("field_id") or u.get("id") for u in unresolved if not any(a["field_id"] == (u.get("field_id") or u.get("id")) for a in actions)],
        "engine": "central_ai_gateway"
    })


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

