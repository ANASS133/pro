import json
import time
from flask import Blueprint, Response, jsonify, request, stream_with_context
from services.job_store import job_store

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.route("/api/jobs", methods=["GET"])
def list_jobs():
    """List recent background jobs."""
    job_type = request.args.get("type")
    limit = int(request.args.get("limit", 50))
    jobs = job_store.list_jobs(job_type=job_type, limit=limit)
    return jsonify({"success": True, "jobs": jobs}), 200


@jobs_bp.route("/api/jobs/<job_id>", methods=["GET"])
def get_job(job_id: str):
    """Get single job status."""
    job = job_store.get_job(job_id)
    if not job:
        return jsonify({"success": False, "message": "Job not found"}), 404
    return jsonify({"success": True, "job": job}), 200


@jobs_bp.route("/api/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id: str):
    """Delete a job record."""
    deleted = job_store.delete_job(job_id)
    if not deleted:
        return jsonify({"success": False, "message": "Job not found"}), 404
    return jsonify({"success": True, "message": "Job deleted"}), 200


@jobs_bp.route("/api/jobs/<job_id>/stream", methods=["GET"])
def stream_job_status(job_id: str):
    """Server-Sent Events (SSE) live status stream for background jobs."""
    @stream_with_context
    def generate_events():
        last_payload = None
        heartbeats = 0
        max_heartbeats = 600  # 10 minutes maximum stream life

        while heartbeats < max_heartbeats:
            job = job_store.get_job(job_id)
            if not job:
                yield f"event: error\ndata: {json.dumps({'message': 'Job not found'})}\n\n"
                break

            current_payload = json.dumps(job)
            # Only push updates when job state changed or every 5s heartbeat
            if current_payload != last_payload or heartbeats % 5 == 0:
                yield f"data: {current_payload}\n\n"
                last_payload = current_payload

            # Terminal states exit the event stream
            if not job.get("is_running") and job.get("phase") in {"completed", "failed", "stopped", "interrupted"}:
                yield f"event: close\ndata: {json.dumps({'job_id': job_id, 'phase': job.get('phase')})}\n\n"
                break

            time.sleep(1.0)
            heartbeats += 1

    response = Response(generate_events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response

# ---------------------------------------------------------------------------
# High-Performance Parallel Scraping & Proxy Management Routes
# ---------------------------------------------------------------------------

import queue
import threading
from dataclasses import asdict
from scraper.parallel_domain_engine import (
    ParallelDomainEngine,
    ProxyMode,
    VPNNetworkDetector,
    create_engine,
    get_engine,
)

_batch_stream_queues: dict[str, queue.Queue] = {}
_batch_lock = threading.Lock()


@jobs_bp.route("/api/scraper/batch/start", methods=["POST"])
def start_batch_scraper():
    """Starts a high-performance parallel domain scraping job."""
    body = request.get_json(silent=True) or {}
    domains = body.get("domains") or []
    if not domains:
        return jsonify({"success": False, "message": "No domains provided"}), 400

    max_concurrency = int(body.get("max_concurrency", 25))
    timeout_sec = float(body.get("timeout_seconds", 12.0))
    proxy_mode_str = str(body.get("proxy_mode", "DIRECT")).upper()
    proxy_mode = ProxyMode(proxy_mode_str) if proxy_mode_str in ProxyMode.__members__ else ProxyMode.DIRECT
    proxy_list = body.get("proxy_list") or []

    engine = create_engine(
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_sec,
        proxy_mode=proxy_mode,
        proxy_list=proxy_list,
    )
    enqueued = engine.enqueue_domains(domains)

    q = queue.Queue()
    with _batch_lock:
        _batch_stream_queues[engine.job_id] = q

    def _worker():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def _on_progress(metrics, last_domain):
            payload = {
                "metrics": asdict(metrics),
                "last_domain": asdict(last_domain) if last_domain else None,
            }
            q.put(("progress", payload))

        try:
            results = loop.run_until_complete(engine.run(progress_callback=_on_progress))
            q.put(("complete", {
                "metrics": asdict(engine.metrics),
                "total_completed": len(results),
            }))
        except Exception as exc:
            q.put(("error", {"message": str(exc)}))
        finally:
            loop.close()

    thread = threading.Thread(target=_worker, daemon=True, name=f"batch_{engine.job_id}")
    thread.start()

    return jsonify({
        "success": True,
        "job_id": engine.job_id,
        "total_queued": enqueued,
        "max_concurrency": engine.concurrency_controller.current_concurrency,
        "proxy_mode": proxy_mode.value,
    }), 200


@jobs_bp.route("/api/scraper/batch/<job_id>/stream", methods=["GET"])
def stream_batch_scraper(job_id: str):
    """Server-Sent Events (SSE) live telemetry stream for a batch scraping job."""
    with _batch_lock:
        q = _batch_stream_queues.get(job_id)

    engine = get_engine(job_id)
    if not engine and not q:
        return jsonify({"success": False, "message": "Batch job not found"}), 404

    @stream_with_context
    def generate_events():
        yield f"event: connected\ndata: {json.dumps({'job_id': job_id, 'status': 'connected'})}\n\n"
        heartbeats = 0
        max_heartbeats = 1800  # 30 mins max stream

        while heartbeats < max_heartbeats:
            event_type = None
            payload = None
            if q:
                try:
                    event_type, payload = q.get(timeout=1.0)
                except queue.Empty:
                    heartbeats += 1
            else:
                time.sleep(1.0)
                heartbeats += 1

            if event_type:
                yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                if event_type in ("complete", "error"):
                    yield f"event: close\ndata: {json.dumps({'job_id': job_id})}\n\n"
                    break
            else:
                # Periodic heartbeat with current engine metrics
                eng = get_engine(job_id)
                if eng:
                    yield f"event: heartbeat\ndata: {json.dumps(asdict(eng.metrics))}\n\n"
                    if not eng.is_running and eng.metrics.completed + eng.metrics.failed >= eng.metrics.total_queued:
                        yield f"event: close\ndata: {json.dumps({'job_id': job_id, 'status': 'finished'})}\n\n"
                        break

    resp = Response(generate_events(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@jobs_bp.route("/api/scraper/batch/<job_id>/cancel", methods=["POST"])
def cancel_batch_scraper(job_id: str):
    """Cancels a running parallel scraping batch."""
    engine = get_engine(job_id)
    if not engine:
        return jsonify({"success": False, "message": "Batch job not found"}), 404

    engine.cancel()
    return jsonify({"success": True, "message": f"Job {job_id} cancelled"}), 200


@jobs_bp.route("/api/scraper/batch/<job_id>/status", methods=["GET"])
def get_batch_scraper_status(job_id: str):
    """Retrieves full telemetry, results, and failure classifications for a batch."""
    engine = get_engine(job_id)
    if engine:
        return jsonify({
            "success": True,
            "job_id": engine.job_id,
            "metrics": asdict(engine.metrics),
            "domains": [asdict(d) for d in engine.domain_map.values()],
        }), 200

    # Fallback to persistent checkpoint file
    from scraper.parallel_domain_engine import CHECKPOINT_DIR
    chk_path = CHECKPOINT_DIR / f"{job_id}.json"
    if chk_path.exists():
        try:
            with open(chk_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify({"success": True, "from_checkpoint": True, **data}), 200
        except Exception as e:
            return jsonify({"success": False, "message": f"Corrupt checkpoint: {e}"}), 500

    return jsonify({"success": False, "message": "Batch job not found"}), 404


@jobs_bp.route("/api/scraper/batch/<job_id>/resume", methods=["POST"])
def resume_batch_scraper(job_id: str):
    """Resumes an interrupted scraping batch from its persistent checkpoint."""
    engine = create_engine(job_id=job_id)
    loaded = engine.load_checkpoint(job_id)
    if not loaded:
        return jsonify({"success": False, "message": "No valid checkpoint found to resume"}), 404

    q = queue.Queue()
    with _batch_lock:
        _batch_stream_queues[engine.job_id] = q

    def _worker():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def _on_progress(metrics, last_domain):
            q.put(("progress", {
                "metrics": asdict(metrics),
                "last_domain": asdict(last_domain) if last_domain else None,
            }))

        try:
            results = loop.run_until_complete(engine.run(progress_callback=_on_progress))
            q.put(("complete", {
                "metrics": asdict(engine.metrics),
                "total_completed": len(results),
            }))
        except Exception as exc:
            q.put(("error", {"message": str(exc)}))
        finally:
            loop.close()

    thread = threading.Thread(target=_worker, daemon=True, name=f"batch_resume_{engine.job_id}")
    thread.start()

    return jsonify({
        "success": True,
        "job_id": engine.job_id,
        "resumed_queued": len(engine.queue),
        "already_completed": engine.metrics.completed,
    }), 200


@jobs_bp.route("/api/scraper/proxy/status", methods=["GET"])
def get_proxy_status():
    """Returns proxy pool health and active mode."""
    # Read from default proxy manager
    from scraper.parallel_domain_engine import ProxyPoolManager
    default_mgr = ProxyPoolManager()
    return jsonify({"success": True, "proxy_status": default_mgr.get_status()}), 200


@jobs_bp.route("/api/scraper/network/status", methods=["GET"])
def get_network_status():
    """Inspects OS network routing and reports VPN connectivity."""
    status = VPNNetworkDetector.inspect_connection()
    return jsonify({"success": True, "network": status}), 200

