"""
JobScout — Intelligent Profession-to-Employer Discovery Engine
============================================================
Translates any profession, apprenticeship, or job title into relevant
employer categories, target company types, and location-aware search keywords.

Key features:
1. Normalizes profession titles (strips 'Ausbildung als', gender markers, etc.).
2. Corrects common spelling mistakes (fuzzy matching).
3. Supports German, English, and French profession inputs.
4. Comprehensive offline taxonomy for instant (<5ms) deterministic classification.
5. AI fallback via Central AI Provider Manager (OpenAI / Gemini) for unknown professions.
6. Thread-safe persistent JSON cache in data/profession_intelligence_cache.json.
7. Generates location-aware Google Maps search terms & OpenStreetMap tags.
"""

import difflib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "profession_intelligence_cache.json"

# Common prefixes to strip from user input
PROFESSION_PREFIXES = [
    r"^ausbildung\s+(?:als|zum|zur|für|fuer)\s+",
    r"^lehre\s+(?:als|zum|zur)\s+",
    r"^lehrstelle\s+(?:als|zum|zur)\s+",
    r"^berufsausbildung\s+(?:als|zum|zur)\s+",
    r"^umschulung\s+(?:als|zum|zur)\s+",
    r"^duales\s+studium\s+(?:als|zum|zur|für|fuer)\s+",
    r"^praktikum\s+(?:als|zum|zur|für|fuer)\s+",
    r"^stelle\s+(?:als|zum|zur|für|fuer)\s+",
    r"^job\s+(?:als|zum|zur|für|fuer)\s+",
    r"^trainee\s+(?:als|zum|zur)\s+",
    r"^quereinsteiger\s+(?:als|zum|zur)\s+",
    r"^karriere\s+(?:als|zum|zur)\s+",
    r"^beruf\s+(?:als|zum|zur)\s+",
    r"^arbeit\s+(?:als|zum|zur)\s+",
]

# Suffixes to clean (gender markers, noise tokens)
GENDER_SUFFIXES = [
    r"\s*\(?m[\/\\]w[\/\\]d\)?",
    r"\s*\(?w[\/\\]m[\/\\]d\)?",
    r"\s*\(?d[\/\\]m[\/\\]w\)?",
    r"\s*\(?m[\/\\]f[\/\\]d\)?",
    r"\s*\(?gn\)?",
    r"\s*\(?all\s+genders\)?",
    r"\/in\b",
    r"\/innen\b",
    r"-in\b",
    r"-innen\b",
    r"\*in\b",
    r"\*innen\b",
    r":in\b",
    r":innen\b",
]

# Known spelling errors mapped to canonical tokens
TYPO_CORRECTIONS = {
    "fachinforamtiker": "Fachinformatiker",
    "fachinformatik": "Fachinformatiker",
    "fachinformatikerin": "Fachinformatiker",
    "informatiker": "Fachinformatiker",
    "informatik": "Fachinformatiker",
    "systemintegrator": "Fachinformatiker Systemintegration",
    "anwendungsentwickler": "Fachinformatiker Anwendungsentwicklung",
    "pflegfachmann": "Pflegefachmann",
    "pflegefachfrau": "Pflegefachmann",
    "pflegefachkraft": "Pflegefachmann",
    "altenpfleger": "Pflegefachmann",
    "altenpflege": "Pflegefachmann",
    "krankenpfleger": "Pflegefachmann",
    "krankenschwester": "Pflegefachmann",
    "gesundheits- und krankenpfleger": "Pflegefachmann",
    "kochh": "Koch",
    "köchin": "Koch",
    "kochin": "Koch",
    "kochen": "Koch",
    "verkaeufer": "Verkäufer",
    "verkaufer": "Verkäufer",
    "verkäuferin": "Verkäufer",
    "einzelhandelskaufmann": "Verkäufer",
    "kaufmann im einzelhandel": "Verkäufer",
    "mechatronik": "Kfz-Mechatroniker",
    "kfz mechatroniker": "Kfz-Mechatroniker",
    "kfz-mechaniker": "Kfz-Mechatroniker",
    "automechaniker": "Kfz-Mechatroniker",
    "kfz schlosser": "Kfz-Mechatroniker",
    "elecktroniker": "Elektroniker",
    "elektriker": "Elektroniker",
    "elektroinstallateur": "Elektroniker",
    "elektro": "Elektroniker",
    "schreiner": "Tischler",
    "schreinerei": "Tischler",
    "tischlerei": "Tischler",
    "mfa": "Medizinische Fachangestellte",
    "arzthelferin": "Medizinische Fachangestellte",
    "arzthelfer": "Medizinische Fachangestellte",
    "zfa": "Zahnmedizinische Fachangestellte",
    "zahnarzthelferin": "Zahnmedizinische Fachangestellte",
    "hotelfach": "Hotelfachmann",
    "hotelfachfrau": "Hotelfachmann",
    "hotelkaufmann": "Hotelfachmann",
    "bürokaufmann": "Kaufmann für Büromanagement",
    "buerokaufmann": "Kaufmann für Büromanagement",
    "bürokraft": "Kaufmann für Büromanagement",
    "kaufmann fuer bueromanagement": "Kaufmann für Büromanagement",
}

