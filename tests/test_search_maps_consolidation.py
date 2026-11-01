import os
os.environ['DISABLE_CONDUCTOR_DAEMON'] = 'true'
from bs4 import BeautifulSoup
from app import app


def test_old_maps_page_redirects_to_search_source():
    response = app.test_client().get('/google-maps')
    assert response.status_code == 302
    assert response.headers['Location'] == '/?source=google_maps'


def test_maps_is_one_workspace_inside_search():
    response = app.test_client().get('/?source=google_maps')
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    assert not page.select('[data-section="google-maps"], [data-section-link="google-maps"]')
    assert len(page.select('#gmaps-search-form')) == 1
    assert page.select_one('#search-section #search-maps-workspace #gmaps-search-form')
    assert page.select_one('#search_source_1')['form'] == 'search_form_1'
    for control in ['gmaps-verify-toggle', 'gmaps-progress-panel', 'gmaps-results-panel']:
        assert page.select_one(f'#search-maps-workspace #{control}')
