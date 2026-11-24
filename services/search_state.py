"""
Search State, Cache, and Run Management.
Handles search caching, disk persistence, and search runs tracking.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

SEARCH_CACHE_FILE = (Path("data") / "search_cache.json").resolve()
SEARCH_RUNS_FILE = (Path("data") / "search_runs.json").resolve()

SEARCH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_JOBS = 8000

PUBLISHED_SINCE_MAP = {
    "all": None,
    "today": 1,
    "yesterday": 0,
    "24h": 1,
    "1d": 1,
    "1week": 7,
    "7d": 7,
    "7days": 7,
    "2weeks": 14,
    "14d": 14,
    "14days": 14,
    "4weeks": 28,
    "30d": 30,
    "30days": 30,
}

search_cache: Dict[str, Any] = {
    "jobs": [],
    "keyword": "",
    "location": "",
    "source": "all",
    "mode": "ausbildung",
    "radius": "",
    "published_since": "all",
    "search_run_id": "",
    "last_search_audit": {},
    "unconfirmed_maps_companies": [],
    "profession_intelligence": None,
    "geographic_coverage": None,
}

search_runs: Dict[str, Dict] = {}
search_runs_lock = threading.Lock()


def _normalize_published_since(value: str) -> str:
    key = str(value or "all").strip().lower()
    return key if key in PUBLISHED_SINCE_MAP else "all"


def _published_since_to_days(value: str) -> Optional[int]:
    return PUBLISHED_SINCE_MAP.get(_normalize_published_since(value))


def _save_search_cache_to_disk(
    jobs: Iterable[Dict], keyword: str, location: str, published_since: str = "all"
) -> None:
    payload = {
        "keyword": keyword,
        "location": location,
        "published_since": _normalize_published_since(published_since),
        "jobs": list(jobs),
    }
    try:
        with SEARCH_CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not persist search cache: %s", exc)


def _load_search_cache_from_disk() -> Dict:
    if not SEARCH_CACHE_FILE.exists():
        return {"jobs": [], "keyword": "", "location": "", "published_since": "all"}
    try:
        with SEARCH_CACHE_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        jobs = payload.get("jobs", [])
        return {
            "jobs": jobs if isinstance(jobs, list) else [],
            "keyword": str(payload.get("keyword", "")),
            "location": str(payload.get("location", "")),
            "published_since": _normalize_published_since(payload.get("published_since", "all")),
        }
    except Exception as exc:
        logger.warning("Could not read persisted search cache: %s", exc)
        return {"jobs": [], "keyword": "", "location": "", "published_since": "all"}


def _save_search_runs_to_disk() -> None:
    try:
        with SEARCH_RUNS_FILE.open("w", encoding="utf-8") as f:
            json.dump(search_runs, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Could not persist search runs: %s", exc)


def _load_search_runs_from_disk() -> Dict:
    if not SEARCH_RUNS_FILE.exists():
        return {}
    try:
        with SEARCH_RUNS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Could not load search runs: %s", exc)
        return {}