# Multilingual translation dictionary (English & French -> Canonical German)
MULTILINGUAL_MAP = {
    # English
    "cook": "Koch",
    "chef": "Koch",
    "chef de cuisine": "Koch",
    "line cook": "Koch",
    "baker": "Bäcker",
    "pastry chef": "Konditor",
    "nurse": "Pflegefachmann",
    "nursing": "Pflegefachmann",
    "healthcare assistant": "Pflegefachmann",
    "registered nurse": "Pflegefachmann",
    "care worker": "Pflegefachmann",
    "software developer": "Fachinformatiker",
    "software engineer": "Fachinformatiker",
    "developer": "Fachinformatiker",
    "web developer": "Fachinformatiker",
    "programmer": "Fachinformatiker",
    "it specialist": "Fachinformatiker",
    "it technician": "Fachinformatiker",
    "system administrator": "Fachinformatiker Systemintegration",
    "devops engineer": "Fachinformatiker Systemintegration",
    "car mechanic": "Kfz-Mechatroniker",
    "auto mechanic": "Kfz-Mechatroniker",
    "automotive technician": "Kfz-Mechatroniker",
    "mechanic": "Kfz-Mechatroniker",
    "salesperson": "Verkäufer",
    "retail clerk": "Verkäufer",
    "cashier": "Verkäufer",
    "shop assistant": "Verkäufer",
    "electrician": "Elektroniker",
    "electrical technician": "Elektroniker",
    "carpenter": "Tischler",
    "joiner": "Tischler",
    "medical assistant": "Medizinische Fachangestellte",
    "dental assistant": "Zahnmedizinische Fachangestellte",
    "hotel manager": "Hotelfachmann",
    "hotel receptionist": "Hotelfachmann",
    "office clerk": "Kaufmann für Büromanagement",
    "administrative assistant": "Kaufmann für Büromanagement",
    "plumber": "Anlagenmechaniker SHK",
    "painter": "Maler und Lackierer",
    "roofer": "Dachdecker",
    "bricklayer": "Maurer",
    "logistics clerk": "Fachkraft für Lagerlogistik",
    "warehouse clerk": "Fachkraft für Lagerlogistik",
    "educator": "Erzieher",
    "kindergarten teacher": "Erzieher",
    "banker": "Bankkaufmann",
    "tax assistant": "Steuerfachangestellter",

    # French
    "cuisinier": "Koch",
    "cuisiniere": "Koch",
    "chef cuisinier": "Koch",
    "commis de cuisine": "Koch",
    "boulanger": "Bäcker",
    "patissier": "Konditor",
    "infirmier": "Pflegefachmann",
    "infirmiere": "Pflegefachmann",
    "aide soignant": "Pflegefachmann",
    "aide-soignant": "Pflegefachmann",
    "soignant": "Pflegefachmann",
    "developpeur": "Fachinformatiker",
    "developpeur web": "Fachinformatiker",
    "informaticien": "Fachinformatiker",
    "technicien informatique": "Fachinformatiker",
    "administrateur systeme": "Fachinformatiker Systemintegration",
    "mecanicien": "Kfz-Mechatroniker",
    "mecanicien auto": "Kfz-Mechatroniker",
    "garagiste": "Kfz-Mechatroniker",
    "vendeur": "Verkäufer",
    "vendeuse": "Verkäufer",
    "commercial": "Verkäufer",
    "electricien": "Elektroniker",
    "menuisier": "Tischler",
    "charpentier": "Tischler",
    "secretaire medicale": "Medizinische Fachangestellte",
    "assistant dentaire": "Zahnmedizinische Fachangestellte",
    "hotellier": "Hotelfachmann",
    "receptionniste": "Hotelfachmann",
    "secretaire": "Kaufmann für Büromanagement",
    "plombier": "Anlagenmechaniker SHK",
    "peintre en batiment": "Maler und Lackierer",
    "couvreur": "Dachdecker",
    "macon": "Maurer",
    "logisticien": "Fachkraft für Lagerlogistik",
    "magasinier": "Fachkraft für Lagerlogistik",
    "educateur": "Erzieher",
    "banquier": "Bankkaufmann",
    "comptable": "Steuerfachangestellter",
}

# ---------------------------------------------------------------------------
# Comprehensive Local Profession Taxonomy & Employer Category Map
# ---------------------------------------------------------------------------
# Each canonical entry contains:
# - sector: German occupational sector
# - synonyms: list of alternative job/specialization titles
# - employer_categories: list of dicts with category, relevance (0.0-1.0),
#   search_term (for Maps), and osm_tags (for Overpass API).
# ---------------------------------------------------------------------------

