"""
JobScout Conductor Blueprint & REST API Routes.
Provides full dashboard control for autonomous orchestration:
- Real-time engine status, metrics, daemon start/stop, and global emergency stop
- Per-client automation configuration, pause/resume, and on-demand execution
- Match approval and application dispatching
- Email reply monitoring feed, manual check trigger, and test simulator
- Proactive WhatsApp liaison triggers (digest, missing document requests)
- System activity logs and task execution history with retry controls
"""

from datetime import datetime, timezone
import logging
import uuid
from flask import Blueprint, jsonify, render_template, request
from services.conductor_engine import conductor_engine
from services.conductor_store import conductor_store
from services.conductor_whatsapp_liaison import conductor_whatsapp_liaison
from services.email_reply_monitor import email_reply_monitor

logger = logging.getLogger(__name__)

conductor_bp = Blueprint("conductor", __name__)


@conductor_bp.route("/conductor", methods=["GET"])
@conductor_bp.route("/autopilot", methods=["GET"])
def conductor_page():
    """Render the JobScout SPA shell with Conductor section active."""
    import os
    supabase_url = os.getenv("VITE_SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    supabase_anon_key = os.getenv("VITE_SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
    return render_template(
        "app_shell.html",
        initial_section="conductor",
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
    )


@conductor_bp.route("/api/conductor/status", methods=["GET"])
def get_conductor_status():
    """Returns engine status, metrics, managed clients, recent tasks, and activity logs."""
    try:
        status = conductor_engine.get_status()
        return jsonify({"success": True, "data": status}), 200
    except Exception as exc:
        logger.error("Error retrieving Conductor status: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/engine/toggle", methods=["POST"])
def toggle_conductor_engine():
    """Starts or stops the Conductor background orchestration daemon."""
    try:
        body = request.get_json(silent=True) or {}
        action = str(body.get("action", "")).lower()
        if action == "stop" or (not action and conductor_engine.is_running()):
            conductor_engine.stop()
        else:
            conductor_engine.start()
        return jsonify({
            "success": True,
            "is_running": conductor_engine.is_running(),
            "message": "Conductor background worker started." if conductor_engine.is_running() else "Conductor background worker stopped.",
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/emergency-stop", methods=["POST"])
def toggle_emergency_stop():
    """Toggles the global emergency stop circuit breaker."""
    try:
        body = request.get_json(silent=True) or {}
        enabled = bool(body.get("enabled", True))
        conductor_store.set_emergency_stop(enabled)
        return jsonify({
            "success": True,
            "emergency_stop": enabled,
            "message": "Emergency Stop activated. All autonomous actions halted." if enabled else "Emergency Stop deactivated. Autonomous operations resumed.",
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/settings", methods=["POST"])
def update_conductor_settings():
    """Updates Conductor global operational settings."""
    try:
        body = request.get_json(silent=True) or {}
        for k, v in body.items():
            conductor_store.set_setting(k, v)
        return jsonify({
            "success": True,
            "settings": conductor_store.get_all_settings(),
            "message": "Conductor settings updated successfully.",
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/clients", methods=["GET"])
def list_conductor_clients():
    """Lists all managed clients with their automation toggles and stats."""
    try:
        status = conductor_engine.get_status()
        return jsonify({"success": True, "clients": status.get("clients", [])}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/clients/<client_id>", methods=["POST"])
def update_client_automation_config(client_id):
    """Updates automation settings for a specific client (auto_search, auto_cover_letter, auto_apply, auto_notify_whatsapp, is_paused, etc.)."""
    try:
        body = request.get_json(silent=True) or {}
        updated = conductor_store.update_client_config(client_id, body)
        conductor_store.log_event("INFO", "conductor", f"Updated automation config for {client_id}.", client_id=client_id)
        return jsonify({"success": True, "config": updated}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/clients/<client_id>/pause", methods=["POST"])
def pause_or_resume_client(client_id):
    """Pauses or resumes automation for a specific client."""
    try:
        body = request.get_json(silent=True) or {}
        if "paused" in body:
            paused = bool(body.get("paused"))
        else:
            cfg = conductor_store.get_client_config(client_id)
            paused = not bool(cfg.get("is_paused", 0))
        updated = conductor_engine.pause_client(client_id, paused)
        return jsonify({
            "success": True,
            "client_id": client_id,
            "is_paused": bool(updated.get("is_paused", 0)),
            "config": updated,
            "message": f"Automation {'paused' if paused else 'resumed'} for {client_id}.",
        }), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/clients/<client_id>/run", methods=["POST"])
def run_client_cycle(client_id):
    """Manually triggers an autonomous cycle for a single client."""
    try:
        res = conductor_engine.run_cycle_for_client(client_id, trigger_source="manual_dashboard")
        return jsonify(res), 200 if res.get("success") else 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/run-cycle", methods=["POST"])
def run_global_cycle():
    """Manually triggers an autonomous cycle across all eligible clients."""
    try:
        res = conductor_engine.run_global_cycle(trigger_source="manual_dashboard")
        return jsonify(res), 200 if res.get("success") else 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/matches", methods=["GET"])
def list_matches():
    """Lists discovered matches and staged applications."""
    try:
        client_id = request.args.get("client_id")
        status = request.args.get("status")
        limit = int(request.args.get("limit", 100))
        matches = conductor_store.list_matches(client_id=client_id, status=status, limit=limit)
        return jsonify({"success": True, "count": len(matches), "matches": matches}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/matches/<match_id>/approve", methods=["POST"])
def approve_match(match_id):
    """Approves a staged application, marks it as applied, and updates client statistics."""
    try:
        res = conductor_engine.approve_match(match_id)
        if not res.get("success"):
            return jsonify(res), 404
        return jsonify(res), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/email-monitor/check-now", methods=["POST"])
def check_email_inbox_now():
    """Triggers an immediate check of the recruitment email inbox."""
    try:
        res = conductor_engine.check_inbox_now()
        return jsonify(res), 200 if res.get("success") else 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/email-monitor/simulate", methods=["POST"])
def simulate_incoming_recruiter_email():
    """Simulates an incoming recruiter email for testing classification, status updates, and alerts."""
    try:
        body = request.get_json(silent=True) or {}
        sender = str(body.get("sender") or "karriere@alpha-tech.de").strip()
        recipient = str(body.get("recipient") or "bewerbung@jobscout-hub.com").strip()
        subject = str(body.get("subject") or "Einladung zum Vorstellungsgespräch - Alpha Solutions GmbH").strip()
        email_body = str(
            body.get("body")
            or "Sehr geehrte(r) Bewerber(in), wir haben Ihre Bewerbung geprüft und möchten Sie gerne zu einem persönlichen Vorstellungsgespräch einladen."
        ).strip()
        client_id_hint = str(body.get("client_id") or "").strip()
        msg_id = str(body.get("message_id") or f"sim_email_{uuid.uuid4().hex[:10]}")

        processed = email_reply_monitor.process_incoming_message(
            message_id=msg_id,
            sender=sender,
            recipient=recipient,
            subject=subject,
            received_at=datetime.now(timezone.utc).isoformat(),
            body=email_body,
            client_id_hint=client_id_hint,
        )
        return jsonify({"success": True, "message": processed}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/email-monitor/logs", methods=["GET"])
def list_email_monitor_logs():
    """Lists processed recruiter email replies."""
    try:
        limit = int(request.args.get("limit", 50))
        intent = request.args.get("intent")
        client_id = request.args.get("client_id")
        logs = conductor_store.list_inbox_logs(limit=limit, intent=intent, client_id=client_id)
        return jsonify({"success": True, "count": len(logs), "logs": logs}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/whatsapp/digest/<client_id>", methods=["POST"])
def send_whatsapp_digest(client_id):
    """Manually triggers sending a WhatsApp progress digest to the client."""
    try:
        body = request.get_json(silent=True) or {}
        period = str(body.get("period") or "daily")
        sent = conductor_whatsapp_liaison.send_daily_digest(client_id, period=period, force=True)
        return jsonify({"success": sent, "message": "Digest sent" if sent else "Failed to send digest or notifications disabled"}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/whatsapp/request-docs/<client_id>", methods=["POST"])
def send_whatsapp_document_request(client_id):
    """Requests missing documents from the candidate via WhatsApp."""
    try:
        sent = conductor_whatsapp_liaison.request_missing_documents(client_id, force=True)
        return jsonify({"success": sent, "message": "Document request sent" if sent else "Profile already complete or notifications disabled"}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/tasks", methods=["GET"])
def list_conductor_tasks():
    """Lists recent orchestration tasks."""
    try:
        limit = int(request.args.get("limit", 50))
        client_id = request.args.get("client_id")
        status = request.args.get("status")
        tasks = conductor_store.list_tasks(limit=limit, client_id=client_id, status=status)
        return jsonify({"success": True, "count": len(tasks), "tasks": tasks}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/tasks/<task_id>/retry", methods=["POST"])
def retry_conductor_task(task_id):
    """Retries a failed orchestration task."""
    try:
        res = conductor_engine.retry_task(task_id)
        return jsonify(res), 200 if res.get("success") else 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@conductor_bp.route("/api/conductor/logs", methods=["GET"])
def list_conductor_logs():
    """Lists recent operational activity logs."""
    try:
        limit = int(request.args.get("limit", 100))
        module = request.args.get("module")
        client_id = request.args.get("client_id")
        logs = conductor_store.list_logs(limit=limit, module=module, client_id=client_id)
        return jsonify({"success": True, "count": len(logs), "logs": logs}), 200
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
