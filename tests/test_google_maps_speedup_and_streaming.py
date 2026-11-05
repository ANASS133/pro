import time
from unittest.mock import MagicMock, patch

import pytest

from scraper.google_maps_ausbildung_verifier import GoogleMapsAusbildungVerifier
from scraper.overpass_scraper import OverpassBusinessScraper


# ---------------------------------------------------------------------------
# Priority 1: Consolidate Overpass Queries
# ---------------------------------------------------------------------------

def test_overpass_consolidated_query_generation():
    scraper = OverpassBusinessScraper()
    query = scraper.build_query(
        city="Berlin",
        categories=["handwerk", "it", "office"],
        limit=15,
    )

    assert "[out:json]" in query
    assert 'area["name"="Berlin"]' in query
    # Tags from handwerk and it should be present in a single query union
    assert "node['craft']" in query
    assert "node['office'='it']" in query or "node['office']" in query
    assert "out body 15;" in query


def test_overpass_search_businesses_passes_categories():
    scraper = OverpassBusinessScraper()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "elements": [
            {
                "tags": {
                    "name": "Bau & IT Partner GmbH",
                    "website": "https://bau-it-berlin.de",
                }
            }
        ]
    }

    with patch.object(scraper.session, "post", return_value=mock_resp) as mock_post:
        results = scraper.search_businesses(
            city="Berlin",
            categories=["Bauunternehmen", "Ingenieurbüros"],
            limit=15,
        )

        assert len(results) == 1
        assert results[0]["name"] == "Bau & IT Partner GmbH"
        assert results[0]["website"] == "https://bau-it-berlin.de"

        # Verify only 1 HTTP request was made to Overpass
        assert mock_post.call_count == 1
        post_data = mock_post.call_args[1].get("data", {}).get("data", "")
        assert 'area["name"="Berlin"]' in post_data


# ---------------------------------------------------------------------------
# Priority 4: Fast HTTP Verification & Lower Connect Timeout
# ---------------------------------------------------------------------------

def test_verifier_lowered_socket_timeout():
    verifier = GoogleMapsAusbildungVerifier()
    # Default socket timeout lowered from 10 to 6
    assert verifier.timeout <= 6

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><h1>Tech Ausbildung</h1><p>Wir bilden aus: Koch</p></body></html>"

    with patch.object(verifier.session, "get", return_value=mock_resp) as mock_get:
        verifier._fetch_page("https://example.com")
        assert mock_get.call_count == 1
        # Timeout passed as tuple (connect_timeout <= 3.5, read_timeout <= 6.0)
        timeout_arg = mock_get.call_args[1]["timeout"]
        assert isinstance(timeout_arg, tuple)
        assert timeout_arg[0] <= 3.5
        assert timeout_arg[1] <= 6.0


def test_verifier_skips_deep_form_discovery_during_search():
    verifier = GoogleMapsAusbildungVerifier()

    biz = {
        "name": "Testbetrieb GmbH",
        "website": "https://testbetrieb-gmbh.de",
    }

    homepage_html = "<html><body><h1>Karriere</h1><p>Ausbildung zum Koch bei uns!</p></body></html>"

    with patch.object(verifier, "_fetch_page", return_value=homepage_html), \
         patch.object(verifier, "discover_career_links", return_value=[]), \
         patch.object(verifier, "extract_emails_from_html", return_value=[]), \
         patch.object(verifier.form_discovery, "discover_application_form") as mock_discover:

        # In fast search mode, deep_form_discovery=False
        res = verifier.verify_business(biz, profession_keyword="Koch", deep_form_discovery=False)

        assert res.get("is_verified_vacancy") is True
        assert res.get("has_form") is False
        assert res.get("bewerbung_link") == "https://testbetrieb-gmbh.de"
        # Deep form crawler was NOT called during fast search
        mock_discover.assert_not_called()

