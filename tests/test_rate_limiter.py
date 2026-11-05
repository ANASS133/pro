import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper.rate_limiter import (
    DomainCircuitBreaker,
    apply_micro_jitter,
    extract_domain,
    get_rotated_browser_headers,
    parse_retry_after,
    safe_http_get,
)


def test_extract_domain():
    assert extract_domain("https://www.arbeitsagentur.de/jobsuche/jobdetail/123") == "arbeitsagentur.de"
    assert extract_domain("http://jobs.company.com:8080/careers") == "jobs.company.com"
    assert extract_domain("invalid-url") == "unknown"


def test_parse_retry_after():
    # Direct integer / float seconds
    assert parse_retry_after("15") == 15.0
    assert parse_retry_after("0.2") == 0.5  # Clamped to minimum 0.5
    assert parse_retry_after("120", max_wait=30.0) == 30.0  # Clamped to max_wait

    # Missing or invalid header falls back to default
    assert parse_retry_after(None, default_wait=4.5) == 4.5
    assert parse_retry_after("invalid_header", default_wait=3.0) == 3.0


# ---------------------------------------------------------------------------
# Idea A: Honor Retry-After & Exponential Jitter Backoff
# ---------------------------------------------------------------------------

def test_idea_a_honors_retry_after_and_retries():
    mock_session = MagicMock(spec=requests.Session)

    res_429 = MagicMock(spec=requests.Response)
    res_429.status_code = 429
    res_429.headers = {"Retry-After": "1"}

    res_200 = MagicMock(spec=requests.Response)
    res_200.status_code = 200
    res_200.text = "<html>Success</html>"
    res_200.headers = {"Content-Type": "text/html"}

    mock_session.get.side_effect = [res_429, res_200]

    with patch("time.sleep") as mock_sleep:
        cb = DomainCircuitBreaker(default_cooldown_seconds=60.0)
        resp = safe_http_get(
            mock_session,
            "https://test-company.de/jobs",
            retries=1,
            circuit_breaker=cb,
            apply_jitter=False,
            min_domain_interval=0.0,
        )

        assert resp is not None
        assert resp.status_code == 200
        # sleep must be called with Retry-After parsed value (1.0)
        assert mock_sleep.call_count >= 1
        assert any(1.0 <= call.args[0] <= 2.0 for call in mock_sleep.call_args_list if call.args)


def test_idea_a_exponential_jitter_backoff_when_no_retry_after():
    mock_session = MagicMock(spec=requests.Session)

    res_429 = MagicMock(spec=requests.Response)
    res_429.status_code = 429
    res_429.headers = {}  # No Retry-After header

    res_200 = MagicMock(spec=requests.Response)
    res_200.status_code = 200
    res_200.text = "OK"

    mock_session.get.side_effect = [res_429, res_200]

    with patch("time.sleep") as mock_sleep:
        cb = DomainCircuitBreaker(default_cooldown_seconds=60.0)
        resp = safe_http_get(
            mock_session,
            "https://another-domain.de/career",
            retries=1,
            circuit_breaker=cb,
            apply_jitter=False,
            min_domain_interval=0.0,
        )

        assert resp.status_code == 200
        # Backoff for attempt 0 is 2^0 + [0.5, 1.5] -> between 1.5 and 2.5
        slept_times = [call.args[0] for call in mock_sleep.call_args_list if call.args]
        assert any(1.5 <= t <= 2.6 for t in slept_times)


# ---------------------------------------------------------------------------
# Idea B: Domain Circuit Breaker & Cooldown
# ---------------------------------------------------------------------------

def test_idea_b_circuit_breaker_tripped_on_persistent_429():
    mock_session = MagicMock(spec=requests.Session)

    res_429 = MagicMock(spec=requests.Response)
    res_429.status_code = 429
    res_429.headers = {"Retry-After": "60"}

    mock_session.get.return_value = res_429

    cb = DomainCircuitBreaker(default_cooldown_seconds=60.0)

    with patch("time.sleep"):
        resp = safe_http_get(
            mock_session,
            "https://rate-limited-host.de/stellen",
            retries=1,
            circuit_breaker=cb,
            apply_jitter=False,
            min_domain_interval=0.0,
        )

        assert resp.status_code == 429
        # Domain should now be in cooldown!
        is_cooling, remaining = cb.is_cooling_down("rate-limited-host.de")
        assert is_cooling is True
        assert remaining > 0

        # Next request to rate-limited-host.de should be skipped immediately (resp is None)
        mock_session.get.reset_mock()
        skipped_resp = safe_http_get(
            mock_session,
            "https://rate-limited-host.de/another-job",
            circuit_breaker=cb,
        )
        assert skipped_resp is None
        mock_session.get.assert_not_called()

        # But request to a different domain should still proceed!
        res_ok = MagicMock(spec=requests.Response)
        res_ok.status_code = 200
        mock_session.get.return_value = res_ok

        different_resp = safe_http_get(
            mock_session,
            "https://completely-different-domain.de/job",
            circuit_breaker=cb,
            apply_jitter=False,
            min_domain_interval=0.0,
        )
        assert different_resp is not None
        assert different_resp.status_code == 200


# ---------------------------------------------------------------------------
# Idea C: Request Jitter & Concurrency Throttling
# ---------------------------------------------------------------------------

def test_idea_c_micro_jitter():
    with patch("time.sleep") as mock_sleep:
        jitter = apply_micro_jitter(0.2, 0.5)
        assert 0.2 <= jitter <= 0.5
        mock_sleep.assert_called_once_with(jitter)


def test_idea_c_domain_throttle():
    cb = DomainCircuitBreaker()
    with patch("time.sleep") as mock_sleep:
        # First call sets the timestamp
        cb.throttle_domain("test.de", min_interval_seconds=0.5)
        # Immediate second call should sleep to fulfill the minimum 0.5s interval
        cb.throttle_domain("test.de", min_interval_seconds=0.5)
        assert mock_sleep.call_count >= 1


# ---------------------------------------------------------------------------
# Idea D: User-Agent & Browser Header Rotation
# ---------------------------------------------------------------------------

def test_idea_d_browser_header_rotation():
    headers1 = get_rotated_browser_headers()
    assert "User-Agent" in headers1
    assert "Mozilla/5.0" in headers1["User-Agent"]
    assert "Sec-Ch-Ua" in headers1
    assert "Sec-Ch-Ua-Platform" in headers1
    assert "Accept-Language" in headers1
    assert "de" in headers1["Accept-Language"]

    # Verify that rotated headers include client hints
    assert headers1["Sec-Fetch-Mode"] == "navigate"
    assert headers1["Upgrade-Insecure-Requests"] == "1"

