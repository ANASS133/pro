"""
JobScout — Nationwide Google Maps / OSM Discovery & Verification Engine
========================================================================
Comprehensive discovery engine covering all of Germany:
- Großstädte, Mittelstädte, Kleinstädte, and rural Landkreise/Gemeinden
- Separates Discovery Queue from Verification Queue
- Independent non-blocking background execution
- Persistent checkpointing & resume capabilities
- Controlled request pacing & rate-limit resilience
- Live multi-dimensional progress metrics
"""

import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from services.geographic_batching import geographic_batching
from services.geographic_checkpoint_manager import geographic_checkpoint_manager
from services.profession_intelligence import profession_intelligence
from scraper.overpass_scraper import OverpassBusinessScraper

logger = logging.getLogger(__name__)


class NationwideDiscoveryEngine:
    """
    Orchestrates nationwide discovery and verification across German regions,
    cities, small towns, and rural municipalities.
    """

    def __init__(
        self,
        checkpoint_manager=None,
        overpass_scraper=None,
    ):
        self.checkpoints = checkpoint_manager or geographic_checkpoint_manager
        self.scraper = overpass_scraper or OverpassBusinessScraper()
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def create_and_start_job(
        self,
        search_id: str,
        keyword: str,
        location: str = "",
        categories: Optional[List[str]] = None,
        custom_categories: Optional[List[str]] = None,
        max_regions: int = 16,
        max_businesses_per_region: int = 25,
        max_total_businesses: int = 300,
        verify_websites: bool = True,
        on_business_discovered: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_business_verified: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_metrics_update: Optional[Callable[[Dict[str, Any]], None]] = None,
        resume_existing: bool = False,
    ) -> Dict[str, Any]:
        """
        Launches nationwide discovery in an independent background daemon thread.
        Does not block standard job portals.
        """
        with self.lock:
            # Check if job is already running
            existing = self.active_jobs.get(search_id)
            if existing and existing.get("is_running"):
                logger.info("Nationwide discovery job '%s' already running", search_id)
                return existing

        # 1. Resolve AI Employer Categories & high-fidelity OSM tags
        prof_info = profession_intelligence.classify_profession(keyword)
        clean_keyword = prof_info.get("normalized_profession") or keyword

        cats_to_use: List[str] = []
        if custom_categories:
            cats_to_use = [str(c).strip() for c in custom_categories if str(c).strip()]
        elif categories:
            cats_to_use = [str(c).strip() for c in categories if str(c).strip()]
        elif prof_info.get("employer_categories"):
            cats_to_use = [
                cat.get("search_term") or cat.get("category")
                for cat in prof_info.get("employer_categories", [])
            ]
        if not cats_to_use:
            cats_to_use = [clean_keyword]

        resolution = profession_intelligence.resolve_osm_tags_for_categories(
            cats_to_use, profession_context=prof_info
        )
        resolved_osm_tags = resolution.get("resolved_tags", [])
        unresolved_cats = resolution.get("unresolved_categories", [])

        # 2. Generate Geographic Coverage Plan
        plan = geographic_batching.get_nationwide_coverage_plan(
            location=location, max_regions=max_regions
        )
        regions = plan.get("regions", [])

        # 3. Create or Resume Checkpoint
        checkpoint = None
        if resume_existing:
            checkpoint = self.checkpoints.resume_checkpoint(search_id)

        if not checkpoint:
            checkpoint = self.checkpoints.create_checkpoint(
                search_id=search_id,
                profession=clean_keyword,
                categories=cats_to_use,
                regions=regions,
                resolved_osm_tags=resolved_osm_tags,
                scope=plan.get("scope", "nationwide"),
                location=location,
            )

        job_state: Dict[str, Any] = {
            "search_id": search_id,
            "keyword": clean_keyword,
            "location": location,
            "categories": cats_to_use,
            "resolved_osm_tags": resolved_osm_tags,
            "unresolved_categories": unresolved_cats,
            "plan": plan,
            "max_businesses_per_region": max_businesses_per_region,
            "max_total_businesses": max_total_businesses,
            "verify_websites": verify_websites,
            "is_running": True,
            "is_completed": False,
            "stop_requested": False,
            "pause_requested": False,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "current_region": checkpoint.get("current_region") or (regions[0]["region_id"] if regions else "-"),
            "discovered_businesses": list(checkpoint.get("discovered_businesses") or []),
            "verified_employers": list(checkpoint.get("verified_employers") or []),
            "municipalities_covered": set(checkpoint.get("municipalities_covered") or []),
            "metrics": {
                "regions_total": len(regions),
                "regions_scanned": len(checkpoint.get("scanned_regions") or []),
                "failed_regions": len(checkpoint.get("failed_regions") or []),
                "deferred_regions": len(checkpoint.get("deferred_regions") or []),
                "current_region": checkpoint.get("current_region") or "-",
                "municipalities_count": len(checkpoint.get("municipalities_covered") or []),
                "businesses_discovered": len(checkpoint.get("discovered_businesses") or []),
                "websites_verified": len(checkpoint.get("verified_employers") or []),
                "potential_employers": checkpoint.get("stats", {}).get("potential_employers", 0),
                "verified_vacancies": checkpoint.get("stats", {}).get("confirmed_vacancies", 0),
                "resume_status": "resumed" if resume_existing else "active",
                "is_running": True,
                "is_completed": False,
            },
        }

        with self.lock:
            self.active_jobs[search_id] = job_state

        # Launch background runner thread
        thread = threading.Thread(
            target=self._run_discovery_loop,
            args=(search_id, on_business_discovered, on_business_verified, on_metrics_update),
            daemon=True,
            name=f"gmaps-nationwide-{search_id[:8]}",
        )
        thread.start()

        logger.info(
            "Launched background nationwide discovery job '%s' across %d regions",
            search_id,
            len(regions),
        )
        return job_state

    def stop_job(self, search_id: str) -> bool:
        """Requests graceful stop of an active discovery job."""
        with self.lock:
            job = self.active_jobs.get(search_id)
            if job:
                job["stop_requested"] = True
                job["is_running"] = False
                job["metrics"]["is_running"] = False
                job["metrics"]["resume_status"] = "stopped"
                self.checkpoints.pause_checkpoint(search_id)
                logger.info("Stop requested for discovery job '%s'", search_id)
                return True
        return False

    def pause_job(self, search_id: str) -> bool:
        """Pauses discovery job and preserves checkpoint."""
        with self.lock:
            job = self.active_jobs.get(search_id)
            if job:
                job["pause_requested"] = True
                job["is_running"] = False
                job["metrics"]["is_running"] = False
                job["metrics"]["resume_status"] = "paused"
                self.checkpoints.pause_checkpoint(search_id)
                logger.info("Paused discovery job '%s'", search_id)
                return True
        return False

    def get_job_status(self, search_id: str) -> Optional[Dict[str, Any]]:
        """Returns live status and telemetry for a discovery job."""
        with self.lock:
            job = self.active_jobs.get(search_id)
            if job:
                return dict(job)
        # Fallback to checkpoint on disk if server restarted
        cp = self.checkpoints.get_checkpoint(search_id)
        if cp:
            return {
                "search_id": search_id,
                "keyword": cp.get("profession"),
                "is_running": cp.get("status") == "active",
                "is_completed": cp.get("status") == "completed",
                "metrics": {
                    "regions_total": cp.get("total_regions", 0),
                    "regions_scanned": len(cp.get("scanned_regions") or []),
                    "failed_regions": len(cp.get("failed_regions") or []),
                    "deferred_regions": len(cp.get("deferred_regions") or []),
                    "current_region": cp.get("current_region") or "-",
                    "municipalities_count": len(cp.get("municipalities_covered") or []),
                    "businesses_discovered": len(cp.get("discovered_businesses") or []),
                    "websites_verified": len(cp.get("verified_employers") or []),
                    "potential_employers": cp.get("stats", {}).get("potential_employers", 0),
                    "verified_vacancies": cp.get("stats", {}).get("confirmed_vacancies", 0),
                    "resume_status": cp.get("status", "idle"),
                    "is_running": False,
                    "is_completed": cp.get("status") == "completed",
                },
                "discovered_businesses": cp.get("discovered_businesses") or [],
                "verified_employers": cp.get("verified_employers") or [],
            }
        return None

    def _run_discovery_loop(
        self,
        search_id: str,
        on_discovered: Optional[Callable[[Dict[str, Any]], None]],
        on_verified: Optional[Callable[[Dict[str, Any]], None]],
        on_metrics: Optional[Callable[[Dict[str, Any]], None]],
    ) -> None:
        """
        Background worker executing Phase 1 (Geographic Discovery Queue)
        and launching asynchronous Phase 2 (Verification Queue).
        """
        with self.lock:
            job = self.active_jobs.get(search_id)
            if not job:
                return

        regions = job["plan"].get("regions", [])
        resolved_osm_tags = job["resolved_osm_tags"]
        cats_to_use = job["categories"]
        clean_keyword = job["keyword"]
        max_per_region = job["max_businesses_per_region"]
        max_total = job["max_total_businesses"]
        verify_websites = job["verify_websites"]

        # Track completed regions to skip if resumed
        cp = self.checkpoints.get_checkpoint(search_id)
        scanned_ids: Set[str] = set(cp.get("scanned_regions", []) if cp else [])
        pending_regions = [r for r in regions if (r.get("region_id") or r.get("tile_id")) not in scanned_ids]

        seen_keys: Set[Tuple[str, str]] = {
            (b.get("name", "").lower().strip(), (b.get("website") or b.get("city") or "").lower().strip())
            for b in job["discovered_businesses"]
        }

        # Thread pool for concurrent website verification (Phase 2 Queue)
        verifier_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="geo-verify")

        def _verify_worker(biz_data: Dict[str, Any]):
            if job.get("stop_requested"):
                return
            try:
                from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
                verifier = GoogleMapsAusbildungVerifier()
                verified = verifier.verify_business(
                    biz_data, profession_keyword=clean_keyword, deep_form_discovery=False
                )
                if verified:
                    with self.lock:
                        job["verified_employers"].append(verified)
                        v_count = len(job["verified_employers"])
                        job["metrics"]["websites_verified"] = v_count

                        opp_type = verified.get("opportunity_type")
                        if verified.get("is_verified_vacancy"):
                            job["metrics"]["verified_vacancies"] += 1
                        elif opp_type == "POTENTIAL_EMPLOYER":
                            job["metrics"]["potential_employers"] += 1

                    self.checkpoints.record_verified_employer(search_id, verified)
                    if on_verified:
                        try:
                            on_verified(verified)
                        except Exception as cb_err:
                            logger.debug("on_verified callback error: %s", cb_err)
                    if on_metrics:
                        try:
                            on_metrics(dict(job["metrics"]))
                        except Exception as m_err:
                            logger.debug("on_metrics callback error: %s", m_err)
            except Exception as v_exc:
                logger.debug("Verification error for %s: %s", biz_data.get("name"), v_exc)

        # ─────────────────────────────────────────────────────────────────────
        # Phase 1: Geographic Discovery Loop across Regions & Municipalities
        # ─────────────────────────────────────────────────────────────────────
        try:
            for idx, reg in enumerate(pending_regions):
                if job.get("stop_requested") or job.get("pause_requested"):
                    logger.info("Stopping nationwide discovery loop for '%s'", search_id)
                    break

                if len(job["discovered_businesses"]) >= max_total:
                    logger.info(
                        "Max nationwide business budget reached (%d >= %d). Finalizing discovery.",
                        len(job["discovered_businesses"]),
                        max_total,
                    )
                    break

                r_id = reg.get("region_id") or reg.get("tile_id")
                r_name = reg.get("name") or r_id
                bbox = reg.get("bbox")
                target_cities = reg.get("target_cities") or reg.get("major_cities") or []

                with self.lock:
                    job["current_region"] = r_name
                    job["metrics"]["current_region"] = r_name
                if on_metrics:
                    try:
                        on_metrics(dict(job["metrics"]))
                    except Exception:
                        pass

                logger.info("Discovery scanning region %d/%d: '%s' (%s)", idx + 1, len(pending_regions), r_name, r_id)

                discovered_in_region: List[Dict[str, Any]] = []
                region_status = "scanned"
                region_error = None

                # Strategy A: BBox Query (Covers Großstädte, Mittelstädte, Kleinstädte & Dörfer in one spatial slice)
                if bbox:
                    try:
                        batch = self.scraper.search_businesses_bbox(
                            bbox=bbox,
                            osm_tags=resolved_osm_tags,
                            categories=cats_to_use,
                            limit=max_per_region,
                            default_city=r_name,
                        ) or []
                        for b in batch:
                            k = (b.get("name", "").lower().strip(), (b.get("website") or b.get("city") or "").lower().strip())
                            if k not in seen_keys:
                                seen_keys.add(k)
                                b["region_id"] = r_id
                                b["region_name"] = r_name
                                discovered_in_region.append(b)
                    except Exception as b_err:
                        logger.warning("BBox query error for region %s: %s", r_id, b_err)
                        region_error = str(b_err)

                # Strategy B: Municipal sampling across cities, small towns, and rural districts if bbox empty
                if not discovered_in_region and target_cities:
                    for target_city in target_cities[:3]:
                        if job.get("stop_requested") or job.get("pause_requested"):
                            break
                        try:
                            c_batch = self.scraper.search_businesses(
                                city=target_city,
                                category=cats_to_use[0] if cats_to_use else "handwerk",
                                categories=cats_to_use,
                                osm_tags=resolved_osm_tags,
                                limit=max(10, max_per_region // 2),
                                profession_context=clean_keyword,
                            ) or []
                            for b in c_batch:
                                k = (b.get("name", "").lower().strip(), (b.get("website") or b.get("city") or "").lower().strip())
                                if k not in seen_keys:
                                    seen_keys.add(k)
                                    b["region_id"] = r_id
                                    b["region_name"] = r_name
                                    discovered_in_region.append(b)
                        except Exception as c_err:
                            logger.debug("City query error for %s in %s: %s", target_city, r_name, c_err)

                # Update job state with newly discovered businesses
                with self.lock:
                    for b in discovered_in_region:
                        job["discovered_businesses"].append(b)
                        city = b.get("city")
                        if city:
                            job["municipalities_covered"].add(city)

                        # Enqueue for Phase 2 Verification if website present
                        if verify_websites and b.get("website"):
                            verifier_pool.submit(_verify_worker, b)
                        elif not b.get("website"):
                            # If no website, mark as discovered business / potential employer
                            b["opportunity_type"] = "POTENTIAL_EMPLOYER"
                            b["is_verified_vacancy"] = False
                            job["verified_employers"].append(b)
                            job["metrics"]["potential_employers"] += 1
                            if on_verified:
                                try:
                                    on_verified(b)
                                except Exception:
                                    pass

                    # Update metrics
                    job["metrics"]["regions_scanned"] += 1
                    job["metrics"]["businesses_discovered"] = len(job["discovered_businesses"])
                    job["metrics"]["municipalities_count"] = len(job["municipalities_covered"])

                # Persist progress to disk checkpoint
                self.checkpoints.update_region_progress(
                    search_id=search_id,
                    region_id=r_id,
                    status=region_status,
                    discovered_batch=discovered_in_region,
                    error_msg=region_error,
                )

                # Emit incremental discovery callback
                if on_discovered:
                    for b in discovered_in_region:
                        try:
                            on_discovered(b)
                        except Exception as cb_err:
                            logger.debug("on_discovered callback error: %s", cb_err)

                if on_metrics:
                    try:
                        on_metrics(dict(job["metrics"]))
                    except Exception as m_err:
                        logger.debug("on_metrics callback error: %s", m_err)

                # Controlled request pacing to honor public API rate limits (0.3s - 0.7s jitter)
                time.sleep(random.uniform(0.3, 0.7))

        finally:
            verifier_pool.shutdown(wait=False)

            with self.lock:
                job["is_running"] = False
                job["metrics"]["is_running"] = False
                if not job.get("stop_requested") and not job.get("pause_requested"):
                    job["is_completed"] = True
                    job["metrics"]["is_completed"] = True
                    job["metrics"]["resume_status"] = "completed"
                    job["metrics"]["current_region"] = "Abgeschlossen (100% Regionen)"
                elif job.get("pause_requested"):
                    job["metrics"]["resume_status"] = "paused"
                elif job.get("stop_requested"):
                    job["metrics"]["resume_status"] = "stopped"

            if on_metrics:
                try:
                    on_metrics(dict(job["metrics"]))
                except Exception:
                    pass

            logger.info(
                "Nationwide discovery loop finished for '%s'. Total businesses discovered: %d, municipalities: %d",
                search_id,
                len(job["discovered_businesses"]),
                len(job["municipalities_covered"]),
            )


# Global singleton instance
nationwide_discovery_engine = NationwideDiscoveryEngine()

