"""
JobScout Data Extraction Quality & Regression Test Suite.

Covers:
1. Issue 1: Job Listing URLs (preservation of original vacancy URLs, rejection of advice pages).
2. Issue 2: Phone number validation (rejection of fragments, coordinates, dates, formatting valid German numbers).
3. Issue 3: Recruiter name sanitization (address & street stripping, rejection of generic departments and phrases).
4. Issue 4: Application form links (rejection of generic portal roots like jobs.hogapage.de, mailto correction).
5. Dataset Regression: Full verification against 20261106_122314_ausbildung_als_koch_68beff3b.xlsx (255 rows).
"""

from pathlib import Path
import pytest
import pandas as pd

from services.data_validator import (
    validate_job_listing_url,
    validate_phone_number,
    sanitize_contact_person,
    validate_application_url,
    validate_form_link,
    is_advice_or_generic_page,
)
from scraper.application_form_discovery import normalize_job_opportunity_row
from scraper.arbeitsagentur_extractor import detect_ats_or_url_type, normalize_phone_number
from scraper.parallel_domain_engine import normalize_domain_url


# =============================================================================
# 1. ISSUE 1: JOB LISTING URLS
# =============================================================================
class TestJobListingUrlValidation:
    """Tests for authentic job listing URL preservation and rejection of advice pages."""

    @pytest.mark.parametrize(
        "advice_url",
        [
            "https://www.ausbildung.de/ratgeber/bewerbung/",
            "https://ausbildung.de/ratgeber/bewerbung/lebenslauf/",
            "https://www.azubiyo.de/bewerbung/",
            "https://azubiyo.de/bewerbung/anschreiben/",
            "https://www.aubi-plus.de/bewerbung/",
            "https://aubi-plus.de/bewerbung/tipps/",
            "https://www.arbeitsagentur.de/ratgeber/bewerbung",
            "https://example.com/karriere-ratgeber/",
            "https://example.com/bewerbungstipps/",
        ],
    )
    def test_rejects_advice_pages(self, advice_url: str):
        assert is_advice_or_generic_page(advice_url) is True
        is_valid, cleaned, err = validate_job_listing_url(advice_url)
        assert is_valid is False
        assert cleaned == ""

    def test_falls_back_to_original_portal_url(self):
        advice = "https://www.ausbildung.de/ratgeber/bewerbung/"
        original = "https://www.ausbildung.de/berufe/koch/stellen/12345/"
        is_valid, cleaned, _ = validate_job_listing_url(advice, original_portal_url=original)
        assert is_valid is True
        assert cleaned == original

    @pytest.mark.parametrize(
        "valid_url",
        [
            "https://www.ausbildung.de/berufe/koch/stellen/12345/",
            "https://www.azubiyo.de/stellenanzeigen/koch-in-berlin/98765/",
            "https://www.aubi-plus.de/ausbildung/koch-koechin-112233/",
            "https://www.arbeitsagentur.de/jobsuche/jobdetail/12518-LX60BA-9K0-S",
            "https://jobboerse.arbeitsagentur.de/vamJB/bewerbungVerwalten.html?steaRefnr=10001-1003799465-S",
        ],
    )
    def test_accepts_valid_vacancy_urls(self, valid_url: str):
        is_valid, cleaned, _ = validate_job_listing_url(valid_url)
        assert is_valid is True
        assert cleaned == valid_url


