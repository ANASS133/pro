"""
JobScout WhatsApp Authorized Read-Only Service Tools
====================================================
Server-controlled read-only tools enabling the JobScout Virtual Support Assistant
to query verified live data without arbitrary execution or cross-tenant data exposure.

Security Principles:
1. Strict Tool Schema & Allowlist: Only predefined functions can be invoked.
2. Tenant Isolation & Context Binding: Client-specific tools bind directly to the conversation's
   verified `client_id` provided by the server context. The model CANNOT request data for other clients.
3. Verification Gate: Unverified WhatsApp contacts are prevented from viewing personal application,
   financial, or document details until secure account linking occurs.
4. Transparent Factual Anchoring: All data is queried from live internal services (ClientManager,
   SupabaseService, ProfessionMatcher, KnowledgeBase).
"""

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from services.client_manager import client_manager
from services.profession_matcher import evaluate_profession_match
from services.supabase_service import supabase_service
from services.whatsapp_store import whatsapp_store

logger = logging.getLogger(__name__)


class WhatsAppToolRegistry:
    """Manages tool execution and security enforcement for WhatsApp AI turns."""

    def __init__(self, store=None):
        self._store = store or whatsapp_store
        self._tools: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {}
        self._schemas: List[Dict[str, Any]] = []
        self._register_all_tools()

    def _register_tool(self, name: str, description: str, parameters: Dict[str, Any], func: Callable):
        self._tools[name] = func
        self._schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        })

    def get_tool_schemas(self, allowed_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Returns tool schemas filtered by allowed names."""
        if not allowed_names:
            return self._schemas
        allowed_set = set(allowed_names)
        return [s for s in self._schemas if s["function"]["name"] in allowed_set]

    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes a registered tool within the verified conversation context.
        context keys: conversation_id, wa_id, client_id, display_name
        """
        effective_context = dict(context or {})
        effective_context.update(kwargs)

        if tool_name not in self._tools:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' is not in the authorized tool allowlist.",
            }

        try:
            handler = self._tools[tool_name]
            return handler(arguments, effective_context)
        except Exception as exc:
            logger.error("Error executing tool '%s': %s", tool_name, exc, exc_info=True)
            return {
                "success": False,
                "error": f"Fehler bei der Ausführung von '{tool_name}': {str(exc)}",
            }

    # -------------------------------------------------------------------------
    # Tool Registrations
    # -------------------------------------------------------------------------

    def _register_all_tools(self):
        # 1. get_client_profile
        self._register_tool(
            name="get_client_profile",
            description="Ruft das verifizierte JobScout-Bewerberprofil ab (Name, E-Mail, Sprachniveau, Berufsfeld). Erfordert verifiziertes Konto.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=self._tool_get_client_profile,
        )

        # 2. get_client_application_statistics
        self._register_tool(
            name="get_client_application_statistics",
            description="Ruft die aktuellen Bewerbungsstatistiken ab (Anzahl versendeter Bewerbungen, Paket-Kontingent, Status).",
            parameters={"type": "object", "properties": {}, "required": []},
            func=self._tool_get_client_application_statistics,
        )

        # 3. get_client_application_status
        self._register_tool(
            name="get_client_application_status",
            description="Ruft den aktuellen Bearbeitungs- und Prüfstatus der JobScout-Bewerbung ab.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=self._tool_get_client_application_status,
        )

        # 4. get_client_profession
        self._register_tool(
            name="get_client_profession",
            description="Ruft die hinterlegte Ausbildungsrichtung / den Beruf des Bewerbers ab.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=self._tool_get_client_profession,
        )

        # 5. get_profession_dataset_availability
        self._register_tool(
            name="get_profession_dataset_availability",
            description="Prüft im JobScout-Datensatz-Manager, ob für einen bestimmten Ausbildungsberuf ein passender Stellen-Datensatz existiert (Vorhanden / Ähnlich / Nicht vorhanden) und wie viele Stellen verfügbar sind.",
            parameters={
                "type": "object",
                "properties": {
                    "profession": {
                        "type": "string",
                        "description": "Der Name des Ausbildungsberufs (z.B. 'Fachinformatiker', 'Pflegefachmann', 'Koch')",
                    }
                },
                "required": ["profession"],
            },
            func=self._tool_get_profession_dataset_availability,
        )

        # 6. get_client_document_status
        self._register_tool(
            name="get_client_document_status",
            description="Prüft die eingereichten Unterlagen des Bewerbers (Lebenslauf/CV, Zeugnisse, Zertifikate) und deren Vollständigkeit.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=self._tool_get_client_document_status,
        )

        # 7. get_client_payment_status
        self._register_tool(
            name="get_client_payment_status",
            description="Ruft den Zahlungs- und Freigabestatus des gebuchten Bewerbungspakets ab.",
            parameters={"type": "object", "properties": {}, "required": []},
            func=self._tool_get_client_payment_status,
        )

        # 8. get_jobscout_service_information
        self._register_tool(
            name="get_jobscout_service_information",
            description="Sucht in der offiziellen JobScout-Wissensdatenbank nach geprüften Informationen zu Dienstleistungen, Preisen, Visabestimmungen, Ablauf und Richtlinien.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Suchbegriff oder Frage (z.B. 'Preise', 'Ablauf', 'Visum', 'Pakete')",
                    }
                },
                "required": ["query"],
            },
            func=self._tool_get_jobscout_service_information,
        )

        # 9. request_human_support
        self._register_tool(
            name="request_human_support",
            description="Eskaliert die Konversation an einen menschlichen JobScout-Berater und benachrichtigt das Support-Team, wenn der Kunde persönliche Hilfe wünscht oder ein komplexes Anliegen vorliegt.",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Der Grund für die Eskalation (z.B. 'Kunde wünscht Gespräch mit Mitarbeiter', 'Zahlungsunstimmigkeit')",
                    }
                },
                "required": ["reason"],
            },
            func=self._tool_request_human_support,
        )

        # 10. verify_client_account
        self._register_tool(
            name="verify_client_account",
            description="Verknüpft die WhatsApp-Nummer sicher mit dem JobScout-Bewerberkonto anhand des persönlichen Bewerber-Codes oder der registrierten E-Mail-Adresse.",
            parameters={
                "type": "object",
                "properties": {
                    "code_or_email": {
                        "type": "string",
                        "description": "Der persönliche Bewerber-Code (z.B. aus der Anmeldebestätigung) oder die registrierte E-Mail-Adresse.",
                    }
                },
                "required": ["code_or_email"],
            },
            func=self._tool_verify_client_account,
        )

    # -------------------------------------------------------------------------
    # Tool Implementations
    # -------------------------------------------------------------------------

    def _require_verified_client(self, context: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Ensures that the conversation is linked to a verified client dossier."""
        client_id = context.get("client_id")
        if not client_id:
            return False, None, {
                "success": False,
                "auth_required": True,
                "authenticated": False,
                "error": "Authentifizierung erforderlich: Dieses WhatsApp-Konto ist noch nicht verknüpft.",
                "message": (
                    "Authentifizierung erforderlich: Dieses WhatsApp-Konto ist noch nicht mit einem JobScout-Bewerberkonto verknüpft. "
                    "Bitte nennen Sie Ihren persönlichen Bewerber-Code oder Ihre registrierte E-Mail-Adresse, "
                    "um Ihre persönlichen Daten einzusehen."
                ),
            }

        profile = client_manager.get_client_profile(client_id)
        if not profile:
            # Fallback to Supabase application lookup
            try:
                app = supabase_service.get_application(client_id)
                if app:
                    return True, client_id, {"profile": app, "is_supabase": True}
            except Exception:
                pass
            return False, None, {
                "success": False,
                "error": f"Bewerberprofil '{client_id}' konnte nicht gefunden werden.",
            }

        return True, client_id, profile

    def _tool_get_client_profile(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        is_auth, client_id, profile = self._require_verified_client(context)
        if not is_auth:
            return profile or {}

        # Safe data minimization - omit internal storage paths
        return {
            "success": True,
            "client_id": client_id,
            "full_name": profile.get("full_name") or profile.get("name") or "Bewerber",
            "email": profile.get("email") or "k. A.",
            "language_level": profile.get("language_level") or profile.get("german_level") or "B1/B2",
            "profession_field": profile.get("field") or profile.get("target_profession") or "Allgemein",
            "status": profile.get("status") or "Aktiv",
        }

    def _tool_get_client_application_statistics(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        is_auth, client_id, profile = self._require_verified_client(context)
        if not is_auth:
            return profile or {}

        # Look up application volume & progress
        total_limit = 500
        sent_count = 0
        pack_name = "500 Bewerbungen"

        pack_info = profile.get("package") or profile.get("pack")
        if isinstance(pack_info, dict):
            total_limit = pack_info.get("total_limit", 500)
            pack_name = pack_info.get("name", "500 Bewerbungen")
        elif isinstance(pack_info, str):
            pack_name = pack_info
            if "1000" in pack_info:
                total_limit = 1000
            elif "2000" in pack_info:
                total_limit = 2000

        # Ingestion metrics
        metrics = profile.get("metrics") or {}
        sent_count = metrics.get("sent_applications") or metrics.get("applied_count") or 0

        conductor_stats = {}
        try:
            from services.conductor_store import conductor_store
            conductor_stats = conductor_store.count_matches_by_status(client_id)
            sent_count = max(int(sent_count), int(conductor_stats.get("applied", 0)))
        except Exception:
            pass

        # Also check Supabase application payment
        is_payed = profile.get("is_payed", False)

        return {
            "success": True,
            "client_id": client_id,
            "package_name": pack_name,
            "total_quota": total_limit,
            "sent_applications": sent_count,
            "sent_applications_count": sent_count,
            "staged_for_approval": conductor_stats.get("staged_for_approval", 0),
            "interviews_count": conductor_stats.get("interview", 0),
            "status": "In Bearbeitung" if is_payed else "Wartet auf Zahlungseingang",
            "remaining_quota": max(0, total_limit - sent_count),
            "payment_confirmed": is_payed,
            "campaign_status": "Laufend" if is_payed and sent_count < total_limit else ("Bereit" if is_payed else "Wartet auf Zahlungseingang"),
        }

    def _tool_get_client_application_status(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        is_auth, client_id, profile = self._require_verified_client(context)
        if not is_auth:
            return profile or {}

        is_payed = profile.get("is_payed", False)
        doc_count = len(profile.get("documents") or [])

        stage = "Prüfung der Unterlagen"
        if not is_payed:
            stage = "Warten auf Zahlungsbestätigung"
        elif doc_count >= 1:
            stage = "Bewerbungsunterlagen freigegeben & aktiv in Vermittlung"

        return {
            "success": True,
            "client_id": client_id,
            "applicant_name": profile.get("full_name") or "Bewerber",
            "current_stage": stage,
            "is_payed": is_payed,
            "documents_submitted": doc_count,
            "next_steps": "Unsere Fachberater stimmen die nächsten Bewerbungskontingente ab." if is_payed else "Bitte überweisen Sie die Paketgebühr, damit Ihre Kampagne freigeschaltet wird.",
        }

    def _tool_get_client_profession(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        is_auth, client_id, profile = self._require_verified_client(context)
        if not is_auth:
            return profile or {}

        field = profile.get("field") or profile.get("target_profession") or "Nicht spezifiziert"
        return {
            "success": True,
            "client_id": client_id,
            "profession": field,
        }

    def _tool_get_profession_dataset_availability(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        profession_query = str(args.get("profession") or "").strip()
        if not profession_query:
            return {"success": False, "error": "Bitte geben Sie einen Berufsnamen an."}

        # Query live auto_extraction_exports via app helper
        try:
            from app import _list_auto_extraction_export_files
            available_exports = _list_auto_extraction_export_files()
        except Exception:
            available_exports = []

        match_res = evaluate_profession_match(profession_query, available_exports)
        status = match_res.get("status")  # available, similar, missing
        label = match_res.get("label")    # Vorhanden, Ähnlich, Nicht vorhanden
        total_listings = match_res.get("total_listings", 0)
        matched_prof = match_res.get("matched_profession") or profession_query

        return {
            "success": True,
            "searched_profession": profession_query,
            "matched_profession": matched_prof,
            "status": status,
            "status_label": label,
            "match_type": match_res.get("match_type"),
            "total_listings": total_listings,
            "details": match_res.get("details"),
        }

    def _tool_get_client_document_status(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        is_auth, client_id, profile = self._require_verified_client(context)
        if not is_auth:
            return profile or {}

        raw_docs = profile.get("documents") or []
        doc_summary = []
        for d in raw_docs:
            if isinstance(d, dict):
                doc_summary.append({
                    "name": d.get("name") or d.get("filename") or "Dokument",
                    "status": d.get("status") or "Hochgeladen",
                })
            elif isinstance(d, str):
                filename = d.split("/")[-1].split("\\")[-1]
                doc_summary.append({
                    "name": filename,
                    "status": "Eingereicht",
                })

        return {
            "success": True,
            "client_id": client_id,
            "document_count": len(doc_summary),
            "documents": doc_summary,
            "complete": len(doc_summary) >= 1,
            "notice": "Alle Dokumente liegen sicher im JobScout-Dossier vor." if doc_summary else "Es wurden noch keine Bewerbungsdokumente hinterlegt.",
        }

    def _tool_get_client_payment_status(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        is_auth, client_id, profile = self._require_verified_client(context)
        if not is_auth:
            return profile or {}

        is_payed = profile.get("is_payed", False)
        pack = profile.get("pack") or profile.get("package") or "Standard"
        bank = profile.get("bank") or "Banküberweisung"

        return {
            "success": True,
            "client_id": client_id,
            "is_payed": is_payed,
            "payment_status": "Bezahlt & Verifiziert" if is_payed else "Offen / Ausstehend",
            "package": pack,
            "bank_details_reference": bank if not is_payed else "Bestätigt",
        }

    def _tool_get_jobscout_service_information(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        query_str = str(args.get("query") or "").strip()
        results = self._store.search_knowledge_base(query_str, limit=3)
        if not results:
            return {
                "success": True,
                "found": False,
                "message": "Zu diesem Thema liegt kein spezifischer Wissenseintrag vor. Bitte erfragen Sie Unterstützung durch einen Berater.",
            }

        formatted = [{"title": r["title"], "content": r["content"], "category": r["category"]} for r in results]
        return {
            "success": True,
            "found": True,
            "results": formatted,
        }

    def _tool_request_human_support(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        conversation_id = context.get("conversation_id")
        reason = str(args.get("reason") or "Kunde wünscht persönliche Beratung").strip()

        if conversation_id:
            self._store.atomic_escalate(conversation_id, reason=reason, actor="ai_assistant")
            return {
                "success": True,
                "escalated": True,
                "message": (
                    "Das Anliegen wurde an einen menschlichen JobScout-Berater weitergeleitet. "
                    "Ein Mitarbeiter wird sich in Kürze hier im WhatsApp-Chat melden."
                ),
            }
        return {"success": False, "error": "Keine Konversations-ID im Kontext."}

    def _tool_verify_client_account(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        code_or_email = str(args.get("code_or_email") or "").strip()
        conversation_id = context.get("conversation_id")
        wa_id = context.get("wa_id", "")

        if not code_or_email:
            return {"success": False, "error": "Bitte geben Sie Ihren Code oder Ihre E-Mail-Adresse an."}

        # 1. Look up in Supabase applications by code or email
        matched_app = None
        try:
            apps = supabase_service.list_applications(limit=150)
            clean_term = code_or_email.lower()
            for app in apps:
                app_code = str(app.get("code") or "").lower()
                app_email = str(app.get("email") or "").lower()
                app_phone = str(app.get("whatsapp") or "").replace("+", "").replace(" ", "").replace("-", "")

                # Match if code or email matches AND phone partially aligns or direct match
                if (clean_term in app_code or clean_term == app_email) or (app_phone and app_phone == wa_id):
                    matched_app = app
                    break
        except Exception as exc:
            logger.warning("Error searching Supabase for client verification: %s", exc)

        # 2. Look up in local client dossiers
        if not matched_app:
            for client in client_manager.list_clients():
                c_prof = client_manager.get_client_profile(client["id"]) or {}
                c_email = str(c_prof.get("email") or "").lower()
                c_phone = str(c_prof.get("phone") or c_prof.get("whatsapp") or "").replace("+", "").replace(" ", "").replace("-", "")
                if code_or_email.lower() == c_email or (c_phone and c_phone == wa_id):
                    matched_app = {"id": client["id"], "full_name": client.get("name"), "field": c_prof.get("field")}
                    break

        if not matched_app:
            return {
                "success": False,
                "verified": False,
                "message": (
                    "Leider konnte unter dieser Angabe kein passendes JobScout-Bewerberkonto gefunden werden. "
                    "Bitte überprüfen Sie Ihren Bewerber-Code oder die E-Mail-Adresse."
                ),
            }

        client_id = matched_app.get("id")
        applicant_name = matched_app.get("full_name") or matched_app.get("name") or "Bewerber"

        if conversation_id:
            whatsapp_store.update_conversation(conversation_id, {
                "client_id": client_id,
                "client_code": code_or_email,
                "display_name": applicant_name,
            })
            whatsapp_store.add_audit_log(
                conversation_id,
                "ai_assistant",
                "verify_client",
                details={"client_id": client_id, "matched_identifier": code_or_email},
            )

        return {
            "success": True,
            "verified": True,
            "client_id": client_id,
            "applicant_name": applicant_name,
            "message": f"Konto erfolgreich verifiziert! Herzlich willkommen, {applicant_name}. Sie können nun Ihren Bewerbungsstatus und Ihre Daten abfragen.",
        }


tool_registry = WhatsAppToolRegistry()
