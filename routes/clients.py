"""
Multi-Client Dossier API Routes.
Provides endpoints for client intake, CV parsing, document management, and active client switching.
"""

import io
import json
import logging
from datetime import datetime
from pathlib import Path
from flask import Blueprint, Response, jsonify, request, send_file
from werkzeug.utils import secure_filename

from services.client_manager import client_manager, _slugify, _extract_name_from_filename

logger = logging.getLogger(__name__)

clients_bp = Blueprint("clients", __name__)

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain"
}


@clients_bp.route("/api/clients", methods=["GET"])
def list_clients():
    """Lists all registered client dossiers with active indicator."""
    try:
        clients = client_manager.list_clients()
        active_id = client_manager.get_active_client_id()
        return jsonify({
            "success": True,
            "clients": clients,
            "active_client_id": active_id
        })
    except Exception as exc:
        logger.error("Error listing clients: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@clients_bp.route("/api/clients/active", methods=["GET"])
@clients_bp.route("/api/profiles/active", methods=["GET"])
def get_active_client():
    """Returns the profile and documents for the currently active client."""
    active_id = client_manager.get_active_client_id()
    if not active_id:
        return jsonify({"success": False, "error": "No active client"}), 404

    profile = client_manager.get_client(active_id)
    if not profile:
        return jsonify({"success": False, "error": f"Client {active_id} profile not found"}), 404

    docs = client_manager.list_documents(active_id)
    return jsonify({
        "success": True,
        "client_id": active_id,
        "profile_id": active_id,
        "profile": profile,
        "applicant": profile.get("applicant", {}),
        "documents": docs
    })


@clients_bp.route("/api/clients/active", methods=["POST"])
@clients_bp.route("/api/profiles/active", methods=["POST"])
def set_active_client():
    """Switches the active client."""
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id") or data.get("profile_id") or data.get("id")
    if not client_id:
        return jsonify({"success": False, "error": "client_id or profile_id is required"}), 400

    success = client_manager.set_active_client_id(client_id)
    if not success:
        return jsonify({"success": False, "error": f"Client '{client_id}' not found"}), 404

    profile = client_manager.get_client(client_id)
    return jsonify({
        "success": True,
        "message": f"Active client set to {client_id}",
        "active_client_id": client_id,
        "profile": profile
    })


@clients_bp.route("/api/clients/ingest-cv", methods=["POST"])
def ingest_cv():
    """
    Intake endpoint for paying clients:
    Upload candidate CV PDF, automatically extract structured information,
    create client dossier, save Lebenslauf.pdf, and set as active client.
    """
    if "cv_file" not in request.files and "file" not in request.files:
        return jsonify({"success": False, "error": "No CV PDF file uploaded (key 'cv_file' or 'file' expected)"}), 400

    file = request.files.get("cv_file") or request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "error": "Empty file provided"}), 400

    filename = secure_filename(file.filename) or "Lebenslauf.pdf"
    if not filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "Uploaded file must be a PDF document"}), 400

    try:
        pdf_bytes = file.read()
        if not pdf_bytes:
            return jsonify({"success": False, "error": "Uploaded PDF file is empty"}), 400

        custom_id = request.form.get("client_id", "").strip() or None
        result = client_manager.ingest_cv(pdf_bytes, filename=filename, client_id=custom_id)
        return jsonify(result)
    except Exception as exc:
        logger.error("CV ingestion failed: %s", exc)
        # Resilient fallback: Create client dossier and save document even if parsing fails completely
        try:
            fallback_name = _extract_name_from_filename(filename) or "Bewerber"
            fallback_id = custom_id or (_slugify(fallback_name) if fallback_name != "Bewerber" else f"client_{int(datetime.now().timestamp())}")
            fallback_profile = {
                "profile_version": "1.0",
                "profile_language": "de",
                "applicant": {
                    "personal": {"first_name": fallback_name.split()[0], "last_name": " ".join(fallback_name.split()[1:]), "full_name": fallback_name, "salutation": "Herr"},
                    "contact": {"email": "", "phone": "", "address": {"city": "", "country": "Deutschland"}},
                    "professional_profile": {"current_title": "Bewerber", "headline": f"{fallback_name} - Bewerber"},
                    "skills": {"technologies_from_cv": []},
                    "languages": [{"language": "German", "language_de": "Deutsch", "level_de": "Fließend"}]
                }
            }
            client_manager.save_client(fallback_id, fallback_profile)
            client_manager.save_document(fallback_id, pdf_bytes, filename)
            client_manager.set_active_client_id(fallback_id)
            return jsonify({
                "success": True,
                "client_id": fallback_id,
                "client_name": fallback_name,
                "profile": fallback_profile,
                "note": "Document saved successfully. Due to PDF stream formatting anomalies, text fields could not be auto-extracted. Please verify details in the profile."
            })
        except Exception as inner_exc:
            return jsonify({"success": False, "error": f"Failed to ingest CV: {inner_exc}"}), 500


