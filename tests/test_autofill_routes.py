import unittest
from app import app


class AutofillRoutesTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_autofill_page_route(self):
        response = self.client.get("/autofill")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("autofill-section", html)
        self.assertIn("Bewerberprofile", html)

    def test_autofill_profiles_api(self):
        # Test both /api/autofill/profiles and extension-compatible /api/profiles
        for path in ["/api/autofill/profiles", "/api/profiles"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn("profiles", data)
            self.assertIsInstance(data["profiles"], list)
            # anass_sibbi should be present
            ids = [p["id"] for p in data["profiles"]]
            self.assertIn("anass_sibbi", ids)

    def test_autofill_profile_detail_and_matching(self):
        detail_resp = self.client.get("/api/autofill/profiles/anass_sibbi")
        self.assertEqual(detail_resp.status_code, 200)
        profile = detail_resp.get_json()
        self.assertIn("applicant", profile)

        matching_resp = self.client.get("/api/autofill/profiles/anass_sibbi/matching-data")
        self.assertEqual(matching_resp.status_code, 200)
        matching = matching_resp.get_json()
        self.assertIn("applicant", matching)
        self.assertIn("documents", matching)
        self.assertIn("corrections", matching)

    def test_autofill_map_fields_fallback(self):
        sample_fields = [
            {"field_id": "first_name", "label": "Vorname", "type": "text"},
            {"field_id": "email", "label": "E-Mail-Adresse", "type": "email"},
            {"field_id": "city", "label": "Wohnort", "type": "text"}
        ]
        response = self.client.post(
            "/api/autofill/map-fields",
            json={
                "fields": sample_fields,
                "profileId": "anass_sibbi",
                "domain": "test.de"
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("actions", data)
        actions = data["actions"]
        self.assertTrue(len(actions) >= 2)
        field_ids = [a["field_id"] for a in actions]
        self.assertIn("first_name", field_ids)
        self.assertIn("email", field_ids)

    def test_autofill_log_and_get_applications(self):
        log_payload = {
            "title": "Senior Frontend Developer",
            "company": "Tech Corp",
            "domain": "techcorp.com",
            "profileId": "anass_sibbi",
            "fieldsFilled": 8,
            "date": "25.10.2026"
        }
        post_resp = self.client.post("/api/autofill/log-application", json=log_payload)
        self.assertEqual(post_resp.status_code, 200)
        post_data = post_resp.get_json()
        self.assertTrue(post_data.get("success"))

        get_resp = self.client.get("/api/autofill/applications")
        self.assertEqual(get_resp.status_code, 200)
        get_data = get_resp.get_json()
        self.assertIn("applications", get_data)
        apps = get_data["applications"]
        self.assertTrue(len(apps) >= 1)
        titles = [a.get("title") for a in apps]
        self.assertIn("Senior Frontend Developer", titles)

    def test_test_forms_served(self):
        resp_de = self.client.get("/test-form")
        self.assertEqual(resp_de.status_code, 200)
        self.assertIn("text/html", resp_de.content_type)

        resp_fr = self.client.get("/french-form")
        self.assertEqual(resp_fr.status_code, 200)
        self.assertIn("text/html", resp_fr.content_type)


if __name__ == "__main__":
    unittest.main()
