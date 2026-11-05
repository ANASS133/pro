"""
OpenStreetMap Overpass API Business Scraper.
Provides high-speed, ban-free, and captcha-free discovery of local businesses,
craftsmen, medical practices, and corporate offices across Germany.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import requests

logger = logging.getLogger(__name__)

DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Common categories mapped to OpenStreetMap key/value pairs
CATEGORY_TAG_MAP = {
    "handwerk": ["node['craft']", "way['craft']"],
    "craft": ["node['craft']", "way['craft']"],
    "it": ["node['office'='it']", "node['office'='software']", "way['office'='it']"],
    "office": ["node['office']", "way['office']"],
    "aerzte": ["node['amenity'='doctors']", "node['amenity'='dentist']"],
    "healthcare": ["node['healthcare']", "node['amenity'='hospital']"],
    "gastro": ["node['amenity'='restaurant']", "node['amenity'='cafe']"],
    "shop": ["node['shop']", "way['shop']"],
}


class OverpassBusinessScraper:
    """Discovers business listings using OpenStreetMap Overpass API."""

    def __init__(self, endpoints: Optional[List[str]] = None, timeout: int = 25):
        self.endpoints = endpoints or DEFAULT_OVERPASS_ENDPOINTS
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ArbeitsagenturBusinessDiscovery/1.0",
            "Accept": "application/json",
        })

    def build_query(
        self,
        city: str = "",
        category: Union[str, List[str]] = "handwerk",
        limit: int = 100,
        osm_tags: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        profession_context: Optional[Union[Dict[str, Any], str]] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> str:
        """Construct Overpass QL query filtering by German city, bounding box, and business categories.
        
        Supports spatial bounding boxes (s, w, n, e) or administrative area polygons.
        """
        clean_city = str(city or "").strip()
        
        # 1. Use explicitly passed OSM tags if present
        tags = list(osm_tags or [])

        # Priority 1: Consolidated category union
        cat_list: List[str] = []
        if categories:
            cat_list = [str(c).strip() for c in categories if str(c).strip()]
        elif isinstance(category, list):
            cat_list = [str(c).strip() for c in category if str(c).strip()]
        elif category:
            cat_list = [str(category).strip()]
        
        # 2. Consult ProfessionIntelligence for dedicated category-to-OSM resolution
        if not tags and cat_list:
            try:
                from services.profession_intelligence import profession_intelligence
                resolved = profession_intelligence.resolve_osm_tags_for_categories(
                    cat_list, profession_context=profession_context
                )
                tags = resolved.get("resolved_tags", [])
            except Exception as exc:
                logger.warning("Failed to resolve OSM tags via profession_intelligence: %s", exc)
                tags = []

            # Secondary fallback for categories not in taxonomy but explicitly in CATEGORY_TAG_MAP
            unresolved = resolved.get("unresolved_categories", [])
            for c_item in unresolved:
                if c_item.lower() in CATEGORY_TAG_MAP:
                    tags.extend(CATEGORY_TAG_MAP[c_item.lower()])

        # Do NOT silently fallback to generic node['craft'] or node['office']
        # If no valid domain tags could be resolved, return empty query to prevent spamming irrelevant businesses
        if not tags:
            logger.warning("No specific OSM tags resolved for categories %s; aborting generic fallback", cat_list)
            return ""
        
        # Deduplicate tags while preserving order
        unique_tags = []
        for t in tags:
            if t not in unique_tags:
                unique_tags.append(t)

        # Spatial Bounding Box Strategy (Ultra fast, covers small towns, villages & rural areas)
        if bbox:
            s, w, n, e = bbox
            tag_queries = [f"{tag};" for tag in unique_tags]
            tag_block = "\n  ".join(tag_queries)
            query = f"""
[out:json][timeout:{self.timeout}][bbox:{s},{w},{n},{e}];
(
  {tag_block}
);
out body {limit};
>;
out skel qt;
"""
            return query.strip()

        # Administrative Area Strategy (City / municipality / state)
        tag_queries = []
        for tag in unique_tags:
            tag_queries.append(f"{tag}(area.searchArea);")
            
        tag_block = "\n  ".join(tag_queries)

        query = f"""
