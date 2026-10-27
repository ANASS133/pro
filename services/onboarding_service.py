"""
Candidate Onboarding Pipeline for JobScout.
Securely converts paid Supabase applications into persistent, collision-free
JobScout candidate dossiers, downloading submitted documents, parsing CVs,
associating purchased application packages, and synchronizing autofill profiles.
"""

import copy
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.client_manager import ClientManager, _slugify, client_manager
from services.cv_parser import CVParser
from services.onboarding_tracker import OnboardingStatus, onboarding_tracker
from services.supabase_service import (
    ApplicationNotFoundError,
    DocumentDownloadError,
    PaymentUnverifiedError,
    SupabaseServiceError,
    supabase_service,
)

logger = logging.getLogger(__name__)

# Standard Server-Defined Packages Configuration
STANDARD_PACKAGES: Dict[str, Dict[str, Any]] = {
    "500 bewerbung": {"name": "500 Bewerbung", "total_limit": 500},
    "500": {"name": "500 Bewerbung", "total_limit": 500},
    "1000 bewerbung": {"name": "1000 Bewerbung", "total_limit": 1000},
    "1000": {"name": "1000 Bewerbung", "total_limit": 1000},
    "2000 bewerbung": {"name": "2000 Bewerbung", "total_limit": 2000},
    "2000": {"name": "2000 Bewerbung", "total_limit": 2000},
}


