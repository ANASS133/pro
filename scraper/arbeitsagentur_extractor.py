"""
Arbeitsagentur Application Details Extractor & Multi-Stage Application Resolver.
================================================================================
Implements smart 4-stage extraction for Arbeitsagentur and German job portal vacancies:
  Stage 1: Official API / SSR embedded JSON data
  Stage 2: High-speed HTML parsing ("Informationen zur Bewerbung" & description)
  Stage 3: Selenium browser fallback (reusing active sessions & handling in-page captchas)
  Stage 4: Employer website discovery (career pages, ATS detection, Kontakt, Impressum)

Never discards an opportunity because an email is missing. Preserves all available
application channels: email, form, external_link, phone, postal.
"""

import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .application_form_discovery import (
    APPLICATION_BUTTON_KEYWORDS,
    KNOWN_ATS_DOMAINS,
    ApplicationFormDiscovery,
    classify_application_method,
    normalize_job_opportunity_row,
)
from .impressum_extractor import ImpressumExtractor

logger = logging.getLogger(__name__)

# Common regex patterns for German contact information
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
PHONE_REGEX = re.compile(
    r"(?:\+49|0049|0)\s*(?:\(0\)\s*)?[1-9][0-9\s/().\-]{5,22}[0-9]"
)
POSTAL_CODE_CITY_REGEX = re.compile(
    r"\b(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+(?:[\s\-][A-ZÄÖÜ][a-zäöüß]+)*)\b"
)

# Known ATS provider signatures for classification
EXTENDED_ATS_SIGNATURES: Dict[str, str] = {
    "persis": "ats_persis",
    "personio": "ats_personio",
    "workday": "ats_workday",
    "myworkdayjobs": "ats_workday",
    "softgarden": "ats_softgarden",
    "recruitee": "ats_recruitee",
    "greenhouse": "ats_greenhouse",
    "lever": "ats_lever",
    "d.vinci": "ats_dvinci",
    "d-vinci": "ats_dvinci",
    "covider": "ats_covider",
    "rexx": "ats_rexx",
    "rexx-systems": "ats_rexx",
    "smartrecruiters": "ats_smartrecruiters",
    "successfactors": "ats_successfactors",
    "talention": "ats_talention",
    "join.com": "ats_join",
    "stepstone": "external_listing",
    "indeed": "external_listing",
    "arbeitsagentur": "portal",
}

# Exclusion patterns for false-positive emails
PORTAL_EXCLUDED_EMAILS = {
    "jobboerse@arbeitsagentur.de",
    "noreply@arbeitsagentur.de",
    "service@arbeitsagentur.de",
    "datenschutz@arbeitsagentur.de",
    "impressum@arbeitsagentur.de",
}

_EMPLOYER_EMAIL_CACHE_LOCK = threading.RLock()
_EMPLOYER_EMAIL_CACHE: Dict[str, Dict[str, Any]] = {}
_EMPLOYER_EMAIL_INFLIGHT: Dict[str, threading.Event] = {}

_GENERIC_BRAND_TOKENS = {
    "hotel", "autohaus", "bäckerei", "baeckerei", "apotheke", "klinik",
    "stadt", "gemeinde", "deutsche", "nord", "süd", "sued", "west", "ost",
    "mode", "haus", "laden", "shop", "service", "center", "group", "gruppe",
    "marken", "discount", "supermarkt", "handel", "gastronomie", "restaurant",
}

_RECRUITMENT_EMAIL_PREFIXES = (
    "bewerbung", "ausbildung", "karriere", "personal", "recruiting", "jobs", "hr", "talent",
)

_BRAND_DOMAIN_HINTS = {
    "netto marken-discount": "https://www.netto-online.de",
    "metro cash": "https://www.metro.de",
    "kaufland": "https://www.kaufland.de",
    "penny": "https://www.penny.de",
    "rewe": "https://www.rewe.de",
    "lidl": "https://www.lidl.de",
    "edeka": "https://www.edeka.de",
    "dm-drogerie": "https://www.dm.de",
    "rossmann": "https://www.rossmann.de",
    "aldi süd": "https://www.aldi-sued.de",
    "aldi sued": "https://www.aldi-sued.de",
    "aldi nord": "https://www.aldi-nord.de",
    "hornbach": "https://www.hornbach.de",
    "deichmann": "https://www.deichmann.com",
    "norma": "https://www.norma-online.de",
    "primark": "https://www.primark.com",
    "modepark": "https://www.modepark.de",
    "röther": "https://www.modepark.de",
    "roether": "https://www.modepark.de",
    "media-saturn": "https://www.mediamarktsaturn.com",
    "mediamarkt": "https://www.mediamarktsaturn.com",
}

_DDG_SKIP_DOMAINS = (
    "northdata", "kununu", "xing", "linkedin", "facebook", "instagram",
    "youtube", "wikipedia", "gelbeseiten", "11880", "dasoertliche", "yelp",
    "wer-zu-wem", "implisense", "unternehmensregister", "companyhouse",
    "firmenwissen", "cylex", "golocal", "meinestadt", "dastelefonbuch",
    "wlw.de", "creditsafe", "dnb.com", "bloomberg", "reuters", "duckduckgo.com",
)


def _transliterate_german(text: str) -> str:
    return (
        str(text or "")
        .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    )


def _generate_employer_website_candidates(
    company: str,
    existing_website: str = "",
    direct_url: str = "",
) -> List[str]:
    """Generate prioritized candidate employer homepage URLs (max 5)."""
    from services.employer_cache import (
        extract_registrable_domain,
        is_non_employer_domain,
        is_portal_domain,
        is_shared_ats_domain,
        is_shortener_domain,
        is_valid_company_name,
    )

    candidates: List[str] = []
    seen_roots: Set[str] = set()

    def _add_candidate(u: str) -> None:
        raw = str(u or "").strip()
        if not raw.startswith(("http://", "https://")):
            return
        if is_non_employer_domain(raw) or is_portal_domain(raw) or is_shortener_domain(raw) or is_shared_ats_domain(raw):
            return
        p = urlparse(raw)
        if not p.netloc:
            return
        root = f"{p.scheme}://{p.netloc}".lower()
        if root not in seen_roots:
            seen_roots.add(root)
            candidates.append(root)

    if existing_website:
        _add_candidate(existing_website)

    if direct_url:
        _add_candidate(direct_url)
        reg_dom = extract_registrable_domain(direct_url)
        if reg_dom and not is_non_employer_domain(reg_dom):
            _add_candidate(f"https://www.{reg_dom}")
            _add_candidate(f"https://unternehmen.{reg_dom}")

    comp_low = str(company or "").strip().lower()
    for brand_key, brand_url in _BRAND_DOMAIN_HINTS.items():
        if brand_key in comp_low:
            _add_candidate(brand_url)
            break

    if is_valid_company_name(company):
        comp_ascii = _transliterate_german(company).lower()
        comp_clean = re.sub(
            r"\b(gmbh|ag|kg|co|mbh|se|ohg|gbr|stiftung|e\.?\s*v\.?|kgaa|holding|"
            r"verwaltungsges(?:ellschaft)?|beteiligungs(?:ges(?:ellschaft)?)?|"
            r"produktions|handels|und|non-food|textilien|getraenkemaerkte|getraenkemarkt|"
            r"markt|filiale|deutschland)\b",
            " ",
            comp_ascii,
            flags=re.IGNORECASE,
        )
        tokens = [re.sub(r"[^a-z0-9]", "", t) for t in re.split(r"[\s/,&+!\"'()]+", comp_clean)]
        tokens = [t for t in tokens if len(t) >= 2]
        if tokens:
            full_slug = "".join(tokens)
            if len(full_slug) >= 4:
                _add_candidate(f"https://www.{full_slug}.de")
            if len(tokens) >= 2 and len(tokens[0]) >= 2 and len(tokens[1]) >= 2:
                _add_candidate(f"https://www.{tokens[0]}-{tokens[1]}.de")
            first_tok = tokens[0]
            if len(first_tok) >= 3 and first_tok not in _GENERIC_BRAND_TOKENS:
                _add_candidate(f"https://www.{first_tok}.de")
                _add_candidate(f"https://unternehmen.{first_tok}.de")
                _add_candidate(f"https://karriere.{first_tok}.de")

    return candidates[:5]


