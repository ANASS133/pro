"""
JobScout Meta WhatsApp Cloud API Service & Webhook Processor
=============================================================
Production-grade integration with the official Meta WhatsApp Business Platform Cloud API (Graph API v21.0).
Provides:
- Webhook challenge verification (GET)
- Webhook HMAC-SHA256 signature validation (POST)
- Async message queue processing for sub-second webhook responses
- Message deduplication by provider wamid
- Outbound text and template message delivery with exponential backoff
- Delivery status tracking (sent, delivered, read, failed)
- Media download metadata resolution
- 24-hour customer service window tracking
"""

import hashlib
import hmac
import json
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from services.whatsapp_store import whatsapp_store

logger = logging.getLogger(__name__)


class WhatsAppAPIError(Exception):
    """Raised when an interaction with Meta Graph API fails."""
    def __init__(self, message: str, status_code: Optional[int] = None, error_data: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_data = error_data or {}


class WhatsAppService:
    """Orchestrates Meta WhatsApp Cloud API communication and incoming webhook ingestion."""

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        store = kwargs.get("store") or (args[0] if args else None)
        if store is not None:
            inst = super(WhatsAppService, cls).__new__(cls)
            inst._initialized = False
            return inst

        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(WhatsAppService, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, store=None):
        if getattr(self, "_initialized", False):
            if store:
                self.store = store
            return

        self.store = store or whatsapp_store
        self._load_config()
        self._init_http_client()
        self._init_queue_worker()
        self._realtime_subscribers: List[queue.Queue] = []
        self._subscriber_lock = threading.Lock()
        self._ai_turn_handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None
        self._initialized = True

    def _load_config(self):
        """Loads configuration from environment and store settings."""
        self.phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        self.waba_id = os.environ.get("WHATSAPP_WABA_ID", "").strip()
        self.access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
        self.verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "jobscout_wa_verify_secure_token").strip()
        self.app_secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
        self.api_version = os.environ.get("WHATSAPP_API_VERSION", "v21.0").strip()
        self.graph_base_url = f"https://graph.facebook.com/{self.api_version}"

    def reload_config(self):
        """Hot-reloads configuration (e.g. after admin updates settings)."""
        self._load_config()

    def register_ai_turn_handler(self, handler: Callable[[Dict[str, Any], Dict[str, Any]], None]):
        """Registers the AI engine callback to handle autonomous AI turns."""
        self._ai_turn_handler = handler

    def _init_http_client(self):
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def _init_queue_worker(self):
        """Starts background worker thread for asynchronous message processing."""
        self._work_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._worker_thread = threading.Thread(
            target=self._queue_worker_loop,
            daemon=True,
            name="WhatsAppWebhookWorker",
        )
        self._worker_thread.start()

    # -------------------------------------------------------------------------
    # Webhook Verification & HMAC-SHA256 Security
    # -------------------------------------------------------------------------

    def verify_webhook_token(self, mode: Optional[str], token: Optional[str], challenge: Optional[str]) -> Optional[str]:
        """Validates Meta verification handshake (GET /api/whatsapp/webhook)."""
        if mode == "subscribe" and token and hmac.compare_digest(token, self.verify_token):
            logger.info("WhatsApp webhook verified successfully.")
            return challenge
        logger.warning("WhatsApp webhook verification failed: Invalid verify token.")
        return None

    def validate_signature(self, payload_bytes: bytes, signature_header: Optional[str]) -> bool:
        """
        Validates the X-Hub-Signature-256 header using the application secret.
        If app secret is not configured in local development, logs warning and allows request.
        """
        if not self.app_secret:
            logger.debug("WHATSAPP_APP_SECRET not configured; skipping HMAC verification.")
            return True

        if not signature_header or not signature_header.startswith("sha256="):
            logger.warning("Missing or malformed X-Hub-Signature-256 header.")
            return False

        received_sig = signature_header.split("sha256=")[1].strip()
        expected_sig = hmac.new(
            self.app_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(received_sig, expected_sig)
        if not is_valid:
            logger.warning("Invalid WhatsApp webhook signature.")
        return is_valid

    # -------------------------------------------------------------------------
    # Webhook Event Ingestion & Asynchronous Dispatch
    # -------------------------------------------------------------------------

    def enqueue_webhook_event(self, raw_payload: Dict[str, Any]) -> bool:
        """Enqueues incoming webhook payload for immediate non-blocking acknowledgment."""
        try:
            self._work_queue.put_nowait(raw_payload)
            return True
        except queue.Full:
            logger.error("WhatsApp webhook work queue is full! Dropping event.")
            return False

    def _queue_worker_loop(self):
        """Background worker consuming webhook events."""
        while True:
            try:
                payload = self._work_queue.get()
                if payload is None:
                    break
                self._process_webhook_payload(payload)
                self._work_queue.task_done()
            except Exception as exc:
                logger.error("Unhandled error processing WhatsApp webhook event: %s", exc, exc_info=True)

    def _process_webhook_payload(self, payload: Dict[str, Any]):
        """Parses Meta payload structure (messages and statuses)."""
        entries = payload.get("entry") or []
        for entry in entries:
            changes = entry.get("changes") or []
            for change in changes:
                value = change.get("value") or {}
                # 1. Process delivery / read statuses
                statuses = value.get("statuses") or []
                for st in statuses:
                    self._handle_status_update(st)

                # 2. Process incoming messages
                messages = value.get("messages") or []
                contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts") or []}
                for msg in messages:
                    self._handle_incoming_message(msg, contacts)

    def _handle_status_update(self, status_payload: Dict[str, Any]):
        """Updates delivery status of an outbound message."""
        provider_id = status_payload.get("id")
        status_name = status_payload.get("status")  # sent, delivered, read, failed
        if not provider_id or not status_name:
            return

        failure_reason = ""
        if status_name == "failed":
            errors = status_payload.get("errors") or []
            if errors:
                err = errors[0]
                failure_reason = f"[{err.get('code')}] {err.get('title', '')}: {err.get('message', '')}"
            else:
                failure_reason = "Unknown Meta delivery failure"

        updated = whatsapp_store.update_message_delivery_status(provider_id, status_name, failure_reason)
        if updated:
            self.emit_realtime_event({
                "type": "status_update",
                "provider_message_id": provider_id,
                "status": status_name,
                "failure_reason": failure_reason,
                "timestamp": status_payload.get("timestamp"),
            })

    def _handle_incoming_message(self, msg_payload: Dict[str, Any], contacts_map: Dict[str, Optional[str]]):
        """Processes an incoming message from a customer."""
        provider_msg_id = msg_payload.get("id")
        from_wa_id = str(msg_payload.get("from") or "").strip()
        msg_type = msg_payload.get("type", "text")

        if not from_wa_id or not provider_msg_id:
            return

        display_name = contacts_map.get(from_wa_id) or f"+{from_wa_id}"
        conversation = whatsapp_store.get_or_create_conversation(from_wa_id, display_name=display_name)
        conv_id = conversation["id"]

        # Automatically synchronize client identity if unlinked
        if not conversation.get("client_id"):
            try:
                from services.client_manager import client_manager
                matched = client_manager.find_client_by_phone(from_wa_id)
                if matched:
                    conversation = whatsapp_store.update_conversation(
                        conv_id,
                        {"client_id": matched["id"], "display_name": matched["name"]}
                    )
                    client_manager.sync_verified_whatsapp(matched["id"], from_wa_id)
                    logger.info("Automatically linked incoming WhatsApp from %s to client %s", from_wa_id, matched["id"])
            except Exception as auto_link_err:
                logger.warning("Auto-linking client failed for WA ID %s: %s", from_wa_id, auto_link_err)


        # Parse message content & media
        content, media_url, media_meta = self._extract_message_content(msg_payload, msg_type)

        # Store incoming message (idempotent deduplication)
        message = whatsapp_store.add_message(
            conversation_id=conv_id,
            direction="inbound",
            sender_type="client",
            content=content,
            provider_message_id=provider_msg_id,
            sender_name=display_name,
            media_type=msg_type,
            media_url=media_url,
            media_meta=media_meta,
            delivery_status="delivered",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Emit real-time event for connected agent dashboards
        self.emit_realtime_event({
            "type": "new_message",
            "conversation_id": conv_id,
            "message": message,
            "conversation": whatsapp_store.get_conversation(conv_id),
        })

        # Check conversation state for automated AI routing
        refreshed_conv = whatsapp_store.get_conversation(conv_id) or conversation
        current_mode = refreshed_conv.get("mode", "AI_ACTIVE")

        # Auto-reopen closed conversation if new message arrives
        if current_mode == "CLOSED":
            whatsapp_store.update_conversation(conv_id, {"mode": "AI_ACTIVE"})
            current_mode = "AI_ACTIVE"
            refreshed_conv["mode"] = "AI_ACTIVE"

        # Check global emergency pause
        settings = whatsapp_store.get_all_settings()
        if settings.get("emergency_ai_pause") is True or settings.get("ai_enabled") is False:
            logger.info("Global AI pause active. Skipping autonomous reply for conv %s.", conv_id)
            return

        # If conversation is AI_ACTIVE, trigger AI response generation
        if current_mode == "AI_ACTIVE" and self._ai_turn_handler:
            self._ai_turn_handler(refreshed_conv, message)

    def _extract_message_content(
        self,
        msg: Dict[str, Any],
        msg_type: str
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Extracts readable content and attachment metadata based on Meta message type."""
        content = ""
        media_url = ""
        meta: Dict[str, Any] = {}

        if msg_type == "text":
            content = msg.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            itype = interactive.get("type")
            if itype == "button_reply":
                content = interactive.get("button_reply", {}).get("title", "")
                meta["button_id"] = interactive.get("button_reply", {}).get("id")
            elif itype == "list_reply":
                content = interactive.get("list_reply", {}).get("title", "")
                meta["list_id"] = interactive.get("list_reply", {}).get("id")
        elif msg_type in ("image", "document", "audio", "video", "sticker"):
            media_obj = msg.get(msg_type, {})
            media_id = media_obj.get("id", "")
            mime = media_obj.get("mime_type", "")
            caption = media_obj.get("caption", "").strip()
            filename = media_obj.get("filename", "")
            content = caption or f"[{msg_type.upper()}: {filename or media_id}]"
            media_url = self._resolve_media_url(media_id) if media_id else ""
            meta = {
                "media_id": media_id,
                "mime_type": mime,
                "filename": filename,
                "file_size": media_obj.get("file_size"),
            }
        elif msg_type == "location":
            loc = msg.get("location", {})
            content = f"[Standort: Lat {loc.get('latitude')}, Long {loc.get('longitude')}]"
            meta = loc
        else:
            content = f"[{msg_type.upper()} Nachricht empfangen]"

        return content, media_url, meta

    def _resolve_media_url(self, media_id: str) -> str:
        """Retrieves temporary download URL from Meta Graph API for attachments."""
        if not self.access_token:
            return ""
        try:
            url = f"{self.graph_base_url}/{media_id}"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            res = self.session.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return data.get("url", "")
        except Exception as exc:
            logger.warning("Failed retrieving media URL for %s: %s", media_id, exc)
        return ""

    # -------------------------------------------------------------------------
    # Outbound Message Delivery (Text, Templates, Status Checks)
    # -------------------------------------------------------------------------

    def send_text_message(
        self,
        to_wa_id: Optional[str] = None,
        text: str = "",
        preview_url: bool = False,
        conversation_id: Optional[str] = None,
        to_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sends an outbound text message via Meta WhatsApp Cloud API.
        Enforces 24-hour service window check and error handling.
        """
        target = to_wa_id or to_phone or ""
        clean_to = str(target).strip().replace("+", "").replace(" ", "").replace("-", "")
        clean_text = str(text or "").strip()

        if not clean_to:
            raise WhatsAppAPIError("Recipient WhatsApp ID (to_wa_id) cannot be empty.")
        if not clean_text:
            raise WhatsAppAPIError("Message text cannot be empty.")

        # If Cloud API credentials are not set, provide simulated delivery for testing/development
        if not self.phone_number_id or not self.access_token:
            simulated_id = f"sim_wamid_{hashlib.md5(f'{clean_to}{clean_text}{time.time()}'.encode()).hexdigest()[:16]}"
            logger.info("Simulated WhatsApp send to %s (API credentials not configured): '%s'", clean_to, clean_text[:40])
            return {
                "success": True,
                "provider_message_id": simulated_id,
                "simulated": True,
                "status": "sent",
            }

        endpoint = f"{self.graph_base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": clean_text,
            },
        }

        # Send with retries on transient network errors
        attempts = 0
        max_attempts = 3
        last_error = None

        while attempts < max_attempts:
            attempts += 1
            try:
                res = self.session.post(endpoint, headers=headers, json=payload, timeout=15)
                res_json = res.json() if res.content else {}

                if res.status_code in (200, 201):
                    messages_res = res_json.get("messages") or []
                    provider_msg_id = messages_res[0].get("id") if messages_res else f"wamid_out_{int(time.time())}"
                    return {
                        "success": True,
                        "provider_message_id": provider_msg_id,
                        "raw_response": res_json,
                        "status": "sent",
                    }

                # Handle Meta API Errors
                err_data = res_json.get("error") or {}
                err_code = err_data.get("code")
                err_msg = err_data.get("message", res.text)

                if err_code == 131047:
                    logger.warning("WhatsApp 24-hour service window expired for recipient %s (Code 131047).", clean_to)
                    if conversation_id:
                        self.store.add_message(
                            conversation_id=conversation_id,
                            direction="outbound",
                            sender_type="ai",
                            content=clean_text,
                            delivery_status="failed",
                            failure_reason="24-hour service window expired (Meta code 131047)"
                        )
                    raise WhatsAppAPIError(f"Meta WhatsApp API error {res.status_code}: 131047 24-hour service window expired", res.status_code, err_data)

                logger.error("Meta API error (%s): %s", res.status_code, err_msg)
                last_error = WhatsAppAPIError(f"Meta WhatsApp API error {res.status_code}: {err_msg}", res.status_code, err_data)

                if conversation_id:
                    self.store.add_message(
                        conversation_id=conversation_id,
                        direction="outbound",
                        sender_type="ai",
                        content=clean_text,
                        delivery_status="failed",
                        failure_reason=str(last_error)
                    )

                # Only retry on 5xx or rate limits
                if res.status_code not in (429, 500, 502, 503, 504):
                    break

            except requests.RequestException as exc:
                last_error = WhatsAppAPIError(f"Network error sending WhatsApp message: {exc}")
                time.sleep(0.5 * (2 ** attempts))

        if last_error:
            raise last_error
        raise WhatsAppAPIError("Failed sending WhatsApp message after retries.")

    def send_template_message(
        self,
        to_wa_id: str,
        template_name: str,
        language_code: str = "de",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Sends an approved WhatsApp Business template message (required outside the 24h window).
        """
        clean_to = str(to_wa_id or "").strip().replace("+", "").replace(" ", "").replace("-", "")
        if not self.phone_number_id or not self.access_token:
            simulated_id = f"sim_template_{hashlib.md5(f'{clean_to}{template_name}{time.time()}'.encode()).hexdigest()[:16]}"
            logger.info("Simulated WhatsApp template send to %s: '%s'", clean_to, template_name)
            return {"success": True, "provider_message_id": simulated_id, "simulated": True}

        endpoint = f"{self.graph_base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }

        try:
            res = self.session.post(endpoint, headers=headers, json=payload, timeout=15)
            if res.status_code in (200, 201):
                data = res.json()
                provider_id = (data.get("messages") or [{}])[0].get("id")
                return {"success": True, "provider_message_id": provider_id}
            err = res.json().get("error", {})
            raise WhatsAppAPIError(f"Template send error: {err.get('message', res.text)}", res.status_code, err)
        except requests.RequestException as exc:
            raise WhatsAppAPIError(f"Network error sending template: {exc}")

    def send_human_reply(
        self,
        conversation_id: str,
        text: str,
        agent_name: str = "Administrator"
    ) -> Dict[str, Any]:
        """
        Sends an outbound message written by a human agent.
        Atomically ensures the conversation transitions to HUMAN_ACTIVE.
        """
        conv = self.store.get_conversation(conversation_id)
        if not conv:
            raise WhatsAppAPIError(f"Conversation {conversation_id} not found.")

        # If not yet in HUMAN_ACTIVE, take over atomically
        if conv.get("mode") != "HUMAN_ACTIVE":
            self.store.atomic_takeover(conversation_id, agent_name=agent_name)

        send_res = self.send_text_message(
            to_wa_id=conv.get("wa_id"),
            text=text,
            conversation_id=conversation_id
        )
        provider_wamid = send_res.get("provider_message_id", "wamid.admin")

        msg = self.store.add_message(
            conversation_id=conversation_id,
            direction="outbound",
            sender_type="human",
            sender_name=agent_name,
            content=text,
            provider_message_id=provider_wamid,
            delivery_status="sent",
        )

        self.emit_realtime_event({
            "type": "new_message",
            "conversation_id": conversation_id,
            "message": msg,
        })
        return msg

    # -------------------------------------------------------------------------
    # Real-Time SSE Subscription Engine
    # -------------------------------------------------------------------------

    def subscribe_realtime_events(self) -> queue.Queue:
        """Subscribes an SSE connection to live events."""
        sub = queue.Queue(maxsize=200)
        with self._subscriber_lock:
            self._realtime_subscribers.append(sub)
        return sub

    def unsubscribe_realtime_events(self, sub: queue.Queue):
        """Unsubscribes an SSE connection."""
        with self._subscriber_lock:
            if sub in self._realtime_subscribers:
                self._realtime_subscribers.remove(sub)

    def emit_realtime_event(self, event_data: Dict[str, Any]):
        """Dispatches an event payload to all active SSE listeners."""
        with self._subscriber_lock:
            dead_subs = []
            for sub in self._realtime_subscribers:
                try:
                    sub.put_nowait(event_data)
                except queue.Full:
                    dead_subs.append(sub)
            for d in dead_subs:
                if d in self._realtime_subscribers:
                    self._realtime_subscribers.remove(d)


whatsapp_service = WhatsAppService()
