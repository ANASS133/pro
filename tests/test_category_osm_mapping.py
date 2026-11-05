import pytest
from services.profession_intelligence import profession_intelligence
from scraper.overpass_scraper import OverpassBusinessScraper


class TestCategoryOsmMapping:
    """Test AI Employer Category to OSM Tag Mapping fixes."""

    def test_hotelfachmann_category_resolution(self):
        """Verify Hotelfachmann categories resolve to hospitality OSM tags with zero office/craft tags."""
        prof_context = profession_intelligence.classify_profession("Hotelfachmann")
        categories = ["Hotel", "Resort & Wellnesshotel", "Gasthof & Pension", "Event- & Tagungszentrum"]
        
        result = profession_intelligence.resolve_osm_tags_for_categories(categories, profession_context=prof_context)
        resolved_tags = result["resolved_tags"]
        unresolved = result["unresolved_categories"]

        assert len(unresolved) == 0, f"Unexpected unresolved categories: {unresolved}"
        assert any("tourism" in t and "hotel" in t for t in resolved_tags)
        assert any("tourism" in t and "guest_house" in t for t in resolved_tags)
        assert any("amenity" in t and "events_venue" in t for t in resolved_tags)
        
        # Must NOT contain generic fallback tags
        assert "node['craft']" not in resolved_tags
        assert "node['office']" not in resolved_tags

    def test_pflegefachmann_category_resolution(self):
        """Verify Pflegefachmann categories resolve to healthcare/hospital/nursing tags."""
        prof_context = profession_intelligence.classify_profession("Pflegefachmann")
        categories = ["Krankenhaus & Klinikum", "Pflegeheim & Seniorenresidenz", "Ambulanter Pflegedienst"]
        
        result = profession_intelligence.resolve_osm_tags_for_categories(categories, profession_context=prof_context)
        resolved_tags = result["resolved_tags"]
        unresolved = result["unresolved_categories"]

        assert len(unresolved) == 0
        assert any("hospital" in t or "clinic" in t for t in resolved_tags)
        assert any("nursing_home" in t for t in resolved_tags)
        assert any("nurse" in t for t in resolved_tags)
        assert "node['craft']" not in resolved_tags

    def test_fachinformatiker_category_resolution(self):
        """Verify Fachinformatiker Systemintegration resolves to IT/data center tags."""
        prof_context = profession_intelligence.classify_profession("Fachinformatiker Systemintegration")
        categories = ["IT-Systemhaus", "Rechenzentrum"]
        
        result = profession_intelligence.resolve_osm_tags_for_categories(categories, profession_context=prof_context)
        resolved_tags = result["resolved_tags"]

        assert any("office'='it" in t for t in resolved_tags)
        assert any("telecom'='data_center" in t for t in resolved_tags)
        assert "node['craft']" not in resolved_tags

    def test_kfz_mechatroniker_category_resolution(self):
        """Verify Kfz-Mechatroniker categories resolve to car repair/dealership tags."""
        prof_context = profession_intelligence.classify_profession("Kfz-Mechatroniker")
        categories = ["Autohaus", "Kfz-Werkstatt"]
        
        result = profession_intelligence.resolve_osm_tags_for_categories(categories, profession_context=prof_context)
        resolved_tags = result["resolved_tags"]

        assert any("shop'='car" in t for t in resolved_tags)
        assert any("car_repair" in t for t in resolved_tags)

    def test_no_generic_fallbacks_for_unknown_categories(self):
        """Verify completely unknown categories do not silently fall back to craft/office."""
        result = profession_intelligence.resolve_osm_tags_for_categories(
            ["TotallyFakeCategoryXYZ", "UnknownIndustry123"]
        )
        assert result["resolved_tags"] == []
        assert "TotallyFakeCategoryXYZ" in result["unresolved_categories"]
        assert "UnknownIndustry123" in result["unresolved_categories"]

    def test_custom_keyword_matching_categories(self):
        """Verify custom user-added categories like 'Hostel' or 'Tierklinik' match keyword patterns."""
        result = profession_intelligence.resolve_osm_tags_for_categories(["Hostel", "Tierklinik"])
        tags = result["resolved_tags"]
        assert any("hostel" in t for t in tags)
        assert any("veterinary" in t for t in tags)

    def test_overpass_query_builder_with_categories(self):
        """Verify OverpassBusinessScraper builds query with resolved tags and aborts on empty tags."""
        scraper = OverpassBusinessScraper()
        
        # 1. Hotelfachmann categories
        q = scraper.build_query(
            city="Köln",
            categories=["Hotel", "Gasthof & Pension"],
            profession_context="Hotelfachmann",
        )
        assert 'area["name"="Köln"]' in q
        assert "tourism" in q and "hotel" in q
        assert "node['craft']" not in q
        assert "node['office']" not in q

        # 2. Unknown category returns empty query ""
        q_unknown = scraper.build_query(
            city="Köln",
            categories=["CompletelyBogusCategory"],
        )
        assert q_unknown == ""