def _classify_email_type(email: str, source_hint: str = "") -> str:
    local = str(email or "").strip().lower().split("@")[0]
    if "widerruf" not in local and any(p in local for p in _RECRUITMENT_EMAIL_PREFIXES):
        return "recruitment"
    if source_hint == "impressum" or any(g in local for g in ("info", "kontakt", "zentrale", "office", "service", "mail")):
        return "impressum"
    return "general"


def detect_ats_or_url_type(url: str) -> Tuple[str, bool]:
    """
    Classifies a destination URL into its type and indicates if it represents a direct form.
    Returns (url_type, has_form).
    """
    if not url:
        return "none", False

    u_lower = url.lower().strip()
    if u_lower.startswith("mailto:") or "mailto:" in u_lower:
        return "email", False

    for signature, ats_type in EXTENDED_ATS_SIGNATURES.items():
        if signature in u_lower:
            is_form = ats_type.startswith("ats_")
            return ats_type, is_form

    from services.data_validator import is_advice_or_generic_page, GENERIC_PORTAL_ROOTS
    parsed = urlparse(u_lower)
    netloc = parsed.netloc
    path = parsed.path.strip("/")

    # Generic job board roots or homepages are NOT application forms
    if netloc in GENERIC_PORTAL_ROOTS or not path:
        if any(ind in u_lower for ind in ["karriere", "career", "jobs", "stellen"]):
            return "career_portal", False
        return "external_link", False

    if is_advice_or_generic_page(u_lower):
        return "advice_page", False

    # Check for verified form indicators in path/query (explicit application form endpoints)
    form_indicators = ["/bewerb", "/apply", "formular", "online-bewerb", "application/form"]
    if any(ind in u_lower for ind in form_indicators):
        return "direct_form", True

    if any(ind in u_lower for ind in ["karriere", "career", "jobs", "stellen"]):
        return "career_portal", False

    return "external_link", False


def normalize_phone_number(raw_phone: Optional[str]) -> str:
    """Standardizes German phone numbers to +49 format when clean; returns empty string if invalid."""
    if not raw_phone:
        return ""
    from services.data_validator import validate_phone_number
    ok, cleaned, _ = validate_phone_number(raw_phone)
    return cleaned if ok else ""


