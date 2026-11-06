"""
Global thread-safe employer & domain cache for JobScout.
Enables cross-worker sharing of company contact details, Impressum,
career portals, and application form links to eliminate duplicate HTTP and browser visits.
"""

import threading
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EmployerDomainCache:
    """Thread-safe cross-worker cache for employer contacts and domain metadata."""

    def __init__(self):
        self._lock = threading.RLock()
        self._cache_by_domain: Dict[str, Dict[str, Any]] = {}
        self._cache_by_company: Dict[str, Dict[str, Any]] = {}
        self.hits: int = 0
        self.misses: int = 0

    @staticmethod
    def normalize_domain(url_or_domain: str) -> str:
        if not url_or_domain:
            return ""
        raw = str(url_or_domain).strip().lower()
        if raw.startswith("http://") or raw.startswith("https://"):
            try:
                parsed = urlparse(raw)
                raw = parsed.netloc or raw
            except Exception:
                pass
        raw = raw.split(":")[0].strip()
        if raw.startswith("www."):
            raw = raw[4:]
        return raw

    @staticmethod
    def make_company_key(company: str, city: str = "") -> str:
        c = str(company or "").strip().lower()
        l = str(city or "").strip().lower()
        if len(c) < 3:
            return ""
        return f"{c}|{l}" if l else c

    def get(self, company: str = "", city: str = "", url_or_domain: str = "") -> Optional[Dict[str, Any]]:
        domain = self.normalize_domain(url_or_domain)
        comp_key = self.make_company_key(company, city)

        with self._lock:
            # 1. Try domain lookup first (highest fidelity)
            if domain and domain in self._cache_by_domain:
                entry = self._cache_by_domain[domain]
                self.hits += 1
                return dict(entry)

            # 2. Try company key lookup
            if comp_key and comp_key in self._cache_by_company:
                entry = self._cache_by_company[comp_key]
                self.hits += 1
                return dict(entry)

            self.misses += 1
            return None

    def put(
        self,
        company: str = "",
        city: str = "",
        url_or_domain: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not data or not isinstance(data, dict):
            return

        domain = self.normalize_domain(url_or_domain)
        comp_key = self.make_company_key(company, city)
        
        # Only cache meaningful contact information
        has_val = any(
            bool(data.get(k))
            for k in ("email", "phone", "contact_person", "has_form", "direct_application_url", "form_link")
        )
        if not has_val:
            return

        clean_entry = {
            "email": data.get("email") or "",
            "phone": data.get("phone") or "",
            "contact_person": data.get("contact_person") or "",
            "has_form": bool(data.get("has_form")),
            "form_link": data.get("form_link") or data.get("direct_application_url") or "",
            "direct_application_url": data.get("direct_application_url") or data.get("form_link") or "",
            "application_method": data.get("application_method") or "",
            "employer_website": data.get("employer_website") or "",
        }

        with self._lock:
            if domain:
                self._cache_by_domain[domain] = clean_entry
            if comp_key:
                self._cache_by_company[comp_key] = clean_entry

    def clear(self) -> None:
        with self._lock:
            self._cache_by_domain.clear()
            self._cache_by_company.clear()
            self.hits = 0
            self.misses = 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache_by_domain) + len(self._cache_by_company)


_GLOBAL_EMPLOYER_CACHE = EmployerDomainCache()

def get_employer_cache() -> EmployerDomainCache:
    return _GLOBAL_EMPLOYER_CACHE
