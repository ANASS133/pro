"""
ATS Keyword Tailoring & Analysis Service powered by Central AI Provider Manager
Supports official OpenAI (GPT-6 Luna, GPT-5.6 Luna) and optional Gemini / Local Heuristic fallback.

Architecture:
- Deterministic local caching (0 tokens on repeat calls)
- Dynamic applicant profile matching (no hardcoded names)
- Accurate model attribution ("local-heuristic" when offline, actual model name when AI used)
"""

import hashlib
import json
import logging
import os
from pathlib import Path
import re

from services.ai_provider_manager import ai_manager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "ats_cache.json"

# Profile directory from ai-job-autofill
PROFILES_DIR = BASE_DIR / "ai-job-autofill" / "server" / "profiles"


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
        logger.warning(f"Failed to save ATS cache: {e}")


def _get_cache_key(job_title, company_name, requirements, bullets):
    normalized = f"{job_title.lower().strip()}|{company_name.lower().strip()}|{requirements.lower().strip()}|{bullets.lower().strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def load_candidate_profile_bullets(profile_id="anass_sibbi"):
    """Load default skills & experience highlights from applicant JSON profile."""
    profile_path = PROFILES_DIR / f"{profile_id}.json"
    if not profile_path.exists():
        return [
            "Erfahrung in agiler Softwareentwicklung, Full-Stack-Webanwendungen und Schnittstellenanbindung.",
            "Sichere Implementierung relationaler Datenbanken und moderner Versionskontrolle (Git).",
            "Entwicklung performanter und wartbarer Lösungen mit hohem Qualitätsanspruch."
        ]

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        applicant = data.get("applicant", {})
        summary = applicant.get("professional_profile", {}).get("summary_de", "")
        
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


def load_candidate_info(profile_id="anass_sibbi") -> dict:
    """Dynamically load candidate full name, job title, and skills list."""
    profile_path = PROFILES_DIR / f"{profile_id}.json"
    default_info = {
        "name": "Bewerber",
        "title": "Softwareentwickler",
        "skills": ["Python", "JavaScript", "REST-APIs", "SQL", "Git", "Docker"],
        "skills_str": "Python, JavaScript, REST-APIs, SQL, Git, Docker",
        "bullets": load_candidate_profile_bullets(profile_id)
    }

    if not profile_path.exists():
        return default_info

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        applicant = data.get("applicant", {})
        personal = applicant.get("personal_information") or applicant.get("personal") or {}
        first = personal.get("first_name", "")
        last = personal.get("last_name", "")
        full_name = personal.get("full_name") or f"{first} {last}".strip() or "Bewerber"

        prof = applicant.get("professional_profile", {})
        title = prof.get("current_title", "") or "Softwareentwickler"
        raw_skills = prof.get("skills", [])
        if isinstance(raw_skills, list) and raw_skills:
            skills = [str(s).strip() for s in raw_skills if str(s).strip()]
        else:
            skills = ["Python", "JavaScript", "REST-APIs", "SQL", "Git"]

        skills_str = ", ".join(skills[:8]) if skills else "Softwareentwicklung, REST-APIs, Git"

        return {
            "name": full_name,
            "title": title,
            "skills": skills,
            "skills_str": skills_str,
            "bullets": load_candidate_profile_bullets(profile_id)
        }
    except Exception as e:
        logger.warning(f"Error loading candidate info for {profile_id}: {e}")
        return default_info


