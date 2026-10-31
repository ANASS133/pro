"""
Multi-Client Dossier Manager Service.
Manages candidate profiles, documents, CV ingestion, and active client tracking.
Maintains bi-directional compatibility with ai-job-autofill/server/profiles/.
"""

import io
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import DATA_DIR
from services.cv_parser import CVParser

logger = logging.getLogger(__name__)

CLIENTS_DIR = DATA_DIR / "clients"
ACTIVE_CLIENT_FILE = DATA_DIR / "active_client.json"

BASE_DIR = Path(__file__).resolve().parent.parent
AUTOFILL_PROFILES_DIR = BASE_DIR / "ai-job-autofill" / "server" / "profiles"

SUPPORTED_DOC_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".txt"}


def _slugify(text: str) -> str:
    """Creates a clean alphanumeric ID from a name."""
    clean = re.sub(r"[^\w\s-]", "", str(text or "").lower()).strip()
    slug = re.sub(r"[-\s]+", "_", clean)
    return slug or "client"


def _extract_name_from_filename(filename: str) -> str:
    """Extracts a plausible candidate name from the uploaded PDF filename."""
    if not filename:
        return ""
    name = re.sub(r"(?i)\.pdf$", "", filename)
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"(?i)\b(lebenslauf|resume|curriculum|vitae|cv|bewerbung|profil|aktuelle|dokument|document)\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    words = [w for w in name.split() if w.isalpha() and len(w) > 1]
    if len(words) >= 2:
        return " ".join(w.capitalize() for w in words[:3])
    elif len(words) == 1:
        return words[0].capitalize()
    return ""


