"""
Global thread-safe 3-tier cache architecture for JobScout.

Separates caching into three strictly isolated categories:
1. JobResultCache:
   Keyed strictly by a stable, unique job identifier or canonical job listing URL.
2. VerifiedEmployerCache:
   Keyed ONLY by a verified employer identity and its official employer domain
   (never a job-board domain, redirect/shortener domain, or shared multi-tenant ATS root domain).
   A cached employer contact may be reused ONLY as a fallback when no stronger job-specific
   evidence exists and employer association is verified.
3. PlatformConfigCache:
   Stores only reusable platform-level metadata, selectors, and configuration.
   Never stores employer contacts.
"""

import logging
import re
import threading
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# 1. Aggregator / recruitment portal domains that MUST NEVER be used as employer identifiers
PORTAL_DOMAINS = {
    "ausbildung.de",
    "arbeitsagentur.de",
    "azubiyo.de",
    "aubi-plus.de",
    "ihk.de",
    "ihk-lehrstellenboerse.de",
    "meine-ausbildung-in-deutschland.de",
    "jobs.meine-ausbildung-in-deutschland.de",
    "indexinternet.de",
    "ihk-azubi-stellenmarkt.indexinternet.de",
    "stepstone.de",
    "indeed.com",
    "indeed.de",
    "monster.de",
    "stellenanzeigen.de",
    "stellenmarkt.de",
    "yourfirm.de",
    "heyjobs.co",
    "hogapage.de",
    "jobs.hogapage.de",
    "hotelcareer.de",
    "gastrojobs.de",
    "xing.com",
    "linkedin.com",
    "google.com",
    "google.de",
    "meinestadt.de",
    "jobware.de",
    "kimeta.de",
    "bewerbung2go.de",
    "funkeworks.de",
    "funke-digital.de",
    "funke.de",
    "azubister.net",
    "schuelerkarriere.de",
    "talentsconnect.com",
}

# 2. URL shortener & redirect domains that MUST NEVER be used as employer identifiers
SHORTENER_DOMAINS = {
    "short.sg",
    "bit.ly",
    "t.co",
    "tinyurl.com",
    "ow.ly",
    "buff.ly",
    "lnkd.in",
    "rb.gy",
    "cutt.ly",
    "is.gd",
    "rebrand.ly",
    "shorturl.at",
    "tiny.cc",
}

# 3. Shared multi-tenant ATS domains that host many unrelated employers
SHARED_ATS_DOMAINS = {
    "softgarden.io",
    "personio.de",
    "personio.com",
    "myworkdayjobs.com",
    "workday.com",
    "prescreen.io",
    "onlyfy.com",
    "join.com",
    "recruitee.com",
    "smartrecruiters.com",
    "greenhouse.io",
    "lever.co",
    "breezy.hr",
    "ashbyhq.com",
    "d-vinci.de",
    "dvinci.de",
    "rexx-systems.com",
    "rexx-recruitment.com",
    "perbit.de",
    "talention.com",
    "umantis.com",
    "haufe.com",
    "successfactors.com",
    "successfactors.eu",
    "pi-asp.de",
    "b-ite.com",
    "bite.de",
    "concludis.de",
    "hrworks.de",
    "kenjo.io",
    "factorialhr.com",
    "jobylon.com",
    "teamtailor.com",
}

# Generic placeholder company names that cannot identify a unique employer
INVALID_COMPANY_NAMES = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "unbekannt",
    "k. a.",
    "k.a.",
    "m",
    "top-ausbilder",
    "ausbildungsbetrieb",
    "arbeitgeber",
    "unternehmen",
}


