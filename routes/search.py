"""
Job Search & Multi-Portal Discovery API Routes.
Provides endpoints for synchronous and streaming job search across Arbeitsagentur,
Ausbildung.de, Azubiyo, AUBI-plus, IHK, and Google Maps.
"""

import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from flask import (
    Blueprint,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
    session,
    stream_with_context,
)

from scraper.aubi_plus_scraper import AubiPlusScraper
from scraper.ausbildung_de_scraper import AusbildungDeScraper
from scraper.azubiyo_scraper import AzubiyoScraper
from scraper.ihk_scraper import IhkScraper
from services.geographic_batching import geographic_batching
from services.profession_intelligence import profession_intelligence
from services.search_engine import _fetch_combined_jobs
from services.search_state import (
    DEFAULT_MAX_JOBS,
    search_cache,
    search_runs,
    search_runs_lock,
    _load_search_cache_from_disk,
    _normalize_published_since,
    _published_since_to_days,
    _save_search_cache_to_disk,
    _save_search_runs_to_disk,
)
from routes.cover_letters import _prepare_download_jobs

logger = logging.getLogger(__name__)

search_bp = Blueprint("search", __name__)

AUTO_EXTRACTION_EXPORT_DIR = (Path("data") / "auto_extraction_exports").resolve()
AUTO_EXTRACTION_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_export_slug(keyword: str, fallback: str = "suchergebnisse") -> str:
    raw = str(keyword or "").strip().lower()
    clean = re.sub(r"[^a-z0-9äöüß]+", "_", raw).strip("_")
    return clean or fallback


def _build_download_filename(keyword: str, fallback: str = "suchergebnisse") -> str:
    raw = str(keyword or "").strip()
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return f"{cleaned or fallback}.xlsx"


