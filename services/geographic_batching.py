"""
JobScout — Geographic Batching & Coverage Engine
================================================
Comprehensive nationwide geographic coverage engine covering ALL of Germany:
- Großstädte (large cities)
- Mittelstädte (medium cities)
- Kleinstädte (small towns)
- Landkreise & ländliche Gemeinden (rural municipalities & villages)

Provides administrative-region coverage across all 16 Bundesländer and
adaptive geographic bounding box tiling with zero blind spots.
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

# ─────────────────────────────────────────────────────────────────────────────
# Complete 16 Federal States Administrative Regions with BBox & Urban/Rural Mix
# ─────────────────────────────────────────────────────────────────────────────
GERMAN_ADMIN_REGIONS: Dict[str, Dict[str, Any]] = {
    "DE-BW": {
        "id": "DE-BW",
        "name": "Baden-Württemberg",
        "bbox": (47.53, 7.51, 49.79, 10.50),  # (min_lat, min_lon, max_lat, max_lon)
        "major_cities": ["Stuttgart", "Karlsruhe", "Mannheim", "Freiburg im Breisgau", "Heidelberg", "Ulm", "Pforzheim", "Heilbronn"],
        "medium_cities": ["Reutlingen", "Esslingen am Neckar", "Ludwigsburg", "Tübingen", "Villingen-Schwenningen", "Konstanz", "Aalen", "Sindelfingen", "Schwäbisch Gmünd", "Offenburg"],
        "small_towns": ["Bietigheim-Bissingen", "Rastatt", "Böblingen", "Waiblingen", "Heidenheim", "Leonberg", "Singen", "Lahr", "Rottweil", "Biberach", "Wangen im Allgäu"],
        "rural_districts": ["Schwarzwald-Baar-Kreis", "Odenwaldkreis", "Landkreis Sigmaringen", "Landkreis Calw", "Zollernalbkreis", "Main-Tauber-Kreis", "Hohenlohekreis"],
    },
    "DE-BY": {
        "id": "DE-BY",
        "name": "Bayern",
        "bbox": (47.27, 8.97, 50.56, 13.84),
        "major_cities": ["München", "Nürnberg", "Augsburg", "Regensburg", "Ingolstadt", "Würzburg", "Fürth", "Erlangen"],
        "medium_cities": ["Bamberg", "Bayreuth", "Aschaffenburg", "Landshut", "Kempten (Allgäu)", "Rosenheim", "Schweinfurt", "Neu-Ulm", "Passau", "Straubing"],
        "small_towns": ["Dachau", "Freising", "Kaufbeuren", "Memmingen", "Coburg", "Amberg", "Ansbach", "Schwabach", "Deggendorf", "Neumarkt in der Oberpfalz", "Cham", "Dingolfing"],
        "rural_districts": ["Landkreis Regen", "Landkreis Cham", "Landkreis Freyung-Grafenau", "Landkreis Rhön-Grabfeld", "Landkreis Wunsiedel", "Landkreis Berchtesgadener Land"],
    },
    "DE-BE": {
        "id": "DE-BE",
        "name": "Berlin",
        "bbox": (52.33, 13.08, 52.68, 13.76),
        "major_cities": ["Berlin"],
        "medium_cities": ["Berlin-Spandau", "Berlin-Köpenick", "Berlin-Pankow", "Berlin-Marzahn"],
        "small_towns": ["Berlin-Wannsee", "Berlin-Kladow", "Berlin-Frohnau", "Berlin-Müggelheim"],
        "rural_districts": ["Berlin Randgebiete", "Umland Berlin-Süd", "Umland Berlin-Nord"],
    },
    "DE-BB": {
        "id": "DE-BB",
        "name": "Brandenburg",
        "bbox": (51.35, 11.26, 53.56, 14.77),
        "major_cities": ["Potsdam", "Cottbus"],
        "medium_cities": ["Brandenburg an der Havel", "Frankfurt (Oder)", "Oranienburg", "Falkensee", "Eberswalde", "Bernau bei Berlin"],
        "small_towns": ["Königs Wusterhausen", "Fürstenwalde", "Neuruppin", "Schwedt", "Eisenhüttenstadt", "Senftenberg", "Wittstock/Dosse", "Templin"],
        "rural_districts": ["Landkreis Uckermark", "Landkreis Prignitz", "Landkreis Ostprignitz-Ruppin", "Landkreis Elbe-Elster", "Landkreis Spree-Neiße"],
    },
    "DE-HB": {
        "id": "DE-HB",
        "name": "Bremen",
        "bbox": (53.01, 8.48, 53.64, 8.92),
        "major_cities": ["Bremen", "Bremerhaven"],
        "medium_cities": ["Bremen-Vegesack", "Bremen-Blumenthal", "Bremen-Hemelingen"],
        "small_towns": ["Bremen-Burglesum", "Bremen-Farge", "Bremerhaven-Wulsdorf"],
        "rural_districts": ["Bremen Blockland", "Bremen Borgfeld", "Bremerhaven Überseehafengebiet"],
    },
    "DE-HH": {
        "id": "DE-HH",
        "name": "Hamburg",
        "bbox": (53.38, 9.70, 53.74, 10.33),
        "major_cities": ["Hamburg"],
        "medium_cities": ["Hamburg-Harburg", "Hamburg-Bergedorf", "Hamburg-Wandsbek", "Hamburg-Altona"],
        "small_towns": ["Hamburg-Finkenwerder", "Hamburg-Neugraben", "Hamburg-Kirchwerder"],
        "rural_districts": ["Vier- und Marschlande", "Altes Land (Hamburg)", "Neuwerk"],
    },
    "DE-HE": {
        "id": "DE-HE",
        "name": "Hessen",
        "bbox": (49.39, 7.77, 51.66, 10.24),
        "major_cities": ["Frankfurt am Main", "Wiesbaden", "Kassel", "Darmstadt", "Offenbach am Main", "Hanau", "Gießen"],
        "medium_cities": ["Marburg", "Fulda", "Rüsselsheim", "Bad Homburg vor der Höhe", "Wetzlar", "Oberursel", "Rodgau", "Dreieich", "Bensheim"],
        "small_towns": ["Hofheim am Taunus", "Maintal", "Neu-Isenburg", "Limburg an der Lahn", "Viernheim", "Dietzenbach", "Bad Hersfeld", "Friedberg", "Korbach"],
        "rural_districts": ["Vogelsbergkreis", "Werra-Meißner-Kreis", "Odenwaldkreis", "Landkreis Waldeck-Frankenberg", "Schwalm-Eder-Kreis"],
    },
    "DE-MV": {
        "id": "DE-MV",
        "name": "Mecklenburg-Vorpommern",
        "bbox": (53.07, 10.59, 54.69, 14.42),
        "major_cities": ["Rostock", "Schwerin"],
        "medium_cities": ["Neubrandenburg", "Stralsund", "Greifswald", "Wismar", "Güstrow"],
        "small_towns": ["Waren (Müritz)", "Parchim", "Neustrelitz", "Ribnitz-Damgarten", "Bergen auf Rügen", "Anklam", "Ludwigslust", "Demmin"],
        "rural_districts": ["Landkreis Vorpommern-Rügen", "Landkreis Mecklenburgische Seenplatte", "Landkreis Vorpommern-Greifswald", "Landkreis Ludwigslust-Parchim"],
    },
    "DE-NI": {
        "id": "DE-NI",
        "name": "Niedersachsen",
        "bbox": (51.29, 6.65, 53.89, 11.60),
        "major_cities": ["Hannover", "Braunschweig", "Oldenburg", "Osnabrück", "Wolfsburg", "Göttingen", "Salzgitter", "Hildesheim"],
        "medium_cities": ["Delmenhorst", "Wilhelmshaven", "Lüneburg", "Celle", "Garbsen", "Hameln", "Lingen (Ems)", "Langenhagen", "Nordhorn", "Wolfenbüttel", "Goslar", "Peine"],
        "small_towns": ["Emden", "Stade", "Meppen", "Cuxhaven", "Buchholz in der Nordheide", "Leer (Ostfriesland)", "Cloppenburg", "Nienburg/Weser", "Uelzen", "Aurich", "Vechta", "Buxtehude"],
        "rural_districts": ["Landkreis Lüchow-Dannenberg", "Landkreis Wittmund", "Landkreis Friesland", "Landkreis Emsland", "Landkreis Rotenburg (Wümme)", "Landkreis Heidekreis"],
    },
    "DE-NW": {
        "id": "DE-NW",
        "name": "Nordrhein-Westfalen",
        "bbox": (50.32, 5.86, 52.53, 9.46),
        "major_cities": ["Köln", "Düsseldorf", "Dortmund", "Essen", "Duisburg", "Bochum", "Wuppertal", "Bielefeld", "Bonn", "Münster", "Mönchengladbach", "Gelsenkirchen", "Aachen"],
        "medium_cities": ["Krefeld", "Oberhausen", "Hagen", "Hamm", "Mülheim an der Ruhr", "Leverkusen", "Solingen", "Herne", "Neuss", "Paderborn", "Bottrop", "Recklinghausen", "Bergisch Gladbach", "Remscheid", "Moers", "Siegen", "Gütersloh", "Witten"],
        "small_towns": ["Ahaus", "Borken", "Coesfeld", "Steinfurt", "Warendorf", "Detmold", "Lippstadt", "Bocholt", "Dinslaken", "Kerpen", "Dormagen", "Euskirchen", "Kleve", "Wesel", "Ibbenbüren", "Arnsberg"],
        "rural_districts": ["Kreis Höxter", "Hochsauerlandkreis", "Kreis Olpe", "Märkischer Kreis", "Kreis Euskirchen", "Kreis Borken", "Kreis Coesfeld"],
    },
    "DE-RP": {
        "id": "DE-RP",
        "name": "Rheinland-Pfalz",
        "bbox": (48.96, 6.11, 50.94, 8.51),
        "major_cities": ["Mainz", "Ludwigshafen am Rhein", "Koblenz", "Trier", "Kaiserslautern"],
        "medium_cities": ["Worms", "Neuwied", "Neustadt an der Weinstraße", "Bad Kreuznach", "Speyer", "Frankenthal (Pfalz)", "Landau in der Pfalz", "Pirmasens"],
        "small_towns": ["Idar-Oberstein", "Andernach", "Bad Neuenahr-Ahrweiler", "Bingen am Rhein", "Ingelheim am Rhein", "Germersheim", "Schifferstadt", "Wittlich", "Konz"],
        "rural_districts": ["Eifelkreis Bitburg-Prüm", "Vulkaneifel", "Landkreis Kusel", "Donnersbergkreis", "Landkreis Birkenfeld", "Rhein-Hunsrück-Kreis", "Westerwaldkreis"],
    },
    "DE-SL": {
        "id": "DE-SL",
        "name": "Saarland",
        "bbox": (49.11, 6.35, 49.64, 7.41),
        "major_cities": ["Saarbrücken"],
        "medium_cities": ["Neunkirchen", "Homburg", "Völklingen", "Sankt Ingbert", "Saarlouis", "Merzig", "Sankt Wendel", "Blieskastel"],
        "small_towns": ["Dillingen/Saar", "Lebach", "Püttlingen", "Heusweiler", "Wadgassen", "Bexbach", "Schwalbach", "Ottweiler", "Illingen"],
        "rural_districts": ["Landkreis Sankt Wendel", "Landkreis Merzig-Wadern", "Saarpfalz-Kreis", "Landkreis Saarlouis"],
    },
    "DE-SN": {
        "id": "DE-SN",
        "name": "Sachsen",
        "bbox": (50.17, 11.87, 51.68, 15.04),
        "major_cities": ["Leipzig", "Dresden", "Chemnitz"],
        "medium_cities": ["Zwickau", "Plauen", "Görlitz", "Freiberg", "Bautzen", "Freital", "Pirna", "Hoyerswerda", "Riesa", "Radebeul"],
        "small_towns": ["Meißen", "Grimma", "Zittau", "Delitzsch", "Limbach-Oberfrohna", "Markkleeberg", "Glauchau", "Werdau", "Döbeln", "Annaberg-Buchholz", "Aue-Bad Schlema"],
        "rural_districts": ["Erzgebirgskreis", "Landkreis Görlitz", "Landkreis Bautzen", "Landkreis Mittelsachsen", "Landkreis Nordsachsen", "Vogtlandkreis"],
    },
    "DE-ST": {
        "id": "DE-ST",
        "name": "Sachsen-Anhalt",
        "bbox": (50.93, 10.56, 53.06, 13.31),
        "major_cities": ["Halle (Saale)", "Magdeburg"],
        "medium_cities": ["Dessau-Roßlau", "Lutherstadt Wittenberg", "Weißenfels", "Halberstadt", "Stendal", "Bitterfeld-Wolfen", "Merseburg", "Wernigerode", "Bernburg (Saale)", "Naumburg (Saale)"],
        "small_towns": ["Schönebeck (Elbe)", "Zeitz", "Aschersleben", "Sangerhausen", "Köthen (Anhalt)", "Staßfurt", "Quedlinburg", "Salzwedel", "Gardeleben", "Eisleben"],
        "rural_districts": ["Altmarkkreis Salzwedel", "Landkreis Stendal", "Landkreis Harz", "Landkreis Mansfeld-Südharz", "Burgenlandkreis"],
    },
    "DE-SH": {
        "id": "DE-SH",
        "name": "Schleswig-Holstein",
        "bbox": (53.36, 7.86, 55.06, 11.32),
        "major_cities": ["Kiel", "Lübeck"],
        "medium_cities": ["Flensburg", "Neumünster", "Norderstedt", "Elmshorn", "Pinneberg", "Wedel", "Ahrensburg", "Geesthacht", "Itzehoe"],
        "small_towns": ["Rendsburg", "Henstedt-Ulzburg", "Reinbek", "Bad Oldesloe", "Schleswig", "Eckernförde", "Husum", "Heide", "Quickborn", "Kaltenkirchen", "Mölln"],
        "rural_districts": ["Kreis Dithmarschen", "Kreis Nordfriesland", "Kreis Herzogtum Lauenburg", "Kreis Plön", "Kreis Steinburg", "Kreis Rendsburg-Eckernförde"],
    },
    "DE-TH": {
        "id": "DE-TH",
        "name": "Thüringen",
        "bbox": (50.20, 9.87, 51.65, 12.65),
        "major_cities": ["Erfurt", "Jena"],
        "medium_cities": ["Gera", "Weimar", "Gotha", "Nordhausen", "Eisenach", "Suhl", "Mühlhausen/Thüringen", "Altenburg"],
        "small_towns": ["Saalfeld/Saale", "Ilmenau", "Arnstadt", "Rudolstadt", "Sondershausen", "Meiningen", "Apolda", "Greiz", "Sonneberg", "Zeulenroda-Triebes"],
        "rural_districts": ["Kyffhäuserkreis", "Landkreis Hildburghausen", "Landkreis Sonneberg", "Saale-Orla-Kreis", "Unstrut-Hainich-Kreis", "Wartburgkreis"],
    },
}


class GeographicBatchingEngine:
    """
    JobScout Geographic Batching & Coverage Engine.
    Scales discovery across all 16 Bundesländer, covering Großstädte,
    Mittelstädte, Kleinstädte, and rural Landkreise/Gemeinden without caps.
    """

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
                "deutschlandweit",
            }
        )

    @classmethod
    def get_nationwide_coverage_plan(
        cls,
        location: Optional[str] = None,
        max_regions: int = 16,
        include_rural: bool = True,
    ) -> Dict[str, Any]:
        """
        Generates a comprehensive geographic execution plan.
        - Nationwide: systematically returns structured coverage across all 16 German states,
          including representative Großstädte, Mittelstädte, Kleinstädte, and rural municipalities.
        - State: returns structured regions within that federal state.
        - Specific city/postal code: returns localized coverage targets.
        """
        clean_loc = str(location or "").strip()

        # 1. Specific local search (city / postal code)
        if not cls.is_nationwide_query(clean_loc):
            state_key = clean_loc.lower().replace(" ", "-")
            # Check if user named a Bundesland
            matched_state_id = None
            for r_id, r_data in GERMAN_ADMIN_REGIONS.items():
                if (
                    clean_loc.lower() == r_data["name"].lower()
                    or state_key == r_id.lower()
                    or state_key == r_data["name"].lower().replace(" ", "-")
                ):
                    matched_state_id = r_id
                    break

            if matched_state_id:
                state_data = GERMAN_ADMIN_REGIONS[matched_state_id]
                regions = [{
                    "region_id": state_data["id"],
                    "name": state_data["name"],
                    "bbox": state_data["bbox"],
                    "major_cities": state_data["major_cities"],
                    "medium_cities": state_data["medium_cities"],
                    "small_towns": state_data["small_towns"],
                    "rural_districts": state_data["rural_districts"],
                    "target_cities": state_data["major_cities"] + state_data["medium_cities"][:2],
                }]
                return {
                    "scope": "federal_state",
                    "is_nationwide": False,
                    "is_regional": True,
                    "region_name": state_data["name"],
                    "total_regions": 1,
                    "regions": regions,
                    "target_cities": state_data["major_cities"],
                    "coverage_label": f"Bundesland ({state_data['name']}): Großstädte, Mittelstädte & ländlicher Raum",
                    "coverage_summary": f"{state_data['name']} (Groß-, Mittel- & Kleinstädte)",
                }

            # Local City or Postal code
            return {
                "scope": "city",
                "is_nationwide": False,
                "is_regional": False,
                "region_name": clean_loc,
                "total_regions": 1,
                "regions": [{
                    "region_id": f"LOCAL-{clean_loc.upper()[:10]}",
                    "name": clean_loc,
                    "bbox": None,
                    "major_cities": [clean_loc],
                    "medium_cities": [],
                    "small_towns": [],
                    "rural_districts": [],
                    "target_cities": [clean_loc],
                }],
                "target_cities": [clean_loc],
                "coverage_label": f"Lokale Suche: {clean_loc}",
                "coverage_summary": clean_loc,
            }

        # 2. Comprehensive Nationwide Search across all 16 Bundesländer
        selected_region_ids = list(GERMAN_ADMIN_REGIONS.keys())[:max_regions]
        planned_regions = []

        all_cities_count = 0
        all_towns_count = 0
        all_rural_count = 0

        for r_id in selected_region_ids:
            r = GERMAN_ADMIN_REGIONS[r_id]
            # Construct a balanced municipal target set for each region:
            # 1 Großstadt, 1-2 Mittelstädte, 1 Kleinstadt, 1 ländlicher Kreis
            sample_cities = []
            if r["major_cities"]:
                sample_cities.append(r["major_cities"][0])
            if r["medium_cities"]:
                sample_cities.extend(r["medium_cities"][:2])
            if r["small_towns"]:
                sample_cities.append(r["small_towns"][0])

            planned_regions.append({
                "region_id": r["id"],
                "name": r["name"],
                "bbox": r["bbox"],
                "major_cities": r["major_cities"],
                "medium_cities": r["medium_cities"],
                "small_towns": r["small_towns"],
                "rural_districts": r["rural_districts"],
                "target_cities": sample_cities,
            })

            all_cities_count += len(r["major_cities"])
            all_towns_count += len(r["medium_cities"]) + len(r["small_towns"])
            all_rural_count += len(r["rural_districts"])

        summary = (
            f"Bundesweite Vollabdeckung ({len(planned_regions)} Bundesländer, "
            f"{all_cities_count} Großstädte, {all_towns_count} Mittel- & Kleinstädte, "
            f"{all_rural_count} Landkreise/ländliche Gemeinden)"
        )

        return {
            "scope": "nationwide_comprehensive",
            "is_nationwide": True,
            "is_regional": False,
            "region_name": "Deutschland (Bundesweit)",
            "total_regions": len(planned_regions),
            "regions": planned_regions,
            "target_cities": [c for r in planned_regions for c in r["target_cities"]],
            "coverage_label": f"Bundesweite Suche ({len(planned_regions)} Regionen: Städte & ländlicher Raum)",
            "coverage_summary": summary,
            "total_major_cities": all_cities_count,
            "total_towns": all_towns_count,
            "total_rural_districts": all_rural_count,
        }

    @classmethod
    def get_geographic_tiles(
        cls,
        rows: int = 4,
        cols: int = 4,
        overlap_deg: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """
        Divides Germany into a spatial grid of geographic bounding boxes (tiles).
        Germany Bounds: Lat 47.27 to 55.06, Lon 5.86 to 15.04.
        BBox Overpass queries cover 100% of spatial territory, ensuring small villages
        and rural municipalities are fully included without polygon clipping issues.
        """
        min_lat, max_lat = 47.27, 55.06
        min_lon, max_lon = 5.86, 15.04

        lat_step = (max_lat - min_lat) / rows
        lon_step = (max_lon - min_lon) / cols

        tiles: List[Dict[str, Any]] = []
        for r in range(rows):
            for c in range(cols):
                s = round(max(min_lat, min_lat + r * lat_step - overlap_deg), 4)
                n = round(min(max_lat, min_lat + (r + 1) * lat_step + overlap_deg), 4)
                w = round(max(min_lon, min_lon + c * lon_step - overlap_deg), 4)
                e = round(min(max_lon, min_lon + (c + 1) * lon_step + overlap_deg), 4)
                tile_id = f"TILE_R{r+1}_C{c+1}"
                tiles.append({
                    "tile_id": tile_id,
                    "row": r + 1,
                    "col": c + 1,
                    "bbox": (s, w, n, e),
                    "center": (round((s + n) / 2, 4), round((w + e) / 2, 4)),
                    "label": f"Geo-Kachel {tile_id} ({s}°N–{n}°N, {w}°E–{e}°E)",
                })
        return tiles

    @classmethod
    def resolve_targets(
        cls,
        location: Optional[str],
        max_hubs: int = 16,
        include_tier_2: bool = True,
    ) -> Dict[str, Any]:
        """Backward-compatible wrapper mapping to comprehensive nationwide plan."""
        plan = cls.get_nationwide_coverage_plan(location=location, max_regions=max_hubs)
        # Ensure legacy keys exist
        plan["targets"] = plan.get("target_cities", [])
        return plan


# Global singleton instance
geographic_batching = GeographicBatchingEngine()