# =============================================================================
# 2. ISSUE 2: PHONE NUMBER VALIDATION
# =============================================================================
class TestPhoneNumberValidation:
    """Tests for rejection of numerical noise and standardized German phone parsing."""

    @pytest.mark.parametrize(
        "corrupted_phone",
        [
            "026",
            "000",
            "027",
            "043",
            "027\n70174",
            "027\n4",
            "027\n20537",
            "05859 7.75 3.5 6.19141 3",
            "+491082027",
            "+491022027",
            "022-2025",
            "01.09.2027",
            "01.08.2027",
            "0000-12075517",
            "0001-10033733",
            "017160000000000000000",
        ],
    )
    def test_rejects_corrupted_phone_numbers(self, corrupted_phone: str):
        is_valid, cleaned, err = validate_phone_number(corrupted_phone)
        assert is_valid is False
        assert cleaned == ""

    @pytest.mark.parametrize(
        "raw_phone, expected_prefix",
        [
            ("+49 1522 1887849", "+4915221887849"),
            ("089 / 1234 5678", "+498912345678"),
            ("0711 12345-67", "+497111234567"),
            ("+49 (0) 30 1234567", "+49301234567"),
            ("+49 4381 9008-0", "+49438190080"),
            ("02223 29699", "+49222329699"),
            ("05772 49345", "+49577249345"),
        ],
    )
    def test_formats_valid_german_numbers(self, raw_phone: str, expected_prefix: str):
        is_valid, cleaned, err = validate_phone_number(raw_phone)
        assert is_valid is True
        assert cleaned == expected_prefix

    def test_empty_phone_returns_empty_string(self):
        is_valid, cleaned, _ = validate_phone_number(None)
        assert is_valid is False
        assert cleaned == ""
        assert normalize_phone_number("026") == ""


# =============================================================================
# 3. ISSUE 3: RECRUITER / CONTACT PERSON SANITIZATION
# =============================================================================
class TestContactPersonSanitization:
    """Tests for address and street stripping from recruiter names."""

    @pytest.mark.parametrize(
        "raw_name, expected_name",
        [
            ("frau simone annemarie biskupek hans-vogel-straße", "Frau Simone Annemarie Biskupek"),
            ("Frau Fischer\nGartenweg", "Frau Fischer"),
            ("herr nils jablonski overather str", "Herr Nils Jablonski"),
            ("frau ilona gorgis kirchheimer str", "Frau Ilona Gorgis"),
            ("herr sirko schönbeck fontanestr", "Herr Sirko Schönbeck"),
            ("frau renata spanic europastr", "Frau Renata Spanic"),
            ("herr rolf josef thelen neustr", "Herr Rolf Josef Thelen"),
            ("frau cornelia rist-martius zielow seeufer", "Frau Cornelia Rist-Martius"),
            ("frau sabine scheichenzuber kleblmühle kleblmühle", "Frau Sabine Scheichenzuber"),
            ("ist: Herr Guiseppe Sansone.", "Herr Guiseppe Sansone"),
            ("ist Frau Sandra Schwarz.", "Frau Sandra Schwarz"),
            ("herr volker wehmeier unter der", "Herr Volker Wehmeier"),
            ("frau yvonne hohaus e-mail anzeigen", "Frau Yvonne Hohaus"),
            ("Frau Eller\nHohensyburgstr", "Frau Eller"),
            ("Herr Brandt\nSchäferberg", "Herr Brandt"),
            ("Herr Hofmann\nLindow", "Herr Hofmann"),
            ("Herr Speerschneider\nIm", "Herr Speerschneider"),
            ("Herr Schelle\nZossen", "Herr Schelle"),
            ("ist: Hoteldirektor Thomas Varwig, Telefon: 04381/9008-0", "Hoteldirektor Thomas Varwig"),
            ("Frau Dr. Julia Meyer", "Frau Dr. Julia Meyer"),
            ("Thomas Schulz", "Thomas Schulz"),
        ],
    )
    def test_strips_addresses_and_normalizes_casing(self, raw_name: str, expected_name: str):
        is_valid, cleaned, _ = sanitize_contact_person(raw_name)
        assert is_valid is True
        assert cleaned == expected_name

    @pytest.mark.parametrize(
        "invalid_phrase",
        [
            "frau für restaurants und veranstaltungsgastronomie",
            "frau für restaurants- und veranstaltungsgastronomie",
            "Personalabteilung",
            "Bewerbermanagement",
            "während deiner Ausbildung",
            "für die gesamte Ausbildungszeit | Corporate Benefits | Arbeitskleidung wird gest",
            "und Ausbilder, die sie unterstützen und fördern",
            "nan",
            "None",
            "",
        ],
    )
    def test_rejects_generic_departments_and_non_names(self, invalid_phrase: str):
        is_valid, cleaned, _ = sanitize_contact_person(invalid_phrase)
        assert is_valid is False
        assert cleaned == ""


