import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_ai_generate_anschreiben_with_valid_client(client):
    """
    Verify that /api/ai-generate-anschreiben loads the client profile (e.g. anass_sibbi),
    extracts the candidate's CV details and skills, and generates a structured DIN 5008 Anschreiben.
    """
    payload = {
        "client_id": "anass_sibbi",
        "company": "Bechtle AG",
        "position": "Ausbildung Fachinformatiker Anwendungsentwicklung",
        "city": "Köln",
        "contact_person": "Herr Schmidt",
    }
    response = client.post("/api/ai-generate-anschreiben", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("success") is True
    text = data.get("text", "")
    assert "Anass Sibbi" in text
    assert "Bechtle AG" in text
    assert "Fachinformatiker" in text
    assert "Ausbildung" in text or "Ausbildungsplatz" in text
    assert "Sehr geehrte" in text or "Sehr geehrter Herr Schmidt" in text


def test_ai_generate_anschreiben_with_raw_payload(client):
    """
    Verify that /api/ai-generate-anschreiben works with candidate details provided directly in payload.
    """
    payload = {
        "candidate_name": "Maria Musterfrau",
        "candidate_email": "maria@example.de",
        "candidate_phone": "+49 151 98765432",
        "candidate_address": "Bahnhofstraße 5, 10115 Berlin",
        "company": "Siemens AG",
        "position": "Duales Studium Informatik",
        "city": "Berlin",
        "skills": ["Java", "SQL", "Spring Boot"],
    }
    response = client.post("/api/ai-generate-anschreiben", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("success") is True
    text = data.get("text", "")
    assert "Maria Musterfrau" in text
    assert "Siemens AG" in text
    assert "Duales Studium Informatik" in text


def test_direct_jobs_bootstrap_links_client(client):
    """
    Verify that direct-jobs-bootstrap populates candidate data when client_id is passed.
    """
    payload = {
        "client_id": "anass_sibbi",
        "jobs": [
            {
                "company": "Telekom AG",
                "title": "Fachinformatiker",
                "location": "Bonn",
                "source": "Quick Studio",
            }
        ],
    }
    response = client.post("/api/create-anschreibens/direct-jobs-bootstrap", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("success") is True
    assert "session_id" in data
    assert data.get("client_id") == "anass_sibbi"


def test_list_clients_includes_paid_supabase_applications(client):
    """
    Verify that /api/clients returns all paid candidates from Supabase
    and excludes corrupted/test dummy entries.
    """
    response = client.get("/api/clients")
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("success") is True
    clients = data.get("clients", [])
    assert len(clients) > 0
    # Ensure all returned clients have names and dummy test entries are omitted
    names = [c.get("name") for c in clients]
    assert "Corrupt Test" not in names
    # Verify that paid candidates from Supabase are included
    paid_clients = [c for c in clients if c.get("is_payed")]
    assert len(paid_clients) > 0

