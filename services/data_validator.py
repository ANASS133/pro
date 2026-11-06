"""
JobScout Centralized Data Validator & Sanitizer.

Provides strict, reusable validation and sanitization for:
1. Job listing URLs (preserving original vacancy ad URLs, rejecting advice/guide pages).
2. Phone numbers (rejecting fragments, coordinates, dates, multi-line values, standardizing German formats).
3. Recruiter / Contact person names (stripping addresses, street markers, postal codes, department names, normalizing honorifics & casing).
4. Application URLs and destination links (preventing advice links, correcting malformed mailto protocols).
5. Application form links (rejecting generic portal homepages, verifying actual form/ATS endpoints).
"""

import logging
import re
from typing import Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse

try:
    import phonenumbers
except ImportError:
    phonenumbers = None

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# ADVICE & GENERIC LANDING PAGE PATTERNS
# -----------------------------------------------------------------------------
GENERIC_ADVICE_PATHS = (
    "/ratgeber/",
    "/ratgeber",
    "/magazin/",
    "/magazin",
    "/tipps/",
    "/tipps",
    "/faq/",
    "/faq",
    "/blog/",
    "/blog",
    "/karriere-ratgeber/",
    "/karriere-ratgeber",
    "/bewerbungstipps/",
    "/bewerbungstipps",
    "/help/",
    "/service/",
    "/ueber-uns/",
    "/ueber-uns",
    "/impressum",
    "/datenschutz",
    "/agb",
    "/suche/",
    "/search/",
)

KNOWN_PORTAL_ADVICE_DOMAINS = {
    "ausbildung.de": ["/ratgeber", "/bewerbung", "/magazin", "/tipps", "/suche"],
    "azubiyo.de": ["/bewerbung", "/ratgeber", "/magazin", "/tipps", "/schueler", "/suche"],
    "aubi-plus.de": ["/bewerbung", "/ratgeber", "/magazin", "/tipps", "/suche"],
    "arbeitsagentur.de": ["/ratgeber", "/tipps", "/faq", "/hilfe"],
}

# Generic job board root domains or landing pages that must NEVER be classified as a verified application form
GENERIC_PORTAL_ROOTS = {
    "jobs.hogapage.de",
    "hogapage.de",
    "stepstone.de",
    "www.stepstone.de",
    "indeed.com",
    "de.indeed.com",
    "monster.de",
    "stellenanzeigen.de",
    "stellenmarkt.de",
    "arbeitsagentur.de",
    "www.arbeitsagentur.de",
    "ausbildung.de",
    "www.ausbildung.de",
    "azubiyo.de",
    "www.azubiyo.de",
    "aubi-plus.de",
    "www.aubi-plus.de",
}

# -----------------------------------------------------------------------------
# STREET & ADDRESS PATTERNS (German)
# -----------------------------------------------------------------------------
GERMAN_STREET_MARKERS = [
    r"straße\b",
    r"strasse\b",
    r"str\.\b",
    r"str\b",
    r"weg\b",
    r"platz\b",
    r"pl\.\b",
    r"allee\b",
    r"gasse\b",
    r"ring\b",
    r"damm\b",
    r"ufer\b",
    r"chaussee\b",
    r"zeile\b",
    r"berg\b",
    r"rain\b",
    r"graben\b",
    r"markt\b",
    r"kamp\b",
    r"anger\b",
    r"gässchen\b",
    r"gaesschen\b",
    r"steig\b",
    r"steg\b",
    r"acker\b",
    r"feld\b",
    r"tor\b",
    r"seeufer\b",
    r"kleblmühle\b",
    r"hohensyburgstr\b",
    r"kirchheimer\b",
    r"fontanestr\b",
    r"neustr\b",
    r"overather\b",
    r"europastr\b",
]

# Words indicating a street or address preposition
ADDRESS_PREPOSITIONS = [
    r"\bunter\s+der\b",
    r"\bunter\s+den\b",
    r"\bauf\s+dem\b",
    r"\ban\s+der\b",
    r"\bam\b",
    r"\ban\b",
    r"\bim\b",
    r"\bin\b",
]

