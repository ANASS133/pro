import unittest
from unittest.mock import patch, MagicMock
from pdf_generator.services.ats_service import (
    load_candidate_profile_bullets,
    tailor_ats_keywords,
    _get_cache_key,
    _load_cache
)
import app as flask_app


class TestATSService(unittest.TestCase):
    def test_load_candidate_bullets(self):
        bullets = load_candidate_profile_bullets('anass_sibbi')
        self.assertIsInstance(bullets, list)
        self.assertGreater(len(bullets), 0)

    def test_cache_key_generation(self):
        key1 = _get_cache_key("Stelle", "Firma", "Req", "Bullets")
        key2 = _get_cache_key("stelle ", " FIRMA", "req", "bullets ")
        self.assertEqual(key1, key2)

    def test_tailor_ats_keywords_cache_hit(self):
        # We already cached Siemens AG test earlier, verify it hits cache
        result = tailor_ats_keywords(
            job_title='Fachinformatiker Anwendungsentwicklung',
            company_name='Siemens AG',
            job_requirements='Python, REST-APIs, relationale Datenbanken, Docker'
        )
        self.assertTrue(result.get('success'))
        self.assertTrue(result.get('from_cache'))
        self.assertEqual(result.get('usage', {}).get('estimated_cost_usd'), 0.0)

    def test_api_route(self):
        client = flask_app.app.test_client()
        resp = client.post('/api/pdf/ats-tailor', json={
            'job_title': 'Fachinformatiker Anwendungsentwicklung',
            'company_name': 'Siemens AG',
            'job_requirements': 'Python, REST-APIs, relationale Datenbanken, Docker'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('tailored_bullets', data)

    def test_golden_hook_route(self):
        client = flask_app.app.test_client()
        resp = client.post('/api/pdf/golden-hook', json={
            'company_name': 'Siemens AG',
            'job_title': 'Fachinformatiker'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('hook', data)
        self.assertGreater(len(data['hook']), 5)

    def test_culture_vibe_route(self):
        client = flask_app.app.test_client()
        resp = client.post('/api/pdf/culture-vibe', json={
            'company_name': 'Siemens AG',
            'job_title': 'Fachinformatiker'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('formality', data)
        self.assertIn('vibe', data)

    def test_ats_heatmap_route(self):
        client = flask_app.app.test_client()
        resp = client.post('/api/pdf/ats-heatmap', json={
            'company_name': 'Siemens AG',
            'job_title': 'Fachinformatiker',
            'requirements': 'Python, REST-APIs, Docker'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('match_percent', data)
        self.assertIn('matched', data)
        self.assertIn('bridge_tip', data)


if __name__ == '__main__':
    unittest.main()