PROFESSION_TAXONOMY: Dict[str, Dict[str, Any]] = {
    # ── Gastronomie & Hotellerie ───────────────────────────────────────────
    "Koch": {
        "sector": "Gastronomie & Hotellerie",
        "synonyms": ["Köchin", "Jungkoch", "Beikoch", "Chef de Partie", "Sous Chef", "Küchenchef"],
        "employer_categories": [
            {
                "category": "Restaurant",
                "relevance": 1.0,
                "search_term": "Restaurant Gaststätte",
                "osm_tags": ["node['amenity'='restaurant']", "way['amenity'='restaurant']"],
            },
            {
                "category": "Hotel & Gastgewerbe",
                "relevance": 0.98,
                "search_term": "Hotel Restaurant Gasthof",
                "osm_tags": ["node['tourism'='hotel']", "way['tourism'='hotel']"],
            },
            {
                "category": "Catering & Partyservice",
                "relevance": 0.92,
                "search_term": "Catering Partyservice Eventgastronomie",
                "osm_tags": ["node['craft'='caterer']", "way['craft'='caterer']"],
            },
            {
                "category": "Kantine & Betriebsgastronomie",
                "relevance": 0.88,
                "search_term": "Kantine Großküche Betriebsgastronomie",
                "osm_tags": ["node['amenity'='canteen']", "way['amenity'='canteen']"],
            },
            {
                "category": "Klinik- & Seniorenküchen",
                "relevance": 0.82,
                "search_term": "Krankenhaus Seniorenheim Küche",
                "osm_tags": ["node['amenity'='hospital']", "node['amenity'='nursing_home']"],
            },
        ],
    },
    "Hotelfachmann": {
        "sector": "Gastronomie & Hotellerie",
        "synonyms": ["Hotelfachfrau", "Hotelkaufmann", "Hotelbetriebswirt", "Hotelier"],
        "employer_categories": [
            {
                "category": "Hotel",
                "relevance": 1.0,
                "search_term": "Hotel Residenz Tagungshotel",
                "osm_tags": ["node['tourism'='hotel']", "way['tourism'='hotel']"],
            },
            {
                "category": "Resort & Wellnesshotel",
                "relevance": 0.95,
                "search_term": "Wellnesshotel Kurhotel Resort",
                "osm_tags": ["node['tourism'='hotel']"],
            },
            {
                "category": "Gasthof & Pension",
                "relevance": 0.88,
                "search_term": "Gasthof Pension Gästehaus",
                "osm_tags": ["node['tourism'='guest_house']"],
            },
            {
                "category": "Event- & Tagungszentrum",
                "relevance": 0.82,
                "search_term": "Veranstaltungszentrum Eventlocation Tagungszentrum",
                "osm_tags": ["node['amenity'='events_venue']"],
            },
        ],
    },
    "Bäcker": {
        "sector": "Ernährung & Lebensmittelhandwerk",
        "synonyms": ["Bäckermeister", "Bäckereifachverkäufer", "Konditor"],
        "employer_categories": [
            {
                "category": "Bäckerei",
                "relevance": 1.0,
                "search_term": "Bäckerei Backstube Meisterbäcker",
                "osm_tags": ["node['shop'='bakery']", "way['shop'='bakery']"],
            },
            {
                "category": "Konditorei & Café",
                "relevance": 0.92,
                "search_term": "Konditorei Cafe Feinbäckerei",
                "osm_tags": ["node['shop'='pastry']", "node['amenity'='cafe']"],
            },
            {
                "category": "Großbäckerei & Backwarenhersteller",
                "relevance": 0.85,
                "search_term": "Großbäckerei Backwaren Produktion",
                "osm_tags": ["node['craft'='bakery']"],
            },
        ],
    },
    "Konditor": {
        "sector": "Ernährung & Lebensmittelhandwerk",
        "synonyms": ["Konditormeister", "Pâtissier", "Chocolatier"],
        "employer_categories": [
            {
                "category": "Konditorei & Patisserie",
                "relevance": 1.0,
                "search_term": "Konditorei Patisserie Confiserie",
                "osm_tags": ["node['shop'='pastry']", "way['shop'='pastry']"],
            },
            {
                "category": "Café & Confiserie",
                "relevance": 0.95,
                "search_term": "Kaffeehaus Cafe Chocolaterie",
                "osm_tags": ["node['amenity'='cafe']"],
            },
            {
                "category": "Hotelpatisserie",
                "relevance": 0.85,
                "search_term": "Hotel Restaurant Pâtisserie",
                "osm_tags": ["node['tourism'='hotel']"],
            },
        ],
    },

    # ── Gesundheit & Pflege ────────────────────────────────────────────────
    "Pflegefachmann": {
        "sector": "Gesundheitswesen & Pflege",
        "synonyms": [
            "Pflegefachfrau", "Gesundheits- und Krankenpfleger", "Altenpfleger",
            "Pflegekraft", "Krankenpfleger", "Krankenschwester", "Altenpflegehelfer",
        ],
        "employer_categories": [
            {
                "category": "Krankenhaus & Klinik",
                "relevance": 1.0,
                "search_term": "Krankenhaus Klinik Klinikum",
                "osm_tags": ["node['amenity'='hospital']", "way['amenity'='hospital']", "node['amenity'='clinic']"],
            },
            {
                "category": "Pflegeheim & Seniorenheim",
                "relevance": 0.98,
                "search_term": "Pflegeheim Seniorenheim Seniorenresidenz",
                "osm_tags": ["node['amenity'='nursing_home']", "way['amenity'='nursing_home']"],
            },
            {
                "category": "Ambulanter Pflegedienst",
                "relevance": 0.94,
                "search_term": "Ambulanter Pflegedienst Diakonie Caritas Hauskrankenpflege",
                "osm_tags": ["node['healthcare'='nurse']", "office['healthcare'='nurse']", "node['office'='charity']"],
            },
            {
                "category": "Rehabilitationsklinik",
                "relevance": 0.88,
                "search_term": "Rehaklinik Rehabilitationszentrum Kurklinik",
                "osm_tags": ["node['amenity'='rehabilitation']", "way['amenity'='rehabilitation']"],
            },
            {
                "category": "Hospiz & Palliativpflege",
                "relevance": 0.80,
                "search_term": "Hospiz Palliativzentrum",
                "osm_tags": ["node['amenity'='hospice']"],
            },
        ],
    },
    "Medizinische Fachangestellte": {
        "sector": "Gesundheitswesen & Medizin",
        "synonyms": ["MFA", "Arzthelferin", "Arzthelfer", "Praxisassistent"],
        "employer_categories": [
            {
                "category": "Arztpraxis & Ärztezentrum",
                "relevance": 1.0,
                "search_term": "Arztpraxis Facharzt Gemeinschaftspraxis",
                "osm_tags": ["node['amenity'='doctors']", "way['amenity'='doctors']"],
            },
            {
                "category": "Medizinisches Versorgungszentrum (MVZ)",
                "relevance": 0.98,
                "search_term": "Medizinisches Versorgungszentrum MVZ Gesundheitszentrum",
                "osm_tags": ["node['amenity'='clinic']", "way['amenity'='clinic']"],
            },
            {
                "category": "Klinikambulanz & Krankenhaus",
                "relevance": 0.90,
                "search_term": "Krankenhaus Poliklinik Institutsambulanz",
                "osm_tags": ["node['amenity'='hospital']"],
            },
            {
                "category": "Betriebsärztlicher Dienst",
                "relevance": 0.78,
                "search_term": "Arbeitsmedizinisches Zentrum Betriebsärztlicher Dienst",
                "osm_tags": ["node['office'='company']"],
            },
        ],
    },
    "Zahnmedizinische Fachangestellte": {
        "sector": "Gesundheitswesen & Zahnmedizin",
        "synonyms": ["ZFA", "Zahnarzthelferin", "Zahnarzthelfer", "Dentalhygieniker"],
        "employer_categories": [
            {
                "category": "Zahnarztpraxis",
                "relevance": 1.0,
                "search_term": "Zahnarzt Zahnarztpraxis Gemeinschaftspraxis",
                "osm_tags": ["node['amenity'='dentist']", "way['amenity'='dentist']"],
            },
            {
                "category": "Kieferorthopädische Praxis",
                "relevance": 0.95,
                "search_term": "Kieferorthopäde Kieferorthopädische Praxis",
                "osm_tags": ["node['amenity'='dentist']"],
            },
            {
                "category": "Zahnklinik & Mund-Kiefer-Gesichtschirurgie",
                "relevance": 0.90,
                "search_term": "Zahnklinik MKG-Chirurgie",
                "osm_tags": ["node['amenity'='clinic']"],
            },
        ],
    },
    "Physiotherapeut": {
        "sector": "Gesundheitswesen & Therapie",
        "synonyms": ["Physiotherapeutin", "Krankengymnast", "Sportphysiotherapeut"],
        "employer_categories": [
            {
                "category": "Physiotherapiepraxis",
                "relevance": 1.0,
                "search_term": "Physiotherapie Krankengymnastik Praxis",
                "osm_tags": ["node['healthcare'='physiotherapist']", "way['healthcare'='physiotherapist']"],
            },
            {
                "category": "Rehazentrum & Kliniken",
                "relevance": 0.92,
                "search_term": "Rehazentrum Kurklinik Sportklinik",
                "osm_tags": ["node['amenity'='clinic']", "node['amenity'='hospital']"],
            },
            {
                "category": "Fitness- & Gesundheitscenter",
                "relevance": 0.80,
                "search_term": "Gesundheitszentrum Sporttherapie",
                "osm_tags": ["node['leisure'='fitness_centre']"],
            },
        ],
    },

    # ── IT & Informatik ───────────────────────────────────────────────────
    "Fachinformatiker": {
        "sector": "IT & Softwareentwicklung",
        "synonyms": [
            "Fachinformatikerin", "Softwareentwickler", "Informatiker", "Programmierer",
            "Webentwickler", "Fullstack Developer", "Frontend Entwickler", "Backend Entwickler",
        ],
        "employer_categories": [
            {
                "category": "Softwareunternehmen & SaaS",
                "relevance": 1.0,
                "search_term": "Softwareunternehmen Softwareentwicklung Softwarehaus",
                "osm_tags": ["node['office'='it']", "node['office'='software']", "way['office'='it']"],
            },
            {
                "category": "IT-Dienstleister & IT-Consulting",
                "relevance": 0.98,
                "search_term": "IT-Dienstleister IT-Beratung IT-Consulting",
                "osm_tags": ["node['office'='it']", "way['office'='it']"],
            },
            {
                "category": "IT-Systemhaus",
                "relevance": 0.94,
                "search_term": "IT-Systemhaus Systemhaus EDV-Systemhaus",
                "osm_tags": ["node['office'='it']", "shop['computer']"],
            },
            {
                "category": "Digital- & Webagentur",
                "relevance": 0.90,
                "search_term": "Webagentur Digitalagentur Internetagentur",
                "osm_tags": ["node['office'='advertising_agency']", "node['office'='it']"],
            },
            {
                "category": "Unternehmens-IT & Rechenzentren",
                "relevance": 0.85,
                "search_term": "Rechenzentrum IT-Service Hosting",
                "osm_tags": ["node['office'='company']", "node['telecom'='data_center']"],
            },
        ],
    },
    "Fachinformatiker Systemintegration": {
        "sector": "IT & Telekommunikation",
        "synonyms": [
            "Systemadministrator", "Netzwerkadministrator", "IT-Support Spezialist",
            "DevOps Engineer", "Cloud Engineer", "IT-Systemelektroniker",
        ],
        "employer_categories": [
            {
                "category": "IT-Systemhaus & Managed Services",
                "relevance": 1.0,
                "search_term": "IT-Systemhaus Systemhaus IT-Infrastruktur",
                "osm_tags": ["node['office'='it']", "way['office'='it']"],
            },
            {
                "category": "IT-Dienstleister & Netzwerklösungen",
                "relevance": 0.98,
                "search_term": "IT-Dienstleister Netzwerktechnik IT-Service",
                "osm_tags": ["node['office'='it']"],
            },
            {
                "category": "Rechenzentrum & Cloud Provider",
                "relevance": 0.92,
                "search_term": "Rechenzentrum Cloud-Dienste Data Center Hosting",
                "osm_tags": ["node['telecom'='data_center']", "node['office'='it']"],
            },
            {
                "category": "Softwareunternehmen & Softwarehaus",
                "relevance": 0.88,
                "search_term": "Softwareunternehmen Softwarehaus Softwareentwicklung",
                "osm_tags": ["node['office'='it']", "way['office'='it']"],
            },
            {
                "category": "Telekommunikationsanbieter",
                "relevance": 0.84,
                "search_term": "Telekommunikation Breitband Internetprovider",
                "osm_tags": ["node['office'='telecommunication']"],
            },
            {
                "category": "Großunternehmen mit eigener IT-Abteilung",
                "relevance": 0.80,
                "search_term": "Industrieunternehmen Firmenzentrale IT-Abteilung",
                "osm_tags": ["node['office'='company']"],
            },
        ],
    },
    "Fachinformatiker Anwendungsentwicklung": {
        "sector": "IT & Softwareentwicklung",
        "synonyms": [
            "Softwareentwickler", "App Entwickler", "Mobile Developer", "Java Entwickler",
            "Python Entwickler", "Web Developer", "Frontend Entwickler",
        ],
        "employer_categories": [
            {
                "category": "Softwarehaus & Softwareunternehmen",
                "relevance": 1.0,
                "search_term": "Softwarehaus Softwareunternehmen Softwareentwicklung",
                "osm_tags": ["node['office'='software']", "node['office'='it']"],
            },
            {
                "category": "Internetagentur & Webentwicklung",
                "relevance": 0.96,
                "search_term": "Webagentur Internetagentur App-Entwicklung",
                "osm_tags": ["node['office'='it']", "node['office'='advertising_agency']"],
            },
            {
                "category": "IT-Consulting & Technologieberatung",
                "relevance": 0.92,
                "search_term": "IT-Consulting Technologieberatung Enterprise Software",
                "osm_tags": ["node['office'='it']"],
            },
            {
                "category": "E-Commerce & Online-Portale",
                "relevance": 0.86,
                "search_term": "E-Commerce Plattform Online-Shop Entwicklung",
                "osm_tags": ["node['office'='it']", "node['office'='company']"],
            },
        ],
    },

    # ── Automotive & Fahrzeugtechnik ──────────────────────────────────────
    "Kfz-Mechatroniker": {
        "sector": "Automobil & Kraftfahrzeugtechnik",
        "synonyms": [
            "Kfz-Mechaniker", "Automechaniker", "Fahrzeugmechatroniker",
            "Nutzfahrzeugmechatroniker", "Karosseriebauer", "Servicetechniker Kfz",
        ],
        "employer_categories": [
            {
                "category": "Autohaus & Vertragswerkstatt",
                "relevance": 1.0,
                "search_term": "Autohaus Vertragswerkstatt Kfz-Betrieb",
                "osm_tags": ["node['shop'='car']", "way['shop'='car']"],
            },
            {
                "category": "Freie Kfz-Meisterwerkstatt",
                "relevance": 0.98,
                "search_term": "Kfz-Werkstatt Autowerkstatt Auto Reparatur Meisterbetrieb",
                "osm_tags": ["node['shop'='car_repair']", "way['shop'='car_repair']", "node['craft'='car_repair']"],
            },
            {
                "category": "Nutzfahrzeug- & Lkw-Werkstatt",
                "relevance": 0.90,
                "search_term": "Nutzfahrzeuge Lkw-Werkstatt Nutzfahrzeugservice",
                "osm_tags": ["node['shop'='truck_repair']", "way['shop'='truck_repair']"],
            },
            {
                "category": "Karosseriebau & Lackiererei",
                "relevance": 0.85,
                "search_term": "Karosseriefachbetrieb Autolackiererei Karosseriebau",
                "osm_tags": ["node['craft'='car_painter']"],
            },
            {
                "category": "Prüfstellen & Pannendienste",
                "relevance": 0.78,
                "search_term": "TÜV DEKRA KÜS Abschleppdienst Prüfstelle",
                "osm_tags": ["node['office'='company']"],
            },
        ],
    },

    # ── Handwerk & Elektrotechnik ─────────────────────────────────────────
    "Elektroniker": {
        "sector": "Elektrotechnik & Handwerk",
        "synonyms": [
            "Elektriker", "Elektroinstallateur", "Elektroniker Energie- und Gebäudetechnik",
            "Elektroniker für Betriebstechnik", "Elektromeister",
        ],
        "employer_categories": [
            {
                "category": "Elektro-Fachbetrieb & Installation",
                "relevance": 1.0,
                "search_term": "Elektroinstallation Elektromeister Elektrobetrieb Elektrofirma",
                "osm_tags": ["node['craft'='electrician']", "way['craft'='electrician']"],
            },
            {
                "category": "Gebäude- & Energietechnik",
                "relevance": 0.95,
                "search_term": "Gebäudetechnik Energietechnik Elektroanlagenbau",
                "osm_tags": ["node['craft'='electrician']", "node['office'='energy']"],
            },
            {
                "category": "Industrie- & Automatisierungstechnik",
                "relevance": 0.90,
                "search_term": "Schaltanlagenbau Automatisierungstechnik Industrieelektronik",
                "osm_tags": ["node['office'='company']"],
            },
            {
                "category": "Photovoltaik- & Solartechnik",
                "relevance": 0.88,
                "search_term": "Photovoltaik Solaranlagen Solartechnik",
                "osm_tags": ["node['craft'='photovoltaic']", "node['shop'='solar']"],
            },
            {
                "category": "Netzbetreiber & Stadtwerke",
                "relevance": 0.82,
                "search_term": "Stadtwerke Energieversorger Stromnetz",
                "osm_tags": ["node['office'='energy_supplier']"],
            },
        ],
    },
    "Anlagenmechaniker SHK": {
        "sector": "Sanitär, Heizung & Klimatechnik",
        "synonyms": ["Klempner", "Installateur", "Gas-Wasser-Installateur", "Heizungsbauer", "Lüftungsbauer"],
        "employer_categories": [
            {
                "category": "Sanitär- & Heizungsbaubetrieb",
                "relevance": 1.0,
                "search_term": "Heizungsbau Sanitärinstallation Klempnerei Meisterbetrieb",
                "osm_tags": ["node['craft'='plumber']", "way['craft'='plumber']"],
            },
            {
                "category": "Klima- & Lüftungstechnik",
                "relevance": 0.94,
                "search_term": "Klimaanlagen Lüftungstechnik Kältetechnik",
                "osm_tags": ["node['craft'='hvac']", "node['craft'='plumber']"],
            },
            {
                "category": "Haustechnik & Gebäudemanagement",
                "relevance": 0.88,
                "search_term": "Haustechnik Gebäudetechnik Facility Management",
                "osm_tags": ["node['office'='company']"],
            },
            {
                "category": "Badausstellung & Badrenovierung",
                "relevance": 0.84,
                "search_term": "Badgestaltung Bäderstudio Sanitärfachgeschäft",
                "osm_tags": ["node['shop'='bathroom_furnishing']"],
            },
        ],
    },
    "Tischler": {
        "sector": "Holzverarbeitung & Handwerk",
        "synonyms": ["Tischlerin", "Schreiner", "Schreinerin", "Tischlermeister", "Möbeltischler"],
        "employer_categories": [
            {
                "category": "Tischlerei & Schreinerei",
                "relevance": 1.0,
                "search_term": "Tischlerei Schreinerei Holzbau Meisterbetrieb",
                "osm_tags": ["node['craft'='carpenter']", "way['craft'='carpenter']"],
            },
            {
                "category": "Möbelmanufaktur & Innenausbau",
                "relevance": 0.95,
                "search_term": "Möbelbau Innenausbau Ladenbau Messebau",
                "osm_tags": ["node['craft'='joiner']", "node['craft'='carpenter']"],
            },
            {
                "category": "Fenster- & Türenbau",
                "relevance": 0.90,
                "search_term": "Fensterbau Türenbau Bauelemente",
                "osm_tags": ["node['craft'='window_construction']"],
            },
            {
                "category": "Küchenstudio & Möbelhaus",
                "relevance": 0.80,
                "search_term": "Küchenstudio Maßanfertigung Möbelhaus",
                "osm_tags": ["node['shop'='kitchen']"],
            },
        ],
    },
    "Maler und Lackierer": {
        "sector": "Ausbau & Handwerk",
        "synonyms": ["Maler", "Malerin", "Lackierer", "Fahrzeuglackierer", "Malermeister"],
        "employer_categories": [
            {
                "category": "Malerbetrieb & Fassadengestaltung",
                "relevance": 1.0,
                "search_term": "Malerbetrieb Malermeister Malerfirma Fassadenanstrich",
                "osm_tags": ["node['craft'='painter']", "way['craft'='painter']"],
            },
            {
                "category": "Fahrzeuglackiererei",
                "relevance": 0.92,
                "search_term": "Autolackiererei Fahrzeuglackierung Karosserielackierung",
                "osm_tags": ["node['craft'='car_painter']"],
            },
            {
                "category": "Trockenbau & Innenausbau",
                "relevance": 0.85,
                "search_term": "Trockenbau Raumgestaltung Bodenbeläge",
                "osm_tags": ["node['craft'='plasterer']"],
            },
        ],
    },
    "Dachdecker": {
        "sector": "Bauhandwerk & Dach",
        "synonyms": ["Dachdeckermeister", "Spengler", "Zimmerer"],
        "employer_categories": [
            {
                "category": "Dachdeckerbetrieb",
                "relevance": 1.0,
                "search_term": "Dachdeckerei Dachdecker Meisterbetrieb Dachsanierung",
                "osm_tags": ["node['craft'='roofer']", "way['craft'='roofer']"],
            },
            {
                "category": "Zimmerei & Holzbau",
                "relevance": 0.92,
                "search_term": "Zimmerei Holzbau Dachstuhl",
                "osm_tags": ["node['craft'='carpenter']"],
            },
            {
                "category": "Bauklempnerei & Spenglerei",
                "relevance": 0.88,
                "search_term": "Bauklempnerei Spenglerei Dacheindeckung",
                "osm_tags": ["node['craft'='tinsmith']"],
            },
        ],
    },

    # ── Handel & Vertrieb ─────────────────────────────────────────────────
    "Verkäufer": {
        "sector": "Handel & Vertrieb",
        "synonyms": [
            "Verkäuferin", "Kaufmann im Einzelhandel", "Einzelhandelskaufmann",
            "Fachverkäufer", "Kassierer", "Handelsfachwirt",
        ],
        "employer_categories": [
            {
                "category": "Einzelhandel & Fachgeschäfte",
                "relevance": 1.0,
                "search_term": "Einzelhandel Fachgeschäft Kaufhaus Modehaus",
                "osm_tags": ["node['shop'='clothes']", "node['shop'='department_store']"],
            },
            {
                "category": "Supermarkt & Lebensmittelhandel",
                "relevance": 0.98,
                "search_term": "Supermarkt Lebensmittelfiliale Discounter",
                "osm_tags": ["node['shop'='supermarket']", "way['shop'='supermarket']"],
            },
            {
                "category": "Baumarkt & Gartencenter",
                "relevance": 0.92,
                "search_term": "Baumarkt Heimwerkermarkt Gartencenter",
                "osm_tags": ["node['shop'='doityourself']", "way['shop'='doityourself']"],
            },
            {
                "category": "Elektronikfachmarkt & Möbelhaus",
                "relevance": 0.90,
                "search_term": "Elektronikfachmarkt Möbelhaus Einrichtungshaus",
                "osm_tags": ["node['shop'='electronics']", "node['shop'='furniture']"],
            },
            {
                "category": "Drogeriemarkt",
                "relevance": 0.86,
                "search_term": "Drogerie Drogeriemarkt Parfümerie",
                "osm_tags": ["node['shop'='chemist']"],
            },
        ],
    },
    "Kaufmann im Groß- und Außenhandel": {
        "sector": "Großhandel & Logistik",
        "synonyms": ["Großhandelskaufmann", "Außenhandelskaufmann", "Vertriebskaufmann"],
        "employer_categories": [
            {
                "category": "Großhandelsunternehmen",
                "relevance": 1.0,
                "search_term": "Großhandel Großhändler Baustoffgroßhandel Elektrogroßhandel",
                "osm_tags": ["node['office'='wholesale']", "node['shop'='wholesale']"],
            },
            {
                "category": "Import & Export Unternehmen",
                "relevance": 0.95,
                "search_term": "Import Export Außenhandel Vertriebsgesellschaft",
                "osm_tags": ["node['office'='company']"],
            },
            {
                "category": "Industriebedarf & Distribution",
                "relevance": 0.88,
                "search_term": "Industriebedarf Technischer Großhandel Handelsvertretung",
                "osm_tags": ["node['office'='company']"],
            },
        ],
    },

    # ── Verwaltung & Wirtschaft ───────────────────────────────────────────
    "Kaufmann für Büromanagement": {
        "sector": "Wirtschaft & Verwaltung",
        "synonyms": [
            "Bürokaufmann", "Bürokaufrau", "Kaufmann für Bürokommunikation",
            "Fachkraft für Büroorganisation", "Assistent der Geschäftsführung",
        ],
        "employer_categories": [
            {
                "category": "Mittelständische Unternehmen & Konzerne",
                "relevance": 1.0,
                "search_term": "Firmenzentrale Verwaltung Unternehmensberatung Dienstleistungen",
                "osm_tags": ["node['office'='company']", "way['office'='company']"],
            },
            {
                "category": "Kanzleien & Notariate",
                "relevance": 0.92,
                "search_term": "Rechtsanwalt Notar Kanzlei Steuerberatung",
                "osm_tags": ["node['office'='lawyer']", "node['office'='tax_advisor']"],
            },
            {
                "category": "Immobilienunternehmen & Hausverwaltungen",
                "relevance": 0.88,
                "search_term": "Hausverwaltung Immobilienbüro Bauträger",
                "osm_tags": ["node['office'='estate_agent']"],
            },
            {
                "category": "Öffentliche Verwaltung & Verbände",
                "relevance": 0.85,
                "search_term": "Stadtverwaltung Behörde Verband Kammer",
                "osm_tags": ["node['office'='government']", "node['amenity'='townhall']"],
            },
        ],
    },
    "Steuerfachangestellter": {
        "sector": "Steuer- & Finanzwesen",
        "synonyms": ["Steuerfachangestellte", "Steuerfachwirt", "Steuerberater Assistent", "Finanzbuchhalter"],
        "employer_categories": [
            {
                "category": "Steuerberatungskanzlei",
                "relevance": 1.0,
                "search_term": "Steuerberater Steuerberatungsgesellschaft Steuerkanzlei",
                "osm_tags": ["node['office'='tax_advisor']", "way['office'='tax_advisor']"],
            },
            {
                "category": "Wirtschaftsprüfungsgesellschaft",
                "relevance": 0.95,
                "search_term": "Wirtschaftsprüfung Wirtschaftsprüfungsgesellschaft Audit",
                "osm_tags": ["node['office'='accountant']"],
            },
            {
                "category": "Buchhaltungs- & Treuhandbüro",
                "relevance": 0.88,
                "search_term": "Buchhaltungsbüro Treuhandgesellschaft Finanzberatung",
                "osm_tags": ["node['office'='financial']"],
            },
        ],
    },
    "Bankkaufmann": {
        "sector": "Finanzdienstleistungen & Banken",
        "synonyms": ["Bankkauffrau", "Bankbetriebswirt", "Finanzberater", "Vermögensberater"],
        "employer_categories": [
            {
                "category": "Sparkasse & Genossenschaftsbank",
                "relevance": 1.0,
                "search_term": "Sparkasse Volksbank Raiffeisenbank Bankfiliale",
                "osm_tags": ["node['amenity'='bank']", "way['amenity'='bank']"],
            },
            {
                "category": "Privatbank & Großbank",
                "relevance": 0.96,
                "search_term": "Deutsche Bank Commerzbank Privatbank Finanzzentrum",
                "osm_tags": ["node['amenity'='bank']"],
            },
            {
                "category": "Versicherung & Finanzberatung",
                "relevance": 0.85,
                "search_term": "Versicherungsagentur Bausparkasse Vermögensberatung",
                "osm_tags": ["node['office'='insurance']"],
            },
        ],
    },

    # ── Logistik & Lager ──────────────────────────────────────────────────
    "Fachkraft für Lagerlogistik": {
        "sector": "Logistik, Spedition & Lager",
        "synonyms": [
            "Fachlagerist", "Lagerist", "Lagerarbeiter", "Kommissionierer",
            "Logistikfachkraft", "Lagerleiter",
        ],
        "employer_categories": [
            {
                "category": "Spedition & Transportlogistik",
                "relevance": 1.0,
                "search_term": "Spedition Logistikzentrum Transportunternehmen Güterkraftverkehr",
                "osm_tags": ["node['office'='logistics']", "node['landuse'='industrial']"],
            },
            {
                "category": "Logistik- & Distributionszentrum",
                "relevance": 0.98,
                "search_term": "Distributionszentrum Zentrallager Versandzentrum Frachtzentrum",
                "osm_tags": ["node['building'='warehouse']", "way['building'='warehouse']"],
            },
            {
                "category": "Handels- & Industrie-Warenlager",
                "relevance": 0.90,
                "search_term": "Warenlager Baustoffhandel Industriebetrieb Lager",
                "osm_tags": ["node['shop'='wholesale']"],
            },
            {
                "category": "Paketdienst & Kurierdienste",
                "relevance": 0.85,
                "search_term": "Paketzentrum DHL DPD Hermes Zustellbasis",
                "osm_tags": ["node['amenity'='post_office']"],
            },
        ],
    },

    # ── Erziehung & Soziales ──────────────────────────────────────────────
    "Erzieher": {
        "sector": "Erziehung & Soziales",
        "synonyms": [
            "Erzieherin", "Kindergärtnerin", "Sozialpädagogischer Assistent",
            "Kindheitspädagoge", "Jugend- und Heimerzieher",
        ],
        "employer_categories": [
            {
                "category": "Kindertagesstätte & Kindergarten",
                "relevance": 1.0,
                "search_term": "Kindertagesstätte Kindergarten Kita Krippe",
                "osm_tags": ["node['amenity'='kindergarten']", "way['amenity'='kindergarten']"],
            },
            {
                "category": "Kinderkrippe & Hort",
                "relevance": 0.95,
                "search_term": "Schülerhort Ganztagsschule Kinderkrippe",
                "osm_tags": ["node['amenity'='school']", "node['amenity'='childcare']"],
            },
            {
                "category": "Kinder- & Jugendheim",
                "relevance": 0.88,
                "search_term": "Kinderheim Jugendhilfe Wohngruppe Erziehungsberatung",
                "osm_tags": ["node['office'='charity']", "node['social_facility'='group_home']"],
            },
            {
                "category": "Träger der freien Jugendhilfe",
                "relevance": 0.82,
                "search_term": "AWO DRK Diakonie Caritas Jugendzentrum",
                "osm_tags": ["node['amenity'='community_centre']"],
            },
        ],
    },
}