# Generic department names and non-person phrases that should be rejected
INVALID_CONTACT_PATTERNS = [
    re.compile(r"\bpersonalabteilung\b", re.I),
    re.compile(r"\bpersonal(?:referat|bereich|wesen)\b", re.I),
    re.compile(r"\bhr\s*(?:team|abteilung|management|department)?\b", re.I),
    re.compile(r"\bbewerbermanagement\b", re.I),
    re.compile(r"\brecruiting(?:\s+team)?\b", re.I),
    re.compile(r"\bzentrale\b", re.I),
    re.compile(r"\bausbildung(?:sleitung|szeit)?\b", re.I),
    re.compile(r"\bgastronomie\b", re.I),
    re.compile(r"\bveranstaltungsgastronomie\b", re.I),
    re.compile(r"\bcorporate\s+benefits\b", re.I),
    re.compile(r"\barbeitskleidung\b", re.I),
    re.compile(r"\bwährend\s+deiner\b", re.I),
    re.compile(r"\bund\s+ausbilder\b", re.I),
    re.compile(r"\bunterstützen\s+und\s+fördern\b", re.I),
    re.compile(r"\bfür\s+restaurants\b", re.I),
]


# =============================================================================
# 1. JOB LISTING URL VALIDATION
# =============================================================================
def is_advice_or_generic_page(url: str) -> bool:
    """Checks whether a URL is a generic advice page, guide, blog, or search page."""
    if not url:
        return False
    u = url.strip().lower()
    parsed = urlparse(u)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()

    # Domain-specific advice checks
    for portal_domain, advice_prefixes in KNOWN_PORTAL_ADVICE_DOMAINS.items():
        if portal_domain in netloc:
            for prefix in advice_prefixes:
                if path.startswith(prefix) or f"{prefix}/" in path or path == prefix:
                    return True

    # Generic advice path checks
    for advice_path in GENERIC_ADVICE_PATHS:
        if advice_path in path:
            return True

    # Generic /bewerbung/ check: if path is exactly /bewerbung or /bewerbung/
    if path.rstrip("/") in ("/bewerbung", "/karriere/bewerbung", "/jobs/bewerbung"):
        return True

    return False


def validate_job_listing_url(
    url: Optional[str],
    original_portal_url: Optional[str] = "",
) -> Tuple[bool, str, str]:
    """
    Validates and preserves the genuine job advertisement URL.
    Rejects generic advice/guide pages and naked portal roots.
    Falls back to original_portal_url if provided and valid.

    Returns:
        (is_valid, cleaned_url, error_reason)
    """
    candidate = str(url or "").strip()
    fallback = str(original_portal_url or "").strip()

    def check_single_url(u: str) -> Tuple[bool, str]:
        if not u or u.lower() in ("nan", "none", "null", "n/a"):
            return False, "URL is empty"
        if not u.startswith(("http://", "https://")):
            return False, "Missing http/https protocol"
        parsed = urlparse(u)
        if not parsed.netloc or "." not in parsed.netloc:
            return False, "Invalid domain"
        if is_advice_or_generic_page(u):
            return False, f"Generic advice or guide page: {u}"
        # Reject naked homepages for job ads
        if parsed.path.strip("/") == "" and not parsed.query:
            return False, "Root homepage cannot be a job listing URL"
        return True, ""

    is_cand_valid, cand_reason = check_single_url(candidate)
    if is_cand_valid:
        return True, candidate, ""

    # Try fallback if candidate was invalid
    if fallback and fallback != candidate:
        is_fall_valid, fall_reason = check_single_url(fallback)
        if is_fall_valid:
            return True, fallback, ""

    return False, "", cand_reason or "Invalid job listing URL"


