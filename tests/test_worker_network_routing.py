"""
Automated Test Suite for JobScout Independent Network Routing for 4 Extraction Workers.

Validates:
1. Per-worker profile loading, stable assignment, and protocol support (HTTP, HTTPS, SOCKS5).
2. Credential sanitization (passwords never exposed in dicts, URLs, or errors).
3. Public IP verification with 4 distinct IP addresses across 4 workers.
4. Strict fail-closed semantics (no silent fallback or host IP leak when proxy is unreachable).
5. Configurable direct fallback when explicitly enabled.
6. Worker session, cookie, and proxy isolation between worker instances.
7. Selenium browser proxy option configuration.
8. Dashboard API status response containing routing profiles, connection status, and public IPs.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from services.worker_network_router import (
    WorkerNetworkProfile,
    load_worker_network_profiles,
    verify_worker_connection,
    verify_all_worker_connections,
    redact_proxy_url,
    parse_proxy_components,
    apply_proxy_to_browser_options,
)
from scraper.working_email_extractor import WorkingEmailExtractor


class TestWorkerNetworkRouting(unittest.TestCase):

    def test_credential_sanitization_and_redaction(self):
        """Proxy passwords must never be exposed in sanitized URLs, dict representations, or error logs."""
        raw_http = "http://alice:supersecret123@198.51.100.10:8080"
        sanitized_http = redact_proxy_url(raw_http)
        self.assertNotIn("supersecret123", sanitized_http)
        self.assertIn("***:***", sanitized_http)
        self.assertIn("198.51.100.10:8080", sanitized_http)

        raw_socks = "socks5://socksuser:p@ssword!@203.0.113.50:1080"
        sanitized_socks = redact_proxy_url(raw_socks)
        self.assertNotIn("p@ssword!", sanitized_socks)
        self.assertIn("***:***", sanitized_socks)
        self.assertIn("203.0.113.50:1080", sanitized_socks)

        profile = WorkerNetworkProfile(
            worker_id=1,
            profile_name="Secure-Proxy-1",
            proxy_url=raw_http,
            protocol="http",
            public_ip="198.51.100.10",
            connection_status="connected",
        )
        safe_dict = profile.to_dict()
        self.assertNotIn("supersecret123", str(safe_dict))
        self.assertNotIn("alice", str(safe_dict))
        self.assertEqual(safe_dict["profile_name"], "Secure-Proxy-1")
        self.assertEqual(safe_dict["public_ip"], "198.51.100.10")
        self.assertEqual(safe_dict["connection_status"], "connected")

    def test_load_worker_network_profiles_http_https_socks5(self):
        """Loads and parses HTTP, HTTPS, and SOCKS5 configurations for 4 workers with custom names."""
        test_config = {
            "WORKER_ALLOW_DIRECT_FALLBACK": "false",
            "WORKER_1_PROXY": "http://user1:pass1@198.51.100.1:8080",
            "WORKER_1_NAME": "Proxy-Frankfurt-1",
            "WORKER_2_PROXY": "https://user2:pass2@198.51.100.2:8443",
            "WORKER_2_NAME": "Proxy-Munich-2",
            "WORKER_3_PROXY": "socks5://user3:pass3@198.51.100.3:1080",
            "WORKER_3_NAME": "Proxy-Berlin-3",
            "WORKER_4_PROXY": "socks5h://user4:pass4@198.51.100.4:1080",
            "WORKER_4_NAME": "Proxy-Hamburg-4",
        }

        profiles = load_worker_network_profiles(config=test_config, max_workers=4)

        self.assertEqual(len(profiles), 4)
        self.assertEqual(profiles[1].profile_name, "Proxy-Frankfurt-1")
        self.assertEqual(profiles[1].protocol, "http")
        self.assertFalse(profiles[1].allow_direct_fallback)

        self.assertEqual(profiles[2].profile_name, "Proxy-Munich-2")
        self.assertEqual(profiles[2].protocol, "https")

        self.assertEqual(profiles[3].profile_name, "Proxy-Berlin-3")
        self.assertEqual(profiles[3].protocol, "socks5")

        self.assertEqual(profiles[4].profile_name, "Proxy-Hamburg-4")
        self.assertEqual(profiles[4].protocol, "socks5h")

    def test_verify_worker_connections_four_distinct_ips(self):
        """Simulates 4 distinct workers checking public IP and receiving 4 distinct verified IPs."""
        profiles = {
            1: WorkerNetworkProfile(1, "Worker-1-DE", proxy_url="http://198.51.100.1:8080"),
            2: WorkerNetworkProfile(2, "Worker-2-DE", proxy_url="http://198.51.100.2:8080"),
            3: WorkerNetworkProfile(3, "Worker-3-DE", proxy_url="http://198.51.100.3:8080"),
            4: WorkerNetworkProfile(4, "Worker-4-DE", proxy_url="http://198.51.100.4:8080"),
        }

        mock_responses = {
            "http://198.51.100.1:8080": "198.51.100.1",
            "http://198.51.100.2:8080": "198.51.100.2",
            "http://198.51.100.3:8080": "198.51.100.3",
            "http://198.51.100.4:8080": "198.51.100.4",
        }

        def mock_get(session_self, url, **kwargs):
            session_proxies = getattr(session_self, "proxies", {})
            proxy_used = session_proxies.get("http")
            ip = mock_responses.get(proxy_used, "127.0.0.1")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = f'{{"ip": "{ip}"}}'
            mock_resp.json.return_value = {"ip": ip}
            return mock_resp

        with patch("requests.Session.get", autospec=True, side_effect=mock_get):
            for w_id, prof in profiles.items():
                success, ip, err = verify_worker_connection(prof)
                self.assertTrue(success)
                self.assertEqual(prof.connection_status, "connected")

        # Verify that all 4 workers have unique, distinct public IPs
        verified_ips = [p.public_ip for p in profiles.values()]
        self.assertEqual(len(set(verified_ips)), 4)
        self.assertEqual(verified_ips, ["198.51.100.1", "198.51.100.2", "198.51.100.3", "198.51.100.4"])

    def test_strict_fail_closed_behavior(self):
        """When proxy is unreachable and allow_direct_fallback is False, fail closed without leaking host IP."""
        profile = WorkerNetworkProfile(
            worker_id=2,
            profile_name="Proxy-Down",
            proxy_url="http://198.51.100.99:8080",
            allow_direct_fallback=False,  # strict fail-closed
        )

        with patch("requests.Session.get", side_effect=Exception("Connection refused")):
            success, ip, err = verify_worker_connection(profile)

        self.assertFalse(success)
        self.assertEqual(profile.connection_status, "failed")
        self.assertIn("Fail-Closed", profile.public_ip)
        self.assertIn("Fail-closed enforced", err)

        # Initializing extractor with this failed profile must raise fail-closed RuntimeError
        with self.assertRaises(RuntimeError) as ctx:
            WorkingEmailExtractor(
                captcha_userid="dummy",
                captcha_apikey="dummy",
                worker_id=2,
                network_profile=profile,
            )
        self.assertIn("Fail-closed enforced for worker 2", str(ctx.exception))

    def test_configurable_direct_fallback(self):
        """When allow_direct_fallback is True, worker degrades to direct connection with warning."""
        profile = WorkerNetworkProfile(
            worker_id=3,
            profile_name="Proxy-Degraded",
            proxy_url="http://198.51.100.88:8080",
            allow_direct_fallback=True,  # fallback enabled
        )

        def mock_get(session_self, url, **kwargs):
            if getattr(session_self, "proxies", {}).get("http"):
                # Proxy attempt fails
                raise Exception("Proxy unreachable")
            # Direct fallback succeeds
            resp = MagicMock()
            resp.status_code = 200
            resp.text = '{"ip": "203.0.113.200"}'
            resp.json.return_value = {"ip": "203.0.113.200"}
            return resp

        with patch("requests.Session.get", autospec=True, side_effect=mock_get):
            success, ip, err = verify_worker_connection(profile)

        self.assertTrue(success)
        self.assertEqual(profile.connection_status, "degraded")
        self.assertEqual(profile.public_ip, "203.0.113.200")
        self.assertIn("fell back to direct", err)

    def test_worker_session_and_cookie_isolation(self):
        """Ensure distinct worker extractors possess isolated sessions, independent cookies, and distinct proxies."""
        prof1 = WorkerNetworkProfile(1, "Worker-1", proxy_url="http://198.51.100.1:8080", connection_status="connected")
        prof2 = WorkerNetworkProfile(2, "Worker-2", proxy_url="http://198.51.100.2:8080", connection_status="connected")

        with patch("scraper.working_email_extractor.find_browser", return_value=("chrome", "/path/to/chrome")), \
             patch("scraper.working_email_extractor.start_driver") as mock_start:
            mock_start.return_value = MagicMock()

            ext1 = WorkingEmailExtractor(
                captcha_userid="u1",
                captcha_apikey="k1",
                worker_id=1,
                network_profile=prof1,
            )
            ext2 = WorkingEmailExtractor(
                captcha_userid="u2",
                captcha_apikey="k2",
                worker_id=2,
                network_profile=prof2,
            )

            # Assert separate session objects
            self.assertIsNot(ext1.session, ext2.session)

            # Assert separate proxies
            self.assertEqual(ext1.session.proxies.get("http"), "http://198.51.100.1:8080")
            self.assertEqual(ext2.session.proxies.get("http"), "http://198.51.100.2:8080")

            # Assert cookie isolation
            ext1.session.cookies.set("worker1_token", "secret1", domain="example.com")
            self.assertIn("worker1_token", ext1.session.cookies)
            self.assertNotIn("worker1_token", ext2.session.cookies)

            ext1.close()
            ext2.close()

    def test_selenium_browser_proxy_options(self):
        """Selenium options correctly set --proxy-server flag without leaking credentials."""
        prof = WorkerNetworkProfile(
            worker_id=1,
            profile_name="Test-Socks",
            proxy_url="socks5://198.51.100.1:1080",
        )
        options = MagicMock()
        apply_proxy_to_browser_options(options, prof)
        options.add_argument.assert_called_with("--proxy-server=socks5://198.51.100.1:1080")

    def test_dashboard_status_contains_routing_metadata(self):
        """Dashboard status API reflects worker routing profile, public IP, and connection status."""
        from app import app, auto_extraction_jobs, auto_extraction_jobs_lock

        test_job_id = "test_route_job_123"
        with auto_extraction_jobs_lock:
            auto_extraction_jobs[test_job_id] = {
                "job_id": test_job_id,
                "is_running": True,
                "current_index": 2,
                "total_jobs": 10,
                "workers": {
                    "worker_1": {
                        "id": "Worker 1",
                        "worker_id": 1,
                        "status": "processing",
                        "connection_status": "connected",
                        "network_profile": "Proxy-Frankfurt-1",
                        "public_ip": "198.51.100.1",
                        "current_job": "Siemens AG",
                        "completed_count": 1,
                        "method": "Fast-HTTP",
                    },
                    "worker_2": {
                        "id": "Worker 2",
                        "worker_id": 2,
                        "status": "idle",
                        "connection_status": "connected",
                        "network_profile": "Proxy-Munich-2",
                        "public_ip": "198.51.100.2",
                        "current_job": "Waiting for task...",
                        "completed_count": 1,
                        "method": "Selenium",
                    },
                    "worker_3": {
                        "id": "Worker 3",
                        "worker_id": 3,
                        "status": "failed",
                        "connection_status": "failed",
                        "network_profile": "Proxy-Berlin-3",
                        "public_ip": "Route Failed (Fail-Closed)",
                        "current_job": "Offline (Fail-Closed)",
                        "completed_count": 0,
                        "method": "—",
                    },
                    "worker_4": {
                        "id": "Worker 4",
                        "worker_id": 4,
                        "status": "idle",
                        "connection_status": "direct",
                        "network_profile": "Direct",
                        "public_ip": "203.0.113.5",
                        "current_job": "Waiting for task...",
                        "completed_count": 0,
                        "method": "—",
                    },
                },
            }

        client = app.test_client()
        resp = client.get(f"/api/inline/auto-jobs/status/{test_job_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertTrue(data["success"])
        job_data = data["job"]
        workers = job_data["workers"]

        self.assertIn("worker_1", workers)
        w1 = workers["worker_1"]
        self.assertEqual(w1["network_profile"], "Proxy-Frankfurt-1")
        self.assertEqual(w1["public_ip"], "198.51.100.1")
        self.assertEqual(w1["connection_status"], "connected")

        w3 = workers["worker_3"]
        self.assertEqual(w3["connection_status"], "failed")
        self.assertEqual(w3["public_ip"], "Route Failed (Fail-Closed)")

        # Cleanup
        with auto_extraction_jobs_lock:
            auto_extraction_jobs.pop(test_job_id, None)


if __name__ == "__main__":
    unittest.main()