def _save_auto_extraction_export_records(
    records: List[Dict],
    keyword: str,
    fallback_slug: str = "suche",
    suffix: str = "",
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    slug = _sanitize_export_slug(keyword, fallback=fallback_slug)
    normalized_suffix = str(suffix or "").strip()
    file_stem = f"{timestamp}_{slug}"
    if normalized_suffix:
        file_stem = f"{file_stem}_{normalized_suffix}"

    file_path = AUTO_EXTRACTION_EXPORT_DIR / f"{file_stem}.xlsx"
    df = pd.DataFrame(records or []).fillna("")
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Stellenangebote", index=False)
    return file_path


# ---------------------------------------------------------------------------
# Search Routes
# ---------------------------------------------------------------------------

@search_bp.route("/search", methods=["POST"])
def search():
    keyword = request.form.get("keyword", "").strip()
    location = request.form.get("location", "").strip()
    source = request.form.get("source", "all").strip().lower()
    mode = request.form.get("mode", "ausbildung").strip().lower()
    radius = request.form.get("radius", "").strip()
    published_since = _normalize_published_since(request.form.get("published_since", "all"))
    search_scope = request.form.get("search_scope", "both").strip().lower()
    auto_categories = request.form.get("auto_categories", "true").lower() in ("true", "1", "yes", "on")
    custom_categories = request.form.get("custom_categories", "")

    try:
        fetch_res = _fetch_combined_jobs(
            keyword,
            location,
            source=source,
            mode=mode,
            radius=radius,
            max_jobs=DEFAULT_MAX_JOBS,
            published_since_days=_published_since_to_days(published_since),
            return_audit=True,
            search_scope=search_scope,
            auto_categories=auto_categories,
            custom_categories=custom_categories,
        )
        if isinstance(fetch_res, tuple) and len(fetch_res) == 2:
            jobs, audit = fetch_res
        else:
            jobs = fetch_res
            audit = search_cache.get("last_search_audit") or {}

        search_cache["jobs"] = jobs
        search_cache["keyword"] = keyword
        search_cache["location"] = location
        search_cache["source"] = source
        search_cache["mode"] = mode
        search_cache["radius"] = radius
        search_cache["published_since"] = published_since
        search_cache["last_search_audit"] = audit
        _save_search_cache_to_disk(jobs, keyword, location, published_since)

        session["last_search_meta"] = {
            "keyword": keyword,
            "location": location,
            "source": source,
            "mode": mode,
            "radius": radius,
            "published_since": published_since,
            "total": len(jobs),
        }

        return render_template(
            "results.html",
            jobs=jobs,
            keyword=keyword,
            location=location,
            source=source,
            mode=mode,
            radius=radius,
            published_since=published_since,
            total=len(jobs),
            audit=audit,
        )
    except Exception as exc:
        return render_template("error.html", error=str(exc))


@search_bp.route("/api/search")
def api_search():
    search_run_id = request.args.get("search_run_id", "").strip() or f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    source = request.args.get("source", "all").strip().lower()
    mode = request.args.get("mode", "ausbildung").strip().lower()
    radius = request.args.get("radius", "").strip()
    published_since = _normalize_published_since(request.args.get("published_since", "all"))
    max_jobs = int(request.args.get("max_jobs", DEFAULT_MAX_JOBS))
    search_scope = request.args.get("search_scope", "both").strip().lower()
    auto_categories = request.args.get("auto_categories", "true").lower() in ("true", "1", "yes", "on")
    custom_categories = request.args.get("custom_categories", "")

    fetch_res = _fetch_combined_jobs(
        keyword,
        location,
        source=source,
        mode=mode,
        radius=radius,
        max_jobs=max_jobs,
        published_since_days=_published_since_to_days(published_since),
        return_audit=True,
        search_scope=search_scope,
        auto_categories=auto_categories,
        custom_categories=custom_categories,
    )
    if isinstance(fetch_res, tuple) and len(fetch_res) == 2:
        jobs, audit = fetch_res
    else:
        jobs = fetch_res
        audit = search_cache.get("last_search_audit") or {}

    with search_runs_lock:
        search_runs[search_run_id] = {
            "search_run_id": search_run_id,
            "keyword": keyword,
            "location": location,
            "source": source,
            "mode": mode,
            "radius": radius,
            "published_since": published_since,
            "jobs": [dict(j) for j in jobs],
            "total": len(jobs),
            "audit": audit,
            "created_at": datetime.now().isoformat(),
            "auto_job_id": None,
        }
        _save_search_runs_to_disk()

    search_cache["search_run_id"] = search_run_id
    search_cache["jobs"] = jobs
    search_cache["keyword"] = keyword
    search_cache["location"] = location
    search_cache["source"] = source
    search_cache["mode"] = mode
    search_cache["radius"] = radius
    search_cache["published_since"] = published_since
    search_cache["last_search_audit"] = audit
    _save_search_cache_to_disk(jobs, keyword, location, published_since)

    return jsonify({
        "status": "success",
        "search_run_id": search_run_id,
        "total": len(jobs),
        "source": source,
        "mode": mode,
        "radius": radius,
        "published_since": published_since,
        "search_scope": search_scope,
        "jobs": jobs,
        "audit": audit,
        "profession_intelligence": search_cache.get("profession_intelligence"),
        "geographic_coverage": search_cache.get("geographic_coverage"),
    })


@search_bp.route("/api/search/audit", methods=["GET"])
def api_search_audit():
    audit = search_cache.get("last_search_audit") or {}
    return jsonify({
        "success": True,
        "audit": audit,
    })


@search_bp.route("/api/profession/classify", methods=["GET", "POST"])
def api_classify_profession():
    """Classifies a user-provided profession title, returning normalized job title, sector, and employer categories."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        keyword = data.get("keyword") or request.form.get("keyword") or ""
        location = data.get("location") or request.form.get("location") or ""
    else:
        keyword = request.args.get("keyword", "")
        location = request.args.get("location", "")

    keyword = str(keyword or "").strip()
    if not keyword:
        return jsonify({"status": "error", "message": "Stichwort/Beruf ist erforderlich."}), 400

    try:
        classification = profession_intelligence.classify_profession(keyword)
        geo_coverage = geographic_batching.resolve_targets(location, max_hubs=3) if location is not None else None
        search_queries = profession_intelligence.get_search_queries(keyword, location=location or "")
        return jsonify({
            "status": "success",
            "classification": classification,
            "geographic_coverage": geo_coverage,
            "search_queries": search_queries,
            "input": classification.get("input", keyword),
            "normalized_profession": classification.get("normalized_profession", keyword),
            "sector": classification.get("sector", "Allgemein"),
            "employer_categories": classification.get("employer_categories", []),
        })
    except Exception as exc:
        logger.warning("api_classify_profession error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@search_bp.route("/api/search/stream", methods=["GET"])
def api_search_stream():
    search_run_id = request.args.get("search_run_id", "").strip() or f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    source = request.args.get("source", "all").strip().lower()
    mode = request.args.get("mode", "ausbildung").strip().lower()
    radius = request.args.get("radius", "").strip()
    published_since = _normalize_published_since(request.args.get("published_since", "all"))
    max_jobs = int(request.args.get("max_jobs", DEFAULT_MAX_JOBS))
    search_scope = request.args.get("search_scope", "both").strip().lower()
    auto_categories = request.args.get("auto_categories", "true").lower() in ("true", "1", "yes", "on")
    custom_categories = request.args.get("custom_categories", "")
    days = _published_since_to_days(published_since)

    if not keyword:
        return jsonify({"status": "error", "message": "Bitte ein Stichwort eingeben"}), 400

    @stream_with_context
    def generate_events():
        q = queue.Queue()

        def progress_cb(data):
            if isinstance(data, dict):
                data["search_run_id"] = search_run_id
            q.put(("progress", data))

        def worker():
            try:
                fetch_res = _fetch_combined_jobs(
                    keyword=keyword,
                    location=location,
                    source=source,
                    mode=mode,
                    radius=radius,
                    max_jobs=max_jobs,
                    published_since_days=days,
                    progress_callback=progress_cb,
                    return_audit=True,
                    search_scope=search_scope,
                    auto_categories=auto_categories,
                    custom_categories=custom_categories,
                )
                if isinstance(fetch_res, tuple) and len(fetch_res) == 2:
                    jobs, audit = fetch_res
                else:
                    jobs = fetch_res
                    audit = {}
                q.put(("done", {"jobs": jobs, "audit": audit}))
            except Exception as e:
                q.put(("error", str(e)))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        yield f"event: start\ndata: {json.dumps({'message': 'Suche gestartet', 'keyword': keyword, 'source': source, 'search_run_id': search_run_id})}\n\n"

        while True:
            try:
                evt_type, payload = q.get(timeout=30.0)
                if evt_type == "progress":
                    yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
                elif evt_type == "done":
                    jobs = payload.get("jobs", [])
                    audit = payload.get("audit", {})
                    search_cache["jobs"] = jobs
                    search_cache["keyword"] = keyword
                    search_cache["location"] = location
                    search_cache["source"] = source
                    search_cache["mode"] = mode
                    search_cache["radius"] = radius
                    search_cache["published_since"] = published_since
                    search_cache["last_search_audit"] = audit
                    _save_search_cache_to_disk(jobs, keyword, location, published_since)

                    with search_runs_lock:
                        search_runs[search_run_id] = {
                            "search_run_id": search_run_id,
                            "keyword": keyword,
                            "location": location,
                            "source": source,
                            "mode": mode,
                            "radius": radius,
                            "published_since": published_since,
                            "jobs": jobs,
                            "total": len(jobs),
                            "audit": audit,
                            "created_at": datetime.now().isoformat(),
                        }
                        _save_search_runs_to_disk()

                    if mode == "ausbildung" and jobs:
                        try:
                            _save_auto_extraction_export_records(
                                jobs,
                                keyword,
                                fallback_slug="ausbildung_suche",
                            )
                        except Exception as save_err:
                            logger.warning("Could not automatically save stream search results to Ausbildung dataset: %s", save_err)

                    complete_payload = {
                        "status": "success",
                        "search_run_id": search_run_id,
                        "total": len(jobs),
                        "source": source,
                        "mode": mode,
                        "radius": radius,
                        "published_since": published_since,
                        "search_scope": search_scope,
                        "jobs": jobs,
                        "audit": audit,
                        "profession_intelligence": search_cache.get("profession_intelligence"),
                        "geographic_coverage": search_cache.get("geographic_coverage"),
                    }
                    yield f"event: complete\ndata: {json.dumps(complete_payload)}\n\n"
                    break
                elif evt_type == "error":
                    yield f"event: error\ndata: {json.dumps({'error': payload})}\n\n"
                    break
            except queue.Empty:
                yield ": ping\n\n"

    response = Response(generate_events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@search_bp.route("/api/ausbildung-de/search", methods=["GET"])
def api_ausbildung_de_search():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    max_jobs = int(request.args.get("max_jobs", 50))
    scraper = AusbildungDeScraper()
    jobs = scraper.fetch_jobs(keyword=keyword, location=location, max_jobs=max_jobs)
    return jsonify({
        "success": True,
        "status": "success",
        "source": "ausbildung.de",
        "total": len(jobs),
        "jobs": jobs,
    })


@search_bp.route("/api/azubiyo/search", methods=["GET"])
def api_azubiyo_search():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    max_jobs = int(request.args.get("max_jobs", 50))
    scraper = AzubiyoScraper()
    jobs = scraper.fetch_jobs(keyword=keyword, location=location, max_jobs=max_jobs)
    return jsonify({
        "success": True,
        "status": "success",
        "source": "azubiyo.de",
        "total": len(jobs),
        "jobs": jobs,
    })


@search_bp.route("/api/aubi-plus/search", methods=["GET"])
def api_aubi_plus_search():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    max_jobs = int(request.args.get("max_jobs", 40))
    scraper = AubiPlusScraper()
    jobs = scraper.fetch_jobs(keyword=keyword, location=location, max_jobs=max_jobs)
    return jsonify({
        "success": True,
        "status": "success",
        "source": "aubi-plus.de",
        "total": len(jobs),
        "jobs": jobs,
    })


@search_bp.route("/api/ihk/search", methods=["GET"])
def api_ihk_search():
    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()
    max_jobs = int(request.args.get("max_jobs", 40))
    scraper = IhkScraper()
    jobs = scraper.fetch_jobs(keyword=keyword, location=location, max_jobs=max_jobs)
    return jsonify({
        "success": True,
        "status": "success",
        "source": "ihk.de",
        "total": len(jobs),
        "jobs": jobs,
    })


@search_bp.route("/api/search/runs/<search_run_id>", methods=["GET"])
def api_get_search_run(search_run_id: str):
    with search_runs_lock:
        s_run = search_runs.get(search_run_id)
        if not s_run:
            return jsonify({"success": False, "message": "Suchlauf nicht gefunden"}), 404
        return jsonify({
            "success": True,
            "search_run": {
                "search_run_id": s_run.get("search_run_id"),
                "keyword": s_run.get("keyword"),
                "location": s_run.get("location"),
                "total": s_run.get("total"),
                "jobs": s_run.get("jobs", []),
                "auto_job_id": s_run.get("auto_job_id"),
                "created_at": s_run.get("created_at"),
            }
        })


@search_bp.route("/api/search/download", methods=["GET"])
def api_search_download():
    """Direct Excel export of the matching search results."""
    search_run_id = request.args.get("search_run_id", "").strip()
    jobs = []
    keyword = ""
    if search_run_id:
        with search_runs_lock:
            s_run = search_runs.get(search_run_id)
            if s_run:
                jobs = list(s_run.get("jobs") or [])
                keyword = str(s_run.get("keyword") or "")
    if not jobs:
        jobs = list(search_cache.get("jobs", []))
        if not jobs:
            persisted = _load_search_cache_from_disk()
            jobs = persisted.get("jobs", [])
        if jobs and not keyword:
            keyword = str(search_cache.get("keyword") or "").strip()
    if not jobs:
        return jsonify({"error": "Keine Suchergebnisse zum Download vorhanden."}), 400

    prepared_jobs = _prepare_download_jobs(jobs)
    if not prepared_jobs:
        return jsonify({"error": "Keine passenden Stellenangebote zum Download verfügbar."}), 400

    temp_file = _save_auto_extraction_export_records(
        prepared_jobs,
        keyword,
        fallback_slug="suchergebnisse",
    )
    return send_file(
        temp_file,
        as_attachment=True,
        download_name=_build_download_filename(keyword, fallback="suchergebnisse"),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
