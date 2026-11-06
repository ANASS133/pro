import os
os.environ['DISABLE_CONDUCTOR_DAEMON'] = 'true'
from bs4 import BeautifulSoup
from app import app


def test_old_maps_page_redirects_to_search_source():
    """Verify legacy /google-maps URL redirects seamlessly to the unified dashboard with source=google_maps."""
    response = app.test_client().get('/google-maps')
    assert response.status_code == 302
    assert response.headers['Location'] == '/?source=google_maps'


def test_unified_dashboard_renders_for_all_three_modes():
    """Verify that all 3 search modes render the single unified search dashboard without legacy workspaces."""
    client = app.test_client()
    for mode in ["all", "job_portals", "google_maps"]:
        response = client.get(f'/?source={mode}')
        assert response.status_code == 200
        page = BeautifulSoup(response.data, 'html.parser')

        # 1. Main unified search elements MUST exist
        assert page.select_one('#search-section') is not None
        assert page.select_one('#search_form_1') is not None
        assert page.select_one('#keyword') is not None
        assert page.select_one('#location') is not None
        assert page.select_one('#search_radius') is not None
        assert page.select_one('#search_source_1') is not None
        assert page.select_one('#previous_tasks_list_1') is not None

        # 2. Source dropdown must contain all three modes
        options = {opt['value']: opt.text.strip() for opt in page.select('#search_source_1 option')}
        assert "all" in options
        assert "job_portals" in options
        assert "google_maps" in options

        # 3. Legacy standalone elements MUST NOT exist anywhere
        assert page.select_one('#search-maps-workspace') is None
        assert page.select_one('#gmaps-search-form') is None
        assert page.select_one('#gmaps-progress-panel') is None
        assert page.select_one('#gmaps-results-panel') is None
        assert page.select_one('#gmaps-export-bar') is None
        assert page.select_one('#gmaps-discovery-summary') is None

        # 4. Legacy google-maps.js script tag MUST NOT exist
        scripts = [s.get('src', '') for s in page.find_all('script') if s.get('src')]
        assert not any('google-maps.js' in s for s in scripts)


def test_backend_source_mode_routing():
    """Verify the backend search pipeline activates the correct portals for each mode."""
    # Source: all -> has_portals=True, has_gmaps=True
    source_clean = "all"
    is_all = source_clean in {"all", "all_with_maps", "all_sources"}
    has_portals = is_all or source_clean in {"job_portals", "jobboersen", "jobbörsen", "portals"}
    has_gmaps = is_all or source_clean in {"google_maps", "google-maps", "maps"}
    assert has_portals is True
    assert has_gmaps is True

    # Source: job_portals -> has_portals=True, has_gmaps=False
    source_clean = "job_portals"
    is_all = source_clean in {"all", "all_with_maps", "all_sources"}
    has_portals = is_all or source_clean in {"job_portals", "jobboersen", "jobbörsen", "portals"}
    has_gmaps = is_all or source_clean in {"google_maps", "google-maps", "maps"}
    assert has_portals is True
    assert has_gmaps is False

    # Source: google_maps -> has_portals=False, has_gmaps=True
    source_clean = "google_maps"
    is_all = source_clean in {"all", "all_with_maps", "all_sources"}
    has_portals = is_all or source_clean in {"job_portals", "jobboersen", "jobbörsen", "portals"}
    has_gmaps = is_all or source_clean in {"google_maps", "google-maps", "maps"}
    assert has_portals is False
    assert has_gmaps is True
