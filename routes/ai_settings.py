"""
AI Settings & Central AI Provider Gateway Routes
Allows secure configuration of OpenAI (GPT-6 Luna), Gemini, and Offline mode.
Provides usage statistics, connection testing, and internal AI bridge.
"""

import logging
from flask import Blueprint, jsonify, render_template, request
from services.ai_provider_manager import ai_manager

logger = logging.getLogger(__name__)

ai_settings_bp = Blueprint("ai_settings", __name__)


@ai_settings_bp.route("/ai-settings", methods=["GET"])
@ai_settings_bp.route("/ki-einstellungen", methods=["GET"])
def ai_settings_page():
    """Render the JobScout SPA shell configured to display the AI Settings section."""
    import os
    supabase_url = os.getenv("VITE_SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    supabase_anon_key = os.getenv("VITE_SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))
    return render_template(
        "app_shell.html",
        initial_section="ai-settings",
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key
    )


@ai_settings_bp.route("/api/ai/settings", methods=["GET"])
def get_ai_settings():
    """Return public status and safe masked credentials for AI configuration."""
    try:
        status = ai_manager.get_public_status()
        return jsonify({"success": True, "settings": status})
    except Exception as e:
        logger.error(f"Error fetching AI settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_settings_bp.route("/api/ai/settings", methods=["POST"])
def update_ai_settings():
    """Update AI configuration safely without logging or exposing secret keys."""
    try:
        data = request.get_json(silent=True) or {}
        updates = {}

        if "primary_provider" in data:
            prov = str(data["primary_provider"]).strip().lower()
            if prov in ("openai", "gemini", "offline"):
                updates["primary_provider"] = prov

        if "openai_api_key" in data:
            key = str(data["openai_api_key"]).strip()
            # Only update if user provided an actual non-masked key
            if key and not key.startswith("••••") and not "•••" in key:
                updates["openai_api_key"] = key

        if "openai_model" in data:
            model = str(data["openai_model"]).strip()
            if model:
                updates["openai_model"] = model

        if "openai_endpoint" in data:
            endpoint = str(data["openai_endpoint"]).strip().rstrip("/")
            if endpoint:
                updates["openai_endpoint"] = endpoint

        if "gemini_api_key" in data:
            key = str(data["gemini_api_key"]).strip()
            if key and not key.startswith("••••") and not "•••" in key:
                updates["gemini_api_key"] = key

        if "gemini_model" in data:
            model = str(data["gemini_model"]).strip()
            if model:
                updates["gemini_model"] = model

        if "enable_gemini_fallback" in data:
            updates["enable_gemini_fallback"] = bool(data["enable_gemini_fallback"])

        if "monthly_budget_usd" in data:
            try:
                updates["monthly_budget_usd"] = float(data["monthly_budget_usd"])
            except (ValueError, TypeError):
                pass

        saved_config = ai_manager.save_config(updates)
        return jsonify({
            "success": True,
            "message": "AI-Einstellungen erfolgreich gespeichert.",
            "settings": ai_manager.get_public_status()
        })
    except Exception as e:
        logger.error(f"Error updating AI settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_settings_bp.route("/api/ai/test-connection", methods=["POST"])
def test_connection():
    """
    Test connection to OpenAI or Gemini without making paid inference calls.
    Uses model metadata listing endpoints (0 inference tokens).
    """
    try:
        data = request.get_json(silent=True) or {}
        provider = str(data.get("provider", "openai")).strip().lower()
        api_key = data.get("api_key")

        # Clean key if passed as masked string
        if api_key and ("••••" in api_key or "•••" in api_key):
            api_key = None

        if provider == "openai":
            result = ai_manager.test_openai_connection(api_key=api_key)
            return jsonify(result)
        elif provider == "gemini":
            result = ai_manager.test_gemini_connection(api_key=api_key)
            return jsonify(result)
        else:
            return jsonify({
                "success": True,
                "status": "connected",
                "message": "Lokaler Offline-Modus ist immer betriebsbereit (0 Kosten)."
            })
    except Exception as e:
        logger.error(f"Error testing AI connection: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_settings_bp.route("/api/ai/usage", methods=["GET"])
def get_ai_usage():
    """Return token usage metrics, cost accounting, and cache hit statistics."""
    try:
        summary = ai_manager.get_usage_summary()
        return jsonify({"success": True, "usage": summary})
    except Exception as e:
        logger.error(f"Error fetching AI usage: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_settings_bp.route("/api/ai/reset-cache", methods=["POST"])
def reset_ai_cache():
    """Clear AI response cache."""
    try:
        ai_manager.cache.clear()
        cache_file = ai_manager.cache_file if hasattr(ai_manager, "cache_file") else None
        from pathlib import Path
        cache_path = Path(__file__).resolve().parent.parent / "data" / "ai_cache.json"
        if cache_path.exists():
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write("{}")
        return jsonify({"success": True, "message": "KI-Cache erfolgreich geleert."})
    except Exception as e:
        logger.error(f"Error resetting AI cache: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_settings_bp.route("/api/ai/bridge-autofill", methods=["POST"])
def bridge_autofill():
    """
    Internal bridge for Node.js autofill server and background tools.
    Routes queries through central AI manager without copying secret keys.
    """
    try:
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt") or ""
        system_prompt = data.get("system_prompt") or "You are a helpful career assistant."
        max_tokens = int(data.get("max_output_tokens", 250))
        temperature = float(data.get("temperature", 0.2))

        if not prompt:
            return jsonify({"success": False, "error": "Prompt darf nicht leer sein."}), 400

        res = ai_manager.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature
        )
        return jsonify(res)
    except Exception as e:
        logger.error(f"Error in AI bridge autofill: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