# =============================================================================
# 4. ISSUE 4: APPLICATION FORM LINKS & MAILTO CORRECTION
# =============================================================================
class TestApplicationFormLinkValidation:
    """Tests for rejecting generic portal roots and correcting mailto links."""

    def test_rejects_jobs_hogapage_as_verified_form(self):
        url_type, has_form = detect_ats_or_url_type("https://jobs.hogapage.de")
        assert has_form is False
        assert url_type in ("career_portal", "external_link")

        is_valid, cleaned, _ = validate_form_link("https://jobs.hogapage.de", has_form=True)
        assert is_valid is False
        assert cleaned == ""

    def test_corrects_malformed_mailto_link(self):
        bad_url = "https://mailto:bewerbung@landhotel.de"
        is_valid, cleaned, _ = validate_application_url(bad_url)
        assert is_valid is False
        assert cleaned == ""

        # Test normalize_domain_url does not prefix https:// to mailto
        root_dom, root_url = normalize_domain_url("mailto:bewerbung@landhotel.de")
        assert root_url == ""
        assert root_dom == ""

    def test_accepts_verified_ats_form_link(self):
        personio_url = "https://example.jobs.personio.de/job/12345"
        is_valid, cleaned, _ = validate_form_link(personio_url, has_form=True)
        assert is_valid is True
        assert cleaned == personio_url


# =============================================================================
# 5. DATASET REGRESSION TEST (255-ROW KOCH DATASET)
# =============================================================================
class TestDatasetQualityRegression:
    """Verifies that all 4 issues are permanently fixed on the actual exported dataset."""

    DATASET_PATH = Path("data/auto_extraction_exports/20261106_122314_ausbildung_als_koch_68beff3b.xlsx")

    @pytest.fixture
    def dataset_rows(self):
        assert self.DATASET_PATH.exists(), f"Dataset file not found: {self.DATASET_PATH}"
        df = pd.read_excel(self.DATASET_PATH)
        return [row.to_dict() for _, row in df.iterrows()]

    def test_all_rows_normalized_cleanly(self, dataset_rows):
        cleaned_rows = [normalize_job_opportunity_row(r) for r in dataset_rows]
        assert len(cleaned_rows) == 255

        # 1. Zero advice URLs in job_listing_url
        advice_urls = [
            r["job_listing_url"]
            for r in cleaned_rows
            if is_advice_or_generic_page(r.get("job_listing_url", ""))
        ]
        assert len(advice_urls) == 0, f"Found advice URLs in job_listing_url: {advice_urls}"

        # 2. Zero corrupted phones
        corrupted_phones = [
            r["phone"]
            for r in cleaned_rows
            if r.get("phone") and not validate_phone_number(r["phone"])[0]
        ]
        assert len(corrupted_phones) == 0, f"Found corrupted phone numbers: {corrupted_phones}"

        # 3. Zero address-polluted recruiters
        polluted_names = [
            r["contact_person"]
            for r in cleaned_rows
            if r.get("contact_person") and any(
                m in r["contact_person"].lower()
                for m in ["straße", "str.", "str ", "weg", "allee", "\n", "gastronomie"]
            )
        ]
        assert len(polluted_names) == 0, f"Found polluted contact persons: {polluted_names}"

        # 4. Zero hogapage or mailto in form_link
        bad_forms = [
            r["form_link"]
            for r in cleaned_rows
            if r.get("form_link") in ("https://jobs.hogapage.de", "https://mailto:bewerbung@landhotel.de")
            or "mailto:" in str(r.get("form_link", ""))
        ]
        assert len(bad_forms) == 0, f"Found bad form links: {bad_forms}"

        # 5. Zero mailto in direct_application_url
        bad_direct = [
            r["direct_application_url"]
            for r in cleaned_rows
            if "mailto:" in str(r.get("direct_application_url", ""))
        ]
        assert len(bad_direct) == 0, f"Found mailto in direct_application_url: {bad_direct}"
