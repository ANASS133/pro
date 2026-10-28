"""
JobScout — Geographic Batching & Coverage Engine
================================================
Handles location resolution, nationwide sampling across major German economic
hubs, and transparent progress/coverage reporting.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Top tier metropolitan regions & economic powerhouses in Germany
METROPOLITAN_HUBS_TIER_1 = [
    "Berlin",
    "Hamburg",
    "München",
    "Köln",
    "Frankfurt am Main",
    "Stuttgart",
]

METROPOLITAN_HUBS_TIER_2 = [
    "Düsseldorf",
    "Leipzig",
    "Dortmund",
    "Essen",
    "Bremen",
    "Dresden",
    "Hannover",
    "Nürnberg",
]

METROPOLITAN_HUBS_TIER_3 = [
    "Duisburg",
    "Bochum",
    "Bonn",
    "Münster",
    "Karlsruhe",
    "Mannheim",
    "Augsburg",
    "Wiesbaden",
    "Aachen",
    "Kiel",
    "Braunschweig",
    "Magdeburg",
    "Freiburg im Breisgau",
    "Lübeck",
    "Erfurt",
    "Rostock",
    "Kassel",
    "Potsdam",
    "Saarbrücken",
]

# Mapping of Federal States (Bundesländer) to their major hubs
BUNDESLAND_HUBS = {
    "baden-württemberg": ["Stuttgart", "Karlsruhe", "Mannheim", "Freiburg im Breisgau"],
    "bayern": ["München", "Nürnberg", "Augsburg", "Regensburg", "Würzburg"],
    "berlin": ["Berlin"],
    "brandenburg": ["Potsdam", "Cottbus", "Brandenburg an der Havel"],
    "bremen": ["Bremen", "Bremerhaven"],
    "hamburg": ["Hamburg"],
    "hessen": ["Frankfurt am Main", "Wiesbaden", "Kassel", "Darmstadt"],
    "mecklenburg-vorpommern": ["Rostock", "Schwerin", "Neubrandenburg"],
    "niedersachsen": ["Hannover", "Braunschweig", "Osnabrück", "Oldenburg"],
    "nordrhein-westfalen": ["Köln", "Düsseldorf", "Dortmund", "Essen", "Bonn", "Münster", "Aachen"],
    "rheinland-pfalz": ["Mainz", "Ludwigshafen", "Koblenz", "Trier"],
    "saarland": ["Saarbrücken", "Neunkirchen", "Homburg"],
    "sachsen": ["Leipzig", "Dresden", "Chemnitz"],
    "sachsen-anhalt": ["Magdeburg", "Halle (Saale)", "Dessau-Roßlau"],
    "schleswig-holstein": ["Kiel", "Lübeck", "Flensburg"],
    "thüringen": ["Erfurt", "Jena", "Gera", "Weimar"],
}


class GeographicBatchingEngine:
    """Resolves search locations and batches nationwide queries across metropolitan hubs."""

    @classmethod
    def is_nationwide_query(cls, location: Optional[str]) -> bool:
        clean = str(location or "").strip().lower()
        return (
            not clean
            or clean in {
                "deutschland",
                "bundesweit",
                "germany",
                "alle",
                "all",
                "überall",
                "ueberall",
                "ganz deutschland",
            }
        )

    @classmethod
    def resolve_targets(
        cls,
        location: Optional[str],
        max_hubs: int = 4,
        include_tier_2: bool = False,
    ) -> Dict[str, Any]:
        """
        Resolves a search location input into a structured execution plan.
        - If location is specific (e.g. 'Köln'), returns single local target.
        - If location matches a Bundesland (e.g. 'Bayern'), returns hubs in that state.
        - If location is empty or 'Deutschland', returns top metropolitan economic hubs.
        """
        clean_loc = str(location or "").strip()

        if not cls.is_nationwide_query(clean_loc):
            # Check if user named a Bundesland
            state_key = clean_loc.lower().replace(" ", "-")
            if state_key in BUNDESLAND_HUBS:
                hubs = BUNDESLAND_HUBS[state_key][:max_hubs]
                return {
                    "scope": "federal_state",
                    "is_nationwide": False,
                    "is_regional": True,
                    "matched_state": clean_loc,
                    "region_name": clean_loc,
                    "targets": hubs,
                    "target_cities": hubs,
                    "coverage_label": f"Regionale Suche ({clean_loc}): {len(hubs)} Hauptstädte",
                    "coverage_summary": f"{clean_loc} ({', '.join(hubs)})",
                }

            # Specific city or zip code
            return {
                "scope": "city",
                "is_nationwide": False,
                "is_regional": False,
                "region_name": clean_loc,
                "targets": [clean_loc],
                "target_cities": [clean_loc],
                "coverage_label": f"Lokale Suche: {clean_loc}",
                "coverage_summary": clean_loc,
            }

        # Nationwide search
        pool = list(METROPOLITAN_HUBS_TIER_1)
        if include_tier_2:
            pool.extend(METROPOLITAN_HUBS_TIER_2)

        selected_hubs = pool[:max(1, min(max_hubs, len(pool)))]
        summary_text = (
            f"Bundesweite Stichprobe ({len(selected_hubs)} Metropolen: {', '.join(selected_hubs)})"
        )

        return {
            "scope": "nationwide_sample",
            "is_nationwide": True,
            "is_regional": False,
            "region_name": "Deutschland",
            "targets": selected_hubs,
            "target_cities": selected_hubs,
            "coverage_label": f"Bundesweite Suche ({len(selected_hubs)} Metropolregionen)",
            "coverage_summary": summary_text,
            "all_available_hubs": pool,
        }


# Global singleton instance
geographic_batching = GeographicBatchingEngine()