# =============================================================================
# 2. PHONE NUMBER VALIDATION & STANDARDIZATION
# =============================================================================
def validate_phone_number(
    raw_phone: Optional[str],
    default_region: str = "DE",
) -> Tuple[bool, str, str]:
    """
    Validates and normalizes German telephone numbers.
    Rejects:
    - Multi-line strings (containing newlines)
    - Fragment numbers (e.g., '026', '000', '027')
    - Decimal / SVG coordinate strings ('05859 7.75 3.5 6.19141 3')
    - Date strings ('01.09.2027', '022-2025')
    - Short numbers under 7 digits

    Returns:
        (is_valid, formatted_phone, error_reason)
    """
    if not raw_phone:
        return False, "", "Empty phone value"

    raw = str(raw_phone).strip()
    if not raw or raw.lower() in ("nan", "none", "null", "n/a", "k.a.", "k. a."):
        return False, "", "Empty or NaN placeholder"

    # Strip trunk prefix in parentheses, e.g. +49 (0) 30 -> +49 30
    raw = re.sub(r"(\+49|0049)\s*\(0\)", r"\1 ", raw, flags=re.I)

    # Reject newlines or carriage returns (multi-line corrupted values)
    if "\n" in raw or "\r" in raw:
        return False, "", "Contains newline (multi-line corrupted value)"

    # Reject coordinate/decimal lists: numbers with decimals like '7.75' or multiple spaced decimals
    if re.search(r"\d+\.\d{2,}", raw) or re.search(r"\d+\s+\d+\.\d+", raw):
        return False, "", "Contains decimal coordinates or SVG path data"

    # Reject date patterns like 01.09.2027 or 01/08/2025
    if re.search(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b", raw):
        return False, "", "Contains date pattern instead of telephone"

    # Reject year ranges like 2022-2025 or 022-2025
    if re.search(r"\b(?:(?:19|20)\d{2}\s*[-–]\s*(?:(?:19|20)\d{2}|\d{2})|0?2\d\s*[-–]\s*20\d{2})\b", raw):
        return False, "", "Contains year range instead of telephone"

    # Extract clean digits and leading plus
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) < 7:
        return False, "", f"Too few digits ({len(digits)}) for a valid phone number"

    # Reject reference IDs starting with multiple zeros (e.g. '0000-12075517', '0001-...')
    if raw.startswith(("000", "001")):
        return False, "", "Reference number misinterpreted as phone"

    # Reject repetitive garbage like '0000000' or '1111111'
    if len(set(digits)) <= 2 and len(digits) < 10:
        return False, "", "Repetitive or placeholder digits"

    # Reject date misinterpretations: in German job ads, dates like 01.08.2027, 01.09.2027, 01.02.2027
    # end in a 4-digit future year (e.g. 2024..2035) and have 8 digits starting with 01..31
    if re.search(r"202[4-9]|203[0-5]", digits):
        # If it ends with 202x/203x and total digits is 8 or 10, it's a day+month+year date
        if len(digits) in (8, 10) and (digits.startswith("0") or digits.startswith("49")):
            return False, "", "Date string misinterpreted as phone number"

    # Primary validation via phonenumbers library if installed
    if phonenumbers is not None:
        try:
            # Clean separators for parser
            cleaned_input = re.sub(r"[^\d+()/\s\-]", "", raw)
            parsed_num = phonenumbers.parse(cleaned_input, default_region)
            if phonenumbers.is_valid_number(parsed_num):
                nat_num = str(parsed_num.national_number)
                # German mobile starts with 15/16/17; German service with 18. Never 10, 11, 12, 14.
                if nat_num.startswith("1") and not nat_num.startswith(("15", "16", "17", "18")):
                    return False, "", "Invalid German prefix (10/11/12/14)"
                formatted = phonenumbers.format_number(
                    parsed_num, phonenumbers.PhoneNumberFormat.E164
                )
                return True, formatted, ""
            return False, "", "phonenumbers validation failed"
        except Exception as parse_err:
            logger.debug("phonenumbers parse failed for '%s': %s", raw, parse_err)

    # Fallback validation with German phone number standards
    cleaned = re.sub(r"[^\d+]", "", raw)
    if cleaned.startswith("0049"):
        normalized = "+49" + cleaned[4:]
    elif cleaned.startswith("+49"):
        normalized = cleaned
    elif cleaned.startswith("0") and len(cleaned) >= 8:
        # National format: area code must start with 1-9 (not 0)
        area_first = cleaned[1]
        if area_first in "123456789":
            normalized = "+49" + cleaned[1:]
        else:
            return False, "", "Invalid German area code"
    else:
        return False, "", "Invalid German phone prefix"

    # Check area code rules in German numbering plan
    after_cc = normalized.replace("+49", "")
    if after_cc.startswith("1") and not after_cc.startswith(("15", "16", "17", "18")):
        return False, "", "Invalid German prefix (10/11/12/14)"

    # Verify length of international standard (+49 + 7 to 13 digits)
    num_digits_after_country = len(after_cc)
    if 6 <= num_digits_after_country <= 13:
        return True, normalized, ""

    return False, "", "Invalid phone number length"