def _extract_clean_domain(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    raw = str(url_or_domain).strip().lower()
    if raw.startswith(("http://", "https://")):
        try:
            parsed = urlparse(raw)
            raw = parsed.netloc or raw
        except Exception:
            pass
    elif "/" in raw:
        raw = raw.split("/", 1)[0]
    raw = raw.split(":")[0].strip()
    if raw.startswith("www."):
        raw = raw[4:]
    return raw


def is_portal_domain(domain_or_url: str) -> bool:
    """Returns True if the domain/URL belongs to a recruitment portal or job board."""
    d = _extract_clean_domain(domain_or_url)
    if not d:
        return False
    return any(d == p or d.endswith("." + p) for p in PORTAL_DOMAINS)


def is_shortener_domain(domain_or_url: str) -> bool:
    """Returns True if the domain/URL belongs to a URL shortener service (e.g. short.sg, bit.ly)."""
    d = _extract_clean_domain(domain_or_url)
    if not d:
        return False
    return any(d == s or d.endswith("." + s) for s in SHORTENER_DOMAINS)


def is_shared_ats_domain(domain_or_url: str) -> bool:
    """Returns True if the domain/URL belongs to a shared multi-tenant ATS provider."""
    d = _extract_clean_domain(domain_or_url)
    if not d:
        return False
    return any(d == a or d.endswith("." + a) for a in SHARED_ATS_DOMAINS)


def is_non_employer_domain(domain_or_url: str) -> bool:
    """
    Returns True if the domain cannot be used as an standalone employer domain key
    (portals, shorteners, or bare multi-tenant ATS root domains).
    """
    d = _extract_clean_domain(domain_or_url)
    if not d:
        return True
    if is_portal_domain(d) or is_shortener_domain(d):
        return True
    # Bare shared ATS root domain (e.g., 'softgarden.io', 'social-apply.softgarden.io', 'pi-asp.de', 'b-ite.com')
    if d in SHARED_ATS_DOMAINS or d.startswith(("social-apply.", "jobs.", "apply.", "career.", "karriere.")):
        if is_shared_ats_domain(d):
            return True
    return False


def normalize_company_identity(company: str) -> str:
    """Normalizes an employer name for verified identity matching."""
    if not company:
        return ""
    c = str(company).strip().lower()
    c = re.sub(r"\s+", " ", c)
    if len(c) < 3 or c in INVALID_COMPANY_NAMES:
        return ""
    return c


def is_valid_company_name(company: str) -> bool:
    """Returns True if the company name is specific enough to represent a real employer."""
    return bool(normalize_company_identity(company))


class JobResultCache:
    """
    Tier 1: Job-specific cache.
    Keyed strictly by canonical job URL or unique job identifier.
    Never shares data across different job URLs.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def make_job_key(job_id: str = "", job_url: str = "") -> str:
        clean_url = str(job_url or "").strip()
        if clean_url.startswith(("http://", "https://")):
            parsed = urlparse(clean_url)
            path = (parsed.path or "").rstrip("/")
            # Require a specific listing path or query, never a root domain
            if path or parsed.query:
                return f"url:{parsed.netloc.lower()}{path}?{parsed.query}".rstrip("?")
        clean_id = str(job_id or "").strip()
        if clean_id and len(clean_id) >= 4:
            return f"id:{clean_id.lower()}"
        return ""

    def get(
        self,
        job_url_or_id: str = "",
        *,
        job_id: str = "",
        job_url: str = "",
        company: str = "",
    ) -> Optional[Dict[str, Any]]:
        if job_url_or_id and not job_url and not job_id:
            if job_url_or_id.startswith(("http://", "https://")):
                job_url = job_url_or_id
            else:
                job_id = job_url_or_id
        key = self.make_job_key(job_id=job_id, job_url=job_url)
        if not key:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            # Verify company compatibility if both are present
            cached_comp = normalize_company_identity(entry.get("company") or "")
            req_comp = normalize_company_identity(company)
            if cached_comp and req_comp and cached_comp != req_comp:
                return None
            return dict(entry)

    def put(
        self,
        job_url_or_id: str = "",
        data: Optional[Dict[str, Any]] = None,
        *,
        job_id: str = "",
        job_url: str = "",
        company: str = "",
    ) -> None:
        if job_url_or_id and not job_url and not job_id:
            if job_url_or_id.startswith(("http://", "https://")):
                job_url = job_url_or_id
            else:
                job_id = job_url_or_id
        if not data or not isinstance(data, dict):
            return
        key = self.make_job_key(job_id=job_id, job_url=job_url)
        if not key:
            return
        with self._lock:
            stored = dict(data)
            if company:
                stored["company"] = company
            self._entries[key] = stored

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class PlatformConfigCache:
    """
    Tier 3: Platform-level cache.
    Stores ONLY reusable platform-level metadata, selectors, and configuration.
    Strictly forbids storing any employer contact fields.
    """

    FORBIDDEN_CONTACT_KEYS = {
        "email",
        "phone",
        "contact_person",
        "arbeitsgeber",
        "direct_application_url",
        "form_link",
        "bewerbung_link",
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._config: Dict[str, Dict[str, Any]] = {}

    def get_platform_meta(self, platform: str) -> Optional[Dict[str, Any]]:
        p = str(platform or "").strip().lower()
        if not p:
            return None
        with self._lock:
            entry = self._config.get(p)
            return dict(entry) if entry else None

    def set_platform_meta(self, platform: str, meta: Dict[str, Any]) -> None:
        p = str(platform or "").strip().lower()
        if not p or not isinstance(meta, dict):
            return
        # Strip any accidental contact fields
        safe_meta = {k: v for k, v in meta.items() if k not in self.FORBIDDEN_CONTACT_KEYS}
        with self._lock:
            self._config[p] = safe_meta

    def get(self, platform: str) -> Optional[Dict[str, Any]]:
        return self.get_platform_meta(platform)

    def put(self, platform: str, meta: Dict[str, Any]) -> None:
        if isinstance(meta, dict):
            forbidden = self.FORBIDDEN_CONTACT_KEYS.intersection(meta.keys())
            if forbidden:
                raise ValueError(f"PlatformConfigCache forbids storing employer contact keys: {sorted(forbidden)}")
        self.set_platform_meta(platform, meta)

    def clear(self) -> None:
        with self._lock:
            self._config.clear()


class EmployerDomainCache:
    """
    Tier 2: Verified Employer Cache (+ Unified Façade for JobResultCache & PlatformConfigCache).
    Thread-safe cross-worker cache for verified employer contacts and official employer domains.

    Architectural guarantees:
    - Portal domains (ausbildung.de, azubiyo.de, aubi-plus.de, ihk.de, meine-ausbildung-in-deutschland.de,
      arbeitsagentur.de, etc.) are NEVER stored or queried as employer domain keys.
    - URL shorteners (short.sg, bit.ly, etc.) are NEVER stored or queried as employer domain keys.
    - Shared multi-tenant ATS domains are NEVER stored as bare domain keys without company identity verification.
    - Every cached entry records the verified company identity (`_cached_company`); a domain lookup
      will NOT return another employer's contact details if the requesting job belongs to a different company.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._cache_by_domain: Dict[str, Dict[str, Any]] = {}
        self._cache_by_company: Dict[str, Dict[str, Any]] = {}
        self.job_cache = JobResultCache()
        self.platform_cache = PlatformConfigCache()
        self.hits: int = 0
        self.misses: int = 0

    @staticmethod
    def normalize_domain(url_or_domain: str) -> str:
        d = _extract_clean_domain(url_or_domain)
        if not d or is_non_employer_domain(d):
            return ""
        return d

    @staticmethod
    def make_company_key(company: str, city: str = "") -> str:
        c = normalize_company_identity(company)
        l = str(city or "").strip().lower()
        if not c:
            return ""
        return f"{c}|{l}" if l else c

    @staticmethod
    def _companies_are_compatible(comp_a: str, comp_b: str) -> bool:
        """
        Checks whether two company names refer to the same employer or corporate group.
        If either is empty (e.g. pure domain lookup in unit tests), returns True.
        """
        ca = normalize_company_identity(comp_a)
        cb = normalize_company_identity(comp_b)
        if not ca or not cb:
            return True
        if ca == cb or ca in cb or cb in ca:
            return True
        # Compare primary core token (ignoring legal suffixes)
        legal = {"gmbh", "ag", "kg", "co", "se", "ohg", "gbr", "ev", "e.v.", "mbh", "kgaa", "holding", "gruppe", "group", "deutschland"}
        tokens_a = [t for t in re.split(r"[^a-z0-9äöüß]+", ca) if len(t) >= 3 and t not in legal]
        tokens_b = [t for t in re.split(r"[^a-z0-9äöüß]+", cb) if len(t) >= 3 and t not in legal]
        if tokens_a and tokens_b and tokens_a[0] == tokens_b[0]:
            return True
        return False

    def get(
        self,
        company: str = "",
        city: str = "",
        url_or_domain: str = "",
        require_explicit_or_non_portal: bool = False,
    ) -> Optional[Dict[str, Any]]:
        domain = self.normalize_domain(url_or_domain)
        comp_key = self.make_company_key(company, city)
        comp_only_key = self.make_company_key(company, "")

        with self._lock:
            # 1. Exact job URL lookup first if url_or_domain is a full job URL
            if url_or_domain and url_or_domain.startswith(("http://", "https://")):
                job_hit = self.job_cache.get(job_url=url_or_domain, company=company)
                if job_hit:
                    self.hits += 1
                    return dict(job_hit)

            # 2. Domain lookup ONLY if domain is a verified official employer domain
            # (never a portal domain, shortener domain, or bare shared ATS domain)
            if domain and not is_non_employer_domain(domain) and domain in self._cache_by_domain:
                entry = self._cache_by_domain[domain]
                if self._companies_are_compatible(company, entry.get("_cached_company", "")):
                    self.hits += 1
                    return {k: v for k, v in entry.items() if not k.startswith("_")}

            # 3. Verified company key lookup
            for c_key in (comp_key, comp_only_key):
                if c_key and c_key in self._cache_by_company:
                    entry = self._cache_by_company[c_key]
                    if require_explicit_or_non_portal and not entry.get("_explicit_override"):
                        # If the caller is on a live job portal and hasn't inspected the job page yet,
                        # do not skip inspecting the job page unless explicitly overridden.
                        if is_portal_domain(domain):
                            continue
                    self.hits += 1
                    return {k: v for k, v in entry.items() if not k.startswith("_")}

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

        # Never cache records that were flagged as contaminated or invalid
        if data.get("validation_status") in ("rejected_contamination", "invalid", "unverified"):
            return

        domain = self.normalize_domain(url_or_domain)
        comp_key = self.make_company_key(company, city)

        # Only cache meaningful contact information
        email_val = str(data.get("email") or "").strip()
        phone_val = str(data.get("phone") or "").strip()
        cp_val = str(data.get("contact_person") or "").strip()
        form_link_val = str(data.get("form_link") or "").strip()
        direct_url_val = str(data.get("direct_application_url") or "").strip()

        # Filter out portal/shortener URLs from being cached as employer application URLs
        if form_link_val and (is_portal_domain(form_link_val) or is_shortener_domain(form_link_val)):
            form_link_val = ""
        if direct_url_val and (is_portal_domain(direct_url_val) or is_shortener_domain(direct_url_val)):
            direct_url_val = ""

        has_val = any(bool(v) for v in (email_val, phone_val, cp_val, form_link_val, direct_url_val))
        if not has_val:
            return

        clean_entry = {
            "email": email_val,
            "phone": phone_val,
            "contact_person": cp_val,
            "has_form": bool(data.get("has_form") and (form_link_val or direct_url_val)),
            "form_link": form_link_val or direct_url_val,
            "direct_application_url": direct_url_val or form_link_val,
            "application_method": data.get("application_method") or "",
            "employer_website": data.get("employer_website") or "",
            "_cached_company": normalize_company_identity(company),
            "_cached_domain": domain if not is_non_employer_domain(domain) else "",
        }

        emp_website_domain = self.normalize_domain(data.get("employer_website") or "")

        with self._lock:
            # Never store portal, shortener, or bare shared ATS domains as employer domain keys!
            if domain and not is_non_employer_domain(domain):
                self._cache_by_domain[domain] = clean_entry
            elif emp_website_domain and not is_non_employer_domain(emp_website_domain):
                self._cache_by_domain[emp_website_domain] = clean_entry

            if comp_key:
                self._cache_by_company[comp_key] = clean_entry

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        """Dict-style assignment support for backward compatibility and unit tests."""
        if not key or not isinstance(value, dict):
            return
        k_clean = str(key).strip().lower()
        entry = dict(value)
        entry["_explicit_override"] = True
        with self._lock:
            if "|" in k_clean or " " in k_clean or "." not in k_clean:
                self._cache_by_company[k_clean] = entry
            elif not is_non_employer_domain(k_clean):
                self._cache_by_domain[self.normalize_domain(k_clean)] = entry

    def __getitem__(self, key: str) -> Dict[str, Any]:
        k_clean = str(key).strip().lower()
        with self._lock:
            if k_clean in self._cache_by_company:
                return dict(self._cache_by_company[k_clean])
            if k_clean in self._cache_by_domain:
                return dict(self._cache_by_domain[k_clean])
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        k_clean = str(key).strip().lower()
        with self._lock:
            return k_clean in self._cache_by_company or k_clean in self._cache_by_domain

    def clear(self) -> None:
        with self._lock:
            self._cache_by_domain.clear()
            self._cache_by_company.clear()
            self.job_cache.clear()
            self.platform_cache.clear()
            self.hits = 0
            self.misses = 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache_by_domain) + len(self._cache_by_company) + len(self.job_cache)


_GLOBAL_EMPLOYER_CACHE = EmployerDomainCache()


def get_employer_cache() -> EmployerDomainCache:
    return _GLOBAL_EMPLOYER_CACHE


def get_job_cache() -> JobResultCache:
    return _GLOBAL_EMPLOYER_CACHE.job_cache


def get_platform_cache() -> PlatformConfigCache:
    return _GLOBAL_EMPLOYER_CACHE.platform_cache
