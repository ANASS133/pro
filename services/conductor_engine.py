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
from services.profession_matcher import evaluate_profession_match
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
                if cfg.get("is_paused") or not cfg.get("auto_search", 1):
                    raise RuntimeError("Client search is paused or disabled")
                res = self.search_runner.run_daily_search_for_client(cid, max_jobs=cfg.get("max_daily_applications", 5))
                summary = f"Retry succeeded: {res.get('new_matches_count', 0)} matches found."
            elif ttype == "email_reply_monitor":
                res = self.email_monitor.check_inbox()
                if res.get("status") not in ("success", "empty_inbox"):
                    raise RuntimeError(res.get("error") or res.get("status") or "Inbox check failed")
                summary = f"Retry succeeded: {res.get('processed_count', 0)} messages processed."
            else:
                raise ValueError(f"Unsupported retry task type: {ttype}")

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

        # Pre-flight safety checks (Requirement 9 & 10)
        client_info = client_manager.get_client(client_id) or {}
        pkg = client_info.get("package") or {}
        is_paid = bool(pkg.get("payment_verified") or client_info.get("metadata", {}).get("supabase_application_id"))
        if not is_paid:
            self.store.log_event("WARN", "conductor", f"Blocked cycle for {client_id}: Client is unpaid or payment is unverified.", client_id)
            return {"success": False, "skipped": True, "reason": "unpaid_client", "error": "Client payment is unverified."}

        doc_dir = client_manager.clients_dir / client_id / "documents"
        has_cv = any("cv" in f.name.lower() or "lebenslauf" in f.name.lower() for f in doc_dir.iterdir()) if doc_dir.is_dir() else False
        if not has_cv:
            self.store.log_event("WARN", "conductor", f"Blocked cycle for {client_id}: Missing CV document in dossier.", client_id)
            if not self.store.is_emergency_stopped():
                try:
                    self.whatsapp_liaison.request_missing_documents(client_id)
                except Exception:
                    pass
            return {"success": False, "skipped": True, "reason": "incomplete_dossier", "error": "Candidate dossier is missing CV document."}

        total_limit = int(pkg.get("total_limit") or 500)
        c_stats = self.store.count_matches_by_status(client_id)
        applied_total = c_stats.get("applied", 0)
        if applied_total >= total_limit:
            self.store.log_event("WARN", "conductor", f"Blocked cycle for {client_id}: Application quota exhausted ({applied_total}/{total_limit}).", client_id)
            return {"success": False, "skipped": True, "reason": "quota_exhausted", "error": f"Application quota of {total_limit} has been reached."}

        task = self.store.create_task("daily_search", client_id=client_id)
        task_id = task["id"]
        self.store.update_task(task_id, {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})

        try:
            max_daily = cfg.get("max_daily_applications", 5)

            # 1. Execute Search & Staging
            search_result = self.search_runner.run_daily_search_for_client(client_id, max_jobs=max_daily)
            if search_result.get("skipped"):
                raise RuntimeError(search_result.get("reason", "Search skipped"))
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
        """Reject submission until an actual delivery adapter is available."""
        match = self.store.get_match(match_id)
        if not match:
            return {"success": False, "error": "Match not found"}

        return {
            "success": False,
            "match_id": match_id,
            "status": match.get("status"),
            "error": "Application submission is not implemented in Conductor; no email or online form was sent",
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

        cycle_ok = all(r.get("success") for r in results) and inbox_res.get("success", False)
        summary = f"Processed {len(results)} active clients: {total_new_matches} matches, {total_cover_letters} cover letters, {inbox_res.get('processed_count', 0)} email replies."
        self.store.update_task(task_id, {
            "status": "completed" if cycle_ok else "failed",
            "result_summary": summary,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "success": bool(cycle_ok),
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
            if res.get("status") not in ("success", "empty_inbox"):
                raise RuntimeError(res.get("error") or res.get("status") or "Inbox check failed")
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

    def sync_supabase_applications(self) -> Dict[str, Any]:
        """
        Synchronizes all paid applications from Supabase into Conductor without duplicates.
        Ensures client dossiers, package quota, documents, and automation configs are in sync.
        """
        if self.store.is_emergency_stopped():
            return {"success": False, "error": "Emergency stop is active"}

        task = self.store.create_task("supabase_sync", client_id="system")
        task_id = task["id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        self.store.update_task(task_id, {"status": "running", "started_at": now_iso})

        from services.supabase_service import supabase_service
        from services.onboarding_service import candidate_onboarding_service
        from services.onboarding_tracker import onboarding_tracker

        new_count = 0
        synced_count = 0
        errors = []

        try:
            paid_apps = supabase_service.list_applications(is_payed=True)
        except Exception as exc:
            logger.warning("Could not list paid applications from Supabase (offline/mock): %s", exc)
            paid_apps = []

        existing_records = onboarding_tracker.get_all_records()

        for app in paid_apps:
            app_id = str(app.get("id") or "").strip()
            if not app_id:
                continue

            try:
                if app_id not in existing_records:
                    # New paid candidate: run full onboarding pipeline
                    onboard_res = candidate_onboarding_service.onboard_candidate(app_id)
                    cid = onboard_res.get("client_id")
                    if cid:
                        self.on_client_onboarded(cid, missing_fields=onboard_res.get("missing_fields"))
                        new_count += 1
                else:
                    # Already tracked: verify dossier is initialized in conductor
                    rec = existing_records[app_id]
                    cid = rec.get("client_id")
                    if cid:
                        self.store.get_client_config(cid)
                        synced_count += 1
            except Exception as item_err:
                errors.append(f"App {app_id}: {str(item_err)}")
                logger.error("Error syncing application %s: %s", app_id, item_err)

        local_clients = client_manager.list_clients()
        for lc in local_clients:
            self.store.get_client_config(lc["id"])

        summary = f"Synced with Supabase: {new_count} newly imported, {synced_count} up-to-date. Total managed: {len(local_clients)}."
        self.store.update_task(task_id, {
            "status": "completed",
            "result_summary": summary,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        self.store.log_event("SUCCESS", "conductor", summary, client_id="system")

        return {
            "success": True,
            "task_id": task_id,
            "newly_imported": new_count,
            "synced_existing": synced_count,
            "total_managed_clients": len(local_clients),
            "errors": errors,
            "summary": summary,
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status, metrics, tasks, and activity logs."""
        counts = self.store.count_matches_by_status()
        clients = client_manager.list_clients()
        client_configs = self.store.list_client_configs()

        cfg_map = {cfg["client_id"]: cfg for cfg in client_configs}
        export_datasets = self.search_runner._list_export_datasets()
        managed_clients = []
        for c in clients:
            cid = c["id"]
            cfg = cfg_map.get(cid, self.store.get_client_config(cid))
            c_counts = self.store.count_matches_by_status(cid)

            # Quota calculations
            pkg = c.get("package") or {}
            total_limit = int(pkg.get("total_limit") or 500)
            applied_total = c_counts.get("applied", 0)
            remaining_quota = max(0, total_limit - applied_total)
            quota_exhausted = remaining_quota <= 0

            # Payment verification
            is_paid = bool(pkg.get("payment_verified") or c.get("supabase_application_id"))
            payment_status = "paid" if is_paid else "pending"

            # Dataset availability matching
            target_prof = c.get("target_profession") or c.get("title") or "Fachinformatiker"
            ds_match = evaluate_profession_match(target_prof, export_datasets)
            available_listings = sum(int(d.get("row_count") or 0) for d in ds_match.get("matched_datasets", []))

            # Channel stats (email vs portal leads)
            client_matches = self.store.list_matches(client_id=cid, limit=500)
            email_leads = sum(1 for m in client_matches if m.get("application_method") == "email" or "@" in (m.get("email") or ""))
            portal_leads = sum(1 for m in client_matches if m.get("application_method") == "form" or bool(m.get("apply_url")))
            cover_letters_ready = sum(1 for m in client_matches if bool(m.get("cover_letter_path")))

            # Automation readiness & blockers
            blocking_reasons = []
            if cfg.get("is_paused", 0):
                blocking_reasons.append("Automation is paused")
            if not is_paid:
                blocking_reasons.append("Payment unverified or pending")
            if not c.get("has_cv"):
                blocking_reasons.append("Missing CV document")
            if quota_exhausted:
                blocking_reasons.append("Application quota exhausted")

            managed_clients.append({
                **c,
                "automation": cfg,
                "matches_stats": c_counts,
                "quota": {
                    "package_name": pkg.get("name") or "Standard (500)",
                    "total_limit": total_limit,
                    "applied": applied_total,
                    "remaining": remaining_quota,
                    "is_exhausted": quota_exhausted,
                    "percent_used": round((applied_total / total_limit) * 100, 1) if total_limit else 0.0,
                },
                "payment": {
                    "is_paid": is_paid,
                    "status": payment_status,
                    "bank": pkg.get("bank", ""),
                },
                "dataset_availability": {
                    "status": ds_match.get("status", "none"),
                    "available_listings": available_listings,
                    "matched_files_count": len(ds_match.get("matched_datasets", [])),
                    "details": ds_match.get("details", ""),
                },
                "channel_stats": {
                    "email_leads": email_leads,
                    "portal_leads": portal_leads,
                    "cover_letters_ready": cover_letters_ready,
                },
                "readiness": {
                    "is_ready_for_automation": len(blocking_reasons) == 0,
                    "blocking_reasons": blocking_reasons,
                    "premium_followup_eligible": is_paid and not quota_exhausted,
                },
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