# Inverted index for fast O(1) canonical title resolution from synonyms
SYNONYM_TO_CANONICAL: Dict[str, str] = {}
for _canonical, _data in PROFESSION_TAXONOMY.items():
    SYNONYM_TO_CANONICAL[_canonical.lower()] = _canonical
    for _syn in _data.get("synonyms", []):
        SYNONYM_TO_CANONICAL[_syn.lower()] = _canonical


class ProfessionIntelligence:
    """
    Intelligent Profession-to-Employer Discovery Engine.
    Hybrid deterministic + AI classifier with caching and multilingual support.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ProfessionIntelligence, cls).__new__(cls)
                cls._instance._init_engine()
            return cls._instance

    def _init_engine(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._cache: Dict[str, Any] = {}
        self._load_cache()

    def _load_cache(self):
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception as exc:
                logger.warning("Failed to load profession intelligence cache: %s", exc)
                self._cache = {}

    def _save_cache(self):
        try:
            temp_path = CACHE_FILE.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            temp_path.replace(CACHE_FILE)
        except Exception as exc:
            logger.warning("Failed to persist profession intelligence cache: %s", exc)

    def clear_cache(self):
        """Clears memory and persistent cache."""
        with self._lock:
            self._cache.clear()
            try:
                if CACHE_FILE.exists():
                    CACHE_FILE.unlink()
            except Exception as exc:
                logger.warning("Failed to remove cache file: %s", exc)

    # -------------------------------------------------------------------------
    # Text Normalization & Cleaning
    # -------------------------------------------------------------------------

    def normalize_input(self, raw_input: str) -> str:
        """
        Cleans user input by:
        1. Stripping prefixes like 'Ausbildung als', 'Lehre als', etc.
        2. Removing gender suffixes like '(m/w/d)', '/in', '-innen'.
        3. Normalizing whitespace and casing.
        """
        if not raw_input or not isinstance(raw_input, str):
            return ""

        text = raw_input.strip()

        # Remove prefix variants (case-insensitive)
        for pat in PROFESSION_PREFIXES:
            text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

        # Remove gender and noise suffixes
        for pat in GENDER_SUFFIXES:
            text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

        # Remove redundant whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def correct_spelling_and_typos(self, clean_text: str) -> str:
        """
        Applies known typo dictionary and fuzzy matching against the canonical taxonomy.
        """
        if not clean_text:
            return ""

        low = clean_text.lower()

        # 1. Exact lookup in typo correction dictionary
        if low in TYPO_CORRECTIONS:
            return TYPO_CORRECTIONS[low]

        # 2. Multilingual translation check
        if low in MULTILINGUAL_MAP:
            return MULTILINGUAL_MAP[low]

        # 3. Direct match against canonical taxonomy or synonyms
        if low in SYNONYM_TO_CANONICAL:
            return SYNONYM_TO_CANONICAL[low]

        # 4. Check for partial matches or prefix tokens
        # e.g. "Fachinformatiker für Datenanalyse" -> "Fachinformatiker"
        for canonical, data in PROFESSION_TAXONOMY.items():
            if canonical.lower() in low or low in canonical.lower():
                return canonical
            for syn in data.get("synonyms", []):
                if syn.lower() in low or low in syn.lower():
                    return canonical

        # 5. Fuzzy match against all known dictionary keys
        all_candidates = list(SYNONYM_TO_CANONICAL.keys()) + list(TYPO_CORRECTIONS.keys()) + list(MULTILINGUAL_MAP.keys())
        matches = difflib.get_close_matches(low, all_candidates, n=1, cutoff=0.78)
        if matches:
            matched_key = matches[0]
            if matched_key in SYNONYM_TO_CANONICAL:
                return SYNONYM_TO_CANONICAL[matched_key]
            if matched_key in TYPO_CORRECTIONS:
                return TYPO_CORRECTIONS[matched_key]
            if matched_key in MULTILINGUAL_MAP:
                return MULTILINGUAL_MAP[matched_key]

        # Return original cleaned text if no match found
        return clean_text

    # -------------------------------------------------------------------------
    # Core Classification (Hybrid Taxonomy + AI Gateway)
    # -------------------------------------------------------------------------

    def classify_profession(
        self,
        query: str,
        use_ai: bool = True,
    ) -> Dict[str, Any]:
        """
        Classifies a user profession query into normalized name, sector,
        and structured employer categories.
        """
        raw_query = str(query or "").strip()
        if not raw_query:
            return {
                "input": "",
                "normalized_profession": "",
                "sector": "Allgemein",
                "synonyms": [],
                "employer_categories": [],
                "source": "empty",
            }

        # Step 1: Normalize input
        cleaned = self.normalize_input(raw_query)
        canonical_name = self.correct_spelling_and_typos(cleaned)
        cache_key = cleaned.lower()

        # Step 2: Check deterministic local taxonomy first
        if canonical_name in PROFESSION_TAXONOMY:
            tax_entry = PROFESSION_TAXONOMY[canonical_name]
            result = {
                "input": raw_query,
                "normalized_profession": canonical_name,
                "sector": tax_entry.get("sector", "Allgemein"),
                "synonyms": tax_entry.get("synonyms", []),
                "employer_categories": tax_entry.get("employer_categories", []),
                "source": "deterministic_taxonomy",
            }
            with self.lock:
                self._cache[cache_key] = result
            return result

        # Step 3: Check persistent cache (e.g. for AI classifications)
        with self.lock:
            if cache_key in self._cache:
                cached_entry = dict(self._cache[cache_key])
                cached_entry["input"] = raw_query
                return cached_entry

        # Step 4: Fallback to Central AI Provider Manager (if enabled)
        if use_ai:
            ai_result = self._classify_with_ai(cleaned, raw_query)
            if ai_result:
                with self.lock:
                    self._cache[cache_key] = ai_result
                    self._save_cache()
                return ai_result

        # Step 5: Graceful Heuristic Generation (Offline / Zero-Config fallback)
        heuristic_result = self._generate_heuristic_classification(cleaned, raw_query)
        with self.lock:
            self._cache[cache_key] = heuristic_result
            self._save_cache()
        return heuristic_result

    def _classify_with_ai(self, cleaned: str, raw_query: str) -> Optional[Dict[str, Any]]:
        """
        Calls Central AI Provider Manager (OpenAI / Gemini) to extract structured
        employer categories for unknown or specialized professions.
        """
        try:
            from services.ai_provider_manager import ai_manager

            system_prompt = (
                "Du bist eine intelligente KI für Arbeitsmarktanalysen in Deutschland. "
                "Deine Aufgabe ist es, für jede beliebige Berufsbezeichnung die relevanten "
                "Arbeitgeber-Kategorien (Betriebsarten, Institutionen, Unternehmen) zu ermitteln, "
                "bei denen man in diesem Beruf arbeiten oder eine Ausbildung machen kann.\n\n"
                "Antworte AUSSCHLIESSLICH im folgenden JSON-Format ohne Markdown-Backticks:\n"
                "{\n"
                '  "normalized_profession": "Gereinigter deutscher Berufsname",\n'
                '  "sector": "Branche / Sektor (z.B. IT & Software, Handwerk, Gastronomie, Gesundheitswesen)",\n'
                '  "synonyms": ["Synonym 1", "Synonym 2"],\n'
                '  "employer_categories": [\n'
                '    {"category": "Kategorie-Name", "relevance": 1.0, "search_term": "Suchbegriff für Google Maps"},\n'
                '    {"category": "Kategorie-Name", "relevance": 0.95, "search_term": "Suchbegriff für Google Maps"}\n'
                "  ]\n"
                "}\n\n"
                "Regeln:\n"
                "- Genau 3 bis 5 präzise Arbeitgeberkategorien.\n"
                "- Relevanz-Score zwischen 1.0 (höchste Relevanz) und 0.70.\n"
                "- Die search_term Begriffe müssen konkrete deutsche Unternehmensarten für Google Maps sein."
            )

            user_prompt = f"Berufsbezeichnung / Ausbildung: '{cleaned}'"

            ai_res = ai_manager.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_output_tokens=400,
                temperature=0.1,
            )

            if ai_res.get("success") and ai_res.get("text"):
                raw_text = ai_res.get("text", "").strip()
                # Clean potential markdown wrapping
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                    raw_text = re.sub(r"\s*```$", "", raw_text)

                data = json.loads(raw_text)
                norm_title = str(data.get("normalized_profession") or cleaned).strip()
                sector = str(data.get("sector") or "Fachbereich").strip()
                syns = [str(s).strip() for s in data.get("synonyms", []) if s]
                cats = []
                for c in data.get("employer_categories", []):
                    if isinstance(c, dict) and c.get("category"):
                        cats.append({
                            "category": str(c.get("category")).strip(),
                            "relevance": float(c.get("relevance", 0.9)),
                            "search_term": str(c.get("search_term") or c.get("category")).strip(),
                            "osm_tags": [f"node['office']", f"node['craft']"],
                        })

                if cats:
                    return {
                        "input": raw_query,
                        "normalized_profession": norm_title,
                        "sector": sector,
                        "synonyms": syns,
                        "employer_categories": cats,
                        "source": f"ai_gateway ({ai_res.get('model', 'central_ai')})",
                    }
        except Exception as exc:
            logger.warning("AI profession classification failed: %s", exc)

        return None

    def _generate_heuristic_classification(self, cleaned: str, raw_query: str) -> Dict[str, Any]:
        """
        Deterministic heuristic generator when AI is disabled and profession is not in taxonomy.
        """
        title = cleaned.capitalize() if cleaned else "Fachkraft"
        return {
            "input": raw_query,
            "normalized_profession": title,
            "sector": "Allgemeines Gewerbe & Dienstleistungen",
            "synonyms": [title],
            "employer_categories": [
                {
                    "category": f"{title} Fachbetrieb",
                    "relevance": 1.0,
                    "search_term": f"{title} Fachbetrieb Meisterbetrieb",
                    "osm_tags": ["node['craft']", "way['craft']"],
                },
                {
                    "category": f"{title} Dienstleister & Unternehmen",
                    "relevance": 0.95,
                    "search_term": f"{title} Unternehmen Firma Dienstleistung",
                    "osm_tags": ["node['office']", "way['office']"],
                },
                {
                    "category": "Fachabteilung / Spezialbetrieb",
                    "relevance": 0.85,
                    "search_term": f"{title} Service Zentrum",
                    "osm_tags": ["node['office'='company']"],
                },
            ],
            "source": "heuristic_fallback",
        }

    # -------------------------------------------------------------------------
    # Helper Accessors for Discovery & Verification
    # -------------------------------------------------------------------------

    def get_search_queries(
        self,
        profession_query: str,
        location: str = "",
        max_categories: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Returns location-aware search queries for Google Maps & Overpass.
        Example for 'Ausbildung als Koch' in 'Berlin':
        [
          {"category": "Restaurant", "query": "Restaurant Berlin", "relevance": 1.0, ...},
          {"category": "Hotel & Gastgewerbe", "query": "Hotel Restaurant Gasthof Berlin", ...}
        ]
        """
        classification = self.classify_profession(profession_query)
        loc_suffix = f" {location.strip()}" if location.strip() else ""
        results = []

        for item in classification.get("employer_categories", [])[:max_categories]:
            clean_term = item.get("search_term") or item.get("category")
            full_query = f"{clean_term}{loc_suffix}".strip()
            results.append({
                "category": item.get("category"),
                "relevance": item.get("relevance", 1.0),
                "query": full_query,
                "raw_search_term": clean_term,
                "osm_tags": item.get("osm_tags", []),
                "sector": classification.get("sector"),
                "normalized_profession": classification.get("normalized_profession"),
            })

        return results

    def get_osm_tags_for_profession(self, profession_query: str) -> List[str]:
        """
        Extracts all relevant OpenStreetMap tags for Overpass API.
        """
        classification = self.classify_profession(profession_query)
        tags: Set[str] = set()
        for item in classification.get("employer_categories", []):
            for t in item.get("osm_tags", []):
                tags.add(t)

        return list(tags) if tags else ["node['office']", "node['craft']"]


# Global singleton instance
profession_intelligence = ProfessionIntelligence()
