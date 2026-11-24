"""
Central Multi-Portal Search Engine.
Executes concurrent job discovery across Arbeitsagentur, Ausbildung.de, Azubiyo,
AUBI-plus, IHK, and verified Google Maps employers with real-time instrumentation.
"""

import copy
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from scraper.enhanced_api_scraper import EnhancedJobScraper
from scraper.ausbildung_de_scraper import AusbildungDeScraper
from scraper.azubiyo_scraper import AzubiyoScraper
from scraper.aubi_plus_scraper import AubiPlusScraper
from scraper.ihk_scraper import IhkScraper
from scraper.overpass_scraper import OverpassBusinessScraper
overpass_scraper = OverpassBusinessScraper()
from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
from scraper.search_filter_engine import (
    filter_and_deduplicate_jobs,
    filter_and_deduplicate_jobs_with_audit,
)
from services.profession_intelligence import profession_intelligence
from services.geographic_batching import geographic_batching
from services.geographic_checkpoint_manager import geographic_checkpoint_manager
from services.search_state import (
    DEFAULT_MAX_JOBS,
    search_cache,
    _normalize_published_since,
    _published_since_to_days,
)

logger = logging.getLogger(__name__)

def _build_portal_query_keyword(raw_keyword: str, norm_keyword: str = "") -> str:
    """Clean free-form queries like 'Ausbildung als Verkäufer/in' to portal-friendly profession terms."""
    candidate = str(norm_keyword or raw_keyword or "").strip()
    candidate = re.sub(
        r"^(?:ausbildung\s+(?:als\s+|zum\s+|zur\s+|für\s+|fuer\s+|im\s+|in\s+)?|lehre\s+(?:als\s+|zum\s+|zur\s+)?|duales\s+studium\s+(?:in\s+|für\s+|fuer\s+)?)\s*",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"(?:/in|/-in|/frau|/mann|\(m/w/d\)|\(w/m/d\)|\(d/m/w\)|\(all genders\)|\*in|:in)\b",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" /-–—")
    return candidate or str(raw_keyword or "").strip()


