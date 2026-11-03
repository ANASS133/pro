"""Verifies parallel portal execution, accurate per-portal state, progress and timeout handling."""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import _fetch_combined_jobs  # noqa: E402


def _slow(delay, jobs):
    def fn(*a, **k):
        time.sleep(delay)
        return list(jobs)
    return fn


AA_JOB = {
    "title": "Ausbildung zum Fachinformatiker",
    "company": "Tech AG",
    "city": "Köln",
    "location": "Köln",
    "source": "Arbeitsagentur",
    "apply_url": "https://tech.de/karriere",
    "reference": "aa-1",
}


class TestParallelPortalMonitoring(unittest.TestCase):
    def _run(self, events, **kw):
        return _fetch_combined_jobs(
            keyword="Fachinformatiker",
            location="Köln",
            source="job_portals",
            mode="ausbildung",
            max_jobs=10,
            progress_callback=events.append,
            return_audit=True,
            **kw,
        )

    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", side_effect=_slow(1.0, []))
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", side_effect=_slow(1.0, []))
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", side_effect=_slow(1.0, []))
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", side_effect=RuntimeError("boom api_key=SECRET123"))
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs", side_effect=_slow(1.0, [AA_JOB]))
    def test_portals_run_concurrently_and_states_are_accurate(self, *_mocks):
        events = []
        t0 = time.time()
        jobs, audit = self._run(events)
        elapsed = time.time() - t0
        # 4 portals x 1s sleeping sequentially would take >= 4s
        self.assertLess(elapsed, 3.0, f"portals did not run in parallel ({elapsed:.1f}s)")

        # At some point several portals were running simultaneously
        max_running = max(e["workers"]["running"] for e in events)
        self.assertGreaterEqual(max_running, 3)

        final = events[-1]
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["percent"], 100)
        portals = final["portals"]
        self.assertEqual(portals["arbeitsagentur"]["state"], "completed")
        self.assertEqual(portals["arbeitsagentur"]["scanned"], 1)
        self.assertEqual(portals["arbeitsagentur"]["accepted"], 1)
        self.assertEqual(portals["ausbildung_de"]["state"], "failed")
        self.assertEqual(portals["google_maps"]["state"], "skipped")
        self.assertEqual(final["workers"]["finished"], final["workers"]["total"])
        self.assertEqual(final["live_metrics"]["accepted"], len(jobs))

        # Progress never runs ahead of completed portals and is monotonic
        pcts = [e["percent"] for e in events]
        self.assertEqual(pcts, sorted(pcts))
        for e in events[:-1]:
            w = e["workers"]
            expected = int(5 + 90 * w["finished"] / w["total"])
            self.assertEqual(e["percent"], expected)

        # Secrets never reach logs
        all_text = str([e.get("new_logs") for e in events])
        self.assertNotIn("SECRET123", all_text)

    @patch.dict(os.environ, {"PORTAL_SOFT_TIMEOUT_SECONDS": "10", "PORTAL_TIMEOUT_SECONDS": "16"})
    @patch("scraper.ihk_scraper.IhkScraper.fetch_jobs", side_effect=_slow(40, []))
    @patch("scraper.aubi_plus_scraper.AubiPlusScraper.fetch_jobs", return_value=[])
    @patch("scraper.azubiyo_scraper.AzubiyoScraper.fetch_jobs", return_value=[])
    @patch("scraper.ausbildung_de_scraper.AusbildungDeScraper.fetch_jobs", return_value=[])
    @patch("scraper.enhanced_api_scraper.EnhancedJobScraper.fetch_all_jobs", return_value=[AA_JOB])
    def test_stalled_portal_times_out_and_search_completes(self, *_mocks):
        events = []
        t0 = time.time()
        jobs, _ = self._run(events)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 25, "search waited for the stalled portal")
        final = events[-1]
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["portals"]["ihk"]["state"], "timeout")
        self.assertEqual(final["portals"]["arbeitsagentur"]["state"], "completed")
        self.assertTrue(any(e["status"] == "heartbeat" for e in events))
        logs = [l for e in events for l in e.get("new_logs") or []]
        self.assertTrue(any(l["level"] == "warning" and "slow" in l["message"].lower() for l in logs))
        self.assertGreaterEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()

