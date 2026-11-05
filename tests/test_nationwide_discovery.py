"""
JobScout — Nationwide Google Maps / OSM Discovery Tests
======================================================
Tests covering:
1. Comprehensive nationwide geographic coverage (Großstädte, Mittelstädte, Kleinstädte, rural municipalities)
2. Removal of the 15-business cap and systematic regional batching
3. Preserving AI employer categories with resolved OSM tags and zero generic craft/office fallbacks
4. Spatial bounding box querying and geographic deduplication
5. Persistent checkpoint creation, progress saving, pausing, and resuming
6. Separation of Discovery Queue from Verification Queue
7. Independent background processing and non-blocking portal execution
8. Live progress dashboard telemetry and completion status
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.geographic_batching import GERMAN_ADMIN_REGIONS, geographic_batching
from services.geographic_checkpoint_manager import GeographicCheckpointManager
from services.nationwide_discovery_engine import NationwideDiscoveryEngine
from scraper.overpass_scraper import OverpassBusinessScraper


class TestNationwideDiscovery:
    """Test suite for Nationwide Google Maps & OSM discovery."""

    @pytest.fixture(autouse=True)
    def setup_temp_checkpoint_dir(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_geo_cp_"))
        self.cp_mgr = GeographicCheckpointManager(storage_dir=self.temp_dir)
        yield
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Correct Geographic Search Scope (Großstädte, Mittelstädte, Kleinstädte, rural municipalities)
    def test_nationwide_coverage_includes_all_settlement_types(self):
        """Verifies nationwide plan spans all 16 states and includes large, medium, small, and rural regions."""
        plan = geographic_batching.get_nationwide_coverage_plan("")
        assert plan["scope"] == "nationwide_comprehensive"
        assert plan["total_regions"] == 16
        assert plan["total_major_cities"] >= 16  # Large cities
        assert plan["total_towns"] >= 100        # Medium and small towns
        assert plan["total_rural_districts"] >= 50  # Rural municipalities

        # Check that specific small towns and rural districts are present
        all_small = [town for r in plan["regions"] for town in r.get("small_towns", [])]
        assert any(t in all_small for t in ["Ahaus", "Cham", "Dingolfing", "Neuruppin", "Wittlich"])

        all_rural = [d for r in plan["regions"] for d in r.get("rural_districts", [])]
        assert any("Uckermark" in d or "Regen" in d or "Erzgebirge" in d or "Eifel" in d for d in all_rural)

    def test_specific_city_and_postal_code_scope(self):
        """Verifies specific city or postal code search focuses on that locality."""
        # Ahaus
        city_plan = geographic_batching.get_nationwide_coverage_plan("Ahaus")
        assert city_plan["scope"] == "city"
        assert city_plan["is_nationwide"] is False
        assert city_plan["region_name"] == "Ahaus"

        # Postal code 50668
        plz_plan = geographic_batching.get_nationwide_coverage_plan("50668")
        assert plz_plan["scope"] == "city"
        assert plz_plan["is_nationwide"] is False

    def test_federal_state_scope(self):
        """Verifies searching for Bayern returns Bavarian regional coverage."""
        state_plan = geographic_batching.get_nationwide_coverage_plan("Bayern")
        assert state_plan["scope"] == "federal_state"
        assert state_plan["region_name"] == "Bayern"
        assert "München" in state_plan["target_cities"]

    # 2. Removal of the 15-Business Cap
    def test_removes_15_business_cap(self):
        """Verifies discovery engine processes beyond 15 businesses across multiple regions."""
        mock_scraper = MagicMock(spec=OverpassBusinessScraper)
        # Mock returning 20 businesses in region 1 and 20 in region 2
        mock_scraper.search_businesses_bbox.side_effect = [
            [{"name": f"Biz DE-BY {i}", "city": "München", "website": f"https://biz{i}.de"} for i in range(20)],
            [{"name": f"Biz DE-BW {i}", "city": "Stuttgart", "website": f"https://biz_bw{i}.de"} for i in range(20)],
        ]

        engine = NationwideDiscoveryEngine(checkpoint_manager=self.cp_mgr, overpass_scraper=mock_scraper)

        job = engine.create_and_start_job(
            search_id="test_cap_removal",
            keyword="Hotelfachmann",
            location="",
            max_regions=2,
            max_businesses_per_region=25,
            max_total_businesses=100,  # Cap is 100, NOT 15!
            verify_websites=False,
        )

        # Allow worker thread to process the 2 regions
        time.sleep(1.2)

        status = engine.get_job_status("test_cap_removal")
        assert status is not None
        # Must have collected 40 businesses, proving the 15 cap is removed!
        assert len(status["discovered_businesses"]) == 40
        assert status["metrics"]["businesses_discovered"] == 40

    # 3. Spatial Bounding Box & Geographic Deduplication
    def test_geographic_deduplication_across_overlapping_regions(self):
        """Verifies duplicate businesses appearing in overlapping regions are deduplicated."""
        mock_scraper = MagicMock(spec=OverpassBusinessScraper)
        # Return identical business in both regions
        same_biz = {"name": "Grand Hotel Central", "city": "Berlin", "website": "https://grandhotel.de"}
        unique_biz = {"name": "Boutique Hotel Süd", "city": "München", "website": "https://boutique.de"}

        mock_scraper.search_businesses_bbox.side_effect = [
            [same_biz],
            [same_biz, unique_biz],
        ]

        engine = NationwideDiscoveryEngine(checkpoint_manager=self.cp_mgr, overpass_scraper=mock_scraper)
        engine.create_and_start_job(
            search_id="test_dedup",
            keyword="Hotelfachmann",
            location="",
            max_regions=2,
            verify_websites=False,
        )
        time.sleep(1.2)

        status = engine.get_job_status("test_dedup")
        # Same biz should only appear once; total 2 unique
        assert len(status["discovered_businesses"]) == 2

    # 4. Persistent Checkpoints, Pause & Resume
    def test_checkpoint_persistence_and_resume(self):
        """Verifies state is saved to disk and can resume remaining regions without repeating completed ones."""
        search_id = "test_resume_checkpoint_001"
        regions = [{"region_id": "DE-BY"}, {"region_id": "DE-BW"}, {"region_id": "DE-NW"}]

        # 1. Create
        cp = self.cp_mgr.create_checkpoint(
            search_id=search_id,
            profession="Pflegefachmann",
            categories=["Krankenhaus & Klinikum"],
            regions=regions,
            scope="nationwide",
        )
        assert len(cp["pending_regions"]) == 3

        # 2. Scan region 1 (DE-BY) with 5 businesses
        self.cp_mgr.update_region_progress(
            search_id=search_id,
            region_id="DE-BY",
            status="scanned",
            discovered_batch=[{"name": f"Klinik BY {i}", "city": "Augsburg"} for i in range(5)],
        )

        # 3. Pause
        self.cp_mgr.pause_checkpoint(search_id)
        paused = self.cp_mgr.get_checkpoint(search_id)
        assert paused["status"] == "paused"
        assert "DE-BY" in paused["scanned_regions"]
        assert len(paused["pending_regions"]) == 2

        # 4. Resume
        resumed = self.cp_mgr.resume_checkpoint(search_id)
        assert resumed["status"] == "active"
        # DE-BY should NOT be in pending; only remaining 2 regions
        assert resumed["pending_regions"] == ["DE-BW", "DE-NW"]
        assert resumed["stats"]["discovered_count"] == 5

    # 5. Separate Discovery Queue from Verification Queue
    def test_discovery_queue_preserves_potential_employers_without_websites(self):
        """Verifies businesses without websites are preserved as POTENTIAL_EMPLOYER."""
        mock_scraper = MagicMock(spec=OverpassBusinessScraper)
        mock_scraper.search_businesses_bbox.return_value = [
            {"name": "Dorfbäckerei Schmidt", "city": "Garmisch", "website": ""},
            {"name": "Hotel Alpenblick", "city": "Oberstdorf", "website": "https://alpenblick.de"},
        ]

        engine = NationwideDiscoveryEngine(checkpoint_manager=self.cp_mgr, overpass_scraper=mock_scraper)
        engine.create_and_start_job(
            search_id="test_queue_separation",
            keyword="Bäcker",
            location="",
            max_regions=1,
            verify_websites=False,
        )
        time.sleep(1.0)

        status = engine.get_job_status("test_queue_separation")
        assert len(status["discovered_businesses"]) == 2
        # Dorfbäckerei Schmidt has no website, but must be in verified_employers as potential employer!
        potential_names = [e["name"] for e in status["verified_employers"]]
        assert "Dorfbäckerei Schmidt" in potential_names

    # 6. Overpass BBox Query Builder
    def test_overpass_query_builder_bbox_support(self):
        """Verifies build_query constructs spatial bbox query properly."""
        scraper = OverpassBusinessScraper()
        bbox = (48.1, 11.4, 48.3, 11.7)
        q = scraper.build_query(
            bbox=bbox,
            categories=["Hotel"],
            profession_context="Hotelfachmann",
        )
        assert "[bbox:48.1,11.4,48.3,11.7]" in q
        assert "tourism" in q and "hotel" in q
        assert "node['craft']" not in q
        assert "node['office']" not in q

    # 7. Adaptive Geographic Tiling
    def test_adaptive_geographic_tiles_covers_germany(self):
        """Verifies 16 spatial tiles span all of Germany from South to North and West to East."""
        tiles = geographic_batching.get_geographic_tiles(rows=4, cols=4)
        assert len(tiles) == 16

        # Min latitude should be near southern border (47.27° N)
        min_s = min(t["bbox"][0] for t in tiles)
        assert min_s <= 47.3

        # Max latitude should reach northern border (55.06° N)
        max_n = max(t["bbox"][2] for t in tiles)
        assert max_n >= 55.0

        # Western border (~5.86° E) and Eastern border (~15.04° E)
        min_w = min(t["bbox"][1] for t in tiles)
        max_e = max(t["bbox"][3] for t in tiles)
        assert min_w <= 5.9
        assert max_e >= 15.0