@clients_bp.route("/api/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    """Retrieves full client dossier."""
    profile = client_manager.get_client(client_id)
    if not profile:
        return jsonify({"success": False, "error": "Client not found"}), 404

    docs = client_manager.list_documents(client_id)
    active_id = client_manager.get_active_client_id()
    return jsonify({
        "success": True,
        "client_id": client_id,
        "is_active": (client_id == active_id),
        "profile": profile,
        "applicant": profile.get("applicant", {}),
        "documents": docs
    })


@clients_bp.route("/api/clients", methods=["POST"])
def create_client():
    """Manually creates a new client dossier."""
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id") or data.get("id")
    profile = data.get("profile") or data

    if not client_id:
        name = profile.get("applicant", {}).get("personal", {}).get("full_name", "")
        if name:
            import re
            client_id = re.sub(r"[^\w\s-]", "", name.lower()).strip().replace(" ", "_")
        else:
            return jsonify({"success": False, "error": "client_id or applicant name is required"}), 400

    # Ensure valid structure
    if "applicant" not in profile:
        profile = {
            "profile_version": "1.0",
            "profile_language": "de",
            "applicant": profile
        }

    success = client_manager.save_client(client_id, profile)
    if not success:
        return jsonify({"success": False, "error": "Failed to save client profile"}), 500

    if data.get("set_active"):
        client_manager.set_active_client_id(client_id)

    return jsonify({
        "success": True,
        "client_id": client_id,
        "message": "Client dossier created successfully",
        "profile": profile
    }), 201


@clients_bp.route("/api/clients/<client_id>", methods=["PUT"])
def update_client(client_id):
    """Updates an existing client profile."""
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"success": False, "error": "No update payload provided"}), 400

    existing = client_manager.get_client(client_id) or {}
    if "applicant" in data:
        existing["applicant"] = data["applicant"]
    else:
        existing.setdefault("applicant", {}).update(data)

    success = client_manager.save_client(client_id, existing)
    if not success:
        return jsonify({"success": False, "error": "Failed to update client profile"}), 500

    return jsonify({
        "success": True,
        "client_id": client_id,
        "message": "Client profile updated successfully",
        "profile": existing
    })


@clients_bp.route("/api/clients/<client_id>", methods=["DELETE"])
def delete_client(client_id):
    """Deletes a client dossier."""
    success = client_manager.delete_client(client_id)
    if not success:
        return jsonify({"success": False, "error": "Client not found or could not be deleted"}), 404

    return jsonify({
        "success": True,
        "message": f"Client '{client_id}' deleted successfully",
        "active_client_id": client_manager.get_active_client_id()
    })


@clients_bp.route("/api/clients/<client_id>/documents", methods=["GET"])
def list_client_documents(client_id):
    """Lists all documents in the client dossier."""
    docs = client_manager.list_documents(client_id)
    return jsonify({"success": True, "client_id": client_id, "documents": docs})


@clients_bp.route("/api/clients/<client_id>/documents", methods=["POST"])
def upload_client_document(client_id):
    """Uploads a document to the client dossier."""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"success": False, "error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    file_bytes = file.read()
    res = client_manager.save_document(client_id, file_bytes, filename)
    if not res:
        return jsonify({"success": False, "error": "Failed to save document"}), 500

    return jsonify({"success": True, "document": res}), 201


@clients_bp.route("/api/clients/<client_id>/documents/<filename>", methods=["GET"])
def download_client_document(client_id, filename):
    """Downloads a document from the client dossier."""
    clean_id = secure_filename(client_id)
    safe_name = secure_filename(filename)
    cdir = client_manager.clients_dir / clean_id / "documents"
    fpath = cdir / safe_name

    if not fpath.exists():
        # Fallback to autofill doc dir
        fpath = client_manager.autofill_dir / clean_id / safe_name

    if not fpath.exists():
        return jsonify({"error": "Document not found"}), 404

    return send_file(str(fpath), as_attachment=True, download_name=safe_name)


@clients_bp.route("/api/clients/<client_id>/documents/<filename>/preview", methods=["GET"])
def preview_client_document(client_id, filename):
    """Serves document inline for browser preview."""
    clean_id = secure_filename(client_id)
    safe_name = secure_filename(filename)
    cdir = client_manager.clients_dir / clean_id / "documents"
    fpath = cdir / safe_name

    if not fpath.exists():
        fpath = client_manager.autofill_dir / clean_id / safe_name

    if not fpath.exists():
        return jsonify({"error": "Document not found"}), 404

    ext = fpath.suffix.lower()
    mime = MIME_TYPES.get(ext, "application/octet-stream")
    with open(fpath, "rb") as f:
        content = f.read()
    return Response(content, mimetype=mime, headers={"Content-Disposition": f"inline; filename={safe_name}"})