class CandidateOnboardingService:
    """Orchestrates candidate onboarding from paid Supabase applications."""

    def __init__(
        self,
        client_manager: Optional[ClientManager] = None,
        supabase_service: Optional[SupabaseService] = None,
        cv_parser: Optional[CVParser] = None,
        tracker: Optional[OnboardingTracker] = None,
        manager: Optional[ClientManager] = None,
    ):
        self.client_manager = client_manager or manager or globals().get("client_manager")
        self.supabase_service = supabase_service or globals().get("supabase_service")
        self.cv_parser = cv_parser or CVParser()
        self.tracker = tracker or onboarding_tracker
        self._application_locks: Dict[str, threading.Lock] = {}
        self._master_lock = threading.Lock()

    def _get_app_lock(self, application_id: str) -> threading.Lock:
        with self._master_lock:
            if application_id not in self._application_locks:
                self._application_locks[application_id] = threading.Lock()
            return self._application_locks[application_id]

    def onboard_candidate(
        self,
        application_id: str,
        force_reimport: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end candidate onboarding:
        1. Retrieves application from Supabase.
        2. Validates payment status (strictly rejects unverified payment).
        3. Enforces idempotency (prevents duplicate dossier creation).
        4. Downloads and classifies all submitted documents.
        5. Parses CV with multi-tier error tolerance.
        6. Merges form data (authoritative contact) with CV data (skills/experience).
        7. Associates normalized package quota.
        8. Persists candidate dossier & mirrors to Autofill Hub without altering global active candidate.
        """
        clean_app_id = str(application_id or "").strip()
        if not clean_app_id:
            raise ValueError("Application ID is required.")

        app_lock = self._get_app_lock(clean_app_id)
        with app_lock:
            # 1. Check existing onboarding state (Idempotency)
            existing_record = self.tracker.get_record(clean_app_id)
            if existing_record and not force_reimport:
                if existing_record.get("status") in {OnboardingStatus.READY, OnboardingStatus.PROFILE_REVIEW_REQUIRED}:
                    client_id = existing_record.get("client_id")
                    if client_id and self.client_manager.get_client(client_id):
                        logger.info("Application %s already onboarded as %s (idempotent return)", clean_app_id, client_id)
                        return {
                            "success": True,
                            "client_id": client_id,
                            "supabase_application_id": clean_app_id,
                            "onboarding_status": existing_record.get("status"),
                            "documents_imported": existing_record.get("document_count", 0),
                            "cv_parsed": existing_record.get("cv_parsed", False),
                            "missing_fields": existing_record.get("missing_fields", []),
                            "profile_ready": existing_record.get("profile_ready", False),
                            "client_name": existing_record.get("client_name", ""),
                            "package": existing_record.get("package", {}),
                            "already_imported": True,
                        }

            # Set in-progress status
            self.tracker.set_status(clean_app_id, OnboardingStatus.IMPORTING)

            try:
                # 2. Fetch application from Supabase
                application = self.supabase_service.get_application(clean_app_id)

                # 3. Verify Payment
                # CRITICAL: Onboarding must NEVER set is_payed = true automatically!
                is_payed = bool(application.get("is_payed"))
                if not is_payed:
                    self.tracker.set_status(
                        clean_app_id,
                        OnboardingStatus.PENDING_PAYMENT,
                        last_error="Payment has not been verified for this application.",
                    )
                    raise PaymentUnverifiedError(
                        f"Cannot onboard application '{clean_app_id}': Payment is pending and has not been verified."
                    )

                full_name = str(application.get("full_name") or "").strip()
                email = str(application.get("email") or "").strip()
                whatsapp = str(application.get("whatsapp") or "").strip()
                field_label = str(application.get("field") or "").strip()
                lang_level = str(application.get("language_level") or "").strip()
                pack_label = str(application.get("pack") or "").strip()

                if not full_name:
                    full_name = "Bewerber"

                # 4. Normalize Package Quota
                package_info = self._normalize_package(pack_label)
                package_info["bank"] = application.get("bank", "")
                package_info["promo_code"] = application.get("code")
                package_info["payment_verified"] = True

                # 5. Resolve Collision-Resistant Client ID
                client_id = self._resolve_client_id(full_name, clean_app_id)

                # 6. Retrieve and Classify Documents
                raw_documents = application.get("documents") or []
                if isinstance(raw_documents, str):
                    raw_documents = [raw_documents]

                imported_docs: List[Dict[str, Any]] = []
                cv_bytes: Optional[bytes] = None
                cv_filename: Optional[str] = None
                cv_extracted_text: str = ""

                # Download all permitted files
                downloaded_files: List[Tuple[bytes, str, str, str]] = []  # (bytes, clean_name, mime, storage_path)
                for storage_path in raw_documents:
                    if not storage_path or not isinstance(storage_path, str):
                        continue
                    try:
                        f_bytes, clean_name, mime = self.supabase_service.get_document_bytes(storage_path)
                        downloaded_files.append((f_bytes, clean_name, mime, storage_path))
                    except Exception as doc_err:
                        logger.warning("Could not download document %s for app %s: %s", storage_path, clean_app_id, doc_err)

                # Identify the CV document intelligently
                cv_index = self._identify_cv_document(downloaded_files)

                # Save documents into candidate dossier
                for idx, (f_bytes, clean_name, mime, orig_path) in enumerate(downloaded_files):
                    is_cv = (idx == cv_index)
                    assigned_name = clean_name

                    if is_cv:
                        cv_bytes = f_bytes
                        cv_filename = clean_name
                        # Standardize primary CV file name
                        assigned_name = "Lebenslauf.pdf" if clean_name.lower().endswith(".pdf") else clean_name

                    doc_record = self.client_manager.save_document(client_id, f_bytes, assigned_name)
                    if doc_record:
                        doc_record["is_cv"] = is_cv
                        doc_record["original_storage_path"] = orig_path
                        imported_docs.append(doc_record)

                # 7. Parse CV
                cv_parsed = False
                parsed_cv_data: Dict[str, Any] = {}

                if cv_bytes:
                    try:
                        cv_extracted_text = self.cv_parser.extract_text_from_pdf(cv_bytes)
                        if cv_extracted_text:
                            parsed_cv_data = self.cv_parser.parse_cv_text(cv_extracted_text)
                            cv_parsed = True
                    except Exception as parse_err:
                        logger.warning("Error parsing CV for application %s: %s", clean_app_id, parse_err)

                # 8. Merge Form (Authoritative) + CV Parser Data
                profile_data, missing_fields = self._build_candidate_profile(
                    application=application,
                    parsed_cv=parsed_cv_data,
                    package_info=package_info,
                    application_id=clean_app_id,
                )
                if not cv_bytes:
                    missing_fields.append("cv_document")

                # 9. Save Profile & Synchronize
                self.client_manager.save_client(client_id, profile_data)

                # 10. Determine Final Status
                final_status = (
                    OnboardingStatus.PROFILE_REVIEW_REQUIRED
                    if missing_fields
                    else OnboardingStatus.READY
                )

                # 11. Record Persistent Onboarding State
                record = self.tracker.set_status(
                    application_id=clean_app_id,
                    status=final_status,
                    client_id=client_id,
                    client_name=full_name,
                    payment_verified=True,
                    document_count=len(imported_docs),
                    cv_document=cv_filename,
                    cv_parsed=cv_parsed,
                    missing_fields=missing_fields,
                    package=package_info,
                    profile_ready=(final_status == OnboardingStatus.READY),
                )

                # Non-blocking metadata synchronization to Supabase if schema permits
                try:
                    self.supabase_service.update_application(
                        clean_app_id,
                        {
                            "onboarding_status": final_status,
                            "jobscout_client_id": client_id,
                            "onboarded_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except Exception:
                    pass

                logger.info(
                    "Successfully onboarded candidate '%s' (ID: %s) from application %s with status %s",
                    full_name,
                    client_id,
                    clean_app_id,
                    final_status,
                )

                return {
                    "success": True,
                    "client_id": client_id,
                    "supabase_application_id": clean_app_id,
                    "onboarding_status": final_status,
                    "documents_imported": len(imported_docs),
                    "cv_parsed": cv_parsed,
                    "missing_fields": missing_fields,
                    "profile_ready": (final_status == OnboardingStatus.READY),
                    "client_name": full_name,
                    "package": package_info,
                }

            except PaymentUnverifiedError:
                # Do not overwrite PENDING_PAYMENT status
                raise
            except Exception as exc:
                self.tracker.set_status(
                    clean_app_id,
                    OnboardingStatus.IMPORT_FAILED,
                    last_error=str(exc),
                )
                logger.error("Failed onboarding application %s: %s", clean_app_id, exc, exc_info=True)
                raise

    def _resolve_client_id(self, full_name: str, application_id: str) -> str:
        """
        Determines a clean, collision-free candidate directory slug.
        Ensures candidates with the same name from different applications never collide.
        """
        base_slug = _slugify(full_name)
        if not base_slug or base_slug in {"bewerber", "kandidat", "client"}:
            base_slug = f"client_{application_id[:8]}"

        existing_profile = self.client_manager.get_client(base_slug)
        if not existing_profile:
            return base_slug

        # Check if existing dossier belongs to this exact Supabase application
        existing_app_id = (
            existing_profile.get("metadata", {}).get("supabase_application_id")
            or existing_profile.get("applicant", {}).get("metadata", {}).get("supabase_application_id")
        )
        if existing_app_id == application_id:
            return base_slug

        # Different application with same candidate name -> append unique collision suffix
        suffix = application_id.replace("-", "")[:6].lower()
        return f"{base_slug}_{suffix}"

    def _identify_cv_document(
        self,
        downloaded_files: List[Tuple[bytes, str, str, str]],
    ) -> int:
        """
        Identifies which document is the CV using filename heuristics and text analysis.
        Returns the index in downloaded_files, or -1 if none found.
        """
        if not downloaded_files:
            return -1

        # Tier 1: Strong filename match
        cv_keywords = ["lebenslauf", "curriculum", "resume", "cv"]
        for idx, (_, name, _, _) in enumerate(downloaded_files):
            name_lower = name.lower()
            if any(k in name_lower for k in cv_keywords):
                return idx

        # Tier 2: Content inspection (extract text from PDFs and score CV markers)
        best_idx = -1
        highest_score = 0

        cv_markers = [
            "berufserfahrung", "ausbildung", "schulausbildung", "kenntnisse",
            "beruflicher werdegang", "persönliche daten", "sprachen", "qualifikationen",
            "work experience", "education", "curriculum vitae", "skills",
        ]

        for idx, (f_bytes, name, _, _) in enumerate(downloaded_files):
            if not name.lower().endswith(".pdf"):
                continue
            try:
                text = CVParser.extract_text_from_pdf(f_bytes).lower()
                score = sum(1 for m in cv_markers if m in text)
                if score > highest_score:
                    highest_score = score
                    best_idx = idx
            except Exception:
                pass

        if highest_score >= 2:
            return best_idx

        # Tier 3: First PDF file fallback
        for idx, (_, name, _, _) in enumerate(downloaded_files):
            if name.lower().endswith(".pdf"):
                return idx

        return 0 if downloaded_files else -1

    def _normalize_package(self, pack_label: str) -> Dict[str, Any]:
        """Normalizes submitted package string against server definitions."""
        clean_label = str(pack_label or "").strip()
        key = clean_label.lower()

        if key in STANDARD_PACKAGES:
            cfg = STANDARD_PACKAGES[key]
            return {
                "name": cfg["name"],
                "total_limit": cfg["total_limit"],
                "confirmed_applications": 0,
                "remaining": cfg["total_limit"],
                "original_label": clean_label,
            }

        # Fallback numeric extraction (e.g. "500 Bewerbungen" -> 500)
        digits = re.findall(r"\d+", clean_label)
        total_limit = int(digits[0]) if digits else 500
        name = f"{total_limit} Bewerbung"

        return {
            "name": name,
            "total_limit": total_limit,
            "confirmed_applications": 0,
            "remaining": total_limit,
            "original_label": clean_label,
        }

    def _build_candidate_profile(
        self,
        application: Dict[str, Any],
        parsed_cv: Dict[str, Any],
        package_info: Dict[str, Any],
        application_id: str,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Merges authoritative form submission data with rich parsed CV data.
        Returns: (profile_data, missing_fields)
        """
        missing_fields: List[str] = []

        # Form data is authoritative for contact & names
        full_name = str(application.get("full_name") or "").strip()
        email = str(application.get("email") or "").strip()
        whatsapp = str(application.get("whatsapp") or "").strip()
        field_label = str(application.get("field") or "").strip()
        lang_level = str(application.get("language_level") or "").strip()

        # Split full name into first and last name
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        # Extract CV parsed data
        cv_personal = parsed_cv.get("personal", {})
        cv_contact = parsed_cv.get("contact", {})
        cv_address = cv_contact.get("address", {})
        cv_prof = parsed_cv.get("professional_profile", {})
        cv_skills = parsed_cv.get("skills", {})
        cv_languages = parsed_cv.get("languages", [])

        # Address resolution
        city = cv_address.get("city", "")
        street = cv_address.get("street", "")
        house_number = cv_address.get("house_number", "")
        postal_code = cv_address.get("postal_code", "")

        # Target profession / title
        current_title = ""
        if field_label:
            # Clean up field string (e.g. "ausbildung als Fachmann..." -> "Fachmann...")
            clean_field = re.sub(r"(?i)^ausbildung\s+als\s+", "", field_label).strip()
            current_title = clean_field
        if not current_title:
            current_title = cv_prof.get("current_title") or "Bewerber"

        # Languages array compilation
        languages = copy.deepcopy(cv_languages)
        if lang_level:
            # Check if German already in languages
            de_entry = next((item for item in languages if item.get("language", "").lower() in {"deutsch", "german"}), None)
            if de_entry:
                de_entry["level"] = lang_level
            else:
                languages.insert(0, {
                    "language": "Deutsch",
                    "code": "de",
                    "level": lang_level,
                    "proficiency_category": "intermediate" if lang_level in {"B1", "B2"} else "advanced",
                })

        # Core missing field checks
        if not city:
            missing_fields.append("city")
        if not cv_personal.get("date_of_birth"):
            missing_fields.append("date_of_birth")

        # Assemble canonical profile JSON conforming to ClientManager format
        profile = {
            "profile_version": "1.0",
            "profile_language": "de",
            "metadata": {
                "supabase_application_id": application_id,
                "source": "supabase_onboarding",
                "onboarded_at": datetime.now(timezone.utc).isoformat(),
                "original_field": field_label,
            },
            "package": package_info,
            "applicant": {
                "personal": {
                    "first_name": first_name or cv_personal.get("first_name", ""),
                    "last_name": last_name or cv_personal.get("last_name", ""),
                    "full_name": full_name or cv_personal.get("full_name", ""),
                    "date_of_birth": cv_personal.get("date_of_birth") or "",
                    "date_of_birth_display": cv_personal.get("date_of_birth_display") or "",
                    "place_of_birth": cv_personal.get("place_of_birth") or "",
                    "nationality": cv_personal.get("nationality") or "Marokkanisch",
                    "salutation": cv_personal.get("salutation") or "Herr",
                    "gender": cv_personal.get("gender") or "male",
                },
                "contact": {
                    "email": email or cv_contact.get("email", ""),
                    "phone": whatsapp or cv_contact.get("phone", ""),
                    "phone_display": whatsapp or cv_contact.get("phone_display", ""),
                    "address": {
                        "street": street,
                        "house_number": house_number,
                        "postal_code": postal_code,
                        "city": city or "Koeln",
                        "country": cv_address.get("country", "Deutschland"),
                        "country_code": cv_address.get("country_code", "DE"),
                    },
                    "linkedin": cv_contact.get("linkedin", {}),
                    "portfolio": cv_contact.get("portfolio", {}),
                    "github": cv_contact.get("github", {}),
                },
                "professional_profile": {
                    "current_title": current_title,
                    "headline": cv_prof.get("headline") or f"{full_name} | {current_title}",
                    "summary_de": cv_prof.get("summary_de") or f"Motivierter Bewerber für {current_title}.",
                    "primary_fields": cv_prof.get("primary_fields") or [current_title],
                },
                "skills": cv_skills,
                "languages": languages,
            },
        }

        return profile, missing_fields


# Global service singleton
candidate_onboarding_service = CandidateOnboardingService()
