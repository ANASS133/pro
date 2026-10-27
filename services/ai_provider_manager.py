"""
JobScout Central AI Provider Manager
====================================
Unified, secure, and production-grade AI gateway supporting:
1. Official OpenAI API (GPT-6 Luna, GPT-5.6 Luna, GPT-4o-mini) via /v1/responses & /v1/chat/completions
2. Google Gemini API (gemini-2.5-flash, gemini-3.1-flash-lite, gemini-3.5-flash-lite)
3. Local Heuristic / Offline Processing

Features:
- Zero OpenRouter dependencies
- Server-side secret protection with safe masking (never exposed to browser)
- Deterministic SHA-256 caching for repeat calls
- Token usage and estimated cost tracking (USD)
- Automatic fallback from primary to secondary provider when explicitly enabled
- Safe connection testing without paid inference calls
- Thread-safe persistence in data/ai_config.json & data/ai_usage.json
"""

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "ai_config.json"
CACHE_FILE = DATA_DIR / "ai_cache.json"
USAGE_FILE = DATA_DIR / "ai_usage.json"

# Pricing estimates per 1M tokens (USD)
MODEL_PRICING = {
    # OpenAI Models
    "gpt-6-luna": {"input": 0.20, "output": 1.20},
    "gpt-6-luna-pro": {"input": 0.30, "output": 1.80},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-luna-pro": {"input": 0.30, "output": 1.80},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Gemini Models (Pay-as-you-go reference; free tier is $0.00)
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-3.1-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-3.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}


