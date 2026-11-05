"""
JobScout Rate Limiting & Anti-Bot Protection Module
===================================================
Implements intelligent HTTP 429 rate limit handling, domain circuit breakers,
micro-jitter, and browser header rotation to ensure resilient scraping without
tripping bot barriers or getting IP-banned.

Key Capabilities:
  • Idea A: Honors `Retry-After` header + Exponential Jitter Backoff.
  • Idea B: Per-domain circuit breaker marking offending domains as cooling down (60s)
            allowing other domains to continue unaffected.
  • Idea C: Request micro-jitter (0.2s - 0.6s) & per-domain concurrency throttling.
  • Idea D: Modern User-Agent & Client Hints browser header rotation.
"""

import email.utils
import logging
import random
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idea D: User-Agent & Browser Header Rotation Pool
# ---------------------------------------------------------------------------

BROWSER_HEADER_PROFILES: List[Dict[str, str]] = [
    # Profile 1: Chrome 124 on Windows 10/11
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    },
    # Profile 2: Chrome 125 on Windows
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="125", "Google Chrome";v="125", "Not.A/Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    },
    # Profile 3: Edge 124 on Windows
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de,de-DE;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="124", "Microsoft Edge";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    },
    # Profile 4: Chrome on macOS
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    },
]


def get_rotated_browser_headers(extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Select a randomized, complete modern browser header profile."""
    base = dict(random.choice(BROWSER_HEADER_PROFILES))
    if extra_headers:
        base.update(extra_headers)
    return base


# ---------------------------------------------------------------------------
# Idea B & C: Domain Circuit Breaker & Concurrency Throttling
# ---------------------------------------------------------------------------

def extract_domain(url: str) -> str:
    """Extract registered domain / hostname from a URL or raw domain string."""
    try:
        raw = str(url or "").strip()
        if not raw:
            return "unknown"
        if "://" not in raw:
            raw = f"http://{raw}"
        parsed = urlparse(raw)
        host = (parsed.netloc or "").strip().lower()
        if ":" in host:
            host = host.split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if "." not in host:
            return "unknown"
        return host or "unknown"
    except Exception:
        return "unknown"


class DomainCircuitBreaker:
    """
    Thread-safe circuit breaker preventing scrapers from bombarding rate-limited domains.
    When a domain returns HTTP 429, it enters a cooldown state (default 60s).
    Other domains continue processing normally.
    """

    def __init__(self, default_cooldown_seconds: float = 60.0):
        self.default_cooldown = default_cooldown_seconds
        self._cooldowns: Dict[str, float] = {}
        self._last_request_time: Dict[str, float] = {}
        self._rate_limit_count: int = 0
        self._lock = threading.Lock()

    def get_rate_limit_count(self) -> int:
        with self._lock:
            return self._rate_limit_count

    def increment_rate_limit_count(self) -> int:
        with self._lock:
            self._rate_limit_count += 1
            return self._rate_limit_count

    def mark_rate_limited(self, domain_or_url: str, cooldown_seconds: Optional[float] = None) -> float:
        """Mark a domain as cooling down after an HTTP 429."""
        domain = extract_domain(domain_or_url)
        cooldown = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
        until_ts = time.time() + max(1.0, cooldown)
        with self._lock:
            self._cooldowns[domain] = until_ts
        logger.warning(
            "Circuit breaker tripped: domain '%s' is paused for %.1f seconds due to HTTP 429",
            domain,
            cooldown,
        )
        return until_ts

    def is_cooling_down(self, domain_or_url: str) -> Tuple[bool, float]:
        """
        Check if a domain is currently cooling down.
        Returns: (is_cooling_down, remaining_seconds)
        """
        domain = extract_domain(domain_or_url)
        now = time.time()
        with self._lock:
            until_ts = self._cooldowns.get(domain, 0.0)
            if until_ts > now:
                return True, round(until_ts - now, 1)
            elif domain in self._cooldowns:
                self._cooldowns.pop(domain, None)
        return False, 0.0

    def throttle_domain(self, domain_or_url: str, min_interval_seconds: float = 0.5) -> None:
        """Enforce a minimum spacing between requests to the same domain."""
        domain = extract_domain(domain_or_url)
        now = time.time()
        sleep_needed = 0.0
        with self._lock:
            last = self._last_request_time.get(domain, 0.0)
            elapsed = now - last
            if elapsed < min_interval_seconds:
                sleep_needed = min_interval_seconds - elapsed
            self._last_request_time[domain] = now + sleep_needed

        if sleep_needed > 0:
            time.sleep(sleep_needed)

    def clear(self, domain_or_url: Optional[str] = None) -> None:
        """Reset circuit breaker for a domain or all domains."""
        with self._lock:
            if domain_or_url:
                domain = extract_domain(domain_or_url)
                self._cooldowns.pop(domain, None)
                self._last_request_time.pop(domain, None)
            else:
                self._cooldowns.clear()
                self._last_request_time.clear()


# Global shared circuit breaker instance
GLOBAL_CIRCUIT_BREAKER = DomainCircuitBreaker(default_cooldown_seconds=60.0)


# ---------------------------------------------------------------------------
# Idea A: Retry-After & Exponential Jitter Backoff
# ---------------------------------------------------------------------------

def parse_retry_after(header_val: Optional[str], default_wait: float = 2.0, max_wait: float = 60.0) -> float:
    """
    Parse HTTP Retry-After header.
    Can be integer/float seconds, or an RFC 2822 HTTP date string.
    """
    if not header_val:
        return default_wait

    raw = header_val.strip()
    # 1. Try parsing direct seconds (e.g. '30' or '120')
    try:
        val = float(raw)
        return min(max(0.5, val), max_wait)
    except ValueError:
        pass

    # 2. Try parsing HTTP Date format (e.g. 'Wed, 21 Oct 2026 07:28:00 GMT')
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        now_ts = time.time()
        wait_seconds = dt.timestamp() - now_ts
        return min(max(0.5, wait_seconds), max_wait)
    except Exception:
        pass

    return default_wait


def apply_micro_jitter(min_seconds: float = 0.2, max_seconds: float = 0.6) -> float:
    """Idea C: Micro-jitter to prevent mechanical, robotic request patterns."""
    jitter = random.uniform(min_seconds, max_seconds)
    time.sleep(jitter)
    return jitter


# ---------------------------------------------------------------------------
# Resilient HTTP Fetcher
# ---------------------------------------------------------------------------

def safe_http_get(
    session: requests.Session,
    url: str,
    *,
    retries: int = 2,
    timeout: float = 10.0,
    headers: Optional[Dict[str, str]] = None,
    circuit_breaker: Optional[DomainCircuitBreaker] = None,
    allow_cooldown_skip: bool = True,
    apply_jitter: bool = True,
    min_domain_interval: float = 0.4,
    verify: bool = False,
    **kwargs,
) -> Optional[requests.Response]:
    """
    Execute an HTTP GET request with full 429 protection:
      • Checks domain cooldown (Circuit Breaker)
      • Applies micro-jitter
      • Uses rotated browser headers
      • Honors `Retry-After` header + Exponential Jitter Backoff
      • Automatically marks domain in cooldown on persistent 429
    """
    cb = circuit_breaker or GLOBAL_CIRCUIT_BREAKER
    domain = extract_domain(url)

    # 1. Circuit Breaker Check (Idea B)
    is_paused, remaining = cb.is_cooling_down(domain)
    if is_paused:
        logger.info(
            "Skipping request to '%s' - domain is cooling down for %.1fs after HTTP 429",
            domain,
            remaining,
        )
        if allow_cooldown_skip:
            return None

    # 2. Concurrency Throttle & Micro-Jitter (Idea C)
    cb.throttle_domain(domain, min_interval_seconds=min_domain_interval)
    if apply_jitter:
        apply_micro_jitter(0.15, 0.45)

    # 3. Headers Rotation (Idea D)
    req_headers = get_rotated_browser_headers(headers)

    for attempt in range(retries + 1):
        try:
            resp = session.get(
                url,
                headers=req_headers,
                timeout=timeout,
                verify=verify,
                allow_redirects=True,
                **kwargs,
            )

            # 4. Handle HTTP 429 (Idea A)
            if resp.status_code == 429:
                cb.increment_rate_limit_count()
                retry_after_hdr = resp.headers.get("Retry-After")
                base_backoff = (2 ** attempt) + random.uniform(0.5, 1.5)
                wait_time = parse_retry_after(retry_after_hdr, default_wait=base_backoff)

                logger.warning(
                    "HTTP 429 Rate Limit for %s (attempt %d/%d). Backing off for %.1fs (Retry-After: %s)",
                    domain,
                    attempt + 1,
                    retries + 1,
                    wait_time,
                    retry_after_hdr or "none",
                )

                if attempt < retries:
                    time.sleep(wait_time)
                    # Rotate headers before retry attempt
                    req_headers = get_rotated_browser_headers(headers)
                    continue
                else:
                    # Persistent 429: Trip Circuit Breaker for this domain (Idea B)
                    cooldown = max(60.0, wait_time)
                    cb.mark_rate_limited(domain, cooldown_seconds=cooldown)
                    return resp

            return resp

        except requests.exceptions.Timeout:
            logger.debug("Timeout fetching %s (attempt %d/%d)", url, attempt + 1, retries + 1)
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
        except requests.exceptions.RequestException as exc:
            logger.debug("Request error fetching %s: %s", url, exc)
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue

    return None
