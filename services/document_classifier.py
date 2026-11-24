"""
Multi-Document Dossier Classifier and Page-Level Intelligence.
Detects document boundaries within multi-page PDF dossiers (e.g., CV vs. institutional
evaluations like ZAB, diplomas, certificates, and certified translations).
Enforces address guardrails so third-party institutional addresses are never assigned to candidates.
"""

import io
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pypdf import PdfReader

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    CV = "cv"
    INSTITUTIONAL = "institutional"
    DIPLOMA = "diploma"
    CERTIFICATE = "certificate"
    TRANSLATION = "translation"
    UNKNOWN = "unknown"


# Known third-party institutional address signatures that must NEVER be assigned to candidate
INSTITUTIONAL_SIGNATURES: List[Dict[str, Any]] = [
    {
        "name": "Zentralstelle für ausländisches Bildungswesen (ZAB) / KMK",
        "patterns": [
            r"graurheindorfer\s+str(?:\.|a[ßs]e)?\s*157",
            r"53117\s+bonn",
            r"zabdigitaleauskunft@kmk\.org",
            r"kmk\.org/zab",
            r"anabin\.kmk\.org",
        ],
        "blocked_address": {
            "street": "Graurheindorfer Str.",
            "house_number": "157",
            "postal_code": "53117",
            "city": "Bonn",
        },
    },
    {
        "name": "Bundesagentur für Arbeit",
        "patterns": [
            r"regensburger\s+str(?:\.|a[ßs]e)?\s*104",
            r"90478\s+n[üu]rnberg",
            r"arbeitsagentur\.de",
        ],
        "blocked_address": {
            "street": "Regensburger Str.",
            "house_number": "104",
            "postal_code": "90478",
            "city": "Nürnberg",
        },
    },
    {
        "name": "Telc gGmbH",
        "patterns": [
            r"baseler\s+str(?:\.|a[ßs]e)?",
            r"60329\s+frankfurt",
            r"telc\.net",
        ],
        "blocked_address": {
            "postal_code": "60329",
            "city": "Frankfurt",
        },
    },
    {
        "name": "Goethe-Institut",
        "patterns": [
            r"oskar-von-miller-ring",
            r"80333\s+m[üu]nchen",
            r"goethe\.de",
        ],
        "blocked_address": {
            "postal_code": "80333",
            "city": "München",
        },
    },
    {
        "name": "Behörde für Schule und Berufsbildung Hamburg / Zeugnisanerkennung",
        "patterns": [
            r"freie\s+und\s+hansestadt\s+hamburg",
            r"beh[öo]rde\s+f[üu]r\s+schule",
            r"auslandszeugnisse",
            r"22060\s+hamburg",
            r"hamburger\s+stra[ßs]e\s*131",
        ],
        "blocked_address": {
            "postal_code": "22060",
            "city": "Hamburg",
        },
    },
]


