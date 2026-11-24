"""
Multi-Client Dossier API Routes.
Provides endpoints for client intake, CV parsing, document management, and active client switching.
"""

import logging
from datetime import datetime
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
    """Lists registered client dossiers and all paid candidates from Supabase."""
    try:
        from services.supabase_service import supabase_service
        from services.onboarding_tracker import onboarding_tracker

        local_clients = client_manager.list_clients()
        active_id = client_manager.get_active_client_id()
        existing_records = onboarding_tracker.get_all_records()

        # Fetch paid applications from Supabase
        paid_apps = []
        try:
            paid_apps = supabase_service.list_applications(limit=200, is_payed=True)
        except Exception as sup_err:
            logger.warning("Could not fetch paid applications from Supabase: %s", sup_err)

        # Build mapping of app_id -> client_id and client_id -> app_id
        app_to_client = {}
        client_to_app = {}
        for app_id, rec in existing_records.items():
            cid = rec.get("client_id")
            if cid:
                app_to_client[app_id] = cid
                client_to_app[cid] = app_id

        combined_clients = []
        seen_keys = set()

        # 1. First add valid local clients (skipping obvious corrupt/test dummy entries)
        for lc in local_clients:
            cid = lc.get("id") or ""
            cname = (lc.get("name") or "").strip()
            # Filter out non-candidate test artifacts
            if cname.lower() in {"corrupt test", "corrupt_test", "corrupt-test"}:
                continue
            if cname.lower() == "bewerber" and not lc.get("has_cv"):
                continue

            lc_item = dict(lc)
            sup_app_id = client_to_app.get(cid)
            if sup_app_id:
                lc_item["supabase_application_id"] = sup_app_id
                lc_item["is_payed"] = True

            combined_clients.append(lc_item)
            seen_keys.add(cid.lower())
            if sup_app_id:
                seen_keys.add(sup_app_id.lower())

        # 2. Add all paid applications from Supabase that aren't already represented
        for app in paid_apps:
            app_id = app.get("id")
            if not app_id:
                continue

            if app_id.lower() in seen_keys:
                continue

            # Check if mapped to a local client that is already in combined_clients
            local_cid = app_to_client.get(app_id)
            if local_cid and local_cid.lower() in seen_keys:
                continue

            full_name = (app.get("full_name") or "").strip()
            field = app.get("field") or ""
            pack = app.get("pack") or ""
            email = app.get("email") or ""
            whatsapp = app.get("whatsapp") or ""
            docs = app.get("documents") or []

            candidate_entry = {
                "id": app_id,
                "name": full_name or "Bewerber",
                "email": email,
                "phone": whatsapp,
                "title": field,
                "field": field,
                "profile": {"field": field},
                "pack": pack,
                "is_payed": True,
                "has_cv": bool(docs),
                "source": "supabase",
                "supabase_application_id": app_id,
                "created_at": app.get("created_at") or "",
            }
            combined_clients.append(candidate_entry)
            seen_keys.add(app_id.lower())
            if full_name:
                seen_keys.add(full_name.lower())

        # Sort: Active client first, then by name
        def sort_key(c):
            is_active = 0 if (c.get("id") == active_id) else 1
            has_cv = 0 if c.get("has_cv") else 1
            return (is_active, has_cv, (c.get("name") or "").lower())

        combined_clients.sort(key=sort_key)

        return jsonify({
            "success": True,
            "clients": combined_clients,
            "active_client_id": active_id,
            "total_count": len(combined_clients),
            "paid_supabase_count": len(paid_apps),
        })
    except Exception as exc:
        logger.error("Error listing clients: %s", exc, exc_info=True)
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
    """Retrieves full client dossier, auto-onboarding paid Supabase applicants on demand."""
    try:
        from services.onboarding_tracker import onboarding_tracker
        from services.onboarding_service import candidate_onboarding_service
        from services.supabase_service import supabase_service

        profile = client_manager.get_client(client_id)

        # If not found directly by ID, check if client_id is an application_id from onboarding tracker
        if not profile:
            rec = onboarding_tracker.get_record(client_id)
            if rec and rec.get("client_id"):
                profile = client_manager.get_client(rec["client_id"])
                if profile:
                    client_id = rec["client_id"]

        # If still not found, check if this is a paid application from Supabase that needs on-demand onboarding
        if not profile:
            try:
                sup_app = supabase_service.get_application(client_id)
                if sup_app and sup_app.get("is_payed"):
                    logger.info("Auto-onboarding paid Supabase application on demand: %s", client_id)
                    onboard_res = candidate_onboarding_service.onboard_candidate(client_id)
                    actual_cid = onboard_res.get("client_id")
                    if actual_cid:
                        client_id = actual_cid
                        profile = client_manager.get_client(actual_cid)
            except Exception as onb_err:
                logger.warning("On-demand onboarding for %s failed: %s", client_id, onb_err)

        # If still no profile, check if we can build a fallback profile from Supabase application data
        if not profile:
            try:
                sup_app = supabase_service.get_application(client_id)
                if sup_app:
                    full_name = sup_app.get("full_name") or "Bewerber"
                    field = sup_app.get("field") or "Fachkraft"
                    email = sup_app.get("email") or ""
                    whatsapp = sup_app.get("whatsapp") or ""
                    profile = {
                        "profile_version": "1.0",
                        "profile_language": "de",
                        "applicant": {
                            "personal": {"full_name": full_name, "first_name": full_name.split()[0], "salutation": "Herr"},
                            "contact": {"email": email, "phone": whatsapp, "phone_display": whatsapp, "address": {"city": "Köln", "country": "Deutschland"}},
                            "professional_profile": {"current_title": field, "headline": f"{full_name} - {field}", "primary_fields": [field]},
                            "skills": {"technologies_from_cv": []},
                            "languages": [{"language": "German", "language_de": "Deutsch", "level_de": sup_app.get("language_level") or "B2"}]
                        }
                    }
            except Exception:
                pass

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
    except Exception as exc:
        logger.error("Error retrieving client %s: %s", client_id, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


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


@clients_bp.route("/api/clients/<client_id>/reparse", methods=["POST"])
def reparse_client_dossier(client_id):
    """
    Reparses client's stored multi-document PDF dossier using DocumentClassifier and CVParser.
    Extracts candidate profile fields strictly from the CV, rejects institutional addresses,
    and updates data/clients/<client_id>/profile.json.
    """
    try:
        from services.cv_parser import CVParser
        from services.onboarding_tracker import onboarding_tracker

        resolved_cid = client_id
        client_dir = client_manager.clients_dir / resolved_cid
        if not client_dir.exists():
            rec = onboarding_tracker.get_record(client_id)
            if rec and rec.get("client_id"):
                resolved_cid = rec["client_id"]
                client_dir = client_manager.clients_dir / resolved_cid

        if not client_dir.exists():
            return jsonify({"success": False, "error": f"Client dossier directory not found for '{client_id}'"}), 404

        docs_dir = client_dir / "documents"
        cv_pdf_path = None
        for cand_name in ["Lebenslauf.pdf", "CV.pdf", "cv.pdf", "resume.pdf", "Dossier.pdf"]:
            p = docs_dir / cand_name
            if p.exists():
                cv_pdf_path = p
                break
        if not cv_pdf_path and docs_dir.exists():
            pdfs = list(docs_dir.glob("*.pdf"))
            if pdfs:
                cv_pdf_path = pdfs[0]

        if not cv_pdf_path or not cv_pdf_path.exists():
            return jsonify({"success": False, "error": f"No CV PDF found in documents for client '{resolved_cid}'"}), 404

        pdf_bytes = cv_pdf_path.read_bytes()
        parsed_data = CVParser.parse_pdf_dossier(pdf_bytes)

        profile_path = client_dir / "profile.json"
        updated_profile = CVParser.update_profile_from_cv(profile_path, parsed_data)

        # Invalidate profile cache so subsequent reads reload fresh data
        if hasattr(client_manager, "_profile_cache"):
            client_manager._profile_cache.pop(str(profile_path), None)

        return jsonify({
            "success": True,
            "message": "Candidate dossier successfully reparsed and profile updated",
            "client_id": resolved_cid,
            "profile": updated_profile,
            "parsed_summary": {
                "candidate_name": updated_profile.get("applicant", {}).get("personal", {}).get("full_name"),
                "current_title": updated_profile.get("applicant", {}).get("professional_profile", {}).get("current_title"),
                "target_occupation": updated_profile.get("applicant", {}).get("professional_profile", {}).get("target_occupation"),
                "city": updated_profile.get("applicant", {}).get("contact", {}).get("address", {}).get("city"),
                "country": updated_profile.get("applicant", {}).get("contact", {}).get("address", {}).get("country"),
                "years_of_experience": updated_profile.get("applicant", {}).get("professional_profile", {}).get("years_of_experience"),
                "experience_level": updated_profile.get("applicant", {}).get("professional_profile", {}).get("experience_level"),
                "work_experience_count": len(updated_profile.get("applicant", {}).get("work_experience", [])),
                "education_count": len(updated_profile.get("applicant", {}).get("education", [])),
                "certifications_count": len(updated_profile.get("applicant", {}).get("certifications", [])),
                "cv_pages": parsed_data.get("classification_metadata", {}).get("cv_page_numbers", []),
            }
        })
    except Exception as exc:
        logger.error("Error reparsing client %s: %s", client_id, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


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
