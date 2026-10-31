"""
JobScout Central Conductor Engine.
The primary autonomous multi-agent orchestrator coordinating:
1. Candidate Onboarding -> Dossier Synchronization & Missing Document Checks
2. Autonomous Daily Job & Ausbildung Discovery (DailySearchRunner)
3. Automatic Cover Letter Generation and Authorization Staging
4. Recruitment Email Inbox Reply Monitoring & AI Classification (EmailReplyMonitor)
5. Proactive Candidate WhatsApp Liaison & Alerts (ConductorWhatsAppLiaison)
6. Task Queues, Error Handling, Retries, Per-Client Pause/Resume, and Global Emergency Stop
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.client_manager import client_manager
from services.conductor_store import conductor_store
from services.daily_search_runner import daily_search_runner
from services.email_reply_monitor import email_reply_monitor
from services.conductor_whatsapp_liaison import conductor_whatsapp_liaison

logger = logging.getLogger(__name__)


class ConductorEngine:
    def __init__(self, store=None, search_runner=None, email_monitor=None, whatsapp_liaison=None):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._last_inbox_check: Optional[datetime] = None
        self._consecutive_errors = 0
        self._store = store
        self._search_runner = search_runner
        self._email_monitor = email_monitor
        self._whatsapp_liaison = whatsapp_liaison

    @property
    def store(self):
        return self._store or conductor_store

    @property
    def search_runner(self):
        return self._search_runner or daily_search_runner

    @property
    def email_monitor(self):
        return self._email_monitor or email_reply_monitor

    @property
    def whatsapp_liaison(self):
        return self._whatsapp_liaison or conductor_whatsapp_liaison

    def is_running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    def start(self):
        """Starts the background autonomous orchestration loop."""
        with self._lock:
            if self.is_running():
                return
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="JobScoutConductorWorker")
            self._thread.start()
            self.store.log_event("INFO", "conductor", "JobScout Conductor background engine started.")

    def stop(self):
        """Stops the background autonomous orchestration loop."""
        with self._lock:
            self._running = False
            self._stop_event.set()
            self.store.log_event("INFO", "conductor", "JobScout Conductor background engine stopped.")

    def on_client_onboarded(self, client_id: str, missing_fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Hook invoked automatically when a candidate is onboarded via CandidateOnboardingService.
        Registers client config, logs onboarding task, and requests missing documents if needed.
        """
        cfg = self.store.get_client_config(client_id)
        task = self.store.create_task("client_onboarding", client_id=client_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        self.store.update_task(task["id"], {
            "status": "completed",
            "started_at": now_iso,
            "completed_at": now_iso,
            "result_summary": f"Onboarded client '{client_id}' into JobScout Conductor."
        })
        self.store.log_event("SUCCESS", "conductor", f"Client '{client_id}' onboarded and linked to Conductor.", client_id=client_id)

        docs_requested = False
        if missing_fields and "cv_document" in missing_fields and not self.store.is_emergency_stopped():
            try:
                docs_requested = self.whatsapp_liaison.request_missing_documents(client_id)
            except Exception as exc:
                logger.debug("Onboarding document request skipped for %s: %s", client_id, exc)

        return {"client_id": client_id, "config": cfg, "docs_requested": docs_requested}

    def pause_client(self, client_id: str, paused: bool) -> Dict[str, Any]:
        """Pauses or resumes autonomous workflows for a specific client."""
        updated = self.store.update_client_config(client_id, {"is_paused": 1 if paused else 0})
        state_str = "PAUSED" if paused else "RESUMED"
        self.store.log_event("INFO", "conductor", f"Automation {state_str} for client {client_id}.", client_id=client_id)
        return updated

    def _worker_loop(self):
        logger.info("JobScout Conductor background worker started.")
        while not self._stop_event.is_set():
            try:
                # 1. Check Global Emergency Stop
                if self.store.is_emergency_stopped():
                    time.sleep(5)
                    continue

                # 2. Check Daily Search for Due Clients
                if self.store.get_setting("auto_daily_search", "true").lower() in ("true", "1"):
                    self._check_and_run_due_daily_searches()

                # 3. Check Email Inbox Replies
                if self.store.get_setting("auto_email_monitoring", "true").lower() in ("true", "1"):
                    interval_min = int(self.store.get_setting("email_monitor_interval_minutes", "15") or 15)
                    now = datetime.now(timezone.utc)
                    if not self._last_inbox_check or (now - self._last_inbox_check) >= timedelta(minutes=interval_min):
                        self._last_inbox_check = now
                        self.check_inbox_now()

                # 4. Retry eligible failed tasks
                self._retry_failed_tasks()

                self._consecutive_errors = 0
            except Exception as exc:
                self._consecutive_errors += 1
                logger.error("Error in Conductor worker loop: %s", exc)
                self.store.log_event("ERROR", "conductor", f"Worker loop error: {exc}")
                max_err = int(self.store.get_setting("max_consecutive_errors", "5") or 5)
                if self._consecutive_errors >= max_err:
                    self.store.set_emergency_stop(True)
                    self.store.log_event("ERROR", "conductor", f"Triggered automatic emergency stop after {self._consecutive_errors} consecutive errors.")

            # Sleep in small slices to allow rapid shutdown response
            for _ in range(30):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _retry_failed_tasks(self):
        """Automatically retries failed tasks that have not exceeded max_task_retries."""
        max_retries = int(self.store.get_setting("max_task_retries", "3") or 3)
        failed_tasks = self.store.list_tasks(limit=10, status="failed")
        for t in failed_tasks:
            if int(t.get("retry_count", 0)) < max_retries:
                self.retry_task(t["id"])

    def retry_task(self, task_id: str) -> Dict[str, Any]:
        """Retries a failed or pending orchestration task."""
        task = self.store.get_task(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}

        if self.store.is_emergency_stopped():
            return {"success": False, "error": "Emergency stop is active"}

        new_retry = int(task.get("retry_count", 0)) + 1
        self.store.update_task(task_id, {
            "status": "running",
            "retry_count": new_retry,
            "error_message": "",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        self.store.log_event("INFO", "conductor", f"Retrying task {task_id} (attempt #{new_retry})...", client_id=task.get("client_id", ""))

        try:
            ttype = task.get("task_type")
            cid = task.get("client_id", "")
            if ttype == "daily_search" and cid and cid != "all":
                cfg = self.store.get_client_config(cid)
                res = self.search_runner.run_daily_search_for_client(cid, max_jobs=cfg.get("max_daily_applications", 5))
                summary = f"Retry succeeded: {res.get('new_matches_count', 0)} matches found."
            elif ttype == "email_reply_monitor":
                res = self.email_monitor.check_inbox()
                summary = f"Retry succeeded: {res.get('processed_count', 0)} messages processed."
            else:
                res = {}
                summary = "Retry completed."

            self.store.update_task(task_id, {
                "status": "completed",
                "result_summary": summary,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"success": True, "task_id": task_id, "retry_count": new_retry, "result": res}
        except Exception as exc:
            self.store.update_task(task_id, {
                "status": "failed",
                "error_message": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"success": False, "task_id": task_id, "retry_count": new_retry, "error": str(exc)}

    def _check_and_run_due_daily_searches(self):
        """Checks which clients are due for autonomous daily search and executes them."""
        interval_hours = int(self.store.get_setting("daily_search_interval_hours", "24") or 24)
        threshold_dt = datetime.now(timezone.utc) - timedelta(hours=interval_hours)

        clients = client_manager.list_clients()
        for c in clients:
            if self._stop_event.is_set() or self.store.is_emergency_stopped():
                break

            cid = c["id"]
            cfg = self.store.get_client_config(cid)
            if cfg.get("is_paused", 0) or not cfg.get("auto_search", 1):
                continue

            last_search = cfg.get("last_search_at", "")
            is_due = True
            if last_search:
                try:
                    last_dt = datetime.fromisoformat(last_search)
                    if last_dt > threshold_dt:
                        is_due = False
                except Exception:
                    is_due = True

            if is_due:
                self.run_cycle_for_client(cid, trigger_source="scheduler")

    def run_cycle_for_client(self, client_id: str, trigger_source: str = "manual") -> Dict[str, Any]:
        """
        Executes a complete autonomous cycle for a single client:
        1. Checks emergency stop and client pause status
        2. Discovers matching jobs via DailySearchRunner
        3. Generates cover letters & stages applications
        4. Notifies candidate via WhatsApp if new matches are found
        """
        if self.store.is_emergency_stopped():
            self.store.log_event("WARN", "conductor", f"Cannot run cycle for {client_id}: Emergency Stop is active.", client_id)
            return {"success": False, "error": "Emergency stop is active"}

        cfg = self.store.get_client_config(client_id)
        if cfg.get("is_paused", 0) and trigger_source == "scheduler":
            return {"success": False, "skipped": True, "error": f"Client {client_id} is paused"}

        task = self.store.create_task("daily_search", client_id=client_id)
        task_id = task["id"]
        self.store.update_task(task_id, {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})

        try:
            max_daily = cfg.get("max_daily_applications", 5)

            # 1. Execute Search & Staging
            search_result = self.search_runner.run_daily_search_for_client(client_id, max_jobs=max_daily)
            new_matches = search_result.get("new_matches_count", 0)
            cover_letters = search_result.get("cover_letters_created", 0)

            # 2. Trigger Proactive WhatsApp Notice if new applications were prepared
            whatsapp_notified = False
            if new_matches > 0:
                matches_list = search_result.get("matches", [])
                titles = [m.get("job_title", "") for m in matches_list]
                m_ids = [m.get("id", "") for m in matches_list if m.get("id")]
                whatsapp_notified = self.whatsapp_liaison.notify_new_applications(
                    client_id,
                    new_matches,
                    job_titles=titles,
                    match_ids=m_ids,
                )

            summary = f"Discovered {new_matches} opportunities, staged {cover_letters} cover letter(s)."
            self.store.update_task(task_id, {
                "status": "completed",
                "result_summary": summary,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })

            return {
                "success": True,
                "task_id": task_id,
                "client_id": client_id,
                "trigger_source": trigger_source,
                "new_matches_count": new_matches,
                "cover_letters_created": cover_letters,
                "whatsapp_notified": whatsapp_notified,
                "search_result": search_result,
            }
        except Exception as exc:
            logger.error("Error running cycle for %s: %s", client_id, exc)
            self.store.update_task(task_id, {
                "status": "failed",
                "error_message": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            self.store.log_event("ERROR", "conductor", f"Cycle failed for {client_id}: {exc}", client_id)
            return {"success": False, "task_id": task_id, "error": str(exc)}

    def approve_match(self, match_id: str) -> Dict[str, Any]:
        """Approves a staged application, marks it as applied, and updates client dossier statistics."""
        match = self.store.get_match(match_id)
        if not match:
            return {"success": False, "error": "Match not found"}

        client_id = match.get("client_id", "")
        prev_status = match.get("status", "")
        self.store.update_match_status(match_id, "applied")

        if prev_status != "applied" and client_id:
            self.search_runner._increment_client_applied_stats(client_id, 1)

        self.store.log_event(
            "SUCCESS",
            "conductor",
            f"Authorized and submitted application for {match.get('company')} ({match.get('job_title')})",
            client_id=client_id,
        )
        return {
            "success": True,
            "match_id": match_id,
            "client_id": client_id,
            "status": "applied",
            "message": "Application approved and marked as applied",
        }

    def run_global_cycle(self, trigger_source: str = "manual") -> Dict[str, Any]:
        """Runs the complete autonomous cycle across all registered clients."""
        if self.store.is_emergency_stopped():
            return {"success": False, "error": "Emergency stop is active"}

        task = self.store.create_task("global_cycle", client_id="all")
        task_id = task["id"]
        self.store.update_task(task_id, {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})

        clients = client_manager.list_clients()
        results = []
        total_new_matches = 0
        total_cover_letters = 0

        for c in clients:
            cid = c["id"]
            cfg = self.store.get_client_config(cid)
            if cfg.get("is_paused", 0):
                continue
            c_res = self.run_cycle_for_client(cid, trigger_source=trigger_source)
            results.append(c_res)
            if c_res.get("success"):
                total_new_matches += c_res.get("new_matches_count", 0)
                total_cover_letters += c_res.get("cover_letters_created", 0)

        # Also check email replies
        inbox_res = self.check_inbox_now()

        summary = f"Processed {len(results)} active clients: {total_new_matches} matches, {total_cover_letters} cover letters, {inbox_res.get('processed_count', 0)} email replies."
        self.store.update_task(task_id, {
            "status": "completed",
            "result_summary": summary,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "success": True,
            "task_id": task_id,
            "clients_count": len(results),
            "total_new_matches": total_new_matches,
            "total_cover_letters": total_cover_letters,
            "inbox_result": inbox_res,
            "client_results": results,
        }

    def check_inbox_now(self) -> Dict[str, Any]:
        """Triggers an on-demand check of the recruitment email inbox."""
        if self.store.is_emergency_stopped():
            return {"success": False, "error": "Emergency stop is active"}

        task = self.store.create_task("email_reply_monitor", client_id="system")
        task_id = task["id"]
        self.store.update_task(task_id, {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})

        try:
            res = self.email_monitor.check_inbox()
            count = res.get("processed_count", 0)
            summary = f"Processed {count} messages (Status: {res.get('status')})"
            self.store.update_task(task_id, {
                "status": "completed",
                "result_summary": summary,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"success": True, **res}
        except Exception as exc:
            logger.error("Error during inbox check: %s", exc)
            self.store.update_task(task_id, {
                "status": "failed",
                "error_message": str(exc),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return {"success": False, "error": str(exc)}

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status, metrics, tasks, and activity logs."""
        counts = self.store.count_matches_by_status()
        clients = client_manager.list_clients()
        client_configs = self.store.list_client_configs()

        cfg_map = {cfg["client_id"]: cfg for cfg in client_configs}
        managed_clients = []
        for c in clients:
            cid = c["id"]
            cfg = cfg_map.get(cid, self.store.get_client_config(cid))
            c_counts = self.store.count_matches_by_status(cid)
            managed_clients.append({
                **c,
                "automation": cfg,
                "matches_stats": c_counts,
            })

        recent_tasks = self.store.list_tasks(limit=15)
        recent_logs = self.store.list_logs(limit=25)
        inbox_logs = self.store.list_inbox_logs(limit=15)

        return {
            "is_running": self.is_running(),
            "emergency_stop": self.store.is_emergency_stopped(),
            "settings": self.store.get_all_settings(),
            "metrics": {
                "total_managed_clients": len(clients),
                "discovered_matches": counts.get("discovered", 0),
                "staged_for_approval": counts.get("staged_for_approval", 0),
                "applied_total": counts.get("applied", 0),
                "interviews_total": counts.get("interview", 0),
                "rejections_total": counts.get("rejected", 0),
            },
            "clients": managed_clients,
            "recent_tasks": recent_tasks,
            "recent_logs": recent_logs,
            "recent_inbox_logs": inbox_logs,
        }


conductor_engine = ConductorEngine()
