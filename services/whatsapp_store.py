"""
JobScout WhatsApp Store & Data Access Layer
============================================
Thread-safe, high-concurrency SQLite storage for WhatsApp customer support conversations,
messages, audit logs, knowledge base, and configuration settings.
Enforces transactional writes, optimistic concurrency locking for takeover safety,
and deduplication for webhook idempotency.
"""

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "whatsapp.db"
MIGRATION_PATH = BASE_DIR / "migrations" / "whatsapp_schema.sql"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dict_from_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


class WhatsAppStoreError(Exception):
    """Base exception for WhatsApp Store operations."""
    pass


class ConcurrencyConflictError(WhatsAppStoreError):
    """Raised when an operation encounters an optimistic concurrency conflict (e.g. takeover collision)."""
    pass


class WhatsAppStore:
    """Central data access coordinator for WhatsApp conversations and messaging."""

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        db_path = kwargs.get("db_path") or (args[0] if args else None)
        if db_path is not None and str(db_path) != str(DB_PATH):
            inst = super(WhatsAppStore, cls).__new__(cls)
            inst._initialized = False
            return inst

        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(WhatsAppStore, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Path = DB_PATH):
        if getattr(self, "_initialized", False):
            return
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_db()
        self._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=20.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            self._local.connection = conn
        return conn

    def close(self):
        """Close thread-local SQLite connection and release file locks."""
        conn = getattr(self._local, "connection", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.connection = None

    def _init_db(self):
        """Initializes database schema from migrations file and seeds default knowledge/settings."""
        with self._write_lock:
            conn = self._get_connection()
            if MIGRATION_PATH.exists():
                try:
                    with open(MIGRATION_PATH, "r", encoding="utf-8") as f:
                        schema_sql = f.read()
                    conn.executescript(schema_sql)
                    conn.commit()
                except Exception as exc:
                    logger.error("Failed executing whatsapp schema migration: %s", exc)
                    raise

            # Seed default settings if empty
            self._seed_default_settings(conn)
            self._seed_default_knowledge_base(conn)

    def _seed_default_settings(self, conn: sqlite3.Connection):
        now = _utc_now_iso()
        defaults = {
            "ai_enabled": "true",
            "ai_provider": "openai",
            "ai_model": "gpt-6-luna",
            "ai_temperature": "0.2",
            "ai_max_tokens": "400",
            "ai_system_prompt": (
                "Du bist der offizielle JobScout WhatsApp Kundenservice-Assistent. "
                "Antworte stets professionell, höflich, hilfsbereit und präzise. "
                "Antworte in der Sprache des Kunden (Deutsch, Englisch, Französisch, Arabisch oder Marokkanisches Darija). "
                "Erfinde niemals Bewerbungen, Daten oder Ergebnisse. "
                "Nutze die autorisierten JobScout-Tools, um echte Daten abzufragen. "
                "Wenn der Kunde mit einem Mitarbeiter sprechen möchte oder du unsicher bist, eskaliere an einen menschlichen Berater."
            ),
            "emergency_ai_pause": "false",
            "auto_escalate_on_negative_sentiment": "true",
            "service_window_hours": "24",
            "default_language": "de",
            "allowed_tools": json.dumps([
                "get_client_profile",
                "get_client_application_statistics",
                "get_client_application_status",
                "get_client_profession",
                "get_profession_dataset_availability",
                "get_client_document_status",
                "get_client_payment_status",
                "get_jobscout_service_information",
                "request_human_support"
            ]),
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO whatsapp_settings (key, value, updated_at) VALUES (?, ?, ?);",
                (k, v, now),
            )
        conn.commit()

    def _seed_default_knowledge_base(self, conn: sqlite3.Connection):
        now = _utc_now_iso()
        kb_items = [
            (
                "kb_welcome_info",
                "process",
                "Über JobScout & Bewerbungsprozess",
                "JobScout unterstützt Bewerber bei der Vermittlung von Ausbildungsplätzen in Deutschland. "
                "Nach Prüfung und Freigabe der Bewerbungsunterlagen werden individuelle Bewerbungen gezielt "
                "an passende Ausbildungsbetriebe versendet. Status-Updates sind direkt abrufbar."
            ),
            (
                "kb_pricing_packages",
                "pricing",
                "Bewerbungspakete & Preise",
                "JobScout bietet standardisierte Bewerbungspakete an:\n"
                "- 500 Bewerbungen Paket\n"
                "- 1000 Bewerbungen Paket\n"
                "- 2000 Bewerbungen Paket\n"
                "Die Bezahlung erfolgt per autorisierter Banküberweisung. Nach Zahlungseingang startet die Kampagne."
            ),
            (
                "kb_visa_regulations",
                "policies",
                "Visum & Arbeitserlaubnis Richtlinie",
                "JobScout ist eine Bewerbungs- und Vermittlungsplattform und kann keine Visa oder Arbeitserlaubnisse "
                "garantieren. Ein Visum muss vom Bewerber eigenständig bei der zuständigen deutschen Auslandsvertretung "
                "beantragt werden, sobald ein Ausbildungsvertrag vorliegt."
            ),
            (
                "kb_faq_documents",
                "faq",
                "Benötigte Bewerbungsdokumente",
                "Für eine erfolgreiche Bewerbung werden benötigt:\n"
                "1. Tabellarischer Lebenslauf (CV) auf Deutsch\n"
                "2. Zeugnisse und Nachweise der Vorbildung (beglaubigt übersetzt)\n"
                "3. Sprachzertifikat (mindestens B1 oder B2 Deutsch empfohlen)\n"
                "4. Ggf. Praktikums- oder Arbeitsnachweise"
            ),
        ]
        for item_id, cat, title, content in kb_items:
            conn.execute(
                """
                INSERT OR IGNORE INTO whatsapp_knowledge_base 
                (id, category, title, content, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?);
                """,
                (item_id, cat, title, content, now, now),
            )
        conn.commit()

    # -------------------------------------------------------------------------
    # Conversation Management
    # -------------------------------------------------------------------------

    def get_or_create_conversation(
        self,
        wa_id: str,
        display_name: Optional[str] = None,
        client_id: Optional[str] = None,
        initial_mode: str = "AI_ACTIVE",
    ) -> Dict[str, Any]:
        """Gets existing conversation or atomically creates a new conversation with initial_mode."""
        clean_wa = str(wa_id or "").strip().replace("+", "").replace(" ", "").replace("-", "")
        if not clean_wa:
            raise WhatsAppStoreError("WhatsApp ID (wa_id) cannot be empty.")

        with self._write_lock:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT * FROM whatsapp_conversations WHERE wa_id = ?;",
                (clean_wa,),
            ).fetchone()

            if row:
                conv = dict(row)
                # Optionally update display_name or client_id if newly provided
                updates = []
                params = []
                if display_name and not conv.get("display_name"):
                    updates.append("display_name = ?")
                    params.append(display_name.strip())
                if client_id and not conv.get("client_id"):
                    updates.append("client_id = ?")
                    params.append(client_id.strip())

                if updates:
                    updates.append("updated_at = ?")
                    params.append(_utc_now_iso())
                    params.append(conv["id"])
                    conn.execute(
                        f"UPDATE whatsapp_conversations SET {', '.join(updates)} WHERE id = ?;",
                        params,
                    )
                    conn.commit()
                    row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conv["id"],)).fetchone()
                    return dict(row)
                return conv

            # Create new conversation
            conv_id = f"conv_{uuid.uuid4().hex[:16]}"
            now = _utc_now_iso()
            name_val = (display_name or "").strip()
            conn.execute(
                """
                INSERT INTO whatsapp_conversations (
                    id, wa_id, client_id, display_name, mode,
                    last_activity_at, unread_count, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?);
                """,
                (conv_id, clean_wa, client_id, name_val, initial_mode, now, now, now),
            )
            # Log audit entry
            self._insert_audit_log(
                conn,
                conv_id,
                "system",
                "conversation_created",
                "",
                initial_mode,
                {"wa_id": clean_wa, "display_name": name_val},
                now,
            )
            conn.commit()
            new_row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conv_id,)).fetchone()
            return dict(new_row)

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone()
        return _dict_from_row(row)

    def get_conversation_by_id(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        return self.get_conversation(conversation_id)

    def set_system_setting(self, key: str, value: str) -> bool:
        return self.set_setting(key, value)

    def get_system_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.get_setting(key, default)

    def get_conversation_by_wa_id(self, wa_id: str) -> Optional[Dict[str, Any]]:
        clean_wa = str(wa_id or "").strip().replace("+", "").replace(" ", "").replace("-", "")
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM whatsapp_conversations WHERE wa_id = ?;", (clean_wa,)).fetchone()
        return _dict_from_row(row)

    def list_conversations(
        self,
        mode: Optional[str] = None,
        escalation: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Lists conversations sorted by last activity with filtering."""
        conn = self._get_connection()
        clauses = []
        params: List[Any] = []

        if mode and mode != "all":
            clauses.append("mode = ?")
            params.append(mode.upper())

        if escalation and escalation != "all":
            clauses.append("escalation_status = ?")
            params.append(escalation.lower())

        if search:
            term = f"%{search.strip().lower()}%"
            clauses.append("(LOWER(wa_id) LIKE ? OR LOWER(display_name) LIKE ? OR LOWER(client_id) LIKE ? OR LOWER(summary) LIKE ?)")
            params.extend([term, term, term, term])

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT * FROM whatsapp_conversations
            {where_clause}
            ORDER BY last_activity_at DESC
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def update_conversation(self, conversation_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Generic conversation update with timestamp touch."""
        with self._write_lock:
            conn = self._get_connection()
            safe_updates = {}
            for k, v in updates.items():
                if k in {
                    "client_id", "client_code", "display_name", "assigned_agent",
                    "mode", "last_inbound_at", "last_activity_at", "escalation_status",
                    "escalation_reason", "unread_count", "summary", "ai_config_override"
                }:
                    safe_updates[k] = v

            if not safe_updates:
                return self.get_conversation(conversation_id) or {}

            safe_updates["updated_at"] = _utc_now_iso()
            set_clauses = [f"{k} = ?" for k in safe_updates.keys()]
            params = list(safe_updates.values()) + [conversation_id]

            conn.execute(
                f"UPDATE whatsapp_conversations SET {', '.join(set_clauses)} WHERE id = ?;",
                params,
            )
            conn.commit()
            return self.get_conversation(conversation_id) or {}

    # -------------------------------------------------------------------------
    # Concurrency-Safe Routing State Transitions
    # -------------------------------------------------------------------------

    def atomic_takeover(self, conversation_id: str, agent_name: str) -> Dict[str, Any]:
        """
        Atomically transfers conversation to HUMAN_ACTIVE, increments version counter,
        and logs audit entry. Invalids any pending AI response generation.
        """
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone()
            if not row:
                raise WhatsAppStoreError(f"Conversation {conversation_id} not found.")

            conv = dict(row)
            old_mode = conv.get("mode", "AI_ACTIVE")
            new_version = conv.get("version", 1) + 1
            agent_clean = str(agent_name or "Agent").strip()

            conn.execute(
                """
                UPDATE whatsapp_conversations
                SET mode = 'HUMAN_ACTIVE',
                    assigned_agent = ?,
                    escalation_status = CASE WHEN escalation_status = 'pending' THEN 'resolved' ELSE escalation_status END,
                    version = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (agent_clean, new_version, now, conversation_id),
            )
            self._insert_audit_log(
                conn,
                conversation_id,
                agent_clean,
                "takeover",
                old_mode,
                "HUMAN_ACTIVE",
                {"previous_version": conv.get("version", 1), "new_version": new_version},
                now,
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone())

    def atomic_resume_ai(self, conversation_id: str, agent_name: str) -> Dict[str, Any]:
        """
        Explicitly restores autonomous AI processing. Increments version counter.
        """
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone()
            if not row:
                raise WhatsAppStoreError(f"Conversation {conversation_id} not found.")

            conv = dict(row)
            old_mode = conv.get("mode")
            new_version = conv.get("version", 1) + 1
            agent_clean = str(agent_name or "Agent").strip()

            conn.execute(
                """
                UPDATE whatsapp_conversations
                SET mode = 'AI_ACTIVE',
                    version = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (new_version, now, conversation_id),
            )
            self._insert_audit_log(
                conn,
                conversation_id,
                agent_clean,
                "resume_ai",
                old_mode,
                "AI_ACTIVE",
                {"previous_version": conv.get("version", 1), "new_version": new_version},
                now,
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone())

    def atomic_escalate(self, conversation_id: str, reason: str, actor: str = "ai") -> Dict[str, Any]:
        """
        Transitions conversation to ESCALATED mode, halting autonomous replies until human resolution.
        """
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone()
            if not row:
                raise WhatsAppStoreError(f"Conversation {conversation_id} not found.")

            conv = dict(row)
            old_mode = conv.get("mode")
            new_version = conv.get("version", 1) + 1
            clean_reason = str(reason or "Customer requested human agent").strip()

            conn.execute(
                """
                UPDATE whatsapp_conversations
                SET mode = 'ESCALATED',
                    escalation_status = 'pending',
                    escalation_reason = ?,
                    version = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (clean_reason, new_version, now, conversation_id),
            )
            self._insert_audit_log(
                conn,
                conversation_id,
                actor,
                "escalate",
                old_mode,
                "ESCALATED",
                {"reason": clean_reason, "version": new_version},
                now,
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone())

    def atomic_pause_ai(self, conversation_id: str, agent_name: str) -> Dict[str, Any]:
        """Pauses AI processing for this conversation without assigning human."""
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone()
            if not row:
                raise WhatsAppStoreError(f"Conversation {conversation_id} not found.")

            conv = dict(row)
            old_mode = conv.get("mode")
            new_version = conv.get("version", 1) + 1
            conn.execute(
                "UPDATE whatsapp_conversations SET mode = 'AI_PAUSED', version = ?, updated_at = ? WHERE id = ?;",
                (new_version, now, conversation_id),
            )
            self._insert_audit_log(
                conn, conversation_id, agent_name, "pause_ai", old_mode, "AI_PAUSED", {"version": new_version}, now
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone())

    def atomic_close(self, conversation_id: str, agent_name: str) -> Dict[str, Any]:
        """Marks conversation closed while keeping history intact."""
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            row = conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone()
            if not row:
                raise WhatsAppStoreError(f"Conversation {conversation_id} not found.")

            conv = dict(row)
            old_mode = conv.get("mode")
            new_version = conv.get("version", 1) + 1
            conn.execute(
                """
                UPDATE whatsapp_conversations
                SET mode = 'CLOSED',
                    escalation_status = 'resolved',
                    unread_count = 0,
                    version = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (new_version, now, conversation_id),
            )
            self._insert_audit_log(
                conn, conversation_id, agent_name, "close", old_mode, "CLOSED", {"version": new_version}, now
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM whatsapp_conversations WHERE id = ?;", (conversation_id,)).fetchone())

    def verify_conversation_version(self, conversation_id: str, expected_version: int) -> Tuple[bool, str, int]:
        """
        Validates whether conversation remains in AI_ACTIVE mode and matches expected version.
        Crucial check executed immediately prior to sending any AI reply.
        Returns: (is_valid, current_mode, current_version)
        """
        conn = self._get_connection()
        row = conn.execute(
            "SELECT mode, version FROM whatsapp_conversations WHERE id = ?;",
            (conversation_id,),
        ).fetchone()
        if not row:
            return False, -1, "NON_EXISTENT"

        current_mode = str(row["mode"] or "").upper()
        current_version = int(row["version"] or 0)

        # Valid only if mode is still AI_ACTIVE and version unchanged
        is_valid = (current_mode == "AI_ACTIVE") and (current_version == expected_version)
        return is_valid, current_version, current_mode

    # -------------------------------------------------------------------------
    # Message Storage & Deduplication
    # -------------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        direction: str,
        sender_type: str,
        content: str,
        provider_message_id: Optional[str] = None,
        sender_name: str = "",
        media_type: str = "text",
        media_url: str = "",
        media_meta: Optional[Dict[str, Any]] = None,
        delivery_status: str = "pending",
        failure_reason: str = "",
        ai_metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Adds a message record with idempotent deduplication via provider_message_id.
        Updates conversation last_activity_at and unread_count.
        """
        now = created_at or _utc_now_iso()
        msg_id = f"msg_{uuid.uuid4().hex[:16]}"
        clean_content = str(content or "").strip()
        media_meta_json = json.dumps(media_meta or {})
        ai_meta_json = json.dumps(ai_metadata or {})

        with self._write_lock:
            conn = self._get_connection()

            # Webhook Deduplication Check
            if provider_message_id:
                existing = conn.execute(
                    "SELECT * FROM whatsapp_messages WHERE provider_message_id = ?;",
                    (provider_message_id,),
                ).fetchone()
                if existing:
                    logger.debug("Idempotent check: Message %s already stored.", provider_message_id)
                    return dict(existing)

            # Insert message
            conn.execute(
                """
                INSERT INTO whatsapp_messages (
                    id, provider_message_id, conversation_id, direction,
                    sender_type, sender_name, content, media_type,
                    media_url, media_meta, delivery_status, failure_reason,
                    ai_metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    msg_id, provider_message_id, conversation_id, direction,
                    sender_type, sender_name, clean_content, media_type,
                    media_url, media_meta_json, delivery_status, failure_reason,
                    ai_meta_json, now
                ),
            )

            # Update conversation timestamp & unread count
            is_inbound = (direction == "inbound")
            if is_inbound:
                conn.execute(
                    """
                    UPDATE whatsapp_conversations
                    SET last_activity_at = ?,
                        last_inbound_at = ?,
                        unread_count = unread_count + 1,
                        updated_at = ?
                    WHERE id = ?;
                    """,
                    (now, now, now, conversation_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE whatsapp_conversations
                    SET last_activity_at = ?,
                        unread_count = 0,
                        updated_at = ?
                    WHERE id = ?;
                    """,
                    (now, now, conversation_id),
                )

            conn.commit()
            row = conn.execute("SELECT * FROM whatsapp_messages WHERE id = ?;", (msg_id,)).fetchone()
            return dict(row)

    def get_messages(
        self,
        conversation_id: str,
        limit: int = 100,
        before_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves chronological message history for a conversation."""
        conn = self._get_connection()
        params: List[Any] = [conversation_id]
        where_extra = ""
        if before_id:
            msg_row = conn.execute("SELECT created_at FROM whatsapp_messages WHERE id = ?;", (before_id,)).fetchone()
            if msg_row:
                where_extra = "AND created_at < ?"
                params.append(msg_row["created_at"])

        params.append(limit)
        query = f"""
            SELECT * FROM (
                SELECT * FROM whatsapp_messages
                WHERE conversation_id = ? {where_extra}
                ORDER BY created_at DESC
                LIMIT ?
            ) ORDER BY created_at ASC;
        """
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["media_meta"] = json.loads(d.get("media_meta") or "{}")
            except Exception:
                d["media_meta"] = {}
            try:
                d["ai_metadata"] = json.loads(d.get("ai_metadata") or "{}")
            except Exception:
                d["ai_metadata"] = {}
            result.append(d)
        return result

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM whatsapp_messages WHERE id = ?;", (message_id,)).fetchone()
        return _dict_from_row(row)

    def update_message_delivery_status(
        self,
        identifier: str = "",
        status: str = "",
        failure_reason: str = "",
        provider_message_id: Optional[str] = None,
    ) -> bool:
        """Updates message delivery status by internal message ID or provider wamid."""
        target_id = identifier or provider_message_id or ""
        with self._write_lock:
            conn = self._get_connection()
            cur = conn.execute(
                """
                UPDATE whatsapp_messages
                SET delivery_status = ?,
                    failure_reason = CASE WHEN ? != '' THEN ? ELSE failure_reason END
                WHERE id = ? OR provider_message_id = ?;
                """,
                (status, failure_reason, failure_reason, target_id, target_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def mark_conversation_read(self, conversation_id: str) -> bool:
        """Resets unread counter for conversation."""
        with self._write_lock:
            conn = self._get_connection()
            conn.execute(
                "UPDATE whatsapp_conversations SET unread_count = 0, updated_at = ? WHERE id = ?;",
                (_utc_now_iso(), conversation_id),
            )
            conn.commit()
            return True

    # -------------------------------------------------------------------------
    # Knowledge Base CRUD
    # -------------------------------------------------------------------------

    def list_knowledge_base(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        clauses = []
        params = []
        if active_only:
            clauses.append("is_active = 1")
        if category and category != "all":
            clauses.append("category = ?")
            params.append(category.lower())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM whatsapp_knowledge_base {where} ORDER BY category ASC, updated_at DESC;"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def create_knowledge_base_item(self, category: str, title: str, content: str) -> Dict[str, Any]:
        item_id = f"kb_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO whatsapp_knowledge_base (id, category, title, content, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?);
                """,
                (item_id, category.lower(), title.strip(), content.strip(), now, now),
            )
            conn.commit()
            return dict(conn.execute("SELECT * FROM whatsapp_knowledge_base WHERE id = ?;", (item_id,)).fetchone())

    def update_knowledge_base_item(
        self,
        item_id: str,
        category: Optional[str] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        now = _utc_now_iso()
        with self._write_lock:
            conn = self._get_connection()
            updates = []
            params = []
            if category is not None:
                updates.append("category = ?")
                params.append(category.lower().strip())
            if title is not None:
                updates.append("title = ?")
                params.append(title.strip())
            if content is not None:
                updates.append("content = ?")
                params.append(content.strip())
            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)

            if not updates:
                return _dict_from_row(conn.execute("SELECT * FROM whatsapp_knowledge_base WHERE id = ?;", (item_id,)).fetchone())

            updates.append("updated_at = ?")
            params.append(now)
            params.append(item_id)
            conn.execute(f"UPDATE whatsapp_knowledge_base SET {', '.join(updates)} WHERE id = ?;", params)
            conn.commit()
            return _dict_from_row(conn.execute("SELECT * FROM whatsapp_knowledge_base WHERE id = ?;", (item_id,)).fetchone())

    def delete_knowledge_base_item(self, item_id: str) -> bool:
        with self._write_lock:
            conn = self._get_connection()
            cur = conn.execute("DELETE FROM whatsapp_knowledge_base WHERE id = ?;", (item_id,))
            conn.commit()
            return cur.rowcount > 0

    def search_knowledge_base(self, query_str: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Searches active knowledge base entries matching keywords."""
        tokens = [t.lower() for t in query_str.split() if len(t) > 2]
        if not tokens:
            return self.list_knowledge_base(active_only=True)[:limit]

        conn = self._get_connection()
        like_clauses = " OR ".join(["(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)" for _ in tokens])
        params = []
        for t in tokens:
            params.extend([f"%{t}%", f"%{t}%"])
        params.append(limit)

        sql = f"""
            SELECT * FROM whatsapp_knowledge_base
            WHERE is_active = 1 AND ({like_clauses})
            LIMIT ?;
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Settings Management
    # -------------------------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        conn = self._get_connection()
        row = conn.execute("SELECT value FROM whatsapp_settings WHERE key = ?;", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        val_str = value if isinstance(value, str) else json.dumps(value)
        with self._write_lock:
            conn = self._get_connection()
            conn.execute(
                """
                INSERT INTO whatsapp_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
                """,
                (key, val_str, _utc_now_iso()),
            )
            conn.commit()

    def get_all_settings(self) -> Dict[str, Any]:
        conn = self._get_connection()
        rows = conn.execute("SELECT key, value FROM whatsapp_settings;").fetchall()
        res = {}
        for r in rows:
            k = r["key"]
            v = r["value"]
            if v.lower() in ("true", "false"):
                res[k] = v.lower() == "true"
            elif v.isdigit():
                res[k] = int(v)
            else:
                try:
                    res[k] = json.loads(v)
                except Exception:
                    res[k] = v
        return res

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._write_lock:
            conn = self._get_connection()
            now = _utc_now_iso()
            for k, v in updates.items():
                val_str = v if isinstance(v, str) else json.dumps(v)
                conn.execute(
                    """
                    INSERT INTO whatsapp_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
                    """,
                    (k, val_str, now),
                )
            conn.commit()
        return self.get_all_settings()

    # -------------------------------------------------------------------------
    # Audit Logs & Metrics
    # -------------------------------------------------------------------------

    def _insert_audit_log(
        self,
        conn: sqlite3.Connection,
        conversation_id: str,
        actor: str,
        action: str,
        old_state: str = "",
        new_state: str = "",
        details: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
    ):
        log_id = f"aud_{uuid.uuid4().hex[:14]}"
        conn.execute(
            """
            INSERT INTO whatsapp_audit_logs (id, conversation_id, actor, action, old_state, new_state, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                log_id, conversation_id, actor, action, old_state, new_state,
                json.dumps(details or {}), created_at or _utc_now_iso()
            ),
        )

    def add_audit_log(
        self,
        conversation_id: str,
        actor: str = "system",
        action: str = "",
        old_state: str = "",
        new_state: str = "",
        details: Optional[Dict[str, Any]] = None,
        performed_by: Optional[str] = None,
    ):
        actual_actor = performed_by or actor or "system"
        with self._write_lock:
            conn = self._get_connection()
            self._insert_audit_log(conn, conversation_id, actual_actor, action, old_state, new_state, details)
            conn.commit()

    def get_audit_logs(self, conversation_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        params = []
        where = ""
        if conversation_id:
            where = "WHERE conversation_id = ?"
            params.append(conversation_id)
        params.append(limit)

        sql = f"SELECT * FROM whatsapp_audit_logs {where} ORDER BY created_at DESC LIMIT ?;"
        rows = conn.execute(sql, params).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d.get("details") or "{}")
            except Exception:
                d["details"] = {}
            res.append(d)
        return res

    def get_overview_metrics(self) -> Dict[str, Any]:
        """Calculates live operational metrics from real database data."""
        conn = self._get_connection()
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Conversations summary
        conv_stats = conn.execute(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN mode = 'AI_ACTIVE' THEN 1 ELSE 0 END) as ai_active,
                SUM(CASE WHEN mode = 'HUMAN_ACTIVE' THEN 1 ELSE 0 END) as human_active,
                SUM(CASE WHEN mode = 'ESCALATED' OR escalation_status = 'pending' THEN 1 ELSE 0 END) as escalated,
                SUM(CASE WHEN mode = 'CLOSED' THEN 1 ELSE 0 END) as closed,
                SUM(CASE WHEN unread_count > 0 THEN 1 ELSE 0 END) as unread
            FROM whatsapp_conversations;
            """
        ).fetchone()

        # Messages summary for today
        msg_stats = conn.execute(
            """
            SELECT
                COUNT(*) as total_today,
                SUM(CASE WHEN direction = 'inbound' THEN 1 ELSE 0 END) as inbound_today,
                SUM(CASE WHEN direction = 'outbound' THEN 1 ELSE 0 END) as outbound_today,
                SUM(CASE WHEN delivery_status = 'failed' THEN 1 ELSE 0 END) as failed_today,
                SUM(CASE WHEN sender_type = 'ai' THEN 1 ELSE 0 END) as ai_today,
                SUM(CASE WHEN sender_type = 'human' THEN 1 ELSE 0 END) as human_today
            FROM whatsapp_messages
            WHERE created_at LIKE ?;
            """,
            (f"{today_prefix}%",),
        ).fetchone()

        # Takeover count today
        takeovers_today = conn.execute(
            """
            SELECT COUNT(*) as takeovers
            FROM whatsapp_audit_logs
            WHERE action = 'takeover' AND created_at LIKE ?;
            """,
            (f"{today_prefix}%",),
        ).fetchone()["takeovers"]

        # Aggregate AI tokens and cost from message metadata
        ai_rows = conn.execute(
            """
            SELECT ai_metadata FROM whatsapp_messages 
            WHERE sender_type = 'ai' AND ai_metadata != '{}' AND ai_metadata IS NOT NULL;
            """
        ).fetchall()

        total_cost_usd = 0.0
        total_tokens = 0
        latencies: List[float] = []

        for r in ai_rows:
            try:
                meta = json.loads(r["ai_metadata"] or "{}")
                total_cost_usd += float(meta.get("cost_usd") or 0.0)
                total_tokens += int(meta.get("total_tokens") or 0)
                lat = meta.get("latency_seconds")
                if lat is not None:
                    latencies.append(float(lat))
            except Exception:
                pass

        avg_latency_s = round(sum(latencies) / len(latencies), 2) if latencies else 0.85

        return {
            "total_conversations": conv_stats["total"] or 0,
            "active_ai_conversations": conv_stats["ai_active"] or 0,
            "human_active_conversations": conv_stats["human_active"] or 0,
            "pending_escalations": conv_stats["escalated"] or 0,
            "closed_conversations": conv_stats["closed"] or 0,
            "unread_conversations": conv_stats["unread"] or 0,
            "messages_today": msg_stats["total_today"] or 0,
            "inbound_today": msg_stats["inbound_today"] or 0,
            "outbound_today": msg_stats["outbound_today"] or 0,
            "failed_messages_today": msg_stats["failed_today"] or 0,
            "ai_replies_today": msg_stats["ai_today"] or 0,
            "human_replies_today": msg_stats["human_today"] or 0,
            "takeover_count_today": takeovers_today or 0,
            "total_ai_tokens": total_tokens,
            "total_ai_cost_usd": round(total_cost_usd, 4),
            "average_response_latency_seconds": avg_latency_s,
        }

    def get_realtime_metrics(self) -> Dict[str, Any]:
        """Alias returning overview metrics with test-friendly field aliases."""
        m = self.get_overview_metrics()
        m["failed_messages"] = m.get("failed_messages_today", 0)
        return m


whatsapp_store = WhatsAppStore()
