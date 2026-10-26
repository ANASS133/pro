"""
Intelligent CV / Resume Parser for automatic candidate profile ingestion.
Extracts text from uploaded PDF resumes and structures contact info, skills, experience, and education.
"""

import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pypdf import PdfReader

logger = logging.getLogger(__name__)

COMMON_SKILLS = [
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "PHP", "Go", "Rust", "Ruby", "Swift", "Kotlin",
    "React", "Vue", "Angular", "Next.js", "Node.js", "Express", "Flask", "Django", "FastAPI", "Spring Boot",
    "HTML", "CSS", "Tailwind", "Bootstrap", "Sass", "REST", "GraphQL", "SOAP", "API",
    "PostgreSQL", "MySQL", "MongoDB", "SQLite", "Redis", "Oracle",
    "Git", "GitHub", "GitLab", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Linux", "CI/CD",
    "Selenium", "Playwright", "Puppeteer", "BeautifulSoup", "Scrapy",
    "Agile", "Scrum", "Jira", "Confluence"
]

COMMON_LANGUAGES = {
    "deutsch": ("Deutsch", "German"),
    "englisch": ("Englisch", "English"),
    "english": ("Englisch", "English"),
    "französisch": ("Französisch", "French"),
    "french": ("Französisch", "French"),
    "arabisch": ("Arabisch", "Arabic"),
    "arabic": ("Arabisch", "Arabic"),
    "spanisch": ("Spanisch", "Spanish"),
    "spanish": ("Spanisch", "Spanish"),
    "russisch": ("Russisch", "Russian"),
    "türkisch": ("Türkisch", "Turkish")
}


class CVParser:
    @staticmethod
    def extract_text_from_pdf(pdf_bytes_or_path) -> str:
        """Extract clean text content from a PDF document."""
        if isinstance(pdf_bytes_or_path, (str, Path)):
            reader = PdfReader(str(pdf_bytes_or_path))
        else:
            reader = PdfReader(io.BytesIO(pdf_bytes_or_path))

        text_pages = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text_pages.append(extracted)
        return "\n".join(text_pages).strip()

    @classmethod
    def parse_cv_text(cls, text: str) -> Dict[str, Any]:
        """Heuristically extracts candidate data fields from CV text."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # 1. Email extraction
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
        email = email_match.group(0) if email_match else ""

        # 2. Phone extraction (German / Int'l)
        phone_match = re.search(r"(?:\+49|0049|0)[1-9][0-9\s/.-]{7,15}", text)
        phone = re.sub(r"\s+", " ", phone_match.group(0)).strip() if phone_match else ""

        # 3. Name extraction (check first 8 non-empty lines)
        full_name = ""
        for line in lines[:8]:
            cleaned_line = re.sub(r"^(?:lebenslauf|curriculum\s+vitae|resume|bewerbung|cv)\s*[-|:–—von\s]*", "", line, flags=re.IGNORECASE).strip()
            if not cleaned_line:
                continue
            if "@" in cleaned_line or any(c in cleaned_line for c in "+0123456789"):
                continue
            words = cleaned_line.split()
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha()):
                full_name = cleaned_line
                break

        first_name = full_name.split()[0] if full_name else "Bewerber"
        last_name = " ".join(full_name.split()[1:]) if full_name and len(full_name.split()) > 1 else ""

        # 4. City / Address extraction
        city_match = re.search(r"\b([0-9]{5})[ \t]+([A-ZÄÖÜ][a-zäöüß]+)\b", text)
        postal_code = city_match.group(1) if city_match else ""
        city = city_match.group(2) if city_match else ""

        # 5. Skills extraction
        detected_skills = []
        text_lower = text.lower()
        for skill in COMMON_SKILLS:
            pattern = rf"\b{re.escape(skill.lower())}\b"
            if re.search(pattern, text_lower):
                detected_skills.append(skill)

        # 6. Languages extraction
        detected_languages = []
        for kw, (de_name, en_name) in COMMON_LANGUAGES.items():
            if kw in text_lower:
                level = "B2/C1" if "fließend" in text_lower or "verhandlungssicher" in text_lower else "Gut"
                if "muttersprache" in text_lower or "native" in text_lower:
                    level = "Muttersprache"
                detected_languages.append({
                    "language": en_name,
                    "language_de": de_name,
                    "level_de": level
                })

        return {
            "personal": {
                "first_name": first_name,
                "last_name": last_name,
                "full_name": full_name or f"{first_name} {last_name}".strip(),
                "salutation": "Herr" if "herr" in text_lower else "Frau" if "frau" in text_lower else "Herr"
            },
            "contact": {
                "email": email,
                "phone": phone,
                "phone_display": phone,
                "address": {
                    "postal_code": postal_code,
                    "city": city,
                    "country": "Deutschland"
                }
            },
            "skills": {
                "technologies_from_cv": detected_skills,
                "programming_languages": [s for s in detected_skills if s in ["Python", "JavaScript", "TypeScript", "Java", "C++", "PHP", "Go", "Rust", "SQL"]],
                "frontend": [s for s in detected_skills if s in ["React", "Vue", "Angular", "HTML", "CSS", "Tailwind"]],
                "backend": [s for s in detected_skills if s in ["Node.js", "Express", "Flask", "Django", "FastAPI", "Spring Boot", "REST"]],
                "tools": [s for s in detected_skills if s in ["Git", "GitHub", "Docker", "Linux", "Kubernetes", "Selenium"]]
            },
            "languages": detected_languages or [
                {"language": "German", "language_de": "Deutsch", "level_de": "Fließend"}
            ]
        }

    @classmethod
    def update_profile_from_cv(cls, profile_path: Path, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge parsed CV data into candidate profile JSON."""
        existing = {}
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        applicant = existing.setdefault("applicant", {})

        # Merge personal
        personal = applicant.setdefault("personal", {})
        for k, v in parsed_data["personal"].items():
            if v and (not personal.get(k) or personal.get(k) in ["Firstname", "Lastname", "Firstname Lastname"]):
                personal[k] = v

        # Merge contact
        contact = applicant.setdefault("contact", {})
        if parsed_data["contact"]["email"] and (not contact.get("email") or "example.com" in contact.get("email", "")):
            contact["email"] = parsed_data["contact"]["email"]
        if parsed_data["contact"]["phone"]:
            contact["phone"] = parsed_data["contact"]["phone"]
            contact["phone_display"] = parsed_data["contact"]["phone_display"]

        addr = contact.setdefault("address", {})
        if parsed_data["contact"]["address"]["city"]:
            addr["city"] = parsed_data["contact"]["address"]["city"]
        if parsed_data["contact"]["address"]["postal_code"]:
            addr["postal_code"] = parsed_data["contact"]["address"]["postal_code"]

        # Merge skills
        skills = applicant.setdefault("skills", {})
        existing_techs = set(skills.get("technologies_from_cv", []))
        new_techs = set(parsed_data["skills"]["technologies_from_cv"])
        skills["technologies_from_cv"] = sorted(list(existing_techs | new_techs))

        # Save back
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        return existing
