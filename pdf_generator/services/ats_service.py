"""
ATS Keyword Tailoring Service powered by GPT Luna (gpt-5.6-luna)
Strict zero-waste & cost-minimization architecture:
- Deterministic local caching (0 tokens on repeat calls)
- Strict token budgeting (max 300 chars input, max 120 output tokens)
- On-demand execution only (triggered by user button click)
"""

import hashlib
import json
import os
from pathlib import Path
import re
import requests

LUNA_INPUT_PRICE_PER_M = 0.15
LUNA_OUTPUT_PRICE_PER_M = 0.60

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "ats_cache.json"

# Profile directory from ai-job-autofill
PROFILES_DIR = BASE_DIR / "ai-job-autofill" / "server" / "profiles"


def _get_api_key():
    """Retrieve OpenAI API key from environment or .env files."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return api_key

    # Check ai-job-autofill/server/.env
    server_env = BASE_DIR / "ai-job-autofill" / "server" / ".env"
    if server_env.exists():
        try:
            with open(server_env, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENAI_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass

    # Check root .env
    root_env = BASE_DIR / ".env"
    if root_env.exists():
        try:
            with open(root_env, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENAI_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass

    return None


def _load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache_data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save ATS cache: {e}")


def _get_cache_key(job_title, company_name, requirements, bullets):
    normalized = f"{job_title.lower().strip()}|{company_name.lower().strip()}|{requirements.lower().strip()}|{bullets.lower().strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def load_candidate_profile_bullets(profile_id="anass_sibbi"):
    """Load default skills & experience highlights from applicant JSON profile."""
    profile_path = PROFILES_DIR / f"{profile_id}.json"
    if not profile_path.exists():
        # Fallback to default
        return [
            "Praktische Erfahrung in Full-Stack-Webentwicklung mit React, Spring Boot und RESTful APIs.",
            "Sichere Implementierung relationaler Datenbanken (PostgreSQL/MySQL) und moderner Git-Workflows.",
            "Entwicklung mobiler und webbasierter Verwaltungslösungen mit hohem Fokus auf Performance und Codequalität."
        ]

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        applicant = data.get("applicant", {})
        summary = applicant.get("professional_profile", {}).get("summary_de", "")
        skills = applicant.get("professional_profile", {}).get("skills", [])
        
        bullets = []
        if summary:
            bullets.append(summary)
        
        work_exp = applicant.get("work_experience", [])
        for exp in work_exp[:2]:
            title = exp.get("job_title", "")
            resp = exp.get("responsibilities", [])
            if resp:
                bullets.append(f"{title}: {resp[0]}")
            elif exp.get("description"):
                bullets.append(f"{title}: {exp.get('description')[:120]}")

        return bullets if bullets else [
            "Erfahrung in agiler Softwareentwicklung, Full-Stack-Webanwendungen und Schnittstellenanbindung."
        ]
    except Exception:
        return [
            "Erfahrung in moderner Full-Stack-Softwareentwicklung und REST-APIs."
        ]


def tailor_ats_keywords(
    job_title: str,
    company_name: str,
    job_requirements: str,
    current_bullets: str = None,
    profile_id: str = "anass_sibbi"
) -> dict:
    """
    Tailor applicant experience bullet points with keywords from the target job posting.
    Uses GPT Luna with zero-cost cache hit detection and token guard rails.
    """
    job_title = (job_title or "Fachinformatiker für Anwendungsentwicklung").strip()
    company_name = (company_name or "Unternehmen").strip()
    
    # Clean & truncate input requirements to save input tokens (max 300 chars)
    clean_requirements = (job_requirements or "").strip()[:300]
    
    # If no candidate bullets provided, load from profile
    if not current_bullets or not current_bullets.strip():
        bullets_list = load_candidate_profile_bullets(profile_id)
        current_bullets = "\n".join(f"• {b}" for b in bullets_list)
    else:
        current_bullets = current_bullets.strip()[:400]

    cache_key = _get_cache_key(job_title, company_name, clean_requirements, current_bullets)
    cache = _load_cache()

    # Rule 4: Instant Zero-Cost Cache Hit
    if cache_key in cache:
        cached_entry = cache[cache_key]
        return {
            "success": True,
            "model": "cache-hit",
            "from_cache": True,
            "job_title": job_title,
            "company_name": company_name,
            "tailored_bullets": cached_entry.get("bullets", []),
            "raw_text": cached_entry.get("raw_text", ""),
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0
            }
        }

    api_key = _get_api_key()
    if not api_key:
        return {
            "success": False,
            "error": "OpenAI API Key nicht gefunden in Umgebungsvariablen oder .env"
        }

    # Compact micro-prompt to minimize tokens
    developer_instruction = (
        "Du bist ein präziser deutscher Karriere- & ATS-Optimierer. "
        "Formuliere Erfahrungen so um, dass geforderte Schlüsselbegriffe natürlich enthalten sind. "
        "Erfinde keine falschen Qualifikationen. Antworte extrem kurz."
    )

    user_prompt = (
        f"Ziel: ATS-Optimierung für Bewerbung als '{job_title}' bei '{company_name}'.\n"
        f"Geforderte Keywords / Aufgaben: {clean_requirements or 'Softwareentwicklung, Teamfähigkeit, Problemlösungskompetenz'}\n"
        f"Bisherige Stichpunkte des Bewerbers:\n{current_bullets}\n\n"
        "Aufgabe: Formuliere genau 2 bis maximal 3 prägnante Aufzählungspunkte (jeweils beginnend mit '• ') "
        "für das Anschreiben oder den Lebenslauf, die diese Anforderungen direkt adressieren.\n"
        "Maximal 50 Wörter insgesamt. Kein Gruß, keine Erklärung, nur die Stichpunkte."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-5.6-luna",
        "reasoning": {"effort": "none"},
        "input": [
            {"role": "developer", "content": developer_instruction},
            {"role": "user", "content": user_prompt}
        ],
        "max_output_tokens": 120,
        "store": False
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
            timeout=12
        )

        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"OpenAI API Fehler ({resp.status_code}): {resp.text[:200]}"
            }

        data = resp.json()

        # Extract text from Responses API output structure
        raw_text = ""
        output_items = data.get("output", [])
        if output_items and isinstance(output_items, list):
            for item in output_items:
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        raw_text += content.get("text", "")

        raw_text = raw_text.strip()
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        bullets = [re.sub(r"^[•\-\*\d\.]+\s*", "", line) for line in lines]

        # Calculate exact cost
        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        cost_usd = ((prompt_tokens / 1_000_000) * LUNA_INPUT_PRICE_PER_M) + \
                   ((completion_tokens / 1_000_000) * LUNA_OUTPUT_PRICE_PER_M)

        # Save to cache for $0.00 repeat calls
        cache[cache_key] = {
            "bullets": bullets,
            "raw_text": raw_text,
            "job_title": job_title,
            "company_name": company_name
        }
        _save_cache(cache)

        return {
            "success": True,
            "model": "gpt-5.6-luna",
            "from_cache": False,
            "job_title": job_title,
            "company_name": company_name,
            "tailored_bullets": bullets,
            "raw_text": raw_text,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": round(cost_usd, 6)
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Netzwerk- oder API-Fehler: {str(e)}"
        }


def generate_golden_hook(
    company_name: str,
    job_title: str,
    job_requirements: str = "",
    profile_id: str = "anass_sibbi"
) -> dict:
    """Generate 1 sparkling German opening hook for the cover letter."""
    company_name = (company_name or "Unternehmen").strip()
    job_title = (job_title or "Fachinformatiker für Anwendungsentwicklung").strip()
    clean_requirements = (job_requirements or "").strip()[:250]

    cache_key = f"hook_{hashlib.sha256(f'{company_name}|{job_title}|{clean_requirements}'.encode()).hexdigest()[:20]}"
    cache = _load_cache()

    if cache_key in cache:
        entry = cache[cache_key]
        return {
            "success": True,
            "model": "cache-hit",
            "from_cache": True,
            "hook": entry.get("hook", ""),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    api_key = _get_api_key()
    if not api_key:
        return {"success": False, "error": "OpenAI API Key nicht gefunden."}

    user_prompt = (
        f"Schreibe genau 1 begeisternden, authentischen deutschen Eröffnungssatz für ein Anschreiben "
        f"als '{job_title}' bei '{company_name}', der direkt erklärt, warum genau dieses Unternehmen und diese Aufgaben begeistern.\n"
        f"Fokus / Kontext: {clean_requirements or 'Moderne Softwareentwicklung, Innovation, Teamgeist'}.\n"
        f"Regeln: Maximal 25 Wörter. Kein Gruß, kein 'Sehr geehrte Damen und Herren', nur genau dieser eine Satz."
    )

    payload = {
        "model": "gpt-5.6-luna",
        "reasoning": {"effort": "none"},
        "input": [
            {"role": "developer", "content": "Du bist ein meisterhafter deutscher Bewerbungscoach. Antworte extrem prägnant und direkt mit dem Satz."},
            {"role": "user", "content": user_prompt}
        ],
        "max_output_tokens": 60,
        "store": False
    }

    try:
        resp = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, timeout=10)
        if resp.status_code != 200:
            return {"success": False, "error": f"API Fehler ({resp.status_code})"}
        data = resp.json()
        raw_text = ""
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    raw_text += c.get("text", "")
        hook = raw_text.strip().strip('"\'')
        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        cost_usd = ((prompt_tokens / 1_000_000) * LUNA_INPUT_PRICE_PER_M) + ((completion_tokens / 1_000_000) * LUNA_OUTPUT_PRICE_PER_M)

        cache[cache_key] = {"hook": hook}
        _save_cache(cache)

        return {
            "success": True,
            "model": "gpt-5.6-luna",
            "from_cache": False,
            "hook": hook,
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens, "estimated_cost_usd": round(cost_usd, 6)}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def detect_culture_vibe(company_name: str, job_title: str, snippet: str = "") -> dict:
    """Analyze job posting culture: Du vs. Sie, Formality, and Tone recommendation."""
    company_name = (company_name or "Unternehmen").strip()
    job_title = (job_title or "Fachinformatiker").strip()
    clean_snippet = (snippet or "").strip()[:300]

    cache_key = f"vibe_{hashlib.sha256(f'{company_name}|{job_title}|{clean_snippet}'.encode()).hexdigest()[:20]}"
    cache = _load_cache()

    if cache_key in cache:
        entry = cache[cache_key]
        return {
            "success": True,
            "model": "cache-hit",
            "from_cache": True,
            **entry,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    api_key = _get_api_key()
    if not api_key:
        return {"success": False, "error": "OpenAI API Key nicht gefunden."}

    user_prompt = (
        f"Analysiere die Unternehmenskultur für: Firma '{company_name}', Stelle '{job_title}'.\n"
        f"Textauszug: {clean_snippet or 'Kein Text vorhanden'}.\n"
        "Antworte NUR mit validem JSON (ohne Markdown ```): "
        '{"formality": "Sie (Formal)" oder "Du (Modern)", "vibe": "Konzern / Traditionell" oder "Modern Tech / Agil" oder "Mittelstand / Solide" oder "Startup / Locker", "icon": "🏢" oder "🚀" oder "🌿", "tone_tip": "1 kurzer deutscher Satz als Tipp für den Schreibstil."}'
    )

    payload = {
        "model": "gpt-5.6-luna",
        "reasoning": {"effort": "none"},
        "input": [
            {"role": "developer", "content": "Du bist ein Experte für deutsche Unternehmenskultur. Antworte ausschließlich mit reinem JSON."},
            {"role": "user", "content": user_prompt}
        ],
        "max_output_tokens": 90,
        "store": False
    }

    try:
        resp = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, timeout=10)
        if resp.status_code != 200:
            return {"success": False, "error": f"API Fehler ({resp.status_code})"}
        data = resp.json()
        raw_text = ""
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    raw_text += c.get("text", "")
        clean_json = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(clean_json)

        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        cost_usd = ((prompt_tokens / 1_000_000) * LUNA_INPUT_PRICE_PER_M) + ((completion_tokens / 1_000_000) * LUNA_OUTPUT_PRICE_PER_M)

        vibe_data = {
            "formality": parsed.get("formality", "Sie (Formal)"),
            "vibe": parsed.get("vibe", "Mittelstand / Solide"),
            "icon": parsed.get("icon", "🏢"),
            "tone_tip": parsed.get("tone_tip", "Professionelles und motiviertes Auftreten.")
        }
        cache[cache_key] = vibe_data
        _save_cache(cache)

        return {
            "success": True,
            "model": "gpt-5.6-luna",
            "from_cache": False,
            **vibe_data,
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens, "estimated_cost_usd": round(cost_usd, 6)}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_ats_heatmap(company_name: str, job_title: str, requirements: str = "", profile_id: str = "anass_sibbi") -> dict:
    """Compare candidate profile against job requirements and generate ATS Heatmap pills."""
    company_name = (company_name or "Unternehmen").strip()
    job_title = (job_title or "Fachinformatiker").strip()
    clean_req = (requirements or "").strip()[:300]

    cache_key = f"heatmap_{hashlib.sha256(f'{company_name}|{job_title}|{clean_req}'.encode()).hexdigest()[:20]}"
    cache = _load_cache()

    if cache_key in cache:
        entry = cache[cache_key]
        return {
            "success": True,
            "model": "cache-hit",
            "from_cache": True,
            **entry,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    api_key = _get_api_key()
    if not api_key:
        return {"success": False, "error": "OpenAI API Key nicht gefunden."}

    user_prompt = (
        f"Kandidat Anass Sibbi (Softwareentwickler, Python, React, Spring Boot, Flutter, REST APIs, PostgreSQL, Git) "
        f"bewirbt sich als '{job_title}' bei '{company_name}'.\n"
        f"Anforderungen: {clean_req or 'Softwareentwicklung, Teamgeist, moderne Webtechnologien'}.\n"
        "Antworte NUR mit validem JSON (ohne Markdown ```): "
        '{"match_percent": 85, "matched": ["Skill 1", "Skill 2", "Skill 3"], "transferable": ["Transfer 1", "Transfer 2"], "gaps": ["Gap 1"], "bridge_tip": "1 Satz Überbrückungstipp."}'
    )

    payload = {
        "model": "gpt-5.6-luna",
        "reasoning": {"effort": "none"},
        "input": [
            {"role": "developer", "content": "Du bist ein präziser ATS-Analyst. Antworte ausschließlich mit reinem JSON."},
            {"role": "user", "content": user_prompt}
        ],
        "max_output_tokens": 160,
        "store": False
    }

    try:
        resp = requests.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, timeout=12)
        if resp.status_code != 200:
            return {"success": False, "error": f"API Fehler ({resp.status_code})"}
        data = resp.json()
        raw_text = ""
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    raw_text += c.get("text", "")
        clean_json = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(clean_json)

        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        cost_usd = ((prompt_tokens / 1_000_000) * LUNA_INPUT_PRICE_PER_M) + ((completion_tokens / 1_000_000) * LUNA_OUTPUT_PRICE_PER_M)

        heatmap_data = {
            "match_percent": int(parsed.get("match_percent", 80)),
            "matched": parsed.get("matched", []),
            "transferable": parsed.get("transferable", []),
            "gaps": parsed.get("gaps", []),
            "bridge_tip": parsed.get("bridge_tip", "Betone deine Lernbereitschaft und schnelle Einarbeitungszeit.")
        }
        cache[cache_key] = heatmap_data
        _save_cache(cache)

        return {
            "success": True,
            "model": "gpt-5.6-luna",
            "from_cache": False,
            **heatmap_data,
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens, "estimated_cost_usd": round(cost_usd, 6)}
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
