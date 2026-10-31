"""
JobScout WhatsApp AI Customer Support Center Blueprint & API Endpoints
=====================================================================
Modular Flask routes providing:
- Webhook verification & HMAC-SHA256 signature validation
- Real-time Server-Sent Events (SSE) live stream (/api/whatsapp/stream)
- Conversation listing, inspection, and manual message dispatch
- Atomic state transitions: Takeover, Resume AI, Escalate, Pause, Close
- AI draft suggestions for human agents
- Knowledge Base management & search
- Operational metrics & audit logs
- Secure settings configuration
"""

import json
import logging
import queue
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

from services.client_manager import client_manager
from services.whatsapp_ai_engine import whatsapp_ai_engine
from services.whatsapp_service import WhatsAppAPIError, whatsapp_service
from services.whatsapp_store import ConcurrencyConflictError, whatsapp_store

logger = logging.getLogger(__name__)

whatsapp_bp = Blueprint("whatsapp", __name__)


# -----------------------------------------------------------------------------
# Meta WhatsApp Cloud API Webhook Endpoints
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/api/whatsapp/webhook", methods=["GET"])
def webhook_verify():
    """Meta webhook verification handshake (GET)."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    verified_challenge = whatsapp_service.verify_webhook_token(mode, token, challenge)
    if verified_challenge is not None:
        return Response(verified_challenge, status=200, mimetype="text/plain")

    return jsonify({"error": "Forbidden", "message": "Verification token mismatch"}), 403


@whatsapp_bp.route("/api/whatsapp/webhook", methods=["POST"])
def webhook_event():
    """
    Incoming Meta webhook events (POST).
    Validates HMAC-SHA256 signature, enqueues payload asynchronously,
    and returns HTTP 200 within milliseconds to satisfy Meta timeouts.
    """
    raw_payload = request.get_data()
    signature_header = request.headers.get("X-Hub-Signature-256")

    # 1. Validate signature
    if not whatsapp_service.validate_signature(raw_payload, signature_header):
        logger.warning("Rejected WhatsApp webhook: invalid HMAC-SHA256 signature.")
        return jsonify({"error": "Unauthorized", "message": "Invalid signature"}), 401

    # 2. Parse JSON
    try:
        payload_json = json.loads(raw_payload.decode("utf-8"))
    except Exception as exc:
        logger.error("Malformed WhatsApp webhook JSON: %s", exc)
        return jsonify({"error": "Bad Request", "message": "Invalid JSON"}), 400

    # 3. Fast enqueue for background processing
    enqueued = whatsapp_service.enqueue_webhook_event(payload_json)
    if not enqueued:
        return jsonify({"error": "Service Unavailable", "message": "Queue overloaded"}), 503

    return Response("EVENT_RECEIVED", status=200, mimetype="text/plain")


# -----------------------------------------------------------------------------
# Real-Time Server-Sent Events (SSE) Live Stream
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/api/whatsapp/stream", methods=["GET"])
def stream_whatsapp_events():
    """
    Server-Sent Events (SSE) live updates for the WhatsApp AI Center inbox.
    Pushes new incoming/outgoing messages, delivery status updates,
    conversation state transitions, and escalation alerts in real time.
    """
    sub_queue = whatsapp_service.subscribe_realtime_events()

    @stream_with_context
    def event_stream():
        heartbeats = 0
        try:
            # Send initial connected handshake
            yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'timestamp': time.time()})}\n\n"

            while heartbeats < 3600:  # 1 hour max connection
                try:
                    event = sub_queue.get(timeout=2.0)
                    yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n"
                    heartbeats = 0
                except queue.Empty:
                    heartbeats += 1
                    # Heartbeat comment every 10 seconds to keep connection alive
                    if heartbeats % 5 == 0:
                        yield f": heartbeat {int(time.time())}\n\n"
        finally:
            whatsapp_service.unsubscribe_realtime_events(sub_queue)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


# -----------------------------------------------------------------------------
# Conversations Management Endpoints
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/api/whatsapp/conversations", methods=["GET"])
def list_conversations():
    """Lists conversations with optional filters (mode, escalation, search)."""
    mode = request.args.get("mode")
    escalation = request.args.get("escalation")
    search = request.args.get("search")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))

    conversations = whatsapp_store.list_conversations(
        mode=mode,
        escalation=escalation,
        search=search,
        limit=limit,
        offset=offset,
    )
    return jsonify({"success": True, "conversations": conversations, "count": len(conversations)})


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>", methods=["GET"])
def get_conversation_details(conv_id: str):
    """Retrieves single conversation details along with linked client profile."""
    conv = whatsapp_store.get_conversation(conv_id)
    if not conv:
        return jsonify({"success": False, "message": "Conversation not found"}), 404

    # Attach verified client info if linked
    client_profile = None
    if conv.get("client_id"):
        client_profile = client_manager.get_client_profile(conv["client_id"])

    # Mark read when opened by agent
    whatsapp_store.mark_conversation_read(conv_id)

    return jsonify({
        "success": True,
        "conversation": conv,
        "client_profile": client_profile,
    })


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/messages", methods=["GET"])
def get_conversation_messages(conv_id: str):
    """Retrieves chronological message history."""
    limit = min(int(request.args.get("limit", 100)), 200)
    before_id = request.args.get("before_id")

    conv = whatsapp_store.get_conversation(conv_id)
    if not conv:
        return jsonify({"success": False, "message": "Conversation not found"}), 404

    messages = whatsapp_store.get_messages(conv_id, limit=limit, before_id=before_id)
    return jsonify({"success": True, "messages": messages, "count": len(messages)})


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/messages", methods=["POST"])
def send_human_reply(conv_id: str):
    """
    Sends an outbound message as a human agent.
    Optionally auto-takes over conversation into HUMAN_ACTIVE if not already.
    """
    data = request.get_json(silent=True) or {}
    content = str(data.get("content") or "").strip()
    agent_name = str(data.get("agent_name") or "Agent").strip()
    auto_takeover = data.get("auto_takeover", True)

    if not content:
        return jsonify({"success": False, "message": "Message content cannot be empty."}), 400

    conv = whatsapp_store.get_conversation(conv_id)
    if not conv:
        return jsonify({"success": False, "message": "Conversation not found"}), 404

    # If currently AI_ACTIVE and human replies, atomically take over
    if auto_takeover and conv.get("mode") == "AI_ACTIVE":
        conv = whatsapp_store.atomic_takeover(conv_id, agent_name)

    to_wa = conv.get("wa_id")
    try:
        send_res = whatsapp_service.send_text_message(to_wa, content)
        provider_wamid = send_res.get("provider_message_id")
        delivery_status = send_res.get("status", "sent")

        stored_msg = whatsapp_store.add_message(
            conversation_id=conv_id,
            direction="outbound",
            sender_type="human",
            sender_name=agent_name,
            content=content,
            provider_message_id=provider_wamid,
            delivery_status=delivery_status,
        )

        whatsapp_service.emit_realtime_event({
            "type": "new_message",
            "conversation_id": conv_id,
            "message": stored_msg,
            "conversation": whatsapp_store.get_conversation(conv_id),
        })

        return jsonify({"success": True, "message": stored_msg}), 200

    except WhatsAppAPIError as exc:
        logger.error("Outbound manual reply failed: %s", exc)
        return jsonify({
            "success": False,
            "message": f"WhatsApp Sende-Fehler: {str(exc)}",
            "error_data": exc.error_data,
        }), 502


# -----------------------------------------------------------------------------
# Atomic State Transition Actions
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/takeover", methods=["POST"])
def manual_takeover(conv_id: str):
    """
    Prominent admin action: takes over conversation from AI.
    Atomically increments version counter and transitions state to HUMAN_ACTIVE.
    """
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name") or "Administrator").strip()

    try:
        updated_conv = whatsapp_store.atomic_takeover(conv_id, agent_name)
        whatsapp_service.emit_realtime_event({
            "type": "conversation_updated",
            "conversation_id": conv_id,
            "action": "takeover",
            "conversation": updated_conv,
        })
        return jsonify({"success": True, "conversation": updated_conv})
    except Exception as exc:
        logger.error("Takeover failed for %s: %s", conv_id, exc)
        return jsonify({"success": False, "message": str(exc)}), 500


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/resume-ai", methods=["POST"])
def resume_ai(conv_id: str):
    """
    Explicit action restoring autonomous AI responses for future incoming messages.
    Atomically increments version counter and sets mode to AI_ACTIVE.
    """
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name") or "Administrator").strip()

    try:
        updated_conv = whatsapp_store.atomic_resume_ai(conv_id, agent_name)
        whatsapp_service.emit_realtime_event({
            "type": "conversation_updated",
            "conversation_id": conv_id,
            "action": "resume_ai",
            "conversation": updated_conv,
        })
        return jsonify({"success": True, "conversation": updated_conv})
    except Exception as exc:
        logger.error("Resume AI failed for %s: %s", conv_id, exc)
        return jsonify({"success": False, "message": str(exc)}), 500


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/escalate", methods=["POST"])
def escalate_conversation(conv_id: str):
    """Transitions conversation to ESCALATED mode and halts autonomous AI."""
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason") or "Manual escalation by agent").strip()
    actor = str(data.get("agent_name") or "Agent").strip()

    try:
        updated_conv = whatsapp_store.atomic_escalate(conv_id, reason=reason, actor=actor)
        whatsapp_service.emit_realtime_event({
            "type": "conversation_updated",
            "conversation_id": conv_id,
            "action": "escalate",
            "conversation": updated_conv,
        })
        return jsonify({"success": True, "conversation": updated_conv})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/pause-ai", methods=["POST"])
def pause_ai(conv_id: str):
    """Pauses AI processing for conversation."""
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name") or "Agent").strip()

    try:
        updated_conv = whatsapp_store.atomic_pause_ai(conv_id, agent_name)
        whatsapp_service.emit_realtime_event({
            "type": "conversation_updated",
            "conversation_id": conv_id,
            "action": "pause_ai",
            "conversation": updated_conv,
        })
        return jsonify({"success": True, "conversation": updated_conv})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/close", methods=["POST"])
def close_conversation(conv_id: str):
    """Closes conversation."""
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name") or "Agent").strip()

    try:
        updated_conv = whatsapp_store.atomic_close(conv_id, agent_name)
        whatsapp_service.emit_realtime_event({
            "type": "conversation_updated",
            "conversation_id": conv_id,
            "action": "close",
            "conversation": updated_conv,
        })
        return jsonify({"success": True, "conversation": updated_conv})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/assign", methods=["POST"])
def assign_agent(conv_id: str):
    """Assigns human agent to conversation."""
    data = request.get_json(silent=True) or {}
    agent_name = str(data.get("agent_name") or "").strip()

    conv = whatsapp_store.get_conversation(conv_id)
    if not conv:
        return jsonify({"success": False, "message": "Conversation not found"}), 404

    updated = whatsapp_store.update_conversation(conv_id, {"assigned_agent": agent_name})
    whatsapp_store.add_audit_log(conv_id, "admin", "assign_agent", details={"assigned_agent": agent_name})
    return jsonify({"success": True, "conversation": updated})


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/link-client", methods=["POST"])
def link_client(conv_id: str):
    """Links conversation to a JobScout client ID and synchronizes verified phone with Dossier & Supabase."""
    data = request.get_json(silent=True) or {}
    client_id = str(data.get("client_id") or "").strip()

    conv = whatsapp_store.get_conversation(conv_id)
    if not conv:
        return jsonify({"success": False, "message": "Conversation not found"}), 404

    # Synchronize verified WhatsApp number to candidate dossier & Supabase
    if client_id and conv.get("wa_id"):
        client_manager.sync_verified_whatsapp(client_id, conv["wa_id"])

    profile = client_manager.get_client_profile(client_id)
    display_name = None
    if profile:
        applicant = profile.get("applicant", {})
        personal = applicant.get("personal", {})
        display_name = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip() or profile.get("name")

    updates = {"client_id": client_id}
    if display_name:
        updates["display_name"] = display_name

    updated = whatsapp_store.update_conversation(conv_id, updates)
    whatsapp_store.add_audit_log(conv_id, "admin", "link_client", details={"client_id": client_id, "wa_id": conv.get("wa_id")})
    return jsonify({"success": True, "conversation": updated, "client_profile": profile})


@whatsapp_bp.route("/api/whatsapp/conversations/<conv_id>/suggest-draft", methods=["POST"])
def suggest_draft(conv_id: str):
    """Generates an AI suggested reply for human agent."""
    res = whatsapp_ai_engine.generate_draft_suggestion(conv_id)
    return jsonify(res)


# -----------------------------------------------------------------------------
# Knowledge Base Endpoints
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/api/whatsapp/knowledge-base", methods=["GET"])
def list_knowledge_base():
    """Lists knowledge base items."""
    category = request.args.get("category")
    active_only = request.args.get("active_only", "false").lower() in ("true", "1")
    items = whatsapp_store.list_knowledge_base(category=category, active_only=active_only)
    return jsonify({"success": True, "items": items, "count": len(items)})


@whatsapp_bp.route("/api/whatsapp/knowledge-base", methods=["POST"])
def create_knowledge_base_item():
    """Creates a new knowledge base entry."""
    data = request.get_json(silent=True) or {}
    category = str(data.get("category") or "faq").strip()
    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()

    if not title or not content:
        return jsonify({"success": False, "message": "Titel und Inhalt sind erforderlich."}), 400

    item = whatsapp_store.create_knowledge_base_item(category, title, content)
    return jsonify({"success": True, "item": item}), 201


@whatsapp_bp.route("/api/whatsapp/knowledge-base/<item_id>", methods=["PUT"])
def update_knowledge_base_item(item_id: str):
    """Updates knowledge base entry."""
    data = request.get_json(silent=True) or {}
    item = whatsapp_store.update_knowledge_base_item(
        item_id,
        category=data.get("category"),
        title=data.get("title"),
        content=data.get("content"),
        is_active=data.get("is_active"),
    )
    if not item:
        return jsonify({"success": False, "message": "Item not found"}), 404
    return jsonify({"success": True, "item": item})


@whatsapp_bp.route("/api/whatsapp/knowledge-base/<item_id>", methods=["DELETE"])
def delete_knowledge_base_item(item_id: str):
    """Deletes knowledge base entry."""
    deleted = whatsapp_store.delete_knowledge_base_item(item_id)
    if not deleted:
        return jsonify({"success": False, "message": "Item not found"}), 404
    return jsonify({"success": True, "message": "Item deleted"})


# -----------------------------------------------------------------------------
# Metrics, Audit Logs & Settings Endpoints
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/api/whatsapp/metrics", methods=["GET"])
def get_metrics():
    """Returns live operational metrics derived from database data."""
    metrics = whatsapp_store.get_overview_metrics()
    return jsonify({"success": True, "metrics": metrics})


@whatsapp_bp.route("/api/whatsapp/audit-logs", methods=["GET"])
def get_audit_logs():
    """Returns recent audit logs."""
    conv_id = request.args.get("conversation_id")
    limit = min(int(request.args.get("limit", 50)), 100)
    logs = whatsapp_store.get_audit_logs(conversation_id=conv_id, limit=limit)
    return jsonify({"success": True, "logs": logs, "count": len(logs)})


@whatsapp_bp.route("/api/whatsapp/settings", methods=["GET"])
def get_settings():
    """Retrieves WhatsApp settings with safe masking of Meta tokens."""
    settings = whatsapp_store.get_all_settings()
    # Mask secrets
    token = whatsapp_service.access_token
    masked_token = f"{token[:6]}...{token[-4:]}" if token and len(token) > 12 else ("Configured" if token else "Not set")

    safe_settings = {
        **settings,
        "phone_number_id": whatsapp_service.phone_number_id,
        "waba_id": whatsapp_service.waba_id,
        "api_version": whatsapp_service.api_version,
        "verify_token": whatsapp_service.verify_token,
        "has_access_token": bool(token),
        "masked_access_token": masked_token,
        "has_app_secret": bool(whatsapp_service.app_secret),
    }
    return jsonify({"success": True, "settings": safe_settings})


@whatsapp_bp.route("/api/whatsapp/settings", methods=["POST"])
def update_settings():
    """Updates WhatsApp & AI settings."""
    data = request.get_json(silent=True) or {}
    updated = whatsapp_store.update_settings(data)
    # Check if credentials updated
    if "phone_number_id" in data or "access_token" in data or "app_secret" in data:
        whatsapp_service.reload_config()
    return jsonify({"success": True, "settings": updated})


# -----------------------------------------------------------------------------
# SPA Page Route
# -----------------------------------------------------------------------------

@whatsapp_bp.route("/whatsapp")
@whatsapp_bp.route("/whatsapp-support")
def whatsapp_page():
    """Renders JobScout SPA shell with the WhatsApp AI Center active."""
    return render_template("app_shell.html", initial_section="whatsapp")