[out:json][timeout:{self.timeout}];
area["name"="{clean_city}"]["admin_level"~"^(4|6|7|8)$"]->.searchArea;
(
  {tag_block}
);
out body {limit};
>;
out skel qt;
"""
        return query.strip()

    def search_businesses_bbox(
        self,
        bbox: Tuple[float, float, float, float],
        osm_tags: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        limit: int = 50,
        default_city: str = "",
        profession_context: Optional[Union[Dict[str, Any], str]] = None,
    ) -> List[Dict]:
        """Query Overpass API within a spatial bounding box (s, w, n, e)."""
        query = self.build_query(
            bbox=bbox,
            osm_tags=osm_tags,
            categories=categories,
            limit=limit,
            profession_context=profession_context,
        )
        if not query:
            return []

        data = None
        for endpoint in self.endpoints:
            try:
                resp = self.session.post(
                    endpoint,
                    data={"data": query},
                    timeout=(min(4, self.timeout), self.timeout),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    break
            except Exception as exc:
                logger.debug("BBox Overpass endpoint %s failed: %s", endpoint, exc)

        if not data or "elements" not in data:
            return []
        return self.parse_elements(data["elements"], default_city=default_city)

    def search_businesses(
        self,
        city: str,
        category: Union[str, List[str]] = "handwerk",
        limit: int = 100,
        osm_tags: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        profession_context: Optional[Union[Dict[str, Any], str]] = None,
    ) -> List[Dict]:
        """Query Overpass API and parse results into standardized business dicts."""
        clean_city = str(city or "").strip()
        if not clean_city or clean_city.lower() in {"deutschland", "bundesweit", "all", "alle", "germany"}:
            try:
                from services.geographic_batching import geographic_batching
                targets = geographic_batching.resolve_targets(clean_city, max_hubs=3).get("target_cities", ["Berlin", "Köln", "München"])
            except Exception:
                targets = ["Berlin", "Köln", "München"]
            
            all_biz: List[Dict] = []
            seen = set()
            per_city_limit = max(10, limit // len(targets))
            for target_city in targets:
                city_results = self.search_businesses(city=target_city, category=category, limit=per_city_limit, osm_tags=osm_tags, categories=categories, profession_context=profession_context)
                for b in city_results:
                    key = (b.get("name", "").lower(), b.get("city", "").lower())
                    if key not in seen:
                        seen.add(key)
                        all_biz.append(b)
            return all_biz

        query = self.build_query(
            city=clean_city,
            category=category,
            limit=limit,
            osm_tags=osm_tags,
            categories=categories,
            profession_context=profession_context,
        )
        if not query:
            logger.info("Empty Overpass query generated (no valid OSM tags); skipping query.")
            return []
        data = None

        for endpoint in self.endpoints:
            try:
                logger.info("Executing Overpass query against %s for %s (%s)", endpoint, clean_city, category)
                resp = self.session.post(
                    endpoint,
                    data={"data": query},
                    # Short connect timeout: an unreachable mirror must fail fast instead of
                    # blocking the search for the full read timeout on every endpoint.
                    timeout=(min(4, self.timeout), self.timeout),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    break
            except Exception as exc:
                logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)

        if not data or "elements" not in data:
            logger.warning("No data returned from Overpass API for city=%s", clean_city)
            return []

        return self.parse_elements(data["elements"], default_city=clean_city)

    def parse_elements(self, elements: List[Dict], default_city: str = "") -> List[Dict]:
        """Convert raw OSM elements into clean business records."""
        businesses: List[Dict] = []
        seen_names: set = set()

        for el in elements:
            tags = el.get("tags") or {}
            name = tags.get("name") or tags.get("operator") or tags.get("brand")
            if not name:
                continue

            clean_name = re.sub(r"\s+", " ", str(name)).strip()
            if clean_name.lower() in seen_names:
                continue
            seen_names.add(clean_name.lower())

            # Address components
            street = tags.get("addr:street", "")
            housenumber = tags.get("addr:housenumber", "")
            address = f"{street} {housenumber}".strip()
            postcode = tags.get("addr:postcode", "")
            city = tags.get("addr:city") or default_city

            # Contact info directly in OSM tags
            phone = tags.get("contact:phone") or tags.get("phone", "")
            website = (
                tags.get("contact:website")
                or tags.get("website")
                or tags.get("url", "")
            )
            email = tags.get("contact:email") or tags.get("email", "")

            # Category / type
            biz_type = (
                tags.get("craft")
                or tags.get("office")
                or tags.get("amenity")
                or tags.get("shop")
                or tags.get("healthcare")
                or "Business"
            )

            lat = el.get("lat") or (el.get("center", {}).get("lat") if isinstance(el.get("center"), dict) else None)
            lon = el.get("lon") or (el.get("center", {}).get("lon") if isinstance(el.get("center"), dict) else None)

            businesses.append({
                "name": clean_name,
                "type": biz_type,
                "address": address,
                "street": address,
                "postcode": postcode,
                "postal_code": postcode,
                "city": city,
                "location": f"{postcode} {city}".strip() if postcode else city,
                "phone": phone,
                "website": website,
                "email": email.strip().lower(),
                "source": "OpenStreetMap",
                "opportunity_type": "POTENTIAL_EMPLOYER",
                "is_potential_employer": True,
                "is_verified_vacancy": False,
                "lat": lat,
                "lon": lon,
                "osm_id": el.get("id"),
                "osm_type": el.get("type"),
                "tags": tags,
            })

        return businesses
