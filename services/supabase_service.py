"""
Secure Server-Side Supabase Service for JobScout.
Provides authenticated access to Supabase PostgreSQL database (REST API)
and private storage buckets without exposing privileged service role keys
to frontend clients or browser JavaScript.
"""

import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_STORAGE_BUCKET, SUPABASE_URL

logger = logging.getLogger(__name__)

# Security & Validation Constants
MAX_DOCUMENT_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB max per document
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".txt"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
    "text/plain",
}


class SupabaseServiceError(Exception):
    """Base exception for Supabase service operations."""
    pass


class ApplicationNotFoundError(SupabaseServiceError):
    """Raised when the specified application ID does not exist."""
    pass


class PaymentUnverifiedError(SupabaseServiceError):
    """Raised when attempting candidate onboarding on an unpaid application."""
    pass


class DocumentDownloadError(SupabaseServiceError):
    """Raised when downloading a candidate document fails or violates security checks."""
    pass


class SupabaseService:
    """
    Manages authenticated communication with Supabase backend.
    Uses SUPABASE_SERVICE_ROLE_KEY exclusively on server side,
    with safe fallback to SUPABASE_ANON_KEY for development.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        key: Optional[str] = None,
        bucket: Optional[str] = None,
        timeout: int = 15,
    ):
        self.base_url = (base_url or SUPABASE_URL or "").rstrip("/")
        # Priority: service role key > anon key
        self.auth_key = (
            key
            or SUPABASE_SERVICE_ROLE_KEY
            or SUPABASE_ANON_KEY
            or ""
        )
        self.bucket = bucket or SUPABASE_STORAGE_BUCKET or "applications"
        self.timeout = timeout

        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def _get_headers(self) -> Dict[str, str]:
        return {
            "apikey": self.auth_key,
            "Authorization": f"Bearer {self.auth_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def check_health(self) -> bool:
        """Verifies connectivity to Supabase REST endpoint."""
        if not self.base_url or not self.auth_key:
            return False
        try:
            url = f"{self.base_url}/rest/v1/applications?select=id&limit=1"
            res = self.session.get(url, headers=self._get_headers(), timeout=self.timeout)
            return res.status_code == 200
        except Exception as exc:
            logger.warning("Supabase health check failed: %s", exc)
            return False

    def get_application(self, application_id: str) -> Dict[str, Any]:
        """
        Retrieves a single application record from public.applications by ID.
        Raises ApplicationNotFoundError if not found.
        """
        clean_id = str(application_id or "").strip()
        if not clean_id:
            raise ApplicationNotFoundError("Application ID cannot be empty.")

        # Basic UUID / string sanitization
        if not re.match(r"^[0-9a-fA-F\-]{16,64}$", clean_id):
            raise ApplicationNotFoundError(f"Invalid application ID format: {clean_id}")

        url = f"{self.base_url}/rest/v1/applications"
        params = {
            "id": f"eq.{clean_id}",
            "select": "id,created_at,pack,full_name,email,whatsapp,bank,language_level,field,documents,is_payed,code",
        }

        try:
            res = self.session.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=self.timeout,
            )
            if res.status_code != 200:
                raise SupabaseServiceError(
                    f"Supabase REST error ({res.status_code}): {res.text}"
                )

            data = res.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                raise ApplicationNotFoundError(
                    f"Application with ID '{clean_id}' was not found in Supabase."
                )

            return data[0]
        except requests.RequestException as exc:
            raise SupabaseServiceError(f"Network error querying Supabase: {exc}") from exc

    def list_applications(
        self,
        limit: int = 100,
        is_payed: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Lists applications from Supabase with optional payment filtering."""
        url = f"{self.base_url}/rest/v1/applications"
        params: Dict[str, Any] = {
            "select": "id,created_at,pack,full_name,email,whatsapp,bank,language_level,field,documents,is_payed,code",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        if is_payed is not None:
            params["is_payed"] = f"eq.{str(is_payed).lower()}"

        try:
            res = self.session.get(
                url,
                headers=self._get_headers(),
                params=params,
                timeout=self.timeout,
            )
            if res.status_code != 200:
                raise SupabaseServiceError(f"Error listing applications: {res.text}")
            return res.json() or []
        except requests.RequestException as exc:
            raise SupabaseServiceError(f"Network error listing applications: {exc}") from exc

    def get_document_bytes(self, storage_path: str) -> Tuple[bytes, str, str]:
        """
        Securely downloads a document from Supabase Storage.
        Enforces path traversal protection, size limits, and allowed extensions.
        Returns: (file_bytes, clean_filename, mime_type)
        """
        raw_path = str(storage_path or "").strip().lstrip("/")
        if not raw_path:
            raise DocumentDownloadError("Storage path is empty.")

        # Path traversal guard
        if ".." in raw_path or raw_path.startswith("/") or "\\" in raw_path:
            raise DocumentDownloadError(f"Invalid storage path: '{raw_path}' contains disallowed characters.")

        ext = Path(raw_path).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise DocumentDownloadError(
                f"File extension '{ext}' is not permitted. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # 1. Try direct authenticated download from bucket
        direct_url = f"{self.base_url}/storage/v1/object/{self.bucket}/{raw_path}"
        headers = {
            "apikey": self.auth_key,
            "Authorization": f"Bearer {self.auth_key}",
        }

        try:
            res = self.session.get(direct_url, headers=headers, timeout=self.timeout)

            # 2. If direct returns 401/403, try signed URL flow
            if res.status_code in {401, 403}:
                sign_url = f"{self.base_url}/storage/v1/object/sign/{self.bucket}/{raw_path}"
                sign_res = self.session.post(
                    sign_url,
                    headers=self._get_headers(),
                    json={"expiresIn": 120},
                    timeout=self.timeout,
                )
                if sign_res.status_code == 200:
                    signed_path = sign_res.json().get("signedURL")
                    if signed_path:
                        full_signed_url = (
                            signed_path
                            if signed_path.startswith("http")
                            else f"{self.base_url}/storage/v1{signed_path}"
                        )
                        res = self.session.get(full_signed_url, timeout=self.timeout)

            if res.status_code != 200:
                raise DocumentDownloadError(
                    f"Failed downloading '{raw_path}' from bucket '{self.bucket}' (Status {res.status_code}): {res.text}"
                )

            content = res.content
            if len(content) > MAX_DOCUMENT_SIZE_BYTES:
                raise DocumentDownloadError(
                    f"Document '{raw_path}' exceeds maximum size limit of 25MB (Size: {len(content)} bytes)."
                )

            # Determine clean filename
            original_filename = Path(raw_path).name
            clean_filename = self._extract_clean_filename(original_filename)

            # Detect MIME type
            mime_type = res.headers.get("Content-Type") or mimetypes.guess_type(clean_filename)[0] or "application/octet-stream"

            return content, clean_filename, mime_type
        except requests.RequestException as exc:
            raise DocumentDownloadError(f"Network error downloading document '{raw_path}': {exc}") from exc

    def update_application(self, application_id: str, updates: Dict[str, Any]) -> bool:
        """
        Updates metadata fields on an application record.
        Fails safely if specific columns do not exist on the table.
        """
        clean_id = str(application_id or "").strip()
        if not clean_id or not updates:
            return False

        url = f"{self.base_url}/rest/v1/applications?id=eq.{clean_id}"
        headers = self._get_headers()
        headers["Prefer"] = "return=representation"

        try:
            res = self.session.patch(
                url,
                headers=headers,
                json=updates,
                timeout=self.timeout,
            )
            if res.status_code in {200, 204}:
                return True
            logger.debug("Supabase patch returned status %s: %s", res.status_code, res.text)
            return False
        except Exception as exc:
            logger.warning("Could not update Supabase application %s: %s", clean_id, exc)
            return False

    @staticmethod
    def _extract_clean_filename(stored_name: str) -> str:
        """
        Strips storage timestamps and random hashes from the stored filename
        to reconstruct a human-readable document name.
        Example:
        '1780316080078-4-c82de0e0-c4b6-4db8-98fb-c48af182e2f8-lebenslauf_reda_takie.pdf'
        -> 'lebenslauf_reda_takie.pdf'
        """
        # Match pattern: <timestamp>-<index>-<uuid>-<original>
        pattern = r"^\d+-\d+-[0-9a-fA-F\-]{36}-(.*)$"
        match = re.match(pattern, stored_name)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
        return stored_name


# Global service singleton
supabase_service = SupabaseService()
