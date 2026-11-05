"""
Worker Network Routing Engine for JobScout Auto-Extraction Pipeline.

Provides isolated, per-worker network profiles, proxy support (HTTP, HTTPS, SOCKS5),
public IP verification through authorized services, credential sanitization,
and strict fail-closed enforcement (no silent direct leaks unless explicitly configured).
"""

import os
import re
import json
import zipfile
import tempfile
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

# Authorized public IP check endpoints
DEFAULT_IP_CHECK_SERVICES = [
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
]

IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b")

# Webshare API v2 endpoint
WEBSHARE_API_ENDPOINT = "https://proxy.webshare.io/api/v2/proxy/list/"


def redact_api_key(api_key: Optional[str]) -> str:
    """Mask API key for safe logging (e.g. 'a1b2...9z')."""
    if not api_key:
        return "<none>"
    key_str = str(api_key).strip()
    if len(key_str) <= 6:
        return "***"
    return f"{key_str[:4]}...{key_str[-2:]}"


def fetch_webshare_proxies(
    api_key: str,
    max_proxies: int = 4,
    mode: str = "direct",
    timeout: float = 8.0,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch active proxy configurations from Webshare API v2.
    Ensures proxies have distinct public IPs and valid authentication credentials.

    Webshare API v2 documentation:
      - Endpoint: https://proxy.webshare.io/api/v2/proxy/list/
      - Header: Authorization: Token <api_key>
      - Query Params: mode=direct (or backbone), page=1, page_size=25, valid=true
    """
    if not api_key or not str(api_key).strip():
        logger.warning("Webshare API key is empty.")
        return []

    req_session = session or requests.Session()
    headers = {
        "Authorization": f"Token {api_key.strip()}",
        "Accept": "application/json",
        "User-Agent": "JobScout-Worker-Network/1.0",
    }

    proxies_found: List[Dict[str, Any]] = []
    seen_ips = set()

    # Attempt primary mode first, then fallback to backbone or unconstrained mode if needed
    modes_to_try = [mode] if mode else ["direct", "backbone"]
    if "backbone" not in modes_to_try:
        modes_to_try.append("backbone")

    for current_mode in modes_to_try:
        if len(proxies_found) >= max_proxies:
            break

        url = WEBSHARE_API_ENDPOINT
        params = {
            "mode": current_mode,
            "page": 1,
            "page_size": 25,
        }

        try:
            logger.info("Fetching Webshare proxies (mode=%s, key=%s)...", current_mode, redact_api_key(api_key))
            resp = req_session.get(url, headers=headers, params=params, timeout=timeout)

            if resp.status_code == 401:
                logger.error("Webshare API authentication failed (HTTP 401). Please check WEBSHARE_API_KEY.")
                return []
            if resp.status_code == 403:
                logger.error("Webshare API access forbidden (HTTP 403).")
                return []
            if resp.status_code != 200:
                logger.warning("Webshare API returned HTTP %s: %s", resp.status_code, resp.text[:200])
                continue

            data = resp.json()
            results = data.get("results") or []
            if not isinstance(results, list):
                continue

            for item in results:
                if len(proxies_found) >= max_proxies:
                    break

                # Filter valid proxies
                if not item.get("valid", True):
                    continue

                proxy_addr = item.get("proxy_address")
                port = item.get("port")
                user = item.get("username")
                pwd = item.get("password")
                country = item.get("country_code", "XX")
                city = item.get("city_name", "")

                if not proxy_addr or not port or not user or not pwd:
                    continue

                # Ensure distinct public IP addresses
                if proxy_addr in seen_ips:
                    continue

                seen_ips.add(proxy_addr)
                proxy_url = f"http://{user}:{pwd}@{proxy_addr}:{port}"

                proxies_found.append({
                    "proxy_address": proxy_addr,
                    "port": port,
                    "username": user,
                    "password": pwd,
                    "country_code": country,
                    "city_name": city,
                    "proxy_url": proxy_url,
                    "profile_name": f"Webshare-{len(proxies_found) + 1} ({country})",
                    "protocol": "http",
                })

        except requests.exceptions.RequestException as exc:
            logger.warning("Webshare API request error (mode=%s): %s", current_mode, exc)
            continue
        except Exception as exc:
            logger.exception("Unexpected error querying Webshare API: %s", exc)
            continue

    logger.info("Webshare API provided %d distinct proxy endpoints.", len(proxies_found))
    return proxies_found


def redact_proxy_url(url: Optional[str]) -> Optional[str]:
    """
    Sanitize proxy URL by removing user/password credentials.
    e.g. 'http://alice:secret@192.168.1.1:8080' -> 'http://***:***@192.168.1.1:8080'.
    Raw passwords are NEVER returned or logged.
    """
    if not url:
        return None
    url_str = str(url).strip()
    if not url_str:
        return None

    try:
        parts = urlsplit(url_str)
        if not parts.hostname:
            return url_str

        # If username or password present, mask them
        if parts.username or parts.password:
            masked_netloc = f"***:***@{parts.hostname}"
            if parts.port:
                masked_netloc += f":{parts.port}"
            return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))
        return url_str
    except Exception:
        # Fallback regex redaction if parsing fails
        return re.sub(r"://([^:@]+):([^@]+)@", r"://***:***@", url_str)


def parse_proxy_components(url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse proxy URL into scheme, host, port, username, password."""
    if not url:
        return None
    try:
        parts = urlsplit(str(url).strip())
        if not parts.hostname:
            return None
        return {
            "scheme": parts.scheme.lower() or "http",
            "host": parts.hostname,
            "port": parts.port or (1080 if "socks" in (parts.scheme or "") else 8080),
            "username": parts.username,
            "password": parts.password,
        }
    except Exception as exc:
        logger.debug("Failed parsing proxy URL: %s", exc)
        return None


@dataclass
class WorkerNetworkProfile:
    """
    Represents an isolated network configuration profile for an extraction worker.
    """
    worker_id: int
    profile_name: str
    proxy_url: Optional[str] = None
    protocol: str = "direct"  # "http", "https", "socks5", "socks5h", "direct"
    public_ip: str = "Unverified"
    connection_status: str = "pending"  # "connected", "direct", "degraded", "failed", "pending"
    allow_direct_fallback: bool = False
    last_verified_at: Optional[str] = None
    error_message: Optional[str] = None

    def get_sanitized_proxy_url(self) -> Optional[str]:
        """Return proxy URL with credentials masked."""
        return redact_proxy_url(self.proxy_url)

    def get_selenium_proxy_server(self) -> Optional[str]:
        """
        Return standard host:port string for Selenium --proxy-server flag.
        e.g. 'http://192.168.1.1:8080' or 'socks5://192.168.1.1:1080'.
        Never includes username or password.
        """
        parsed = parse_proxy_components(self.proxy_url)
        if not parsed:
            return None
        scheme = parsed["scheme"]
        # Normalize socks5 schemes for Chromium
        if scheme in ("socks5h", "socks5"):
            scheme = "socks5"
        return f"{scheme}://{parsed['host']}:{parsed['port']}"

    def get_credentials(self) -> Optional[Tuple[str, str]]:
        """Return (username, password) tuple if credentials are present, else None."""
        parsed = parse_proxy_components(self.proxy_url)
        if parsed and parsed.get("username") and parsed.get("password"):
            return parsed["username"], parsed["password"]
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Safe dictionary representation for UI / API serialization. No passwords."""
        return {
            "worker_id": self.worker_id,
            "profile_name": self.profile_name,
            "protocol": self.protocol,
            "proxy_display": self.get_sanitized_proxy_url() or "Direct Connection",
            "public_ip": self.public_ip,
            "connection_status": self.connection_status,
            "allow_direct_fallback": self.allow_direct_fallback,
            "last_verified_at": self.last_verified_at,
            "error_message": self.error_message,
        }


def load_worker_network_profiles(
    config: Optional[Dict[str, Any]] = None,
    max_workers: int = 4,
    webshare_session: Optional[requests.Session] = None,
) -> Dict[int, WorkerNetworkProfile]:
    """
    Load network profiles for workers from config dict or environment variables.

    Supported env variables:
      - WEBSHARE_API_KEY: Webshare.io API token to auto-provision distinct proxies
      - WORKER_ALLOW_DIRECT_FALLBACK: "false" (default: fail-closed)
      - WORKER_REQUIRE_PROXIES: "false" (if true, workers without proxy are marked failed)
      - WORKER_{i}_PROXY: Proxy URL (http, https, socks5) - manual override for worker i
      - WORKER_{i}_NAME: Profile label (e.g. 'Residential-DE-1')
      - WORKER_{i}_ALLOW_DIRECT_FALLBACK: Per-worker fallback override
    """
    def _get(key: str, default: Any = "") -> Any:
        if config and key in config:
            return config[key]
        return os.getenv(key, default)

    global_fallback = str(_get("WORKER_ALLOW_DIRECT_FALLBACK", "false")).lower() in ("true", "1", "yes")
    require_proxies = str(_get("WORKER_REQUIRE_PROXIES", "false")).lower() in ("true", "1", "yes")

    # Webshare API key auto-provisioning
    webshare_api_key = str(_get("WEBSHARE_API_KEY", "")).strip()
    webshare_proxies: List[Dict[str, Any]] = []
    webshare_fetch_attempted = False
    webshare_fetch_error = None

    if webshare_api_key:
        webshare_fetch_attempted = True
        try:
            webshare_proxies = fetch_webshare_proxies(
                api_key=webshare_api_key,
                max_proxies=max_workers,
                session=webshare_session,
            )
            if not webshare_proxies:
                webshare_fetch_error = "Webshare API returned no valid distinct proxies"
        except Exception as exc:
            webshare_fetch_error = f"Webshare fetch exception: {exc}"

    profiles: Dict[int, WorkerNetworkProfile] = {}

    for i in range(1, max_workers + 1):
        proxy_raw = str(
            _get(f"WORKER_{i}_PROXY") or _get(f"WORKER_{i}_PROXY_URL") or ""
        ).strip()
        name_raw = str(
            _get(f"WORKER_{i}_NAME") or _get(f"WORKER_{i}_PROFILE") or ""
        ).strip()
        worker_fallback_raw = _get(f"WORKER_{i}_ALLOW_DIRECT_FALLBACK")

        if worker_fallback_raw is not None and str(worker_fallback_raw).strip() != "":
            worker_fallback = str(worker_fallback_raw).lower() in ("true", "1", "yes")
        else:
            worker_fallback = global_fallback

        # If manual proxy is not configured, assign from Webshare pool
        if not proxy_raw and (i - 1) < len(webshare_proxies):
            ws_item = webshare_proxies[i - 1]
            proxy_raw = ws_item["proxy_url"]
            if not name_raw:
                name_raw = ws_item["profile_name"]

        if proxy_raw:
            parsed = parse_proxy_components(proxy_raw)
            proto = parsed["scheme"] if parsed else "http"
            pname = name_raw or f"Proxy-{i}"
            profiles[i] = WorkerNetworkProfile(
                worker_id=i,
                profile_name=pname,
                proxy_url=proxy_raw,
                protocol=proto,
                public_ip="Unverified",
                connection_status="pending",
                allow_direct_fallback=worker_fallback,
            )
        else:
            if require_proxies:
                err = "Proxy required by configuration but none provided."
                if webshare_fetch_attempted and webshare_fetch_error:
                    err = f"Webshare configuration active, but proxy provisioning failed: {webshare_fetch_error}"
                profiles[i] = WorkerNetworkProfile(
                    worker_id=i,
                    profile_name=name_raw or f"Worker-{i}",
                    proxy_url=None,
                    protocol="direct",
                    public_ip="Route Failed (Fail-Closed)",
                    connection_status="failed",
                    allow_direct_fallback=False,
                    error_message=err,
                )
            else:
                profiles[i] = WorkerNetworkProfile(
                    worker_id=i,
                    profile_name=name_raw or "Direct",
                    proxy_url=None,
                    protocol="direct",
                    public_ip="Unverified",
                    connection_status="direct",
                    allow_direct_fallback=True,
                )

    return profiles


def get_network_routing_summary(profiles: Dict[int, WorkerNetworkProfile]) -> Dict[str, Any]:
    """
    Summarize active network routing configuration vs capability.
    Clearly indicates whether workers are on Direct host mode (shared IP expected),
    Webshare API auto-routed, or manual custom proxies.
    """
    configured_proxies = sum(1 for p in profiles.values() if p.proxy_url)
    all_direct = (configured_proxies == 0)
    is_webshare = any("webshare" in (p.profile_name or "").lower() for p in profiles.values())
    valid_ips = set(
        p.public_ip for p in profiles.values()
        if p.public_ip and "Failed" not in p.public_ip and "Unverified" not in p.public_ip and "Checking" not in p.public_ip
    )

    if all_direct:
        mode_str = "direct_shared"
        desc = "All workers using direct host connection (no proxies configured in .env; shared IP expected)"
    elif is_webshare:
        mode_str = "webshare_api"
        desc = f"{configured_proxies} of {len(profiles)} workers routed via Webshare.io API (distinct public IPs)"
    else:
        mode_str = "proxy_routed"
        desc = f"{configured_proxies} of {len(profiles)} workers routed through custom proxies"

    return {
        "capability": "4-Worker Independent Network Routing Supported",
        "configured_proxies": configured_proxies,
        "active_mode": mode_str,
        "description": desc,
        "distinct_ips_verified": len(valid_ips),
    }


def verify_worker_connection(
    profile: WorkerNetworkProfile,
    timeout: float = 4.0,
    check_services: Optional[List[str]] = None,
    session: Optional[requests.Session] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Verify outbound connectivity and determine public IP via authorized IP echo services.
    Enforces fail-closed semantics when proxy connection fails and allow_direct_fallback is False.
    """
    services = check_services or DEFAULT_IP_CHECK_SERVICES
    req_session = session or requests.Session()

    if profile.proxy_url:
        req_session.proxies.update({
            "http": profile.proxy_url,
            "https": profile.proxy_url,
        })
    else:
        req_session.proxies.clear()

    detected_ip = None
    last_error = None

    for endpoint in services:
        try:
            resp = req_session.get(
                endpoint,
                timeout=timeout,
                headers={"User-Agent": "JobScout-Worker-IPCheck/1.0"},
            )
            if resp.status_code == 200:
                text = resp.text.strip()
                # Check JSON
                try:
                    data = resp.json()
                    ip_val = data.get("ip") or data.get("origin")
                    if ip_val:
                        first_ip = str(ip_val).split(",")[0].strip()
                        if IPV4_PATTERN.search(first_ip) or IPV6_PATTERN.search(first_ip):
                            detected_ip = first_ip
                            break
                except Exception:
                    pass

                # Check plain text
                m = IPV4_PATTERN.search(text) or IPV6_PATTERN.search(text)
                if m:
                    detected_ip = m.group(0)
                    break
        except Exception as exc:
            last_error = redact_proxy_url(str(exc))
            continue

    if detected_ip:
        profile.public_ip = detected_ip
        profile.connection_status = "connected" if profile.proxy_url else "direct"
        profile.last_verified_at = datetime.now().isoformat()
        profile.error_message = None
        logger.info(
            "Worker %s network verified via %s. Public IP: %s (Status: %s)",
            profile.worker_id,
            profile.profile_name,
            detected_ip,
            profile.connection_status,
        )
        return True, detected_ip, None

    # Connection through assigned route failed!
    err_str = last_error or "Network check timeout"

    if profile.proxy_url and profile.allow_direct_fallback:
        logger.warning(
            "Worker %s proxy check failed (%s); direct fallback enabled, verifying host IP.",
            profile.worker_id,
            err_str,
        )
        # Attempt direct connection
        direct_session = requests.Session()
        direct_session.proxies.clear()
        direct_ip = None
        for endpoint in services:
            try:
                resp = direct_session.get(endpoint, timeout=timeout)
                if resp.status_code == 200:
                    m = IPV4_PATTERN.search(resp.text) or IPV6_PATTERN.search(resp.text)
                    if m:
                        direct_ip = m.group(0)
                        break
            except Exception:
                continue

        if direct_ip:
            profile.public_ip = direct_ip
            profile.connection_status = "degraded"
            profile.last_verified_at = datetime.now().isoformat()
            profile.error_message = f"Proxy failed ({err_str}); fell back to direct."
            return True, direct_ip, profile.error_message

    # Fail-closed enforcement
    profile.connection_status = "failed"
    profile.public_ip = "Route Failed (Fail-Closed)"
    profile.error_message = f"Proxy route verification failed: {err_str}. Fail-closed enforced."
    logger.error(
        "Worker %s failed network check. Fail-closed enforced; worker disabled. Reason: %s",
        profile.worker_id,
        err_str,
    )
    return False, "", profile.error_message


def verify_all_worker_connections(
    profiles: Dict[int, WorkerNetworkProfile],
    timeout: float = 4.0,
    check_services: Optional[List[str]] = None,
) -> Dict[int, Tuple[bool, str, Optional[str]]]:
    """Verify connectivity for all workers concurrently."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: Dict[int, Tuple[bool, str, Optional[str]]] = {}
    if not profiles:
        return results

    with ThreadPoolExecutor(max_workers=len(profiles)) as pool:
        future_map = {
            pool.submit(verify_worker_connection, prof, timeout, check_services): w_id
            for w_id, prof in profiles.items()
        }
        for fut in as_completed(future_map):
            w_id = future_map[fut]
            try:
                results[w_id] = fut.result()
            except Exception as exc:
                prof = profiles[w_id]
                prof.connection_status = "failed"
                prof.error_message = redact_proxy_url(str(exc))
                results[w_id] = (False, "", prof.error_message)

    return results


def build_chrome_proxy_extension(
    scheme: str, host: str, port: int, username: str, password: str
) -> str:
    """
    Creates a temporary packed Chrome extension (zip) to support authenticated proxies.
    Chromium CLI flags do not support embedded username:password in --proxy-server.
    """
    temp_dir = tempfile.gettempdir()
    plugin_path = os.path.join(temp_dir, f"proxy_auth_{host}_{port}.zip")

    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "JobScout Proxy Auth",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """

    background_js = f"""
    var config = {{
        mode: "fixed_servers",
        rules: {{
          singleProxy: {{
            scheme: "{scheme}",
            host: "{host}",
            port: parseInt({port})
          }},
          bypassList: ["localhost", "127.0.0.1"]
        }}
    }};
    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
    function callbackFn(details) {{
        return {{
            authCredentials: {{
                username: "{username}",
                password: "{password}"
            }}
        }};
    }}
    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {{urls: ["<all_urls>"]}},
        ['blocking']
    );
    """

    with zipfile.ZipFile(plugin_path, "w") as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)

    return plugin_path


def apply_proxy_to_browser_options(options: Any, profile: Optional[WorkerNetworkProfile]) -> None:
    """
    Apply worker network proxy configuration to Selenium Chrome / Edge options.
    Handles unauthenticated proxies via --proxy-server and authenticated proxies via extension.
    """
    if not profile or not profile.proxy_url:
        return

    parsed = parse_proxy_components(profile.proxy_url)
    if not parsed:
        return

    scheme = parsed["scheme"]
    if scheme in ("socks5h", "socks5"):
        scheme = "socks5"
    host = parsed["host"]
    port = parsed["port"]
    user = parsed.get("username")
    pwd = parsed.get("password")

    if user and pwd:
        # Authenticated proxy
        try:
            ext_path = build_chrome_proxy_extension(scheme, host, port, user, pwd)
            if hasattr(options, "add_extension"):
                options.add_extension(ext_path)
            else:
                options.add_argument(f"--proxy-server={scheme}://{host}:{port}")
        except Exception as exc:
            logger.warning("Failed building proxy auth extension, using standard flag: %s", exc)
            options.add_argument(f"--proxy-server={scheme}://{host}:{port}")
    else:
        # Standard unauthenticated proxy
        options.add_argument(f"--proxy-server={scheme}://{host}:{port}")

