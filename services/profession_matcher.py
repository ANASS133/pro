"""
JobScout Profession Matcher Service.
Provides intelligence for matching candidate / client Ausbildung professions
against available datasets in JobScout (data/auto_extraction_exports).

Determines 3 availability states:
- "available" (Vorhanden, Green): Direct / exact matching Ausbildung dataset exists.
- "similar" (Ähnlich, Yellow): Related profession dataset exists (same occupational cluster/branch).
- "missing" (Nicht vorhanden, Red): No matching or related dataset exists.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from scraper.search_filter_engine import (
    extract_profession_tokens,
    normalize_umlauts,
    PROFESSION_KNOWLEDGE_BASE,
    GERMAN_STOP_WORDS,
)

# Generic German compound word affixes to exclude from stem matching
GENERIC_AFFIXES = {
    "mann", "frau", "frauen", "leute", "fach", "kraft", "kraefte", "kräfte",
    "helfer", "helferin", "assistent", "assistentin", "beruf", "ausbildung",
    "wesen", "dienst", "stelle"
}

# Occupational clusters for determining related ("Ähnlich") professions
PROFESSION_CLUSTERS: Dict[str, Dict[str, Any]] = {
    "it": {
        "name": "IT, Software & Informatik",
        "tokens": {
            "fachinformatiker", "fachinformatikerin", "fachinformatik", "informatik",
            "informatiker", "informatikerin", "anwendungsentwicklung", "systemintegration",
            "daten- und prozessanalyse", "datenanalyse", "digitale vernetzung",
            "softwareentwickler", "softwareentwicklerin", "it-system", "it-system-management",
            "it-systemkaufmann", "it-systemkauffrau", "informatikkaufmann", "informatikkauffrau",
            "medieninformatik", "medieninformatiker", "fachberater", "webentwickler",
            "systemadministrator", "programmierer", "fachberater integrierte systeme"
        }
    },
    "pflege_gesundheit": {
        "name": "Pflege, Medizin & Gesundheit",
        "tokens": {
            "pflegefachmann", "pflegefachfrau", "pflegefachkraft", "altenpfleger",
            "altenpflegerin", "gesundheits- und krankenpfleger", "krankenpfleger",
            "krankenschwester", "pflegehelfer", "pflegehelferin", "pflegeassistent",
            "notfallsanitäter", "notfallsanitaeter", "mfa", "medizinische fachangestellte",
            "zfa", "zmfa", "zahnmedizinische fachangestellte", "physiotherapeut",
            "physiotherapeutin", "ergotherapeut", "hebamme", "ota",
            "operationstechnischer assistent", "anästhesietechnischer assistent"
        }
    },
    "gastronomie_ernaehrung": {
        "name": "Gastronomie, Hotellerie & Ernährung",
        "tokens": {
            "koch", "köchin", "koechin", "köche", "koeche", "beikoch", "beiköchin",
            "chefkoch", "jungkoch", "küchenchef", "kuechenchef", "gastronomiekoch",
            "diätkoch", "diaetkoch", "restaurantfachmann", "restaurantfachfrau",
            "hotelfachmann", "hotelfachfrau", "fachkraft gastgewerbe", "gastronom",
            "bäcker", "bäckerin", "baecker", "baeckerin", "konditor", "konditorin",
            "fleischer", "fleischerin", "metzger", "metzgerin", "fachverkäufer lebensmittel"
        }
    },
    "lager_logistik": {
        "name": "Lager, Logistik & Transport",
        "tokens": {
            "fachkraft für lagerlogistik", "fachkraft fuer lagerlogistik", "lagerlogistik",
            "fachlagerist", "fachlageristin", "lagerist", "lageristin", "kommissionierer",
            "logistik", "spedition", "kaufmann für spedition", "kauffrau für spedition",
            "spedition und logistikdienstleistung", "berufskraftfahrer", "berufskraftfahrerin",
            "fachkraft f r lagerlogistik"
        }
    },
    "wirtschaft_kaufmaennisch": {
        "name": "Wirtschaft, Verwaltung & Handel",
        "tokens": {
            "kaufmann", "kauffrau", "kaufleute", "industriekaufmann", "industriekauffrau",
            "industriekaufleute", "büromanagement", "bueromanagement", "einzelhandel",
            "verkäufer", "verkäuferin", "verkaeufer", "verkaeuferin", "großhandel",
            "grosshandel", "außenhandel", "aussenhandel", "bankkaufmann", "bankkauffrau",
            "immobilienkaufmann", "immobilienkauffrau", "automobilkaufmann",
            "automobilkauffrau", "e-commerce", "steuerfachangestellter",
            "steuerfachangestellte", "verwaltungsfachangestellter", "handelsfachwirt"
        }
    },
    "technik_elektro": {
        "name": "Technik, Elektro & Handwerk",
        "tokens": {
            "mechatroniker", "mechatronikerin", "kfz-mechatroniker", "kfz-mechatronikerin",
            "kraftfahrzeugmechatroniker", "industriemechaniker", "industriemechanikerin",
            "anlagenmechaniker", "anlagenmechanikerin", "konstruktionsmechaniker",
            "zerspanungsmechaniker", "elektroniker", "elektronikerin", "elektriker",
            "elektroinstallateur", "elektrotechnik", "schreiner", "schreinerin",
            "tischler", "tischlerin", "maler", "lackierer", "dachdecker", "zimmerer",
            "metallbauer", "feinwerkmechaniker"
        }
    }
}


def _normalize_morphology(word: str) -> str:
    """Normalizes gender and plural suffixes to canonical base."""
    w = normalize_umlauts(word.lower().strip())
    # Strip gender/plural endings
    if w.endswith("innen"):
        return w[:-5]
    if w.endswith("in") and len(w) > 4:
        return w[:-2]
    if w.endswith("frauen"):
        return w[:-6] + "mann"
    if w.endswith("frau"):
        return w[:-4] + "mann"
    if w.endswith("leute"):
        return w[:-5] + "mann"
    if w.endswith("kraefte") or w.endswith("kräfte"):
        return w[:-7] + "kraft"
    return w


def _is_exact_morphological_match(t1: str, t2: str) -> bool:
    """Checks if two tokens are exact or gender/morphological variants of each other."""
    n1 = _normalize_morphology(t1)
    n2 = _normalize_morphology(t2)
    if n1 == n2:
        return True

    # e.g. koch <-> koechin -> n1='koch', n2='koech'
    if (n1.startswith("koch") and n2.startswith("koch")) or (n1.startswith("koech") and n2.startswith("koech")):
        return True
    if (n1.startswith("koch") and n2.startswith("koech")) or (n1.startswith("koech") and n2.startswith("koch")):
        return True

    # e.g. pflegefachmann <-> pflegefachkraft
    if n1.startswith("pflegefach") and n2.startswith("pflegefach"):
        return True

    # e.g. fachinformatik <-> fachinformatiker
    if (n1.startswith("fachinformatik") and n2.startswith("fachinformatik")):
        return True

    # e.g. lagerlogistik <-> fachkraft fuer lagerlogistik
    if ("lagerlogistik" in n1 and "lagerlogistik" in n2):
        return True

    return False


def _get_profession_cluster_keys(tokens: Set[str]) -> Set[str]:
    """Finds which profession clusters match any of the given tokens."""
    matched_clusters = set()
    norm_tokens = {normalize_umlauts(t.lower()) for t in tokens if len(t) >= 3 and t.lower() not in GENERIC_AFFIXES}

    for cluster_key, cluster_data in PROFESSION_CLUSTERS.items():
        for kw in cluster_data["tokens"]:
            norm_kw = normalize_umlauts(kw.lower())
            for t in norm_tokens:
                if t in GENERIC_AFFIXES:
                    continue
                # Full token match or prefix match for words >= 5 chars
                if t == norm_kw or (len(t) >= 5 and (t in norm_kw or norm_kw in t)):
                    matched_clusters.add(cluster_key)
                    break

    return matched_clusters


def evaluate_profession_match(
    profession_query: str,
    available_datasets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Evaluates whether an Ausbildung dataset is available for a given client profession.

    Args:
        profession_query: The client's target profession or field (e.g. from app.field)
        available_datasets: List of dataset dicts containing at least 'domain_name' or 'filename'

    Returns:
        Dict with keys:
            status: 'available' | 'similar' | 'missing'
            label: 'Vorhanden' | 'Ähnlich' | 'Nicht vorhanden'
            matched_dataset: Dict of matched dataset or None
            details: Human-readable explanation string
    """
    query_str = str(profession_query or "").strip()
    if not query_str or query_str.lower() in {"k. a.", "k.a.", "n/a", "undefined", "none", "null"}:
        return {
            "status": "missing",
            "label": "Nicht vorhanden",
            "match_type": None,
            "matched_profession": None,
            "matched_dataset": None,
            "matched_datasets": [],
            "total_listings": 0,
            "details": "Kein passender Datensatz gefunden.",
        }

    query_meta = extract_profession_tokens(query_str)
    if query_meta.get("is_generic"):
        return {
            "status": "missing",
            "label": "Nicht vorhanden",
            "match_type": None,
            "matched_profession": None,
            "matched_dataset": None,
            "matched_datasets": [],
            "total_listings": 0,
            "details": "Kein passender Datensatz gefunden.",
        }

    client_core = {t for t in query_meta["core_tokens"] if t not in GENERIC_AFFIXES}
    if not client_core:
        return {
            "status": "missing",
            "label": "Nicht vorhanden",
            "match_type": None,
            "matched_profession": None,
            "matched_dataset": None,
            "matched_datasets": [],
            "total_listings": 0,
            "details": "Kein passender Datensatz gefunden.",
        }

    client_norm_core = {normalize_umlauts(t.lower()) for t in client_core}

    if not available_datasets:
        return {
            "status": "missing",
            "label": "Nicht vorhanden",
            "match_type": None,
            "matched_profession": None,
            "matched_dataset": None,
            "matched_datasets": [],
            "total_listings": 0,
            "details": "Kein passender Datensatz gefunden.",
        }

    # -------------------------------------------------------------
    # PASS 1: Check for Direct / Exact Matches ("available" -> "Vorhanden")
    # -------------------------------------------------------------
    exact_matches: List[Dict[str, Any]] = []
    seen_exact_files: Set[str] = set()

    for ds in available_datasets:
        fn = str(ds.get("filename") or "").strip()
        if fn and fn in seen_exact_files:
            continue

        domain_name = str(ds.get("domain_name") or ds.get("filename") or "").lower()
        if not domain_name:
            continue

        ds_meta = extract_profession_tokens(domain_name)
        ds_core = {t for t in ds_meta["core_tokens"] if t not in GENERIC_AFFIXES}
        ds_norm_core = {normalize_umlauts(t.lower()) for t in ds_core}

        matched = False

        # Exact token match or exact morphological match
        for c_tok in client_norm_core:
            for d_tok in ds_norm_core:
                if _is_exact_morphological_match(c_tok, d_tok):
                    matched = True
                    break
            if matched:
                break

        # Check full string normalized inclusion (e.g. "fachkraft fuer lagerlogistik")
        if not matched:
            norm_domain = normalize_umlauts(domain_name)
            for c_tok in client_norm_core:
                if len(c_tok) >= 6 and c_tok in norm_domain and not any(conf in norm_domain for conf in query_meta["conflicts"]):
                    if c_tok not in GENERIC_AFFIXES:
                        matched = True
                        break

        if matched:
            exact_matches.append(ds)
            if fn:
                seen_exact_files.add(fn)

    if exact_matches:
        total_listings = sum(int(d.get("row_count") or 0) for d in exact_matches)
        primary_ds = exact_matches[0]
        return {
            "status": "available",
            "label": "Vorhanden",
            "match_type": "Exakt",
            "matched_profession": primary_ds.get("domain_name") or primary_ds.get("filename") or query_str,
            "matched_dataset": primary_ds,
            "matched_datasets": exact_matches,
            "total_listings": total_listings,
            "details": f"Passender Datensatz vorhanden ({total_listings} Stellen in {len(exact_matches)} Datei(en))",
        }

    # -------------------------------------------------------------
    # PASS 2: Check for Related / Cluster Matches ("similar" -> "Ähnlich")
    # -------------------------------------------------------------
    client_clusters = _get_profession_cluster_keys(client_core)
    similar_matches: List[Dict[str, Any]] = []
    seen_similar_files: Set[str] = set()

    for ds in available_datasets:
        fn = str(ds.get("filename") or "").strip()
        if fn and fn in seen_similar_files:
            continue

        domain_name = str(ds.get("domain_name") or ds.get("filename") or "").lower()
        if not domain_name:
            continue

        ds_meta = extract_profession_tokens(domain_name)
        ds_core = {t for t in ds_meta["core_tokens"] if t not in GENERIC_AFFIXES}
        ds_clusters = _get_profession_cluster_keys(ds_core)

        matched = False

        # 1. Cluster intersection (e.g. Softwareentwickler in IT cluster with Fachinformatiker dataset)
        common_clusters = client_clusters.intersection(ds_clusters)
        if common_clusters:
            conflict_found = any(c in ds_core for c in query_meta["conflicts"]) or any(c in client_core for c in ds_meta["conflicts"])
            if not conflict_found:
                matched = True

        # 2. Shared root (>= 5 chars) with common occupational stem (e.g. informatik)
        if not matched:
            for c_tok in client_norm_core:
                for d_tok in ds_core:
                    norm_d_tok = normalize_umlauts(d_tok.lower())
                    if len(c_tok) >= 5 and len(norm_d_tok) >= 5:
                        if (c_tok.startswith(norm_d_tok[:5]) or norm_d_tok.startswith(c_tok[:5])) and (c_tok not in GENERIC_AFFIXES and norm_d_tok not in GENERIC_AFFIXES):
                            if not any(c in ds_core for c in query_meta["conflicts"]):
                                matched = True
                                break
                if matched:
                    break

        if matched:
            similar_matches.append(ds)
            if fn:
                seen_similar_files.add(fn)

    if similar_matches:
        total_listings = sum(int(d.get("row_count") or 0) for d in similar_matches)
        primary_ds = similar_matches[0]
        return {
            "status": "similar",
            "label": "Ähnlich",
            "match_type": "Ähnlich",
            "matched_profession": primary_ds.get("domain_name") or primary_ds.get("filename") or query_str,
            "matched_dataset": primary_ds,
            "matched_datasets": similar_matches,
            "total_listings": total_listings,
            "details": f"Ähnlicher Datensatz vorhanden ({total_listings} Stellen in {len(similar_matches)} Datei(en))",
        }

    # -------------------------------------------------------------
    # PASS 3: No match ("missing" -> "Nicht vorhanden")
    # -------------------------------------------------------------
    return {
        "status": "missing",
        "label": "Nicht vorhanden",
        "match_type": None,
        "matched_profession": None,
        "matched_dataset": None,
        "matched_datasets": [],
        "total_listings": 0,
        "details": "Kein passender Datensatz gefunden.",
    }

