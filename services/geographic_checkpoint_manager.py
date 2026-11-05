"""
JobScout — Geographic Discovery Checkpoint & Resume Manager
===========================================================
Persistently stores discovery state on disk:
- Search ID & timestamp
- Profession & selected AI employer categories
- Region & Tile tracking (scanned, pending, failed, deferred)
- Discovered businesses & deduplication keys
- Verified employers & confirmed vacancies
- Allows seamless resume of interrupted nationwide discovery runs
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = Path("data/checkpoints")


class GeographicCheckpointManager:
    """Manages persistent checkpoints for nationwide geographic discovery."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or CHECKPOINT_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._memory_cache: Dict[str, Dict[str, Any]] = {}

    def _file_path(self, search_id: str) -> Path:
        safe_id = "".join(c for c in search_id if c.isalnum() or c in ("-", "_"))
        return self.storage_dir / f"checkpoint_{safe_id}.json"

    def create_checkpoint(
        self,
        search_id: str,
        profession: str,
        categories: List[str],
        regions: List[Dict[str, Any]],
        resolved_osm_tags: Optional[List[str]] = None,
        scope: str = "nationwide",
        location: str = "",
    ) -> Dict[str, Any]:
        """Initializes and persists a new geographic discovery checkpoint."""
        now_str = datetime.now().isoformat()
        region_ids = [r.get("region_id") or r.get("tile_id") for r in regions]

        checkpoint_data: Dict[str, Any] = {
            "search_id": search_id,
            "created_at": now_str,
            "updated_at": now_str,
            "profession": profession,
            "categories": list(categories),
            "resolved_osm_tags": list(resolved_osm_tags or []),
            "scope": scope,
            "location": location,
            "total_regions": len(region_ids),
            "scanned_regions": [],
            "pending_regions": list(region_ids),
            "failed_regions": [],
            "deferred_regions": [],
            "current_region": region_ids[0] if region_ids else None,
            "status": "active",  # "active", "paused", "completed", "stopped"
            "discovered_businesses": [],
            "verified_employers": [],
            "municipalities_covered": [],
            "stats": {
                "discovered_count": 0,
                "verified_count": 0,
                "potential_employers": 0,
                "confirmed_vacancies": 0,
                "municipalities_count": 0,
            },
        }

        with self.lock:
            self._memory_cache[search_id] = checkpoint_data
            self._save_to_disk(search_id, checkpoint_data)

        logger.info(
            "Created geographic discovery checkpoint '%s' for profession '%s' (%d regions)",
            search_id,
            profession,
            len(region_ids),
        )
        return checkpoint_data

    def update_region_progress(
        self,
        search_id: str,
        region_id: str,
        status: str,  # "scanned", "failed", "deferred"
        discovered_batch: Optional[List[Dict[str, Any]]] = None,
        error_msg: Optional[str] = None,
        next_region_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Updates region status, ingests newly discovered businesses, and updates checkpoint."""
        with self.lock:
            cp = self._get_or_load(search_id)
            if not cp:
                return None

            now_str = datetime.now().isoformat()
            cp["updated_at"] = now_str

            # Update region lists
            if region_id in cp["pending_regions"]:
                cp["pending_regions"].remove(region_id)

            if status == "scanned":
                if region_id not in cp["scanned_regions"]:
                    cp["scanned_regions"].append(region_id)
            elif status == "failed":
                if region_id not in cp["failed_regions"]:
                    cp["failed_regions"].append(region_id)
            elif status == "deferred":
                if region_id not in cp["deferred_regions"]:
                    cp["deferred_regions"].append(region_id)

            # Ingest and deduplicate discovered businesses
            if discovered_batch:
                seen_keys: Set[str] = {
                    (b.get("name", "").lower().strip(), (b.get("website") or b.get("city") or "").lower().strip())
                    for b in cp["discovered_businesses"]
                }
                new_added = 0
                for b in discovered_batch:
                    key = (b.get("name", "").lower().strip(), (b.get("website") or b.get("city") or "").lower().strip())
                    if key not in seen_keys:
                        seen_keys.add(key)
                        b_copy = dict(b)
                        b_copy["source_region"] = region_id
                        b_copy["discovered_at"] = now_str
                        cp["discovered_businesses"].append(b_copy)
                        new_added += 1

                        city = b.get("city")
                        if city and city not in cp["municipalities_covered"]:
                            cp["municipalities_covered"].append(city)

            # Set current region
            cp["current_region"] = next_region_id or (cp["pending_regions"][0] if cp["pending_regions"] else None)

            # Update stats
            cp["stats"]["discovered_count"] = len(cp["discovered_businesses"])
            cp["stats"]["municipalities_count"] = len(cp["municipalities_covered"])

            # Check if all regions are finished
            if not cp["pending_regions"] and not cp["deferred_regions"]:
                cp["status"] = "completed"
            elif cp["status"] == "active" and not cp["pending_regions"] and cp["deferred_regions"]:
                cp["status"] = "partially_completed"

            self._save_to_disk(search_id, cp)
            return cp

    def record_verified_employer(
        self,
        search_id: str,
        verified_biz: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Records a verified employer into checkpoint stats."""
        with self.lock:
            cp = self._get_or_load(search_id)
            if not cp:
                return None

            now_str = datetime.now().isoformat()
            cp["updated_at"] = now_str

            # Deduplicate in verified_employers
            seen_refs = {v.get("reference") or v.get("name") for v in cp["verified_employers"]}
            ref = verified_biz.get("reference") or verified_biz.get("name")
            if ref and ref not in seen_refs:
                cp["verified_employers"].append(dict(verified_biz))
                cp["stats"]["verified_count"] = len(cp["verified_employers"])

                opp_type = verified_biz.get("opportunity_type")
                if verified_biz.get("is_verified_vacancy") or opp_type == "VERIFIED_AUSBILDUNG":
                    cp["stats"]["confirmed_vacancies"] += 1
                elif opp_type == "POTENTIAL_EMPLOYER":
                    cp["stats"]["potential_employers"] += 1

                self._save_to_disk(search_id, cp)
            return cp

    def pause_checkpoint(self, search_id: str) -> bool:
        """Pauses active discovery."""
        with self.lock:
            cp = self._get_or_load(search_id)
            if cp:
                cp["status"] = "paused"
                cp["updated_at"] = datetime.now().isoformat()
                self._save_to_disk(search_id, cp)
                return True
            return False

    def resume_checkpoint(self, search_id: str) -> Optional[Dict[str, Any]]:
        """
        Restores a checkpoint to resume remaining pending and deferred regions.
        Requeues deferred regions into pending.
        """
        with self.lock:
            cp = self._get_or_load(search_id)
            if not cp:
                return None

            # Re-enqueue deferred regions
            for def_r in list(cp.get("deferred_regions", [])):
                if def_r not in cp["pending_regions"]:
                    cp["pending_regions"].append(def_r)
            cp["deferred_regions"] = []

            cp["status"] = "active"
            cp["current_region"] = cp["pending_regions"][0] if cp["pending_regions"] else None
            cp["updated_at"] = datetime.now().isoformat()
            self._save_to_disk(search_id, cp)
            logger.info("Resumed checkpoint '%s': %d pending regions remaining", search_id, len(cp["pending_regions"]))
            return cp

    def get_checkpoint(self, search_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self._get_or_load(search_id)

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """Returns summary of all available checkpoints on disk."""
        checkpoints: List[Dict[str, Any]] = []
        with self.lock:
            for p in self.storage_dir.glob("checkpoint_*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        checkpoints.append({
                            "search_id": data.get("search_id"),
                            "profession": data.get("profession"),
                            "created_at": data.get("created_at"),
                            "status": data.get("status"),
                            "total_regions": data.get("total_regions"),
                            "scanned_regions": len(data.get("scanned_regions") or []),
                            "pending_regions": len(data.get("pending_regions") or []),
                            "discovered_count": data.get("stats", {}).get("discovered_count", 0),
                            "verified_count": data.get("stats", {}).get("verified_count", 0),
                        })
                except Exception as exc:
                    logger.debug("Failed reading checkpoint %s: %s", p, exc)
        return checkpoints

    def _get_or_load(self, search_id: str) -> Optional[Dict[str, Any]]:
        if search_id in self._memory_cache:
            return self._memory_cache[search_id]
        p = self._file_path(search_id)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._memory_cache[search_id] = data
                    return data
            except Exception as exc:
                logger.error("Error loading checkpoint %s: %s", p, exc)
        return None

    def _save_to_disk(self, search_id: str, data: Dict[str, Any]) -> None:
        p = self._file_path(search_id)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Error writing checkpoint %s: %s", p, exc)


# Global singleton instance
geographic_checkpoint_manager = GeographicCheckpointManager()

