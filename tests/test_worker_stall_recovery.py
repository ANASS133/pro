"""
Regression tests for the auto-extraction stall (e.g. 549/563 with 1 active worker,
3 workers "waiting" and 14 jobs pending forever) and for related performance fixes.
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

import app as app_module


HANG_RELEASE = threading.Event()


class _HangingExtractor:
    """Fake extractor: job #7 hangs (simulates a wedged Selenium/renderer call)."""

    def __init__(self, *args, worker_id=1, lazy_driver=False, **kwargs):
        self.worker_id = worker_id
        self.lazy_driver = lazy_driver
        self.driver = MagicMock()
        self.stats = {}

    def process_job(self, job, profession_keyword="", on_stage_change=None):
        if job["id"] == 7:
            HANG_RELEASE.wait(timeout=30)
        else:
            time.sleep(0.005)
        res = dict(job)
        res.update(extraction_status="completed", email=f"job{job['id']}@example.test", email_extracted=True)
        return res

    def save_progress(self, *args, **kwargs):
        return None

    def close(self):
        return None


def _profiles():
    return {
        i: SimpleNamespace(
            worker_id=i,
            profile_name=f"Worker-{i}",
            connection_status="connected",
            allow_direct_fallback=True,
            public_ip="127.0.0.1",
        )
        for i in range(1, 5)
    }


