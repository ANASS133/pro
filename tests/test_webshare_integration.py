"""
Unit and Integration Tests for JobScout Webshare.io API Integration.

Tests:
1. Webshare API proxy fetching with distinct public IPs.
2. Credential masking (API keys, usernames, passwords never leaked).
3. 4-worker stable proxy assignment from Webshare API.
4. Priority of manual worker overrides (WORKER_{i}_PROXY) over Webshare pool.
5. Strict fail-closed semantics when WORKER_REQUIRE_PROXIES=true and fallback=false.
6. Handling of Webshare API authentication errors (401/403) and API failures.
7. Mode fallback (direct -> backbone) when direct mode returns no valid proxies.
8. Non-rotation guarantee on proxy failure.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
import requests

from services.worker_network_router import (
    WorkerNetworkProfile,
    load_worker_network_profiles,
    fetch_webshare_proxies,
    redact_api_key,
    redact_proxy_url,
    get_network_routing_summary,
    verify_worker_connection,
    apply_proxy_to_browser_options,
)


class TestWebshareIntegration(unittest.TestCase):

    def setUp(self):
        self.mock_webshare_response = {
            "count": 4,
            "next": None,
            "previous": None,
            "results": [
                {
                    "id": "ws-1",
                    "username": "user1",
                    "password": "secretpassword1",
                    "proxy_address": "185.100.1.10",
                    "port": 8000,
                    "valid": True,
                    "country_code": "DE",
                    "city_name": "Frankfurt",
                },
                {
                    "id": "ws-2",
                    "username": "user2",
                    "password": "secretpassword2",
                    "proxy_address": "185.100.2.20",
                    "port": 8000,
                    "valid": True,
                    "country_code": "FR",
                    "city_name": "Paris",
                },
                {
                    "id": "ws-3",
                    "username": "user3",
                    "password": "secretpassword3",
                    "proxy_address": "185.100.3.30",
                    "port": 8000,
                    "valid": True,
                    "country_code": "NL",
                    "city_name": "Amsterdam",
                },
                {
                    "id": "ws-4",
                    "username": "user4",
                    "password": "secretpassword4",
                    "proxy_address": "185.100.4.40",
                    "port": 8000,
                    "valid": True,
                    "country_code": "US",
                    "city_name": "New York",
                },
            ],
        }

    def test_api_key_and_credential_masking(self):
        """Webshare API keys and proxy credentials must be strictly redacted in logs and summaries."""
        secret_key = "abc123xyz987verysecrettoken"
        masked = redact_api_key(secret_key)
        self.assertNotIn("verysecrettoken", masked)
        self.assertEqual(masked, "abc1...en")

        short_key = "12345"
        self.assertEqual(redact_api_key(short_key), "***")
        self.assertEqual(redact_api_key(""), "<none>")
        self.assertEqual(redact_api_key(None), "<none>")

        raw_proxy = "http://webshare_user:super_secret_pass@185.100.1.10:8000"
        sanitized = redact_proxy_url(raw_proxy)
        self.assertNotIn("super_secret_pass", sanitized)
        self.assertNotIn("webshare_user", sanitized)
        self.assertIn("***:***", sanitized)
        self.assertIn("185.100.1.10:8000", sanitized)

    def test_fetch_webshare_proxies_success_distinct_ips(self):
        """fetch_webshare_proxies retrieves 4 distinct proxies with proper authentication headers."""
        mock_session = MagicMock(spec=requests.Session)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.mock_webshare_response
        mock_session.get.return_value = mock_resp

        proxies = fetch_webshare_proxies(
            api_key="valid-test-key",
            max_proxies=4,
            session=mock_session,
        )

        self.assertEqual(len(proxies), 4)

        # Verify distinct IP addresses
        ips = [p["proxy_address"] for p in proxies]
        self.assertEqual(len(set(ips)), 4)
        self.assertIn("185.100.1.10", ips)
        self.assertIn("185.100.4.40", ips)

        # Verify proxy URLs include credentials
        self.assertEqual(proxies[0]["proxy_url"], "http://user1:secretpassword1@185.100.1.10:8000")
        self.assertEqual(proxies[0]["profile_name"], "Webshare-1 (DE)")
        self.assertEqual(proxies[3]["profile_name"], "Webshare-4 (US)")

        # Verify request headers used Token authentication (Webshare API standard)
        args, kwargs = mock_session.get.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Token valid-test-key")

    def test_fetch_webshare_proxies_deduplication(self):
        """Duplicate proxy_address entries in API response are deduplicated to ensure distinct public IPs."""
        dup_response = {
            "count": 4,
            "results": [
                {"proxy_address": "185.100.1.10", "port": 8000, "username": "u1", "password": "p1", "valid": True},
                {"proxy_address": "185.100.1.10", "port": 8001, "username": "u2", "password": "p2", "valid": True},
                {"proxy_address": "185.100.2.20", "port": 8000, "username": "u3", "password": "p3", "valid": True},
            ],
        }
        mock_session = MagicMock(spec=requests.Session)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = dup_response
        mock_session.get.return_value = mock_resp

        proxies = fetch_webshare_proxies(
            api_key="valid-test-key",
            max_proxies=4,
            session=mock_session,
        )
        self.assertEqual(len(proxies), 2)
        self.assertEqual(proxies[0]["proxy_address"], "185.100.1.10")
        self.assertEqual(proxies[1]["proxy_address"], "185.100.2.20")

    def test_fetch_webshare_proxies_auth_error_handling(self):
        """HTTP 401/403 errors are handled gracefully without raising or leaking credentials."""
        mock_session = MagicMock(spec=requests.Session)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized - Invalid token"
        mock_session.get.return_value = mock_resp

        proxies = fetch_webshare_proxies(
            api_key="bad-token",
            session=mock_session,
        )
        self.assertEqual(proxies, [])

    def test_fetch_webshare_proxies_backbone_fallback(self):
        """If direct mode returns 0 proxies, fallback to backbone mode is attempted."""
        mock_session = MagicMock(spec=requests.Session)
        direct_resp = MagicMock(status_code=200)
        direct_resp.json.return_value = {"results": []}

        backbone_resp = MagicMock(status_code=200)
        backbone_resp.json.return_value = self.mock_webshare_response

        mock_session.get.side_effect = [direct_resp, backbone_resp]

        proxies = fetch_webshare_proxies(
            api_key="valid-token",
            max_proxies=4,
            session=mock_session,
        )
        self.assertEqual(len(proxies), 4)
        self.assertEqual(mock_session.get.call_count, 2)

    def test_load_worker_network_profiles_auto_provisioning(self):
        """load_worker_network_profiles auto-populates 4 worker profiles from Webshare API."""
        mock_session = MagicMock(spec=requests.Session)
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = self.mock_webshare_response
        mock_session.get.return_value = mock_resp

        config = {
            "WEBSHARE_API_KEY": "test-webshare-token-12345",
            "WORKER_REQUIRE_PROXIES": "true",
            "WORKER_ALLOW_DIRECT_FALLBACK": "false",
        }

        profiles = load_worker_network_profiles(
            config=config,
            max_workers=4,
            webshare_session=mock_session,
        )

        self.assertEqual(len(profiles), 4)
        for w_id in range(1, 5):
            prof = profiles[w_id]
            self.assertEqual(prof.worker_id, w_id)
            self.assertIn("Webshare", prof.profile_name)
            self.assertFalse(prof.allow_direct_fallback)
            self.assertEqual(prof.connection_status, "pending")
            self.assertIsNotNone(prof.proxy_url)
            # Ensure safe dict masks credentials
            d = prof.to_dict()
            self.assertNotIn("secretpassword", str(d))
            self.assertIn("***:***", d["proxy_display"])

        # Check summary indicates webshare_api mode
        summary = get_network_routing_summary(profiles)
        self.assertEqual(summary["active_mode"], "webshare_api")
        self.assertEqual(summary["configured_proxies"], 4)

    def test_load_worker_network_profiles_manual_override_priority(self):
        """Manual WORKER_{i}_PROXY overrides Webshare auto-provisioning for that specific worker."""
        mock_session = MagicMock(spec=requests.Session)
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = self.mock_webshare_response
        mock_session.get.return_value = mock_resp

        config = {
            "WEBSHARE_API_KEY": "test-webshare-token-12345",
            "WORKER_2_PROXY": "socks5://custom_user:custom_pass@203.0.113.88:1080",
            "WORKER_2_NAME": "Manual-Dedicated-2",
            "WORKER_REQUIRE_PROXIES": "true",
            "WORKER_ALLOW_DIRECT_FALLBACK": "false",
        }

        profiles = load_worker_network_profiles(
            config=config,
            max_workers=4,
            webshare_session=mock_session,
        )

        self.assertEqual(len(profiles), 4)
        # Worker 1 gets Webshare
        self.assertEqual(profiles[1].profile_name, "Webshare-1 (DE)")
        # Worker 2 gets manual override
        self.assertEqual(profiles[2].profile_name, "Manual-Dedicated-2")
        self.assertEqual(profiles[2].protocol, "socks5")
        self.assertIn("203.0.113.88:1080", profiles[2].proxy_url)
        # Worker 3 and 4 get Webshare
        self.assertEqual(profiles[3].profile_name, "Webshare-3 (NL)")
        self.assertEqual(profiles[4].profile_name, "Webshare-4 (US)")

    def test_fail_closed_when_webshare_fails_and_proxies_required(self):
        """If Webshare API fails and WORKER_REQUIRE_PROXIES=true, workers fail-closed rather than leaking direct IP."""
        mock_session = MagicMock(spec=requests.Session)
        mock_resp = MagicMock(status_code=401)
        mock_session.get.return_value = mock_resp

        config = {
            "WEBSHARE_API_KEY": "invalid-token",
            "WORKER_REQUIRE_PROXIES": "true",
            "WORKER_ALLOW_DIRECT_FALLBACK": "false",
        }

        profiles = load_worker_network_profiles(
            config=config,
            max_workers=4,
            webshare_session=mock_session,
        )

        self.assertEqual(len(profiles), 4)
        for w_id in range(1, 5):
            prof = profiles[w_id]
            self.assertEqual(prof.connection_status, "failed")
            self.assertEqual(prof.public_ip, "Route Failed (Fail-Closed)")
            self.assertFalse(prof.allow_direct_fallback)
            self.assertIn("Webshare", prof.error_message)

    def test_verification_success_stores_distinct_public_ips(self):
        """verify_worker_connection sets connection_status='connected' and stores the verified public IP."""
        profile = WorkerNetworkProfile(
            worker_id=1,
            profile_name="Webshare-1 (DE)",
            proxy_url="http://user1:pass1@185.100.1.10:8000",
            protocol="http",
            allow_direct_fallback=False,
        )

        mock_session = MagicMock()
        mock_session.proxies = {}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ip": "185.100.1.10"}
        mock_session.get.return_value = mock_resp

        ok, ip, err = verify_worker_connection(profile, session=mock_session)
        self.assertTrue(ok)
        self.assertEqual(ip, "185.100.1.10")
        self.assertEqual(profile.connection_status, "connected")
        self.assertEqual(profile.public_ip, "185.100.1.10")
        self.assertIsNone(err)

    def test_verification_failure_enforces_fail_closed_no_rotation(self):
        """When a proxy route fails verification, fail-closed is strictly enforced without proxy rotation."""
        profile = WorkerNetworkProfile(
            worker_id=1,
            profile_name="Webshare-1 (DE)",
            proxy_url="http://user1:pass1@185.100.1.10:8000",
            protocol="http",
            allow_direct_fallback=False,
        )

        mock_session = MagicMock()
        mock_session.proxies = {}
        mock_session.get.side_effect = requests.exceptions.ConnectTimeout("Proxy gateway connection timed out")

        ok, ip, err = verify_worker_connection(profile, session=mock_session)
        self.assertFalse(ok)
        self.assertEqual(ip, "")
        self.assertEqual(profile.connection_status, "failed")
        self.assertEqual(profile.public_ip, "Route Failed (Fail-Closed)")
        self.assertIn("Fail-closed enforced", err)
        # Verify proxy_url was NOT replaced or rotated
        self.assertEqual(profile.proxy_url, "http://user1:pass1@185.100.1.10:8000")

    def test_selenium_browser_options_applied_for_webshare_worker(self):
        """Selenium browser options receive the authenticated proxy configuration for Webshare profiles."""
        profile = WorkerNetworkProfile(
            worker_id=1,
            profile_name="Webshare-1 (DE)",
            proxy_url="http://user1:secretpass@185.100.1.10:8000",
            protocol="http",
        )

        mock_options = MagicMock()
        apply_proxy_to_browser_options(mock_options, profile)

        # Either add_extension (auth extension zip) or add_argument is called
        has_extension_call = mock_options.add_extension.called
        has_argument_call = mock_options.add_argument.called
        self.assertTrue(has_extension_call or has_argument_call)


if __name__ == "__main__":
    unittest.main()
