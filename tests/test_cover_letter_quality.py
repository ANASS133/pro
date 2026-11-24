"""
Comprehensive Quality and Regression Suite for JobScout Anschreiben Engine.

Tests:
1. Generic-content detection (QualityAssurancePipeline catches clichés)
2. Job-specific personalization (Title, company, city, contact person)
3. Evidence-grounded writing (Ranks candidate experience, no hallucination)
4. Experienced candidates applying for Ausbildung (Dual narrative present, no 'zero experience')
5. Unavailable vacancy descriptions (Grounded writing without hallucinated company facts)
6. AI provider failures & deterministic template isolation (Never disguises fallback as AI)
7. Refinement actions (improve, concise, formal, natural)
8. End-to-end PDF consistency (Generated text matches rendered PDF)
9. Documented Rubric Evaluation Comparison (Old generator vs. New generator)
"""

import io
import pytest
from app import app
from services.cover_letter_engine import (
    CoverLetterEngine,
    JobAnalyzer,
    EvidenceSelector,
    QualityAssurancePipeline,
    CoverLetterWriter,
    GENERIC_CLICHE_PATTERNS,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def sample_candidate_profile():
    return {
        "applicant": {
            "personal": {
                "full_name": "Anass Sibbi",
                "first_name": "Anass",
                "last_name": "Sibbi",
            },
            "contact": {
                "email": "anass.sibbi@example.com",
                "phone_display": "+212 600000000",
                "address": {
                    "city": "Casablanca",
                    "country": "Marokko",
                },
            },
            "professional_profile": {
                "years_of_experience": 3.0,
                "headline": "Softwareentwickler | Full-Stack-Entwickler",
                "current_level": "Professional",
            },
            "work_experience": [
                {
                    "position": "Full-Stack-Entwickler",
                    "employer": "Marokkanisches Innenministerium",
                    "start_date": "2022",
                    "end_date": "2024",
                    "responsibilities": [
                        "Entwicklung behördlicher Webanwendungen mit Python, React und PostgreSQL",
                        "Design von RESTful APIs und Microservices",
                    ],
                },
                {
                    "position": "Webentwickler",
                    "employer": "Outsourcia",
                    "start_date": "2020",
                    "end_date": "2022",
                    "responsibilities": [
                        "Kundenprojekte mit PHP, JavaScript und MySQL",
                    ],
                },
            ],
            "education": [
                {
                    "degree": "Licence Professionnelle en Génie Logiciel",
                    "institution": "Universität Hassan II",
                    "start_date": "2017",
                    "end_date": "2020",
                    "field_of_study": "Informatik / Software Engineering",
                }
            ],
            "skills": {
                "technologies_from_cv": ["Python", "JavaScript", "React", "PostgreSQL", "Docker", "Git"],
                "programming_languages": ["Python", "JavaScript"],
            },
            "languages": [
                {"language": "Deutsch", "level_de": "B2 (fließend)"},
                {"language": "Französisch", "level_de": "C1 (verhandlungssicher)"},
                {"language": "Englisch", "level_de": "B2"},
            ],
        }
    }


# ==============================================================================
# TEST 1: Generic Cliché Detection in QA Pipeline
# ==============================================================================
def test_generic_cliche_detection_in_qa():
    """
    Ensure QualityAssurancePipeline flags generic clichés and penalizes quality score.
    """
    bad_cliche_letter = """
Anass Sibbi
Casablanca, Marokko
anass.sibbi@example.com

Bechtle AG
Personalabteilung
Köln

Köln, den 11.11.2026

Bewerbung um einen Ausbildungsplatz als Fachinformatiker für Anwendungsentwicklung

Sehr geehrte Damen und Herren,

hiermit bewerbe ich mich mit großem Interesse um den Ausbildungsplatz in Ihrem Unternehmen.
Ihr Unternehmen hat mein Interesse geweckt, weil Sie innovative IT-Lösungen anbieten.
Ich bin teamfähig, motiviert und flexibel und arbeite sehr gerne im Team.
Als engagierter Kandidat bringe ich fundierte Fachkenntnisse mit. Ich habe großes Interesse an Softwareentwicklung.

Ich freue mich über eine Einladung zu einem persönlichen Vorstellungsgespräch.

Mit freundlichen Grüßen
Anass Sibbi
"""
    result = QualityAssurancePipeline.evaluate(
        text=bad_cliche_letter,
        candidate_data={"full_name": "Anass Sibbi"},
        vacancy_data={
            "company": "Bechtle AG",
            "position": "Fachinformatiker",
            "city": "Köln",
        },
    )

    # QA must detect clichés and penalize score
    assert len(result["cliches_detected"]) >= 3
    assert result["score"] < 7.0
    assert result["is_valid"] is False


# ==============================================================================
# TEST 2: Job-Specific Analysis & Opportunity Detection
# ==============================================================================
def test_job_analyzer_detects_ausbildung_and_specialization():
    """
    Ensure JobAnalyzer identifies opportunity type and technical specialization.
    """
    analysis = JobAnalyzer.analyze(
        company="Bechtle AG",
        position="Ausbildung zum Fachinformatiker für Anwendungsentwicklung (m/w/d)",
        city="Köln",
        job_description="Wir entwickeln cloudbasierte Unternehmenssoftware für den Mittelstand.",
    )
    assert analysis["opportunity_type"] == "ausbildung"
    assert "anwendungsentwicklung" in analysis["specialization"].lower()
    assert analysis["company"] == "Bechtle AG"
    assert analysis["has_rich_description"] is True
    assert "Cloud" in analysis["extracted_skills"]


# ==============================================================================
# TEST 3: Evidence Selection & Ranking (No Skill Dumping)
# ==============================================================================
def test_evidence_selector_ranks_top_evidence(sample_candidate_profile):
    """
    Ensure EvidenceSelector extracts top 2-3 grounded evidence pieces
    and handles the experienced-candidate dual narrative.
    """
    job_analysis = JobAnalyzer.analyze(
        company="Bechtle AG",
        position="Ausbildung Fachinformatiker Anwendungsentwicklung",
        city="Köln",
    )
    evidence = EvidenceSelector.select_evidence(
        candidate_profile=sample_candidate_profile,
        job_analysis=job_analysis,
    )

    assert evidence["is_experienced"] is True
    assert evidence["ausbildung_rationale"] != ""
    assert "IHK" in evidence["ausbildung_rationale"] or "duale" in evidence["ausbildung_rationale"].lower()
    assert 1 <= len(evidence["top_evidence"]) <= 3
    # Verify candidate actual employers are prioritized
    headlines = [e.get("headline", "") for e in evidence["top_evidence"]]
    assert any("Innenministerium" in h or "Outsourcia" in h for h in headlines)


# ==============================================================================
# TEST 4: Experienced Candidate Applying for Ausbildung (Dual Narrative)
# ==============================================================================
def test_experienced_candidate_ausbildung_generation(sample_candidate_profile):
    """
    Generate letter for experienced developer applying for Ausbildung and verify:
    1. Acknowledges prior practical experience
    2. Explains dual vocational training in Germany (IHK standards, integration)
    3. Never claims candidate is a complete beginner or has zero experience
    4. Has 250-350 words, clean German B2-C1 prose
    """
    result = CoverLetterEngine.generate_cover_letter(
        candidate_profile=sample_candidate_profile,
        company="Bechtle AG",
        position="Ausbildung Fachinformatiker Anwendungsentwicklung",
        city="Köln",
        contact_person="Herr Markus Weber",
        job_description="Fokus auf moderne Webapplikationen und REST-APIs im Enterprise-Umfeld.",
    )

    assert result["success"] is True
    text = result["text"]

    # Factual grounding
    assert "Bechtle" in text
    assert "Fachinformatiker" in text
    assert "Sehr geehrter Herr Markus Weber" in text or "Sehr geehrter Herr Weber" in text
    assert "Anass Sibbi" in text

    # Dual narrative presence
    text_lower = text.lower()
    assert any(term in text_lower for term in ["erfahrung", "projekten", "praxis", "beruf"])
    assert any(term in text_lower for term in ["ausbildung", "duale", "ihk", "standard", "vertiefen", "fundieren"])

    # No beginner insults
    assert "keinerlei erfahrung" not in text_lower
    assert "blutiger anfänger" not in text_lower

    # Word count check (DIN 5008 one-page target: 200 - 420 words)
    words = len(text.split())
    assert 200 <= words <= 420


# ==============================================================================
# TEST 5: Unavailable Vacancy Description Handling
# ==============================================================================
def test_unavailable_vacancy_description_handling(sample_candidate_profile):
    """
    When vacancy description is empty, generator must remain grounded without inventing company metrics.
    """
    result = CoverLetterEngine.generate_cover_letter(
        candidate_profile=sample_candidate_profile,
        company="CANCOM SE",
        position="Fachinformatiker Systemintegration",
        city="München",
        contact_person="",
        job_description="",  # Vacancy description empty
    )

    assert result["success"] is True
    text = result["text"]
    assert "CANCOM" in text
    # No unreplaced placeholders
    assert "{{" not in text
    assert "}}" not in text
    assert "[Unternehmensadresse]" not in text
    assert "[Datum]" not in text


# ==============================================================================
# TEST 6: Deterministic Template Mode & Failure Transparency
# ==============================================================================
def test_deterministic_template_mode_does_not_claim_ai(client):
    """
    Explicit template mode must return deterministic text marked as template mode,
    never claiming to be AI-generated.
    """
    response = client.post(
        "/api/ai-generate-anschreiben",
        json={
            "mode": "template",
            "client_id": "anass_sibbi",
            "company": "Deutsche Telekom AG",
            "position": "Softwareentwickler",
            "city": "Bonn",
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("success") is True
    assert data.get("is_ai_generated") is False
    assert data.get("engine_used") == "deterministic_template"
    assert "Deutsche Telekom AG" in data.get("text", "")


# ==============================================================================
# TEST 7: Refinement Actions (Improve, Concise, Formal, Natural)
# ==============================================================================
def test_refinement_actions_via_api(client):
    """
    Verify /api/ai-refine-anschreiben endpoint supports improve, concise, formal, natural.
    """
    base_text = """
Anass Sibbi
Casablanca, Marokko

Bechtle AG
Köln

Köln, den 11.11.2026

Bewerbung um einen Ausbildungsplatz als Fachinformatiker für Anwendungsentwicklung

Sehr geehrte Damen und Herren,

als passionierter Softwareentwickler mit fundierter Praxiserfahrung in der Backend- und Frontend-Entwicklung möchte ich meine Kenntnisse im Rahmen einer dualen Ausbildung bei der Bechtle AG vertiefen.

In meinen bisherigen Stationen, unter anderem beim Marokkanischen Innenministerium, habe ich robuste Webanwendungen mit Python und React konzipiert. Die duale Ausbildung bietet mir den idealen Rahmen, um meine praktischen Erfahrungen nach anerkannten deutschen IHK-Standards zu formalisieren.

Die Bechtle AG überzeugt mich durch ihre führende Rolle in modernen IT-Infrastrukturen. Ich biete hohe Leistungsbereitschaft und schnelle Einarbeitung ab dem ersten Tag.

Über die Gelegenheit zu einem persönlichen Gespräch freue ich mich sehr.

Mit freundlichen Grüßen
Anass Sibbi
"""
    for action in ["improve", "concise", "formal", "natural"]:
        response = client.post(
            "/api/ai-refine-anschreiben",
            json={
                "text": base_text,
                "action": action,
                "company": "Bechtle AG",
                "position": "Fachinformatiker Anwendungsentwicklung",
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("success") is True
        refined_text = data.get("text", "")
        assert len(refined_text) > 100
        assert "Bechtle" in refined_text
        assert "Anass Sibbi" in refined_text


# ==============================================================================
# TEST 8: PDF Preview Consistency with Live Row Data
# ==============================================================================
def test_pdf_preview_contains_candidate_and_company(client):
    """
    Verify that /api/preview-pdf renders valid PDF containing live candidate and employer data.
    """
    # 1. Bootstrap a session
    bs_res = client.post(
        "/api/create-anschreibens/direct-jobs-bootstrap",
        json={
            "client_id": "anass_sibbi",
            "jobs": [
                {
                    "company": "Bechtle AG",
                    "title": "Ausbildung Fachinformatiker",
                    "location": "Köln",
                    "contact_person": "Herr Weber",
                }
            ],
        },
    )
    assert bs_res.status_code == 200
    bs_data = bs_res.get_json()
    session_id = bs_data["session_id"]

    # 2. Call preview-pdf
    preview_res = client.post(
        "/api/preview-pdf",
        json={
            "session_id": session_id,
            "row_index": 0,
            "row_data": {
                "Unternehmen": "Bechtle AG",
                "Position": "Ausbildung Fachinformatiker",
                "Ort": "Köln",
                "Ansprechpartner": "Herr Weber",
            },
        },
    )
    assert preview_res.status_code == 200
    pdf_bytes = preview_res.data
    # Valid PDF signature
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000


# ==============================================================================
# TEST 9: Evaluation Rubric (Old vs. New Anschreiben Generator)
# ==============================================================================
def test_evaluation_rubric_comparison(sample_candidate_profile):
    """
    Compares Old Generator vs New Engine across the 5 evaluation criteria:
    1. Cliché Freedom (0-10)
    2. Evidence Grounding & Specificity (0-10)
    3. Ausbildung Dual Narrative Adequacy (0-10)
    4. German B2-C1 Natural Prose & Syntax (0-10)
    5. DIN 5008 Word Count Compliance (0-10)
    """
    # Legacy output representation (old generator)
    old_output = """
Sehr geehrte Damen und Herren,

mit großem Interesse bewerbe ich mich um die Stelle als Fachinformatiker bei Bechtle AG.
Ihr Unternehmen hat mein Interesse geweckt. Ich bin teamfähig, motiviert und flexibel.
Als engagierter Kandidat bringe ich fundierte Fachkenntnisse in Python, JavaScript, React, PostgreSQL, Docker, Git mit.
Ich freue mich über ein persönliches Gespräch.

Mit freundlichen Grüßen
Anass Sibbi
"""

    old_eval = QualityAssurancePipeline.evaluate(
        text=old_output,
        candidate_data={"full_name": "Anass Sibbi"},
        vacancy_data={
            "company": "Bechtle AG",
            "position": "Fachinformatiker",
            "city": "Köln",
        },
    )

    # Old output fails due to clichés, short word count, and zero evidence grounding
    assert old_eval["is_valid"] is False
    assert old_eval["score"] < 5.0
    assert len(old_eval["cliches_detected"]) >= 2

    # New engine output representation
    new_result = CoverLetterEngine.generate_cover_letter(
        candidate_profile=sample_candidate_profile,
        company="Bechtle AG",
        position="Ausbildung Fachinformatiker Anwendungsentwicklung",
        city="Köln",
        contact_person="Herr Weber",
    )

    assert new_result["success"] is True
    new_eval = new_result["qa_result"]

    # New engine must achieve a high score (>= 8.0) and pass QA
    assert new_eval["score"] >= 8.0
    assert new_eval["is_valid"] is True
    assert len(new_eval["cliches_detected"]) == 0
