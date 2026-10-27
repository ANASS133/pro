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
        """
        Robustly extract text content from a PDF document.
        Tolerates truncated streams, malformed stream dictionaries,
        missing EOF markers, and corrupted objects without crashing.
        """
        if isinstance(pdf_bytes_or_path, (str, Path)):
            try:
                with open(pdf_bytes_or_path, "rb") as f:
                    pdf_bytes = f.read()
            except Exception as e:
                logger.warning("Could not read PDF from path %s: %s", pdf_bytes_or_path, e)
                return ""
        else:
            pdf_bytes = bytes(pdf_bytes_or_path)

        if not pdf_bytes:
            return ""

        text_pages: List[str] = []

        # -------------------------------------------------------------
        # Tier 1: Standard pypdf extraction with strict=False & per-page isolation
        # -------------------------------------------------------------
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
            for page in reader.pages:
                try:
                    extracted = page.extract_text()
                    if extracted and extracted.strip():
                        text_pages.append(extracted.strip())
                except Exception as page_err:
                    logger.debug("Page text extraction failed (skipping page): %s", page_err)
        except Exception as reader_err:
            logger.debug("Standard PdfReader failed: %s", reader_err)

        if text_pages:
            return "\n".join(text_pages).strip()

        # -------------------------------------------------------------
        # Tier 2: Stream Repair (missing EOF / unclosed stream objects)
        # -------------------------------------------------------------
        try:
            repaired_bytes = pdf_bytes + b"\nendstream\nendobj\nstartxref\n0\n%%EOF\n"
            reader = PdfReader(io.BytesIO(repaired_bytes), strict=False)
            for page in reader.pages:
                try:
                    extracted = page.extract_text()
                    if extracted and extracted.strip():
                        text_pages.append(extracted.strip())
                except Exception:
                    pass
        except Exception:
            pass

        if text_pages:
            return "\n".join(text_pages).strip()

        # -------------------------------------------------------------
        # Tier 3: Direct Raw Stream & Text Operator Recovery
        # Extracts text tokens from uncompressed & partially decompressed zlib streams
        # -------------------------------------------------------------
        recovered_tokens: List[str] = []
        try:
            import zlib
            # 1. Direct regex scan for uncompressed text in (...) Tj or [...] TJ
            for m in re.findall(rb'\(([^()]{2,120})\)\s*Tj', pdf_bytes):
                try:
                    decoded = m.decode("utf-8", errors="ignore").strip()
                    if decoded and not decoded.startswith("/"):
                        recovered_tokens.append(decoded)
                except Exception:
                    pass

            for array in re.findall(rb'\[(.*?)\]\s*TJ', pdf_bytes, re.DOTALL):
                parts = [p.decode("utf-8", errors="ignore") for p in re.findall(rb'\(([^()]+)\)', array)]
                joined = "".join(parts).strip()
                if joined:
                    recovered_tokens.append(joined)

            # 2. Extract and decompress stream blocks (even if truncated or malformed)
            stream_matches = re.finditer(rb'stream[\r\n]+(.*?)[\r\n]*(?:endstream|\Z)', pdf_bytes, re.DOTALL)
            for sm in stream_matches:
                raw_chunk = sm.group(1)
                decompressed = b""
                try:
                    decompressed = zlib.decompress(raw_chunk)
                except Exception:
                    try:
                        # Decompress as much as possible before stream end
                        d = zlib.decompressobj()
                        decompressed = d.decompress(raw_chunk)
                    except Exception:
                        pass

                if decompressed:
                    for m in re.findall(rb'\(([^()]{2,120})\)\s*Tj', decompressed):
                        decoded = m.decode("utf-8", errors="ignore").strip()
                        if decoded and not decoded.startswith("/"):
                            recovered_tokens.append(decoded)
                    for array in re.findall(rb'\[(.*?)\]\s*TJ', decompressed, re.DOTALL):
                        parts = [p.decode("utf-8", errors="ignore") for p in re.findall(rb'\(([^()]+)\)', array)]
                        joined = "".join(parts).strip()
                        if joined:
                            recovered_tokens.append(joined)

            # 3. Direct regex scan for email and candidate patterns in raw bytes
            email_match = re.search(rb'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', pdf_bytes)
            if email_match:
                recovered_tokens.append(email_match.group(0).decode("utf-8", errors="ignore"))

            if recovered_tokens:
                clean_lines = []
                seen_tokens = set()
                for tok in recovered_tokens:
                    if tok not in seen_tokens:
                        seen_tokens.add(tok)
                        clean_lines.append(tok)
                return "\n".join(clean_lines).strip()
        except Exception as tier3_err:
            logger.debug("Tier 3 recovery error: %s", tier3_err)

        return ""

    @classmethod
    def parse_cv_text(cls, text: str) -> Dict[str, Any]:
        """
        Heuristically extracts comprehensive candidate profile fields from CV text:
        - Personal (first_name, last_name, full_name, date_of_birth, place_of_birth, nationality, salutation, gender)
        - Contact & Address (email, phone, street, house_number, postal_code, city, country, country_code, linkedin, github, portfolio)
        - Professional Profile (current_title, headline, summary_de, primary_fields)
        - Skills & Languages
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text_lower = text.lower()

        # 1. Email extraction
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
        email = email_match.group(0) if email_match else ""

        # 2. Phone extraction (German / Int'l)
        phone = ""
        for m in re.finditer(r"(\+?[0-9][0-9\s/().-]{7,25})", text):
            cand = m.group(1).strip().rstrip(".,;)-")
            digits = re.sub(r"\D", "", cand)
            if 8 <= len(digits) <= 15 and (cand.startswith("+") or cand.startswith("00") or (cand.startswith("0") and not re.search(r"\.\d{2,4}", cand))):
                if not re.search(r"\.\d{4}", cand):  # Avoid dates
                    phone = re.sub(r"\s+", " ", cand).strip()
                    break

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

        # 4. Date of Birth & Place of Birth
        date_of_birth_iso = ""
        date_of_birth_display = ""
        dob_match = re.search(
            r"(?i)(?:geburtsdatum|geboren\s+am|geb\.|date\s+of\s+birth|dob)\s*[:.]?\s*(\d{1,2}[\.\/\-]\d{1,2}[\.\/\-]\d{2,4}|\d{4}[\-\/\.]\d{1,2}[\-\/\.]\d{1,2})",
            text
        )
        if dob_match:
            raw_dob = dob_match.group(1).strip()
            dob_parts = re.split(r"[\.\/\-]", raw_dob)
            if len(dob_parts) == 3:
                try:
                    if len(dob_parts[0]) == 4:  # YYYY-MM-DD
                        y, mth, d = int(dob_parts[0]), int(dob_parts[1]), int(dob_parts[2])
                    else:  # DD.MM.YYYY
                        d, mth, y = int(dob_parts[0]), int(dob_parts[1]), int(dob_parts[2])
                        if y < 100:
                            y = 1900 + y if y > 30 else 2000 + y
                    if 1940 <= y <= 2025 and 1 <= mth <= 12 and 1 <= d <= 31:
                        date_of_birth_iso = f"{y:04d}-{mth:02d}-{d:02d}"
                        date_of_birth_display = f"{d:02d}.{mth:02d}.{y:04d}"
                except Exception:
                    pass

        place_of_birth = ""
        pob_match = re.search(
            r"(?i)(?:geburtsort|geboren\s+in|place\s+of\s+birth)\s*[:.]?\s*([A-ZÄÖÜ][a-zäöüß]+)",
            text
        )
        if not pob_match:
            pob_match = re.search(r"(?i)geboren\s+(?:am\s+\S+\s+)?in\s+([A-ZÄÖÜ][a-zäöüß]+)", text)
        if pob_match:
            place_of_birth = pob_match.group(1).strip()

        # 5. Nationality
        nationality = ""
        nat_match = re.search(
            r"(?i)(?:staatsangeh(?:[öo]|oe)rigkeit|nationalit(?:[äa]|ae)t|nationality|citizenship)\s*[:.]?\s*([A-Za-zäöüÄÖÜß\/\-]+)",
            text
        )
        if nat_match:
            nationality = nat_match.group(1).strip().capitalize()

        # 6. Salutation & Gender
        salutation = "Herr"
        gender = "male"
        female_indicators = [
            "frau", "weiblich", "female", "ms.", "mrs.",
            "entwicklerin", "informatikerin", "kauffrau", "ingenieurin",
            "beraterin", "absolventin", "studentin", "azubine", "assistentin"
        ]
        if any(kw in text_lower for kw in female_indicators):
            salutation = "Frau"
            gender = "female"
        elif any(kw in text_lower for kw in ["divers", "nicht-binär", "non-binary"]):
            salutation = "Divers"
            gender = "other"

        # 7. Street & House Number
        street = ""
        house_number = ""
        street_match = re.search(
            r"(?i)\b([A-ZÄÖÜ][a-zäöüß]+(?:[ \t]+[A-ZÄÖÜ][a-zäöüß]+)*(?:straße|strasse|str\.|weg|allee|platz|ring|damm|gasse|pfad|chaussee|ufer|park)?)[ \t]+(\d+[a-zA-Z]?(?:[ \t]*[\/\-][ \t]*\d+[a-zA-Z]?)?)\b",
            text
        )
        if street_match:
            cand_street = street_match.group(1).strip()
            # Filter out non-street false positives (e.g., Tel 1234, PLZ 50667)
            if not any(cand_street.lower().startswith(ex) for ex in ["tel", "mobil", "telefon", "plz", "fax", "seite", "page"]):
                street = cand_street
                house_number = street_match.group(2).strip()

        # 8. City / Postal Code extraction
        postal_code = ""
        city = ""
        city_match = re.search(r"\b(?:D-)?([0-9]{5})[ \t]+([A-ZÄÖÜ][^\r\n,;]+)", text)
        if city_match:
            postal_code = city_match.group(1).strip()
            city = city_match.group(2).strip()

        # 9. LinkedIn, GitHub, and Portfolio URLs
        linkedin_url = ""
        li_m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_\-%]+)", text, re.IGNORECASE)
        if li_m:
            linkedin_url = f"https://linkedin.com/in/{li_m.group(1)}"

        github_url = ""
        gh_m = re.search(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_\-%]+)", text, re.IGNORECASE)
        if gh_m:
            github_url = f"https://github.com/{gh_m.group(1)}"

        portfolio_url = ""
        urls = re.findall(r"https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?", text)
        for u in urls:
            u_clean = u.rstrip(".,;)")
            u_lower = u_clean.lower()
            if not any(ex in u_lower for ex in ["linkedin.com", "github.com", "google.com", "schema.org", "w3.org"]):
                portfolio_url = u_clean
                break

        # 10. Skills extraction
        detected_skills = []
        for skill in COMMON_SKILLS:
            pattern = rf"\b{re.escape(skill.lower())}\b"
            if re.search(pattern, text_lower):
                detected_skills.append(skill)

        # 11. Current Job Title / Role
        current_title = ""
        # Check explicit label first
        title_label_match = re.search(
            r"(?i)(?:angestrebte\s+stelle|angestrebte\s+position|berufsbezeichnung|beruf|position|rolle|job\s*title|role|current\s*title)\s*[:.]?\s*([^\n\r,;]{3,60})",
            text
        )
        if title_label_match:
            val = title_label_match.group(1).strip()
            if len(val) > 3 and not any(w in val.lower() for w in ["lebenslauf", "cv", "bewerbung"]):
                current_title = val

        if not current_title:
            # Check lines under candidate name in top 8 lines
            role_keywords = [
                "entwickler", "developer", "informatiker", "software", "frontend", "backend", "fullstack",
                "full-stack", "engineer", "ingenieur", "data", "cloud", "devops", "administrator",
                "ausbildung", "auszubildende", "azubi", "praktikant", "kaufmann", "kauffrau", "designer",
                "architect", "consultant", "manager", "fachkraft", "techniker"
            ]
            for l in lines[:8]:
                cl = l.strip()
                if not cl or "@" in cl or any(c in cl for c in "+0123456789"):
                    continue
                if any(kw in cl.lower() for kw in role_keywords):
                    current_title = cl
                    break

        if not current_title:
            current_title = "Softwareentwickler" if "python" in text_lower or "javascript" in text_lower else "Bewerber"

        # 12. Application Headline
        headline = f"{full_name} | {current_title}" if full_name else current_title

        # 13. Profile Summary (extracted or generated)
        summary_de = ""
        summary_match = re.search(
            r"(?i)(?:profil|über\s+mich|ueber\s+mich|kurzprofil|persönliches\s+profil|summary|about\s+me|professional\s+summary)\s*[:\n]+([^\n\r]+(?:\n[^\n\r]+){0,3})",
            text
        )
        if summary_match:
            summary_candidate = summary_match.group(1).strip()
            if len(summary_candidate) > 20 and not re.search(r"(?i)^(?:berufserfahrung|ausbildung|kenntnisse|skills|sprachen)", summary_candidate):
                summary_de = " ".join(summary_candidate.split())

        if not summary_de:
            if detected_skills:
                summary_de = f"Engagierter {current_title} mit praktischen Schwerpunkten in {', '.join(detected_skills[:5])}."
            else:
                summary_de = f"Motivierter Kandidat ({current_title}) auf der Suche nach neuen beruflichen Herausforderungen."

        # 14. Primary fields (top 4-6 skills or disciplines)
        primary_fields = detected_skills[:6] if detected_skills else ["Softwareentwicklung", "Webentwicklung"]

        # 15. Languages extraction
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

        # --- AI Extraction Fallback (Official OpenAI GPT Luna / Central AI Manager) ---
        # When rule-based regex leaves core candidate identity fields missing or generic
        needs_ai = (
            not full_name or full_name.lower() in ["bewerber", "kandidat"]
            or not email
            or not phone
            or not city
            or not date_of_birth_iso
        )
        if needs_ai:
            ai_data = cls.extract_with_ai(text)
            if ai_data:
                if ai_data.get("full_name") and ai_data["full_name"].lower() not in ["bewerber", "kandidat"]:
                    full_name = ai_data["full_name"]
                    first_name = ai_data.get("first_name") or full_name.split()[0]
                    last_name = ai_data.get("last_name") or " ".join(full_name.split()[1:])
                elif ai_data.get("first_name"):
                    first_name = ai_data["first_name"]
                    last_name = ai_data.get("last_name", "")
                    full_name = f"{first_name} {last_name}".strip()

                if not email and ai_data.get("email"):
                    email = ai_data["email"]
                if not phone and ai_data.get("phone"):
                    phone = ai_data["phone"]
                if not date_of_birth_iso and ai_data.get("date_of_birth"):
                    date_of_birth_iso = ai_data["date_of_birth"]
                    date_of_birth_display = ai_data.get("date_of_birth_display") or date_of_birth_iso
                if not place_of_birth and ai_data.get("place_of_birth"):
                    place_of_birth = ai_data["place_of_birth"]
                if not nationality and ai_data.get("nationality"):
                    nationality = ai_data["nationality"]
                if ai_data.get("gender") in ["male", "female", "other"]:
                    gender = ai_data["gender"]
                if ai_data.get("salutation"):
                    salutation = ai_data["salutation"]

                if not street and ai_data.get("street"):
                    street = ai_data["street"]
                if not house_number and ai_data.get("house_number"):
                    house_number = ai_data["house_number"]
                if not postal_code and ai_data.get("postal_code"):
                    postal_code = ai_data["postal_code"]
                if not city and ai_data.get("city"):
                    city = ai_data["city"]
                country = ai_data.get("country") or "Deutschland"

                if (not current_title or current_title in ["Bewerber", "Softwareentwickler"]) and ai_data.get("current_title"):
                    current_title = ai_data["current_title"]
                if (not headline or "Bewerber" in headline) and ai_data.get("headline"):
                    headline = ai_data["headline"]
                if (not summary_de or "Motivierter Kandidat" in summary_de) and ai_data.get("summary_de"):
                    summary_de = ai_data["summary_de"]

                if ai_data.get("skills"):
                    for s in ai_data["skills"]:
                        if s not in detected_skills:
                            detected_skills.append(s)

                if ai_data.get("languages"):
                    for lang_item in ai_data["languages"]:
                        if isinstance(lang_item, dict) and lang_item.get("language"):
                            if not any(dl.get("language") == lang_item["language"] for dl in detected_languages):
                                detected_languages.append(lang_item)

        return {
            "personal": {
                "first_name": first_name,
                "last_name": last_name,
                "full_name": full_name or f"{first_name} {last_name}".strip(),
                "date_of_birth": date_of_birth_iso,
                "date_of_birth_display": date_of_birth_display,
                "place_of_birth": place_of_birth,
                "nationality": nationality,
                "salutation": salutation,
                "gender": gender
            },
            "contact": {
                "email": email,
                "phone": phone,
                "phone_display": phone,
                "address": {
                    "street": street,
                    "house_number": house_number,
                    "postal_code": postal_code,
                    "city": city,
                    "country": "Deutschland",
                    "country_code": "DE"
                },
                "linkedin": {
                    "url": linkedin_url
                },
                "portfolio": {
                    "url": portfolio_url
                },
                "github": {
                    "url": github_url
                }
            },
            "professional_profile": {
                "current_title": current_title,
                "headline": headline,
                "summary_de": summary_de,
                "primary_fields": primary_fields
            },
            "skills": {
                "technologies_from_cv": detected_skills,
                "programming_languages": [s for s in detected_skills if s in ["Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "PHP", "Go", "Rust", "SQL"]],
                "frontend": [s for s in detected_skills if s in ["React", "Vue", "Angular", "HTML", "CSS", "Tailwind"]],
                "backend": [s for s in detected_skills if s in ["Node.js", "Express", "Flask", "Django", "FastAPI", "Spring Boot", "REST"]],
                "tools": [s for s in detected_skills if s in ["Git", "GitHub", "Docker", "Linux", "Kubernetes", "Selenium"]]
            },
            "languages": detected_languages or [
                {"language": "German", "language_de": "Deutsch", "level_de": "Fließend"}
            ]
        }

    @classmethod
    def extract_with_ai(cls, text: str) -> Optional[Dict[str, Any]]:
        """
        Uses Central AI Provider Manager (OpenAI GPT Luna / Gemini) to extract structured candidate data.
        """
        try:
            from services.ai_provider_manager import ai_manager
            return ai_manager.extract_cv_json(text)
        except Exception as exc:
            logger.warning("AI CV extraction encountered error: %s", exc)
            return None

    @classmethod
    def extract_with_vision(cls, pdf_bytes: bytes) -> Optional[Dict[str, Any]]:
        """
        Extracts candidate data from scanned or image-based PDF using Central AI Provider Manager.
        """
        if not pdf_bytes:
            return None

        image_bytes = None
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
            if reader.pages:
                page = reader.pages[0]
                if hasattr(page, "images") and page.images:
                    image_bytes = page.images[0].data
        except Exception as e:
            logger.debug("Failed extracting image from PDF page: %s", e)

        if not image_bytes:
            return None

        try:
            from services.ai_provider_manager import ai_manager
            return ai_manager.extract_cv_vision(image_bytes)
        except Exception as exc:
            logger.warning("AI Vision extraction encountered error: %s", exc)
            return None

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
        for k, v in parsed_data.get("personal", {}).items():
            if v and (not personal.get(k) or personal.get(k) in ["Firstname", "Lastname", "Firstname Lastname", "Bewerber"]):
                personal[k] = v

        # Merge contact
        contact = applicant.setdefault("contact", {})
        parsed_contact = parsed_data.get("contact", {})
        if parsed_contact.get("email") and (not contact.get("email") or "example.com" in contact.get("email", "")):
            contact["email"] = parsed_contact["email"]
        if parsed_contact.get("phone"):
            contact["phone"] = parsed_contact["phone"]
            contact["phone_display"] = parsed_contact["phone_display"]

        # Merge address
        addr = contact.setdefault("address", {})
        parsed_addr = parsed_contact.get("address", {})
        for fld in ["street", "house_number", "postal_code", "city", "country", "country_code"]:
            if parsed_addr.get(fld):
                addr[fld] = parsed_addr[fld]

        # Merge socials
        for social_key in ["linkedin", "portfolio", "github"]:
            if parsed_contact.get(social_key, {}).get("url"):
                s_obj = contact.setdefault(social_key, {})
                s_obj["url"] = parsed_contact[social_key]["url"]

        # Merge professional profile
        prof = applicant.setdefault("professional_profile", {})
        parsed_prof = parsed_data.get("professional_profile", {})
        if parsed_prof.get("current_title") and (not prof.get("current_title") or prof.get("current_title") == "Bewerber"):
            prof["current_title"] = parsed_prof["current_title"]
        if parsed_prof.get("headline") and (not prof.get("headline") or "Bewerber" in prof.get("headline", "")):
            prof["headline"] = parsed_prof["headline"]
        if parsed_prof.get("summary_de") and not prof.get("summary_de"):
            prof["summary_de"] = parsed_prof["summary_de"]
        if parsed_prof.get("primary_fields") and not prof.get("primary_fields"):
            prof["primary_fields"] = parsed_prof["primary_fields"]

        # Merge skills
        skills = applicant.setdefault("skills", {})
        existing_techs = set(skills.get("technologies_from_cv", []))
        new_techs = set(parsed_data.get("skills", {}).get("technologies_from_cv", []))
        skills["technologies_from_cv"] = sorted(list(existing_techs | new_techs))

        # Save back
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        return existing