def tailor_ats_keywords(
    job_title: str,
    company_name: str,
    job_requirements: str,
    current_bullets: str = None,
    profile_id: str = "anass_sibbi"
) -> dict:
    """
    Tailor applicant experience bullet points with keywords from the target job posting.
    Uses Central AI Provider Manager (OpenAI GPT-6 Luna / Gemini / Offline).
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

    # Rule: Instant Zero-Cost Cache Hit
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

    ai_res = ai_manager.complete(
        prompt=user_prompt,
        system_prompt=developer_instruction,
        max_output_tokens=120,
        temperature=0.2
    )

    if not ai_res.get("success"):
        # Heuristic fallback
        heur_bullets = [
            f"Erfahrung im Bereich {job_title} mit Fokus auf zielorientierte Umsetzung.",
            "Schnelle Einarbeitung in projektspezifische Anforderungen und teamorientiertes Arbeiten."
        ]
        return {
            "success": True,
            "model": "local-heuristic",
            "from_cache": False,
            "job_title": job_title,
            "company_name": company_name,
            "tailored_bullets": heur_bullets,
            "raw_text": "\n".join(f"• {b}" for b in heur_bullets),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    raw_text = (ai_res.get("text") or "").strip()
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    bullets = [re.sub(r"^[•\-\*\d\.]+\s*", "", line) for line in lines]
    if not bullets:
        bullets = [raw_text]

    # Save to cache
    cache[cache_key] = {
        "bullets": bullets,
        "raw_text": raw_text,
        "job_title": job_title,
        "company_name": company_name
    }
    _save_cache(cache)

    return {
        "success": True,
        "model": ai_res.get("model", "gpt-6-luna"),
        "from_cache": ai_res.get("from_cache", False),
        "job_title": job_title,
        "company_name": company_name,
        "tailored_bullets": bullets,
        "raw_text": raw_text,
        "usage": ai_res.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0
        })
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

    user_prompt = (
        f"Schreibe genau 1 begeisternden, authentischen deutschen Eröffnungssatz für ein Anschreiben "
        f"als '{job_title}' bei '{company_name}', der direkt erklärt, warum genau dieses Unternehmen und diese Aufgaben begeistern.\n"
        f"Fokus / Kontext: {clean_requirements or 'Moderne Softwareentwicklung, Innovation, Teamgeist'}.\n"
        f"Regeln: Maximal 25 Wörter. Kein Gruß, kein 'Sehr geehrte Damen und Herren', nur genau dieser eine Satz."
    )

    ai_res = ai_manager.complete(
        prompt=user_prompt,
        system_prompt="Du bist ein meisterhafter deutscher Bewerbungscoach. Antworte extrem prägnant und direkt mit dem Satz.",
        max_output_tokens=60,
        temperature=0.3
    )

    if not ai_res.get("success"):
        hook = f"Mit großem Interesse an den technologischen Lösungen von {company_name} bewerbe ich mich hochmotiviert als {job_title}."
        return {
            "success": True,
            "model": "local-heuristic",
            "from_cache": False,
            "hook": hook,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    hook = (ai_res.get("text") or "").strip().strip('"\'')
    if not hook:
        hook = f"Mit großem Interesse an den technologischen Lösungen von {company_name} bewerbe ich mich hochmotiviert als {job_title}."

    cache[cache_key] = {"hook": hook}
    _save_cache(cache)

    return {
        "success": True,
        "model": ai_res.get("model", "gpt-6-luna"),
        "from_cache": ai_res.get("from_cache", False),
        "hook": hook,
        "usage": ai_res.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0
        })
    }


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

    user_prompt = (
        f"Analysiere die Unternehmenskultur für: Firma '{company_name}', Stelle '{job_title}'.\n"
        f"Textauszug: {clean_snippet or 'Kein Text vorhanden'}.\n"
        "Antworte NUR mit validem JSON (ohne Markdown ```): "
        '{"formality": "Sie (Formal)" oder "Du (Modern)", "vibe": "Konzern / Traditionell" oder "Modern Tech / Agil" oder "Mittelstand / Solide" oder "Startup / Locker", "icon": "🏢" oder "🚀" oder "🌿", "tone_tip": "1 kurzer deutscher Satz als Tipp für den Schreibstil."}'
    )

    ai_res = ai_manager.complete(
        prompt=user_prompt,
        system_prompt="Du bist ein Experte für deutsche Unternehmenskultur. Antworte ausschließlich mit reinem JSON.",
        max_output_tokens=90,
        temperature=0.2
    )

    if not ai_res.get("success"):
        is_startup = any(w in (clean_snippet + company_name).lower() for w in ["startup", "du ", "flache hierarchien", "agil", "team"])
        vibe_data = {
            "formality": "Du (Modern)" if is_startup else "Sie (Formal)",
            "vibe": "Modern Tech / Agil" if is_startup else "Konzern / Traditionell",
            "icon": "🚀" if is_startup else "🏢",
            "tone_tip": "Begeistert, motiviert und teamorientiert auftreten."
        }
        return {
            "success": True,
            "model": "local-heuristic",
            "from_cache": False,
            **vibe_data,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    raw_text = (ai_res.get("text") or "").strip()
    clean_json = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(clean_json)
        vibe_data = {
            "formality": parsed.get("formality", "Sie (Formal)"),
            "vibe": parsed.get("vibe", "Mittelstand / Solide"),
            "icon": parsed.get("icon", "🏢"),
            "tone_tip": parsed.get("tone_tip", "Professionelles und motiviertes Auftreten.")
        }
    except Exception:
        vibe_data = {
            "formality": "Sie (Formal)",
            "vibe": "Mittelstand / Solide",
            "icon": "🏢",
            "tone_tip": "Professionelles und motiviertes Auftreten."
        }

    cache[cache_key] = vibe_data
    _save_cache(cache)

    return {
        "success": True,
        "model": ai_res.get("model", "gpt-6-luna"),
        "from_cache": ai_res.get("from_cache", False),
        **vibe_data,
        "usage": ai_res.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0
        })
    }


def generate_ats_heatmap(company_name: str, job_title: str, requirements: str = "", profile_id: str = "anass_sibbi") -> dict:
    """Compare candidate profile dynamically against job requirements and generate ATS Heatmap pills."""
    company_name = (company_name or "Unternehmen").strip()
    job_title = (job_title or "Fachinformatiker").strip()
    clean_req = (requirements or "").strip()[:300]

    cand_info = load_candidate_info(profile_id)
    cand_name = cand_info.get("name", "Bewerber")
    cand_skills_str = cand_info.get("skills_str", "Softwareentwicklung, REST-APIs, Git")
    cand_skills_list = cand_info.get("skills", ["python", "javascript", "rest-apis", "sql", "git"])

    cache_key = f"heatmap_{hashlib.sha256(f'{cand_name}|{company_name}|{job_title}|{clean_req}'.encode()).hexdigest()[:20]}"
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

    user_prompt = (
        f"Kandidat {cand_name} (Profil: {cand_skills_str}) "
        f"bewirbt sich als '{job_title}' bei '{company_name}'.\n"
        f"Anforderungen: {clean_req or 'Softwareentwicklung, Teamgeist, moderne Webtechnologien'}.\n"
        "Antworte NUR mit validem JSON (ohne Markdown ```): "
        '{"match_percent": 85, "matched": ["Skill 1", "Skill 2", "Skill 3"], "transferable": ["Transfer 1", "Transfer 2"], "gaps": ["Gap 1"], "bridge_tip": "1 Satz Überbrückungstipp."}'
    )

    ai_res = ai_manager.complete(
        prompt=user_prompt,
        system_prompt="Du bist ein präziser ATS-Analyst. Antworte ausschließlich mit reinem JSON.",
        max_output_tokens=160,
        temperature=0.2
    )

    if not ai_res.get("success"):
        # Heuristic ATS heatmap matching based on dynamic candidate skills
        req_lower = clean_req.lower()
        matched = []
        transferable = []
        gaps = []

        for skill in cand_skills_list:
            skill_l = str(skill).lower()
            if skill_l in req_lower:
                matched.append(str(skill).upper() if len(skill) <= 4 else str(skill).capitalize())
            elif any(s in req_lower for s in ["web", "software", "programmierung", "datenbank", "entwicklung"]):
                if len(transferable) < 2:
                    transferable.append(str(skill).capitalize())

        if not matched:
            matched = [str(s).capitalize() for s in cand_skills_list[:2]]
        if not transferable:
            transferable = [str(s).capitalize() for s in cand_skills_list[2:4]]
        if "cloud" in req_lower or "aws" in req_lower:
            gaps.append("AWS Cloud")

        match_pct = min(95, max(60, 50 + len(matched) * 15))
        heatmap_data = {
            "match_percent": match_pct,
            "matched": matched,
            "transferable": transferable,
            "gaps": gaps,
            "bridge_tip": "Betone deine fundierten Grundlagen und schnelle Einarbeitung in neue Frameworks."
        }
        return {
            "success": True,
            "model": "local-heuristic",
            "from_cache": False,
            **heatmap_data,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
        }

    raw_text = (ai_res.get("text") or "").strip()
    clean_json = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(clean_json)
        heatmap_data = {
            "match_percent": int(parsed.get("match_percent", 80)),
            "matched": parsed.get("matched", []),
            "transferable": parsed.get("transferable", []),
            "gaps": parsed.get("gaps", []),
            "bridge_tip": parsed.get("bridge_tip", "Betone deine Lernbereitschaft und schnelle Einarbeitungszeit.")
        }
    except Exception:
        heatmap_data = {
            "match_percent": 80,
            "matched": [str(s).capitalize() for s in cand_skills_list[:2]],
            "transferable": [str(s).capitalize() for s in cand_skills_list[2:4]],
            "gaps": [],
            "bridge_tip": "Betone deine Lernbereitschaft und schnelle Einarbeitungszeit."
        }

    cache[cache_key] = heatmap_data
    _save_cache(cache)

    return {
        "success": True,
        "model": ai_res.get("model", "gpt-6-luna"),
        "from_cache": ai_res.get("from_cache", False),
        **heatmap_data,
        "usage": ai_res.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0
        })
    }


def batch_evaluate_ats_jobs(jobs: list, profile_id: str = "anass_sibbi") -> list:
    """
    Evaluates and ranks multiple scraped jobs by ATS keyword match score.
    Returns jobs list sorted in descending order of match_percent.
    """
    evaluated = []
    for j in jobs:
        company = j.get("company") or j.get("Unternehmen") or "Unternehmen"
        title = j.get("title") or j.get("Beruf") or "Fachinformatiker"
        reqs = j.get("requirements") or j.get("description") or ""

        analysis = generate_ats_heatmap(company, title, reqs, profile_id=profile_id)
        job_copy = dict(j)
        job_copy["ats_analysis"] = analysis
        job_copy["ats_score"] = analysis.get("match_percent", 50)
        evaluated.append(job_copy)

    # Sort descending by ATS score
    evaluated.sort(key=lambda x: x.get("ats_score", 0), reverse=True)
    return evaluated
