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


class ClientManager:
    """Manages multi-client applicant dossiers, CV parsing, and active client state."""

    def __init__(self, clients_dir: Path = CLIENTS_DIR, autofill_dir: Path = AUTOFILL_PROFILES_DIR):
        self.clients_dir = Path(clients_dir)
        self.autofill_dir = Path(autofill_dir)
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        self.autofill_dir.mkdir(parents=True, exist_ok=True)
        self._bootstrap_existing_profiles()

    def _bootstrap_existing_profiles(self):
        """Syncs existing profiles from ai-job-autofill into data/clients/ if missing."""
        if not self.autofill_dir.exists():
            return
        for item in self.autofill_dir.glob("*.json"):
            if item.name == "template.json":
                continue
            client_id = item.stem
            client_folder = self.clients_dir / client_id
            client_folder.mkdir(parents=True, exist_ok=True)
            target_profile = client_folder / "profile.json"
            if not target_profile.exists():
                try:
                    shutil.copy2(item, target_profile)
                except Exception as exc:
                    logger.warning("Failed to bootstrap client %s: %s", client_id, exc)

            # Copy documents folder if exists
            source_doc_dir = self.autofill_dir / client_id
            if source_doc_dir.is_dir():
                target_docs = client_folder / "documents"
                target_docs.mkdir(parents=True, exist_ok=True)
                for doc in source_doc_dir.glob("*"):
                    if doc.is_file() and not (target_docs / doc.name).exists():
                        try:
                            shutil.copy2(doc, target_docs / doc.name)
                        except Exception:
                            pass

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

            if profile_path.exists():
                try:
                    with open(profile_path, "r", encoding="utf-8") as f:
                        pdata = json.load(f)
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
                except Exception:
                    pass

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

        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as exc:
            logger.error("Error reading client %s: %s", clean_id, exc)
            return None

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

    def ingest_cv(self, pdf_bytes: bytes, filename: str = "Lebenslauf.pdf", client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses candidate CV PDF, extracts profile fields, creates client dossier,
        saves Lebenslauf.pdf, and activates the client.
        """
        raw_text = CVParser.extract_text_from_pdf(pdf_bytes)
        parsed = CVParser.parse_cv_text(raw_text)

        personal = parsed.get("personal", {})
        contact = parsed.get("contact", {})
        skills = parsed.get("skills", {})
        languages = parsed.get("languages", [])

        full_name = personal.get("full_name") or f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()
        if not client_id:
            client_id = _slugify(full_name) if full_name else f"client_{int(datetime.now().timestamp())}"
        else:
            client_id = _slugify(client_id)

        # Build full standard profile structure
        profile_data = {
            "profile_version": "1.0",
            "profile_language": "de",
            "applicant": {
                "personal": {
                    "first_name": personal.get("first_name", ""),
                    "last_name": personal.get("last_name", ""),
                    "full_name": full_name,
                    "salutation": personal.get("salutation", "Herr"),
                    "gender": "male" if personal.get("salutation") == "Herr" else "female"
                },
                "contact": {
                    "email": contact.get("email", ""),
                    "phone": contact.get("phone", ""),
                    "phone_display": contact.get("phone_display", ""),
                    "address": {
                        "street": "",
                        "house_number": "",
                        "postal_code": contact.get("address", {}).get("postal_code", ""),
                        "city": contact.get("address", {}).get("city", ""),
                        "country": "Deutschland",
                        "country_code": "DE"
                    }
                },
                "professional_profile": {
                    "current_title": skills.get("technologies_from_cv", ["Auszubildender"])[0] if skills.get("technologies_from_cv") else "Bewerber",
                    "headline": f"{full_name} - Bewerber",
                    "summary": f"Motivierter Kandidat mit Fachkenntnissen in: {', '.join(skills.get('technologies_from_cv', [])[:6])}"
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
                "city": contact.get("address", {}).get("city", ""),
                "skills": skills.get("technologies_from_cv", []),
                "languages": languages
            }
        }


# Global instance
client_manager = ClientManager()