class ClientManager:
    """Manages multi-client applicant dossiers, CV parsing, and active client state."""

    def __init__(self, clients_dir: Path = CLIENTS_DIR, autofill_dir: Path = AUTOFILL_PROFILES_DIR):
        self.clients_dir = Path(clients_dir)
        self.autofill_dir = Path(autofill_dir)
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        self.autofill_dir.mkdir(parents=True, exist_ok=True)
        self._profile_cache: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        self._bootstrap_existing_profiles()

    def _load_profile_cached(self, profile_path: Path) -> Optional[Dict[str, Any]]:
        if not profile_path.exists():
            return None
        try:
            mtime_ns = profile_path.stat().st_mtime_ns
            cached = self._profile_cache.get(str(profile_path))
            if cached and cached[0] == mtime_ns:
                return cached[1]
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._profile_cache[str(profile_path)] = (mtime_ns, data)
            return data
        except Exception:
            return None

    def sync_all_profiles_with_autofill(self):
        """
        Bi-directionally synchronizes data/clients/ and ai-job-autofill/server/profiles/.
        ClientManager is the single source of truth:
        1. Ensures all data/clients dossiers exist in autofill profiles dir.
        2. Ensures all documents in data/clients/{id}/documents/ are mirrored to autofill/{id}/.
        3. Imports any profiles found only in autofill into data/clients/.
        """
        if not self.autofill_dir.exists():
            self.autofill_dir.mkdir(parents=True, exist_ok=True)

        # 1. Mirror from clients_dir -> autofill_dir
        for cdir in self.clients_dir.iterdir():
            if not cdir.is_dir():
                continue
            cid = cdir.name
            profile_file = cdir / "profile.json"
            if profile_file.exists():
                af_target = self.autofill_dir / f"{cid}.json"
                if not af_target.exists() or af_target.stat().st_mtime_ns < profile_file.stat().st_mtime_ns:
                    try:
                        shutil.copy2(profile_file, af_target)
                    except Exception:
                        pass

            doc_dir = cdir / "documents"
            if doc_dir.is_dir():
                af_doc_dir = self.autofill_dir / cid
                af_doc_dir.mkdir(parents=True, exist_ok=True)
                for doc in doc_dir.iterdir():
                    if doc.is_file():
                        af_doc_target = af_doc_dir / doc.name
                        if not af_doc_target.exists() or af_doc_target.stat().st_mtime_ns < doc.stat().st_mtime_ns:
                            try:
                                shutil.copy2(doc, af_doc_target)
                            except Exception:
                                pass

        # 2. Mirror from autofill_dir -> clients_dir (if missing)
        for item in self.autofill_dir.glob("*.json"):
            if item.name == "template.json":
                continue
            cid = item.stem
            client_folder = self.clients_dir / cid
            target_profile = client_folder / "profile.json"
            if not target_profile.exists():
                client_folder.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(item, target_profile)
                except Exception as exc:
                    logger.warning("Failed to bootstrap client %s: %s", cid, exc)

            af_doc_dir = self.autofill_dir / cid
            if af_doc_dir.is_dir():
                target_docs = client_folder / "documents"
                target_docs.mkdir(parents=True, exist_ok=True)
                for doc in af_doc_dir.glob("*"):
                    if doc.is_file() and not (target_docs / doc.name).exists():
                        try:
                            shutil.copy2(doc, target_docs / doc.name)
                        except Exception:
                            pass

    def _bootstrap_existing_profiles(self):
        """Syncs existing profiles from ai-job-autofill into data/clients/ and vice-versa."""
        self.sync_all_profiles_with_autofill()

    def get_active_client_id(self) -> str:
        """Returns the ID of the currently active client."""
        if ACTIVE_CLIENT_FILE.exists():
            try:
                with open(ACTIVE_CLIENT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    client_id = data.get("active_client_id", "")
                    if client_id and (self.clients_dir / client_id).is_dir():
                        return client_id
            except Exception:
                pass

        # Fallback to anass_sibbi or first available client
        if (self.clients_dir / "anass_sibbi").is_dir():
            return "anass_sibbi"
        clients = [d.name for d in self.clients_dir.iterdir() if d.is_dir()]
        return clients[0] if clients else "default"

    def set_active_client_id(self, client_id: str) -> bool:
        """Sets the active client ID."""
        clean_id = _slugify(client_id)
        if not (self.clients_dir / clean_id).is_dir():
            # If exists in autofill, migrate first
            if (self.autofill_dir / f"{clean_id}.json").exists():
                self._bootstrap_existing_profiles()
            else:
                return False

        try:
            ACTIVE_CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ACTIVE_CLIENT_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "active_client_id": clean_id,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, f, indent=2)
            return True
        except Exception as exc:
            logger.error("Failed to set active client: %s", exc)
            return False

    def list_clients(self) -> List[Dict[str, Any]]:
        """Lists all client dossiers with metadata and active state."""
        active_id = self.get_active_client_id()
        clients = []

        # Scan data/clients/
        dirs = [d for d in self.clients_dir.iterdir() if d.is_dir()]
        for cdir in sorted(dirs, key=lambda d: d.name):
            cid = cdir.name
            profile_path = cdir / "profile.json"
            meta = {
                "id": cid,
                "name": cid.replace("_", " ").title(),
                "email": "",
                "phone": "",
                "title": "",
                "city": "",
                "doc_count": 0,
                "is_active": (cid == active_id),
                "created_at": datetime.fromtimestamp(cdir.stat().st_ctime, timezone.utc).isoformat()
            }

            pdata = self._load_profile_cached(profile_path)
            if pdata:
                applicant = pdata.get("applicant", {})
                personal = applicant.get("personal", {})
                contact = applicant.get("contact", {})
                prof = applicant.get("professional_profile", {})

                full_name = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
                if full_name:
                    meta["name"] = full_name
                meta["email"] = contact.get("email", "")
                meta["phone"] = contact.get("phone_display") or contact.get("phone", "")
                meta["city"] = contact.get("address", {}).get("city", "")
                meta["title"] = prof.get("current_title") or prof.get("headline", "")

            # Count documents
            doc_dir = cdir / "documents"
            if doc_dir.is_dir():
                meta["doc_count"] = len([f for f in doc_dir.iterdir() if f.is_file()])
            elif (self.autofill_dir / cid).is_dir():
                meta["doc_count"] = len([f for f in (self.autofill_dir / cid).iterdir() if f.is_file()])

            clients.append(meta)

        return clients

    def get_client(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves full profile JSON and dossier metadata for a client."""
        clean_id = _slugify(client_id)
        cdir = self.clients_dir / clean_id
        profile_path = cdir / "profile.json"

        if not profile_path.exists():
            # Check autofill dir fallback
            af_profile = self.autofill_dir / f"{clean_id}.json"
            if af_profile.exists():
                self._bootstrap_existing_profiles()
            else:
                return None

        data = self._load_profile_cached(profile_path)
        if data is not None:
            return data

        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as exc:
            logger.error("Error reading client %s: %s", clean_id, exc)
            return None

    def get_client_profile(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Alias for get_client."""
        return self.get_client(client_id)

    def save_client(self, client_id: str, profile_data: Dict[str, Any]) -> bool:
        """Saves a client profile and synchronizes it with the autofill directory."""
        clean_id = _slugify(client_id)
        if not clean_id:
            return False

        cdir = self.clients_dir / clean_id
        cdir.mkdir(parents=True, exist_ok=True)
        profile_path = cdir / "profile.json"

        try:
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, ensure_ascii=False, indent=2)

            self._profile_cache[str(profile_path)] = (profile_path.stat().st_mtime_ns, profile_data)

            # Mirror to ai-job-autofill/server/profiles/
            af_path = self.autofill_dir / f"{clean_id}.json"
            with open(af_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, ensure_ascii=False, indent=2)

            return True
        except Exception as exc:
            logger.error("Failed saving client %s: %s", clean_id, exc)
            return False

    def delete_client(self, client_id: str) -> bool:
        """Deletes a client dossier and mirrors deletion in autofill directory."""
        clean_id = _slugify(client_id)
        cdir = self.clients_dir / clean_id
        if not cdir.exists():
            return False

        try:
            shutil.rmtree(cdir, ignore_errors=True)
            af_json = self.autofill_dir / f"{clean_id}.json"
            if af_json.exists():
                af_json.unlink(missing_ok=True)
            af_doc_dir = self.autofill_dir / clean_id
            if af_doc_dir.exists():
                shutil.rmtree(af_doc_dir, ignore_errors=True)

            # If active client was deleted, switch to another
            if self.get_active_client_id() == clean_id:
                clients = self.list_clients()
                if clients:
                    self.set_active_client_id(clients[0]["id"])
            return True
        except Exception as exc:
            logger.error("Failed deleting client %s: %s", clean_id, exc)
            return False

    def list_documents(self, client_id: str) -> List[Dict[str, Any]]:
        """Lists all uploaded documents in the client dossier."""
        clean_id = _slugify(client_id)
        cdir = self.clients_dir / clean_id
        doc_dir = cdir / "documents"

        docs = []
        doc_paths: Dict[str, Path] = {}

        # 1. Check primary client doc dir
        if doc_dir.is_dir():
            for p in doc_dir.iterdir():
                if p.is_file() and p.suffix.lower() in SUPPORTED_DOC_EXTS:
                    doc_paths[p.name] = p

        # 2. Check autofill doc dir fallback
        af_doc_dir = self.autofill_dir / clean_id
        if af_doc_dir.is_dir():
            for p in af_doc_dir.iterdir():
                if p.is_file() and p.suffix.lower() in SUPPORTED_DOC_EXTS:
                    if p.name not in doc_paths:
                        doc_paths[p.name] = p

        for fname, fpath in sorted(doc_paths.items()):
            ext = fpath.suffix.lower().lstrip(".")
            lower = fname.lower()
            category = "lebenslauf" if any(w in lower for w in ["cv", "resume", "lebenslauf"]) else (
                "zeugnis" if any(w in lower for w in ["zeugnis", "diplom", "certif", "abitur"]) else (
                    "anschreiben" if "anschreiben" in lower else "other"
                )
            )
            docs.append({
                "file_name": fname,
                "fileName": fname,
                "extension": ext,
                "size": fpath.stat().st_size,
                "category": category,
                "download_url": f"/api/clients/{clean_id}/documents/{fname}",
                "preview_url": f"/api/clients/{clean_id}/documents/{fname}/preview"
            })
        return docs

    def save_document(self, client_id: str, file_bytes: bytes, filename: str) -> Optional[Dict[str, Any]]:
        """Saves a document to the client dossier and syncs with autofill."""
        clean_id = _slugify(client_id)
        cdir = self.clients_dir / clean_id
        cdir.mkdir(parents=True, exist_ok=True)
        doc_dir = cdir / "documents"
        doc_dir.mkdir(parents=True, exist_ok=True)

        clean_filename = re.sub(r"[^\w\s.-]", "", filename).strip()
        if not clean_filename:
            clean_filename = f"document_{int(datetime.now().timestamp())}.pdf"

        target_path = doc_dir / clean_filename
        with open(target_path, "wb") as f:
            f.write(file_bytes)

        # Mirror to autofill directory for Chrome extension direct access
        af_doc_dir = self.autofill_dir / clean_id
        af_doc_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(target_path, af_doc_dir / clean_filename)
        except Exception:
            pass

        return {
            "file_name": clean_filename,
            "size": len(file_bytes),
            "download_url": f"/api/clients/{clean_id}/documents/{clean_filename}"
        }

    def delete_document(self, client_id: str, filename: str) -> bool:
        """Deletes a document from the client dossier and mirrors deletion in autofill directory."""
        clean_id = _slugify(client_id)
        clean_filename = Path(filename).name
        deleted = False

        target_file = self.clients_dir / clean_id / "documents" / clean_filename
        if target_file.exists():
            try:
                target_file.unlink()
                deleted = True
            except Exception as e:
                logger.error("Failed to delete %s: %s", target_file, e)

        af_target = self.autofill_dir / clean_id / clean_filename
        if af_target.exists():
            try:
                af_target.unlink()
                deleted = True
            except Exception as e:
                logger.error("Failed to delete %s: %s", af_target, e)

        return deleted

    def find_client_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        Finds a client by matching normalized phone digits against client dossiers.
        """
        if not phone:
            return None
        clean_digits = re.sub(r"\D", "", str(phone))
        if len(clean_digits) < 6:
            return None

        search_suffix = clean_digits[-8:] if len(clean_digits) >= 8 else clean_digits

        for client_info in self.list_clients():
            cid = client_info["id"]
            profile = self.get_client(cid)
            if not profile:
                continue

            contact = profile.get("applicant", {}).get("contact", {})
            phone_candidates = [
                contact.get("phone", ""),
                contact.get("phone_display", ""),
                contact.get("whatsapp", ""),
                client_info.get("phone", "")
            ]

            for cand in phone_candidates:
                if not cand:
                    continue
                cand_digits = re.sub(r"\D", "", str(cand))
                if cand_digits and (cand_digits == clean_digits or cand_digits.endswith(search_suffix) or clean_digits.endswith(cand_digits[-8:])):
                    return {
                        "id": cid,
                        "name": client_info.get("name", cid),
                        "profile": profile
                    }
        return None

    def sync_verified_whatsapp(self, client_id: str, wa_id: str) -> bool:
        """
        Synchronizes verified WhatsApp number to candidate dossier and Supabase.
        """
        clean_id = _slugify(client_id)
        profile = self.get_client(clean_id)
        if not profile:
            return False

        clean_wa = re.sub(r"\D", "", str(wa_id))
        if not clean_wa:
            return False

        contact = profile.setdefault("applicant", {}).setdefault("contact", {})
        contact["phone"] = clean_wa
        contact["whatsapp"] = clean_wa
        contact["phone_display"] = f"+{clean_wa}"

        saved = self.save_client(clean_id, profile)

        # Sync to Supabase if linked application exists
        supabase_app_id = (
            profile.get("metadata", {}).get("supabase_application_id")
            or profile.get("applicant", {}).get("metadata", {}).get("supabase_application_id")
        )
        if supabase_app_id:
            try:
                from services.supabase_service import supabase_service
                supabase_service.update_application(supabase_app_id, {"whatsapp": f"+{clean_wa}"})
                logger.info("Synchronized verified WhatsApp +%s to Supabase app %s", clean_wa, supabase_app_id)
            except Exception as exc:
                logger.warning("Could not sync verified WhatsApp to Supabase app %s: %s", supabase_app_id, exc)

        return saved


    def ingest_cv(self, pdf_bytes: bytes, filename: str = "Lebenslauf.pdf", client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses candidate CV PDF, extracts profile fields, creates client dossier,
        saves Lebenslauf.pdf, and activates the client.
        Tolerates truncated or corrupt PDF streams without failing.
        """
        try:
            raw_text = CVParser.extract_text_from_pdf(pdf_bytes)
        except Exception as exc:
            logger.warning("Error during text extraction: %s", exc)
            raw_text = ""

        parsed = CVParser.parse_cv_text(raw_text)

        # If raw_text had no extractable text (e.g. scanned image PDF), attempt vision extraction
        if not raw_text or len(raw_text.strip()) < 15:
            vision_data = CVParser.extract_with_vision(pdf_bytes)
            if vision_data:
                parsed["personal"]["first_name"] = vision_data.get("first_name") or parsed["personal"].get("first_name", "")
                parsed["personal"]["last_name"] = vision_data.get("last_name") or parsed["personal"].get("last_name", "")
                parsed["personal"]["full_name"] = vision_data.get("full_name") or f"{parsed['personal']['first_name']} {parsed['personal']['last_name']}".strip()
                parsed["personal"]["date_of_birth"] = vision_data.get("date_of_birth") or parsed["personal"].get("date_of_birth", "")
                parsed["personal"]["date_of_birth_display"] = vision_data.get("date_of_birth_display") or parsed["personal"].get("date_of_birth_display", "")
                parsed["personal"]["place_of_birth"] = vision_data.get("place_of_birth") or parsed["personal"].get("place_of_birth", "")
                parsed["personal"]["nationality"] = vision_data.get("nationality") or parsed["personal"].get("nationality", "")
                if vision_data.get("gender"): parsed["personal"]["gender"] = vision_data["gender"]
                if vision_data.get("salutation"): parsed["personal"]["salutation"] = vision_data["salutation"]

                parsed["contact"]["email"] = vision_data.get("email") or parsed["contact"].get("email", "")
                parsed["contact"]["phone"] = vision_data.get("phone") or parsed["contact"].get("phone", "")
                parsed["contact"]["phone_display"] = parsed["contact"]["phone"]
                addr = parsed["contact"].setdefault("address", {})
                for fld in ["street", "house_number", "postal_code", "city", "country"]:
                    if vision_data.get(fld): addr[fld] = vision_data[fld]

                prof = parsed.setdefault("professional_profile", {})
                if vision_data.get("current_title"): prof["current_title"] = vision_data["current_title"]
                if vision_data.get("headline"): prof["headline"] = vision_data["headline"]
                if vision_data.get("summary_de"): prof["summary_de"] = vision_data["summary_de"]

                if vision_data.get("skills"):
                    techs = parsed.setdefault("skills", {}).setdefault("technologies_from_cv", [])
                    for s in vision_data["skills"]:
                        if s not in techs: techs.append(s)

                if vision_data.get("languages"):
                    parsed["languages"] = vision_data["languages"]

        personal = parsed.get("personal", {})
        contact = parsed.get("contact", {})
        skills = parsed.get("skills", {})
        languages = parsed.get("languages", [])

        full_name = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
        if not full_name or full_name.lower() in ["bewerber", "kandidat"]:
            name_from_fn = _extract_name_from_filename(filename)
            if name_from_fn:
                full_name = name_from_fn
                personal["full_name"] = full_name
                personal["first_name"] = full_name.split()[0]
                personal["last_name"] = " ".join(full_name.split()[1:])

        if not client_id:
            client_id = _slugify(full_name) if (full_name and full_name.lower() not in ["bewerber", "kandidat"]) else f"client_{int(datetime.now().timestamp())}"
        else:
            client_id = _slugify(client_id)

        prof = parsed.get("professional_profile", {})

        # Build full standard profile structure
        profile_data = {
            "profile_version": "1.0",
            "profile_language": "de",
            "applicant": {
                "personal": {
                    "first_name": personal.get("first_name", ""),
                    "last_name": personal.get("last_name", ""),
                    "full_name": full_name,
                    "date_of_birth": personal.get("date_of_birth") or "",
                    "date_of_birth_display": personal.get("date_of_birth_display") or "",
                    "place_of_birth": personal.get("place_of_birth") or "",
                    "nationality": personal.get("nationality") or "",
                    "salutation": personal.get("salutation", "Herr"),
                    "gender": personal.get("gender") or ("male" if personal.get("salutation") == "Herr" else "female")
                },
                "contact": {
                    "email": contact.get("email", ""),
                    "phone": contact.get("phone", ""),
                    "phone_display": contact.get("phone_display", ""),
                    "address": {
                        "street": contact.get("address", {}).get("street", ""),
                        "house_number": contact.get("address", {}).get("house_number", ""),
                        "postal_code": contact.get("address", {}).get("postal_code", ""),
                        "city": contact.get("address", {}).get("city", ""),
                        "country": contact.get("address", {}).get("country", "Deutschland"),
                        "country_code": contact.get("address", {}).get("country_code", "DE")
                    },
                    "linkedin": contact.get("linkedin", {}),
                    "portfolio": contact.get("portfolio", {}),
                    "github": contact.get("github", {})
                },
                "professional_profile": {
                    "current_title": prof.get("current_title") or "Softwareentwickler",
                    "headline": prof.get("headline") or f"{full_name} | {prof.get('current_title', 'Bewerber')}",
                    "summary_de": prof.get("summary_de") or f"Motivierter Kandidat mit Fachkenntnissen in: {', '.join(skills.get('technologies_from_cv', [])[:6])}",
                    "primary_fields": prof.get("primary_fields") or skills.get("technologies_from_cv", [])[:6]
                },
                "skills": skills,
                "languages": languages
            }
        }

        # Save profile
        self.save_client(client_id, profile_data)

        # Save uploaded PDF as Lebenslauf.pdf
        doc_name = filename if filename.lower().endswith(".pdf") else "Lebenslauf.pdf"
        self.save_document(client_id, pdf_bytes, doc_name)

        # Set as active client
        self.set_active_client_id(client_id)

        return {
            "success": True,
            "client_id": client_id,
            "client_name": full_name,
            "profile": profile_data,
            "parsed_summary": {
                "name": full_name,
                "email": contact.get("email", ""),
                "phone": contact.get("phone", ""),
                "street": contact.get("address", {}).get("street", ""),
                "house_number": contact.get("address", {}).get("house_number", ""),
                "postal_code": contact.get("address", {}).get("postal_code", ""),
                "city": contact.get("address", {}).get("city", ""),
                "date_of_birth": personal.get("date_of_birth", ""),
                "place_of_birth": personal.get("place_of_birth", ""),
                "nationality": personal.get("nationality", ""),
                "title": prof.get("current_title", ""),
                "linkedin": contact.get("linkedin", {}).get("url", ""),
                "github": contact.get("github", {}).get("url", ""),
                "skills": skills.get("technologies_from_cv", []),
                "languages": languages
            }
        }


# Global instance
client_manager = ClientManager()
