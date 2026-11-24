"""
JobScout - Search Filter & Relevance Engine
Provides unified, robust post-scraping and pre-scraping validation for:
1. Profession Relevance (rejects unrelated professions, accepts German synonyms and variants)
2. Location Normalization & Filtering (cleans bad location tags like 'Video', matches exact & regional commuter radius)
3. Publication Date Normalization & Filtering (separates publication date from scraping date, parses German formats)
4. Application Destination Verification (strictly separates verified forms from ordinary job listings)
5. Dataset Deduplication and Accurate Result Counting
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Stopwords and noise tokens in German apprenticeship queries
GERMAN_STOP_WORDS = {
    "ausbildung",
    "ausbildungsplatz",
    "ausbildungsplaetze",
    "ausbildungsplätze",
    "auszubildende",
    "auszubildender",
    "auszubildenden",
    "azubi",
    "azubis",
    "lehre",
    "lehrstelle",
    "lehrstellen",
    "duales",
    "duale",
    "studium",
    "bachelor",
    "master",
    "stelle",
    "stellen",
    "stellenangebot",
    "stellenangebote",
    "platz",
    "plaetze",
    "plätze",
    "job",
    "jobs",
    "berufsausbildung",
    "facharbeiter",
    "fachkraft",
    "geselle",
    "gesellin",
    "quereinsteiger",
    "praktikum",
    "praktikant",
    "trainee",
    "praxisintegrierte",
    "praxisintegrierter",
    "praxisintegrierten",
    "pia",
    "staatlich",
    "anerkannte",
    "anerkannter",
    "anerkannten",
    "anerkannt",
    "zum",
    "zur",
    "zum/r",
    "zur/m",
    "als",
    "für",
    "fuer",
    "im",
    "in",
    "am",
    "an",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einen",
    "einem",
    "einer",
    "mit",
    "ohne",
    "und",
    "oder",
    "ab",
    "nach",
    "mwd",
    "m/w/d",
    "w/m/d",
    "d/m/w",
    "m/f/d",
    "gn",
    "wmd",
    "dmw",
    "mfd",
    "divers",
    "männlich",
    "weiblich",
    "2024",
    "2025",
    "2026",
    "2027",
    "2028",
    "sofort",
    "gesucht",
}

# Known profession synonyms, variants, and conflicting professions
PROFESSION_KNOWLEDGE_BASE = {
    "koch": {
        "canonical": "Koch/Köchin",
        "variants": {
            "koch",
            "köchin",
            "koechin",
            "köche",
            "koeche",
            "kochs",
            "beikoch",
            "beiköchin",
            "beikoechin",
            "gastronomiekoch",
            "chefkoch",
            "jungkoch",
            "schiffskoch",
            "krankenhauskoch",
            "küchenchef",
            "diätkoch",
            "diaetkoch",
            "commis de cuisine",
        },
        "probable_cues": {
            "küche",
            "kueche",
            "küchenteam",
            "kochen",
            "speisen",
            "zubereitung",
            "culinary",
            "cook",
        },
        "conflicts": {
            "kaufmann",
            "kauffrau",
            "kaufleute",
            "verkäufer",
            "verkaeufer",
            "verkäuferin",
            "versicherungen",
            "finanzanlagen",
            "bankkaufmann",
            "industriekaufmann",
            "industriekauffrau",
            "fachinformatiker",
            "fachinformatikerin",
            "informatik",
            "mechatroniker",
            "mechatronikerin",
            "elektroniker",
            "elektronikerin",
            "mechaniker",
            "schreiner",
            "tischler",
            "friseur",
            "erzieher",
            "pflegefachmann",
            "pflegefachfrau",
            "zahnmedizinisch",
            "immobilienkaufmann",
            "einzelhandel",
            "büromanagement",
            "bueromanagement",
            "großhandel",
            "grosshandel",
            "speditionskaufmann",
            "hotelfachmann",
            "hotelfachfrau",
            "hotelfachleute",
            "restaurantfachmann",
            "restaurantfachfrau",
            "restaurantfachleute",
            "systemgastronomie",
            "fachkraft im gastgewerbe",
            "fachkraft für gastronomie",
            "hauswirtschafter",
            "hauswirtschafterin",
            "bäcker",
            "bäckerin",
            "konditor",
            "konditorin",
            "fleischer",
            "metzger",
        },
    },
    "hotelfachmann": {
        "canonical": "Hotelfachmann/-frau",
        "variants": {"hotelfachmann", "hotelfachfrau", "hotelfachleute", "hotelfach"},
        "conflicts": {"koch", "köchin", "fachinformatiker", "elektroniker", "mechatroniker", "versicherungen"},
    },
    "restaurantfachmann": {
        "canonical": "Restaurantfachmann/-frau",
        "variants": {"restaurantfachmann", "restaurantfachfrau", "restaurantfachleute", "restaurantfach"},
        "conflicts": {"koch", "köchin", "fachinformatiker", "elektroniker", "mechatroniker", "versicherungen"},
    },
    "industriekaufmann": {
        "canonical": "Industriekaufmann/-frau",
        "variants": {
            "industriekaufmann",
            "industriekauffrau",
            "industriekaufleute",
        },
        "conflicts": {"koch", "köchin", "fachinformatiker", "mechatroniker", "friseur", "einzelhandel", "versicherungen"},
    },
    "büromanagement": {
        "canonical": "Kaufmann/-frau für Büromanagement",
        "variants": {
            "büromanagement",
            "bueromanagement",
            "kaufmann für büromanagement",
            "kauffrau für büromanagement",
            "bürokaufmann",
            "bürokauffrau",
            "buerokaufmann",
            "buerokauffrau",
        },
        "conflicts": {
            "koch",
            "köchin",
            "versicherungen",
            "finanzanlagen",
            "einzelhandel",
            "großhandel",
            "fachinformatiker",
            "elektroniker",
            "mechatroniker",
            "pflegefachmann",
        },
    },
    "kaufmann": {
        "canonical": "Kaufmann/-frau",
        "variants": {
            "kaufmann",
            "kauffrau",
            "kaufleute",
            "kaufmännisch",
            "kaufmaennisch",
        },
        "conflicts": {"koch", "köchin", "bäcker", "metzger", "schornsteinfeger", "elektroniker", "mechatroniker", "pflegefachmann"},
    },
    "fachinformatiker": {
        "canonical": "Fachinformatiker/in",
        "variants": {
            "fachinformatiker",
            "fachinformatikerin",
            "informatiker",
            "informatikerin",
            "anwendungsentwicklung",
            "systemintegration",
            "daten- und prozessanalyse",
            "digitale vernetzung",
            "fachinformatik",
            "softwareentwickler",
            "softwareentwicklerin",
            "it-system",
            "it-system-management",
            "it-systemkaufmann",
            "informatikkaufmann",
        },
        "conflicts": {
            "koch",
            "köchin",
            "industriekaufmann",
            "einzelhandel",
            "friseur",
            "versicherungen",
            "finanzanlagen",
            "hotelfachmann",
            "restaurantfachmann",
            "pflegefachmann",
            "pflegefachfrau",
            "bäcker",
            "metzger",
        },
    },
    "informatik": {
        "canonical": "Fachinformatiker/in",
        "variants": {
            "informatik",
            "fachinformatiker",
            "fachinformatikerin",
            "informatiker",
            "informatikerin",
            "anwendungsentwicklung",
            "systemintegration",
            "fachinformatik",
            "softwareentwickler",
            "informatikkaufmann",
        },
        "conflicts": {"koch", "köchin", "friseur", "versicherungen", "hotelfachmann", "pflegefachmann"},
    },
    "elektroniker": {
        "canonical": "Elektroniker/in",
        "variants": {
            "elektroniker",
            "elektronikerin",
            "industrieelektroniker",
            "energie- und gebäudetechnik",
            "betriebstechnik",
            "automatisierungstechnik",
            "elektronik",
        },
        "conflicts": {"koch", "köchin", "kaufmann", "kauffrau", "fachinformatiker", "pflegefachmann", "friseur", "verkäufer"},
    },
    "mechatroniker": {
        "canonical": "Mechatroniker/in",
        "variants": {
            "mechatroniker",
            "mechatronikerin",
            "kfz-mechatroniker",
            "kfz-mechatronikerin",
            "kraftfahrzeugmechatroniker",
        },
        "conflicts": {"koch", "köchin", "kaufmann", "kauffrau", "erzieher", "fachinformatiker", "pflegefachmann"},
    },
    "pflegefachmann": {
        "canonical": "Pflegefachmann/-frau",
        "variants": {
            "pflegefachmann",
            "pflegefachfrau",
            "pflegefachkraft",
            "pflegefachleute",
            "altenpfleger",
            "altenpflegerin",
            "krankenpfleger",
            "krankenpflegerin",
            "gesundheits- und krankenpfleger",
        },
        "conflicts": {"koch", "köchin", "kaufmann", "kauffrau", "fachinformatiker", "elektroniker", "mechatroniker"},
    },
    "bäcker": {
        "canonical": "Bäcker/in",
        "variants": {
            "bäcker",
            "bäckerin",
            "baecker",
            "baeckerin",
            "konditor",
            "konditorin",
            "bäckerei",
        },
        "conflicts": {"kaufmann", "fachinformatiker", "mechatroniker", "koch", "köchin"},
    },
    "erzieher": {
        "canonical": "Erzieher/in",
        "variants": {
            "erzieher",
            "erzieherin",
            "erzieherinnen",
            "erziehern",
            "staatlich anerkannter erzieher",
            "staatlich anerkannte erzieherin",
            "staatlich anerkannten erzieher",
            "jugend- und heimerzieher",
            "jugend- und heimerzieherin",
            "heimerzieher",
            "heimerzieherin",
            "arbeitserzieher",
            "arbeitserzieherin",
            "kinderpfleger",
            "kinderpflegerin",
            "sozialassistent",
            "sozialassistentin",
            "sozialpädagogische assistenz",
            "sozialpaedagogische assistenz",
        },
        "probable_cues": {
            "kita",
            "kindergarten",
            "kindertagesstätte",
            "kindertagesstaette",
            "krippe",
            "hort",
            "pädagogik",
            "paedagogik",
            "sozialpädagogik",
            "sozialpaedagogik",
            "elementarpädagogik",
        },
        "conflicts": {
            "koch",
            "köchin",
            "kaufmann",
            "kauffrau",
            "fachinformatiker",
            "fachinformatikerin",
            "mechatroniker",
            "elektroniker",
            "bäcker",
            "metzger",
            "friseur",
            "verkäufer",
            "hotelfachmann",
            "restaurantfachmann",
        },
    },
    "friseur": {
        "canonical": "Friseur/in",
        "variants": {"friseur", "friseurin", "friseure", "friseurinnen", "frisör", "frisörin"},
        "conflicts": {"koch", "köchin", "kaufmann", "fachinformatiker", "mechatroniker", "elektroniker", "erzieher"},
    },
    "verkäufer": {
        "canonical": "Verkäufer/in",
        "variants": {
            "verkäufer",
            "verkäuferin",
            "verkaeufer",
            "verkaeuferin",
            "kaufmann im einzelhandel",
            "kauffrau im einzelhandel",
            "einzelhandelskaufmann",
            "einzelhandelskauffrau",
        },
        "conflicts": {"koch", "köchin", "fachinformatiker", "mechatroniker", "elektroniker", "erzieher", "pflegefachmann"},
    },
}

# Known regional PLZ prefixes and neighboring towns for German searches
GERMAN_CITY_REGIONS = {
    "ahaus": {
        "plz_prefixes": ["48", "46"],
        "nearby_cities": {
            "ahaus",
            "stadtlohn",
            "vreden",
            "legden",
            "heek",
            "gescher",
            "coesfeld",
            "gronau",
            "borken",
            "schöppingen",
            "schoeppingen",
            "südlohn",
            "suedlohn",
            "münster",
            "muenster",
            "rheine",
            "steinfurt",
            "ochtrup",
        },
    },
    "berlin": {"plz_prefixes": ["10", "12", "13", "14"], "nearby_cities": {"berlin", "potsdam", "teltow"}},
    "münchen": {"plz_prefixes": ["80", "81", "82", "85"], "nearby_cities": {"münchen", "munich", "garching", "haar"}},
    "koeln": {"plz_prefixes": ["50", "51"], "nearby_cities": {"köln", "koeln", "hürth", "leverkusen", "bergisch gladbach"}},
    "köln": {"plz_prefixes": ["50", "51"], "nearby_cities": {"köln", "koeln", "hürth", "leverkusen", "bergisch gladbach"}},
    "frankfurt": {"plz_prefixes": ["60", "65"], "nearby_cities": {"frankfurt", "offenbach", "eschborn", "hanau"}},
    "stuttgart": {"plz_prefixes": ["70", "71", "72"], "nearby_cities": {"stuttgart", "esslingen", "fellbach", "ludwigsburg"}},
    "hamburg": {"plz_prefixes": ["20", "21", "22"], "nearby_cities": {"hamburg", "norderstedt", "wedel", "pinneberg"}},
}

# Bad location tokens incorrectly extracted from badges or metadata
DISALLOWED_LOCATION_TOKENS = {
    "video",
    "videdo",
    "duales studium",
    "geprüfte qualität",
    "gepruefte qualitaet",
    "top-arbeitgeber",
    "deutschland",
    "bundesweit",
    "standort",
    "nach absprache",
    "online",
    "homeoffice",
    "remote",
    "vollzeit",
    "teilzeit",
    "n/a",
    "k. a.",
    "k.a.",
    "undefined",
    "null",
}


def normalize_umlauts(text: str) -> str:
    """Normalizes German umlauts for fuzzy comparison."""
    if not text:
        return ""
    return (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def normalize_gender_inclusive_text(text: str) -> str:
    """
    Expands German gender-inclusive punctuation in job titles and queries so both
    the base and gendered forms are explicitly searchable as whole words.
    Examples:
    - 'Erzieher/in' -> 'Erzieher Erzieherin'
    - 'Erzieher/-in' -> 'Erzieher Erzieherin'
    - 'Erzieher*in' -> 'Erzieher Erzieherin'
    - 'Erzieher:in' -> 'Erzieher Erzieherin'
    - 'Erzieher_in' -> 'Erzieher Erzieherin'
    - 'ErzieherIn' -> 'Erzieher Erzieherin'
    - 'Kaufmann/-frau' -> 'Kaufmann Kauffrau'
    - 'Pflegefachmann*Pflegefachfrau' -> 'Pflegefachmann Pflegefachfrau'
    - 'zum/r' -> 'zum zur'
    """
    if not text:
        return ""
    s = str(text)
    # Handle Binnen-I (e.g. ErzieherIn, ErzieherInnen) before lowercasing
    s = re.sub(
        r"\b([A-ZÄÖÜ][a-zäöüß]{2,})I(n|nnen)\b",
        lambda m: f"{m.group(1)} {m.group(1)}i{m.group(2)}",
        s,
    )
    s_low = s.lower()
    # Strip common gender-inclusive preposition slashes
    s_low = re.sub(r"\bzum\s*/\s*-?\s*r\b", "zum zur", s_low)
    s_low = re.sub(r"\bzur\s*/\s*-?\s*m\b", "zur zum", s_low)

    # Expand -mann/-frau, -mann*frau, -mann:frau, -mann/frau
    s_low = re.sub(
        r"\b([a-zäöüß]{2,}?)mann\s*(?:/-|-/|/|\*|:|_)\s*frau(en)?\b",
        lambda m: f"{m.group(1)}mann {m.group(1)}frau{m.group(2) or ''}",
        s_low,
    )
    # Expand -frau/-mann, -frau*mann
    s_low = re.sub(
        r"\b([a-zäöüß]{2,}?)frau\s*(?:/-|-/|/|\*|:|_)\s*mann\b",
        lambda m: f"{m.group(1)}frau {m.group(1)}mann",
        s_low,
    )
    # Expand <stem>(/in, /-in, *in, :in, _in, /innen, *innen, :innen, _innen)
    s_low = re.sub(
        r"\b([a-zäöüß]{3,}?)\s*(?:/-|-/|/|\*|:|_)\s*(innen|in)\b",
        lambda m: f"{m.group(1)} {m.group(1)}{m.group(2)}",
        s_low,
    )
    # Replace remaining *, :, /, _ between letters with spaces so tokens split cleanly
    s_low = re.sub(r"(?<=[a-zäöüß])[/*:_]+(?=[a-zäöüß])", " ", s_low)
    return s_low


def _deumlaut_stem(stem: str) -> str:
    """Reverses German i-umlaut in occupation roots (e.g. köch -> koch, bäcker -> backer)."""
    return (
        stem.replace("äu", "au")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
    )


def generate_german_occupation_variants(word: str) -> Set[str]:
    """
    Bidirectional German morphological generator for occupation nouns.
    Maps masculine, feminine, plural, dative, and gender-neutral forms to a unified variant set:
    - 'erzieherin' <-> 'erzieher', 'erzieherin', 'erzieherinnen', 'erziehern'
    - 'kauffrau' <-> 'kaufmann', 'kauffrau', 'kaufleute', 'kaufkraft'
    - 'pflegefachfrau' <-> 'pflegefachmann', 'pflegefachfrau', 'pflegefachkraft', 'pflegefachleute'
    - 'köchin' <-> 'koch', 'köchin', 'koechin', 'köche'
    """
    out: Set[str] = set()
    w = str(word or "").strip().lower()
    if not w or len(w) <= 1:
        return out

    out.add(w)
    out.add(normalize_umlauts(w))

    # 1. -erinnen / -erin <-> -er (e.g. erzieherin <-> erzieher, verkäuferin <-> verkäufer)
    if w.endswith("erinnen") and len(w) > 8:
        base_er = w[:-5]  # ends with 'er'
        out.update({base_er, base_er + "in", base_er + "innen", base_er + "n", base_er + "s"})
    elif w.endswith("erin") and len(w) > 5:
        base_er = w[:-2]  # ends with 'er'
        out.update({base_er, base_er + "in", base_er + "innen", base_er + "n", base_er + "s"})
        deum = _deumlaut_stem(base_er)
        if deum != base_er:
            out.update({deum, deum + "in", deum + "innen"})
    elif w.endswith("ern") and len(w) > 5:
        base_er = w[:-1]  # ends with 'er'
        out.update({base_er, base_er + "in", base_er + "innen", base_er + "n"})
    elif w.endswith("er") and len(w) > 3:
        out.update({w, w + "in", w + "innen", w + "n", w + "s"})

    # 2. -frau / -frauen <-> -mann / -leute / -kraft
    if w.endswith("frauen") and len(w) > 7:
        stem = w[:-6]
        out.update({stem + "mann", stem + "frau", stem + "frauen", stem + "leute", stem + "kraft", stem + "kräfte"})
    elif w.endswith("frau") and len(w) > 5:
        stem = w[:-4]
        out.update({stem + "mann", stem + "frau", stem + "frauen", stem + "leute", stem + "kraft", stem + "kräfte"})
    elif w.endswith("mann") and len(w) > 5:
        stem = w[:-4]
        out.update({stem + "mann", stem + "frau", stem + "frauen", stem + "leute", stem + "kraft", stem + "kräfte"})
    elif w.endswith("leute") and len(w) > 6:
        stem = w[:-5]
        out.update({stem + "mann", stem + "frau", stem + "frauen", stem + "leute", stem + "kraft"})
    elif w.endswith("kraft") and len(w) > 6:
        stem = w[:-5]
        out.update({stem + "kraft", stem + "kräfte", stem + "mann", stem + "frau", stem + "leute"})

    # 3. General -innen / -in (when not -erin, e.g. köchin -> koch, assistentin -> assistent, laborantin -> laborant)
    if w.endswith("innen") and not w.endswith("erinnen") and len(w) > 7:
        root = w[:-5]
        out.update({root, root + "in", root + "innen", root + "e", root + "en"})
        deum = _deumlaut_stem(root)
        if deum != root:
            out.update({deum, deum + "e"})
    elif w.endswith("in") and not w.endswith("erin") and len(w) > 4:
        root = w[:-2]
        out.update({root, root + "in", root + "innen", root + "e", root + "en"})
        deum = _deumlaut_stem(root)
        if deum != root:
            out.update({deum, deum + "e"})
    elif any(w.endswith(suf) for suf in ("ist", "ant", "ent", "eut", "eur", "ör", "oer", "arzt", "wirt")) and len(w) > 4:
        out.update({w + "in", w + "innen"})

    # Add umlaut-normalized forms for every generated variant
    for v in list(out):
        out.add(normalize_umlauts(v))

    return out


def extract_profession_tokens(search_keyword: str) -> Dict[str, Any]:
    """
    Strips generic words ("Ausbildung", "zum", "als", "für", etc.) and extracts
    the core profession term along with allowed variants and conflict terms.
    """
    raw = str(search_keyword or "").strip().lower()
    if not raw:
        return {"core_tokens": set(), "variants": set(), "conflicts": set(), "is_generic": True}

    # Remove bracketed gender markers like (m/w/d), [w/m/d], (gn), (d/m/w)
    cleaned = re.sub(r"[\(\[\{]\s*[a-zA-Z0-9/\-\+\.\s]{1,10}\s*[\)\]\}]", " ", raw)
    # Remove standalone gender tokens
    cleaned = re.sub(r"\b(m/w/d|w/m/d|d/m/w|m/f/d|gn|mwd|wmd|dmw|mfd)\b", " ", cleaned)
    # Expand gender-inclusive slash/star/colon forms (e.g. Erzieher*in -> Erzieher Erzieherin)
    cleaned = normalize_gender_inclusive_text(cleaned)
    # Split into words
    words = [w for w in re.split(r"[^a-zA-ZäöüÄÖÜß0-9\-]+", cleaned) if w]
    core_words = [w for w in words if w not in GERMAN_STOP_WORDS and len(w) > 1 and not w.isdigit()]

    if not core_words:
        # User searched only "Ausbildung" or generic term
        return {"core_tokens": set(), "variants": set(), "conflicts": set(), "is_generic": True}

    core_tokens: Set[str] = set()
    variants: Set[str] = set()
    probable_cues: Set[str] = set()
    conflicts: Set[str] = set()
    canonical_name: str = ""

    for word in core_words:
        core_tokens.add(word)
        morph_variants = generate_german_occupation_variants(word)
        variants.update(morph_variants)

        # Check knowledge base using full morphological variant set
        for kb_key, kb_data in PROFESSION_KNOWLEDGE_BASE.items():
            kb_variants = kb_data["variants"]
            if (
                kb_key in morph_variants
                or bool(morph_variants & kb_variants)
                or kb_key in word
                or word in kb_key
            ):
                if not canonical_name and kb_data.get("canonical"):
                    canonical_name = kb_data["canonical"]
                variants.update(kb_variants)
                for v in kb_variants:
                    variants.update(generate_german_occupation_variants(v))
                probable_cues.update(kb_data.get("probable_cues", set()))
                conflicts.update(kb_data["conflicts"])

    # Never allow a generated variant of the requested occupation to remain in conflicts
    conflicts -= variants
    conflicts -= core_tokens

    if not canonical_name:
        canonical_name = " ".join(core_words)

    return {
        "core_tokens": core_tokens,
        "variants": variants,
        "probable_cues": probable_cues,
        "conflicts": conflicts,
        "canonical": canonical_name,
        "normalized_occupation": " ".join(core_words),
        "is_generic": False,
    }


def normalize_occupation_term(text: str) -> str:
    """
    Normalizes German search queries and job titles into their core occupation term:
    - Lowercases and trims whitespace
    - Strips gender markers (m/w/d, w/m/d, d/m/w, gn)
    - Expands gender-inclusive notation (*in, :in, /in, /-in)
    - Strips generic wrapper words (ausbildung, ausbildungsplatz, azubi, zum, zur, als, für, 2026, 2027, etc.)
    """
    raw = str(text or "").strip().lower()
    if not raw or raw in {"n/a", "k. a.", "k.a.", "none"}:
        return ""
    cleaned = re.sub(r"[\(\[\{]\s*[a-zA-Z0-9/\-\+\.\s]{1,12}\s*[\)\]\}]", " ", raw)
    cleaned = re.sub(r"\b(m/w/d|w/m/d|d/m/w|m/f/d|gn|mwd|wmd|dmw|mfd)\b", " ", cleaned, flags=re.I)
    cleaned = normalize_gender_inclusive_text(cleaned)
    words = [w for w in re.split(r"[^a-zA-ZäöüÄÖÜß0-9\-]+", cleaned) if w]
    core_words = []
    for w in words:
        if w not in GERMAN_STOP_WORDS and len(w) > 1 and not w.isdigit():
            if w not in core_words:
                core_words.append(w)
    return " ".join(core_words).strip()


def is_generic_only_title(title: str) -> bool:
    """
    Returns True if a job title contains only generic apprenticeship wrapper words
    (e.g. 'Ausbildung 2027', 'Ausbildung 2026', 'Ausbildung 2027 - Praktikum möglich', 'N/A', '').
    """
    norm = normalize_occupation_term(title)
    if not norm:
        return True
    # Check if remaining words are only generic adjectives like 'möglich', 'ab', 'herbst', 'august', 'september'
    extra_noise = {
        "möglich", "moeglich", "herbst", "sommer", "frühjahr", "winter",
        "august", "september", "oktober", "ab", "start", "beginn", "frei", "freie", "offene",
    }
    rem = [w for w in norm.split() if w not in extra_noise]
    return len(rem) == 0


def detect_job_occupation(job: Dict[str, Any]) -> str:
    """
    Detects the specific German occupation from a job's structured fields, title, or description.
    """
    hauptberuf = str(job.get("hauptberuf") or job.get("beruf") or job.get("occupation") or "").strip()
    if hauptberuf and hauptberuf.lower() not in {"n/a", "k. a.", "none"}:
        return hauptberuf

    title = str(job.get("title") or job.get("titel") or job.get("stellenangebotsTitel") or "").strip()
    title_lower = normalize_gender_inclusive_text(title)
    title_norm = normalize_umlauts(title_lower)

    # Check if any known profession in KB matches the title
    for kb_key, kb_data in PROFESSION_KNOWLEDGE_BASE.items():
        for v in kb_data["variants"]:
            v_norm = normalize_umlauts(v)
            if (
                re.search(r"\b" + re.escape(v) + r"\b", title_lower)
                or re.search(r"\b" + re.escape(v_norm) + r"\b", title_norm)
            ):
                return kb_data.get("canonical", v)

    # Check if title has a normalized occupation term (and isn't generic-only)
    if not is_generic_only_title(title):
        return normalize_occupation_term(title)

    # Inspect description / metadata if title is generic
    desc = " ".join(
        str(job.get(k) or "")
        for k in ("description", "snippet", "category", "breadcrumbs", "requirements", "tasks")
    )
    desc_lower = normalize_gender_inclusive_text(desc)
    desc_norm = normalize_umlauts(desc_lower)
    if desc_lower.strip():
        for kb_key, kb_data in PROFESSION_KNOWLEDGE_BASE.items():
            for v in kb_data["variants"]:
                v_norm = normalize_umlauts(v)
                if (
                    re.search(r"\b" + re.escape(v) + r"\b", desc_lower)
                    or re.search(r"\b" + re.escape(v_norm) + r"\b", desc_norm)
                ):
                    return kb_data.get("canonical", v)

    return ""


def _text_has_variant_or_token(text: str, token_meta: Dict[str, Any]) -> Tuple[bool, bool, str]:
    """
    Checks if `text` contains an exact core token or an equivalent variant.
    Normalizes German gender-inclusive spellings (*in, :in, /in, /-in, _in, Binnen-I)
    before word-boundary and compound matching.
    Returns (is_exact_core, is_equivalent_variant, matched_term).
    """
    raw_text = str(text or "").strip()
    if not raw_text:
        return False, False, ""
    t_lower = normalize_gender_inclusive_text(raw_text)
    t_norm = normalize_umlauts(t_lower)

    for core in token_meta.get("core_tokens", set()):
        core_norm = normalize_umlauts(core)
        if (
            re.search(r"\b" + re.escape(core) + r"\b", t_lower)
            or re.search(r"\b" + re.escape(core_norm) + r"\b", t_norm)
        ):
            return True, True, core

    for v in token_meta.get("variants", set()):
        v_norm = normalize_umlauts(v)
        if (
            re.search(r"\b" + re.escape(v) + r"\b", t_lower)
            or re.search(r"\b" + re.escape(v_norm) + r"\b", t_norm)
            or (len(v) >= 5 and (v in t_lower or v_norm in t_norm))
        ):
            return False, True, v

    for core in token_meta.get("core_tokens", set()):
        core_norm = normalize_umlauts(core)
        if len(core) >= 4 and (core in t_lower or core_norm in t_norm):
            return False, True, core

    return False, False, ""


def _text_has_conflict(text: str, token_meta: Dict[str, Any]) -> Tuple[bool, str]:
    t_lower = str(text or "").lower().strip()
    if not t_lower:
        return False, ""
    t_norm = normalize_umlauts(t_lower)
    for c in token_meta.get("conflicts", set()):
        c_norm = normalize_umlauts(c)
        if (
            re.search(r"\b" + re.escape(c) + r"\b", t_lower)
            or re.search(r"\b" + re.escape(c_norm) + r"\b", t_norm)
        ):
            return True, c
    return False, ""


def score_occupation_relevance(job: Dict[str, Any], search_keyword: str) -> Dict[str, Any]:
    """
    Stage A — Fast discovery occupation relevance classification:
    Classifies a job against `search_keyword` into one of 5 categories:
    - exact_match (1.0): Exact occupation match in job title or structured occupation field.
    - equivalent_occupation (0.95): Valid gender form, plural, synonym, or official variant.
    - probable_match (0.85): Title is generic (e.g. 'Ausbildung 2027') AND structured metadata / description confirms occupation.
    - uncertain (0.50): Generic title with insufficient metadata on card; requires Stage B detail verification.
    - irrelevant (0.0): Different occupation or no evidence of requested occupation.
    """
    token_meta = extract_profession_tokens(search_keyword)
    title = str(job.get("title") or job.get("titel") or job.get("stellenangebotsTitel") or "").strip()
    hauptberuf = str(job.get("hauptberuf") or job.get("beruf") or job.get("occupation") or "").strip()
    extra_meta = " ".join(
        str(job.get(k) or "")
        for k in ("description", "snippet", "category", "breadcrumbs", "requirements", "tasks")
    ).strip()

    detected_occ = detect_job_occupation(job)
    req_occ = token_meta.get("normalized_occupation") or normalize_occupation_term(search_keyword)

    if token_meta["is_generic"]:
        res = {
            "search_query": search_keyword,
            "normalized_requested_occupation": req_occ,
            "detected_job_occupation": detected_occ or title,
            "occupation_match_type": "exact_match",
            "relevance_score": 1.0,
            "relevance_decision_reason": "Generic search query accepts all apprenticeship listings",
        }
        job.update(res)
        return res

    title_exact, title_equiv, title_term = _text_has_variant_or_token(title, token_meta)
    beruf_exact, beruf_equiv, beruf_term = _text_has_variant_or_token(hauptberuf, token_meta)
    title_conflict, conflict_term = _text_has_conflict(f"{title} {hauptberuf}", token_meta)

    # Check if a conflicting occupation appears in the title without the target occupation
    if title_conflict and not (title_exact or title_equiv or beruf_exact or beruf_equiv):
        res = {
            "search_query": search_keyword,
            "normalized_requested_occupation": req_occ,
            "detected_job_occupation": detected_occ or conflict_term,
            "occupation_match_type": "irrelevant",
            "relevance_score": 0.0,
            "relevance_decision_reason": f"Conflicting occupation '{conflict_term}' in title/beruf '{title}' does not match '{req_occ}'",
        }
        job.update(res)
        return res

    # Even if a substring matched, verify Koch vs Kaufmann conflict
    if title_conflict and "koch" in token_meta["core_tokens"]:
        combined_th = f"{title} {hauptberuf}".lower()
        if not any(k in combined_th for k in ["koch", "köch", "koech", "beikoch", "jungkoch"]):
            res = {
                "search_query": search_keyword,
                "normalized_requested_occupation": req_occ,
                "detected_job_occupation": detected_occ or conflict_term,
                "occupation_match_type": "irrelevant",
                "relevance_score": 0.0,
                "relevance_decision_reason": f"Conflicting occupation '{conflict_term}' without explicit Koch match",
            }
            job.update(res)
            return res

    generic_title = is_generic_only_title(title)

    # Case 1: Title itself has exact match
    if title_exact and not generic_title:
        res = {
            "search_query": search_keyword,
            "normalized_requested_occupation": req_occ,
            "detected_job_occupation": detected_occ or token_meta.get("canonical") or title_term,
            "occupation_match_type": "exact_match",
            "relevance_score": 1.0,
            "relevance_decision_reason": f"Exact occupation token '{title_term}' matched in job title '{title}'",
        }
        job.update(res)
        return res

    # Case 2: Title has equivalent occupation variant (gender form, plural, synonym, specialization)
    if title_equiv and not generic_title:
        res = {
            "search_query": search_keyword,
            "normalized_requested_occupation": req_occ,
            "detected_job_occupation": detected_occ or token_meta.get("canonical") or title_term,
            "occupation_match_type": "equivalent_occupation",
            "relevance_score": 0.95,
            "relevance_decision_reason": f"Equivalent occupation variant '{title_term}' matched in job title '{title}'",
        }
        job.update(res)
        return res

    # Case 3: Title is generic (e.g. 'Ausbildung 2027', 'N/A', '') -> check structured hauptberuf or description
    if generic_title:
        if beruf_exact or beruf_equiv:
            canonical_occ = hauptberuf or token_meta.get("canonical") or beruf_term
            if not title or title.lower() in {"n/a", "k. a.", "none"}:
                job["title"] = f"Ausbildung {canonical_occ}"
            elif canonical_occ.lower() not in title.lower():
                job["title"] = f"{title} ({canonical_occ})"
            res = {
                "search_query": search_keyword,
                "normalized_requested_occupation": req_occ,
                "detected_job_occupation": canonical_occ,
                "occupation_match_type": "probable_match",
                "relevance_score": 0.85,
                "relevance_decision_reason": f"Generic title '{title}' confirmed by structured occupation field '{hauptberuf}'",
            }
            job.update(res)
            return res

        meta_exact, meta_equiv, meta_term = _text_has_variant_or_token(extra_meta, token_meta)
        meta_conflict, meta_conflict_term = _text_has_conflict(extra_meta, token_meta)
        if (meta_exact or meta_equiv) and not meta_conflict:
            canonical_occ = token_meta.get("canonical") or meta_term
            if not title or title.lower() in {"n/a", "k. a.", "none"}:
                job["title"] = f"Ausbildung {canonical_occ}"
            elif canonical_occ.lower() not in title.lower():
                job["title"] = f"{title} ({canonical_occ})"
            res = {
                "search_query": search_keyword,
                "normalized_requested_occupation": req_occ,
                "detected_job_occupation": canonical_occ,
                "occupation_match_type": "probable_match",
                "relevance_score": 0.85,
                "relevance_decision_reason": f"Generic title '{title}' confirmed by job description/metadata ('{meta_term}')",
            }
            job.update(res)
            return res

        if meta_conflict and not (meta_exact or meta_equiv):
            res = {
                "search_query": search_keyword,
                "normalized_requested_occupation": req_occ,
                "detected_job_occupation": meta_conflict_term,
                "occupation_match_type": "irrelevant",
                "relevance_score": 0.0,
                "relevance_decision_reason": f"Generic title '{title}' has conflicting occupation '{meta_conflict_term}' in metadata",
            }
            job.update(res)
            return res

        # Insufficient metadata on card -> mark uncertain for Stage B detail verification
        res = {
            "search_query": search_keyword,
            "normalized_requested_occupation": req_occ,
            "detected_job_occupation": detected_occ or "unknown",
            "occupation_match_type": "uncertain",
            "relevance_score": 0.50,
            "relevance_decision_reason": f"Generic title '{title}' has insufficient card metadata; requires Stage B detail verification",
        }
        job.update(res)
        return res

    # Case 4: Non-generic title that did not match title, but structured hauptberuf matches
    if beruf_exact or beruf_equiv:
        res = {
            "search_query": search_keyword,
            "normalized_requested_occupation": req_occ,
            "detected_job_occupation": hauptberuf or token_meta.get("canonical") or beruf_term,
            "occupation_match_type": "probable_match",
            "relevance_score": 0.85,
            "relevance_decision_reason": f"Title '{title}' confirmed by structured occupation field '{hauptberuf}'",
        }
        job.update(res)
        return res

    # Otherwise: Non-generic title with no match in title or hauptberuf -> irrelevant
    res = {
        "search_query": search_keyword,
        "normalized_requested_occupation": req_occ,
        "detected_job_occupation": detected_occ or normalize_occupation_term(title) or "unmatched",
        "occupation_match_type": "irrelevant",
        "relevance_score": 0.0,
        "relevance_decision_reason": f"Title '{title}' contains no evidence of requested occupation '{req_occ}'",
    }
    job.update(res)
    return res


_STAGE_B_SESSION = None
_STAGE_B_LOCK = None


def _get_stage_b_session():
    global _STAGE_B_SESSION, _STAGE_B_LOCK
    import threading
    if _STAGE_B_LOCK is None:
        _STAGE_B_LOCK = threading.Lock()
    with _STAGE_B_LOCK:
        if _STAGE_B_SESSION is None:
            import requests
            from requests.adapters import HTTPAdapter
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            _STAGE_B_SESSION = s
        return _STAGE_B_SESSION


def verify_ambiguous_job_relevance(
    job: Dict[str, Any],
    search_keyword: str,
    session: Optional[Any] = None,
    timeout: int = 5,
) -> Dict[str, Any]:
    """
    Stage B — Job Detail Verification for 'uncertain' results (e.g. 'Ausbildung 2027').
    Fetches and inspects the full job detail page (structured occupation fields, JSON-LD,
    breadcrumbs, headings, and full job description).
    Keeps the job ONLY if the requested occupation is confirmed; otherwise rejects it as 'irrelevant'.
    """
    token_meta = extract_profession_tokens(search_keyword)
    req_occ = token_meta.get("normalized_occupation") or normalize_occupation_term(search_keyword)
    title = str(job.get("title") or "").strip()

    # First re-check any existing description/metadata fields on job
    existing_detail = " ".join(
        str(job.get(k) or "")
        for k in ("hauptberuf", "beruf", "occupation", "description", "snippet", "category", "breadcrumbs", "requirements", "tasks", "full_text")
    ).strip()

    if existing_detail:
        ex_exact, ex_equiv, ex_term = _text_has_variant_or_token(existing_detail, token_meta)
        ex_conflict, ex_conflict_term = _text_has_conflict(existing_detail, token_meta)
        if (ex_exact or ex_equiv) and not ex_conflict:
            canonical_occ = token_meta.get("canonical") or ex_term
            if is_generic_only_title(title):
                if not title or title.lower() in {"n/a", "k. a.", "none"}:
                    job["title"] = f"Ausbildung {canonical_occ}"
                elif canonical_occ.lower() not in title.lower():
                    job["title"] = f"{title} ({canonical_occ})"
            res = {
                "search_query": search_keyword,
                "normalized_requested_occupation": req_occ,
                "detected_job_occupation": canonical_occ,
                "occupation_match_type": "probable_match",
                "relevance_score": 0.85,
                "relevance_decision_reason": f"Stage B confirmed '{canonical_occ}' via detail metadata ('{ex_term}')",
            }
            job.update(res)
            return res

    # If URL is available, inspect detail page via bounded HTTP fetch
    detail_url = str(job.get("job_listing_url") or job.get("url") or job.get("apply_url") or "").strip()
    if detail_url.startswith(("http://", "https://")):
        try:
            from bs4 import BeautifulSoup

            http = session or _get_stage_b_session()
            resp = http.get(
                detail_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code < 400 and resp.text:
                html_text = resp.text
                # Check Arbeitsagentur ng-state for hauptberuf / stellenangebotsbeschreibung
                hb_match = re.search(r'"hauptberuf"\s*:\s*"([^"]+)"', html_text)
                if hb_match:
                    hb_val = hb_match.group(1).strip()
                    job["hauptberuf"] = hb_val
                    hb_exact, hb_equiv, hb_term = _text_has_variant_or_token(hb_val, token_meta)
                    if hb_exact or hb_equiv:
                        if is_generic_only_title(title):
                            job["title"] = f"{title} ({hb_val})" if title and title.lower() not in {"n/a", "k. a."} else f"Ausbildung {hb_val}"
                        res = {
                            "search_query": search_keyword,
                            "normalized_requested_occupation": req_occ,
                            "detected_job_occupation": hb_val,
                            "occupation_match_type": "probable_match",
                            "relevance_score": 0.85,
                            "relevance_decision_reason": f"Stage B confirmed structured hauptberuf '{hb_val}' on detail page",
                        }
                        job.update(res)
                        return res

                soup = BeautifulSoup(html_text, "html.parser")
                for tag in soup(["script", "style", "noscript", "svg"]):
                    tag.decompose()
                page_text = " ".join(soup.get_text(" ", strip=True).split())[:8000]
                p_exact, p_equiv, p_term = _text_has_variant_or_token(page_text, token_meta)
                p_conflict, p_conflict_term = _text_has_conflict(page_text[:1500], token_meta)
                if (p_exact or p_equiv) and not (p_conflict and not p_exact):
                    canonical_occ = token_meta.get("canonical") or p_term
                    if is_generic_only_title(title):
                        job["title"] = f"{title} ({canonical_occ})" if title and title.lower() not in {"n/a", "k. a."} else f"Ausbildung {canonical_occ}"
                    res = {
                        "search_query": search_keyword,
                        "normalized_requested_occupation": req_occ,
                        "detected_job_occupation": canonical_occ,
                        "occupation_match_type": "probable_match",
                        "relevance_score": 0.85,
                        "relevance_decision_reason": f"Stage B confirmed occupation '{p_term}' in detail page content",
                    }
                    job.update(res)
                    return res
        except Exception as exc:
            logger.debug("Stage B detail verification fetch failed for %s: %s", detail_url, exc)

    # Unconfirmed ambiguous listing -> reject before contact extraction and Excel export
    res = {
        "search_query": search_keyword,
        "normalized_requested_occupation": req_occ,
        "detected_job_occupation": "unconfirmed_generic",
        "occupation_match_type": "irrelevant",
        "relevance_score": 0.0,
        "relevance_decision_reason": f"Stage B rejected generic title '{title}': occupation '{req_occ}' not confirmed on detail page",
    }
    job.update(res)
    return res


def is_profession_relevant(
    title: str,
    hauptberuf: str,
    search_keyword: str,
    description: str = "",
) -> bool:
    """
    Checks if a job's title, hauptberuf, or description matches the searched profession.
    Rejects clearly unrelated professions (e.g., Industriekaufmann or Hotelfachmann for Koch)
    and unconfirmed generic titles (e.g., 'Ausbildung 2027' with no occupation evidence).
    Accepts exact matches, equivalent German synonyms/variants, and probable matches.
    """
    sample_job = {
        "title": title,
        "hauptberuf": hauptberuf,
        "description": description,
    }
    scored = score_occupation_relevance(sample_job, search_keyword)
    return scored["occupation_match_type"] in {
        "exact_match",
        "equivalent_occupation",
        "probable_match",
    }



def clean_extracted_location(location_str: str, city_str: str = "") -> Dict[str, str]:
    """
    Cleans raw location strings extracted by scrapers.
    Strips noise like 'Video', 'Online', 'Standort'.
    Extracts 5-digit postal code and normalized city.
    """
    loc_clean = str(location_str or "").strip()
    city_clean = str(city_str or "").strip()

    # Discard known garbage badges
    if loc_clean.lower() in DISALLOWED_LOCATION_TOKENS:
        loc_clean = ""
    if city_clean.lower() in DISALLOWED_LOCATION_TOKENS:
        city_clean = ""

    # Clean out parenthetical notes like '(u.a.)', 'Standort:'
    loc_clean = re.sub(r"\(u\.a\.\)", "", loc_clean, flags=re.I).strip()
    loc_clean = re.sub(r"^standort[:\s]*", "", loc_clean, flags=re.I).strip()

    # Extract 5-digit PLZ if present
    plz = ""
    plz_match = re.search(r"\b(\d{5})\b", loc_clean) or re.search(r"\b(\d{5})\b", city_clean)
    if plz_match:
        plz = plz_match.group(1)

    # If city is missing or has PLZ embedded
    if not city_clean and loc_clean:
        city_candidate = re.sub(r"\b\d{5}\b", "", loc_clean).strip()
        if city_candidate and city_candidate.lower() not in DISALLOWED_LOCATION_TOKENS:
            city_clean = city_candidate

    if not loc_clean and city_clean:
        loc_clean = f"{plz} {city_clean}".strip() if plz else city_clean

    return {
        "postal_code": plz or "N/A",
        "city": city_clean or "k. A.",
        "location": loc_clean or "k. A.",
    }


def is_location_relevant(
    job_location: str,
    job_city: str,
    job_plz: str,
    search_location: str,
) -> bool:
    """
    Validates that a job satisfies the searched location.
    - Rejects nationwide jobs (München, Stuttgart, etc.) when the user searches for a specific city (Ahaus).
    - Accepts exact matches, nearby commuter towns, and same 2-digit PLZ region.
    - Cleans out malformed location metadata like 'Video'.
    """
    search_loc = str(search_location or "").strip().lower()
    if not search_loc or search_loc in {"deutschland", "bundesweit", "alle", "all"}:
        return True

    job_loc_norm = str(job_location or "").lower()
    job_city_norm = str(job_city or "").lower()
    job_plz_clean = str(job_plz or "").strip()

    # If job location was garbage (e.g. 'video') and got cleaned to 'k. A.', reject specific search
    if job_loc_norm in DISALLOWED_LOCATION_TOKENS or job_city_norm in DISALLOWED_LOCATION_TOKENS:
        return False
    if job_loc_norm in {"k. a.", "n/a", ""} and job_city_norm in {"k. a.", "n/a", ""}:
        return False

    # 1. Exact city match
    if search_loc in job_city_norm or search_loc in job_loc_norm:
        return True
    if job_city_norm and job_city_norm in search_loc:
        return True

    # 2. PLZ search (user typed e.g. 48683)
    if re.fullmatch(r"\d{5}", search_loc):
        if job_plz_clean == search_loc:
            return True
        if job_plz_clean and job_plz_clean[:2] == search_loc[:2]:
            return True
        return False

    # 3. Known regional knowledge base (e.g. Ahaus -> PLZ 48/46 & Münsterland towns)
    search_loc_clean = normalize_umlauts(search_loc)
    region_info = None
    for reg_key, reg_data in GERMAN_CITY_REGIONS.items():
        if reg_key == search_loc or reg_key == search_loc_clean:
            region_info = reg_data
            break

    if region_info:
        # Check if job PLZ matches allowed regional prefixes
        if job_plz_clean and any(job_plz_clean.startswith(prefix) for prefix in region_info["plz_prefixes"]):
            return True
        # Check if job city is in allowed regional commuter towns
        job_city_clean = normalize_umlauts(job_city_norm)
        if any(town in job_city_norm or town in job_city_clean for town in region_info["nearby_cities"]):
            return True

        # If it's a known faraway city (e.g. Stuttgart 70xxx, München 80xxx, Biberach 88xxx, Potsdam 14xxx), reject!
        return False

    # 4. General fallback: if search_loc is not in knowledge base, check if PLZ 2-digit matches
    if job_plz_clean and len(job_plz_clean) == 5:
        # If user typed another German city not in KB, allow if city name matches
        return search_loc in job_city_norm or search_loc in job_loc_norm

    return search_loc in job_loc_norm or search_loc in job_city_norm


def parse_german_date(date_val: Any, reference_date: Optional[datetime] = None) -> Optional[datetime]:
    """
    Parses various German date formats into datetime object.
    Supports YYYY-MM-DD, DD.MM.YYYY, and relative expressions (heute, gestern, vor X Tagen).
    """
    if not date_val:
        return None

    ref_date = reference_date or datetime.now()
    val_str = str(date_val).strip()

    # 1. ISO format: YYYY-MM-DD
    iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", val_str)
    if iso_match:
        try:
            return datetime(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            pass

    # 2. German format: DD.MM.YYYY
    de_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", val_str)
    if de_match:
        try:
            return datetime(int(de_match.group(3)), int(de_match.group(2)), int(de_match.group(1)))
        except ValueError:
            pass

    # 3. Relative date formats
    val_lower = val_str.lower()
    if "heute" in val_lower:
        return ref_date
    if "gestern" in val_lower:
        return ref_date - timedelta(days=1)

    tagen_match = re.search(r"vor\s+(\d+)\s+tag", val_lower)
    if tagen_match:
        return ref_date - timedelta(days=int(tagen_match.group(1)))

    wochen_match = re.search(r"vor\s+(\d+)\s+woche", val_lower)
    if wochen_match:
        return ref_date - timedelta(days=int(wochen_match.group(1)) * 7)

    return None


LIVE_PORTAL_SOURCES = {
    "arbeitsagentur",
    "arbeitsagentur.de",
    "ausbildung.de",
    "ausbildung_de",
    "azubiyo",
    "azubiyo.de",
    "aubi-plus",
    "aubi-plus.de",
    "aubi_plus",
    "aubi_plus.de",
    "ihk",
    "ihk.de",
    "ihk_lehrstellenboerse",
    "google_maps",
    "google-maps",
    "maps",
}


def is_publication_date_matching(
    published_date_raw: Any,
    max_days: Optional[int],
    is_source_prefiltered: bool = False,
    reference_date: Optional[datetime] = None,
    source: str = "",
) -> bool:
    """
    Validates whether a job falls within the requested publication period.
    Never silently substitutes scraping date for publication date.
    Strictly applies max_days to parsed publication dates.
    For active live portals (e.g. Ausbildung.de, Azubiyo, AUBI-plus, IHK) where vacancies
    are active live listings without an explicit publication date ("k. A."),
    they are preserved as active matches within the requested window.
    """
    if max_days is None:
        return True

    dt = parse_german_date(published_date_raw, reference_date=reference_date)
    if dt is not None:
        ref_date = reference_date or datetime.now()
        age_days = (ref_date - dt).days
        return 0 <= age_days <= max_days

    # If date is missing/unparsed, check if source is prefiltered or a live vacancy portal
    if is_source_prefiltered:
        return True

    src_lower = str(source or "").lower().strip()
    if src_lower and any(portal in src_lower for portal in LIVE_PORTAL_SOURCES):
        return True

    # Date is unknown or 'k. A.' on a non-live or unverified source
    return False


def verify_application_workflow(job: Dict) -> Dict[str, Any]:
    """
    Verifies the application workflow destination according to the 5 strict categories:
    1. Verified direct application form.
    2. Verified job-specific application starting page.
    3. Generic careers page.
    4. Ordinary job advertisement.
    5. Missing or inaccessible application destination.

    Only categories 1 and 2 count as verified online application workflows (has_form=True).
    """
    has_form_flag = job.get("has_form")
    is_form_true = has_form_flag is True or str(has_form_flag).strip().lower() == "true"
    form_link = str(job.get("form_link") or "").strip()
    apply_url = str(job.get("apply_url") or job.get("url") or "").strip()
    email = str(job.get("email") or "").strip()
    has_valid_email = bool(
        email
        and "@" in email
        and not any(x in email.lower() for x in ["failed", "error", "duplicate", "none"])
    )

    # Portals whose raw listing URLs can NEVER be classified as a verified form
    PORTAL_DOMAINS = {
        "arbeitsagentur.de",
        "ausbildung.de",
        "azubiyo.de",
        "aubi-plus.de",
        "ihk.de",
        "lehrstellenboerse.ihk.de",
    }

    is_portal_url = any(dom in (form_link or apply_url).lower() for dom in PORTAL_DOMAINS)

    if is_form_true and form_link and not is_portal_url:
        category = 1
        category_name = "Verified direct application form"
        verified_form = True
    elif is_form_true and form_link:
        category = 2
        category_name = "Verified job-specific application starting page"
        verified_form = True
    elif form_link or apply_url:
        target = form_link or apply_url
        if any(w in target.lower() for w in ["karriere", "career", "jobs.", "/jobs"]):
            category = 3
            category_name = "Generic careers page"
        else:
            category = 4
            category_name = "Ordinary job advertisement"
        verified_form = False
    else:
        category = 5
        category_name = "Missing or inaccessible application destination"
        verified_form = False

    # Action configuration for frontend rendering
    if verified_form:
        action_button = {
            "type": "verified_form",
            "url": form_link or apply_url,
            "label": "Zum Bewerbungsformular ↗",
            "badge": "Online-Bewerbungsformular",
            "autofill": True,
        }
    elif apply_url:
        action_button = {
            "type": "listing",
            "url": apply_url,
            "label": "Stellenanzeige öffnen ↗",
            "badge": "Stellenanzeige",
            "autofill": False,
        }
    elif form_link:
        action_button = {
            "type": "career",
            "url": form_link,
            "label": "Karriereseite öffnen ↗",
            "badge": "Karriereseite",
            "autofill": False,
        }
    else:
        action_button = {
            "type": "none",
            "url": "",
            "label": "",
            "badge": "Kein Link",
            "autofill": False,
        }

    return {
        "category": category,
        "category_name": category_name,
        "verified_form": verified_form,
        "has_valid_email": has_valid_email,
        "action_button": action_button,
    }


def filter_and_deduplicate_jobs(
    jobs: List[Dict],
    keyword: str = "",
    location: str = "",
    published_since_days: Optional[int] = None,
    reference_date: Optional[datetime] = None,
    return_audit: bool = False,
    mode: str = "ausbildung",
) -> Union[List[Dict], Tuple[List[Dict], Dict[str, Any]]]:
    """
    Applies shared post-scraping relevance validation layer across all sources:
    1. Cleans malformed locations (e.g. 'Video').
    2. Rejects unrelated professions (e.g. Industriekaufmann when searching for Koch).
    3. Rejects distant locations when a specific city is searched (e.g. München when searching for Ahaus).
    4. Filters by publication date (separates published_date from scraped_at).
    5. Deduplicates cross-portal opportunities.

    Tracks full audit metrics at every stage with explicit rejection reasons.
    """
    filtered: List[Dict] = []
    seen_keys: Set[str] = set()
    seen_jobs: Dict[str, Dict] = {}

    raw_total = len(jobs)
    raw_by_source: Dict[str, int] = {}
    filtered_by_source: Dict[str, int] = {}
    exclusions: List[Dict[str, Any]] = []

    per_source_stats: Dict[str, Dict[str, int]] = {}
    relevance_summary: Dict[str, int] = {
        "exact_matches": 0,
        "equivalent_occupation_matches": 0,
        "probable_matches": 0,
        "uncertain_results": 0,
        "irrelevant_results_rejected": 0,
    }

    for j in jobs:
        src = str((j.get("source") if isinstance(j, dict) else "") or "Unknown").strip()
        raw_by_source[src] = raw_by_source.get(src, 0) + 1
        if src not in per_source_stats:
            per_source_stats[src] = {
                "raw": 0,
                "valid": 0,
                "rejected_profession": 0,
                "rejected_location": 0,
                "rejected_date": 0,
                "rejected_duplicate": 0,
            }
        per_source_stats[src]["raw"] += 1

    # Pre-score Stage A and batch-verify Stage B ('uncertain') concurrently when multiple uncertain jobs exist
    pre_scored_map: Dict[int, Dict[str, Any]] = {}
    if keyword:
        uncertain_pairs: List[Tuple[int, Dict[str, Any]]] = []
        for idx_j, j_cand in enumerate(jobs):
            if not isinstance(j_cand, dict):
                continue
            is_pot = j_cand.get("opportunity_type") == "POTENTIAL_EMPLOYER" or bool(j_cand.get("is_potential_employer"))
            if not is_pot:
                sc = score_occupation_relevance(j_cand, keyword)
                pre_scored_map[idx_j] = sc
                if sc["occupation_match_type"] == "uncertain":
                    uncertain_pairs.append((idx_j, j_cand))

        if len(uncertain_pairs) > 1:
            from concurrent.futures import ThreadPoolExecutor
            shared_sess = _get_stage_b_session()
            with ThreadPoolExecutor(max_workers=min(8, len(uncertain_pairs))) as sb_pool:
                futs = {
                    idx_u: sb_pool.submit(verify_ambiguous_job_relevance, j_u, keyword, shared_sess)
                    for idx_u, j_u in uncertain_pairs
                }
                for idx_u, fut_u in futs.items():
                    try:
                        pre_scored_map[idx_u] = (fut_u.result(), True)
                    except Exception:
                        pass
        elif len(uncertain_pairs) == 1:
            idx_u, j_u = uncertain_pairs[0]
            pre_scored_map[idx_u] = (verify_ambiguous_job_relevance(j_u, keyword), True)

    for idx_job, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue

        src = str(job.get("source") or "Unknown").strip()
        title = str(job.get("title") or "").strip()
        hauptberuf = str(job.get("hauptberuf") or "").strip()
        company = str(job.get("company") or "k. A.").strip()

        # 1. Two-Stage Profession Relevance Validation (Stage A + Stage B)
        is_potential = job.get("opportunity_type") == "POTENTIAL_EMPLOYER" or bool(job.get("is_potential_employer"))
        if keyword and not is_potential:
            pre_val = pre_scored_map.get(idx_job)
            if isinstance(pre_val, tuple):
                scored, was_uncertain = pre_val
                if was_uncertain:
                    relevance_summary["uncertain_results"] += 1
            elif isinstance(pre_val, dict):
                scored = pre_val
            else:
                scored = score_occupation_relevance(job, keyword)
                if scored["occupation_match_type"] == "uncertain":
                    relevance_summary["uncertain_results"] += 1
                    scored = verify_ambiguous_job_relevance(job, keyword)
            match_type = scored["occupation_match_type"]

            if match_type == "exact_match":
                relevance_summary["exact_matches"] += 1
            elif match_type == "equivalent_occupation":
                relevance_summary["equivalent_occupation_matches"] += 1
            elif match_type == "probable_match":
                relevance_summary["probable_matches"] += 1
            else:
                relevance_summary["irrelevant_results_rejected"] += 1
                per_source_stats[src]["rejected_profession"] += 1
                exclusions.append({
                    "stage": "profession",
                    "source": src,
                    "title": title,
                    "company": company,
                    "location": str(job.get("location") or "k. A."),
                    "occupation_match_type": match_type,
                    "reason": scored.get("relevance_decision_reason")
                    or f"Titel/Beruf '{title}' entspricht nicht dem gesuchten Berufsfeld '{keyword}'",
                })
                continue
        else:
            job.setdefault("search_query", keyword)
            job.setdefault("normalized_requested_occupation", normalize_occupation_term(keyword))
            job.setdefault("detected_job_occupation", detect_job_occupation(job) or title)
            job.setdefault("occupation_match_type", "exact_match")
            job.setdefault("relevance_score", 1.0)
            job.setdefault("relevance_decision_reason", "Unfiltered or potential employer")
            relevance_summary["exact_matches"] += 1
        title = str(job.get("title") or title).strip()

        # 2. Location Cleaning & Validation
        loc_meta = clean_extracted_location(job.get("location", ""), job.get("city", ""))
        job["location"] = loc_meta["location"]
        job["city"] = loc_meta["city"]
        if loc_meta["postal_code"] != "N/A" and not job.get("postal_code"):
            job["postal_code"] = loc_meta["postal_code"]

        if location and not is_location_relevant(
            job["location"],
            job["city"],
            job.get("postal_code", ""),
            location,
        ):
            per_source_stats[src]["rejected_location"] += 1
            exclusions.append({
                "stage": "location",
                "source": src,
                "title": title,
                "company": company,
                "location": job["location"],
                "reason": f"Ort '{job['location']}' liegt außerhalb des Pendelbereichs/Suchgebiets von '{location}'",
            })
            continue

        # 3. Publication Date Validation
        pub_date = job.get("published_date")
        src_lower = src.lower()
        is_source_prefiltered = ("arbeitsagentur" in src_lower and published_since_days is not None) or bool(job.get("is_source_prefiltered"))

        if published_since_days is not None:
            if not is_publication_date_matching(
                pub_date,
                published_since_days,
                is_source_prefiltered=is_source_prefiltered,
                reference_date=reference_date,
                source=src,
            ):
                per_source_stats[src]["rejected_date"] += 1
                exclusions.append({
                    "stage": "date",
                    "source": src,
                    "title": title,
                    "company": company,
                    "location": job["location"],
                    "published_date": str(pub_date or "k. A."),
                    "reason": f"Veröffentlichungsdatum '{pub_date}' überschreitet das Zeitfenster von {published_since_days} Tagen",
                })
                continue

        # 4. Verified Application Workflow Classification
        wf = verify_application_workflow(job)
        is_arbeit = str(mode or "").lower() == "arbeit"
        if is_arbeit:
            job["has_form"] = bool(job.get("has_form", False))
            job["application_category"] = wf["category"]
            job["application_category_name"] = "Arbeitgeber / Stellenangebot" if not job["has_form"] else wf["category_name"]
        else:
            job["has_form"] = wf["verified_form"]
            job["application_category"] = wf["category"]
            job["application_category_name"] = wf["category_name"]

        # 5. Cross-portal Deduplication key
        comp_norm = re.sub(r"[^a-zA-Z0-9]+", "", str(job.get("company") or "").lower())
        title_norm = re.sub(r"[^a-zA-Z0-9]+", "", str(job.get("title") or "").lower())
        city_norm = re.sub(r"[^a-zA-Z0-9]+", "", str(job.get("city") or "").lower())

        if comp_norm and title_norm:
            dedupe_key = f"{comp_norm}|{title_norm}|{city_norm}"
        else:
            dedupe_key = str(job.get("reference") or job.get("url") or id(job))

        if dedupe_key in seen_keys:
            orig = seen_jobs.get(dedupe_key, {})
            orig_src = orig.get("source", "anderes Portal")
            per_source_stats[src]["rejected_duplicate"] += 1
            exclusions.append({
                "stage": "duplicate",
                "source": src,
                "title": title,
                "company": company,
                "location": job["location"],
                "duplicate_of": f"{orig.get('title')} ({orig_src})",
                "reason": f"Cross-Portal Duplikat von '{orig.get('title')}' bei '{orig.get('company')}' ({orig_src})",
            })
            continue

        seen_keys.add(dedupe_key)
        seen_jobs[dedupe_key] = job

        filtered_by_source[src] = filtered_by_source.get(src, 0) + 1
        per_source_stats[src]["valid"] += 1
        filtered.append(job)

    audit: Dict[str, Any] = {
        "raw_total": raw_total,
        "raw_by_source": raw_by_source,
        "filtered_total": len(filtered),
        "filtered_by_source": filtered_by_source,
        "exclusions_total": len(exclusions),
        "exclusions_by_stage": {
            "profession": sum(1 for e in exclusions if e["stage"] == "profession"),
            "location": sum(1 for e in exclusions if e["stage"] == "location"),
            "date": sum(1 for e in exclusions if e["stage"] == "date"),
            "duplicate": sum(1 for e in exclusions if e["stage"] == "duplicate"),
        },
        "relevance_summary": relevance_summary,
        "exclusions_by_source": per_source_stats,
        "exclusions": exclusions,
    }

    logger.info(
        "Job filtering audit: %d/%d valid matching opportunities across %d sources. Excluded %d (loc: %d, prof: %d, date: %d, dupe: %d) | Relevance: exact=%d, equiv=%d, probable=%d, uncertain=%d, rejected=%d",
        len(filtered),
        raw_total,
        len(raw_by_source),
        len(exclusions),
        audit["exclusions_by_stage"]["location"],
        audit["exclusions_by_stage"]["profession"],
        audit["exclusions_by_stage"]["date"],
        audit["exclusions_by_stage"]["duplicate"],
        relevance_summary["exact_matches"],
        relevance_summary["equivalent_occupation_matches"],
        relevance_summary["probable_matches"],
        relevance_summary["uncertain_results"],
        relevance_summary["irrelevant_results_rejected"],
    )

    if return_audit:
        return filtered, audit
    return filtered


def filter_and_deduplicate_jobs_with_audit(
    jobs: List[Dict],
    keyword: str = "",
    location: str = "",
    published_since_days: Optional[int] = None,
    reference_date: Optional[datetime] = None,
    mode: str = "ausbildung",
) -> Tuple[List[Dict], Dict[str, Any]]:
    """Helper that always returns both the filtered job opportunities and the complete audit dict."""
    res, audit = filter_and_deduplicate_jobs(
        jobs,
        keyword=keyword,
        location=location,
        published_since_days=published_since_days,
        reference_date=reference_date,
        return_audit=True,
        mode=mode,
    )
    return res, audit