class ArbeitsagenturDetailExtractor:
    """
    Specialized extractor for Arbeitsagentur listings and German vocational vacancies.
    Resolves official application details across API, SSR, static HTML, browser DOM,
    and employer website discovery.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        if "User-Agent" not in self.session.headers:
            self.session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "de,de-DE;q=0.9,en;q=0.8",
                }
            )
        self.form_discovery = ApplicationFormDiscovery(session=self.session)
        self.impressum_extractor = ImpressumExtractor(session=self.session)

    def resolve_partner_redirect(self, partner_url: str, timeout: float = 5.0) -> Tuple[str, str, bool]:
        """
        Resolves outbound partner redirects with a strict bounded timeout.
        Returns (terminal_url, state, is_manual_required).
        state: 'resolved' | 'unresolved' | 'blocked'
        """
        clean_url = str(partner_url or "").strip()
        if not clean_url or not clean_url.startswith("http"):
            return clean_url, "unresolved", False

        try:
            # Fast HEAD request first to catch HTTP 301/302 redirects
            resp = self.session.head(clean_url, timeout=timeout, allow_redirects=True)
            term_url = resp.url
            domain = urlparse(term_url).netloc.lower()
            if "arbeitsagentur.de" not in domain:
                return term_url, "resolved", False

            # If still on arbeitsagentur, follow GET with stream to avoid downloading full body
            with self.session.get(clean_url, timeout=timeout, allow_redirects=True, stream=True) as get_resp:
                term_url = get_resp.url
                domain = urlparse(term_url).netloc.lower()
                if "arbeitsagentur.de" not in domain:
                    return term_url, "resolved", False

                if get_resp.status_code in (403, 429):
                    return clean_url, "blocked", True
        except Exception as e:
            logger.debug("Partner redirect resolution timeout/error for %s: %s", clean_url, e)
            is_timeout = "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower()
            return clean_url, "unresolved" if is_timeout else "blocked", True

        return clean_url, "unresolved", False

    # -------------------------------------------------------------------------
    # Stage 1: Official API / SSR Embedded JSON
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_external_url(raw_url: Any) -> str:
        """Ensures URLs like 'www.wm.de' or 'www.bg-kliniken.de/...' have an https:// scheme."""
        val = str(raw_url or "").strip()
        if not val or val.lower() in ("null", "none", "nan"):
            return ""
        if val.startswith(("http://", "https://", "mailto:", "tel:")):
            return val
        if val.startswith("//"):
            return "https:" + val
        if re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/.*)?$", val):
            return "https://" + val
        return ""

    def extract_from_ssr_script(self, html: str) -> Dict[str, Any]:
        """Extracts pre-rendered jobdetail JSON data embedded by Angular SSR."""
        data: Dict[str, Any] = {}
        if not html or "jobdetail" not in html:
            return data

        soup = BeautifulSoup(html, "html.parser")
        for s in soup.find_all("script"):
            content = s.string or ""
            s_id = str(s.get("id") or "")
            if "jobdetail" in content and ("from-ssr" in content or "from-ssr" in s_id or "serverApp-state" in s_id):
                try:
                    parsed = json.loads(content)
                    jd = parsed.get("jobdetail", {})
                    ag_darst = parsed.get("arbeitgeberdarstellung", {})
                    if isinstance(jd, dict):
                        data["ssr_jobdetail"] = jd
                        data["firma"] = jd.get("firma") or (ag_darst.get("firma") if isinstance(ag_darst, dict) else None)
                        data["titel"] = jd.get("stellenangebotsTitel") or jd.get("titel")
                        data["hauptberuf"] = jd.get("hauptberuf") or jd.get("beruf")
                        data["externeURL"] = self._normalize_external_url(
                            jd.get("externeURL") or jd.get("externeUrl")
                        )
                        data["allianzpartnerUrl"] = self._normalize_external_url(
                            jd.get("allianzpartnerUrl")
                        )
                        data["allianzpartnerName"] = jd.get("allianzpartnerName")
                        data["referenznummer"] = jd.get("referenznummer")
                        data["arbeitsorte"] = jd.get("stellenlokationen", [])
                        data["description"] = jd.get("stellenangebotsBeschreibung")
                        ag_links: List[Dict[str, str]] = []
                        if isinstance(ag_darst, dict) and isinstance(ag_darst.get("links"), list):
                            for lnk in ag_darst["links"]:
                                if isinstance(lnk, dict) and lnk.get("url"):
                                    norm_l = self._normalize_external_url(lnk.get("url"))
                                    if norm_l:
                                        ag_links.append({"url": norm_l, "art": str(lnk.get("art") or "")})
                        data["ag_links"] = ag_links
                        break
                except Exception as exc:
                    logger.debug("Failed to parse SSR jobdetail JSON: %s", exc)

        return data

    # -------------------------------------------------------------------------
    # Stage 2: HTML Extraction ("Informationen zur Bewerbung" & Copytext)
    # -------------------------------------------------------------------------

    def parse_application_section(self, html: str, source_url: str = "") -> Dict[str, Any]:
        """
        Parses the official 'Informationen zur Bewerbung' section and full copytext.
        Extracts email, phone, contact person, postal address, accepted methods,
        required documents, and employer URLs.
        """
        result: Dict[str, Any] = {
            "email": "",
            "email_type": "",
            "phone": "",
            "contact_person": "",
            "postal_address": "",
            "employer_website": "",
            "direct_application_url": "",
            "application_url_type": "none",
            "has_form": False,
            "application_methods": [],
            "required_documents": "",
            "extraction_status": "partial",
            "logs": [],
            "manual_review_required": False,
            "manual_review_reason": "",
        }

        if not html:
            result["extraction_status"] = "no_content"
            return result

        soup = BeautifulSoup(html, "html.parser")

        # 1. Locate the application section and copytext
        kontaktdaten_block = (
            soup.find(id="jobdetails-kontaktdaten-block")
            or soup.find(id="jobdetails-kontaktdaten-container")
            or soup.find(lambda el: el.name in ["section", "div"] and "Informationen zur Bewerbung" in el.get_text())
        )
        copytext_block = soup.find("div", class_="ba-copytext")

        # Combine text regions with priority given to kontaktdaten & copytext
        contact_text = kontaktdaten_block.get_text("\n", strip=True) if kontaktdaten_block else ""
        copy_text = copytext_block.get_text("\n", strip=True) if copytext_block else ""
        full_text = soup.get_text("\n", strip=True)

        combined_focused_text = f"{contact_text}\n{copy_text}"

        # 2. Extract Email & Email Type
        # Priority: mailto links inside contact or copytext
        emails: List[str] = []
        target_blocks = [b for b in [kontaktdaten_block, copytext_block] if b is not None]
        for blk in target_blocks:
            for mailto in blk.find_all("a", href=lambda h: h and h.startswith("mailto:")):
                raw_addr = mailto.get("href", "").replace("mailto:", "").split("?")[0].strip().lower()
                if raw_addr and "@" in raw_addr and raw_addr not in PORTAL_EXCLUDED_EMAILS:
                    emails.append(raw_addr)

        if not emails:
            # Fallback to regex across focused text
            found = EMAIL_REGEX.findall(combined_focused_text)
            emails = [e.lower() for e in found if e.lower() not in PORTAL_EXCLUDED_EMAILS]

        if emails:
            result["email"] = emails[0]
            result["email_type"] = "recruitment"
            result["logs"].append(f"Email extracted: {result['email']} (recruitment)")

        # 3. Extract Phone Number
        phone_match = None
        for blk in target_blocks:
            for tel in blk.find_all("a", href=lambda h: h and h.startswith("tel:")):
                phone_match = tel.get("href", "").replace("tel:", "").strip()
                if phone_match:
                    break
            if phone_match:
                break

        if not phone_match:
            # Search telephone cues: "Tel.:", "Telefon:", "Fon:"
            tel_cue = re.search(r"(?:tel(?:efon)?\.?|fon)\s*[:\-\s]\s*([+0-9\s/().\-]{6,25})", combined_focused_text, re.IGNORECASE)
            if tel_cue:
                phone_match = tel_cue.group(1).strip()
            else:
                phones = PHONE_REGEX.findall(combined_focused_text)
                if phones:
                    phone_match = phones[0]

        if phone_match:
            result["phone"] = normalize_phone_number(phone_match)
            result["logs"].append(f"Phone extracted: {result['phone']}")

        # 4. Extract Contact Person (require explicit colon after Ansprechpartner/Kontaktperson to avoid prose matches)
        contact_person = ""
        cp_match = re.search(
            r"(?:ansprechpartner(?:in)?|kontaktperson)\s*:\s*([^\n\r<]{3,70})",
            combined_focused_text,
            re.IGNORECASE,
        )
        if cp_match:
            contact_person = cp_match.group(1).strip()
        else:
            # Search for Herr / Frau salutation patterns
            salut_match = re.search(r"\b((?:Herr|Frau|Dr\.|Prof\.)\s+[A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)\b", combined_focused_text)
            if salut_match:
                contact_person = salut_match.group(1).strip()

        from services.data_validator import (
            GENERIC_PORTAL_ROOTS,
            sanitize_contact_person,
            validate_form_link,
            validate_application_url,
            validate_job_listing_url,
            validate_phone_number,
        )
        is_cp_valid, cleaned_cp, _ = sanitize_contact_person(contact_person)
        result["contact_person"] = cleaned_cp if is_cp_valid else ""
        if result["contact_person"]:
            result["logs"].append(f"Contact person detected: {result['contact_person']}")

        # 5. Extract Postal Address
        postal_match = POSTAL_CODE_CITY_REGEX.search(combined_focused_text)
        if postal_match:
            # Look backwards for street
            result["postal_address"] = postal_match.group(0).strip()

        # 6. Extract Required Application Documents
        docs: List[str] = []
        if re.search(r"\blebenslauf\b", combined_focused_text, re.IGNORECASE):
            docs.append("Lebenslauf")
        if re.search(r"\banschreiben\b|\bbewerbungsanschreiben\b", combined_focused_text, re.IGNORECASE):
            docs.append("Anschreiben")
        if re.search(r"\bzeugnisse?\b|\babschlusszeugnis\b|\bnotenspiegel\b", combined_focused_text, re.IGNORECASE):
            docs.append("Zeugnisse")

        # Explicit Geforderte Anlagen line
        anlagen_match = re.search(r"(?:geforderte\s+anlagen|anlagen)\s*[:\-\s]\s*([^\n\r<]{3,120})", combined_focused_text, re.IGNORECASE)
        if anlagen_match:
            result["required_documents"] = anlagen_match.group(1).strip()
        elif docs:
            result["required_documents"] = ", ".join(docs)

        if result["required_documents"]:
            result["logs"].append(f"Required documents detected: {result['required_documents']}")

        # 7. Extract Application Links & Employer URLs
        candidate_links: List[str] = []

        # Also check explicit external job buttons on Arbeitsagentur detail page ("Externe Seite öffnen")
        for ext_btn_id in ("detail-beschreibung-externe-url-btn", "detail-footer-externe-url-btn", "detail-kopfbereich-externe-url-btn"):
            ext_btn = soup.find(id=ext_btn_id)
            if ext_btn and ext_btn.get("href"):
                norm_ext = self._normalize_external_url(ext_btn.get("href"))
                if norm_ext and "arbeitsagentur.de" not in norm_ext.lower():
                    candidate_links.append(norm_ext)

        # Find external anchor links in application & copytext sections
        for blk in target_blocks:
            for a in blk.find_all("a", href=True):
                href = a.get("href", "").strip()
                if not href or href.startswith("tel:") or href.startswith("javascript:"):
                    continue
                # If mailto: link, extract email if not already present
                if href.startswith("mailto:") or "mailto:" in href:
                    m = re.search(r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", href, re.I)
                    if m and not result["email"]:
                        extracted_mail = m.group(1).lower()
                        if extracted_mail not in PORTAL_EXCLUDED_EMAILS:
                            result["email"] = extracted_mail
                            result["email_type"] = "recruitment"
                            result["logs"].append(f"Email extracted from mailto link: {extracted_mail}")
                    continue
                abs_url = urljoin(source_url, href) if href.startswith("/") else self._normalize_external_url(href)
                if not abs_url:
                    continue
                # Filter out Arbeitsagentur internal navigation and social shares
                domain = urlparse(abs_url).netloc.lower()
                if "arbeitsagentur.de" in domain:
                    continue
                candidate_links.append(abs_url)

        # Check SSR externeURL and allianzpartnerUrl or partner redirects
        ssr_data = self.extract_from_ssr_script(html)
        ssr_externe = ssr_data.get("externeURL")
        ssr_allianz = ssr_data.get("allianzpartnerUrl")
        ssr_ag_links = ssr_data.get("ag_links") or []
        if ssr_data.get("titel"):
            result["ssr_title"] = ssr_data["titel"]
        if ssr_data.get("hauptberuf"):
            result["ssr_hauptberuf"] = ssr_data["hauptberuf"]
        if ssr_data.get("description"):
            result["ssr_description"] = ssr_data["description"]
        if ssr_data.get("firma"):
            result["ssr_firma"] = ssr_data["firma"]

        # Add employer Karriereseite / Homepage links from arbeitgeberdarstellung
        for ag_lnk in ssr_ag_links:
            ag_u = ag_lnk.get("url", "")
            if ag_u and "arbeitsagentur.de" not in ag_u.lower():
                if ag_lnk.get("art") == "Karriereseite":
                    candidate_links.insert(0, ag_u)
                else:
                    candidate_links.append(ag_u)

        if ssr_allianz:
            if "arbeitsagentur.de" not in ssr_allianz:
                p_allianz = urlparse(ssr_allianz.lower())
                # Do not add bare generic portal root homepages (e.g. https://jobs.hogapage.de)
                if not (p_allianz.netloc in GENERIC_PORTAL_ROOTS and not p_allianz.path.strip("/")):
                    candidate_links.insert(0, ssr_allianz)
            else:
                # Safely resolve bounded partner redirect
                resolved_url, res_state, needs_manual = self.resolve_partner_redirect(ssr_allianz, timeout=5.0)
                if res_state == "resolved":
                    candidate_links.insert(0, resolved_url)
                    result["logs"].append(f"Resolved partner redirect to: {resolved_url}")
                elif needs_manual:
                    result["manual_review_required"] = True
                    result["manual_review_reason"] = "Partner portal requires human verification"
                    result["extraction_status"] = "manual_required"
                    result["direct_application_url"] = ssr_allianz
                    result["application_url_type"] = "partner_portal"
                    result["logs"].append(f"Partner portal redirect unresolved/blocked: {ssr_allianz}")

        # Prioritize specific externeURL ahead of generic allianzpartnerUrl
        if ssr_externe and "arbeitsagentur.de" not in ssr_externe.lower():
            candidate_links.insert(0, ssr_externe)
            result["externe_url"] = ssr_externe

        # Filter out bare generic portal homepages from candidate_links
        filtered_candidates: List[str] = []
        for url in candidate_links:
            if url.startswith("mailto:") or "mailto:" in url:
                continue
            p_cand = urlparse(url.lower())
            if p_cand.netloc in GENERIC_PORTAL_ROOTS and not p_cand.path.strip("/"):
                continue
            if url not in filtered_candidates:
                filtered_candidates.append(url)
        candidate_links = filtered_candidates

        # Classify candidate links using evidence-based ApplicationDestinationType
        from services.application_url_validator import (
            ApplicationDestinationType,
            classify_and_validate_destination,
        )
        from services.employer_cache import is_non_employer_domain

        for url in candidate_links:
            cls_res = classify_and_validate_destination(
                url,
                company=str(ssr_data.get("firma") or ""),
                job_title=str(ssr_data.get("titel") or ssr_data.get("hauptberuf") or ""),
                job_listing_url=source_url,
            )
            url_type = cls_res["application_url_type"]
            is_verified_dest = cls_res["application_url_verified"]
            ats_subtype, ats_is_form = detect_ats_or_url_type(url)

            if is_verified_dest and not result["direct_application_url"]:
                result["direct_application_url"] = url
                result["application_url_type"] = ats_subtype if ats_subtype.startswith("ats_") else url_type
                result["has_form"] = bool(ats_is_form or url_type == ApplicationDestinationType.DIRECT_APPLICATION_FORM.value)
                result["logs"].append(f"Verified application destination found: {url} ({result['application_url_type']})")
            elif not result["employer_website"] and not is_non_employer_domain(url):
                result["employer_website"] = url
                if result["application_url_type"] == "none":
                    result["application_url_type"] = url_type
                result["logs"].append(f"Employer website/career root preserved: {url} ({url_type})")

        # 8. Identify Accepted Application Methods
        methods: List[str] = []
        text_lower = combined_focused_text.lower()

        # Check for web portal application cues
        if (
            result["has_form"]
            or result["direct_application_url"]
            or "über internetseite des arbeitgebers" in text_lower
            or "bewerbungsportal" in text_lower
            or "online-bewerbung" in text_lower
            or "online bewerben" in text_lower
            or "jetzt bewerben" in text_lower
        ):
            if result["has_form"]:
                methods.append("form")
            else:
                methods.append("external_link")

        # Check for email application cues
        if result["email"] or "per e-mail" in text_lower or "e-mail-bewerbung" in text_lower:
            methods.append("email")

        # Check for postal application cues
        if "per post" in text_lower or "postalisch" in text_lower or "schriftlich" in text_lower:
            methods.append("postal")

        # Check for phone application cues
        if "telefonisch" in text_lower or (result["phone"] and "bewerbung" in text_lower and "telefon" in text_lower):
            methods.append("phone")

        # Deduplicate while preserving order
        unique_methods = []
        for m in methods:
            if m not in unique_methods:
                unique_methods.append(m)

        result["application_methods"] = unique_methods

        # Calculate primary application_method
        has_email = bool(result["email"] and "@" in result["email"])
        has_verified_form = bool(result["has_form"])
        has_ext_link = bool(result["direct_application_url"] or "external_link" in unique_methods)

        if has_email and (has_verified_form or has_ext_link):
            result["application_method"] = "both"
        elif has_email:
            result["application_method"] = "email"
        elif has_verified_form:
            result["application_method"] = "form"
        elif has_ext_link:
            result["application_method"] = "external_link"
        elif "phone" in unique_methods:
            result["application_method"] = "phone"
        elif "postal" in unique_methods:
            result["application_method"] = "postal"
        else:
            result["application_method"] = "unknown"

        # Update extraction status
        if result.get("manual_review_required"):
            result["extraction_status"] = "manual_required"
        elif has_email or has_verified_form or has_ext_link:
            result["extraction_status"] = "completed"
        elif result["phone"] or contact_person:
            result["extraction_status"] = "partial"
        else:
            result["extraction_status"] = "no_contact_found"

        return result

    # -------------------------------------------------------------------------
    # Stage 3: Selenium Browser Fallback
    # -------------------------------------------------------------------------

    def extract_with_selenium(
        self,
        driver,
        job_url: str,
        solver=None,
        manual_captcha_handler=None,
    ) -> Dict[str, Any]:
        """
        Reuses an existing Selenium WebDriver session to handle dynamic JavaScript rendering
        and solve in-page contact captchas without starting a new browser process.
        """
        result: Dict[str, Any] = {
            "email": "",
            "phone": "",
            "contact_person": "",
            "employer_website": "",
            "direct_application_url": "",
            "has_form": False,
            "application_methods": [],
            "required_documents": "",
            "extraction_status": "partial",
            "logs": [],
        }

        if driver is None or not job_url:
            return result

        try:
            current_url = getattr(driver, "current_url", "")
            if not current_url or job_url not in current_url:
                driver.get(job_url)
                t_wait = time.time()
                while time.time() - t_wait < 1.2:
                    try:
                        ps = getattr(driver, "page_source", "") or ""
                        if not isinstance(ps, str) or any(
                            marker in ps
                            for marker in (
                                "jobdetails-kontaktdaten-block",
                                "detail-bewerbung",
                                "kontaktdaten-captcha-image",
                                "Informationen zur Bewerbung",
                            )
                        ):
                            break
                    except Exception:
                        break
                    time.sleep(0.15)

            # Dismiss cookies
            try:
                from .cookie_handler import accept_cookies
                accept_cookies(driver, wait_after_click=0.5)
            except Exception:
                pass

            # Check for in-page captcha
            from selenium.webdriver.common.by import By
            captcha_imgs = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-image'] | //img[contains(@src, 'captcha')]")
            captcha_inputs = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-input'] | //input[contains(@name, 'captcha')]")
            submit_btns = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-absenden-button'] | //button[@type='submit']")

            if captcha_imgs and captcha_inputs and solver:
                result["logs"].append("In-page captcha encountered in contact section")
                from services.captcha_monitor import get_captcha_tracker, generate_challenge_fingerprint
                job_id = getattr(solver, "job_id", "")
                worker_id = getattr(solver, "worker_id", 1)
                tracker = get_captcha_tracker(job_id)
                ch_fp = generate_challenge_fingerprint("arbeitsagentur.de", "kontaktdaten-inpage-captcha")
                corr_id = tracker.record_challenge_detected(
                    domain="arbeitsagentur.de",
                    worker_id=worker_id,
                    challenge_fingerprint=ch_fp,
                    details="In-page contact captcha encountered on Arbeitsagentur",
                )

                manual_handoff_recorded = [False]

                def route_to_live_manual_review(reason: str) -> bool:
                    """Keep this browser session alive while the dashboard handles the challenge."""
                    if not callable(manual_captcha_handler):
                        return False
                    try:
                        current_images = driver.find_elements(
                            By.XPATH,
                            "//*[@id='kontaktdaten-captcha-image'] | //img[contains(@src, 'captcha')]",
                        )
                        image_element = current_images[0] if current_images else captcha_imgs[0]
                        result["logs"].append(f"Routing in-page CAPTCHA to live manual review: {reason}")
                        resolved = bool(manual_captcha_handler(
                            domain="arbeitsagentur.de",
                            corr_id=corr_id,
                            challenge_type="image_text",
                            captcha_img_element=image_element,
                            job_url=job_url,
                        ))
                        if not resolved:
                            # The shared handler records the dismissed/expired/failed outcome.
                            manual_handoff_recorded[0] = True
                        return resolved
                    except Exception as manual_err:
                        logger.error("Live manual CAPTCHA handoff failed: %s", manual_err)
                        result["logs"].append(f"Live manual CAPTCHA handoff failed: {manual_err}")
                        return False

                def mark_manual_required(reason: str) -> None:
                    if not manual_handoff_recorded[0]:
                        tracker.record_manual_verification_required(
                            correlation_id=corr_id,
                            worker_id=worker_id,
                            domain="arbeitsagentur.de",
                            reason=reason,
                        )
                    result["manual_review_required"] = True
                    result["manual_review_reason"] = reason
                    result["extraction_status"] = "manual_required"

                try:
                    img_src = captcha_imgs[0].get_attribute("src") or ""
                    captcha_text = None
                    if img_src.startswith("http"):
                        img_res = self.session.get(img_src, timeout=10)
                        if img_res.status_code == 200:
                            solver_ctx = {
                                "job_id": job_id,
                                "worker_id": worker_id,
                                "domain": "arbeitsagentur.de",
                                "correlation_id": corr_id,
                            }
                            captcha_text = solver.solve_captcha(img_res.content, context=solver_ctx)

                    if captcha_text:
                        captcha_inputs[0].clear()
                        captcha_inputs[0].send_keys(captcha_text)
                        if submit_btns:
                            submit_btns[0].click()
                        time.sleep(2.0)
                        # Confirm whether target website accepted the solution
                        still_present = driver.find_elements(By.XPATH, "//*[@id='kontaktdaten-captcha-image'] | //img[contains(@src, 'captcha')]")
                        if not still_present:
                            tracker.record_website_verification(
                                correlation_id=corr_id,
                                worker_id=worker_id,
                                domain="arbeitsagentur.de",
                                details="Target website accepted in-page verification",
                            )
                            result["logs"].append("Target website confirmed in-page captcha verification")
                        else:
                            reason = "Target website still presents captcha after submit"
                            if route_to_live_manual_review(reason):
                                result["logs"].append("Manual CAPTCHA verification completed in the live worker session")
                            else:
                                mark_manual_required(reason)
                                result["logs"].append("Target website did NOT accept captcha (manual verification required)")
                    else:
                        reason = "No solution text returned by recognition service"
                        if route_to_live_manual_review(reason):
                            result["logs"].append("Manual CAPTCHA verification completed in the live worker session")
                        else:
                            mark_manual_required(reason)
                except Exception as c_err:
                    logger.debug("Captcha solving error: %s", c_err)
                    reason = f"Captcha submission failed: {c_err}"
                    result["logs"].append(f"Captcha handling failed: {c_err}")
                    if route_to_live_manual_review(reason):
                        result["logs"].append("Manual CAPTCHA verification completed in the live worker session")
                    else:
                        mark_manual_required(reason)

            # Sync verified browser cookies back to requests.Session for subsequent fast HTTP calls
            try:
                if hasattr(driver, "get_cookies") and self.session is not None:
                    for c in driver.get_cookies() or []:
                        if isinstance(c, dict) and c.get("name") and c.get("value") is not None:
                            self.session.cookies.set(c["name"], c["value"], domain=c.get("domain") or "")
            except Exception:
                pass

            # Extract rendered DOM page source
            rendered_html = driver.page_source
            parsed = self.parse_application_section(rendered_html, source_url=job_url)
            parsed["extraction_method"] = "selenium"
            if result.get("manual_review_required"):
                parsed["manual_review_required"] = True
                parsed["manual_review_reason"] = result.get("manual_review_reason", "")
                parsed["extraction_status"] = "manual_required"
            return parsed

        except Exception as exc:
            logger.debug("Selenium fallback failed for %s: %s", job_url, exc)
            result["logs"].append(f"Selenium extraction error: {exc}")
            return result

    # -------------------------------------------------------------------------
    # Stage 4: Employer Website Discovery Fallback
    # -------------------------------------------------------------------------

    def discover_employer_website_fallback(
        self,
        company: str,
        location: str = "",
        existing_website: str = "",
        job_title: str = "",
        driver=None,
    ) -> Dict[str, Any]:
        """
        Discovers company career pages, contact details, and ATS forms
        when the official Arbeitsagentur listing does not contain direct contact details.
        """
        from services.employer_cache import is_non_employer_domain, is_valid_company_name
        from services.contamination_detector import is_email_compatible_with_employer
        from services.application_url_validator import follow_generic_employer_website

        norm_existing = self._normalize_external_url(existing_website)
        if norm_existing and is_non_employer_domain(norm_existing):
            norm_existing = ""

        result: Dict[str, Any] = {
            "email": "",
            "email_type": "",
            "phone": "",
            "employer_website": norm_existing,
            "direct_application_url": "",
            "has_form": False,
            "application_method": "unknown",
            "application_url_type": "none",
            "logs": ["Attempting employer website discovery fallback"],
        }

        target_website = norm_existing
        if not target_website and is_valid_company_name(company):
            # Clean company name
            clean_comp = re.sub(r"\b(gmbh|ag|kg|e\.v\.|ohg|gbr|co\.|mbh|se|stiftung)\b", "", company, flags=re.IGNORECASE).strip()
            # Try basic domain heuristic only when company name is reasonably specific
            domain_guess = re.sub(r"[^a-zA-Z0-9]", "", clean_comp).lower()
            if domain_guess and len(domain_guess) >= 4:
                cand_site = f"https://www.{domain_guess}.de"
                if not is_non_employer_domain(cand_site):
                    target_website = cand_site

        if not target_website or is_non_employer_domain(target_website):
            return result

        result["employer_website"] = target_website

        # 0. Follow generic employer website to locate job-specific application page or email (Part 1.5)
        try:
            crawl_res = follow_generic_employer_website(
                start_url=target_website,
                company=company,
                job_title=job_title,
                session=self.session,
                max_requests=4,
            )
            if crawl_res.get("discovered_email"):
                result["email"] = crawl_res["discovered_email"]
                result["email_type"] = "recruitment"
                result["logs"].append(f"Discovered recruitment email on employer career page: {result['email']}")
            if crawl_res.get("resolved_application_url"):
                result["direct_application_url"] = crawl_res["resolved_application_url"]
                result["application_url_type"] = crawl_res.get("resolved_url_type") or "job_specific_application_page"
                result["has_form"] = bool(crawl_res.get("resolved_has_form"))
                result["application_method"] = "form" if result["has_form"] else "external_link"
                result["logs"].append(f"Resolved job-specific application page on employer website: {result['direct_application_url']}")
            if crawl_res.get("manual_review_required") and not result.get("email") and not result.get("direct_application_url"):
                result["manual_review_required"] = True
                result["manual_review_reason"] = crawl_res.get("diagnostic_reason") or "Employer career portal requires manual verification"
        except Exception as crawl_err:
            logger.debug("Employer career crawl error for %s: %s", target_website, crawl_err)

        # 1. Discover application form via ApplicationFormDiscovery if not already resolved
        if not result["direct_application_url"]:
            dummy_job = {
                "company": company,
                "url": target_website,
                "apply_url": target_website,
            }
            discovery_res = self.form_discovery.discover_application_form(dummy_job, driver=driver)
            if discovery_res and discovery_res.has_form:
                result["has_form"] = True
                result["direct_application_url"] = discovery_res.form_link or discovery_res.bewerbung_link
                url_type, _ = detect_ats_or_url_type(result["direct_application_url"])
                result["application_url_type"] = url_type
                result["application_method"] = "form"
                result["logs"].append(f"Discovered external application form: {result['direct_application_url']}")

        # 2. Extract legal notice (Impressum) as non-recruitment contact fallback
        if not result["email"]:
            try:
                impressum_info = self.impressum_extractor.extract_from_website(target_website)
                if impressum_info:
                    if impressum_info.get("emails"):
                        for imp_email in impressum_info["emails"]:
                            ok_imp, _ = is_email_compatible_with_employer(imp_email, company, employer_website=target_website)
                            if ok_imp:
                                # Explicit rule: Do not classify Impressum email as recruitment email
                                result["email"] = imp_email.lower()
                                result["email_type"] = "impressum"
                                result["logs"].append(f"Impressum email extracted: {result['email']} (email_type=impressum)")
                                break
                    if not result["phone"] and impressum_info.get("phone"):
                        result["phone"] = normalize_phone_number(impressum_info["phone"])
                    elif not result["phone"] and impressum_info.get("telephones"):
                        result["phone"] = normalize_phone_number(impressum_info["telephones"][0])
                    if impressum_info.get("geschaeftsfuehrer"):
                        gf_val = impressum_info["geschaeftsfuehrer"]
                        result["contact_person"] = gf_val[0] if isinstance(gf_val, list) else str(gf_val)
            except Exception as imp_err:
                logger.debug("Impressum fallback failed: %s", imp_err)

        return result

    def discover_employer_email(
        self,
        company: str,
        location: str = "",
        existing_website: str = "",
        direct_url: str = "",
        job_title: str = "",
    ) -> Dict[str, Any]:
        """
        Cached, fast HTTP + Impressum/Kontakt email discovery for an employer.
        Probes candidate employer URLs (bounded 4.0s per request), decodes obfuscated emails,
        validates employer compatibility, and caches both positive and negative outcomes.
        """
        from services.employer_cache import (
            extract_registrable_domain,
            is_non_employer_domain,
            is_valid_company_name,
            normalize_company_identity,
        )
        from services.contamination_detector import is_email_compatible_with_employer
        from services.application_url_validator import extract_all_emails_including_obfuscated

        norm_comp = normalize_company_identity(company)
        dom_key = ""
        for u in (existing_website, direct_url):
            d = extract_registrable_domain(u)
            if d and not is_non_employer_domain(d):
                dom_key = d
                break

        cache_key = norm_comp or dom_key
        if not cache_key:
            return {"email": "", "email_type": "", "employer_website": "", "phone": "", "contact_person": ""}

        with _EMPLOYER_EMAIL_CACHE_LOCK:
            cached = _EMPLOYER_EMAIL_CACHE.get(cache_key)
            if cached is not None:
                return dict(cached)
            inflight_ev = _EMPLOYER_EMAIL_INFLIGHT.get(cache_key)
            if inflight_ev is None:
                inflight_ev = threading.Event()
                _EMPLOYER_EMAIL_INFLIGHT[cache_key] = inflight_ev
                is_leader = True
            else:
                is_leader = False

        if not is_leader:
            inflight_ev.wait(timeout=10.0)
            with _EMPLOYER_EMAIL_CACHE_LOCK:
                cached_after = _EMPLOYER_EMAIL_CACHE.get(cache_key)
                if cached_after is not None:
                    return dict(cached_after)

        res: Dict[str, Any] = {
            "email": "",
            "email_type": "",
            "employer_website": "",
            "phone": "",
            "contact_person": "",
        }

        try:
            if not is_valid_company_name(company) and not dom_key:
                return res

            norm_existing = self._normalize_external_url(existing_website)
            if norm_existing and is_non_employer_domain(norm_existing):
                norm_existing = ""
            norm_direct = self._normalize_external_url(direct_url)

            candidates = _generate_employer_website_candidates(
                company=company,
                existing_website=norm_existing,
                direct_url=norm_direct,
            )

            reachable_url = ""
            home_html = ""
            for cand_url in candidates:
                try:
                    resp = self.session.get(cand_url, timeout=4.0, allow_redirects=True)
                    status = getattr(resp, "status_code", None)
                    body = getattr(resp, "text", None)
                    final_u = getattr(resp, "url", None) or cand_url
                    if isinstance(status, int) and status == 200 and isinstance(body, str) and len(body) > 200:
                        if not is_non_employer_domain(final_u):
                            reachable_url = final_u
                            home_html = body
                            break
                except Exception:
                    continue

            # DuckDuckGo lightweight fallback if direct guesses didn't resolve
            if not reachable_url and is_valid_company_name(company):
                try:
                    q_str = f"{company} {location} Impressum".strip()
                    ddg_resp = self.session.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": q_str},
                        timeout=4.5,
                    )
                    ddg_status = getattr(ddg_resp, "status_code", None)
                    ddg_body = getattr(ddg_resp, "text", None)
                    if isinstance(ddg_status, int) and ddg_status == 200 and isinstance(ddg_body, str) and len(ddg_body) > 200:
                        ddg_soup = BeautifulSoup(ddg_body, "html.parser")
                        ddg_urls: List[str] = []
                        for a_tag in ddg_soup.find_all("a", class_=re.compile(r"result__a|result__url"), href=True):
                            raw_href = a_tag.get("href", "").strip()
                            if "uddg=" in raw_href:
                                parsed_q = urllib.parse.parse_qs(urlparse(raw_href).query)
                                if parsed_q.get("uddg"):
                                    raw_href = parsed_q["uddg"][0]
                            if not raw_href.startswith(("http://", "https://")):
                                continue
                            u_low = raw_href.lower()
                            if any(skip in u_low for skip in _DDG_SKIP_DOMAINS) or is_non_employer_domain(raw_href):
                                continue
                            if raw_href not in ddg_urls:
                                ddg_urls.append(raw_href)
                        for ddg_u in ddg_urls[:2]:
                            try:
                                r2 = self.session.get(ddg_u, timeout=4.0, allow_redirects=True)
                                st2 = getattr(r2, "status_code", None)
                                b2 = getattr(r2, "text", None)
                                fu2 = getattr(r2, "url", None) or ddg_u
                                if isinstance(st2, int) and st2 == 200 and isinstance(b2, str) and len(b2) > 200:
                                    if not is_non_employer_domain(fu2):
                                        reachable_url = fu2
                                        home_html = b2
                                        break
                            except Exception:
                                continue
                except Exception:
                    pass

            if reachable_url and home_html:
                res["employer_website"] = reachable_url
                site_dom = extract_registrable_domain(reachable_url)
                collected: List[Tuple[int, str, str]] = []

                try:
                    imp_info = self.impressum_extractor.extract_from_website(reachable_url, homepage_html=home_html)
                    if imp_info:
                        if imp_info.get("phone"):
                            res["phone"] = normalize_phone_number(imp_info["phone"])
                        if imp_info.get("geschaeftsfuehrer"):
                            from services.data_validator import sanitize_contact_person
                            gf = imp_info["geschaeftsfuehrer"]
                            raw_gf = str(gf[0] if isinstance(gf, list) else gf)
                            ok_cp, clean_cp, _ = sanitize_contact_person(raw_gf)
                            if ok_cp:
                                res["contact_person"] = clean_cp
                        for imp_e in imp_info.get("emails") or []:
                            ok_e, _ = is_email_compatible_with_employer(imp_e, company, employer_website=reachable_url)
                            if ok_e:
                                e_low = imp_e.lower().strip()
                                dom_match = 0 if (site_dom and e_low.endswith("@" + site_dom)) else 2
                                local_e = e_low.split("@")[0]
                                rec_tier = 0 if ("widerruf" not in local_e and any(p in local_e for p in _RECRUITMENT_EMAIL_PREFIXES)) else 1
                                collected.append((dom_match * 10 + rec_tier, e_low, "impressum"))
                except Exception as imp_err:
                    logger.debug("Employer impressum discovery failed for %s: %s", reachable_url, imp_err)

                try:
                    for h_e in extract_all_emails_including_obfuscated(home_html):
                        e_low = h_e.lower().strip()
                        if not self.impressum_extractor._is_usable_email(e_low):
                            continue
                        ok_e, _ = is_email_compatible_with_employer(e_low, company, employer_website=reachable_url)
                        if ok_e:
                            dom_match = 0 if (site_dom and e_low.endswith("@" + site_dom)) else 2
                            local_e = e_low.split("@")[0]
                            rec_tier = 0 if ("widerruf" not in local_e and any(p in local_e for p in _RECRUITMENT_EMAIL_PREFIXES)) else 1
                            collected.append((dom_match * 10 + rec_tier, e_low, "homepage"))
                except Exception:
                    pass

                if collected:
                    collected.sort(key=lambda t: t[0])
                    _, best_email, best_hint = collected[0]
                    res["email"] = best_email
                    res["email_type"] = _classify_email_type(best_email, source_hint=best_hint)

            with _EMPLOYER_EMAIL_CACHE_LOCK:
                if len(_EMPLOYER_EMAIL_CACHE) >= 2000:
                    _EMPLOYER_EMAIL_CACHE.clear()
                _EMPLOYER_EMAIL_CACHE[cache_key] = dict(res)

            return res
        finally:
            if is_leader:
                with _EMPLOYER_EMAIL_CACHE_LOCK:
                    ev = _EMPLOYER_EMAIL_INFLIGHT.pop(cache_key, None)
                    if ev is not None:
                        ev.set()

    # -------------------------------------------------------------------------
    # Main Orchestrator: Multi-Stage Extraction
    # -------------------------------------------------------------------------

    def extract_vacancy(
        self,
        job: Dict[str, Any],
        driver=None,
        captcha_solver=None,
        on_stage_change=None,
        manual_captcha_handler=None,
        driver_provider=None,
    ) -> Dict[str, Any]:
        """
        Executes the 4-stage smart extraction workflow for an Arbeitsagentur vacancy.
        Preserves all existing attributes and integrates discovered application methods.
        Never discards a vacancy solely for missing email.
        """
        if on_stage_change:
            on_stage_change("HTTP Fast-Path")
        enriched = dict(job or {})
        cand_apply = str(enriched.get("apply_url") or "").strip()
        cand_url = str(enriched.get("url") or "").strip()
        if "arbeitsagentur.de" in cand_url and "arbeitsagentur.de" not in cand_apply:
            source_url = cand_url
        else:
            source_url = cand_apply or cand_url
        reference = str(enriched.get("reference") or enriched.get("referenznummer") or "").strip()
        company = str(enriched.get("company") or enriched.get("firma") or "").strip()
        location = str(enriched.get("location") or enriched.get("city") or "").strip()

        logs: List[str] = []

        if not source_url and reference:
            source_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
            enriched["url"] = source_url

        parsed_details: Dict[str, Any] = {}

        # ---------------------------------------------------------------------
        # Stage 1 & 2: Fast HTTP Fetch & HTML / SSR Parsing
        # ---------------------------------------------------------------------
        if source_url and "arbeitsagentur.de" in source_url:
            try:
                t0 = time.time()
                from .rate_limiter import safe_http_get
                resp = safe_http_get(self.session, source_url, timeout=12)
                elapsed = time.time() - t0
                if resp is not None and resp.status_code == 200 and resp.text:
                    parsed_details = self.parse_application_section(resp.text, source_url=source_url)
                    logs.extend(parsed_details.get("logs", []))
                    logs.append(f"Stage 2 HTML parsed in {elapsed:.2f}s")
            except Exception as http_err:
                logger.debug("Fast HTTP fetch failed for %s: %s", source_url, http_err)
                logs.append(f"Stage 2 HTTP error: {http_err}")

        # Check if Stage 2 extracted sufficient application details
        has_email = bool(parsed_details.get("email") and "@" in parsed_details.get("email"))
        has_form = bool(parsed_details.get("has_form"))
        has_ext_link = bool(parsed_details.get("direct_application_url"))

        # Stage 2b: If Stage 2 found an external partner job URL (externeURL) but no email,
        # inspect the external partner listing via fast HTTP to extract direct email or ATS form
        ext_partner_url = str(parsed_details.get("externe_url") or parsed_details.get("direct_application_url") or "").strip()
        if not has_email and ext_partner_url.startswith("http") and "arbeitsagentur.de" not in ext_partner_url.lower():
            try:
                if "ausbildung.de/stellen/" in ext_partner_url.lower():
                    from .ausbildung_de_detail_extractor import AusbildungDeDetailExtractor
                    ausb_ext = AusbildungDeDetailExtractor(session=self.session)
                    sub_job = dict(enriched)
                    sub_job["url"] = ext_partner_url
                    ausb_res = ausb_ext.extract_vacancy(sub_job, driver=None, session=self.session)
                    if ausb_res.get("email"):
                        parsed_details["email"] = ausb_res["email"]
                        parsed_details["email_type"] = "recruitment"
                        has_email = True
                    if ausb_res.get("has_form") and ausb_res.get("form_link"):
                        parsed_details["direct_application_url"] = ausb_res["form_link"]
                        parsed_details["has_form"] = True
                        has_form = True
                    if not parsed_details.get("phone") and ausb_res.get("phone"):
                        parsed_details["phone"] = ausb_res["phone"]
                    if not parsed_details.get("contact_person") and ausb_res.get("contact_person"):
                        parsed_details["contact_person"] = ausb_res["contact_person"]
                else:
                    ext_resp = self.session.get(ext_partner_url, timeout=6, allow_redirects=True)
                    if ext_resp.status_code == 200 and ext_resp.text:
                        final_ext_url = ext_resp.url or ext_partner_url
                        ext_html = ext_resp.text
                        from services.contamination_detector import is_email_compatible_with_employer
                        from services.application_url_validator import extract_all_emails_including_obfuscated
                        # Check mailto, obfuscated, and text emails on external partner page
                        cand_partner_emails = extract_all_emails_including_obfuscated(ext_html)
                        valid_partner_emails: List[str] = []
                        for m_cand in cand_partner_emails:
                            m_clean = str(m_cand).strip().lower()
                            if m_clean and "@" in m_clean and m_clean not in PORTAL_EXCLUDED_EMAILS and self.impressum_extractor._is_usable_email(m_clean):
                                ok_e, _ = is_email_compatible_with_employer(m_clean, company, employer_website=final_ext_url)
                                if ok_e and m_clean not in valid_partner_emails:
                                    valid_partner_emails.append(m_clean)
                        if valid_partner_emails:
                            ranked_p = self.impressum_extractor._rank_emails(set(valid_partner_emails), source_url=final_ext_url)
                            parsed_details["email"] = ranked_p[0]
                            parsed_details["email_type"] = _classify_email_type(ranked_p[0])
                            has_email = True
                        # Check application links on external partner page
                        if not has_form:
                            ext_links = ApplicationFormDiscovery.extract_application_links_from_html(ext_html, final_ext_url)
                            for elink in ext_links:
                                u_type, is_f = detect_ats_or_url_type(elink)
                                if is_f or ApplicationFormDiscovery.is_known_ats_url(elink):
                                    parsed_details["direct_application_url"] = elink
                                    parsed_details["application_url_type"] = u_type
                                    parsed_details["has_form"] = True
                                    has_form = True
                                    break
            except Exception as ext_err:
                logger.debug("External partner page inspection skipped for %s: %s", ext_partner_url, ext_err)

        # ---------------------------------------------------------------------
        # Stage 3: Browser Fallback (Selenium)
        # ---------------------------------------------------------------------
        if not (has_email or has_form or has_ext_link) and driver is None and callable(driver_provider):
            try:
                driver = driver_provider()
            except Exception as drv_err:
                logger.debug("driver_provider error in Arbeitsagentur Stage 3: %s", drv_err)

        if not (has_email or has_form or has_ext_link) and driver is not None:
            if on_stage_change:
                on_stage_change("Selenium Fallback")
            logs.append("Stage 2 missing direct application channels, falling back to Stage 3 (Selenium)")
            sel_details = self.extract_with_selenium(
                driver,
                source_url,
                solver=captcha_solver,
                manual_captcha_handler=manual_captcha_handler,
            )
            logs.extend(sel_details.get("logs", []))

            # Merge Selenium results over Stage 2
            for key, val in sel_details.items():
                if val and not parsed_details.get(key):
                    parsed_details[key] = val

            has_email = bool(parsed_details.get("email") and "@" in parsed_details.get("email"))
            has_form = bool(parsed_details.get("has_form"))
            has_ext_link = bool(parsed_details.get("direct_application_url"))

            if parsed_details.get("manual_review_required"):
                if on_stage_change:
                    on_stage_change("Manual Review")
                enriched.update(parsed_details)
                enriched["extraction_status"] = "manual_required"
                enriched["manual_review_required"] = True
                enriched["manual_review_reason"] = parsed_details.get("manual_review_reason") or "Human verification required"
                enriched["extraction_logs"] = logs
                return enriched

        # ---------------------------------------------------------------------
        # Stage 4: Employer Website Discovery
        # ---------------------------------------------------------------------
        if not (has_email or has_form or has_ext_link):
            if on_stage_change:
                on_stage_change("Finding Application Form")
            logs.append("Stage 3 yielded no application channels, attempting Stage 4 (Employer Website Discovery)")
            discovery_details = self.discover_employer_website_fallback(
                company=company,
                location=location,
                existing_website=parsed_details.get("employer_website") or enriched.get("website") or "",
                job_title=str(enriched.get("title") or parsed_details.get("ssr_title") or parsed_details.get("ssr_hauptberuf") or ""),
                driver=driver,
            )
            logs.extend(discovery_details.get("logs", []))

            for key, val in discovery_details.items():
                if val and not parsed_details.get(key):
                    parsed_details[key] = val

        # ---------------------------------------------------------------------
        # Stage 4b: Cached Employer Email Enrichment (even when form/link exists)
        # ---------------------------------------------------------------------
        has_email_now = bool(parsed_details.get("email") and "@" in str(parsed_details.get("email") or ""))
        if not has_email_now and company:
            try:
                emp_email_res = self.discover_employer_email(
                    company=company,
                    location=location,
                    existing_website=parsed_details.get("employer_website") or enriched.get("website") or "",
                    direct_url=parsed_details.get("direct_application_url") or "",
                    job_title=str(enriched.get("title") or parsed_details.get("ssr_title") or ""),
                )
                if emp_email_res.get("email") and "@" in emp_email_res["email"]:
                    parsed_details["email"] = emp_email_res["email"]
                    parsed_details["email_type"] = emp_email_res.get("email_type") or "impressum"
                    logs.append(f"Stage 4b enriched employer email: {emp_email_res['email']} ({parsed_details['email_type']})")
                if emp_email_res.get("employer_website") and not parsed_details.get("employer_website"):
                    parsed_details["employer_website"] = emp_email_res["employer_website"]
                if emp_email_res.get("phone") and not parsed_details.get("phone"):
                    parsed_details["phone"] = emp_email_res["phone"]
                if emp_email_res.get("contact_person") and not parsed_details.get("contact_person"):
                    parsed_details["contact_person"] = emp_email_res["contact_person"]
            except Exception as emp_enrich_err:
                logger.debug("Stage 4b employer email enrichment error for %s: %s", company, emp_enrich_err)

        # Populate SSR occupation/title/description metadata onto enriched record for Stage B relevance verification
        if parsed_details.get("ssr_hauptberuf") and (not enriched.get("hauptberuf") or enriched.get("hauptberuf") == "N/A"):
            enriched["hauptberuf"] = parsed_details["ssr_hauptberuf"]
        if parsed_details.get("ssr_description") and not enriched.get("description"):
            enriched["description"] = parsed_details["ssr_description"]
        if parsed_details.get("ssr_firma") and (not company or company in ("N/A", "k. A.")):
            enriched["company"] = parsed_details["ssr_firma"]
            company = parsed_details["ssr_firma"]
        cur_title = str(enriched.get("title") or "").strip()
        if not cur_title or cur_title in ("N/A", "k. A."):
            if parsed_details.get("ssr_title"):
                enriched["title"] = parsed_details["ssr_title"]
            elif parsed_details.get("ssr_hauptberuf"):
                enriched["title"] = f"Ausbildung {parsed_details['ssr_hauptberuf']}"

        # ---------------------------------------------------------------------
        # Consolidate and Normalize
        # ---------------------------------------------------------------------
        from services.data_validator import (
            validate_form_link,
            validate_job_listing_url,
            validate_phone_number,
            sanitize_contact_person,
            validate_application_url,
        )

        # Phone validation
        raw_phone = parsed_details.get("phone") or enriched.get("phone") or ""
        is_phone_ok, clean_phone, _ = validate_phone_number(raw_phone)
        enriched["phone"] = clean_phone if is_phone_ok else ""

        # Contact person validation
        raw_cp = parsed_details.get("contact_person") or enriched.get("arbeitsgeber") or ""
        is_cp_ok, clean_cp, _ = sanitize_contact_person(raw_cp)
        enriched["contact_person"] = clean_cp if is_cp_ok else ""
        enriched["arbeitsgeber"] = enriched["contact_person"]

        # Direct application url and form link validation
        raw_direct = str(parsed_details.get("direct_application_url") or "").strip()
        raw_has_form = bool(parsed_details.get("has_form"))
        is_form_ok, clean_form_link, _ = validate_form_link(raw_direct, has_form=raw_has_form)
        enriched["has_form"] = is_form_ok
        enriched["form_link"] = clean_form_link if is_form_ok else ""

        is_app_ok, clean_app_url, _ = validate_application_url(raw_direct)
        enriched["direct_application_url"] = clean_app_url if is_app_ok else (clean_form_link if is_form_ok else "")

        # Always preserve the authentic vacancy URL
        orig_listing = source_url or enriched.get("apply_url") or enriched.get("url") or ""
        is_list_ok, clean_listing, _ = validate_job_listing_url(orig_listing)
        enriched["job_listing_url"] = clean_listing or orig_listing
        enriched["apply_url"] = clean_listing or orig_listing
        enriched["bewerbung_link"] = enriched["direct_application_url"] or enriched["job_listing_url"]

        enriched["email"] = parsed_details.get("email") or enriched.get("email") or ""
        enriched["email_type"] = parsed_details.get("email_type") or ("recruitment" if enriched["email"] else "")
        enriched["postal_address"] = parsed_details.get("postal_address") or ""
        enriched["employer_website"] = parsed_details.get("employer_website") or ""
        enriched["application_url_type"] = parsed_details.get("application_url_type") or ("direct_form" if is_form_ok else "none")
        enriched["required_documents"] = parsed_details.get("required_documents") or ""
        enriched["application_methods"] = parsed_details.get("application_methods") or []

        # Final application_method calculation
        app_method, bewerbung_art = classify_application_method(
            email=enriched["email"],
            has_form=enriched["has_form"],
            existing_method=parsed_details.get("application_method") or enriched.get("application_method") or "",
            direct_url=enriched["direct_application_url"],
        )
        enriched["application_method"] = app_method
        enriched["bewerbung_art"] = bewerbung_art

        if parsed_details.get("extraction_method"):
            enriched["extraction_method"] = parsed_details["extraction_method"]
        elif driver is not None and not (has_email or has_form or has_ext_link):
            enriched["extraction_method"] = "selenium"
        else:
            enriched["extraction_method"] = "fast_http"

        if parsed_details.get("manual_review_required") and not (enriched["email"] or enriched["has_form"] or enriched["direct_application_url"]):
            enriched["manual_review_required"] = True
            enriched["manual_review_reason"] = parsed_details.get("manual_review_reason") or "Manual review required"

        from services.contamination_detector import attach_contact_provenance
        attach_contact_provenance(
            enriched,
            source_url=source_url,
            section="arbeitsagentur_kontaktdaten",
            extraction_method=enriched["extraction_method"],
            verified=True,
        )

        if enriched["email"] or enriched["has_form"] or enriched["direct_application_url"]:
            enriched["extraction_status"] = "completed"
        elif enriched.get("manual_review_required"):
            enriched["extraction_status"] = "manual_review_required"
        elif enriched["phone"] or enriched["contact_person"]:
            enriched["extraction_status"] = "partial"
        else:
            enriched["extraction_status"] = "no_contact_found"

        enriched["extraction_logs"] = logs
        return normalize_job_opportunity_row(enriched)
