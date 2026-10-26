"""
Tests for JobScout Search, Filtering, Application Verification, and Excel Export
Covers all criteria and regression scenarios from the JobScout specifications.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
import pandas as pd

from scraper.search_filter_engine import (
    extract_profession_tokens,
    is_profession_relevant,
    clean_extracted_location,
    is_location_relevant,
    parse_german_date,
    is_publication_date_matching,
    verify_application_workflow,
    filter_and_deduplicate_jobs,
)
from scraper.application_form_discovery import (
    EXCEL_COLUMNS,
    normalize_job_opportunity_row,
)
from app import app, _prepare_download_jobs, _fetch_combined_jobs


class SearchRelevanceFilteringTestCase(unittest.TestCase):
    """Test profession matching and unrelated job rejection."""

    def test_profession_token_extraction(self):
        meta = extract_profession_tokens("Ausbildung zum Koch (m/w/d)")
        self.assertIn("koch", meta["core_tokens"])
        self.assertIn("köchin", meta["variants"])
        self.assertIn("kaufmann", meta["conflicts"])

    def test_accept_legitimate_koch_titles(self):
        query = "Ausbildung zum Koch"
        valid_titles = [
            "Ausbildung zum Koch (m/w/d)",
            "Koch/Köchin Ausbildung",
            "Ausbildung Koch/Köchin 2027",
            "Ausbildungsplatz Koch",
            "Ausbildung als Köchin",
            "Koch (gn)",
            "Auszubildende Köche (d/m/w)",
            "Beikoch / Beiköchin Ausbildung",
        ]
        for title in valid_titles:
            self.assertTrue(
                is_profession_relevant(title, "", query),
                f"Expected '{title}' to be accepted for query '{query}'",
            )

    def test_reject_unrelated_professions_for_koch(self):
        query = "Ausbildung zum Koch"
        invalid_titles = [
            "Ausbildung Industriekaufmann/-frau",
            "Kaufmann für Versicherungen und Finanzanlagen",
            "Kaufmann im Einzelhandel",
            "Fachinformatiker Anwendungsentwicklung",
            "Verkäufer im Frischebereich",
            "Kfz-Mechatroniker",
            "Zahnmedizinische Fachangestellte",
        ]
        for title in invalid_titles:
            self.assertFalse(
                is_profession_relevant(title, "", query),
                f"Expected '{title}' to be rejected for query '{query}'",
            )


class LocationFilteringTestCase(unittest.TestCase):
    """Test location normalization, bad badge cleaning, and regional matching."""

    def test_location_cleaning_discards_video_and_badges(self):
        # Azubiyo bug: <li>Video</li> or <li>Duales Studium</li> parsed as location
        loc1 = clean_extracted_location("Video")
        self.assertEqual(loc1["location"], "k. A.")
        self.assertEqual(loc1["city"], "k. A.")

        loc2 = clean_extracted_location("48683 Ahaus (u.a.)")
        self.assertEqual(loc2["postal_code"], "48683")
        self.assertEqual(loc2["city"], "Ahaus")
        self.assertIn("48683 Ahaus", loc2["location"])

    def test_ahaus_location_matches_exact_and_commuter_region(self):
        search_loc = "Ahaus"

        # Exact city match
        self.assertTrue(is_location_relevant("48683 Ahaus", "Ahaus", "48683", search_loc))
        self.assertTrue(is_location_relevant("Ahaus-Wüllen", "Ahaus-Wüllen", "48683", search_loc))

        # Regional Münsterland / Kreis Borken commuter towns (PLZ 48/46)
        self.assertTrue(is_location_relevant("48703 Stadtlohn", "Stadtlohn", "48703", search_loc))
        self.assertTrue(is_location_relevant("48691 Vreden", "Vreden", "48691", search_loc))
        self.assertTrue(is_location_relevant("48720 Rosendahl", "Rosendahl", "48720", search_loc))

    def test_ahaus_location_rejects_distant_nationwide_cities(self):
        search_loc = "Ahaus"

        # Distant cities returned by nationwide fallbacks
        self.assertFalse(is_location_relevant("70173 Stuttgart", "Stuttgart", "70173", search_loc))
        self.assertFalse(is_location_relevant("80331 München", "München", "80331", search_loc))
        self.assertFalse(is_location_relevant("88400 Biberach", "Biberach", "88400", search_loc))
        self.assertFalse(is_location_relevant("14467 Potsdam", "Potsdam", "14467", search_loc))

    def test_disallowed_video_location_is_rejected_for_specific_search(self):
        search_loc = "Ahaus"
        self.assertFalse(is_location_relevant("Video", "Video", "N/A", search_loc))
        self.assertFalse(is_location_relevant("k. A.", "k. A.", "N/A", search_loc))


class PublicationDateFilteringTestCase(unittest.TestCase):
    """Test publication date parsing and filtering without substituting scraping date."""

    def test_parse_german_date_formats(self):
        ref_date = datetime(2026, 10, 26, 12, 0, 0)

        # ISO
        d1 = parse_german_date("2026-10-20", reference_date=ref_date)
        self.assertEqual(d1, datetime(2026, 10, 20))

        # German standard
        d2 = parse_german_date("15.10.2026", reference_date=ref_date)
        self.assertEqual(d2, datetime(2026, 10, 15))

        # Relative
        d3 = parse_german_date("vor 3 Tagen", reference_date=ref_date)
        self.assertEqual(d3.date(), (ref_date - timedelta(days=3)).date())

        d4 = parse_german_date("gestern", reference_date=ref_date)
        self.assertEqual(d4.date(), (ref_date - timedelta(days=1)).date())

    def test_publication_date_matching_window(self):
        ref_date = datetime(2026, 10, 26, 12, 0, 0)
        # 2 weeks = 14 days

        # Job published 5 days ago -> Accept
        self.assertTrue(
            is_publication_date_matching("2026-10-21", max_days=14, reference_date=ref_date)
        )

        # Job published 25 days ago -> Reject
        self.assertFalse(
            is_publication_date_matching("2026-10-01", max_days=14, reference_date=ref_date)
        )

        # Job published 3 months ago (e.g. 2026-07-01) -> Reject
        self.assertFalse(
            is_publication_date_matching("2026-07-01", max_days=14, reference_date=ref_date)
        )

        # Missing date -> Rejected under strict 14-day filter unless prefiltered by API
        self.assertFalse(
            is_publication_date_matching("k. A.", max_days=14, reference_date=ref_date)
        )
        self.assertTrue(
            is_publication_date_matching("k. A.", max_days=14, is_source_prefiltered=True)
        )


class ApplicationWorkflowVerificationTestCase(unittest.TestCase):
    """Test 5-tier classification and verification of online application forms."""

    def test_verified_direct_form_category_1(self):
        job = {
            "title": "Koch",
            "company": "Hotel Grand",
            "has_form": True,
            "form_link": "https://karriere.hotel-grand.de/apply/form/123",
            "apply_url": "https://www.arbeitsagentur.de/jobsuche/jobdetail/123",
        }
        wf = verify_application_workflow(job)
        self.assertEqual(wf["category"], 1)
        self.assertTrue(wf["verified_form"])
        self.assertEqual(wf["action_button"]["type"], "verified_form")
        self.assertTrue(wf["action_button"]["autofill"])
        self.assertEqual(wf["action_button"]["label"], "Zum Bewerbungsformular ↗")

    def test_ordinary_job_ad_category_4(self):
        # Raw job portal links can NEVER qualify as a verified application form
        job = {
            "title": "Koch",
            "company": "Gasthof Zur Post",
            "has_form": False,
            "form_link": "",
            "apply_url": "https://www.azubiyo.de/stellenanzeigen/koch-muenster/",
        }
        wf = verify_application_workflow(job)
        self.assertEqual(wf["category"], 4)
        self.assertFalse(wf["verified_form"])
        self.assertEqual(wf["action_button"]["type"], "listing")
        self.assertFalse(wf["action_button"]["autofill"])
        self.assertEqual(wf["action_button"]["label"], "Stellenanzeige öffnen ↗")


class FullRegressionScenarioTestCase(unittest.TestCase):
    """
    Mandatory Regression Scenario:
    Search parameters:
      Keyword: 'Ausbildung zum Koch'
      Location: 'Ahaus'
      Publication period: '2 Wochen' (14 days)
      Sources: All sources
    """

    def setUp(self):
        self.ref_date = datetime(2026, 10, 26, 12, 0, 0)
        self.raw_jobs = [
            # Job 1: Valid Koch in Ahaus published 3 days ago -> ACCEPT
            {
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Hotel Ahaus Hof",
                "location": "48683 Ahaus",
                "city": "Ahaus",
                "postal_code": "48683",
                "published_date": "2026-10-23",
                "source": "Arbeitsagentur",
                "apply_url": "https://arbeitsagentur.de/job/101",
                "email": "bewerbung@hotel-ahaus.de",
                "has_form": True,
                "form_link": "https://hotel-ahaus.de/apply-form",
            },
            # Job 2: Valid Koch/Köchin in Stadtlohn (PLZ 48703, near Ahaus) published 7 days ago -> ACCEPT
            {
                "title": "Koch/Köchin Ausbildung 2027",
                "company": "Gasthaus Stadtlohn",
                "location": "48703 Stadtlohn",
                "city": "Stadtlohn",
                "postal_code": "48703",
                "published_date": "2026-10-19",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/koch-stadtlohn/",
                "email": "",
                "has_form": False,
                "form_link": "",
            },
            # Job 3: Unrelated profession (Industriekaufmann) in Ahaus -> REJECT
            {
                "title": "Ausbildung Industriekaufmann/-frau",
                "company": "Industrie Werke Ahaus GmbH",
                "location": "48683 Ahaus",
                "city": "Ahaus",
                "postal_code": "48683",
                "published_date": "2026-10-22",
                "source": "azubiyo.de",
                "apply_url": "https://azubiyo.de/stellen/industriekaufmann/",
            },
            # Job 4: Unrelated profession (Kaufmann Einzelhandel) in Ahaus -> REJECT
            {
                "title": "Kaufmann im Einzelhandel (m/w/d)",
                "company": "Supermarkt Ahaus",
                "location": "48683 Ahaus",
                "city": "Ahaus",
                "postal_code": "48683",
                "published_date": "2026-10-21",
                "source": "ihk.de",
                "apply_url": "https://ihk.de/stellen/einzelhandel/",
            },
            # Job 5: Faraway city (Stuttgart) nationwide fallback -> REJECT
            {
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Schlosshotel Stuttgart",
                "location": "70173 Stuttgart",
                "city": "Stuttgart",
                "postal_code": "70173",
                "published_date": "2026-10-20",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/koch-stuttgart/",
            },
            # Job 6: Malformed location badge ('Video') -> REJECT for specific city search
            {
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Mystery Gastronomie",
                "location": "Video",
                "city": "Video",
                "published_date": "2026-10-20",
                "source": "azubiyo.de",
                "apply_url": "https://azubiyo.de/stellen/koch-video/",
            },
            # Job 7: Koch in Ahaus, but published 60 days ago (outside 14-day window) -> REJECT
            {
                "title": "Ausbildung Koch 2026",
                "company": "Old Inn Ahaus",
                "location": "48683 Ahaus",
                "city": "Ahaus",
                "postal_code": "48683",
                "published_date": "2026-08-15",
                "source": "Arbeitsagentur",
                "apply_url": "https://arbeitsagentur.de/job/107",
            },
            # Job 8: Cross-portal duplicate of Job 1 (same company, title, city) -> DEDUPLICATE
            {
                "title": "Ausbildung zum Koch (m/w/d)",
                "company": "Hotel Ahaus Hof",
                "location": "Ahaus",
                "city": "Ahaus",
                "published_date": "2026-10-23",
                "source": "aubi-plus.de",
                "apply_url": "https://aubi-plus.de/stelle/koch-hotel-ahaus-hof/",
            },
        ]

    def test_regression_filtering_and_counts(self):
        filtered = filter_and_deduplicate_jobs(
            self.raw_jobs,
            keyword="Ausbildung zum Koch",
            location="Ahaus",
            published_since_days=14,
            reference_date=self.ref_date,
        )

        # 1. Unrelated professions are excluded (Industriekaufmann, Einzelhandel rejected)
        titles = [j["title"] for j in filtered]
        self.assertNotIn("Ausbildung Industriekaufmann/-frau", titles)
        self.assertNotIn("Kaufmann im Einzelhandel (m/w/d)", titles)

        # 2. Distant locations excluded (Stuttgart rejected, Video rejected)
        locations = [j["location"] for j in filtered]
        self.assertFalse(any("Stuttgart" in loc for loc in locations))
        self.assertFalse(any("Video" in loc for loc in locations))

        # 3. Old publication date excluded (Old Inn Ahaus rejected)
        companies = [j["company"] for j in filtered]
        self.assertNotIn("Old Inn Ahaus", companies)

        # 4. Duplicate merged (Job 8 deduplicated against Job 1)
        self.assertEqual(len([c for c in companies if c == "Hotel Ahaus Hof"]), 1)

        # 5. Result count is exactly 2 matching opportunities
        self.assertEqual(len(filtered), 2)

    def test_excel_export_preserves_exact_21_columns(self):
        filtered = filter_and_deduplicate_jobs(
            self.raw_jobs,
            keyword="Ausbildung zum Koch",
            location="Ahaus",
            published_since_days=14,
            reference_date=self.ref_date,
        )

        # Prepare export records
        export_records = _prepare_download_jobs(filtered)
        self.assertEqual(len(export_records), 2)

        # Verify all 21 columns are preserved in exact order
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            df = pd.DataFrame(export_records)
            df = df[EXCEL_COLUMNS]
            df.to_excel(tmp_path, index=False)

            # Re-read and assert columns
            read_df = pd.read_excel(tmp_path)
            self.assertEqual(list(read_df.columns), EXCEL_COLUMNS)
            self.assertEqual(len(read_df.columns), 21)
            self.assertEqual(len(read_df), 2)

            # Assert opportunity without email (Job 2) is retained
            job2_row = read_df[read_df["company"] == "Gasthaus Stadtlohn"].iloc[0]
            self.assertTrue(pd.isna(job2_row["email"]) or job2_row["email"] == "")
            self.assertEqual(job2_row["title"], "Koch/Köchin Ausbildung 2027")
            self.assertEqual(job2_row["has_form"], False)

            # Assert opportunity with form (Job 1) has has_form True
            job1_row = read_df[read_df["company"] == "Hotel Ahaus Hof"].iloc[0]
            self.assertEqual(job1_row["has_form"], True)
            self.assertEqual(job1_row["form_link"], "https://hotel-ahaus.de/apply-form")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