class DocumentClassifier:
    """Classifies pages in a multi-document PDF and segments the candidate CV."""

    @classmethod
    def _read_pdf_pages(cls, pdf_bytes_or_path: Union[bytes, str, Path]) -> List[str]:
        """Extracts text page by page from PDF using PyMuPDF (Tier 1) and pypdf (Tier 2)."""
        if isinstance(pdf_bytes_or_path, (str, Path)):
            with open(pdf_bytes_or_path, "rb") as f:
                data = f.read()
        else:
            data = bytes(pdf_bytes_or_path)

        pages_text: List[str] = []
        if not data:
            return pages_text

        # Tier 1: PyMuPDF (Fast, accurate C engine, eliminates character spacing issues)
        try:
            import pymupdf
            doc = pymupdf.open(stream=data, filetype="pdf")
            for page in doc:
                pages_text.append(page.get_text() or "")
            doc.close()
            if any(p.strip() for p in pages_text):
                return pages_text
        except Exception as fitz_err:
            logger.debug("PyMuPDF page extraction failed: %s", fitz_err)

        # Tier 2: pypdf fallback
        pages_text = []
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            for page in reader.pages:
                try:
                    txt = page.extract_text() or ""
                    pages_text.append(txt)
                except Exception as pe:
                    logger.debug("Failed to extract page text: %s", pe)
                    pages_text.append("")
        except Exception as e:
            logger.warning("pypdf reading failed: %s", e)

        return pages_text

    @classmethod
    def classify_page(cls, text: str, page_num: int) -> Dict[str, Any]:
        """
        Classifies an individual page based on structural keywords, headers, and institutional markers.
        Returns document type, confidence, and detected institutional entities.
        """
        txt_lower = text.lower()
        txt_stripped = text.strip()

        if not txt_stripped:
            return {
                "page": page_num,
                "type": DocumentType.UNKNOWN,
                "confidence": 0.0,
                "is_cv": False,
                "title": "Empty Page",
                "matched_markers": [],
            }

        scores: Dict[DocumentType, float] = {
            DocumentType.CV: 0.0,
            DocumentType.INSTITUTIONAL: 0.0,
            DocumentType.DIPLOMA: 0.0,
            DocumentType.CERTIFICATE: 0.0,
            DocumentType.TRANSLATION: 0.0,
        }
        matched: Dict[DocumentType, List[str]] = {t: [] for t in DocumentType}

        # --- CV Markers ---
        cv_strong_headers = [
            "berufserfahrung", "beruflicher werdegang", "persönliche daten",
            "curriculum vitae", "lebenslauf", "work experience", "kurzprofil",
            "ausbildung", "technologien", "sprachen", "kenntnisse und fähigkeiten",
            "schulausbildung", "praktika", "projekte", "skills"
        ]
        for h in cv_strong_headers:
            if re.search(rf"\b{re.escape(h)}\b", txt_lower):
                scores[DocumentType.CV] += 1.5
                matched[DocumentType.CV].append(h)

        # Contact line signatures (phone + email + city/country)
        if re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", txt_lower):
            if any(contact_kw in txt_lower for contact_kw in ["tel", "phone", "linkedin", "github", "portfolio", "morocco", "marokko", "deutschland", "germany"]):
                scores[DocumentType.CV] += 2.0
                matched[DocumentType.CV].append("contact_header")

        # Layout cue: Date ranges typical for CV timeline (e.g. 11.2025 - heute, 09/2022 - 07/2024, 2021 - 2022)
        date_range_count = len(re.findall(r"\b(?:\d{2}[./])?\d{4}\s*[-–—]\s*(?:heute|present|\d{2}[./]\d{4}|\d{4})\b", txt_lower))
        if date_range_count >= 2:
            scores[DocumentType.CV] += min(date_range_count * 0.8, 4.0)
            matched[DocumentType.CV].append(f"{date_range_count}_timeline_entries")

        # --- Institutional Evaluation Markers (ZAB, KMK, Government bodies) ---
        inst_markers = [
            ("graurheindorfer", 3.0),
            ("53117 bonn", 3.0),
            ("auskunft zur berufsqualifikation", 4.0),
            ("zentralstelle für ausländisches bildungswesen", 4.0),
            ("zab", 2.0),
            ("anabin", 2.0),
            ("kmk.org", 2.0),
            ("titelerteilenden stelle", 2.5),
            ("aufenthg", 2.0),
            ("beschv", 2.0),
            ("siegelplatzhalter", 3.0),
            ("digitales siegel", 2.5),
            ("apostille", 3.0),
            ("bezirksregierung", 3.0),
            ("minister", 2.0),
            ("reg.-nr.", 2.0),
        ]
        for kw, weight in inst_markers:
            if kw in txt_lower:
                scores[DocumentType.INSTITUTIONAL] += weight
                matched[DocumentType.INSTITUTIONAL].append(kw)

        # --- Translation Markers ---
        trans_markers = [
            ("übersetzung", 3.0),
            ("aus der arabischen sprache", 3.5),
            ("aus der französischen sprache", 3.5),
            ("traduction", 3.0),
            ("traducteur assermenté", 3.5),
            ("vereidigter übersetzer", 3.5),
            ("richtigkeit und vollständigkeit der übersetzung", 4.0),
            ("beglaubigte abschrift", 3.0),
            ("original lag vor", 3.0),
            ("stempel:", 2.0),
            ("unterschrift:", 2.0),
        ]
        for kw, weight in trans_markers:
            if kw in txt_lower:
                scores[DocumentType.TRANSLATION] += weight
                matched[DocumentType.TRANSLATION].append(kw)

        # --- Diploma / Degree Markers ---
        diploma_markers = [
            ("diplôme", 3.0),
            ("diplom", 3.0),
            ("baccalauréat", 3.0),
            ("zeugnis der allgemeinen hochschulreife", 3.5),
            ("ofppt", 3.0),
            ("technicien spécialisé", 3.0),
            ("attestation de réussite", 3.0),
            ("relevé de notes", 3.0),
            ("royaume du maroc", 2.5),
            ("universität", 2.0),
            ("université", 2.0),
            ("exzellenz-lizenz", 3.0),
        ]
        for kw, weight in diploma_markers:
            if kw in txt_lower:
                scores[DocumentType.DIPLOMA] += weight
                matched[DocumentType.DIPLOMA].append(kw)

        # --- Certificate Markers ---
        cert_markers = [
            ("course certificate", 3.5),
            ("certificate of completion", 3.5),
            ("teilnahmebescheinigung", 3.0),
            ("telc deutsch", 3.5),
            ("goethe-zertifikat", 3.5),
            ("cisco networking academy", 3.5),
            ("python essentials", 3.0),
            ("has successfully completed", 3.0),
        ]
        for kw, weight in cert_markers:
            if kw in txt_lower:
                scores[DocumentType.CERTIFICATE] += weight
                matched[DocumentType.CERTIFICATE].append(kw)

        # Determine winner
        top_type = DocumentType.UNKNOWN
        top_score = 0.0
        for dtype, sc in scores.items():
            if sc > top_score:
                top_score = sc
                top_type = dtype

        confidence = min(top_score / 6.0, 1.0)
        is_cv = (top_type == DocumentType.CV and confidence >= 0.4)

        return {
            "page": page_num,
            "type": top_type,
            "confidence": round(confidence, 3),
            "is_cv": is_cv,
            "score": round(top_score, 2),
            "matched_markers": matched[top_type],
        }

    @classmethod
    def classify_dossier(
        cls,
        pdf_bytes_or_path: Union[bytes, str, Path],
    ) -> Dict[str, Any]:
        """
        Analyzes a multi-page PDF dossier:
        1. Classifies each page.
        2. Discovers the primary CV page range (never assumes page 1).
        3. Isolates institutional addresses to prevent false assignment to candidate.
        4. Extracts separated texts: `cv_text` vs `supporting_documents_text`.
        """
        raw_pages = cls._read_pdf_pages(pdf_bytes_or_path)
        total_pages = len(raw_pages)

        classified_pages: List[Dict[str, Any]] = []
        cv_page_indices: List[int] = []
        institutional_page_indices: List[int] = []
        blacklisted_addresses: List[Dict[str, Any]] = []

        for idx, p_text in enumerate(raw_pages):
            p_res = cls.classify_page(p_text, idx + 1)
            classified_pages.append(p_res)

            if p_res["is_cv"]:
                cv_page_indices.append(idx)
            elif p_res["type"] == DocumentType.INSTITUTIONAL:
                institutional_page_indices.append(idx)

            # Check for institutional address patterns on this page
            for sig in INSTITUTIONAL_SIGNATURES:
                if any(re.search(pat, p_text, re.IGNORECASE) for pat in sig["patterns"]):
                    blacklisted_addresses.append(sig["blocked_address"])

        # Fallback if no page met CV confidence threshold:
        # Score pages by presence of contact info + experience/education
        if not cv_page_indices and raw_pages:
            best_idx = 0
            best_score = -1.0
            for idx, p_res in enumerate(classified_pages):
                # Never treat clear institutional or translation pages as CV fallback
                if p_res["type"] in {DocumentType.INSTITUTIONAL, DocumentType.TRANSLATION}:
                    continue
                score = p_res.get("score", 0.0)
                if score > best_score:
                    best_score = score
                    best_idx = idx
            cv_page_indices = [best_idx]
            classified_pages[best_idx]["is_cv"] = True
            classified_pages[best_idx]["type"] = DocumentType.CV

        # Assemble separate texts
        cv_text_parts = [raw_pages[i] for i in cv_page_indices if i < len(raw_pages)]
        supporting_text_parts = [
            raw_pages[i]
            for i in range(total_pages)
            if i not in cv_page_indices
        ]

        cv_text = "\n\n".join(cv_text_parts).strip()
        supporting_text = "\n\n".join(supporting_text_parts).strip()

        return {
            "total_pages": total_pages,
            "cv_page_indices": cv_page_indices,
            "cv_page_numbers": [i + 1 for i in cv_page_indices],
            "cv_text": cv_text,
            "supporting_text": supporting_text,
            "classified_pages": classified_pages,
            "institutional_page_indices": institutional_page_indices,
            "blacklisted_addresses": blacklisted_addresses,
            "is_multi_document": total_pages > 1 and len(cv_page_indices) < total_pages,
        }