# =============================================================================
# 3. RECRUITER / CONTACT PERSON VALIDATION & SANITIZATION
# =============================================================================
def sanitize_contact_person(raw_name: Optional[str]) -> Tuple[bool, str, str]:
    """
    Cleans and standardizes recruiter and contact person names.
    - Preserves honorifics ('Herr', 'Frau', 'Dr.', 'Prof.')
    - Stops at newlines and punctuation
    - Detects and trims German street names, postal codes, and addresses
    - Strips conversational phrases ('ist: ...', 'e-mail anzeigen', 'auf einen', 'für')
    - Rejects generic department names ('Personalabteilung', 'Bewerbermanagement')
    - Rejects job titles mistakenly captured as names ('Frau für Restaurants...')
    - Formats to proper Title Case

    Returns:
        (is_valid, cleaned_name, error_reason)
    """
    if not raw_name:
        return False, "", "Empty contact person"

    raw = str(raw_name).strip()
    if not raw or raw.lower() in ("nan", "none", "null", "n/a", "k.a.", "k. a."):
        return False, "", "Empty contact person"

    # Stop at first newline or carriage return
    raw = raw.split("\n")[0].split("\r")[0].strip()

    # Check for invalid generic department names or non-person text
    for pat in INVALID_CONTACT_PATTERNS:
        if pat.search(raw):
            return False, "", f"Matched invalid pattern: {pat.pattern}"

    # Strip conversational prefixes like "ist:", "ist ", "Herr/Frau ist", "Ansprechpartner:"
    raw = re.sub(r"^(?:(?:ihr[e]?\s+)?ansprechpartner(?:in)?|kontaktperson|kontakt)\s*[:\-\s]\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"^ist\s*[:\-\s]\s*", "", raw, flags=re.I).strip()
    raw = re.sub(r"^ist\s+(?:herr|frau)\b", lambda m: m.group(0).split()[-1], raw, flags=re.I).strip()

    # Strip trailing punctuation or sentence terminators: comma, semicolon, pipe, period at end
    raw = raw.rstrip(".,;:|/- ")

    # Stop at telephone or email or trailing metadata cues
    raw = re.split(r"(?:telefon|tel\.|fon|e-mail|mail)\s*:", raw, flags=re.I)[0].strip()
    raw = re.split(r"[,;|]", raw)[0].strip()

    # Strip trailing filler phrases like "e-mail anzeigen", "auf einen", "für", "anzeigen"
    raw = re.sub(r"\s+e-mail\s+anzeigen.*$", "", raw, flags=re.I).strip()
    raw = re.sub(r"\s+(?:auf\s+einen|auf|für)\b.*$", "", raw, flags=re.I).strip()

    # Strip German postal codes and cities: e.g. "70174 Stuttgart" or "50667"
    raw = re.sub(r"\b\d{5}\b.*$", "", raw).strip()

    # Strip street names and address elements:
    # 1. Match address prepositions: e.g. "unter der ...", "im ...", "an der ..."
    for prep in ADDRESS_PREPOSITIONS:
        raw = re.split(prep, raw, flags=re.I)[0].strip()

    # 2. Standalone street type words (str, straße, weg, seeufer, etc) can take preceding street word:
    # e.g. 'overather str', 'kirchheimer str', 'zielow seeufer'
    standalone_types = (
        r"(?:straße|strasse|str\.|str|weg|platz|pl\.|allee|gasse|ring|"
        r"damm|ufer|seeufer|chaussee|zeile|berg|rain|graben|markt|kamp|anger|steig|steg|acker|feld|tor)"
    )
    raw = re.sub(rf"\b[A-Za-zÄÖÜäöüß\-]+\s+{standalone_types}\b.*$", "", raw, flags=re.I).strip()

    # 3. Match compound word ending in street type: e.g. 'hans-vogel-straße', 'fontanestr', 'neustr', 'europastr', 'kleblmühle'
    raw = re.sub(
        rf"\b[A-Za-zÄÖÜäöüß\-]+(?:straße|strasse|str|weg|platz|allee|gasse|ring|damm|ufer|seeufer|mühle)\b.*$",
        "",
        raw,
        flags=re.I,
    ).strip()

    # Re-clean trailing punctuation or whitespace
    raw = re.sub(r"\s+", " ", raw).strip(" .,;:-")

    # If nothing remains or too short
    if not raw or len(raw) < 3:
        return False, "", "Name too short or empty after address stripping"

    # Check tokens
    tokens = raw.split()

    # If first token is honorific (Herr / Frau), ensure there is at least one name token
    honorific = ""
    title = ""
    idx = 0
    if tokens and tokens[0].lower() in ("herr", "herrn", "frau"):
        honorific = "Frau" if tokens[0].lower() == "frau" else "Herr"
        idx += 1

    if idx < len(tokens) and tokens[idx].lower() in ("dr.", "dr", "prof.", "prof"):
        title = tokens[idx].title().rstrip(".") + "."
        idx += 1

    name_tokens = tokens[idx:]
    if not name_tokens:
        return False, "", "Only honorific present without a name"

    # Reject if only 1 token and that token is a single letter or not capitalized
    cleaned_name_parts = []
    for part in name_tokens:
        part_clean = part.strip(".,;:()")
        if part_clean and len(part_clean) > 1 and part_clean.isalpha():
            cleaned_name_parts.append(part_clean.capitalize())
        elif "-" in part_clean:
            # hyphenated name: e.g. Rist-Martius
            sub_parts = [sp.capitalize() for sp in part_clean.split("-") if sp.isalpha()]
            cleaned_name_parts.append("-".join(sub_parts))

    if not cleaned_name_parts:
        return False, "", "No valid alphabetic name parts"

    # Reconstruct clean name with proper Title Casing
    full_parts = []
    if honorific:
        full_parts.append(honorific)
    if title:
        full_parts.append(title)
    full_parts.extend(cleaned_name_parts)

    cleaned_full_name = " ".join(full_parts)
    return True, cleaned_full_name, ""


def validate_contact_person(raw_name: Optional[str]) -> Tuple[bool, str, str]:
    """Alias for sanitize_contact_person."""
    return sanitize_contact_person(raw_name)


# =============================================================================
# 4. APPLICATION URL VALIDATION
# =============================================================================
def validate_application_url(
    url: Optional[str],
    job_listing_url: Optional[str] = "",
) -> Tuple[bool, str, str]:
    """
    Validates destination application URL.
    - Corrects/rejects malformed 'https://mailto:...'
    - Rejects generic advice and guide pages
    - Rejects tel: links
    - Preserves genuine ATS and job application destinations

    Returns:
        (is_valid, cleaned_url, error_reason)
    """
    raw = str(url or "").strip()
    if not raw:
        return False, "", "Empty application URL"

    # Check for malformed mailto protocol
    if "mailto:" in raw.lower():
        # Extract email address if embedded
        m = re.search(r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", raw, re.I)
        email = m.group(1).lower() if m else ""
        return False, "", f"Malformed mailto protocol (email={email})"

    # Check for tel protocol
    if "tel:" in raw.lower():
        return False, "", "Telephone protocol cannot be an application URL"

    # Check for advice / guide page
    if is_advice_or_generic_page(raw):
        return False, "", f"Generic advice or guide page: {raw}"

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "", "Invalid URL scheme or missing hostname"

    return True, raw, ""


# =============================================================================
# 5. APPLICATION FORM LINK VALIDATION
# =============================================================================
def validate_form_link(
    url: Optional[str],
    has_form: bool = True,
) -> Tuple[bool, str, str]:
    """
    Strictly validates verified online application form links.
    - Rejects generic job portal homepages (e.g. 'https://jobs.hogapage.de')
    - Rejects naked root domains without specific form path/query
    - Rejects malformed 'mailto:' URLs
    - Requires verified ATS endpoint or application form path

    Returns:
        (is_valid, cleaned_url, error_reason)
    """
    if not has_form or not url:
        return False, "", "has_form is False or URL empty"

    raw = str(url).strip()
    if not raw.startswith(("http://", "https://")):
        return False, "", "Missing http/https protocol"

    # Reject malformed mailto
    if "mailto:" in raw.lower():
        return False, "", "Malformed mailto link cannot be a form link"

    parsed = urlparse(raw)
    netloc = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/")

    # Check generic portal roots
    if netloc in GENERIC_PORTAL_ROOTS:
        # A root domain or top-level portal page is NEVER a verified direct form
        if not path or path in ("jobs", "stellenangebote", "stellen", "jobsuche"):
            return False, "", f"Generic portal root/listing '{netloc}' is not a direct form"

    # Reject naked root domains for any company without any path or query
    if not path and not parsed.query:
        return False, "", f"Root domain '{netloc}' without form path cannot be a verified form"

    # Reject advice pages
    if is_advice_or_generic_page(raw):
        return False, "", f"Generic advice page cannot be a form link: {raw}"

    return True, raw, ""