def _fetch_combined_jobs(
    keyword: str,
    location: str,
    source: str = "all",
    mode: str = "ausbildung",
    radius: Optional[Union[int, str]] = None,
    max_jobs: int = DEFAULT_MAX_JOBS,
    published_since_days: Optional[int] = None,
    progress_callback: Optional[Any] = None,
    return_audit: bool = False,
    search_scope: str = "both",
    auto_categories: bool = True,
    custom_categories: Optional[Union[List[str], str]] = None,
) -> Union[List[Dict], Tuple[List[Dict], Dict[str, Any]]]:
    """Fetches jobs from enabled scrapers with real-time multi-portal instrumentation and audit metrics."""
    from scraper.search_filter_engine import (
        filter_and_deduplicate_jobs,
        filter_and_deduplicate_jobs_with_audit,
    )

    # 0. Intelligent Profession Classification & Geographic Target Resolution
    prof_info = profession_intelligence.classify_profession(keyword)
    search_cache["profession_intelligence"] = prof_info
    norm_keyword = prof_info.get("normalized_profession") or keyword
    portal_keyword = _build_portal_query_keyword(keyword, norm_keyword)

    geo_plan = geographic_batching.resolve_targets(location, max_hubs=3)
    search_cache["geographic_coverage"] = geo_plan

    mode_clean = str(mode or "ausbildung").strip().lower()
    if mode_clean not in {"ausbildung", "arbeit"}:
        mode_clean = "ausbildung"

    radius_val: Optional[int] = None
    if radius:
        try:
            radius_val = int(str(radius).strip())
        except (ValueError, TypeError):
            radius_val = None

    source_clean = str(source or "all").lower().strip()
    is_all = source_clean in {"all", "all_with_maps", "all_sources"}
    has_portals = is_all or source_clean in {"job_portals", "jobboersen", "jobbörsen", "portals"}
    has_gmaps = is_all or source_clean in {"google_maps", "google-maps", "maps"}

    # Scraper Monitoring Dashboard Tracker (thread-safe; portals run concurrently)
    import copy as _copy
    import re as _re
    from concurrent.futures import wait as _futures_wait

    try:
        _portal_soft_timeout = max(10, int(os.environ.get("PORTAL_SOFT_TIMEOUT_SECONDS", "45")))
    except (TypeError, ValueError):
        _portal_soft_timeout = 45
    try:
        _portal_hard_timeout = max(_portal_soft_timeout + 5, int(os.environ.get("PORTAL_TIMEOUT_SECONDS", "150")))
    except (TypeError, ValueError):
        _portal_hard_timeout = 150
    # Google Maps crawls many company websites, so it gets a larger budget.
    _portal_timeouts = {
        "google_maps": (_portal_soft_timeout * 2, int(_portal_hard_timeout * 1.6)),
    }

    _secret_re = _re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|token|secret|password|passwd|key|auth)=)([^&\s'\"]+)"
    )

    def _redact(text: Any) -> str:
        """Strips credentials/tokens from any text that ends up in monitoring logs."""
        return _secret_re.sub(r"\1***", str(text or ""))

    state_lock = threading.RLock()

    class _ScraperMonitoringTracker:
        TERMINAL_STATES = {"completed", "failed", "timeout", "skipped"}

        def __init__(self):
            self.lock = threading.RLock()
            self.start_time = time.time()
            self.log_counter = 0
            portal_defs = [
                ("arbeitsagentur", "Arbeitsagentur", "https://rest.arbeitsagentur.de/opensearch/anti-robot/jobs"),
                ("ausbildung_de", "Ausbildung.de", "https://www.ausbildung.de/suche/"),
                ("azubiyo", "Azubiyo", "https://www.azubiyo.de/ausbildungsplaetze/"),
                ("aubi_plus", "AUBI-plus", "https://www.aubi-plus.de/suchmaschine/"),
                ("ihk", "IHK Lehrstellenbörse", "https://www.lehrstellen-boerse.de/"),
                ("google_maps", "Google Maps", "https://overpass-api.de/api/interpreter"),
            ]
            self.portals = {}
            for key, name, url in portal_defs:
                soft, hard = _portal_timeouts.get(key, (_portal_soft_timeout, _portal_hard_timeout))
                self.portals[key] = {
                    "key": key,
                    "name": name,
                    "url": url,
                    "state": "pending",
                    # `status` mirrors `state` for older frontends that read p.status
                    "status": "pending",
                    "scanned": 0,
                    "accepted": 0,
                    "rejected": 0,
                    "duplicates": 0,
                    "errors": 0,
                    "duration_ms": 0,
                    "elapsed_ms": 0,
                    "slow": False,
                    "soft_timeout_s": soft,
                    "timeout_s": hard,
                    "current_task": "Queued in pipeline",
                    "rejection_reasons": {},
                    "discovered_items": [],
                }
            self.google_maps_metrics = {
                "city": location or "Deutschland (Bundesweit)",
                "category": keyword,
                "companies_found": 0,
                "websites_visited": 0,
                "emails_extracted": 0,
                "verified_vacancies": 0,
                "potential_employers": 0,
                "regions_scanned": 0,
                "regions_total": 16,
                "current_region": "-",
                "municipalities_covered": 0,
                "failed_regions": 0,
                "deferred_regions": 0,
                "resume_status": "idle",
                "is_completed": False,
            }
            self.workers = {
                "active": 0,
                "running": 0,
                "active_names": [],
                "queued": 6,
                "completed": 0,
                "failed": 0,
                "timed_out": 0,
                "total": 6,
                "finished": 0,
                "parallel": True,
            }
            self.all_logs = []
            self.new_logs_buffer = []
            self.recent_items = []
            self._items_cursor = 0
            self._totals_cache = (-1, 0)

        # ---- state helpers -------------------------------------------------
        def _set_state(self, p, state):
            p["state"] = state
            p["status"] = state

        def is_abandoned(self, portal_key):
            with self.lock:
                p = self.portals.get(portal_key)
                return bool(p and p["state"] in ("timeout", "skipped"))

        def set_skipped(self, active_keys):
            with self.lock:
                for k, p in self.portals.items():
                    if k not in active_keys:
                        self._set_state(p, "skipped")
                        p["current_task"] = "Skipped (not selected in search source)"
                self._update_workers()

        def _update_workers(self):
            states = [p["state"] for p in self.portals.values()]
            running = [p["name"] for p in self.portals.values() if p["state"] == "running"]
            self.workers["queued"] = states.count("pending")
            self.workers["completed"] = states.count("completed")
            self.workers["failed"] = states.count("failed") + states.count("timeout")
            self.workers["timed_out"] = states.count("timeout")
            self.workers["running"] = len(running)
            self.workers["active"] = len(running)
            self.workers["active_names"] = running
            self.workers["total"] = sum(1 for s in states if s != "skipped")
            self.workers["finished"] = self.workers["completed"] + self.workers["failed"]

        def compute_percent(self):
            total = self.workers.get("total") or 0
            if total <= 0:
                return 100
            return int(5 + 90 * (self.workers.get("finished", 0) / total))

        def all_finished(self):
            with self.lock:
                return all(p["state"] in self.TERMINAL_STATES for p in self.portals.values())

        # ---- logging -------------------------------------------------------
        def log(self, portal_key, level, message, url=None, task=None, item=None, rejection_reason=None):
            with self.lock:
                self.log_counter += 1
                p_name = self.portals.get(portal_key, {}).get("name", str(portal_key).capitalize())
                clean_item = None
                if item and isinstance(item, dict):
                    clean_item = {
                        "title": item.get("title") or item.get("name") or "Position",
                        "company": item.get("company") or item.get("name") or "Unternehmen",
                        "location": item.get("location") or item.get("city") or "",
                        "url": _redact(item.get("apply_url") or item.get("url") or item.get("website") or ""),
                        "source": item.get("source") or p_name,
                        "status": "rejected" if rejection_reason else "accepted",
                        "rejection_reason": rejection_reason,
                        "application_method": item.get("application_method") or item.get("bewerbung_art") or ("email" if item.get("email") else "portal"),
                        "email": item.get("email") or "",
                    }

                entry = {
                    "id": self.log_counter,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "portal": portal_key,
                    "portal_name": p_name,
                    "level": level,
                    "message": _redact(message),
                    "url": _redact(url) if url else None,
                    "task": _redact(task) if task else None,
                    "rejection_reason": _redact(rejection_reason) if rejection_reason else None,
                    "item": clean_item,
                }
                self.all_logs.append(entry)
                self.new_logs_buffer.append(entry)
                if len(self.all_logs) > 500:
                    self.all_logs = self.all_logs[-500:]
                if len(self.new_logs_buffer) > 300:
                    self.new_logs_buffer = self.new_logs_buffer[-300:]

        # ---- lifecycle -----------------------------------------------------
        def start_portal(self, portal_key, task, url=None, **_legacy):
            with self.lock:
                p = self.portals.get(portal_key)
                if not p:
                    return
                self._set_state(p, "running")
                p["start_time"] = time.time()
                p["current_task"] = task
                if url:
                    p["url"] = url
                self._update_workers()
                self.log(portal_key, "info", task, url=url, task=task)
            self.emit_progress(portal_key, task, status="running")

        def set_task(self, portal_key, task, scanned=None, url=None, level="info"):
            with self.lock:
                p = self.portals.get(portal_key)
                if not p or p["state"] != "running":
                    return
                p["current_task"] = task
                if scanned is not None:
                    p["scanned"] = int(scanned)
                self.log(portal_key, level, task, url=url, task=task)
            self.emit_progress(portal_key, task, status="running")

        def finish_portal(
            self,
            portal_key,
            stage_desc,
            source_valid=0,
            source_raw=0,
            discovered_jobs=None,
            audit_exclusions=None,
            error=None,
            cross_duplicates=0,
            **_legacy,
        ):
            with self.lock:
                p = self.portals.get(portal_key)
                if not p or p["state"] in ("timeout", "skipped"):
                    # Late result from a portal that was already abandoned after its timeout.
                    if p is not None and p["state"] == "timeout":
                        self.log(portal_key, "warning", f"Late response ignored (portal exceeded {p['timeout_s']}s timeout)")
                    return

                if error:
                    self._set_state(p, "failed")
                    p["errors"] += 1
                    p["current_task"] = f"Failed: {_redact(error)}"
                    self.log(portal_key, "error", f"Scraper execution failed: {error}")
                    status = "source_error"
                else:
                    self._set_state(p, "completed")
                    p["scanned"] = source_raw
                    p["accepted"] = source_valid
                    p["rejected"] = max(0, source_raw - source_valid)
                    p["duplicates"] += int(cross_duplicates or 0)
                    p["current_task"] = f"Completed ({source_valid} verified of {source_raw} scanned)"
                    status = "source_done"

                    if audit_exclusions:
                        for ex in audit_exclusions:
                            stg = ex.get("stage") or "other"
                            p["rejection_reasons"][stg] = p["rejection_reasons"].get(stg, 0) + 1
                            if ex.get("stage") == "duplicate":
                                p["duplicates"] += 1
                            self.log(
                                portal_key,
                                "rejected",
                                f"Excluded: '{ex.get('title')}' at '{ex.get('company')}' — {ex.get('reason')}",
                                item=ex,
                                rejection_reason=ex.get("reason"),
                            )

                    if discovered_jobs:
                        for j in discovered_jobs[:25]:
                            clean = {
                                "title": j.get("title") or j.get("name") or "Position",
                                "company": j.get("company") or j.get("name") or "Unternehmen",
                                "location": j.get("location") or j.get("city") or "",
                                "url": _redact(j.get("apply_url") or j.get("url") or j.get("website") or ""),
                                "source": j.get("source") or p["name"],
                                "portal": portal_key,
                                "status": "accepted",
                                "application_method": j.get("application_method") or j.get("bewerbung_art") or ("email" if j.get("email") else "portal"),
                                "email": j.get("email") or "",
                                "has_form": bool(j.get("has_form")),
                            }
                            p["discovered_items"].append(clean)
                            self.recent_items.append(clean)
                            self.log(
                                portal_key,
                                "success",
                                f"Discovered matching position: '{clean['title']}' at '{clean['company']}' ({clean['location']})",
                                item=clean,
                            )

                if "start_time" in p:
                    p["duration_ms"] = int((time.time() - p["start_time"]) * 1000)
                    p["elapsed_ms"] = p["duration_ms"]
                if p["slow"] and not error:
                    p["slow"] = False

                self._update_workers()
                self.log(
                    portal_key,
                    "success" if not error else "error",
                    f"{p['name']} finished in {p['duration_ms'] / 1000:.1f}s — "
                    f"{self.workers['finished']}/{self.workers['total']} portals done",
                )

            self.emit_progress(
                portal_key,
                stage_desc,
                finished_source=portal_key,
                source_count=source_valid,
                source_raw_count=source_raw,
                status=status,
            )

        def check_timeouts(self):
            """Flags slow portals and abandons portals that exceeded their hard timeout."""
            timed_out = []
            now = time.time()
            with self.lock:
                for key, p in self.portals.items():
                    if p["state"] != "running" or "start_time" not in p:
                        continue
                    elapsed = now - p["start_time"]
                    p["elapsed_ms"] = int(elapsed * 1000)
                    if elapsed >= p["timeout_s"]:
                        self._set_state(p, "timeout")
                        p["errors"] += 1
                        p["slow"] = True
                        p["duration_ms"] = p["elapsed_ms"]
                        p["current_task"] = f"Timed out after {int(elapsed)}s — portal unresponsive, skipped"
                        self.log(key, "error", f"{p['name']} did not respond within {p['timeout_s']}s; continuing without it")
                        timed_out.append(key)
                    elif elapsed >= p["soft_timeout_s"] and not p["slow"]:
                        p["slow"] = True
                        self.log(key, "warning", f"{p['name']} is slow: still running after {int(elapsed)}s (timeout at {p['timeout_s']}s)")
                if timed_out:
                    self._update_workers()
            return timed_out

        def _current_totals(self):
            """Global (cross-portal, deduplicated) accepted/raw counts."""
            with state_lock:
                snapshot = list(jobs)
            if not snapshot:
                return 0, 0
            if self._totals_cache[0] == len(snapshot):
                return self._totals_cache[1], len(snapshot)
            try:
                valid_now = filter_and_deduplicate_jobs(
                    snapshot,
                    keyword=keyword,
                    location=location,
                    published_since_days=published_since_days,
                    mode=mode_clean,
                )
                valid_count = len(valid_now)
            except Exception as err:  # pragma: no cover - defensive
                logger.debug("live totals calculation failed: %s", err)
                valid_count = self._totals_cache[1]
            self._totals_cache = (len(snapshot), valid_count)
            return valid_count, len(snapshot)

        def emit_progress(
            self,
            source,
            stage,
            percent=None,
            found=None,
            raw_found=None,
            finished_source=None,
            source_count=None,
            source_raw_count=None,
            status="running",
            audit=None,
        ):
            if not callable(progress_callback):
                return

            if found is None or raw_found is None:
                live_found, live_raw = self._current_totals()
                found = live_found if found is None else found
                raw_found = live_raw if raw_found is None else raw_found

            with self.lock:
                now = time.time()
                for p in self.portals.values():
                    if p["state"] == "running" and "start_time" in p:
                        p["elapsed_ms"] = int((now - p["start_time"]) * 1000)
                if percent is None:
                    percent = self.compute_percent()

                total_scanned = sum(p["scanned"] for p in self.portals.values())
                total_rejected = sum(p["rejected"] for p in self.portals.values())
                total_duplicates = sum(p["duplicates"] for p in self.portals.values())
                total_errors = sum(p["errors"] for p in self.portals.values())
                running_names = list(self.workers.get("active_names") or [])

                new_items = self.recent_items[self._items_cursor:]
                self._items_cursor = len(self.recent_items)

                data = {
                    "source": source,
                    "stage": _redact(stage),
                    "percent": percent,
                    "found": found,
                    "raw_found": raw_found,
                    "finished_source": finished_source,
                    "source_count": source_count,
                    "source_raw_count": source_raw_count,
                    "status": status,
                    "audit": audit,
                    "portals": _copy.deepcopy(self.portals),
                    "live_metrics": {
                        # `scanned` kept for compatibility; `raw_scanned` is what the dashboard reads
                        "scanned": max(total_scanned, raw_found or 0),
                        "raw_scanned": max(total_scanned, raw_found or 0),
                        "accepted": found or 0,
                        "rejected": total_rejected,
                        "duplicates": total_duplicates,
                        "errors": total_errors,
                        "execution_time_seconds": round(now - self.start_time, 2),
                        "active_portal": ", ".join(running_names) if running_names else ("Done" if status == "complete" else "—"),
                    },
                    "google_maps_metrics": dict(self.google_maps_metrics),
                    "workers": _copy.deepcopy(self.workers),
                    "new_logs": list(self.new_logs_buffer),
                    # Only items discovered since the previous event (frontend appends them)
                    "recent_items": list(new_items[-50:]),
                    "elapsed_seconds": round(now - self.start_time, 1),
                }
                self.new_logs_buffer.clear()
            try:
                progress_callback(data)
            except Exception as e:
                logger.debug("progress_callback error: %s", e)

    tracker = _ScraperMonitoringTracker()

    active_keys = []
    if has_portals or source_clean in {"arbeitsagentur", "arbeitsagentur.de"}:
        active_keys.append("arbeitsagentur")
    if has_portals or source_clean in {"ausbildung_de", "ausbildung.de"}:
        active_keys.append("ausbildung_de")
    if has_portals or source_clean in {"azubiyo", "azubiyo.de"}:
        active_keys.append("azubiyo")
    if has_portals or source_clean in {"aubi_plus", "aubi-plus", "aubi_plus.de"}:
        active_keys.append("aubi_plus")
    if has_portals or source_clean in {"ihk", "ihk.de", "ihk_lehrstellenboerse"}:
        active_keys.append("ihk")
    if has_gmaps:
        active_keys.append("google_maps")

    tracker.set_skipped(active_keys)

    jobs: List[Dict] = []
    seen_refs = set()

    def _merge_portal_jobs(portal_key, new_jobs, default_source, ref_fn):
        """Thread-safely merges a portal's raw jobs into the shared list; returns cross-portal duplicates."""
        dup = 0
        with state_lock:
            if tracker.is_abandoned(portal_key):
                return 0
            for j in new_jobs:
                j.setdefault("source", default_source)
                ref = ref_fn(j)
                if ref and ref not in seen_refs:
                    seen_refs.add(ref)
                    jobs.append(j)
                elif ref:
                    dup += 1
        return dup

    def _simple_ref(j):
        return j.get("reference") or j.get("url")

    def _aa_ref(j):
        return j.get("reference") or j.get("url") or j.get("apply_url") or j.get("refnr") or f"{j.get('company')}_{j.get('title')}"

    def _run_standard_portal(portal_key, label, start_task, url, fetch_fn, default_source, ref_fn):
        tracker.start_portal(portal_key, start_task, url=url)
        try:
            portal_jobs = list(fetch_fn() or [])
            tracker.set_task(
                portal_key,
                f"{label}: received {len(portal_jobs)} listings — validating relevance, location & dates...",
                scanned=len(portal_jobs),
            )
            valid_jobs, p_audit = filter_and_deduplicate_jobs_with_audit(
                portal_jobs,
                keyword=keyword,
                location=location,
                published_since_days=published_since_days,
                mode=mode_clean,
            )
            dup = _merge_portal_jobs(portal_key, portal_jobs, default_source, ref_fn)
            tracker.finish_portal(
                portal_key,
                f"{label}: {len(portal_jobs)} scanned ({len(valid_jobs)} matching positions)",
                source_valid=len(valid_jobs),
                source_raw=len(portal_jobs),
                discovered_jobs=valid_jobs,
                audit_exclusions=(p_audit or {}).get("exclusions", []),
                cross_duplicates=dup,
            )
        except Exception as exc:
            logger.warning("%s search failed: %s", label, exc)
            tracker.finish_portal(portal_key, f"{label} failed: {exc}", error=exc)

    portal_runners = []

    # 1. Arbeitsagentur
    if "arbeitsagentur" in active_keys:
        aa_label = "Live Jobs" if mode_clean == "arbeit" else "Vocational / Apprenticeships"
        aa_limit = max_jobs if not is_all and not has_portals else min(max(15, max_jobs // 2), 4000)
        aa_angebotsart = 1 if mode_clean == "arbeit" else 4

        def _aa_progress(info):
            if not isinstance(info, dict):
                return
            pg = int(info.get("page") or 1)
            total_fetched = int(info.get("total_fetched") or 0)
            if pg == 1 or pg % 3 == 0:
                tracker.set_task(
                    "arbeitsagentur",
                    f"Arbeitsagentur ({aa_label}): page {pg} — {total_fetched} listings fetched...",
                    scanned=total_fetched,
                )

        def _fetch_aa():
            scraper = EnhancedJobScraper()
            try:
                return scraper.fetch_all_jobs(
                    portal_keyword,
                    location,
                    max_jobs=aa_limit,
                    published_since_days=published_since_days,
                    angebotsart=aa_angebotsart,
                    umkreis=radius_val,
                    progress_callback=_aa_progress,
                    should_stop=lambda: tracker.is_abandoned("arbeitsagentur"),
                )
            except TypeError:
                return scraper.fetch_all_jobs(
                    portal_keyword,
                    location,
                    max_jobs=aa_limit,
                    published_since_days=published_since_days,
                    angebotsart=aa_angebotsart,
                    umkreis=radius_val,
                )

        portal_runners.append(("arbeitsagentur", lambda: _run_standard_portal(
            "arbeitsagentur", "Arbeitsagentur",
            f"Arbeitsagentur ({aa_label}): Fetching official live vacancies...",
            "https://rest.arbeitsagentur.de/opensearch/anti-robot/jobs",
            _fetch_aa, "Arbeitsagentur", _aa_ref,
        )))

    # 2. Ausbildung.de
    if "ausbildung_de" in active_keys:
        adb_limit = max_jobs if not is_all and not has_portals else min(max(15, max_jobs // 3), 400)
        portal_runners.append(("ausbildung_de", lambda: _run_standard_portal(
            "ausbildung_de", "Ausbildung.de",
            "Ausbildung.de: Crawling apprenticeship listings...",
            "https://www.ausbildung.de/suche/",
            lambda: AusbildungDeScraper().fetch_jobs(
                keyword=portal_keyword, location=location, max_jobs=adb_limit, published_since_days=published_since_days,
            ),
            "ausbildung.de", _simple_ref,
        )))

    # 3. Azubiyo.de
    if "azubiyo" in active_keys:
        az_limit = max_jobs if not is_all and not has_portals else min(max(12, max_jobs // 4), 250)
        portal_runners.append(("azubiyo", lambda: _run_standard_portal(
            "azubiyo", "Azubiyo",
            "Azubiyo: Querying vocational listings...",
            "https://www.azubiyo.de/ausbildungsplaetze/",
            lambda: AzubiyoScraper().fetch_jobs(keyword=portal_keyword, location=location, max_jobs=az_limit),
            "azubiyo.de", _simple_ref,
        )))

    # 4. AUBI-plus
    if "aubi_plus" in active_keys:
        aubi_limit = max_jobs if not is_all and not has_portals else min(max(12, max_jobs // 4), 250)
        portal_runners.append(("aubi_plus", lambda: _run_standard_portal(
            "aubi_plus", "AUBI-plus",
            "AUBI-plus: Checking vocational database...",
            "https://www.aubi-plus.de/suchmaschine/",
            lambda: AubiPlusScraper().fetch_jobs(keyword=portal_keyword, location=location, max_jobs=aubi_limit),
            "aubi-plus.de", _simple_ref,
        )))

    # 5. IHK Lehrstellenbörse
    if "ihk" in active_keys:
        ihk_limit = max_jobs if not is_all and not has_portals else min(max(12, max_jobs // 4), 300)
        portal_runners.append(("ihk", lambda: _run_standard_portal(
            "ihk", "IHK",
            "IHK Lehrstellenbörse: Querying Chamber of Commerce registry...",
            "https://www.lehrstellen-boerse.de/",
            lambda: IhkScraper().fetch_jobs(keyword=portal_keyword, location=location, max_jobs=ihk_limit),
            "ihk.de", _simple_ref,
        )))

    # 6. Google Maps (when selected explicitly or as part of all sources)
    def _run_google_maps():
        gmaps_label = "Local Employers & Websites" if mode_clean == "arbeit" else "Local Training Companies & Career Websites"
        tracker.start_portal(
            "google_maps",
            f"Google Maps ({gmaps_label}): Initiating nationwide discovery across cities & rural areas...",
            url="https://overpass-api.de/api/interpreter",
        )
        try:
            from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
            from scraper.overpass_scraper import OverpassBusinessScraper
            from services.geographic_batching import geographic_batching
            from services.geographic_checkpoint_manager import geographic_checkpoint_manager

            unconfirmed_maps_companies = []
            gm = tracker.google_maps_metrics

            # 1. Determine target employer categories
            parsed_custom_cats = []
            if custom_categories:
                if isinstance(custom_categories, list):
                    parsed_custom_cats = [str(c).strip() for c in custom_categories if str(c).strip()]
                elif isinstance(custom_categories, str):
                    parsed_custom_cats = [c.strip() for c in custom_categories.split(",") if c.strip()]

            if parsed_custom_cats:
                categories_to_query = parsed_custom_cats
            elif auto_categories and prof_info.get("employer_categories"):
                categories_to_query = [
                    cat.get("search_term") or cat.get("category")
                    for cat in prof_info.get("employer_categories", [])
                ]
            else:
                categories_to_query = [keyword]
            categories_to_query = [c for c in categories_to_query if c] or [keyword]

            from services.profession_intelligence import profession_intelligence
            resolution = profession_intelligence.resolve_osm_tags_for_categories(
                categories_to_query, profession_context=prof_info
            )
            resolved_osm_tags = resolution.get("resolved_tags", [])
            unresolved_cats = resolution.get("unresolved_categories", [])

            # 2. Comprehensive Geographic Coverage Plan (All 16 Bundesländer, cities & rural municipalities)
            is_nationwide = geographic_batching.is_nationwide_query(location)
            geo_plan = geographic_batching.get_nationwide_coverage_plan(location=location)
            planned_regions = geo_plan.get("regions", [])

            with tracker.lock:
                gm["city"] = location or "Deutschland (Bundesweit)"
                gm["category"] = categories_to_query[0] if categories_to_query else keyword
                gm["regions_total"] = len(planned_regions)
                gm["regions_scanned"] = 0
                gm["municipalities_covered"] = 0
                gm["resume_status"] = "active"
                gm["is_completed"] = False

            tracker.log(
                "google_maps",
                "info",
                f"Google Maps AI: Starting {'nationwide discovery across ' + str(len(planned_regions)) + ' regions' if is_nationwide else 'localized search in ' + location} for '{norm_keyword}' ({len(resolved_osm_tags)} OSM tags).",
            )
            if unresolved_cats:
                tracker.log(
                    "google_maps",
                    "warning",
                    f"Google Maps AI: Categories without specific OSM tag mapping (omitted from query): {', '.join(unresolved_cats)}",
                )

            # Persistent Checkpoint
            search_checkpoint_id = f"gmaps_search_{int(time.time())}"
            geographic_checkpoint_manager.create_checkpoint(
                search_id=search_checkpoint_id,
                profession=norm_keyword,
                categories=categories_to_query,
                regions=planned_regions,
                resolved_osm_tags=resolved_osm_tags,
                scope=geo_plan.get("scope", "nationwide"),
                location=location,
            )

            overpass_scraper = OverpassBusinessScraper()
            discovered_raw = []
            seen_biz_keys = set()
            max_per_region = 30 if is_nationwide else 60
            max_nationwide_budget = 300 if is_nationwide else 100

            # 3. Phase 1: Geographic Discovery Loop across Regions & Municipalities (Zero 15-business cap!)
            for reg in planned_regions:
                if tracker.is_abandoned("google_maps"):
                    break
                if len(discovered_raw) >= max_nationwide_budget:
                    tracker.log("google_maps", "info", f"Nationwide discovery budget reached ({len(discovered_raw)} companies).")
                    break

                r_id = reg.get("region_id") or "REGION"
                r_name = reg.get("name") or r_id
                bbox = reg.get("bbox")
                target_cities = reg.get("target_cities") or reg.get("major_cities") or []

                with tracker.lock:
                    gm["current_region"] = r_name
                    gm["city"] = r_name
                tracker.set_task(
                    "google_maps",
                    f"Overpass: scanning '{r_name}' ({len(categories_to_query)} categories, cities & rural districts)...",
                    url="https://overpass-api.de/api/interpreter",
                )

                batch = []
                # Strategy A: BBox Query (Covers Großstädte, Mittelstädte, Kleinstädte & Dörfer in one spatial slice)
                if bbox:
                    try:
                        batch = overpass_scraper.search_businesses_bbox(
                            bbox=bbox,
                            osm_tags=resolved_osm_tags,
                            categories=categories_to_query,
                            limit=max_per_region,
                            default_city=r_name,
                            profession_context=norm_keyword,
                        ) or []
                    except Exception as b_err:
                        tracker.log("google_maps", "warning", f"BBox query for '{r_name}' failed: {b_err}")
                        batch = []

                # Strategy B: Municipal sampling across cities, small towns, and rural municipalities if bbox empty
                if not batch and target_cities:
                    for t_city in target_cities[:3]:
                        if tracker.is_abandoned("google_maps"):
                            break
                        try:
                            c_batch = overpass_scraper.search_businesses(
                                city=t_city,
                                category=categories_to_query[0] if categories_to_query else "handwerk",
                                categories=categories_to_query,
                                osm_tags=resolved_osm_tags,
                                limit=max(10, max_per_region // 2),
                                profession_context=norm_keyword,
                            ) or []
                            batch.extend(c_batch)
                        except Exception as c_err:
                            tracker.log("google_maps", "warning", f"Overpass query for '{t_city}' ({r_name}) failed: {c_err}")

                # Deduplicate and register newly discovered businesses
                new_in_reg = []
                for b in batch:
                    b_key = (
                        (b.get("name") or "").lower().strip(),
                        (b.get("website") or b.get("street") or b.get("city") or "").lower().strip(),
                    )
                    if b_key not in seen_biz_keys:
                        seen_biz_keys.add(b_key)
                        b["target_category"] = categories_to_query[0]
                        b["region_id"] = r_id
                        b["region_name"] = r_name
                        discovered_raw.append(b)
                        new_in_reg.append(b)

                with tracker.lock:
                    gm["companies_found"] = len(discovered_raw)
                    gm["regions_scanned"] += 1
                    distinct_mun = {b.get("city") for b in discovered_raw if b.get("city")}
                    gm["municipalities_covered"] = len(distinct_mun)

                # Persist checkpoint to disk
                geographic_checkpoint_manager.update_region_progress(
                    search_id=search_checkpoint_id,
                    region_id=r_id,
                    status="scanned",
                    discovered_batch=new_in_reg,
                )

                tracker.log(
                    "google_maps",
                    "info",
                    f"Overpass discovery in '{r_name}' returned {len(batch)} businesses ({len(discovered_raw)} total across Germany, {len(distinct_mun)} municipalities)",
                    url="https://overpass-api.de/api/interpreter",
                )

            if not discovered_raw and not tracker.is_abandoned("google_maps"):
                city_query = location or "Berlin"
                discovered_raw = overpass_scraper.search_businesses(city=city_query, category=keyword, limit=15) or []
                with tracker.lock:
                    gm["companies_found"] = len(discovered_raw)

            # 4. Phase 2: Separate Verification Queue
            tracker.set_task(
                "google_maps",
                f"Verifying {len(discovered_raw)} discovered businesses & career websites (6 parallel workers)...",
                scanned=len(discovered_raw),
            )

            _verifier_local = threading.local()

            def _get_verifier():
                v = getattr(_verifier_local, "v", None)
                if v is None:
                    v = GoogleMapsAusbildungVerifier()
                    _verifier_local.v = v
                return v

            def _verify(biz):
                if tracker.is_abandoned("google_maps"):
                    return None
                with tracker.lock:
                    gm["websites_visited"] += 1
                tracker.log(
                    "google_maps",
                    "info",
                    f"Inspecting {'company website' if mode_clean == 'arbeit' else 'training opportunities'}: {biz.get('name')} ({biz.get('website') or 'No site'})...",
                    url=biz.get("website"),
                )
                try:
                    if mode_clean == "arbeit":
                        return _get_verifier().verify_business_for_arbeit(biz, profession_keyword=norm_keyword)
                    return _get_verifier().verify_business(biz, profession_keyword=norm_keyword, deep_form_discovery=False)
                except Exception as err:
                    tracker.log("google_maps", "error", f"Website check failed for {biz.get('name')}: {err}", url=biz.get("website"))
                    return None

            verified_count = 0
            search_scope_clean = str(search_scope or "both").lower().strip()
            discovered_maps_jobs = []
            dup = 0

            # Register businesses without websites immediately as POTENTIAL_EMPLOYER (preserving small town initiative targets)
            for biz in discovered_raw:
                if not biz.get("website"):
                    biz["opportunity_type"] = "POTENTIAL_EMPLOYER"
                    biz["is_potential_employer"] = True
                    ref = biz.get("name") or f"gmaps_{abs(hash(biz.get('name', '')))}"
                    with state_lock:
                        if ref not in seen_refs:
                            seen_refs.add(ref)
                            jobs.append(biz)
                            discovered_maps_jobs.append(biz)
                            verified_count += 1
                    with tracker.lock:
                        gm["potential_employers"] += 1

            # Process businesses with websites concurrently in verification queue
            from concurrent.futures import as_completed
            businesses_to_verify = [b for b in discovered_raw if b.get("website")]
            with ThreadPoolExecutor(max_workers=6, thread_name_prefix="gmaps-verify") as v_pool:
                futures = {v_pool.submit(_verify, biz): biz for biz in businesses_to_verify[:60]}
                for fut in as_completed(futures):
                    if tracker.is_abandoned("google_maps"):
                        for f in futures:
                            f.cancel()
                        break
                    try:
                        verified_biz = fut.result()
                    except Exception as err:
                        logger.debug("Verification task failed: %s", err)
                        continue

                    if not verified_biz:
                        continue

                    if verified_biz.get("email"):
                        with tracker.lock:
                            gm["emails_extracted"] += 1
                        tracker.log(
                            "google_maps",
                            "success",
                            f"Extracted email '{verified_biz.get('email')}' for {verified_biz.get('name') or verified_biz.get('company')}",
                            item=verified_biz,
                        )

                    ref = verified_biz.get("apply_url") or verified_biz.get("website") or verified_biz.get("name")

                    if mode_clean == "arbeit":
                        accept = True
                    else:
                        opp_type = verified_biz.get("opportunity_type") or (
                            "VERIFIED_AUSBILDUNG" if verified_biz.get("is_verified_vacancy") else "POTENTIAL_EMPLOYER"
                        )
                        if verified_biz.get("is_verified_vacancy"):
                            with tracker.lock:
                                gm["verified_vacancies"] += 1
                            tracker.log(
                                "google_maps",
                                "success",
                                f"Confirmed verified Ausbildung: '{verified_biz.get('title')}' at '{verified_biz.get('name') or verified_biz.get('company')}'",
                                item=verified_biz,
                            )
                        elif opp_type == "POTENTIAL_EMPLOYER":
                            with tracker.lock:
                                gm["potential_employers"] += 1

                        if search_scope_clean == "verified_only":
                            accept = opp_type == "VERIFIED_AUSBILDUNG" or bool(verified_biz.get("is_verified_vacancy"))
                        elif search_scope_clean == "potential_only":
                            accept = opp_type == "POTENTIAL_EMPLOYER"
                        else:  # "both" (default)
                            accept = opp_type in ("VERIFIED_AUSBILDUNG", "POTENTIAL_EMPLOYER") or bool(verified_biz.get("is_verified_vacancy"))
                        if not accept:
                            unconfirmed_maps_companies.append(verified_biz)
                            continue

                    if not accept:
                        continue
                    # Stream directly into shared jobs collection progressively
                    with state_lock:
                        if ref and ref not in seen_refs:
                            seen_refs.add(ref)
                            jobs.append(verified_biz)
                            discovered_maps_jobs.append(verified_biz)
                            verified_count += 1
                        elif ref:
                            dup += 1

            search_cache["unconfirmed_maps_companies"] = unconfirmed_maps_companies

            with tracker.lock:
                gm["is_completed"] = True
                gm["resume_status"] = "completed"

            success_stage = (
                f"Google Maps: {verified_count} businesses verified across {gm.get('municipalities_covered', 0)} municipalities"
                if mode_clean == "arbeit"
                else f"Google Maps: {verified_count} matching training companies/positions ({gm.get('municipalities_covered', 0)} municipalities)"
            )
            tracker.finish_portal(
                "google_maps",
                success_stage,
                source_valid=verified_count,
                source_raw=len(discovered_raw),
                discovered_jobs=discovered_maps_jobs,
                cross_duplicates=dup,
            )
        except Exception as exc:
            logger.warning("Google Maps search failed: %s", exc)
            tracker.finish_portal("google_maps", f"Google Maps failed: {exc}", error=exc)

    if "google_maps" in active_keys:
        portal_runners.append(("google_maps", _run_google_maps))

    # Execute all selected portals concurrently, with heartbeats and per-portal timeouts.
    if portal_runners:
        tracker.log(
            "all",
            "info",
            f"Launching {len(portal_runners)} portal workers in parallel: "
            + ", ".join(tracker.portals[k]["name"] for k, _ in portal_runners),
        )
        tracker.emit_progress("all", f"Searching {len(portal_runners)} portals in parallel...", status="running")

        executor = ThreadPoolExecutor(max_workers=len(portal_runners), thread_name_prefix="portal")
        future_map = {executor.submit(fn): key for key, fn in portal_runners}
        pending_futures = set(future_map)
        last_heartbeat = time.time()
        try:
            while pending_futures:
                done, pending_futures = _futures_wait(pending_futures, timeout=1.0)
                for fut in done:
                    try:
                        fut.result()
                    except Exception as exc:  # runners catch their own errors; this is a safety net
                        key = future_map[fut]
                        logger.warning("Portal worker %s crashed: %s", key, exc)
                        tracker.finish_portal(key, f"{key} crashed: {exc}", error=exc)

                if tracker.check_timeouts():
                    pending_futures = {f for f in pending_futures if not tracker.is_abandoned(future_map[f])}

                # Safety net: a worker whose portal already reached a terminal state is no longer awaited.
                pending_futures = {
                    f for f in pending_futures
                    if tracker.portals[future_map[f]]["state"] not in _ScraperMonitoringTracker.TERMINAL_STATES
                }

                now = time.time()
                if pending_futures and now - last_heartbeat >= 2.0:
                    last_heartbeat = now
                    with tracker.lock:
                        running = list(tracker.workers.get("active_names") or [])
                    hb_stage = (
                        f"Running in parallel: {', '.join(running)}"
                        if running
                        else "Finalizing portal results..."
                    )
                    tracker.emit_progress("all", hb_stage, status="heartbeat")
        finally:
            # Never block on abandoned (timed-out) workers.
            executor.shutdown(wait=False)

    # Smart relevance ranking on collected jobs (after all portals have finished)
    if "google_maps" in active_keys:
        try:
            from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier

            with state_lock:
                jobs = GoogleMapsAusbildungVerifier().smart_rank_employers(list(jobs), profession=norm_keyword)
        except Exception as rank_err:
            logger.debug("smart ranking skipped: %s", rank_err)

    with state_lock:
        jobs = list(jobs)

    # Apply shared relevance validation, location filtering, publication date filtering and deduplication
    final_jobs, audit = filter_and_deduplicate_jobs_with_audit(
        jobs,
        keyword=keyword,
        location=location,
        published_since_days=published_since_days,
        mode=mode_clean,
    )
    search_cache["last_search_audit"] = audit
    search_cache["mode"] = mode_clean

    # Store full monitoring dashboard summary in audit and search_cache
    dashboard_summary = {
        "portals": tracker.portals,
        "live_metrics": {
            "scanned": sum(p["scanned"] for p in tracker.portals.values()) or len(jobs),
            "accepted": len(final_jobs),
            "rejected": len(audit.get("exclusions", [])),
            "duplicates": audit.get("exclusions_by_stage", {}).get("duplicate", 0),
            "errors": sum(p["errors"] for p in tracker.portals.values()),
            "execution_time_seconds": round(time.time() - tracker.start_time, 2),
        },
        "google_maps_metrics": tracker.google_maps_metrics,
        "workers": tracker.workers,
        "logs": tracker.all_logs,
        "recent_items": tracker.recent_items,
    }
    audit["dashboard"] = dashboard_summary
    search_cache["last_scraper_dashboard"] = dashboard_summary

    tracker.emit_progress(
        source="all",
        stage=f"Search complete: {len(final_jobs)} matching positions verified (from {len(jobs)} total offers scanned)",
        percent=100,
        found=len(final_jobs),
        raw_found=len(jobs),
        audit=audit,
        status="complete",
    )

    if return_audit:
        return final_jobs, audit
    return final_jobs
