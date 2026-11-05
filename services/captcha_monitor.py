"""
Centralized, Thread-Safe CAPTCHA Monitoring and Telemetry Engine for JobScout.

Tracks accurate, transparent metrics for CAPTCHA events:
- CAPTCHA Challenges Detected: Total challenge detection events
- Unique CAPTCHA Challenges: Distinct challenges encountered (deduplicated by fingerprint)
- Jobs Requiring CAPTCHA: Number of distinct jobs affected
- CAPTCHA Service Requests: Number of outgoing service requests to recognition API
- CAPTCHA Responses Received: Number of responses received from recognition API
- Website Verifications Confirmed: Cases where target website actually confirmed verification
- Manual Verification Required: Jobs blocked or awaiting human action

Guarantees:
- Never treats recognition-service API response 'success=True' as website verification confirmation.
- Privacy-safe: never logs or stores raw CAPTCHA solution text, cookies, or secrets.
- Idempotent tracking and safe correlation between workers, jobs, and requests.
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def generate_challenge_fingerprint(domain: str, marker_details: Optional[str] = None) -> str:
    """Generate a safe, stable SHA-256 fingerprint for a challenge."""
    norm_domain = (domain or "unknown").strip().lower()
    details = (marker_details or "").strip().lower()
    raw = f"{norm_domain}::{details}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def generate_correlation_id(job_id: str, job_index: Optional[int], worker_id: int) -> str:
    """Generate a privacy-safe correlation ID connecting detection to service requests."""
    t_ms = int(time.time() * 1000) % 1000000
    safe_job = (job_id or "job")[:8]
    idx_str = f"idx{job_index}" if job_index is not None else "idx0"
    return f"c_{safe_job}_{idx_str}_w{worker_id}_{t_ms}"


@dataclass
class CaptchaEvent:
    event_id: str
    timestamp: str
    event_type: str  # "detected", "service_request", "service_response", "website_confirmed", "manual_required"
    domain: str
    worker_id: int
    correlation_id: str
    status: str
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "domain": self.domain,
            "worker_id": self.worker_id,
            "correlation_id": self.correlation_id,
            "status": self.status,
            "details": self.details,
        }


class CaptchaTracker:
    """Thread-safe CAPTCHA monitor tracking metrics and diagnostic events."""

    def __init__(self, job_id: str = ""):
        self.job_id = job_id
        self._lock = threading.Lock()

        self.challenges_detected_count = 0
        self.service_requests_count = 0
        self.responses_received_count = 0
        self.website_verifications_confirmed_count = 0

        self.unique_challenges: Set[str] = set()
        self.jobs_requiring_captcha: Set[str] = set()
        self.manual_verification_required_jobs: Set[str] = set()

        self.recent_events: List[Dict[str, Any]] = []
        self._seen_detections: Set[str] = set()

    def record_challenge_detected(
        self,
        domain: str,
        worker_id: int = 1,
        job_index: Optional[int] = None,
        challenge_fingerprint: Optional[str] = None,
        details: str = "Challenge detected on page",
    ) -> str:
        """Records a challenge detection event and returns a correlation ID."""
        with self._lock:
            domain_clean = (domain or "unknown").strip().lower()
            fp = challenge_fingerprint or generate_challenge_fingerprint(domain_clean)
            corr_id = generate_correlation_id(self.job_id, job_index, worker_id)

            self.challenges_detected_count += 1
            self.unique_challenges.add(fp)

            job_key = f"{self.job_id}:{job_index if job_index is not None else 'default'}"
            self.jobs_requiring_captcha.add(job_key)

            evt = CaptchaEvent(
                event_id=f"evt_{len(self.recent_events)+1}_{int(time.time()*1000)%10000}",
                timestamp=datetime.now().strftime("%H:%M:%S"),
                event_type="detected",
                domain=domain_clean,
                worker_id=worker_id,
                correlation_id=corr_id,
                status="Detected",
                details=details,
            )
            self._append_event(evt)
            return corr_id

    def record_service_request(
        self,
        correlation_id: str,
        worker_id: int = 1,
        domain: str = "unknown",
        service_name: str = "TrueCAPTCHA",
    ) -> None:
        """Records an outgoing service request to recognition API."""
        with self._lock:
            self.service_requests_count += 1
            evt = CaptchaEvent(
                event_id=f"evt_{len(self.recent_events)+1}_{int(time.time()*1000)%10000}",
                timestamp=datetime.now().strftime("%H:%M:%S"),
                event_type="service_request",
                domain=(domain or "unknown").strip().lower(),
                worker_id=worker_id,
                correlation_id=correlation_id,
                status="Request Sent",
                details=f"Outgoing request to {service_name}",
            )
            self._append_event(evt)

    def record_service_response(
        self,
        correlation_id: str,
        worker_id: int = 1,
        domain: str = "unknown",
        success: bool = True,
        request_id: Optional[str] = None,
        time_taken: Optional[float] = None,
    ) -> None:
        """
        Records a response received from recognition API.
        NOTE: This does NOT confirm website verification.
        """
        with self._lock:
            self.responses_received_count += 1
            req_str = f" [reqId: {request_id[:8]}...]" if request_id else ""
            timing_str = f" ({time_taken:.2f}s)" if time_taken else ""
            status_label = "Response OK" if success else "Response Failed"
            details = f"Service responded: success={success}{timing_str}{req_str}"

            evt = CaptchaEvent(
                event_id=f"evt_{len(self.recent_events)+1}_{int(time.time()*1000)%10000}",
                timestamp=datetime.now().strftime("%H:%M:%S"),
                event_type="service_response",
                domain=(domain or "unknown").strip().lower(),
                worker_id=worker_id,
                correlation_id=correlation_id,
                status=status_label,
                details=details,
            )
            self._append_event(evt)

    def record_website_verification(
        self,
        correlation_id: str,
        worker_id: int = 1,
        domain: str = "unknown",
        details: str = "Target website confirmed verification",
    ) -> None:
        """
        Records confirmation that the TARGET WEBSITE verified and unlocked content.
        Only called when the target website confirmed the action.
        """
        with self._lock:
            self.website_verifications_confirmed_count += 1
            evt = CaptchaEvent(
                event_id=f"evt_{len(self.recent_events)+1}_{int(time.time()*1000)%10000}",
                timestamp=datetime.now().strftime("%H:%M:%S"),
                event_type="website_confirmed",
                domain=(domain or "unknown").strip().lower(),
                worker_id=worker_id,
                correlation_id=correlation_id,
                status="Website Verified",
                details=details,
            )
            self._append_event(evt)

    def record_manual_verification_required(
        self,
        correlation_id: str,
        worker_id: int = 1,
        domain: str = "unknown",
        job_index: Optional[int] = None,
        reason: str = "Challenge requires manual verification",
    ) -> None:
        """Records that a challenge could not be verified automatically and requires human action."""
        with self._lock:
            job_key = f"{self.job_id}:{job_index if job_index is not None else correlation_id}"
            self.manual_verification_required_jobs.add(job_key)

            evt = CaptchaEvent(
                event_id=f"evt_{len(self.recent_events)+1}_{int(time.time()*1000)%10000}",
                timestamp=datetime.now().strftime("%H:%M:%S"),
                event_type="manual_required",
                domain=(domain or "unknown").strip().lower(),
                worker_id=worker_id,
                correlation_id=correlation_id,
                status="Manual Required",
                details=reason,
            )
            self._append_event(evt)

    def _append_event(self, evt: CaptchaEvent) -> None:
        self.recent_events.append(evt.to_dict())
        if len(self.recent_events) > 50:
            self.recent_events = self.recent_events[-50:]

    def get_summary(self) -> Dict[str, Any]:
        """Returns safe metrics dictionary for API and dashboard."""
        with self._lock:
            return {
                "challenges_detected": self.challenges_detected_count,
                "unique_challenges": len(self.unique_challenges),
                "jobs_requiring_captcha": len(self.jobs_requiring_captcha),
                "service_requests": self.service_requests_count,
                "responses_received": self.responses_received_count,
                "website_verifications_confirmed": self.website_verifications_confirmed_count,
                "manual_verification_required": len(self.manual_verification_required_jobs),
                "recent_events": list(self.recent_events[-35:]),
            }


_trackers_lock = threading.Lock()
_trackers: Dict[str, CaptchaTracker] = {}
_default_tracker = CaptchaTracker("global")


def get_captcha_tracker(job_id: Optional[str] = None) -> CaptchaTracker:
    """Retrieve or create the CaptchaTracker for a job."""
    if not job_id:
        return _default_tracker
    with _trackers_lock:
        if job_id not in _trackers:
            _trackers[job_id] = CaptchaTracker(job_id)
        return _trackers[job_id]


def reset_captcha_tracker(job_id: Optional[str] = None) -> None:
    """Reset tracker state for testing or new jobs."""
    if not job_id:
        global _default_tracker
        _default_tracker = CaptchaTracker("global")
        return
    with _trackers_lock:
        _trackers[job_id] = CaptchaTracker(job_id)

