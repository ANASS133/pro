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