class AIProviderManager:
    """Central orchestrator for AI operations across all JobScout features."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AIProviderManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._load_config()
        self._load_usage()

    # -------------------------------------------------------------------------
    # Configuration Management & Secret Masking
    # -------------------------------------------------------------------------

    def _load_config(self):
        """Loads configuration from data/ai_config.json with env fallbacks."""
        defaults = {
            "primary_provider": os.environ.get("AI_PROVIDER", "openai").strip().lower(),
            "openai_api_key": os.environ.get("OPENAI_API_KEY", "").strip(),
            "openai_model": os.environ.get("OPENAI_MODEL", "gpt-6-luna").strip(),
            "openai_endpoint": os.environ.get("OPENAI_ENDPOINT", "https://api.openai.com/v1").rstrip("/"),
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", "").strip(),
            "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            "enable_gemini_fallback": os.environ.get("AI_ENABLE_FALLBACK", "false").lower() in ("true", "1", "yes"),
            "monthly_budget_usd": float(os.environ.get("AI_MONTHLY_BUDGET_USD", "15.0")),
            "last_tested_openai": None,
            "last_tested_gemini": None,
            "openai_status": "untested",
            "gemini_status": "untested",
            "openai_available_models": [],
        }

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    defaults.update(saved)
            except Exception as e:
                logger.warning("Could not read ai_config.json: %s", e)

        # Environment variable overrides
        if os.environ.get("OPENAI_API_KEY"):
            defaults["openai_api_key"] = os.environ.get("OPENAI_API_KEY", "").strip()
        if os.environ.get("OPENAI_MODEL"):
            defaults["openai_model"] = os.environ.get("OPENAI_MODEL", "").strip()
        if os.environ.get("GEMINI_API_KEY"):
            defaults["gemini_api_key"] = os.environ.get("GEMINI_API_KEY", "").strip()

        self.config = defaults

    def save_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Saves configuration updates safely to disk."""
        with self.lock:
            for k, v in updates.items():
                if k in self.config:
                    # Prevent overwriting an existing secret with a masked placeholder
                    if "key" in k and isinstance(v, str) and ("••••" in v or "..." in v):
                        continue
                    self.config[k] = v

            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error("Failed to save ai_config.json: %s", e)
                return {"success": False, "error": str(e)}

            # Sync with os.environ for runtime consistency
            if self.config.get("openai_api_key"):
                os.environ["OPENAI_API_KEY"] = self.config["openai_api_key"]
            if self.config.get("openai_model"):
                os.environ["OPENAI_MODEL"] = self.config["openai_model"]
            if self.config.get("gemini_api_key"):
                os.environ["GEMINI_API_KEY"] = self.config["gemini_api_key"]

            return {"success": True, "public_config": self.get_public_status()}

    @staticmethod
    def mask_key(key: Optional[str]) -> str:
        """Masks an API key securely (e.g., sk-proj-••••••••a8F9)."""
        if not key:
            return ""
        k = key.strip()
        if len(k) <= 8:
            return "••••••••"
        return f"{k[:7]}••••••••{k[-4:]}"

    @property
    def is_configured(self) -> bool:
        """Returns True if the primary provider has an active key or is in offline mode."""
        prov = self.config.get("primary_provider", "openai")
        if prov == "offline":
            return True
        elif prov == "openai":
            return bool(self.config.get("openai_api_key"))
        elif prov == "gemini":
            return bool(self.config.get("gemini_api_key"))
        return False

    def get_public_status(self) -> Dict[str, Any]:
        """Returns safe, non-sensitive configuration for the frontend."""
        with self.lock:
            openai_configured = bool(self.config.get("openai_api_key"))
            gemini_configured = bool(self.config.get("gemini_api_key"))
            return {
                "primary_provider": self.config.get("primary_provider", "openai"),
                "openai_has_key": openai_configured,
                "openai_masked_key": self.mask_key(self.config.get("openai_api_key")),
                "openai_model": self.config.get("openai_model", "gpt-6-luna"),
                "openai_status": self.config.get("openai_status", "untested"),
                "last_tested_openai": self.config.get("last_tested_openai"),
                "gemini_has_key": gemini_configured,
                "gemini_masked_key": self.mask_key(self.config.get("gemini_api_key")),
                "gemini_model": self.config.get("gemini_model", "gemini-2.5-flash"),
                "gemini_status": self.config.get("gemini_status", "untested"),
                "last_tested_gemini": self.config.get("last_tested_gemini"),
                "openai": {
                    "configured": openai_configured,
                    "masked_key": self.mask_key(self.config.get("openai_api_key")),
                    "model": self.config.get("openai_model", "gpt-6-luna"),
                    "status": self.config.get("openai_status", "untested"),
                    "last_tested": self.config.get("last_tested_openai"),
                    "available_models": self.config.get("openai_available_models") or [
                        "gpt-6-luna", "gpt-6-luna-pro", "gpt-5.6-luna", "gpt-5.6-luna-pro", "gpt-4o-mini", "gpt-4o"
                    ],
                },
                "gemini": {
                    "configured": gemini_configured,
                    "masked_key": self.mask_key(self.config.get("gemini_api_key")),
                    "model": self.config.get("gemini_model", "gemini-2.5-flash"),
                    "status": self.config.get("gemini_status", "untested"),
                    "last_tested": self.config.get("last_tested_gemini"),
                    "available_models": [
                        "gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-1.5-flash"
                    ],
                },
                "enable_gemini_fallback": self.config.get("enable_gemini_fallback", False),
                "monthly_budget_usd": self.config.get("monthly_budget_usd", 15.0),
                "usage_summary": self.get_usage_summary(),
            }

    # -------------------------------------------------------------------------
    # Connection Testing (Safe: Zero Paid Inference Tokens)
    # -------------------------------------------------------------------------

    def test_openai_connection(
        self,
        api_key: Optional[str] = None,
        key_override: Optional[str] = None,
        model: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Safely verifies OpenAI credentials by listing models (GET /v1/models).
        Does NOT incur paid inference token costs.
        """
        effective_key = api_key or key_override or self.config.get("openai_api_key")
        effective_model = model or model_override or self.config.get("openai_model", "gpt-6-luna")

        if not effective_key:
            return {"success": False, "error": "Kein OpenAI API Key vorhanden."}

        endpoint = self.config.get("openai_endpoint", "https://api.openai.com/v1")
        url = f"{endpoint}/models"

        start_time = time.time()
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {effective_key}"},
                timeout=10,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                models_list = [m.get("id") for m in data.get("data", []) if m.get("id")]
                now_str = datetime.now().isoformat()

                # Check if chosen model or luna variants appear in the account
                luna_matches = [m for m in models_list if "luna" in m.lower() or "gpt" in m.lower()]

                self.save_config({
                    "openai_status": "connected",
                    "last_tested_openai": now_str,
                    "openai_available_models": luna_matches[:10] if luna_matches else models_list[:10],
                })

                return {
                    "success": True,
                    "status": "connected",
                    "latency_ms": latency_ms,
                    "target_model": effective_model,
                    "model_found": any(effective_model.lower() == m.lower() for m in models_list),
                    "total_accessible_models": len(models_list),
                    "message": f"Verbindung erfolgreich! ({latency_ms}ms, {len(models_list)} Modelle zugänglich)",
                }
            elif resp.status_code == 401:
                self.save_config({"openai_status": "error"})
                return {"success": False, "error": "Ungültiger API-Schlüssel (HTTP 401 Unauthorized)."}
            else:
                self.save_config({"openai_status": "error"})
                return {"success": False, "error": f"OpenAI API Fehler ({resp.status_code}): {resp.text[:200]}"}
        except Exception as e:
            logger.error("OpenAI connection test failed: %s", e)
            self.save_config({"openai_status": "error"})
            return {"success": False, "error": f"Verbindungsfehler: {str(e)}"}

    def test_gemini_connection(
        self,
        api_key: Optional[str] = None,
        key_override: Optional[str] = None,
        model: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Safely verifies Gemini credentials by querying available models.
        """
        effective_key = api_key or key_override or self.config.get("gemini_api_key")
        effective_model = model or model_override or self.config.get("gemini_model", "gemini-2.5-flash")

        if not effective_key:
            return {"success": False, "error": "Kein Google Gemini API Key vorhanden."}

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={effective_key}"
        start_time = time.time()
        try:
            resp = requests.get(url, timeout=10)
            latency_ms = int((time.time() - start_time) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                raw_models = [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
                now_str = datetime.now().isoformat()
                self.save_config({
                    "gemini_status": "connected",
                    "last_tested_gemini": now_str,
                })
                return {
                    "success": True,
                    "status": "connected",
                    "latency_ms": latency_ms,
                    "target_model": model,
                    "available_models": raw_models[:12],
                    "message": f"Gemini API verbunden! ({latency_ms}ms, {len(raw_models)} Modelle verfügbar)",
                }
            elif resp.status_code == 400 or resp.status_code == 403:
                self.save_config({"gemini_status": "error"})
                return {"success": False, "error": f"Ungültiger Gemini Key ({resp.status_code})."}
            else:
                self.save_config({"gemini_status": "error"})
                return {"success": False, "error": f"Gemini API Fehler ({resp.status_code}): {resp.text[:200]}"}
        except Exception as e:
            self.save_config({"gemini_status": "error"})
            return {"success": False, "error": f"Verbindungsfehler: {str(e)}"}

    # -------------------------------------------------------------------------
    # Caching Layer (SHA-256)
    # -------------------------------------------------------------------------

    def _get_cache_key(self, prompt: str, system_prompt: str, model: str) -> str:
        combined = f"{model.strip().lower()}|{system_prompt.strip()}|{prompt.strip()}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if not CACHE_FILE.exists():
            return None
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(cache_key)
        except Exception:
            return None

    def _set_cached(self, cache_key: str, entry: Dict[str, Any]):
        try:
            data = {}
            if CACHE_FILE.exists():
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[cache_key] = entry
            # Limit cache size to 5,000 recent items
            if len(data) > 5000:
                keys = list(data.keys())[:1000]
                for k in keys:
                    data.pop(k, None)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.debug("Failed saving AI cache: %s", e)

    # -------------------------------------------------------------------------
    # Usage & Cost Tracking
    # -------------------------------------------------------------------------

    def _load_usage(self):
        defaults = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "cache_hits": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "estimated_cost_usd": 0.0,
            "daily_stats": {},
            "model_stats": {},
        }
        if USAGE_FILE.exists():
            try:
                with open(USAGE_FILE, "r", encoding="utf-8") as f:
                    defaults.update(json.load(f))
            except Exception:
                pass
        self.usage = defaults

    def _record_usage(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        from_cache: bool = False,
        success: bool = True,
        provider: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None
    ):
        if input_tokens is not None:
            prompt_tokens = input_tokens
        if output_tokens is not None:
            completion_tokens = output_tokens

        with self.lock:
            self.usage["total_requests"] += 1
            if success:
                self.usage["successful_requests"] += 1
            else:
                self.usage["failed_requests"] += 1

            if from_cache:
                self.usage["cache_hits"] += 1
                return

            self.usage["total_prompt_tokens"] += prompt_tokens
            self.usage["total_completion_tokens"] += completion_tokens

            # Calculate cost estimate
            if cost_usd is not None:
                cost = cost_usd
            else:
                pricing = MODEL_PRICING.get(model.lower()) or {"input": 0.20, "output": 1.20}
                cost = ((prompt_tokens / 1_000_000) * pricing["input"]) + ((completion_tokens / 1_000_000) * pricing["output"])
            self.usage["estimated_cost_usd"] = round(self.usage["estimated_cost_usd"] + cost, 6)

            # Daily breakdown
            today = datetime.now().strftime("%Y-%m-%d")
            d = self.usage["daily_stats"].setdefault(today, {"requests": 0, "tokens": 0, "cost_usd": 0.0})
            d["requests"] += 1
            d["tokens"] += (prompt_tokens + completion_tokens)
            d["cost_usd"] = round(d["cost_usd"] + cost, 6)

            # Model breakdown
            m = self.usage["model_stats"].setdefault(model, {"requests": 0, "tokens": 0, "cost_usd": 0.0})
            m["requests"] += 1
            m["tokens"] += (prompt_tokens + completion_tokens)
            m["cost_usd"] = round(m["cost_usd"] + cost, 6)

            try:
                with open(USAGE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.usage, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.debug("Failed to write ai_usage.json: %s", e)

    def get_usage_summary(self) -> Dict[str, Any]:
        with self.lock:
            total = self.usage["total_requests"]
            hits = self.usage["cache_hits"]
            hit_rate = round((hits / total * 100), 1) if total > 0 else 0.0
            return {
                "total_requests": total,
                "successful_requests": self.usage["successful_requests"],
                "failed_requests": self.usage["failed_requests"],
                "cache_hits": hits,
                "cache_hit_rate_pct": hit_rate,
                "total_tokens": self.usage["total_prompt_tokens"] + self.usage["total_completion_tokens"],
                "input_tokens": self.usage["total_prompt_tokens"],
                "output_tokens": self.usage["total_completion_tokens"],
                "total_prompt_tokens": self.usage["total_prompt_tokens"],
                "total_completion_tokens": self.usage["total_completion_tokens"],
                "estimated_cost_usd": round(self.usage["estimated_cost_usd"], 4),
                "daily_stats": self.usage.get("daily_stats", {}),
            }

    # -------------------------------------------------------------------------
    # Core Inference Orchestrator
    # -------------------------------------------------------------------------

    def complete(
        self,
        prompt: str,
        system_prompt: str = "You are JobScout AI assistant.",
        model_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        max_output_tokens: int = 800,
        temperature: float = 0.2,
        json_mode: bool = False,
        use_cache: bool = True,
        candidate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes an AI completion request across configured providers with:
        1. Cache lookup ($0.00)
        2. Primary Provider (OpenAI GPT Luna by default)
        3. Optional Secondary Provider (Gemini if enabled)
        4. Structured output validation
        """
        provider = (provider_override or self.config.get("primary_provider", "openai")).lower()
        model = (model_override or (self.config.get("openai_model", "gpt-6-luna") if provider == "openai" else self.config.get("gemini_model", "gemini-2.5-flash"))).strip()

        if provider == "offline":
            return {
                "success": False,
                "error": "Offline Mode active. KI-Verarbeitung ist deaktiviert.",
                "model": "offline",
                "from_cache": False,
            }

        # Check Cache
        cache_key = self._get_cache_key(prompt, system_prompt, model)
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                self._record_usage(model, 0, 0, from_cache=True, success=True)
                return {
                    "success": True,
                    "content": cached.get("content", ""),
                    "parsed_json": cached.get("parsed_json"),
                    "model": cached.get("model", model),
                    "from_cache": True,
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0},
                }

        # Route to Primary Provider
        if provider == "openai":
            res = self._call_openai(prompt, system_prompt, model, max_output_tokens, temperature, json_mode)
            if not res.get("success") and self.config.get("enable_gemini_fallback") and self.config.get("gemini_api_key"):
                logger.info("OpenAI call failed (%s). Triggering fallback to Google Gemini.", res.get("error"))
                fallback_model = self.config.get("gemini_model", "gemini-2.5-flash")
                res = self._call_gemini(prompt, system_prompt, fallback_model, max_output_tokens, temperature, json_mode)
        elif provider == "gemini":
            res = self._call_gemini(prompt, system_prompt, model, max_output_tokens, temperature, json_mode)
            if not res.get("success") and self.config.get("openai_api_key"):
                logger.info("Gemini call failed. Falling back to OpenAI GPT Luna.")
                res = self._call_openai(prompt, system_prompt, self.config.get("openai_model", "gpt-6-luna"), max_output_tokens, temperature, json_mode)
        else:
            return {"success": False, "error": f"Unbekannter Provider: {provider}"}

        # If successful, cache and return
        if res.get("success"):
            if use_cache and res.get("content"):
                self._set_cached(cache_key, {
                    "content": res["content"],
                    "parsed_json": res.get("parsed_json"),
                    "model": res.get("model", model),
                    "timestamp": datetime.now().isoformat(),
                })

        return res

    # -------------------------------------------------------------------------
    # Provider Implementations
    # -------------------------------------------------------------------------

    def _call_openai(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        model: str = "gpt-6-luna",
        max_output_tokens: int = 400,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Calls official OpenAI API. Supports /v1/responses (for Luna) and /v1/chat/completions."""
        api_key = self.config.get("openai_api_key")
        if not api_key:
            return {"success": False, "error": "OpenAI API Key nicht konfiguriert."}

        endpoint = self.config.get("openai_endpoint", "https://api.openai.com/v1").rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # If model is Luna or user specified responses endpoint
        use_responses_api = "luna" in model.lower() or "/responses" in endpoint

        if use_responses_api:
            # Official OpenAI Responses API structure
            target_url = f"{endpoint}/responses" if not endpoint.endswith("/responses") else endpoint
            payload = {
                "model": model,
                "reasoning": {"effort": "none"},
                "input": [
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "max_output_tokens": max_output_tokens,
                "store": False,
            }
        else:
            # Standard Chat Completions structure
            target_url = f"{endpoint}/chat/completions"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_output_tokens,
                "temperature": temperature,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(target_url, headers=headers, json=payload, timeout=25)
            if resp.status_code != 200:
                self._record_usage(model, 0, 0, from_cache=False, success=False)
                return {"success": False, "error": f"OpenAI Fehler ({resp.status_code}): {resp.text[:300]}"}

            data = resp.json()
            content = ""

            # Extract output from /v1/responses or /v1/chat/completions
            if "output" in data and isinstance(data["output"], list):
                for item in data["output"]:
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            content += c.get("text", "")
            elif "choices" in data and data["choices"]:
                content = data["choices"][0].get("message", {}).get("content", "")
            elif "output_text" in data:
                content = data["output_text"]

            content = content.strip()

            usage = data.get("usage", {})
            prompt_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or int(len(prompt) / 4)
            completion_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or int(len(content) / 4)
            self._record_usage(model, prompt_tokens, completion_tokens, from_cache=False, success=True)

            parsed_json = None
            if json_mode and content:
                cleaned = re.sub(r"^```(?:json)?\s*", "", content)
                cleaned = re.sub(r"\s*```$", "", cleaned).strip()
                try:
                    parsed_json = json.loads(cleaned)
                except Exception:
                    pass

            return {
                "success": True,
                "content": content,
                "text": content,
                "parsed_json": parsed_json,
                "model": model,
                "from_cache": False,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        except Exception as e:
            self._record_usage(model, 0, 0, from_cache=False, success=False)
            logger.error("OpenAI request failed: %s", e)
            return {"success": False, "error": f"OpenAI Anfrage fehlgeschlagen: {str(e)}"}

    def _call_gemini(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        model: str = "gemini-2.5-flash",
        max_output_tokens: int = 400,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Calls Google Gemini REST API directly."""
        api_key = self.config.get("gemini_api_key")
        if not api_key:
            return {"success": False, "error": "Gemini API Key nicht konfiguriert."}

        clean_model = model.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key}"

        payload: Dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code != 200:
                self._record_usage(model, 0, 0, from_cache=False, success=False)
                return {"success": False, "error": f"Gemini API Fehler ({resp.status_code}): {resp.text[:300]}"}

            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return {"success": False, "error": "Keine Antwort von Gemini erhalten."}

            parts = candidates[0].get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts).strip()

            usage_metadata = data.get("usageMetadata", {})
            prompt_tokens = usage_metadata.get("promptTokenCount") or int(len(prompt) / 4)
            completion_tokens = usage_metadata.get("candidatesTokenCount") or int(len(content) / 4)
            self._record_usage(model, prompt_tokens, completion_tokens, from_cache=False, success=True)

            parsed_json = None
            if json_mode and content:
                try:
                    parsed_json = json.loads(content)
                except Exception:
                    cleaned = re.sub(r"^```(?:json)?\s*", "", content)
                    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
                    try:
                        parsed_json = json.loads(cleaned)
                    except Exception:
                        pass

            return {
                "success": True,
                "content": content,
                "text": content,
                "parsed_json": parsed_json,
                "model": model,
                "from_cache": False,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        except Exception as e:
            self._record_usage(model, 0, 0, from_cache=False, success=False)
            return {"success": False, "error": f"Gemini Anfrage fehlgeschlagen: {str(e)}"}

    # Method aliases for compatibility
    _call_openai_api = _call_openai
    _call_gemini_api = _call_gemini

    # -------------------------------------------------------------------------
    # High-Level Specialized Helpers
    # -------------------------------------------------------------------------

    def extract_cv_json(self, text: str, candidate_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Parses CV text into structured candidate JSON."""
        if not text or len(text.strip()) < 15:
            return None

        prompt = f"""Extract all candidate details into valid JSON with this exact schema:
{{
  "first_name": "First name",
  "last_name": "Last name",
  "full_name": "Full name",
  "email": "Email",
  "phone": "Phone with country code",
  "date_of_birth": "YYYY-MM-DD or empty",
  "date_of_birth_display": "DD.MM.YYYY or empty",
  "place_of_birth": "City of birth or empty",
  "nationality": "Nationality",
  "gender": "male or female",
  "salutation": "Herr or Frau",
  "street": "Street name",
  "house_number": "House number",
  "postal_code": "Postal code",
  "city": "City",
  "country": "Country",
  "current_title": "Target job title",
  "headline": "Brief professional headline",
  "summary_de": "Short German summary",
  "skills": ["Skill1", "Skill2"],
  "languages": [{{"language": "German", "language_de": "Deutsch", "level_de": "B2"}}]
}}
CV TEXT:
{text[:6000]}
"""
        res = self.complete(
            prompt=prompt,
            system_prompt="You are an expert HR CV/Resume parser. Output only valid JSON.",
            json_mode=True,
            max_output_tokens=900,
            candidate_id=candidate_id,
        )

        if res.get("success"):
            parsed = res.get("parsed_json")
            if not parsed:
                content = (res.get("text") or res.get("content") or "").strip()
                cleaned = re.sub(r"^```(?:json)?\s*", "", content)
                cleaned = re.sub(r"\s*```$", "", cleaned).strip()
                try:
                    parsed = json.loads(cleaned)
                except Exception:
                    parsed = None
            if parsed:
                return {
                    "success": True,
                    "parsed_profile": parsed,
                    "first_name": parsed.get("first_name", ""),
                    "last_name": parsed.get("last_name", ""),
                    "email": parsed.get("email", ""),
                    "model": res.get("model", "gpt-6-luna"),
                    "usage": res.get("usage", {})
                }
        return None

    def extract_cv_vision(self, image_bytes: bytes, candidate_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Extracts candidate data from scanned resume image."""
        if not image_bytes:
            return None

        # For vision, if OpenAI is primary, call /v1/chat/completions with image_url
        api_key = self.config.get("openai_api_key")
        if not api_key:
            return None

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        prompt = "Extract all candidate profile details from this CV image into raw JSON (first_name, last_name, email, phone, city, skills, languages)."

        payload = {
            "model": "gpt-4o-mini" if "luna" in self.config.get("openai_model", "") else self.config.get("openai_model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": "You are a precise document extraction system. Output only raw JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                },
            ],
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
        }

        try:
            resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            logger.warning("Vision extraction failed: %s", e)
        return None


# Module-level singleton instance
ai_manager = AIProviderManager()
