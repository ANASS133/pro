"""
Supabase Candidate Onboarding Blueprint for JobScout.
Provides secure endpoints for importing paid client applications,
querying persistent onboarding status, and resolving candidate dossiers.
"""

import logging
from flask import Blueprint, jsonify, request

from services.onboarding_service import candidate_onboarding_service
from services.onboarding_tracker import onboarding_tracker
from services.supabase_service import (
    ApplicationNotFoundError,
    DocumentDownloadError,
    PaymentUnverifiedError,
    SupabaseServiceError,
)
from services.client_manager import client_manager

logger = logging.getLogger(__name__)

supabase_onboarding_bp = Blueprint("supabase_onboarding", __name__)


@supabase_onboarding_bp.route("/api/supabase/onboard-candidate", methods=["POST"])
def onboard_candidate_endpoint():
    """
    Imports a paid Supabase application as a JobScout candidate.
    Downloads submitted documents, parses CV, merges form data,
    associates package quota, and persists candidate dossier.
    """
    data = request.get_json(silent=True) or {}
    application_id = str(data.get("application_id") or "").strip()
    force_reimport = bool(data.get("force_reimport", False))

    if not application_id:
        return jsonify({
            "success": False,
            "error": "INVALID_REQUEST",
            "message": "application_id ist erforderlich.",
        }), 400

    try:
        result = candidate_onboarding_service.onboard_candidate(
            application_id=application_id,
            force_reimport=force_reimport,
        )
        return jsonify(result), 200

    except PaymentUnverifiedError as exc:
        return jsonify({
            "success": False,
            "error": "PAYMENT_UNVERIFIED",
            "message": str(exc),
        }), 400

    except ApplicationNotFoundError as exc:
        return jsonify({
            "success": False,
            "error": "APPLICATION_NOT_FOUND",
            "message": str(exc),
        }), 404

    except DocumentDownloadError as exc:
        return jsonify({
            "success": False,
            "error": "DOCUMENT_DOWNLOAD_ERROR",
            "message": f"Dokumenten-Import fehlgeschlagen: {exc}",
        }), 502

    except Exception as exc:
        logger.error("Unhandled error onboarding application %s: %s", application_id, exc, exc_info=True)
        return jsonify({
            "success": False,
            "error": "INTERNAL_ERROR",
            "message": f"Interner Fehler beim Onboarding: {exc}",
        }), 500


@supabase_onboarding_bp.route("/api/supabase/onboarding-status", methods=["GET"])
def get_all_onboarding_statuses():
    """Returns persistent onboarding records for all imported applications."""
    try:
        records = onboarding_tracker.get_all_records()
        return jsonify({
            "success": True,
            "records": records,
        }), 200
    except Exception as exc:
        logger.error("Error retrieving onboarding records: %s", exc)
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 500


@supabase_onboarding_bp.route("/api/supabase/onboarding-status/<application_id>", methods=["GET"])
def get_single_onboarding_status(application_id: str):
    """Returns onboarding status for a specific Supabase application ID."""
    clean_id = str(application_id or "").strip()
    record = onboarding_tracker.get_record(clean_id)
    if not record:
        return jsonify({
            "success": False,
            "error": "NOT_FOUND",
            "message": f"Kein Onboarding-Eintrag für {clean_id} gefunden.",
        }), 404

    return jsonify({
        "success": True,
        "record": record,
    }), 200


@supabase_onboarding_bp.route("/api/supabase/candidate-by-application/<application_id>", methods=["GET"])
def get_candidate_by_application(application_id: str):
    """
    Resolves the JobScout candidate dossier linked to a Supabase application ID.
    Used by Cover Letter Studio and Autofill Hub for persistent client profile loading.
    """
    clean_id = str(application_id or "").strip()
    record = onboarding_tracker.get_record(clean_id)
    if not record or not record.get("client_id"):
        return jsonify({
            "success": False,
            "error": "NOT_ONBOARDED",
            "message": "Bewerbung wurde noch nicht als Kandidat importiert.",
        }), 404

    client_id = record["client_id"]
    profile = client_manager.get_client(client_id)
    if not profile:
        return jsonify({
            "success": False,
            "error": "PROFILE_NOT_FOUND",
            "message": f"Kandidaten-Profil '{client_id}' wurde nicht im Speicher gefunden.",
        }), 404

    docs = client_manager.list_documents(client_id)
    return jsonify({
        "success": True,
        "client_id": client_id,
        "profile": profile,
        "documents": docs,
        "onboarding_record": record,
    }), 200