class AutoExtractionStallRecoveryTest(unittest.TestCase):
    def setUp(self):
        HANG_RELEASE.clear()
        self.saved_jobs = dict(app_module.auto_extraction_jobs)
        app_module.auto_extraction_jobs.clear()
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.patches = [
            patch.object(app_module, "AUTO_JOBS_STORE_PATH", root / "jobs.json"),
            patch.object(app_module, "SEARCH_RUNS_STORE_PATH", root / "runs.json"),
            patch.object(app_module, "PROGRESS_DIR", root / "progress"),
            patch.dict(os.environ, {"AUTO_EXTRACTION_TASK_TIMEOUT": "0.6"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        HANG_RELEASE.set()
        for p in reversed(self.patches):
            p.stop()
        app_module.auto_extraction_jobs.clear()
        app_module.auto_extraction_jobs.update(self.saved_jobs)
        self.tempdir.cleanup()

    def test_hung_task_is_recovered_and_run_completes(self):
        jobs = [{"id": i, "title": f"Job {i}", "company": f"Co {i}", "url": f"https://example.test/{i}"} for i in range(40)]
        job_id = app_module._create_auto_extraction_job(jobs, "Pflege", "Berlin", "all")

        t0 = time.time()
        with patch.object(app_module, "WorkingEmailExtractor", _HangingExtractor), \
             patch("services.worker_network_router.load_worker_network_profiles", return_value=_profiles()), \
             patch("services.worker_network_router.verify_all_worker_connections", return_value=_profiles()):
            runner = threading.Thread(target=app_module._run_auto_extraction_job, args=(job_id,))
            runner.start()
            runner.join(timeout=15)
        self.assertFalse(runner.is_alive(), "extraction run stalled instead of recovering the hung worker")
        self.assertLess(time.time() - t0, 15)

        result = app_module.auto_extraction_jobs[job_id]
        self.assertEqual(result["current_index"], 40)
        self.assertIn(result["status_label"], ("Completed", "Completed with Manual Review"))
        self.assertEqual(result["jobs"][7]["attempt_state"], "timed_out")
        self.assertIn(result["jobs"][7]["extraction_status"], ("timed_out", "extraction_failed"))
        for row in result["jobs"]:
            if row["id"] != 7:
                self.assertEqual(row["attempt_state"], "completed")
        # No worker may be left "waiting" once nothing remains to be claimed.
        for w in result["workers"].values():
            self.assertNotIn(w["status"], ("waiting", "working"))

    def test_job_finished_respects_attempt_state(self):
        self.assertTrue(app_module._is_job_finished({"attempt_state": "timed_out"}))
        self.assertFalse(app_module._is_job_finished({"title": "fresh"}))


class ExtractorPerformanceRegressionTest(unittest.TestCase):
    def _make_extractor(self):
        from scraper.working_email_extractor import WorkingEmailExtractor
        with patch("scraper.working_email_extractor.start_driver") as start:
            ext = WorkingEmailExtractor(headless=True, lazy_driver=True)
            start.assert_not_called()
        return ext

    def test_lazy_driver_does_not_launch_browser(self):
        ext = self._make_extractor()
        self.assertIsNone(ext.driver)
        ext.close()

    def test_azubiyo_job_no_name_error(self):
        ext = self._make_extractor()
        ext.azubiyo_extractor.extract_vacancy = MagicMock(return_value={"email": "ausbildung@klinik.test"})
        job = {"source": "azubiyo", "url": "https://www.azubiyo.de/stellenanzeigen/x_y_16a4g814/", "company": "Klinik"}
        res = ext.process_job(job)
        self.assertEqual(res["email"], "ausbildung@klinik.test")
        self.assertIsNone(ext.driver)
        ext.close()

    def test_ausbildung_de_fast_http_no_double_fetch(self):
        ext = self._make_extractor()
        ext.ausbildung_extractor.extract_vacancy = MagicMock(return_value={})
        ext.session.get = MagicMock()
        job = {"source": "ausbildung.de", "company": "Nobody GmbH",
               "url": f"https://www.ausbildung.de/stellen/test-{time.time_ns()}/"}
        self.assertIsNone(ext.extract_via_fast_http(job))
        ext.session.get.assert_not_called()
        ext.close()

    def test_region_restricted_short_circuits_selenium(self):
        ext = self._make_extractor()
        restricted = {"extraction_status": "region_restricted", "manual_review_required": True}
        with patch.object(ext, "extract_via_fast_http", return_value=restricted), \
             patch.object(ext, "recycle_driver_if_needed") as recycle:
            res = ext.process_job({"source": "ausbildung.de", "url": "https://www.ausbildung.de/stellen/x/"})
        self.assertEqual(res["extraction_status"], "region_restricted")
        recycle.assert_not_called()
        ext.close()

    def test_arbeitsagentur_driver_provider_only_when_needed(self):
        from scraper.arbeitsagentur_extractor import ArbeitsagenturDetailExtractor
        aa = ArbeitsagenturDetailExtractor(session=MagicMock())
        provider = MagicMock(return_value=None)
        with patch("scraper.rate_limiter.safe_http_get", return_value=None):
            aa.extract_vacancy({"url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1-S"}, driver_provider=provider)
        provider.assert_called_once()

        provider2 = MagicMock()
        with patch.object(aa, "parse_application_section", return_value={"email": "a@b.de", "logs": []}), \
             patch("scraper.rate_limiter.safe_http_get", return_value=SimpleNamespace(status_code=200, text="<html/>")):
            aa.extract_vacancy({"url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-2-S"}, driver_provider=provider2)
        provider2.assert_not_called()

    def test_employer_crawl_cache_reuses_results(self):
        import services.application_url_validator as v
        v._EMPLOYER_CRAWL_CACHE.clear()
        sess = requests.Session()
        sess.get = MagicMock(return_value=SimpleNamespace(status_code=200, url="https://www.acme-pflege.de/", text="<html><body>Hi</body></html>"))
        r1 = v.follow_generic_employer_website("https://www.acme-pflege.de/", company="Acme", job_title="Pflegefachmann", session=sess)
        calls = sess.get.call_count
        r2 = v.follow_generic_employer_website("https://www.acme-pflege.de/", company="Acme", job_title="Pflegefachmann", session=sess)
        self.assertEqual(sess.get.call_count, calls, "second crawl of same employer domain should hit cache")
        self.assertEqual(r1["diagnostic_reason"], r2["diagnostic_reason"])


if __name__ == "__main__":
    unittest.main()
