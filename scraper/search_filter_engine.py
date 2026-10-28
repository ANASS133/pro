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
    "zum",
    "zur",
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
        "variants": {
            "koch",
            "köchin",
            "koechin",
            "köche",
            "koeche",
            "kochs",
            "kueche",
            "küche",
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
        },
        "conflicts": {
            "kaufmann",
            "kauffrau",
            "kaufleute",
            "verkäufer",
            "verkaeufer",
            "versicherungen",
            "finanzanlagen",
            "bankkaufmann",
            "industriekaufmann",
            "industriekauffrau",
            "fachinformatiker",
            "informatik",
            "mechatroniker",
            "elektroniker",
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
        },
    },
    "industriekaufmann": {
        "variants": {
            "industriekaufmann",
            "industriekauffrau",
            "industriekaufleute",
        },
        "conflicts": {"koch", "köchin", "fachinformatiker", "mechatroniker", "friseur"},
    },
    "kaufmann": {
        "variants": {
            "kaufmann",
            "kauffrau",
            "kaufleute",
            "kaufmännisch",
            "kaufmaennisch",
        },
        "conflicts": {"koch", "köchin", "bäcker", "metzger", "schornsteinfeger"},
    },
    "fachinformatiker": {
        "variants": {
            "fachinformatiker",
            "fachinformatikerin",
            "informatik",
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
        "conflicts": {"koch", "köchin", "industriekaufmann", "einzelhandel", "friseur"},
    },
    "informatik": {
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
        "conflicts": {"koch", "köchin", "friseur"},
    },
    "mechatroniker": {
        "variants": {
            "mechatroniker",
            "mechatronikerin",
            "kfz-mechatroniker",
            "kfz-mechatronikerin",
            "kraftfahrzeugmechatroniker",
        },
        "conflicts": {"koch", "köchin", "kaufmann", "kauffrau", "erzieher"},
    },
    "bäcker": {
        "variants": {
            "bäcker",
            "bäckerin",
            "baecker",
            "baeckerin",
            "konditor",
            "konditorin",
            "bäckerei",
        },
        "conflicts": {"kaufmann", "fachinformatiker", "mechatroniker"},
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
    # Split into words
    words = [w for w in re.split(r"[^a-zA-ZäöüÄÖÜß0-9\-]+", cleaned) if w]
    core_words = [w for w in words if w not in GERMAN_STOP_WORDS and len(w) > 1]

    if not core_words:
        # User searched only "Ausbildung" or generic term
        return {"core_tokens": set(), "variants": set(), "conflicts": set(), "is_generic": True}

    core_tokens: Set[str] = set()
    variants: Set[str] = set()
    conflicts: Set[str] = set()

    for word in core_words:
        core_tokens.add(word)
        variants.add(word)
        variants.add(normalize_umlauts(word))

        # Check knowledge base
        for kb_key, kb_data in PROFESSION_KNOWLEDGE_BASE.items():
            if kb_key == word or word in kb_data["variants"] or kb_key in word or word in kb_key:
                variants.update(kb_data["variants"])
                for v in kb_data["variants"]:
                    variants.add(normalize_umlauts(v))
                conflicts.update(kb_data["conflicts"])

        # Automatic German morphological variants (e.g. -er -> -erin, -mann -> -frau)
        if word.endswith("er") and len(word) > 3:
            base = word[:-2]
            variants.add(base + "erin")
            variants.add(base + "erinnen")
            variants.add(base + "er")
        elif word.endswith("mann") and len(word) > 4:
            base = word[:-4]
            variants.add(base + "frau")
            variants.add(base + "frauen")
            variants.add(base + "leute")
            variants.add(base + "männlich")

    return {
        "core_tokens": core_tokens,
        "variants": variants,
        "conflicts": conflicts,
        "is_generic": False,
    }


def is_profession_relevant(title: str, hauptberuf: str, search_keyword: str) -> bool:
    """
    Checks if a job's title or hauptberuf matches the searched profession.
    Rejects clearly unrelated professions (e.g., Industriekaufmann for Koch).
    Accepts legitimate German synonyms and morphological variations (Koch, Köchin, etc.).
    """
    token_meta = extract_profession_tokens(search_keyword)
    if token_meta["is_generic"]:
        return True

    title_norm = str(title or "").lower().strip()
    beruf_norm = str(hauptberuf or "").lower().strip()
    combined_text = f"{title_norm} {beruf_norm}"
    combined_norm = normalize_umlauts(combined_text)

    # Check positive match: any variant or core token matches
    has_variant = any(
        re.search(r"\b" + re.escape(v) + r"\b", combined_text, re.I)
        or re.search(r"\b" + re.escape(v) + r"\b", combined_norm, re.I)
        or (len(v) >= 4 and (v in combined_text or v in combined_norm))
        for v in token_meta["variants"]
    )

    if not has_variant:
        # Check if any core token is a substring of title words (e.g. "koch" in "beikoch", "informatik" in "fachinformatiker")
        has_token = any(
            t in combined_text or t in combined_norm
            for t in token_meta["core_tokens"]
            if len(t) >= 4
        )
        if not has_token:
            return False

    # Conflict check: If conflict keywords are defined and present in the title,
    # ensure that an explicit core variant is present to avoid false positives
    # (e.g. "Kaufmann für Versicherungen" should NOT match "Koch")
    has_conflict = any(
        re.search(r"\b" + re.escape(c) + r"\b", combined_text, re.I)
        or re.search(r"\b" + re.escape(c) + r"\b", combined_norm, re.I)
        for c in token_meta["conflicts"]
    )

    if has_conflict:
        # If there is a conflict profession word (like Kaufmann),
        # only accept if a primary target variant (e.g. Koch) is explicitly present
        primary_match = any(
            re.search(r"\b" + re.escape(tok) + r"\b", combined_text, re.I)
            or re.search(r"\b" + re.escape(tok) + r"\b", combined_norm, re.I)
            or any(re.search(r"\b" + re.escape(v) + r"\b", combined_text, re.I) for v in token_meta["variants"] if len(v) >= 4)
            for tok in token_meta["core_tokens"]
        )
        # For Koch, if title has Kaufmann and no Koch, reject!
        if "koch" in token_meta["core_tokens"] and not any(k in combined_text for k in ["koch", "köch", "koech", "küch", "kuech"]):
            return False

    return True



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

    for job in jobs:
        if not isinstance(job, dict):
            continue

        src = str(job.get("source") or "Unknown").strip()
        title = str(job.get("title") or "").strip()
        hauptberuf = str(job.get("hauptberuf") or "").strip()
        company = str(job.get("company") or "k. A.").strip()

        # 1. Profession Relevance Validation
        is_potential = job.get("opportunity_type") == "POTENTIAL_EMPLOYER" or bool(job.get("is_potential_employer"))
        if keyword and not is_potential and not is_profession_relevant(title, hauptberuf, keyword):
            per_source_stats[src]["rejected_profession"] += 1
            exclusions.append({
                "stage": "profession",
                "source": src,
                "title": title,
                "company": company,
                "location": str(job.get("location") or "k. A."),
                "reason": f"Titel/Beruf '{title}' entspricht nicht dem gesuchten Berufsfeld '{keyword}'",
            })
            continue

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
        "exclusions_by_source": per_source_stats,
        "exclusions": exclusions,
    }

    logger.info(
        "Job filtering audit: %d/%d valid matching opportunities across %d sources. Excluded %d (loc: %d, prof: %d, date: %d, dupe: %d)",
        len(filtered),
        raw_total,
        len(raw_by_source),
        len(exclusions),
        audit["exclusions_by_stage"]["location"],
        audit["exclusions_by_stage"]["profession"],
        audit["exclusions_by_stage"]["date"],
        audit["exclusions_by_stage"]["duplicate"],
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
