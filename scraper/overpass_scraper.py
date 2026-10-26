"""
OpenStreetMap Overpass API Business Scraper.
Provides high-speed, ban-free, and captcha-free discovery of local businesses,
craftsmen, medical practices, and corporate offices across Germany.
"""

import logging
import re
from typing import Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

DEFAULT_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
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

    def __init__(self, endpoints: Optional[List[str]] = None, timeout: int = 45):
        self.endpoints = endpoints or DEFAULT_OVERPASS_ENDPOINTS
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ArbeitsagenturBusinessDiscovery/1.0",
            "Accept": "application/json",
        })

    def build_query(self, city: str, category: str = "handwerk", limit: int = 100) -> str:
        """Construct Overpass QL query filtering by German city and business category."""
        clean_city = str(city or "").strip()
        tags = CATEGORY_TAG_MAP.get(category.lower(), ["node['craft']", "node['office']"])
        
        tag_queries = []
        for tag in tags:
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

    def search_businesses(
        self,
        city: str,
        category: str = "handwerk",
        limit: int = 100,
    ) -> List[Dict]:
        """Query Overpass API and parse results into standardized business dicts."""
        if not city:
            return []

        query = self.build_query(city=city, category=category, limit=limit)
        data = None

        for endpoint in self.endpoints:
            try:
                logger.info("Executing Overpass query against %s for %s (%s)", endpoint, city, category)
                resp = self.session.post(
                    endpoint,
                    data={"data": query},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    break
            except Exception as exc:
                logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)

        if not data or "elements" not in data:
            logger.warning("No data returned from Overpass API for city=%s", city)
            return []

        return self.parse_elements(data["elements"], default_city=city)

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

            businesses.append({
                "name": clean_name,
                "type": biz_type,
                "address": address,
                "postcode": postcode,
                "city": city,
                "phone": phone,
                "website": website,
                "email": email.strip().lower(),
                "source": "OpenStreetMap",
                "lat": el.get("lat"),
                "lon": el.get("lon"),
            })

        return businesses
