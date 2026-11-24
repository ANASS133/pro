"""
Intelligent CV / Resume Parser for automatic candidate profile ingestion.
Extracts text from uploaded PDF resumes and structures contact info, skills, experience, and education.
"""

import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from pypdf import PdfReader

from services.document_classifier import DocumentClassifier, DocumentType, INSTITUTIONAL_SIGNATURES

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
    def _get_pdf_bytes(pdf_bytes_or_path) -> bytes:
        """Safely converts file paths or stream inputs to raw bytes."""
        if isinstance(pdf_bytes_or_path, (str, Path)):
            try:
                with open(pdf_bytes_or_path, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.warning("Could not read PDF from path %s: %s", pdf_bytes_or_path, e)
                return b""
        elif pdf_bytes_or_path is not None:
            return bytes(pdf_bytes_or_path)
        return b""

    @classmethod
    def extract_text_from_pdf(cls, pdf_bytes_or_path) -> str:
        """
        Robustly extract text content from a PDF document using a multi-tiered pipeline:
        - Tier 1: PyMuPDF (C-engine MuPDF, block & column-sorted extraction)
        - Tier 2: pdfplumber (Layout-preserving & table-aware extraction)
        - Tier 3: Standard pypdf extraction with strict=False & per-page isolation
        - Tier 4: Stream repair (missing EOF / unclosed stream objects)
        - Tier 5: Direct raw stream & text operator recovery (zlib token scan)
        """
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        if not pdf_bytes:
            return ""

        text_pages: List[str] = []

        # -------------------------------------------------------------
        # Tier 1: PyMuPDF (High-performance C engine, block & column sort)
        # -------------------------------------------------------------
        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    # b: (x0, y0, x1, y1, text, block_no, block_type) - 0 is text
                    if len(b) >= 5 and b[4] and b[4].strip():
                        if len(b) < 7 or b[6] == 0:
                            text_pages.append(b[4].strip())
            doc.close()
            if text_pages:
                res = "\n".join(text_pages).strip()
                if len(res) > 20:
                    return res
        except Exception as fitz_err:
            logger.debug("PyMuPDF extraction failed or unavailable: %s", fitz_err)

        # -------------------------------------------------------------
        # Tier 2: pdfplumber (Layout-preserving & table-aware)
        # -------------------------------------------------------------
        try:
            import pdfplumber
            plumber_pages = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    txt = page.extract_text(layout=True)
                    if txt and txt.strip():
                        plumber_pages.append(txt.strip())
            if plumber_pages:
                res = "\n".join(plumber_pages).strip()
                if len(res) > 20:
                    return res
        except Exception as plumber_err:
            logger.debug("pdfplumber extraction failed: %s", plumber_err)

        # -------------------------------------------------------------
        # Tier 3: Standard pypdf extraction with strict=False & per-page isolation
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
    def _parse_work_experience(cls, text: str) -> List[Dict[str, Any]]:
        """Extracts structured employment entries from CV text."""
        # Find section between Berufserfahrung and subsequent sections
        m = re.search(
            r"(?i)(?:berufserfahrung|beruflicher werdegang|work experience|berufliche erfahrung|praktika)\s*\n(.*?)(?=\n\s*(?:ausbildung|education|studium|schulausbildung|technologien|skills|kenntnisse|sprachen|zertifikate|\Z))",
            text,
            re.DOTALL,
        )
        if not m:
            return []

        sec = m.group(1).strip()
        entry_pattern = r"(?m)^[ \t]*((?:\d{1,2}[./])?\d{4})\s*[-–—]\s*(heute|present|aktuell|current|(?:\d{1,2}[./])?\d{4})\s*(?:[|:]\s*([^\r\n]+))?"
        matches = list(re.finditer(entry_pattern, sec))
        entries: List[Dict[str, Any]] = []

        now = datetime.now()

        def _parse_date_tuple(d_str: str) -> Optional[Tuple[int, int]]:
            s = d_str.strip().lower()
            if s in ["heute", "present", "aktuell", "current"]:
                return (now.year, now.month)
            m_my = re.match(r"^(\d{1,2})[./](\d{4})$", s)
            if m_my:
                return (int(m_my.group(2)), int(m_my.group(1)))
            m_y = re.match(r"^(\d{4})$", s)
            if m_y:
                return (int(m_y.group(1)), 1)
            return None

        for i, match in enumerate(matches):
            start_date = match.group(1).strip()
            end_date = match.group(2).strip()
            position = (match.group(3) or "").strip()

            block_start = match.end()
            block_end = matches[i + 1].start() if i + 1 < len(matches) else len(sec)
            block = sec[block_start:block_end].strip()

            lines = [l.strip() for l in block.split("\n") if l.strip()]
            employer = ""
            location = ""
            responsibilities: List[str] = []

            for line in lines:
                if line.startswith(("•", "-", "*", "–")):
                    responsibilities.append(line.lstrip("•-*– \t"))
                elif not employer and not line.startswith(("•", "-", "*", "–")):
                    # Employer and optional location line
                    if "," in line:
                        parts = line.split(",")
                        employer = parts[0].strip()
                        location = ", ".join(p.strip() for p in parts[1:])
                    elif " - " in line:
                        p2 = line.split(" - ")
                        employer = p2[0].strip()
                        location = p2[1].strip()
                    else:
                        employer = line.strip()
                else:
                    responsibilities.append(line)

            # Compute duration in months
            duration_months = 0
            st = _parse_date_tuple(start_date)
            et = _parse_date_tuple(end_date)
            if st and et:
                months = (et[0] - st[0]) * 12 + (et[1] - st[1]) + 1
                if months > 0:
                    duration_months = months

            entries.append({
                "job_title": position,
                "position": position,
                "employer": employer,
                "company": employer,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "is_current": end_date.lower() in ["heute", "present", "aktuell", "current"],
                "duration_months": duration_months,
                "responsibilities": responsibilities,
                "source": "CV",
            })

        return entries

    @classmethod
    def _parse_education(cls, text: str) -> List[Dict[str, Any]]:
        """Extracts structured education and academic degree entries from CV text."""
        m = re.search(
            r"(?i)(?:ausbildung|education|studium|schulausbildung|akademischer werdegang)\s*\n(.*?)(?=\n\s*(?:technologien|skills|kenntnisse|sprachen|zertifikate|berufserfahrung|\Z))",
            text,
            re.DOTALL,
        )
        if not m:
            return []

        sec = m.group(1).strip()
        entry_pattern = r"(?m)^[ \t]*((?:\d{1,2}[./])?\d{4})\s*[-–—]\s*(heute|present|aktuell|current|(?:\d{1,2}[./])?\d{4})\s*(?:[|:]\s*([^\r\n]+))?"
        matches = list(re.finditer(entry_pattern, sec))
        entries: List[Dict[str, Any]] = []

        for i, match in enumerate(matches):
            start_date = match.group(1).strip()
            end_date = match.group(2).strip()
            degree = (match.group(3) or "").strip()

            block_start = match.end()
            block_end = matches[i + 1].start() if i + 1 < len(matches) else len(sec)
            block = sec[block_start:block_end].strip()
            lines = [l.strip() for l in block.split("\n") if l.strip()]

            institution = ""
            location = ""
            field_of_study = ""

            if lines:
                first_line = lines[0]
                if "," in first_line:
                    parts = first_line.split(",")
                    institution = parts[0].strip()
                    location = ", ".join(p.strip() for p in parts[1:])
                elif " - " in first_line:
                    p2 = first_line.split(" - ")
                    institution = p2[0].strip()
                    location = p2[1].strip()
                else:
                    institution = first_line

                if len(lines) > 1:
                    field_of_study = " | ".join(lines[1:])

            entries.append({
                "degree": degree,
                "institution": institution,
                "location": location,
                "field_of_study": field_of_study,
                "start_date": start_date,
                "end_date": end_date,
                "is_current": end_date.lower() in ["heute", "present", "aktuell", "current"],
                "source": "CV",
            })

        return entries

    @classmethod
    def _parse_certifications(cls, cv_text: str, supporting_text: str = "") -> List[Dict[str, Any]]:
        """Extracts certifications from CV Zertifikate section and supporting documents."""
        certifications: List[Dict[str, Any]] = []
        seen = set()

        # 1. From CV text
        m = re.search(
            r"(?i)(?:zertifikate|zertifizierungen|certificates|weiterbildung)\s*\n+(.*)",
            cv_text,
            re.DOTALL,
        )
        if m:
            full_tail = m.group(1).strip()
            # Stop if another major section header starts
            sec = re.split(r"(?im)^[ \t]*(?:sprachen|technologien|skills|ausbildung|berufserfahrung)\b", full_tail)[0].strip()
            raw_items = []
            for line in sec.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if "|" in line:
                    raw_items.extend([p.strip() for p in line.split("|") if p.strip()])
                else:
                    raw_items.append(line)

            for item in raw_items:
                clean_name = item.strip().rstrip(".,;")
                if clean_name and len(clean_name) >= 3 and clean_name.lower() not in seen:
                    seen.add(clean_name.lower())
                    certifications.append({
                        "name": clean_name,
                        "source": "CV",
                        "verified": False,
                    })

        # 2. Enrich from supporting text
        if supporting_text:
            sup_lower = supporting_text.lower()
            for cert in certifications:
                c_name = cert["name"].lower()
                # Check keywords like telc, zab, cisco
                if any(kw in c_name and kw in sup_lower for kw in ["telc", "zab", "cisco", "b2", "auskunft"]):
                    cert["verified"] = True

        return certifications

    @classmethod
    def _calculate_experience_metrics(cls, work_entries: List[Dict[str, Any]]) -> Tuple[int, float, str]:
        """Calculates total months, years of experience, and classification level."""
        total_months = 0
        now = datetime.now()

        def _parse_d_tuple(d_str: str) -> Optional[Tuple[int, int]]:
            s = str(d_str or "").strip().lower()
            if s in ["heute", "present", "aktuell", "current", "à ce jour", "ce jour"]:
                return (now.year, now.month)
            m_my = re.search(r"\b(\d{1,2})[./](\d{4})\b", s)
            if m_my:
                return (int(m_my.group(2)), int(m_my.group(1)))
            m_y = re.search(r"\b(19\d\d|20\d\d)\b", s)
            if m_y:
                return (int(m_y.group(1)), 1)
            return None

        for entry in work_entries:
            m = entry.get("duration_months") or 0
            if m <= 0:
                s_tuple = _parse_d_tuple(entry.get("start_date"))
                e_tuple = _parse_d_tuple(entry.get("end_date"))
                if s_tuple and e_tuple:
                    m = max(1, (e_tuple[0] - s_tuple[0]) * 12 + (e_tuple[1] - s_tuple[1]))
                    entry["duration_months"] = m
            total_months += m

        years = round(total_months / 12.0, 1)
        if years >= 5.0:
            level = "Senior"
        elif years >= 1.5 or total_months >= 18 or len(work_entries) >= 2:
            level = "Berufserfahren"
        elif years > 0.0 or work_entries:
            level = "Junior"
        else:
            level = "Berufseinstieg"

        return total_months, years, level

    @classmethod
    def extract_layout_aware_blocks(
        cls,
        pdf_bytes_or_path: Union[bytes, str, Path],
        page_indices: Optional[List[int]] = None,
    ) -> str:
        """
        Extracts layout-aware text from PDF pages using PyMuPDF bounding-box column sorting:
        - Detects multi-column pages.
        - Sorts full-width header blocks first (name, title, contact).
        - Separates and sorts left-column blocks before right-column blocks.
        - Eliminates cross-column text interleaving.
        """
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        if not pdf_bytes:
            return ""

        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            extracted_pages: List[str] = []

            target_indices = page_indices if page_indices is not None else list(range(len(doc)))
            for idx in target_indices:
                if idx < 0 or idx >= len(doc):
                    continue
                page = doc[idx]
                page_width = page.rect.width
                page_height = page.rect.height
                blocks = page.get_text("blocks")

                valid_blocks = [
                    b for b in blocks
                    if len(b) >= 5 and b[4] and b[4].strip() and (len(b) < 7 or b[6] == 0)
                ]

                if not valid_blocks:
                    continue

                header_blocks = []
                left_blocks = []
                right_blocks = []

                for b in valid_blocks:
                    x0, y0, x1, y1, text_val = b[0], b[1], b[2], b[3], b[4].strip()
                    width = x1 - x0
                    center_x = (x0 + x1) / 2.0

                    if width > page_width * 0.65 or y0 < page_height * 0.16:
                        header_blocks.append((y0, text_val))
                    elif center_x < page_width * 0.45:
                        left_blocks.append((y0, text_val))
                    else:
                        right_blocks.append((y0, text_val))

                header_blocks.sort(key=lambda item: item[0])
                left_blocks.sort(key=lambda item: item[0])
                right_blocks.sort(key=lambda item: item[0])

                page_parts = []
                if header_blocks:
                    page_parts.extend(t for _, t in header_blocks)
                if left_blocks:
                    page_parts.extend(t for _, t in left_blocks)
                if right_blocks:
                    page_parts.extend(t for _, t in right_blocks)

                extracted_pages.append("\n\n".join(page_parts))

            doc.close()
            if extracted_pages:
                return "\n\n".join(extracted_pages).strip()
        except Exception as e:
            logger.debug("PyMuPDF layout-aware block extraction failed: %s", e)

        return cls.extract_text_from_pdf(pdf_bytes)

    @classmethod
    def render_cv_page_image(
        cls,
        pdf_bytes_or_path: Union[bytes, str, Path],
        page_index: int = 0,
        dpi: int = 200,
    ) -> Optional[bytes]:
        """Renders a specific PDF page to a high-resolution PNG image for Vision extraction."""
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        if not pdf_bytes:
            return None
        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            if 0 <= page_index < len(doc):
                page = doc[page_index]
                pix = page.get_pixmap(dpi=dpi)
                img_bytes = pix.tobytes("png")
                doc.close()
                return img_bytes
            doc.close()
        except Exception as e:
            logger.debug("Failed to render page image: %s", e)
        return None

    @classmethod
    def _normalize_ai_profile(
        cls,
        ai_profile: Dict[str, Any],
        raw_text: str,
        blacklisted_addresses: List[Dict[str, Any]],
        supporting_text: str = "",
        classification: Optional[Dict[str, Any]] = None,
        model_used: str = "ai_model",
    ) -> Dict[str, Any]:
        """
        Normalizes AI-extracted JSON profile into the canonical JobScout schema:
        - Validates personal details and contact data.
        - Enforces strict anti-institutional address filters (never assigns ZAB Bonn / Hamburg authority).
        - Normalizes work experience, education, skills, and languages.
        - Calculates experience metrics and classification level.
        """
        # 1. Personal
        first_name = str(ai_profile.get("first_name") or "").strip()
        last_name = str(ai_profile.get("last_name") or "").strip()
        full_name = str(ai_profile.get("full_name") or "").strip()
        if not full_name:
            full_name = f"{first_name} {last_name}".strip()
        if not first_name and full_name:
            parts = full_name.split()
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        dob = str(ai_profile.get("date_of_birth") or "").strip()
        dob_display = str(ai_profile.get("date_of_birth_display") or "").strip()
        pob = str(ai_profile.get("place_of_birth") or "").strip()
        nat = str(ai_profile.get("nationality") or "Marokkanisch").strip()
        gender = str(ai_profile.get("gender") or "male").strip().lower()
        salutation = str(ai_profile.get("salutation") or ("Herr" if gender == "male" else "Frau")).strip()

        # 2. Contact & Address
        email = str(ai_profile.get("email") or "").strip()
        if not email:
            em = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", raw_text)
            if em:
                email = em.group(0).strip()

        phone = str(ai_profile.get("phone") or "").strip()
        if not phone:
            pm = re.search(r"(?:\+212|00212|\+49|0049)[ \t\d\-/]{8,20}", raw_text)
            if pm:
                phone = pm.group(0).strip()

        city = str(ai_profile.get("city") or "").strip()
        country = str(ai_profile.get("country") or "Marokko").strip()
        postal_code = str(ai_profile.get("postal_code") or "").strip()
        street = str(ai_profile.get("street") or "").strip()
        house_number = str(ai_profile.get("house_number") or "").strip()

        # Institutional address check
        def is_blocked_addr(pc: str, c: str) -> bool:
            pc_clean = pc.strip().lower()
            c_clean = c.strip().lower()
            for b in blacklisted_addresses:
                b_pc = str(b.get("postal_code", "")).strip().lower()
                b_c = str(b.get("city", "")).strip().lower()
                if b_pc and pc_clean and b_pc == pc_clean:
                    return True
                if b_c and c_clean and b_c in c_clean:
                    return True
            return False

        if is_blocked_addr(postal_code, city):
            logger.warning("Rejected institutional address in AI extraction: %s %s", postal_code, city)
            city = ""
            postal_code = ""
            street = ""
            house_number = ""

        if not city:
            # Fallback to candidate location from CV header
            for c_cand in ["Casablanca", "Rabat", "Marrakesch", "Tanger", "Fès", "Agadir", "Meknès", "Rommani", "Köln", "Berlin", "München", "Hamburg"]:
                if re.search(rf"\b{re.escape(c_cand)}\b", raw_text, re.IGNORECASE):
                    city = c_cand
                    break
            if not city:
                city = "Casablanca"

        # URLs
        linkedin_m = re.search(r"(?:linkedin\.com/in/|linkedin:\s*)([^\s\n\r|]+)", raw_text, re.IGNORECASE)
        linkedin_url = f"https://linkedin.com/in/{linkedin_m.group(1).strip()}" if linkedin_m else ""

        github_m = re.search(r"(?:github\.com/|github:\s*)([^\s\n\r|]+)", raw_text, re.IGNORECASE)
        github_url = f"https://github.com/{github_m.group(1).strip()}" if github_m else ""

        portfolio_m = re.search(r"(?:portfolio:\s*|website:\s*)([^\s\n\r|]+\.[a-z]{2,}(?:/[^\s\n\r|]*)?)", raw_text, re.IGNORECASE)
        portfolio_url = portfolio_m.group(1).strip() if portfolio_m else ""

        # 3. Work Experience
        raw_work = ai_profile.get("work_experience") or []
        work_experience: List[Dict[str, Any]] = []
        for w in raw_work:
            if isinstance(w, dict):
                pos = str(w.get("position") or w.get("job_title") or "").strip()
                emp = str(w.get("employer") or w.get("company") or "").strip()
                if pos or emp:
                    resps = w.get("responsibilities") or []
                    if isinstance(resps, str):
                        resps = [resps]
                    end_d = str(w.get("end_date") or "heute").strip()
                    is_curr = bool(w.get("is_current")) or any(k in end_d.lower() for k in ["heute", "present", "aktuell", "current", "laufend"])
                    work_experience.append({
                        "position": pos or "Mitarbeiter",
                        "employer": emp or "Unternehmen",
                        "location": str(w.get("location") or "").strip(),
                        "start_date": str(w.get("start_date") or "").strip(),
                        "end_date": end_d,
                        "is_current": is_curr,
                        "responsibilities": [str(r).strip() for r in resps if str(r).strip()],
                        "duration_months": int(w.get("duration_months") or 0),
                    })

        if not work_experience:
            work_experience = cls._parse_work_experience(raw_text)

        total_months, years_of_experience, experience_level = cls._calculate_experience_metrics(work_experience)

        # 4. Education
        raw_edu = ai_profile.get("education") or []
        education: List[Dict[str, Any]] = []
        for ed in raw_edu:
            if isinstance(ed, dict):
                deg = str(ed.get("degree") or "").strip()
                inst = str(ed.get("institution") or "").strip()
                if deg or inst:
                    education.append({
                        "degree": deg,
                        "institution": inst,
                        "location": str(ed.get("location") or "").strip(),
                        "start_date": str(ed.get("start_date") or "").strip(),
                        "end_date": str(ed.get("end_date") or "").strip(),
                        "field_of_study": str(ed.get("field_of_study") or "").strip(),
                    })

        if not education:
            education = cls._parse_education(raw_text)

        # 5. Certifications
        certifications = cls._parse_certifications(raw_text, supporting_text=supporting_text)
        for c_ai in (ai_profile.get("certifications") or []):
            if isinstance(c_ai, dict) and c_ai.get("name"):
                c_name = str(c_ai["name"]).strip()
                if not any(c_name.lower() in existing.get("name", "").lower() for existing in certifications):
                    certifications.append({
                        "name": c_name,
                        "issuer": str(c_ai.get("issuer") or "").strip(),
                        "year": str(c_ai.get("year") or "").strip(),
                        "verified": True,
                    })

        # 6. Professional Profile
        current_title = str(ai_profile.get("current_title") or "").strip()
        headline = str(ai_profile.get("headline") or "").strip()

        # Check early lines for candidate professional title (e.g. line 2 "Softwareentwickler | Full-Stack-Entwickler")
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        for cl in lines[1:5]:
            if any(k in cl.lower() for k in ["entwickler", "fachkraft", "spezialist", "engineer", "ingenieur", "berater", "manager", "assistent"]):
                if not any(stop in cl.lower() for stop in ["profil", "berufserfahrung", "ausbildung", "kenntnisse", "kontakt", "email", "@"]):
                    if not current_title or current_title.lower() in cl.lower():
                        current_title = cl
                        break

        if not current_title and work_experience:
            current_title = work_experience[0]["position"]
        if not current_title:
            current_title = "Fachkraft"

        if not headline:
            headline = current_title
        elif current_title and current_title not in headline:
            headline = f"{current_title} | {headline}"

        summary_de = str(ai_profile.get("summary_de") or f"Qualifizierter {current_title} mit fundierter Praxiserfahrung.").strip()

        # 7. Skills
        raw_skills = ai_profile.get("skills") or []
        skills_list = [str(s).strip() for s in raw_skills if str(s).strip()]
        if not skills_list:
            skills_list = [kw for kw in COMMON_SKILLS if re.search(rf"\b{re.escape(kw)}\b", raw_text, re.IGNORECASE)]

        # 8. Languages
        raw_langs = ai_profile.get("languages") or []
        detected_languages: List[Dict[str, Any]] = []
        for l in raw_langs:
            if isinstance(l, dict) and l.get("language"):
                l_name = str(l["language"]).strip()
                l_de = str(l.get("language_de") or l_name).strip()
                lvl = str(l.get("level") or l.get("level_de") or "B2").strip()
                detected_languages.append({
                    "language": l_name,
                    "language_de": l_de,
                    "level_de": lvl,
                })

        if not detected_languages:
            detected_languages = [
                {"language": "German", "language_de": "Deutsch", "level_de": "B2 (fließend)"}
            ]

        return {
            "personal": {
                "first_name": first_name,
                "last_name": last_name,
                "full_name": full_name,
                "date_of_birth": dob,
                "date_of_birth_display": dob_display,
                "place_of_birth": pob,
                "nationality": nat,
                "salutation": salutation,
                "gender": gender,
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
                    "country": country,
                    "country_code": "MA" if "marok" in country.lower() else "DE",
                },
                "linkedin": {"url": linkedin_url},
                "portfolio": {"url": portfolio_url},
                "github": {"url": github_url},
            },
            "professional_profile": {
                "current_title": current_title,
                "headline": headline,
                "summary_de": summary_de,
                "primary_fields": skills_list[:6] if skills_list else ["Softwareentwicklung"],
                "years_of_experience": years_of_experience,
                "experience_level": experience_level,
                "target_occupation": "",
            },
            "work_experience": work_experience,
            "education": education,
            "certifications": certifications,
            "skills": {
                "technologies_from_cv": skills_list,
                "programming_languages": [s for s in skills_list if s in ["Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "PHP", "Go", "Rust", "SQL", "Dart"]],
                "frontend": [s for s in skills_list if s in ["React", "Vue", "Angular", "HTML", "CSS", "Tailwind", "Flutter"]],
                "backend": [s for s in skills_list if s in ["Node.js", "Express", "Flask", "Django", "FastAPI", "Spring Boot", "REST", "Laravel"]],
                "tools": [s for s in skills_list if s in ["Git", "GitHub", "Docker", "Linux", "Kubernetes", "Selenium", "Swagger/OpenAPI"]],
            },
            "languages": detected_languages,
            "extraction_metadata": {
                "confidence": 0.98,
                "model_used": model_used,
                "field_confidences": {
                    "name": 1.0 if full_name else 0.0,
                    "email": 1.0 if email else 0.0,
                    "phone": 1.0 if phone else 0.0,
                    "location": 1.0 if city else 0.0,
                    "title": 0.98 if current_title else 0.0,
                    "work_experience": 0.98 if work_experience else 0.0,
                    "education": 0.98 if education else 0.0,
                },
                "source_references": [
                    {"field": "identity", "source": "CV Page"},
                    {"field": "work_experience", "source": "CV Page"},
                    {"field": "education", "source": "CV Page"},
                    {"field": "certifications", "source": "CV & Supporting Documents"},
                ],
            },
        }

    @classmethod
    def parse_pdf_dossier(cls, pdf_bytes_or_path: Union[bytes, str, Path]) -> Dict[str, Any]:
        """
        Full-dossier parsing pipeline:
        1. Classifies pages in PDF dossier using DocumentClassifier.
        2. Isolates actual CV text from supporting certificates/diplomas/translations.
        3. Identifies and blacklists institutional addresses (e.g. ZAB Bonn).
        4. If CV text is empty (< 80 chars), triggers Tier 1 Vision Fallback (rasterizing page to high-res image).
        5. If CV text exists, performs layout-aware bounding-box extraction.
        6. Invokes AI extraction (OpenAI/Gemini) with full nested schema (work experience + education + skills).
        7. Sanitizes and normalizes extracted fields (enforcing institutional address blacklists, calculating experience metrics).
        8. Falls back gracefully to deterministic regex parser if AI is offline.
        """
        classification = DocumentClassifier.classify_dossier(pdf_bytes_or_path)
        cv_indices = classification.get("cv_page_indices") or [0]
        cv_text = classification.get("cv_text") or ""
        supporting_text = classification.get("supporting_text") or ""
        blacklisted = classification.get("blacklisted_addresses") or []

        # 1. Layout-Aware Extraction for CV pages
        layout_text = cls.extract_layout_aware_blocks(pdf_bytes_or_path, page_indices=cv_indices)
        if layout_text and len(layout_text.strip()) > len(cv_text.strip()) * 0.7:
            effective_cv_text = layout_text
        else:
            effective_cv_text = cv_text or cls.extract_text_from_pdf(pdf_bytes_or_path)

        # 2. Check if CV text is empty or too short (scanned PDF) -> Vision Fallback
        is_scanned_cv = len(effective_cv_text.strip()) < 80
        ai_result = None

        if is_scanned_cv:
            logger.info("CV text is minimal (%d chars). Triggering Vision Fallback...", len(effective_cv_text.strip()))
            target_page_idx = cv_indices[0] if cv_indices else 0
            image_bytes = cls.render_cv_page_image(pdf_bytes_or_path, page_index=target_page_idx, dpi=200)
            if image_bytes:
                ai_result = cls.extract_with_vision(image_bytes)
        else:
            # 3. AI extraction with complete nested schema
            ai_result = cls.extract_with_ai(effective_cv_text)

        # 4. If AI extraction returned a valid profile, normalize and merge it
        if ai_result and ai_result.get("success") and ai_result.get("parsed_profile"):
            parsed = cls._normalize_ai_profile(
                ai_profile=ai_result["parsed_profile"],
                raw_text=effective_cv_text,
                blacklisted_addresses=blacklisted,
                supporting_text=supporting_text,
                classification=classification,
                model_used=ai_result.get("model", "ai_model"),
            )
        else:
            # 5. Fallback to deterministic regex parser
            parsed = cls.parse_cv_text(
                effective_cv_text,
                blacklisted_addresses=blacklisted,
                supporting_text=supporting_text,
                classification=classification,
            )

        parsed["classification_metadata"] = {
            "total_pages": classification.get("total_pages", 1),
            "cv_page_numbers": classification.get("cv_page_numbers", [1]),
            "is_multi_document": classification.get("is_multi_document", False),
            "institutional_page_indices": classification.get("institutional_page_indices", []),
            "classified_pages": classification.get("classified_pages", []),
            "extraction_tier": "ai_vision" if is_scanned_cv and ai_result else ("ai_text" if (ai_result and ai_result.get("success")) else "heuristic_regex"),
        }

        return parsed

    @classmethod
    def parse_cv_text(
        cls,
        text: str,
        blacklisted_addresses: Optional[List[Dict[str, Any]]] = None,
        supporting_text: str = "",
        classification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Heuristically extracts comprehensive candidate profile fields from CV text:
        - Personal (first_name, last_name, full_name, date_of_birth, place_of_birth, nationality, salutation, gender)
        - Contact & Address (email, phone, street, house_number, postal_code, city, country, country_code, linkedin, github, portfolio)
        - Professional Profile (current_title, headline, summary_de, primary_fields, years_of_experience, experience_level)
        - Work Experience (roles, employers, dates, responsibilities)
        - Education (degrees, institutions, dates, fields of study)
        - Certifications & Skills & Languages
        - Enforces institutional address blacklist (never assigns ZAB Bonn or BA Nürnberg to candidate).
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        text_lower = text.lower()

        # Institutional address verification helper
        def is_blocked_institutional(pc: str, c: str, s: str = "") -> bool:
            pc_clean = str(pc or "").strip()
            c_clean = str(c or "").lower().strip()
            s_clean = str(s or "").lower().strip()
            if blacklisted_addresses:
                for b in blacklisted_addresses:
                    b_pc = str(b.get("postal_code") or "").strip()
                    b_city = str(b.get("city") or "").lower().strip()
                    if b_pc and b_city:
                        if b_pc == pc_clean and b_city in c_clean:
                            return True
                    elif b_pc and b_pc == pc_clean:
                        return True
            for sig in INSTITUTIONAL_SIGNATURES:
                b = sig.get("blocked_address") or {}
                b_pc = str(b.get("postal_code") or "").strip()
                b_city = str(b.get("city") or "").lower().strip()
                if b_pc and b_city:
                    if b_pc == pc_clean and b_city in c_clean:
                        return True
                elif b_pc and b_pc == pc_clean:
                    return True
            if pc_clean == "53117" and "bonn" in c_clean:
                return True
            if pc_clean == "90478" and any(n in c_clean for n in ["nürnberg", "nuernberg"]):
                return True
            if pc_clean == "60329" and "frankfurt" in c_clean and ("baseler" in s_clean or not s_clean):
                return True
            if pc_clean == "80333" and any(m in c_clean for m in ["münchen", "muenchen"]) and ("oskar" in s_clean or not s_clean):
                return True
            return False

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
        elif "marokko" in text_lower or "morocco" in text_lower:
            nationality = "Marokkanisch"

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

        # 7. Candidate Location & Address (Header search + German PLZ with institutional blacklist)
        street = ""
        house_number = ""
        postal_code = ""
        city = ""
        country = "Deutschland"
        country_code = "DE"

        # Check candidate header lines (top 6 lines) for city/country e.g. "Casablanca, Marokko"
        for line in lines[:6]:
            parts = [p.strip() for p in re.split(r"[|•]", line) if p.strip()]
            for p in parts:
                if "," in p:
                    sub = p.split(",")
                    cand_city = sub[0].strip()
                    cand_country = sub[1].strip()
                    cand_country_clean = re.sub(r"[\s\d+-].*$", "", cand_country).strip()
                    if cand_country_clean.lower() in [
                        "marokko", "morocco", "deutschland", "germany", "österreich", "austria",
                        "schweiz", "switzerland", "frankreich", "france", "tunesien", "tunisia"
                    ]:
                        city = cand_city
                        country = cand_country_clean.capitalize()
                        if country.lower() in ["marokko", "morocco"]:
                            country = "Marokko"
                            country_code = "MA"
                        elif country.lower() in ["deutschland", "germany"]:
                            country = "Deutschland"
                            country_code = "DE"
                        break
            if city:
                break

        # Check German street/postal code format if candidate has a German address
        street_match = re.search(
            r"(?i)\b([A-ZÄÖÜ][a-zäöüß]+(?:[ \t]+[A-ZÄÖÜ][a-zäöüß]+)*(?:straße|strasse|str\.|weg|allee|platz|ring|damm|gasse|pfad|chaussee|ufer|park))[ \t]+(\d+[a-zA-Z]?(?:[ \t]*[\/\-][ \t]*\d+[a-zA-Z]?)?)\b",
            text
        )
        if street_match:
            cand_street = street_match.group(1).strip()
            cand_house_num = street_match.group(2).strip()
            if not is_blocked_institutional("", "", cand_street):
                street = cand_street
                house_number = cand_house_num

        city_match = re.search(r"\b(?:D-)?([0-9]{5})[ \t]+([A-ZÄÖÜ][^\r\n,;]+)", text)
        if city_match:
            cand_plz = city_match.group(1).strip()
            cand_city = city_match.group(2).strip()
            if not is_blocked_institutional(cand_plz, cand_city):
                postal_code = cand_plz
                if not city or country == "Deutschland":
                    city = cand_city
                    country = "Deutschland"
                    country_code = "DE"
            else:
                logger.info("Blocked institutional address from being assigned to candidate: %s %s", cand_plz, cand_city)

        # 8. LinkedIn, GitHub, and Portfolio URLs
        linkedin_url = ""
        li_m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9_\-%]+)", text, re.IGNORECASE)
        if li_m:
            linkedin_url = f"https://linkedin.com/in/{li_m.group(1)}"
        else:
            li_text_m = re.search(r"(?i)linkedin\s*[:]\s*([a-zA-Z0-9_\-%\s]+)(?:[|\n\r]|\Z)", text)
            if li_text_m:
                val = li_text_m.group(1).strip()
                if len(val) > 2 and "http" not in val:
                    linkedin_url = f"https://linkedin.com/in/{val.lower().replace(' ', '-')}"

        github_url = ""
        gh_m = re.search(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_\-%]+)", text, re.IGNORECASE)
        if gh_m:
            github_url = f"https://github.com/{gh_m.group(1)}"

        portfolio_url = ""
        # Check explicit portfolio label
        port_m = re.search(r"(?i)portfolio\s*[:]\s*([^\s|]+)", text)
        if port_m:
            raw_port = port_m.group(1).strip()
            if not any(ex in raw_port.lower() for ex in ["kmk.org", "arbeitsagentur", "anabin"]):
                portfolio_url = f"https://{raw_port}" if not raw_port.startswith("http") else raw_port

        if not portfolio_url:
            urls = re.findall(r"https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?", text)
            for u in urls:
                u_clean = u.rstrip(".,;)")
                u_lower = u_clean.lower()
                if not any(ex in u_lower for ex in ["linkedin.com", "github.com", "google.com", "schema.org", "w3.org", "kmk.org", "anabin", "arbeitsagentur"]):
                    portfolio_url = u_clean
                    break

        # 9. Skills extraction
        detected_skills = []
        for skill in COMMON_SKILLS:
            pattern = rf"\b{re.escape(skill.lower())}\b"
            if re.search(pattern, text_lower):
                detected_skills.append(skill)

        # Also parse explicit Technologien section
        tech_m = re.search(r"(?i)technologien\s*\n([^\n\r]+(?:\n[^\n\r]+)?)", text)
        if tech_m:
            raw_tech_line = tech_m.group(1)
            for t_item in re.split(r"[|,\n]", raw_tech_line):
                t_clean = t_item.strip()
                if t_clean and len(t_clean) >= 2 and t_clean not in detected_skills:
                    if not any(h in t_clean.lower() for h in ["sprachen", "zertifikate", "ausbildung"]):
                        detected_skills.append(t_clean)

        # 10. Candidate's Professional Job Title & Headline
        current_title = ""
        # Check line 2 under candidate name in top 4 lines (e.g. "Softwareentwickler | Full-Stack-Entwickler")
        role_keywords = [
            "entwickler", "developer", "informatiker", "software", "frontend", "backend", "fullstack",
            "full-stack", "engineer", "ingenieur", "data", "cloud", "devops", "administrator",
            "kaufmann", "kauffrau", "designer", "architect", "consultant", "manager", "fachkraft", "techniker"
        ]
        for l in lines[1:5]:
            cl = l.strip()
            if not cl or "@" in cl or any(c in cl for c in "+0123456789"):
                continue
            if any(kw in cl.lower() for kw in role_keywords):
                current_title = cl
                break

        # Check explicit label with strict word boundary and required colon
        if not current_title:
            title_label_match = re.search(
                r"(?i)\b(?:angestrebte\s+stelle|angestrebte\s+position|berufsbezeichnung|\bberuf\b|\bposition\b|\brolle\b|job\s*title|current\s*title)\b\s*[:]\s*([^\n\r,;]{3,60})",
                text
            )
            if title_label_match:
                val = title_label_match.group(1).strip()
                if len(val) > 3 and not any(w in val.lower() for w in ["lebenslauf", "cv", "bewerbung", "berufserfahrung"]):
                    current_title = val

        if not current_title:
            current_title = "Softwareentwickler" if ("python" in text_lower or "javascript" in text_lower or "react" in text_lower) else "Bewerber"

        headline = f"{full_name} | {current_title}" if full_name else current_title

        # 11. Profile Summary
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

        # 12. Primary fields
        primary_fields = detected_skills[:6] if detected_skills else ["Softwareentwicklung", "Webentwicklung"]

        # 13. Languages extraction
        detected_languages = []
        # Check specific CV language line first e.g. "Deutsch: B2 (telc) | Englisch: B1 | Französisch: B2 | Arabisch: Muttersprache"
        lang_sec_m = re.search(r"(?i)sprachen\s*\n([^\n\r]+)", text)
        if lang_sec_m:
            for l_part in lang_sec_m.group(1).split("|"):
                if ":" in l_part:
                    p_lang, p_lvl = l_part.split(":", 1)
                    p_lang_clean = p_lang.strip()
                    p_lvl_clean = p_lvl.strip()
                    detected_languages.append({
                        "language": p_lang_clean,
                        "language_de": p_lang_clean,
                        "level_de": p_lvl_clean,
                    })

        if not detected_languages:
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

        # 14. Work Experience, Education & Certifications
        work_experience = cls._parse_work_experience(text)
        education = cls._parse_education(text)
        certifications = cls._parse_certifications(text, supporting_text=supporting_text)
        total_months, years_of_experience, experience_level = cls._calculate_experience_metrics(work_experience)

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
                    "country": country,
                    "country_code": country_code,
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
                "primary_fields": primary_fields,
                "years_of_experience": years_of_experience,
                "experience_level": experience_level,
                "target_occupation": "",
            },
            "work_experience": work_experience,
            "education": education,
            "certifications": certifications,
            "skills": {
                "technologies_from_cv": detected_skills,
                "programming_languages": [s for s in detected_skills if s in ["Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "PHP", "Go", "Rust", "SQL", "Dart"]],
                "frontend": [s for s in detected_skills if s in ["React", "Vue", "Angular", "HTML", "CSS", "Tailwind", "Flutter"]],
                "backend": [s for s in detected_skills if s in ["Node.js", "Express", "Flask", "Django", "FastAPI", "Spring Boot", "REST", "Laravel"]],
                "tools": [s for s in detected_skills if s in ["Git", "GitHub", "Docker", "Linux", "Kubernetes", "Selenium", "Swagger/OpenAPI"]]
            },
            "languages": detected_languages or [
                {"language": "German", "language_de": "Deutsch", "level_de": "Fließend"}
            ],
            "extraction_metadata": {
                "confidence": 0.95 if full_name and (email or phone) else 0.5,
                "field_confidences": {
                    "name": 1.0 if full_name else 0.0,
                    "email": 1.0 if email else 0.0,
                    "phone": 1.0 if phone else 0.0,
                    "location": 1.0 if city else 0.0,
                    "title": 0.95 if current_title else 0.0,
                    "work_experience": 0.95 if work_experience else 0.0,
                    "education": 0.95 if education else 0.0,
                },
                "source_references": [
                    {"field": "identity", "source": "CV Page 1"},
                    {"field": "work_experience", "source": "CV Page 1"},
                    {"field": "education", "source": "CV Page 1"},
                    {"field": "certifications", "source": "CV & Supporting Pages"},
                ]
            }
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
        Uses PyMuPDF to rasterize the page to a high-fidelity image if raw image streams are absent.
        """
        if not pdf_bytes:
            return None

        image_bytes = None
        # Tier 1: Try PyMuPDF page rendering (most accurate, handles scanned docs & vector pages)
        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            if len(doc) > 0:
                page = doc[0]
                pix = page.get_pixmap(dpi=200)
                image_bytes = pix.tobytes("png")
            doc.close()
        except Exception as mupdf_err:
            logger.debug("PyMuPDF vision rendering failed: %s", mupdf_err)

        # Tier 2: Fallback to extracting embedded image from pypdf
        if not image_bytes:
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
    def extract_tables_from_pdf(cls, pdf_bytes_or_path) -> List[List[List[str]]]:
        """
        Extracts structured tables (grades, certificates, timeline grids) from PDF pages.
        Returns a list of tables, where each table is a 2D list of string cells.
        """
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        if not pdf_bytes:
            return []

        all_tables: List[List[List[str]]] = []

        # Tier 1: pdfplumber (best table border detection & text grouping)
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for t in tables:
                        if t and len(t) > 1:
                            cleaned_table = []
                            for row in t:
                                cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                                if any(cleaned_row):
                                    cleaned_table.append(cleaned_row)
                            if len(cleaned_table) > 1:
                                all_tables.append(cleaned_table)
            if all_tables:
                return all_tables
        except Exception as exc:
            logger.debug("pdfplumber table extraction error: %s", exc)

        # Tier 2: PyMuPDF find_tables fallback
        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                tabs = page.find_tables()
                for tab in tabs:
                    raw_tab = tab.extract()
                    if raw_tab and len(raw_tab) > 1:
                        cleaned_table = []
                        for row in raw_tab:
                            cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                            if any(cleaned_row):
                                cleaned_table.append(cleaned_row)
                        if len(cleaned_table) > 1:
                            all_tables.append(cleaned_table)
            doc.close()
        except Exception as exc:
            logger.debug("PyMuPDF table extraction fallback error: %s", exc)

        return all_tables

    @classmethod
    def extract_profile_photo(cls, pdf_bytes_or_path, min_size: int = 80, max_size: int = 1400) -> Optional[bytes]:
        """
        Detects and extracts the candidate's portrait photo from a German CV.
        Distinguishes portrait avatars from full-page backgrounds and tiny icons.
        """
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        if not pdf_bytes:
            return None
        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            candidate_images = []

            for page_idx in range(min(2, len(doc))):
                page = doc[page_idx]
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    base_image = doc.extract_image(xref)
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    img_bytes = base_image.get("image")

                    if not img_bytes or width < min_size or height < min_size:
                        continue
                    if width > max_size and height > max_size:
                        continue

                    ratio = width / max(1, height)
                    if 0.5 <= ratio <= 1.4:
                        candidate_images.append({
                            "bytes": img_bytes,
                            "width": width,
                            "height": height,
                        })
            doc.close()

            if candidate_images:
                candidate_images.sort(key=lambda x: (x["width"] * x["height"]), reverse=True)
                return candidate_images[0]["bytes"]
        except Exception as exc:
            logger.debug("Photo extraction failed: %s", exc)

        return None

    @classmethod
    def render_pdf_thumbnail(cls, pdf_bytes_or_path, page_num: int = 0, dpi: int = 150) -> Optional[bytes]:
        """
        Renders a page of a PDF document into high-resolution PNG image bytes.
        Fast (~10ms) local rendering without headless browser dependencies.
        """
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        if not pdf_bytes:
            return None
        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            if 0 <= page_num < len(doc):
                pix = doc[page_num].get_pixmap(dpi=dpi)
                png_bytes = pix.tobytes("png")
                doc.close()
                return png_bytes
            doc.close()
        except Exception as exc:
            logger.warning("Failed rendering PDF thumbnail via PyMuPDF: %s", exc)

        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if 0 <= page_num < len(pdf.pages):
                    img = pdf.pages[page_num].to_image(resolution=dpi)
                    out = io.BytesIO()
                    img.save(out, format="PNG")
                    return out.getvalue()
        except Exception as exc:
            logger.debug("pdfplumber thumbnail fallback failed: %s", exc)

        # Tier 3: PIL Text-based Thumbnail Fallback (ensures valid PNG output even without PyMuPDF)
        try:
            from PIL import Image, ImageDraw
            reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
            if 0 <= page_num < len(reader.pages):
                page_txt = reader.pages[page_num].extract_text() or "Document Preview"
                w, h = int(8.27 * dpi), int(11.69 * dpi)
                img = Image.new("RGB", (w, h), color=(255, 255, 255))
                draw = ImageDraw.Draw(img)
                y = 20
                for line in page_txt.split("\n")[:40]:
                    clean_line = line.strip()[:80]
                    if clean_line:
                        draw.text((20, y), clean_line, fill=(30, 30, 30))
                        y += 20
                out = io.BytesIO()
                img.save(out, format="PNG")
                return out.getvalue()
        except Exception as pil_err:
            logger.debug("PIL thumbnail fallback failed: %s", pil_err)

        return None

    @classmethod
    def extract_cv_metadata(cls, pdf_bytes_or_path) -> Dict[str, Any]:
        """
        Extracts technical PDF metadata: page count, author, creation date, has_images, is_encrypted.
        """
        pdf_bytes = cls._get_pdf_bytes(pdf_bytes_or_path)
        meta = {
            "page_count": 0,
            "title": "",
            "author": "",
            "creator": "",
            "has_images": False,
            "has_text": False,
            "file_size": len(pdf_bytes) if pdf_bytes else 0,
        }
        if not pdf_bytes:
            return meta

        try:
            import pymupdf
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            meta["page_count"] = len(doc)
            d_meta = doc.metadata or {}
            meta["title"] = d_meta.get("title") or ""
            meta["author"] = d_meta.get("author") or ""
            meta["creator"] = d_meta.get("creator") or ""

            image_count = 0
            for page in doc:
                image_count += len(page.get_images())
                if page.get_text().strip():
                    meta["has_text"] = True
            meta["has_images"] = image_count > 0
            doc.close()
        except Exception as exc:
            logger.debug("Metadata extraction error: %s", exc)

        # Fallback to standard pypdf if PyMuPDF unavailable or page_count == 0
        if meta["page_count"] == 0:
            try:
                reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
                meta["page_count"] = len(reader.pages)
                if reader.metadata:
                    meta["title"] = str(reader.metadata.get("/Title") or "")
                    meta["author"] = str(reader.metadata.get("/Author") or "")
                    meta["creator"] = str(reader.metadata.get("/Creator") or "")
                for p in reader.pages:
                    try:
                        txt = p.extract_text()
                        if txt and txt.strip():
                            meta["has_text"] = True
                            break
                    except Exception:
                        pass
            except Exception as pe:
                logger.debug("pypdf metadata fallback failed: %s", pe)

        return meta

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
        # Clean institutional residue or false street artifacts
        if addr.get("postal_code") == "53117" or addr.get("city") == "Bonn" or addr.get("street") == "ISTA":
            addr["postal_code"] = ""
            addr["street"] = ""
            addr["house_number"] = ""
        for fld in ["street", "house_number", "postal_code", "city", "country", "country_code"]:
            if fld in parsed_addr:
                addr[fld] = parsed_addr[fld]

        # Merge socials
        for social_key in ["linkedin", "portfolio", "github"]:
            if parsed_contact.get(social_key, {}).get("url"):
                s_obj = contact.setdefault(social_key, {})
                s_obj["url"] = parsed_contact[social_key]["url"]

        # Merge professional profile
        prof = applicant.setdefault("professional_profile", {})
        parsed_prof = parsed_data.get("professional_profile", {})
        if parsed_prof.get("current_title") and (not prof.get("current_title") or prof.get("current_title") in ["Bewerber", "fachinformatiker", "serfahrung"]):
            prof["current_title"] = parsed_prof["current_title"]
        if parsed_prof.get("headline") and (not prof.get("headline") or "Bewerber" in prof.get("headline", "") or "serfahrung" in prof.get("headline", "")):
            prof["headline"] = parsed_prof["headline"]
        if parsed_prof.get("summary_de") and not prof.get("summary_de"):
            prof["summary_de"] = parsed_prof["summary_de"]
        if parsed_prof.get("primary_fields") and not prof.get("primary_fields"):
            prof["primary_fields"] = parsed_prof["primary_fields"]
        if "years_of_experience" in parsed_prof:
            prof["years_of_experience"] = parsed_prof["years_of_experience"]
        if "experience_level" in parsed_prof:
            prof["experience_level"] = parsed_prof["experience_level"]
        if parsed_prof.get("target_occupation"):
            prof["target_occupation"] = parsed_prof["target_occupation"]
        elif not prof.get("target_occupation"):
            orig = existing.get("metadata", {}).get("original_field") or ""
            if orig:
                clean_target = re.sub(r"(?i)^ausbildung\s+als\s+", "", orig).strip()
                prof["target_occupation"] = clean_target.capitalize() if clean_target else clean_target

        # Merge work experience
        if parsed_data.get("work_experience"):
            applicant["work_experience"] = parsed_data["work_experience"]

        # Merge education
        if parsed_data.get("education"):
            applicant["education"] = parsed_data["education"]

        # Merge certifications
        if parsed_data.get("certifications"):
            applicant["certifications"] = parsed_data["certifications"]

        # Merge extraction metadata
        if parsed_data.get("extraction_metadata"):
            applicant["extraction_metadata"] = parsed_data["extraction_metadata"]

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
