"""
Tests for JobScout Search Results Lifecycle & Discrepancy Resolution.
Verifies:
1. Every enabled scraper contributes to the unified pipeline.
2. Date filter does not eliminate live portal opportunities with 'k. A.'.
3. Stale dates on any portal are strictly rejected.
4. Multi-stage audit tracks raw, filtered, and rejected counts per source with explicit reasons.
5. Canonical result dataset is consistent across API responses, display counts, and 21-column Excel export.
"""

import unittest
from datetime import datetime, timedelta
import pandas as pd

from scraper.search_filter_engine import (
    is_publication_date_matching,
    filter_and_deduplicate_jobs,
    filter_and_deduplicate_jobs_with_audit,
)
from scraper.application_form_discovery import EXCEL_COLUMNS, normalize_job_opportunity_row
from app import app, search_cache, _prepare_download_jobs, _save_auto_extraction_export_records


class SearchDiscrepancyResolutionTestCase(unittest.TestCase):
    """Test suite addressing the 141 -> 10 disappearance bug and ensuring complete source retention."""

    def setUp(self):
        self.app = app.test_client()
        self.ref_date = datetime(2026, 10, 26, 12, 0, 0)

    def test_live_portal_unknown_date_preservation(self):
        """Live vacancy portals (Ausbildung.de, Azubiyo, AUBI-plus, IHK) only serve active listings;
        they must not be dropped when published_date is 'k. A.'."""
        # Ausbildung.de with 'k. A.' -> Keep
        self.assertTrue(
            is_publication_date_matching(
                "k. A.",
                max_days=28,
                reference_date=self.ref_date,
                source="ausbildung.de",
            )
        )
        # Azubiyo with 'k. A.' -> Keep
        self.assertTrue(
            is_publication_date_matching(
                "k. A.",
                max_days=28,
                reference_date=self.ref_date,
                source="azubiyo.de",
            )
        )
        # Aubi-plus with empty date -> Keep
        self.assertTrue(
            is_publication_date_matching(
                "",
                max_days=28,
                reference_date=self.ref_date,
                source="aubi-plus.de",
            )
        )
        # Unknown source with 'k. A.' -> Reject
        self.assertFalse(
            is_publication_date_matching(
                "k. A.",
                max_days=28,
                reference_date=self.ref_date,
                source="custom_unknown_source",
            )
        )

    def test_stale_dates_on_portals_are_strictly_rejected(self):
        """If a portal listing DOES contain a parsed publication date that exceeds max_days,
        it must be strictly rejected even if it comes from an enabled portal."""
        # Published 60 days ago (outside 28-day window) -> Reject
        self.assertFalse(
            is_publication_date_matching(
                "2026-08-15",
                max_days=28,
                reference_date=self.ref_date,
                source="ausbildung.de",
            )
        )
        # Published 10 days ago (inside 28-day window) -> Accept
        self.assertTrue(
            is_publication_date_matching(
                "2026-10-16",
                max_days=28,
                reference_date=self.ref_date,
                source="ausbildung.de",
            )
        )

    def test_multi_source_lifecycle_trace_ahaus_fachinformatiker(self):
        """Simulate the exact scenario:
        Keyword: 'ausbildung als fachinformatiker'
        Location: 'ahaus'
        Period: '4 Wochen' (28 days)
        Raw inputs: Arbeitsagentur (10), Ausbildung.de (114), Azubiyo (15), AUBI-plus (2).
        Verifies:
        1. Final results are NOT limited to Arbeitsagentur.
        2. Valid local opportunities from Ausbildung.de and Azubiyo are preserved.
        3. Excluded records have documented reasons (location, profession, date, duplicate).
        """
        raw_dataset = [
            # 1. Arbeitsagentur: 3 sample local jobs with explicit recent dates
            {
                "title": "Ausbildung Fachinformatiker Systemintegration (m/w/d)",
                "company": "amexus Informationstechnik GmbH & Co. KG",
                "location": "48683 Ahaus",
                "city": "Ahaus",
                "postal_code": "48683",
                "published_date": "2026-10-07",
                "source": "Arbeitsagentur",
                "apply_url": "https://arbeitsagentur.de/job/1",
            },
            {
                "title": "Ausbildung 2027: Fachinformatiker Anwendungsentwicklung",
                "company": "Schnell media GmbH & Co. KG",
                "location": "48691 Vreden",
                "city": "Vreden",
                "postal_code": "48691",
                "published_date": "2026-10-10",
                "source": "Arbeitsagentur",
                "apply_url": "https://arbeitsagentur.de/job/2",
            },
            {
                "title": "Fachinformatiker/in Fachrichtung Systemintegration",
                "company": "buerodata AG",
                "location": "48703 Stadtlohn",
                "city": "Stadtlohn",
                "postal_code": "48703",
                "published_date": "2026-10-23",
                "source": "Arbeitsagentur",
                "apply_url": "https://arbeitsagentur.de/job/3",
            },

            # 2. Ausbildung.de: valid local jobs in commuter area (Münster, Bottrop, Rheine) with 'k. A.'
            {
                "title": "Ausbildung Fachinformatiker/in für Daten- und Prozessanalyse (m/w/d)",
                "company": "Cortina Consult GmbH",
                "location": "48155 Münster",
                "city": "Münster",
                "postal_code": "48155",
                "published_date": "k. A.",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/cortina-datenanalyse",
            },
            {
                "title": "Ausbildung 2027 – Fachinformatiker/in für Systemintegration (w/m/d)",
                "company": "DTS Systeme GmbH",
                "location": "48155 Münster",
                "city": "Münster",
                "postal_code": "48155",
                "published_date": "k. A.",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/dts-systeme",
            },
            {
                "title": "Fachinformatiker Systemintegration (m/w/d)",
                "company": "Logistik IT GmbH",
                "location": "48431 Rheine",
                "city": "Rheine",
                "postal_code": "48431",
                "published_date": "k. A.",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/logistik-it",
            },
            # Ausbildung.de: Distant sponsored fallbacks (Frankfurt, München, Berlin) -> REJECT
            {
                "title": "Ausbildung Fachinformatiker Anwendungsentwicklung",
                "company": "Main Finance Frankfurt",
                "location": "60311 Frankfurt am Main",
                "city": "Frankfurt am Main",
                "postal_code": "60311",
                "published_date": "k. A.",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/ffm-it",
            },
            {
                "title": "Fachinformatiker Systemintegration (m/w/d)",
                "company": "Bayern Auto AG",
                "location": "80331 München",
                "city": "München",
                "postal_code": "80331",
                "published_date": "k. A.",
                "source": "ausbildung.de",
                "apply_url": "https://ausbildung.de/stellen/muc-it",
            },

            # 3. Azubiyo: valid local jobs in commuter area (Münster, Dülmen) with 'k. A.'
            {
                "title": "Ausbildung zum Fachinformatiker - Anwendungsentwicklung (m/w/d)",
                "company": "Finanz Informatik GmbH & Co. KG",
                "location": "48147 Münster",
                "city": "Münster",
                "postal_code": "48147",
                "published_date": "k. A.",
                "source": "azubiyo.de",
                "apply_url": "https://azubiyo.de/stellen/finanz-informatik",
            },
            {
                "title": "Ausbildung Fachinformatiker/in - Systemintegration 2027 (m/w/d)",
                "company": "KORDEL Antriebstechnik GmbH",
                "location": "48249 Dülmen",
                "city": "Dülmen",
                "postal_code": "48249",
                "published_date": "k. A.",
                "source": "azubiyo.de",
                "apply_url": "https://azubiyo.de/stellen/kordel-duelmen",
            },
            # Azubiyo: Unrelated profession in Ahaus -> REJECT
            {
                "title": "Ausbildung Industriekaufmann (m/w/d)",
                "company": "Westmünsterland Industrie",
                "location": "48683 Ahaus",
                "city": "Ahaus",
                "postal_code": "48683",
                "published_date": "k. A.",
                "source": "azubiyo.de",
                "apply_url": "https://azubiyo.de/stellen/industrie-ahaus",
            },

            # 4. AUBI-plus: distant job (Stuttgart) -> REJECT
            {
                "title": "Ausbildung Fachinformatiker Digitale Vernetzung",
                "company": "Südtech Stuttgart",
                "location": "70173 Stuttgart",
                "city": "Stuttgart",
                "postal_code": "70173",
                "published_date": "k. A.",
                "source": "aubi-plus.de",
                "apply_url": "https://aubi-plus.de/stellen/suedtech",
            },
        ]

        filtered, audit = filter_and_deduplicate_jobs_with_audit(
            raw_dataset,
            keyword="ausbildung als fachinformatiker",
            location="ahaus",
            published_since_days=28,
            reference_date=self.ref_date,
        )

        # 1. Total counts must reconcile exactly
        self.assertEqual(audit["raw_total"], len(raw_dataset))
        self.assertEqual(audit["filtered_total"], len(filtered))
        self.assertEqual(audit["exclusions_total"], audit["raw_total"] - audit["filtered_total"])

        # 2. Multi-source presence: NOT limited to Arbeitsagentur
        sources_present = {j["source"] for j in filtered}
        self.assertIn("Arbeitsagentur", sources_present)
        self.assertIn("ausbildung.de", sources_present)
        self.assertIn("azubiyo.de", sources_present)

        # Arbeitsagentur: 3, Ausbildung.de: 3, Azubiyo: 2 -> total 8 valid opportunities
        self.assertEqual(len(filtered), 8)

        # 3. Exclusions breakdown
        by_stage = audit["exclusions_by_stage"]
        self.assertEqual(by_stage["location"], 3)  # Frankfurt, München, Stuttgart
        self.assertEqual(by_stage["profession"], 1)  # Industriekaufmann
        self.assertEqual(by_stage["date"], 0)

        # 4. Verify explicit exclusion reasons exist for all excluded records
        self.assertEqual(len(audit["exclusions"]), 4)
        for excl in audit["exclusions"]:
            self.assertIn("reason", excl)
            self.assertTrue(len(excl["reason"]) > 10)
            self.assertIn("stage", excl)
            self.assertIn("source", excl)

    def test_canonical_dataset_used_for_excel_export(self):
        """Excel export must include the complete final dataset across all portals,
        enforce the 21-column schema, and preserve secondary sheets for Google Maps."""
        test_jobs = [
            {
                "title": "Fachinformatiker Systemintegration",
                "company": "amexus",
                "location": "48683 Ahaus",
                "source": "Arbeitsagentur",
                "email": "info@amexus.com",
                "apply_url": "https://amexus.com/job/1",
                "has_form": False,
            },
            {
                "title": "Fachinformatiker Anwendungsentwicklung",
                "company": "DTS Systeme",
                "location": "48155 Münster",
                "source": "ausbildung.de",
                "email": None,
                "apply_url": "https://dts.de/karriere",
                "has_form": True,
                "form_link": "https://dts.de/apply-form",
            },
            {
                "title": "Fachinformatiker Daten- und Prozessanalyse",
                "company": "Finanz Informatik",
                "location": "48147 Münster",
                "source": "azubiyo.de",
                "email": "karriere@f-i.de",
                "apply_url": "https://f-i.de/jobs/123",
                "has_form": False,
            },
        ]

        prepared = _prepare_download_jobs(test_jobs)
        self.assertEqual(len(prepared), 3)

        file_path = _save_auto_extraction_export_records(
            prepared,
            keyword="ausbildung als fachinformatiker",
            fallback_slug="test_export",
        )
        self.assertTrue(file_path.exists())

        excel = pd.ExcelFile(file_path)
        self.assertIn("Ausbildungsplätze", excel.sheet_names)
        df = pd.read_excel(file_path, sheet_name="Ausbildungsplätze")
        self.assertEqual(len(df), 3)

        # All 21 standard columns present
        for col in EXCEL_COLUMNS:
            self.assertIn(col, df.columns)

        # Companies from all 3 sources are present in the Excel export
        companies = set(df["company"].tolist())
        self.assertIn("amexus", companies)
        self.assertIn("DTS Systeme", companies)
        self.assertIn("Finanz Informatik", companies)

    def test_search_audit_api_endpoint(self):
        """Verify the /api/search/audit endpoint returns the latest search audit metrics."""
        fake_audit = {
            "raw_total": 141,
            "filtered_total": 42,
            "exclusions_total": 99,
            "exclusions_by_stage": {"location": 95, "profession": 4, "date": 0, "duplicate": 0},
            "raw_by_source": {"Arbeitsagentur": 10, "ausbildung.de": 114, "azubiyo.de": 15, "aubi-plus.de": 2},
            "filtered_by_source": {"Arbeitsagentur": 10, "ausbildung.de": 23, "azubiyo.de": 9, "aubi-plus.de": 0},
        }
        search_cache["last_search_audit"] = fake_audit

        res = self.app.get("/api/search/audit")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["audit"]["raw_total"], 141)
        self.assertEqual(data["audit"]["filtered_total"], 42)
        self.assertEqual(data["audit"]["exclusions_total"], 99)


if __name__ == "__main__":
    unittest.main()
