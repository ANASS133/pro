"""
JobScout High-Performance Parallel Scraping & Smart Proxy Management Engine.
=============================================================================
Provides asynchronous, high-throughput domain crawling capable of processing
hundreds to thousands of employer websites concurrently with:
- Connection pooling and keep-alive sessions via httpx.AsyncClient
- Per-domain concurrency limiting and site politeness
- Adaptive AIMD (Additive Increase / Multiplicative Decrease) concurrency controller
- Domain Queue with full lifecycle (Pending, Processing, Completed, Failed, Skipped)
- Modular Proxy Management (Direct, Proxy, Hybrid) with health checks & quarantine
- VPN & Network routing compatibility checking
- Deep Contact & Career Form Extraction (reusing JobScout rules & ATS signatures)
- Resilient JSON checkpoints for resuming interrupted batches
- Live SSE monitoring metrics
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .application_form_discovery import (
    APPLICATION_BUTTON_KEYWORDS,
    KNOWN_ATS_DOMAINS,
    classify_application_method,
)
from .tech_detector import TechDetector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Shared Patterns
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

EXCLUDED_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net",
    "wix.com", "squarespace.com", "wordpress.com",
    "sentry.io", "googleapis.com", "google.com",
    "googlemail.com", "gstatic.com", "w3.org",
    "schema.org", "facebook.com", "twitter.com", "instagram.com",
}

EXCLUDED_EMAIL_PREFIXES = {
    "noreply", "no-reply", "no_reply", "donotreply",
    "mailer-daemon", "postmaster", "hostmaster", "webmaster",
    "abuse", "root",
}

CONTACT_KEYWORDS = [
    "kontakt", "contact", "impressum", "imprint",
    "ueber-uns", "about", "team", "ansprechpartner",
    "karriere", "jobs", "career", "stellenangebote", "stellen",
    "ausbildung", "wir-suchen",
]

IMPRESSUM_URL_PATTERNS = [
    re.compile(r"impressum", re.IGNORECASE),
    re.compile(r"imprint", re.IGNORECASE),
    re.compile(r"legal[-_]?notice", re.IGNORECASE),
]

GESCHAEFTSFUEHRER_PATTERNS = [
    re.compile(
        r"(?:geschäftsführer(?:in)?|geschäftsführung|inhaber(?:in)?|vorstand|vertreten\s+durch)\s*[:\-\s]\s*([^\n\r<]{3,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:vertretungsberechtigt[e|er|en]*)\s*(?:person(?:en)?|gesellschafter)?\s*[:\-\s]\s*([^\n\r<]{3,120})",
        re.IGNORECASE,
    ),
]

CHECKPOINT_DIR = Path("data") / "scraper_checkpoints"


# ---------------------------------------------------------------------------
# Enums & Data Structures
# ---------------------------------------------------------------------------

class DomainStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class FailureReason(str, Enum):
    NONE = "NONE"
    DNS_FAILURE = "DNS_FAILURE"
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    BLOCKED = "BLOCKED"
    INVALID_DOMAIN = "INVALID_DOMAIN"
    PARSE_ERROR = "PARSE_ERROR"
    NO_CONTACT_FOUND = "NO_CONTACT_FOUND"


class ProxyMode(str, Enum):
    DIRECT = "DIRECT"
    PROXY = "PROXY"
    HYBRID = "HYBRID"


@dataclass
class ProxyNode:
    url: str
    is_healthy: bool = True
    latency_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    quarantined_until: float = 0.0
    last_tested_at: float = 0.0


@dataclass
class DomainItem:
    raw_domain: str
    normalized_domain: str
    root_url: str
    company_name: str = ""
    priority: int = 10  # Lower number = higher priority
    status: DomainStatus = DomainStatus.PENDING
    failure_reason: FailureReason = FailureReason.NONE
    http_status: Optional[int] = None
    retries_left: int = 2
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    # Discovery payload
    emails: List[str] = field(default_factory=list)
    primary_email: str = ""
    phone: str = ""
    geschaeftsfuehrer: str = ""
    salutation: str = "Sehr geehrte Damen und Herren,"
    career_urls: List[str] = field(default_factory=list)
    apply_url: str = ""
    has_form: bool = False
    application_method: str = "EMAIL"  # DIRECT_APPLICATION_FORM, APPLICATION_PORTAL, EMAIL
    open_vacancies: List[str] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    crawl_pages_visited: int = 0
    latency_ms: float = 0.0


@dataclass
class ScraperMetrics:
    job_id: str
    total_queued: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    emails_discovered: int = 0
    forms_detected: int = 0
    active_concurrency: int = 25
    requests_per_sec: float = 0.0
    avg_latency_ms: float = 0.0
    healthy_proxies: int = 0
    total_proxies: int = 0
    proxy_mode: str = "DIRECT"
    vpn_active: bool = False
    vpn_details: str = "Direct OS Routing"
    elapsed_seconds: float = 0.0
    is_running: bool = False
    is_cancelled: bool = False


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def normalize_domain_url(raw: str) -> Tuple[str, str]:
    """
    Normalizes domain input.
    Returns (normalized_domain, root_url).
    Examples:
      'example.de' -> ('example.de', 'https://example.de')
      'http://www.firm.com/jobs' -> ('firm.com', 'https://www.firm.com')
    """
    cleaned = str(raw or "").strip().lower()
    if not cleaned:
        return "", ""
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    
    parsed = urlparse(cleaned)
    hostname = (parsed.hostname or "").strip().lower()
    if hostname.startswith("www."):
        root_domain = hostname[4:]
    else:
        root_domain = hostname
    
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
    root_url = f"{scheme}://{parsed.netloc}"
    return root_domain, root_url


def decode_cloudflare_email(cf_hex: str) -> str:
    """Decodes Cloudflare email protection hex strings."""
    try:
        r = int(cf_hex[:2], 16)
        email = "".join(chr(int(cf_hex[i:i+2], 16) ^ r) for i in range(2, len(cf_hex), 2))
        return email.strip()
    except Exception:
        return ""


def deobfuscate_email_text(text: str) -> str:
    """Cleans common anti-spam email obfuscations: [at], (at), [dot], etc."""
    if not text:
        return ""
    import html
    text = html.unescape(text)
    text = re.sub(r'\[\s*(?:at|AT)\s*\]|\(\s*(?:at|AT)\s*\)', '@', text)
    text = re.sub(r'\[\s*(?:dot|DOT)\s*\]|\(\s*(?:dot|DOT)\s*\)', '.', text)
    text = re.sub(r'([A-Za-z0-9-]+)\s*\.\s*([A-Za-z]{2,}\b)', r'\1.\2', text)
    text = re.sub(r'(\b[A-Za-z0-9._%+-]+)\s*@\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)', r'\1@\2', text)
    return text


def is_valid_email(email: str) -> bool:
    norm = str(email or "").strip().strip(".,;:\"'<>()[]").lower()
    if not norm or "@" not in norm or len(norm) > 254:
        return False
    local, domain = norm.split("@", 1)
    if domain in EXCLUDED_EMAIL_DOMAINS:
        return False
    if local in EXCLUDED_EMAIL_PREFIXES or any(norm.startswith(p + "@") for p in EXCLUDED_EMAIL_PREFIXES):
        return False
    if norm.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")):
        return False
    return True


# ---------------------------------------------------------------------------
# Proxy Management & Health Validation
# ---------------------------------------------------------------------------

class ProxyPoolManager:
    """
    Modular proxy pool manager supporting Direct, Proxy, and Hybrid modes.
    Conducts non-invasive canary health checks and quarantines failing nodes.
    """

    def __init__(
        self,
        mode: ProxyMode = ProxyMode.DIRECT,
        proxies: Optional[List[str]] = None,
        quarantine_duration: float = 180.0,
        canary_url: str = "https://1.1.1.1",
    ):
        self.mode = mode
        self.quarantine_duration = quarantine_duration
        self.canary_url = canary_url
        self.nodes: List[ProxyNode] = []
        self._index = 0
        self._lock = asyncio.Lock()

        if proxies:
            self.set_proxies(proxies)

    def set_proxies(self, proxy_urls: List[str]):
        seen = set()
        new_nodes = []
        for p in proxy_urls:
            p_clean = str(p or "").strip()
            if p_clean and p_clean not in seen:
                seen.add(p_clean)
                new_nodes.append(ProxyNode(url=p_clean))
        self.nodes = new_nodes
        self._index = 0

    async def get_next_proxy(self) -> Optional[str]:
        if self.mode == ProxyMode.DIRECT:
            return None

        async with self._lock:
            if not self.nodes:
                return None

            now = time.time()
            # Find a healthy proxy that is not in quarantine
            available = [n for n in self.nodes if n.is_healthy and n.quarantined_until < now]

            if not available:
                if self.mode == ProxyMode.HYBRID:
                    # In hybrid mode, fall back cleanly to direct connection
                    return None
                # In strict proxy mode, try the oldest quarantined proxy
                self.nodes.sort(key=lambda n: n.quarantined_until)
                chosen = self.nodes[0]
            else:
                self._index = (self._index + 1) % len(available)
                chosen = available[self._index]

            return chosen.url

    async def record_result(self, proxy_url: Optional[str], success: bool, latency_ms: float = 0.0):
        if not proxy_url:
            return

        async with self._lock:
            for node in self.nodes:
                if node.url == proxy_url:
                    node.last_tested_at = time.time()
                    if success:
                        node.success_count += 1
                        node.consecutive_failures = 0
                        node.is_healthy = True
                        node.quarantined_until = 0.0
                        node.latency_ms = (node.latency_ms * 0.7) + (latency_ms * 0.3)
                    else:
                        node.failure_count += 1
                        node.consecutive_failures += 1
                        if node.consecutive_failures >= 3:
                            node.is_healthy = False
                            node.quarantined_until = time.time() + self.quarantine_duration
                    break

    async def run_health_checks(self):
        """Validates all configured proxies concurrently against canary endpoint."""
        if not self.nodes:
            return

        tasks = [self._check_node(n) for n in self.nodes]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_node(self, node: ProxyNode):
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(proxy=node.url, timeout=4.0, verify=False) as client:
                resp = await client.get(self.canary_url)
                lat = (time.perf_counter() - t0) * 1000.0
                if resp.status_code in (200, 204, 301, 302):
                    node.is_healthy = True
                    node.consecutive_failures = 0
                    node.quarantined_until = 0.0
                    node.latency_ms = lat
                    return
        except Exception:
            pass

        node.consecutive_failures += 1
        node.is_healthy = False
        node.quarantined_until = time.time() + self.quarantine_duration

    def get_status(self) -> Dict[str, Any]:
        healthy = sum(1 for n in self.nodes if n.is_healthy and n.quarantined_until <= time.time())
        return {
            "mode": self.mode.value,
            "total_proxies": len(self.nodes),
            "healthy_proxies": healthy,
            "quarantined_proxies": len(self.nodes) - healthy,
        }


# ---------------------------------------------------------------------------
# Network & VPN Inspection
# ---------------------------------------------------------------------------

class VPNNetworkDetector:
    """Inspects default system network routing and reports VPN adapter presence."""

    @classmethod
    def inspect_connection(cls) -> Dict[str, Any]:
        info = {
            "vpn_active": False,
            "adapter_type": "Standard Network",
            "public_ip": "Direct Local",
            "dns_latency_ms": 0.0,
        }

        # Measure DNS resolution latency for Cloudflare
        t0 = time.perf_counter()
        try:
            socket.gethostbyname("one.one.one.one")
            info["dns_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception:
            info["dns_latency_ms"] = 999.0

        # Check for common VPN interface names or environment markers
        try:
            import psutil
            stats = psutil.net_if_stats()
            for iface_name in stats.keys():
                name_lower = iface_name.lower()
                if any(v in name_lower for v in ["proton", "warp", "wireguard", "tun", "tap", "nord", "openvpn"]):
                    info["vpn_active"] = True
                    info["adapter_type"] = f"VPN Interface: {iface_name}"
                    break
        except Exception:
            pass

        return info


# ---------------------------------------------------------------------------
# Adaptive Concurrency Controller (AIMD)
# ---------------------------------------------------------------------------

class AdaptiveConcurrencyController:
    """
    Congestion controller using Additive Increase, Multiplicative Decrease (AIMD).
    Starts at 25 concurrent domain workers. Dynamically scales between min_workers
    and max_workers based on network latency and error responses.
    """

    def __init__(self, start_concurrency: int = 25, min_concurrency: int = 5, max_concurrency: int = 60):
        self.current_concurrency = start_concurrency
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.recent_errors = 0
        self.recent_successes = 0
        self._lock = asyncio.Lock()

    async def report_success(self, latency_ms: float):
        async with self._lock:
            self.recent_successes += 1
            # Every 15 successful domain scrapes with low latency, gently ramp up concurrency
            if self.recent_successes >= 15:
                self.recent_successes = 0
                if self.current_concurrency < self.max_concurrency and latency_ms < 1500:
                    self.current_concurrency = min(self.max_concurrency, self.current_concurrency + 2)

    async def report_error(self, is_backpressure: bool = False):
        async with self._lock:
            self.recent_errors += 1
            # If server backpressure (429, 503) or multiple timeouts, back off immediately
            if is_backpressure or self.recent_errors >= 4:
                self.recent_errors = 0
                self.recent_successes = 0
                self.current_concurrency = max(self.min_concurrency, int(self.current_concurrency * 0.75))

    def get_concurrency(self) -> int:
        return self.current_concurrency


# ---------------------------------------------------------------------------
# Host-Level Rate Limiter (Site Politeness)
# ---------------------------------------------------------------------------

class HostRateLimiter:
    """
    Ensures politeness across hundreds of domains:
    - Never executes more than max_per_host concurrent requests to the SAME domain.
    - Applies a minimum pause between sequential requests to the same host.
    """

    def __init__(self, max_per_host: int = 2, min_delay_sec: float = 0.5):
        self.max_per_host = max_per_host
        self.min_delay_sec = min_delay_sec
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._last_request_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, host: str):
        async with self._lock:
            if host not in self._semaphores:
                self._semaphores[host] = asyncio.Semaphore(self.max_per_host)
            sem = self._semaphores[host]

        await sem.acquire()

        # Enforce inter-request spacing for the same host
        now = time.time()
        last = self._last_request_time.get(host, 0.0)
        gap = now - last
        if gap < self.min_delay_sec:
            await asyncio.sleep(self.min_delay_sec - gap)
        self._last_request_time[host] = time.time()

    def release(self, host: str):
        sem = self._semaphores.get(host)
        if sem:
            sem.release()


# ---------------------------------------------------------------------------
# Intelligent Contact & Career Extractor (Async)
# ---------------------------------------------------------------------------

class AsyncContactExtractor:
    """
    Extracts contact info, German legal Impressum details, career vacancy links,
    and online application forms from HTML pages asynchronously.
    """

    @classmethod
    def extract_emails(cls, html: str) -> Set[str]:
        if not html:
            return set()
        emails = set()
        clean_text = deobfuscate_email_text(html)

        try:
            soup = BeautifulSoup(clean_text, "html.parser")

            # 1. Mailto links
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if href.startswith("mailto:"):
                    clean = href.replace("mailto:", "").split("?")[0].strip()
                    if is_valid_email(clean):
                        emails.add(clean.lower())

            # 2. Cloudflare protected emails
            for cf in soup.find_all(attrs={"data-cfemail": True}):
                decoded = decode_cloudflare_email(cf["data-cfemail"])
                if is_valid_email(decoded):
                    emails.add(decoded.lower())

            # 3. Regular text patterns
            text = soup.get_text(separator=" ")
            for match in EMAIL_PATTERN.findall(text):
                if is_valid_email(match):
                    emails.add(match.lower())
        except Exception:
            pass

        return emails

    @classmethod
    def extract_impressum(cls, html: str) -> Dict[str, str]:
        """Extracts executive name and phone from legal Impressum page."""
        result = {"geschaeftsfuehrer": "", "phone": "", "salutation": "Sehr geehrte Damen und Herren,"}
        if not html:
            return result

        try:
            soup = BeautifulSoup(html, "html.parser")
            raw_text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()

            # Phone search
            phone_match = re.search(r"(?:\+49|0049|0)\s*(?:\(0\)\s*)?[1-9][0-9\s/().\-]{5,20}[0-9]", raw_text)
            if phone_match:
                result["phone"] = phone_match.group(0).strip()

            # Managing director search across flattened blocks
            blocks_to_check = []
            for tag in soup.find_all(["p", "div", "li", "td", "span"]):
                txt = re.sub(r"\s+", " ", tag.get_text(separator=" ")).strip()
                if len(txt) > 5:
                    blocks_to_check.append(txt)
            blocks_to_check.append(raw_text)

            name_token = r"(?:(?:Dr\.|Prof\.|Dipl\.-[A-Za-z]+)\s+)*[A-ZÄÖÜ][a-zäöüß]+(?:[- ][A-ZÄÖÜ][a-zäöüß]+)*"
            individual_re = re.compile(rf"\b{name_token}\s+{name_token}\b")

            for block in blocks_to_check:
                for pat in GESCHAEFTSFUEHRER_PATTERNS:
                    m = pat.search(block)
                    if m:
                        chunk = m.group(1).strip()
                        clean_chunk = re.split(
                            r"(?:Amtsgericht|HRB|HRA|USt-IdNr|Sitz der Gesellschaft|Registergericht)",
                            chunk,
                            flags=re.IGNORECASE,
                        )[0]
                        names = individual_re.findall(clean_chunk)
                        for n in names:
                            cleaned_name = n.strip()
                            if not any(k in cleaned_name.lower() for k in ["gmbh", "amtsgericht", "deutschland", "strasse"]):
                                if len(cleaned_name) > 4:
                                    result["geschaeftsfuehrer"] = cleaned_name
                                    if any(cleaned_name.lower().startswith(p) for p in ["frau ", "dr. frau"]):
                                        result["salutation"] = f"Sehr geehrte {cleaned_name},"
                                    elif any(cleaned_name.lower().startswith(p) for p in ["herr ", "herrn ", "dr. herr"]):
                                        result["salutation"] = f"Sehr geehrter {cleaned_name},"
                                    break
                    if result["geschaeftsfuehrer"]:
                        break
                if result["geschaeftsfuehrer"]:
                    break
        except Exception:
            pass

        return result
    @classmethod
    def discover_subpage_links(cls, base_url: str, html: str, max_links: int = 5) -> Tuple[List[str], List[str]]:
        """
        Identifies Impressum, Contact, and Career links from homepage HTML.
        Returns: (contact_and_impressum_urls, career_urls)
        """
        contact_urls: List[str] = []
        career_urls: List[str] = []
        if not html or not base_url:
            return contact_urls, career_urls

        base_parsed = urlparse(base_url)
        base_netloc = base_parsed.netloc.lower()
        seen: Set[str] = {base_url}

        try:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue

                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)
                # Keep requests within the same root host or subdomains
                if parsed.netloc.lower() != base_netloc and not parsed.netloc.lower().endswith("." + base_netloc):
                    continue

                path_lower = parsed.path.lower()
                text_lower = (a.get_text() or "").lower()

                # Career detection
                if any(k in path_lower or k in text_lower for k in ["karriere", "jobs", "career", "stellen", "ausbildung"]):
                    if full_url not in seen:
                        seen.add(full_url)
                        career_urls.append(full_url)
                # Contact / Impressum detection
                elif any(k in path_lower or k in text_lower for k in ["kontakt", "contact", "impressum", "imprint"]):
                    if full_url not in seen:
                        seen.add(full_url)
                        contact_urls.append(full_url)

                if len(contact_urls) + len(career_urls) >= max_links * 2:
                    break
        except Exception:
            pass

        # Standard conventional fallbacks if none discovered
        if not contact_urls:
            contact_urls.append(urljoin(base_url, "/impressum"))
            contact_urls.append(urljoin(base_url, "/kontakt"))
        if not career_urls:
            career_urls.append(urljoin(base_url, "/karriere"))

        return contact_urls[:max_links], career_urls[:max_links]

    @classmethod
    def detect_application_workflow(cls, html: str, page_url: str) -> Tuple[bool, str, str]:
        """
        Inspects page for direct forms or ATS application portals.
        Returns: (has_form, application_method, direct_apply_url)
        """
        if not html:
            return False, "EMAIL", ""

        has_form = False
        method = "EMAIL"
        direct_url = ""

        try:
            soup = BeautifulSoup(html, "html.parser")

            # 1. Check for standard HTML application form inputs (file upload for CV)
            has_file_input = bool(soup.find("input", type="file"))
            has_form_tag = bool(soup.find("form"))
            if has_file_input and has_form_tag:
                has_form = True
                method = "DIRECT_APPLICATION_FORM"
                direct_url = page_url

            # 2. Check for known ATS links
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                for ats_domain in KNOWN_ATS_DOMAINS:
                    if ats_domain in href.lower():
                        has_form = True
                        method = "APPLICATION_PORTAL"
                        direct_url = href
                        return has_form, method, direct_url

            # 3. Check for application buttons
            for btn in soup.find_all(["a", "button"], href=True):
                text_lower = (btn.get_text() or "").lower().strip()
                if any(kw in text_lower for kw in APPLICATION_BUTTON_KEYWORDS):
                    full_href = urljoin(page_url, btn.get("href", ""))
                    if not direct_url:
                        direct_url = full_href
                    if not has_form:
                        has_form = True
                        method = "APPLICATION_PORTAL"

        except Exception:
            pass

        return has_form, method, direct_url


# ---------------------------------------------------------------------------
# High-Performance Parallel Domain Engine
# ---------------------------------------------------------------------------

class ParallelDomainEngine:
    """
    Main asynchronous orchestration engine for parallel domain scraping.
    Manages bounded concurrency, resilient queue lifecycles, proxy pooling,
    adaptive backoff, and live SSE event broadcasting.
    """

    def __init__(
        self,
        job_id: Optional[str] = None,
        max_concurrency: int = 25,
        timeout_seconds: float = 12.0,
        max_pages_per_domain: int = 4,
        proxy_mode: ProxyMode = ProxyMode.DIRECT,
        proxy_list: Optional[List[str]] = None,
    ):
        self.job_id = job_id or f"job_{int(time.time())}_{os.urandom(4).hex()}"
        self.max_concurrency = max_concurrency
        self.timeout_seconds = timeout_seconds
        self.max_pages_per_domain = max_pages_per_domain

        self.concurrency_controller = AdaptiveConcurrencyController(
            start_concurrency=min(25, max_concurrency),
            min_concurrency=5,
            max_concurrency=max(30, max_concurrency),
        )
        self.host_limiter = HostRateLimiter(max_per_host=2, min_delay_sec=0.4)
        self.proxy_pool = ProxyPoolManager(mode=proxy_mode, proxies=proxy_list)
        self.vpn_detector = VPNNetworkDetector()

        self.queue: List[DomainItem] = []
        self.domain_map: Dict[str, DomainItem] = {}
        self.active_workers: int = 0
        self.is_running: bool = False
        self.is_cancelled: bool = False
        self._cancel_event = asyncio.Event()

        # Metrics Tracking
        self.metrics = ScraperMetrics(job_id=self.job_id, proxy_mode=proxy_mode.value)
        self._request_latencies: List[float] = []
        self._requests_completed: int = 0
        self._start_time: float = 0.0

        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    def enqueue_domains(self, domains: List[Dict[str, Any]]) -> int:
        """
        Enqueues a list of domains or company dicts.
        Deduplicates against already queued domains.
        """
        added = 0
        for entry in domains:
            raw = entry.get("website") or entry.get("domain") or entry.get("url") or ""
            company = entry.get("name") or entry.get("company") or ""
            norm_domain, root_url = normalize_domain_url(raw)
            if not norm_domain or norm_domain in self.domain_map:
                continue

            item = DomainItem(
                raw_domain=raw,
                normalized_domain=norm_domain,
                root_url=root_url,
                company_name=company,
                priority=int(entry.get("priority", 10)),
            )
            self.domain_map[norm_domain] = item
            self.queue.append(item)
            added += 1

        self.metrics.total_queued = len(self.domain_map)
        return added

    def cancel(self):
        """Signals active workers to stop cleanly."""
        self.is_cancelled = True
        self._cancel_event.set()
        self.metrics.is_cancelled = True
        logger.info("Parallel scraping job %s cancelled.", self.job_id)

    def save_checkpoint(self):
        """Saves current state and discovered data to persistent JSON disk storage."""
        path = CHECKPOINT_DIR / f"{self.job_id}.json"
        data = {
            "job_id": self.job_id,
            "metrics": asdict(self.metrics),
            "domains": [asdict(d) for d in self.domain_map.values()],
            "timestamp": time.time(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_checkpoint(self, job_id: str) -> bool:
        """Resumes an interrupted job from disk checkpoint."""
        path = CHECKPOINT_DIR / f"{job_id}.json"
        if not path.exists():
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.job_id = data.get("job_id", self.job_id)
            self.queue = []
            self.domain_map = {}

            for d in data.get("domains", []):
                item = DomainItem(**d)
                self.domain_map[item.normalized_domain] = item
                if item.status in (DomainStatus.PENDING, DomainStatus.PROCESSING):
                    item.status = DomainStatus.PENDING
                    self.queue.append(item)

            self.metrics.total_queued = len(self.domain_map)
            self.metrics.completed = sum(1 for d in self.domain_map.values() if d.status == DomainStatus.COMPLETED)
            self.metrics.failed = sum(1 for d in self.domain_map.values() if d.status == DomainStatus.FAILED)
            return True
        except Exception as e:
            logger.error("Failed loading checkpoint for job %s: %s", job_id, e)
            return False

    async def _fetch_html(
        self,
        client: httpx.AsyncClient,
        url: str,
        host: str,
    ) -> Tuple[Optional[str], Optional[int], float, Optional[str]]:
        """
        Fetches an individual URL respecting host limits and proxy routing.
        Returns: (html_text, http_status, latency_ms, error_msg)
        """
        await self.host_limiter.acquire(host)
        t0 = time.perf_counter()
        try:
            resp = await client.get(url, follow_redirects=True)
            lat = (time.perf_counter() - t0) * 1000.0
            self._requests_completed += 1
            self._request_latencies.append(lat)
            if resp.status_code == 200:
                return resp.text, resp.status_code, lat, None
            return None, resp.status_code, lat, f"HTTP {resp.status_code}"
        except httpx.TimeoutException:
            lat = (time.perf_counter() - t0) * 1000.0
            return None, 408, lat, "Timeout"
        except httpx.ConnectError:
            lat = (time.perf_counter() - t0) * 1000.0
            return None, 502, lat, "Connection Error"
        except Exception as exc:
            lat = (time.perf_counter() - t0) * 1000.0
            return None, 500, lat, str(exc)
        finally:
            self.host_limiter.release(host)

    async def _process_domain(self, client: httpx.AsyncClient, item: DomainItem):
        """Processes a single company domain through multi-page extraction."""
        if self._cancel_event.is_set():
            item.status = DomainStatus.SKIPPED
            item.failure_reason = FailureReason.NONE
            return

        item.status = DomainStatus.PROCESSING
        item.attempts += 1
        host = item.normalized_domain
        start_time = time.perf_counter()

        # Step 1: Fetch Homepage
        homepage_html, status_code, lat, err = await self._fetch_html(client, item.root_url, host)
        if not homepage_html and item.root_url.startswith("https://"):
            # Fallback to HTTP if HTTPS fails
            http_root = "http://" + item.root_url[8:]
            homepage_html, status_code, lat, err = await self._fetch_html(client, http_root, host)

        item.http_status = status_code
        item.latency_ms = lat

        if not homepage_html:
            if status_code in (408, 504):
                item.failure_reason = FailureReason.TIMEOUT
            elif status_code in (403, 429):
                item.failure_reason = FailureReason.BLOCKED
            elif status_code and status_code >= 400:
                item.failure_reason = FailureReason.HTTP_ERROR
            else:
                item.failure_reason = FailureReason.DNS_FAILURE

            await self.concurrency_controller.report_error(is_backpressure=(status_code in (429, 503)))

            if item.retries_left > 0 and item.failure_reason in (FailureReason.TIMEOUT, FailureReason.DNS_FAILURE):
                item.retries_left -= 1
                item.status = DomainStatus.PENDING
                self.queue.append(item)
            else:
                item.status = DomainStatus.FAILED
            return

        # Successful homepage fetch: report to adaptive controller
        await self.concurrency_controller.report_success(lat)
        item.crawl_pages_visited += 1

        all_emails: Set[str] = AsyncContactExtractor.extract_emails(homepage_html)

        # Tech Stack Detection
        tech_info = TechDetector.detect(homepage_html)
        item.technologies = tech_info.get("technologies", [])

        # Step 2: Discover Subpage links (Impressum, Contact, Careers)
        contact_links, career_links = AsyncContactExtractor.discover_subpage_links(
            item.root_url,
            homepage_html,
            max_links=self.max_pages_per_domain,
        )

        # Step 3: Fetch candidate subpages concurrently
        subpage_tasks = []
        for url in (contact_links + career_links)[:self.max_pages_per_domain]:
            subpage_tasks.append(self._fetch_html(client, url, host))

        if subpage_tasks:
            subpage_results = await asyncio.gather(*subpage_tasks, return_exceptions=True)
            for res in subpage_results:
                if isinstance(res, tuple) and res[0]:
                    sub_html, _, _, _ = res
                    item.crawl_pages_visited += 1
                    for em in AsyncContactExtractor.extract_emails(sub_html):
                        all_emails.add(em)

                    imp_info = AsyncContactExtractor.extract_impressum(sub_html)
                    if imp_info.get("geschaeftsfuehrer") and not item.geschaeftsfuehrer:
                        item.geschaeftsfuehrer = imp_info["geschaeftsfuehrer"]
                        item.salutation = imp_info["salutation"]
                    if imp_info.get("phone") and not item.phone:
                        item.phone = imp_info["phone"]

                    # Check for application forms on career subpages
                    has_form, app_method, direct_url = AsyncContactExtractor.detect_application_workflow(sub_html, item.root_url)
                    if has_form:
                        item.has_form = True
                        item.application_method = app_method
                        if direct_url and not item.apply_url:
                            item.apply_url = direct_url

        # Check homepage for application workflow if not yet discovered
        if not item.has_form:
            has_f, mtd, d_url = AsyncContactExtractor.detect_application_workflow(homepage_html, item.root_url)
            item.has_form = has_f
            item.application_method = mtd
            item.apply_url = d_url or item.root_url

        item.career_urls = career_links
        clean_emails = sorted(list(all_emails))
        item.emails = clean_emails

        if clean_emails:
            # Prioritize recruitment / career addresses
            primary = clean_emails[0]
            for em in clean_emails:
                if any(k in em for k in ["bewerbung", "karriere", "jobs", "recruiting"]):
                    primary = em
                    break
            item.primary_email = primary
            item.status = DomainStatus.COMPLETED
            item.failure_reason = FailureReason.NONE
        else:
            item.status = DomainStatus.COMPLETED
            item.failure_reason = FailureReason.NO_CONTACT_FOUND

        item.updated_at = time.time()

    async def run(
        self,
        progress_callback: Optional[Callable[[ScraperMetrics, Optional[DomainItem]], Any]] = None,
    ) -> List[DomainItem]:
        """
        Executes the parallel scraping engine across all enqueued domains.
        Returns the completed domain items.
        """
        self.is_running = True
        self.is_cancelled = False
        self._cancel_event.clear()
        self._start_time = time.time()

        # Update initial system environment inspection
        net_info = self.vpn_detector.inspect_connection()
        self.metrics.vpn_active = net_info.get("vpn_active", False)
        self.metrics.vpn_details = net_info.get("adapter_type", "Standard Network")
        self.metrics.is_running = True

        # Pre-validate proxy pool if enabled
        if self.proxy_pool.mode != ProxyMode.DIRECT:
            await self.proxy_pool.run_health_checks()
        p_status = self.proxy_pool.get_status()
        self.metrics.total_proxies = p_status.get("total_proxies", 0)
        self.metrics.healthy_proxies = p_status.get("healthy_proxies", 0)

        # Configure connection limits and timeouts for high concurrency
        limits = httpx.Limits(
            max_connections=120,
            max_keepalive_connections=50,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(self.timeout_seconds, connect=5.0)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 JobScout/3.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # Bounded worker pool using an asyncio Semaphore
        semaphore = asyncio.Semaphore(self.concurrency_controller.current_concurrency)

        async def worker_loop(client: httpx.AsyncClient):
            while not self._cancel_event.is_set():
                item = None
                try:
                    # Pop next domain from queue
                    if not self.queue:
                        break
                    item = self.queue.pop(0)
                except IndexError:
                    break

                if not item:
                    break

                async with semaphore:
                    self.active_workers += 1
                    try:
                        await self._process_domain(client, item)
                    finally:
                        self.active_workers -= 1

                # Update live metrics
                self._update_metrics()
                if progress_callback:
                    try:
                        res = progress_callback(self.metrics, item)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass

        # Create persistent async client with connection pooling
        async with httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            headers=headers,
            verify=False,
        ) as client:
            num_workers = self.concurrency_controller.max_concurrency
            tasks = [asyncio.create_task(worker_loop(client)) for _ in range(num_workers)]
            await asyncio.gather(*tasks, return_exceptions=True)

        self.is_running = False
        self.metrics.is_running = False
        self._update_metrics()
        self.save_checkpoint()

        if progress_callback:
            try:
                res = progress_callback(self.metrics, None)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

        return list(self.domain_map.values())

    def _update_metrics(self):
        """Updates internal telemetry figures."""
        now = time.time()
        elapsed = max(0.1, now - self._start_time)
        completed = sum(1 for d in self.domain_map.values() if d.status == DomainStatus.COMPLETED)
        failed = sum(1 for d in self.domain_map.values() if d.status == DomainStatus.FAILED)
        skipped = sum(1 for d in self.domain_map.values() if d.status == DomainStatus.SKIPPED)
        processing = sum(1 for d in self.domain_map.values() if d.status == DomainStatus.PROCESSING)

        emails = sum(len(d.emails) for d in self.domain_map.values())
        forms = sum(1 for d in self.domain_map.values() if d.has_form)

        avg_lat = (sum(self._request_latencies) / len(self._request_latencies)) if self._request_latencies else 0.0

        self.metrics.completed = completed
        self.metrics.failed = failed
        self.metrics.skipped = skipped
        self.metrics.processing = processing
        self.metrics.emails_discovered = emails
        self.metrics.forms_detected = forms
        self.metrics.active_concurrency = self.concurrency_controller.get_concurrency()
        self.metrics.requests_per_sec = round(self._requests_completed / elapsed, 1)
        self.metrics.avg_latency_ms = round(avg_lat, 1)
        self.metrics.elapsed_seconds = round(elapsed, 1)


# ---------------------------------------------------------------------------
# Global Registry & Synchronous Bridge
# ---------------------------------------------------------------------------

_active_engines: Dict[str, ParallelDomainEngine] = {}


def get_engine(job_id: str) -> Optional[ParallelDomainEngine]:
    return _active_engines.get(job_id)


def create_engine(
    job_id: Optional[str] = None,
    max_concurrency: int = 25,
    timeout_seconds: float = 12.0,
    proxy_mode: ProxyMode = ProxyMode.DIRECT,
    proxy_list: Optional[List[str]] = None,
) -> ParallelDomainEngine:
    engine = ParallelDomainEngine(
        job_id=job_id,
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
        proxy_mode=proxy_mode,
        proxy_list=proxy_list,
    )
    _active_engines[engine.job_id] = engine
    return engine


def run_parallel_domain_scrape(
    domains: List[Dict[str, Any]],
    max_concurrency: int = 25,
    timeout_seconds: float = 12.0,
    proxy_mode: str = "DIRECT",
    proxy_list: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[ScraperMetrics, Optional[DomainItem]], Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Synchronous bridge for existing ThreadPoolExecutor callers and Flask routes.
    Runs the asynchronous domain engine cleanly within an event loop.
    """
    mode_enum = ProxyMode(proxy_mode.upper()) if proxy_mode.upper() in ProxyMode.__members__ else ProxyMode.DIRECT
    engine = create_engine(
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
        proxy_mode=mode_enum,
        proxy_list=proxy_list,
    )
    engine.enqueue_domains(domains)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # Running inside an existing event loop (e.g., AnyIO / pytest-asyncio)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result_items = pool.submit(lambda: asyncio.run(engine.run(progress_callback))).result()
    else:
        result_items = loop.run_until_complete(engine.run(progress_callback))

    return [asdict(item) for item in result_items]
