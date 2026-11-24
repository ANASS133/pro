"""
Application Destination Classification, Evidence-Based Validation & Employer Career Crawler.

Implements Part 1 & Part 3 requirements:
1. Explicit ApplicationDestinationType enum classification based on page evidence.
2. Redirect chain tracking, HTTP status verification, employer/job matching, form & login detection.
3. Rejection of generic employer homepages (e.g., https://www.deimann.de, https://www.bmas.de,
   https://www.boehringer-ingelheim.com, https://jobs.umg-gastronomie.de/, https://www.lokschuppen-marburg.com)
   as verified direct application URLs unless resolved to a job-specific application page or form.
4. Controlled crawl of generic employer websites / 404 career pages to locate the specific Ausbildung
   listing or recruitment email (including TYPO3 Caesar-cipher mailto and Cloudflare email decoding).
"""

import html as html_lib
import json
import logging
import re
import threading
import urllib.parse
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from services.data_validator import (
    GENERIC_PORTAL_ROOTS,
    is_advice_or_generic_page,
)
from services.employer_cache import (
    PORTAL_DOMAINS,
    SHARED_ATS_DOMAINS,
    SHORTENER_DOMAINS,
    extract_registrable_domain,
    is_portal_domain,
    is_shortener_domain,
    normalize_company_identity,
)

logger = logging.getLogger(__name__)


class ApplicationDestinationType(str, Enum):
    DIRECT_APPLICATION_FORM = "direct_application_form"
    JOB_SPECIFIC_APPLICATION_PAGE = "job_specific_application_page"
    RECRUITMENT_PORTAL = "recruitment_portal"
    LOGIN_REQUIRED = "login_required"
    EMPLOYER_CAREERS_PAGE = "employer_careers_page"
    GENERIC_EMPLOYER_WEBSITE = "generic_employer_website"
    IRRELEVANT_PAGE = "irrelevant_page"
    BROKEN_URL = "broken_url"
    REGION_RESTRICTED = "region_restricted"
    REQUIRES_MANUAL_REVIEW = "requires_manual_review"


# Destination types that qualify as a verified application destination
VERIFIED_DESTINATION_TYPES = {
    ApplicationDestinationType.DIRECT_APPLICATION_FORM,
    ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE,
}

# Known ATS host/path signatures
KNOWN_ATS_SIGNATURES = (
    "softgarden.io",
    "softgarden.de",
    "personio.de",
    "personio.com",
    "myworkdayjobs.com",
    "workday.com",
    "greenhouse.io",
    "smartrecruiters.com",
    "recruitee.com",
    "dvinci-easy.com",
    "d-vinci.de",
    "onlyfy.jobs",
    "prescreen.io",
    "join.com",
    "talention.com",
    "successfactors.com",
    "successfactors.eu",
    "guidecom.de",
    "rexx-systems.com",
    "perbit.cloud",
    "contactrh.com",
    "jobufo.com",
    "gohiring.com",
    "umantis.com",
    "bamboohr.com",
    "lever.co",
    "icims.com",
    "taleo.net",
    "pi-asp.de",
    "bewerberportal",
    "talentcommunity/apply",
    "candidateselfservice",
    "persis",
    "projectid=",
    "fn=bm.jobs",
    "info-online.org",
    "iventajobdata.eu",
    "rexx-recruitment.com",
    "rexx-systems.com",
    "jobs.lvr.de",
    "bundeswehr-karriere.de",
    "public.euroakademie.de",
    "hana.ondemand.com",
    "easyapply",
    "/workflow",
    "vacancyid=",
    "/kip",
    "/anmeldung/",
)

# Paths that indicate a generic homepage or start page rather than a job/application page
GENERIC_HOMEPAGE_PATHS = {
    "",
    "index.html",
    "index.php",
    "index.htm",
    "start",
    "start.html",
    "startseite",
    "startseite.html",
    "home",
    "home.html",
    "de",
    "de/home",
    "de/startseite",
    "en",
    "willkommen",
}

# Paths that indicate a generic careers overview page (not a specific job or application form)
GENERIC_CAREERS_OVERVIEW_PATHS = {
    "karriere",
    "karriere/stellenangebote",
    "karriere/jobs",
    "karriere/ausbildung",
    "jobs",
    "jobs-karriere",
    "jobs-und-karriere",
    "jobs-und-karriere/stellenangebote",
    "jobs-und-karriere/ausbildung",
    "stellenangebote",
    "stellenmarkt",
    "offene-stellen",
    "ausbildung",
    "beruf-und-karriere",
    "arbeiten-bei-uns",
    "career",
    "careers",
    "de/karriere",
    "de/jobs",
    "de/ausbildung",
}


def decode_typo3_mailto(token: str, vector: int = 2) -> str:
    """
    Decodes TYPO3 spamProtectEmailAddresses Caesar cipher (`data-mailto-token` + `data-mailto-vector`).
    TYPO3 shifts characters in ranges:
      0x2B..0x3A ('+'..':'), 0x40..0x5A ('@'..'Z'), 0x61..0x7A ('a'..'z')
    """
    if not token:
        return ""
    out: List[str] = []
    shift = -abs(int(vector or 2))
    for ch in token:
        code = ord(ch)
        if 0x2B <= code <= 0x3A:
            dec = 0x2B + ((code - 0x2B + shift) % (0x3A - 0x2B + 1))
            out.append(chr(dec))
        elif 0x40 <= code <= 0x5A:
            dec = 0x40 + ((code - 0x40 + shift) % (0x5A - 0x40 + 1))
            out.append(chr(dec))
        elif 0x61 <= code <= 0x7A:
            dec = 0x61 + ((code - 0x61 + shift) % (0x7A - 0x61 + 1))
            out.append(chr(dec))
        else:
            out.append(ch)
    decoded = "".join(out)
    decoded = urllib.parse.unquote(decoded)
    if decoded.lower().startswith("mailto:"):
        decoded = decoded[7:]
    email_part = decoded.split("?")[0].strip().lower()
    if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email_part):
        return email_part
    return ""


def decode_cloudflare_email(cf_hex: str) -> str:
    """Decodes Cloudflare `data-cfemail` hex string."""
    try:
        r = int(cf_hex[:2], 16)
        email = "".join(chr(int(cf_hex[i : i + 2], 16) ^ r) for i in range(2, len(cf_hex), 2)).strip().lower()
        if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            return email
    except Exception:
        pass
    return ""


def extract_all_emails_including_obfuscated(html: str) -> List[str]:
    """
    Extracts standard mailto/text emails PLUS TYPO3 `data-mailto-token`, Cloudflare `data-cfemail`,
    JS unicode/hex escapes, `data-user`/`data-domain`, JS concatenations, and `(at)`/`(ät)`/`[punkt]` obfuscation.
    """
    if not html:
        return []
    unescaped = html_lib.unescape(html)
    # Normalize JS unicode/hex escapes for @ and . (common in Next.js / React JSON payloads)
    unescaped = (
        unescaped
        .replace("\\u0040", "@").replace("\\u002e", ".").replace("\\u002E", ".")
        .replace("\\x40", "@").replace("\\x2e", ".").replace("\\x2E", ".")
    )
    candidates: List[str] = []

    # 1. TYPO3 data-mailto-token
    for m_t3 in re.finditer(
        r'data-mailto-token=["\']([^"\']+)["\'](?:\s+data-mailto-vector=["\'](-?\d+)["\'])?',
        unescaped,
        re.I,
    ):
        vec = int(m_t3.group(2)) if m_t3.group(2) else 2
        dec = decode_typo3_mailto(m_t3.group(1), vec)
        if dec and dec not in candidates:
            candidates.append(dec)

    # 2. Cloudflare data-cfemail
    for cf_hex in re.findall(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', unescaped):
        dec = decode_cloudflare_email(cf_hex)
        if dec and dec not in candidates:
            candidates.append(dec)

    # 3. HTML data-user / data-name + data-domain attributes
    for m_attr in re.finditer(
        r'data-(?:user|name|mail-user)=["\']([A-Za-z0-9._%+-]+)["\'][^>]{0,120}?data-(?:domain|host|mail-domain)=["\']([A-Za-z0-9.-]+\.[A-Za-z]{2,})["\']',
        unescaped,
        re.I,
    ):
        cand_attr = f"{m_attr.group(1)}@{m_attr.group(2)}".strip().lower()
        if cand_attr not in candidates:
            candidates.append(cand_attr)

    # 4. Simple JS string concatenation ('karriere' + '@' + 'firma.de')
    for m_js in re.finditer(
        r'["\']([A-Za-z0-9._%+-]+)["\']\s*\+\s*["\']@["\']\s*\+\s*["\']([A-Za-z0-9.-]+\.[A-Za-z]{2,})["\']',
        unescaped,
    ):
        cand_js = f"{m_js.group(1)}@{m_js.group(2)}".strip().lower()
        if cand_js not in candidates:
            candidates.append(cand_js)

    # 5. Standard mailto: links
    for m_mail in re.findall(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', unescaped, re.I):
        e_low = m_mail.strip().lower()
        if e_low not in candidates:
            candidates.append(e_low)

    # 6. De-obfuscate (at)/(ät)/[at] and (dot)/(punkt)/[punkt] patterns in text
    deobf = re.sub(r"\s*(?:\[(?:at|ät|ae?t)\]|(?:\((?:at|ät|ae?t)\))|\{(?:at|ät|ae?t)\}|\s+at\s+)\s*", "@", unescaped, flags=re.I)
    deobf = re.sub(r"\s*(?:\[(?:dot|punkt)\]|(?:\((?:dot|punkt)\))|\{(?:dot|punkt)\})\s*", ".", deobf, flags=re.I)
    for m_reg in re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", deobf):
        e_low = m_reg.strip().lower()
        if not e_low.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")):
            if e_low not in candidates:
                candidates.append(e_low)

    return candidates


def _classify_structural_generic_homepage(url: str) -> Tuple[bool, str]:
    """
    Determines whether a URL is structurally a generic employer website homepage or
    a generic careers overview root without any job-specific identifier.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, ""
    parsed = urlparse(url.strip())
    netloc = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/").lower()
    query = (parsed.query or "").strip().lower()

    # Check if query contains a specific job/vacancy parameter
    job_query_keys = (
        "jobid=", "job_id=", "stelleid=", "ausid=", "p=", "id=", "jp=", "prj=", "oid=",
        "stearefnr=", "anzeige=", "projectid=", "fn=bm.jobs", "guid=", "guid", "sid=", "ref=",
        "ac=jobad", "ac=apply", "crmid=", "actionhandler=",
        "reqid=", "vacancyid=", "workflowid=",
    )
    has_job_query = any(k in query for k in job_query_keys)

    if has_job_query:
        return False, ""

    # 1. Naked root homepage or /start.html, /index.html, etc.
    if path in GENERIC_HOMEPAGE_PATHS:
        if any(sub in netloc for sub in ("jobs.", "karriere.", "career.", "careers.", "ausbildung.")):
            return True, ApplicationDestinationType.EMPLOYER_CAREERS_PAGE.value
        return True, ApplicationDestinationType.GENERIC_EMPLOYER_WEBSITE.value

    # 2. Generic careers overview path (e.g. /karriere, /jobs, /stellenangebote) without a specific job slug
    if path in GENERIC_CAREERS_OVERVIEW_PATHS:
        return True, ApplicationDestinationType.EMPLOYER_CAREERS_PAGE.value

    # 3. Single-segment path on an employer domain that is just a city/branch name (e.g. amber-hotels.de/reichenhall, bg-kliniken.de/klinikum-bergmannstrost-halle)
    segments = [s for s in path.split("/") if s]
    if len(segments) == 1:
        seg = segments[0]
        # Alphanumeric short codes (e.g. /vcdw4, /zXCzc, /2p8kt3tw) or UUID/hex identifiers are specific job redirect tokens
        is_job_token = (
            (any(c.isdigit() for c in seg) and any(c.isalpha() for c in seg) and len(seg) <= 12)
            or bool(re.match(r"^[0-9a-fA-F-]{16,}$", seg))
        )
        if is_job_token:
            return False, ""

        job_or_apply_tokens = (
            "job", "stellen", "ausbildung", "bewerb", "apply", "karriere", "career",
            "vacanc", "position", "koch", "koechin", "fachinformatik", "kaufmann", "kauffrau",
            "elektroniker", "mechatroniker", "pflege", "azubi", "kurzbewerbung", "formular",
            "studium", "dual",
        )
        is_known_ats = any(sig in netloc for sig in KNOWN_ATS_SIGNATURES)
        if not is_known_ats and not any(tok in seg for tok in job_or_apply_tokens):
            # Single non-job path segment like /reichenhall or /klinikum-bergmannstrost-halle
            return True, ApplicationDestinationType.GENERIC_EMPLOYER_WEBSITE.value

    return False, ""


def is_structural_generic_homepage(url: str) -> bool:
    """Returns True if `url` is a structural generic employer homepage or bare careers root."""
    is_gen, _ = _classify_structural_generic_homepage(url)
    return is_gen


def _check_employer_match_in_destination(
    final_url: str,
    html: str,
    company: str,
) -> bool:
    """Checks whether the destination URL or page content corresponds to the job's employer."""
    comp_norm = normalize_company_identity(company)
    if not comp_norm:
        return True

    url_low = (final_url or "").lower()
    reg_dom = extract_registrable_domain(final_url)
    dom_stem = reg_dom.split(".")[0].replace("-", "") if reg_dom else ""

    comp_tokens = [t for t in comp_norm.split() if len(t) >= 3 and t not in {"hotel", "haus", "bad", "san", "st", "der", "die", "das", "und", "fuer"}]
    if not comp_tokens:
        comp_tokens = [t for t in comp_norm.split() if len(t) >= 2]

    # Check domain or URL match
    for tok in comp_tokens:
        if tok in url_low or (dom_stem and (tok in dom_stem or dom_stem in tok)):
            return True

    # Check page text/title if HTML is available
    if html:
        html_low = html_lib.unescape(html).lower()
        if any(tok in html_low for tok in comp_tokens):
            return True

    # Known corporate groups check
    from services.contamination_detector import KNOWN_CORPORATE_GROUP_DOMAINS
    for grp_dom, aliases in KNOWN_CORPORATE_GROUP_DOMAINS.items():
        if grp_dom in url_low or any(a in url_low for a in aliases):
            if any(a.strip() in comp_norm for a in aliases):
                return True

    return False


def _check_job_match_in_destination(
    final_url: str,
    html: str,
    job_title: str,
    search_keyword: str = "",
) -> bool:
    """Checks whether the destination URL or page content matches the specific job or Ausbildung."""
    url_low = (final_url or "").lower()
    combined_target = f"{job_title or ''} {search_keyword or ''}".lower()

    # Extract key occupation words
    occ_tokens: List[str] = []
    for kw in ("koch", "koechin", "köchin", "fachinformatik", "systemintegration", "anwendungsentwicklung",
               "kaufmann", "kauffrau", "elektronik", "mechatronik", "pflege", "bäcker", "baecker",
               "hotelfach", "restaurantfach", "ausbildung", "azubi"):
        if kw in combined_target:
            occ_tokens.append(kw)

    if any(tok in url_low for tok in occ_tokens if tok not in ("ausbildung", "azubi")):
        return True

    # Check query/path for explicit job ID or apply endpoint
    if re.search(r"(?:jobid|job_id|stelleid|ausid|jp|prj|oid|stearefnr)=\w+", url_low):
        return True
    if re.search(r"/(?:job|jobs|offer|vacancies|stellen|apply|applications|bewerbung)/[A-Za-z0-9_-]{3,}", url_low):
        return True

    if html:
        soup = BeautifulSoup(html, "html.parser")
        title_text = (soup.title.string if soup.title else "") or ""
        headings = " ".join(h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"]))
        focus_text = f"{title_text} {headings}".lower()
        non_generic_occ = [t for t in occ_tokens if t not in ("ausbildung", "azubi")]
        if non_generic_occ and any(t in focus_text for t in non_generic_occ):
            return True
        if not non_generic_occ and ("ausbildung" in focus_text or "azubi" in focus_text):
            return True

    return False


def _inspect_html_for_application_evidence(html: str, final_url: str) -> Dict[str, Any]:
    """
    Inspects HTML for actual application form fields, apply buttons, login walls,
    and structured JobPosting data.
    """
    evidence = {
        "has_application_form": False,
        "has_apply_button": False,
        "has_login_wall": False,
        "has_job_posting_schema": False,
        "apply_button_urls": [],
    }
    if not html:
        return evidence

    soup = BeautifulSoup(html, "html.parser")
    text_low = soup.get_text(" ", strip=True).lower()

    # 1. Check JSON-LD JobPosting
    for sc in soup.find_all("script", type="application/ld+json"):
        sc_txt = (sc.string or "").lower()
        if '"jobposting"' in sc_txt:
            evidence["has_job_posting_schema"] = True
            break

    # 2. Check for actual application forms (exclude search, login, newsletter, cookie forms)
    for form in soup.find_all("form"):
        f_str = str(form).lower()
        f_action = (form.get("action") or "").lower()
        f_id_class = f"{form.get('id', '')} {' '.join(form.get('class', []))}".lower()

        if any(noise in f_id_class or noise in f_action for noise in ("search", "suche", "newsletter", "cookie", "filter")):
            continue

        has_file_upload = bool(form.find("input", {"type": "file"}))
        has_applicant_fields = any(
            kw in f_str for kw in ("lebenslauf", "anschreiben", "vorname", "nachname", "resume", "cv", "bewerbung", "applicant")
        )
        if has_file_upload or (has_applicant_fields and len(form.find_all(["input", "textarea", "select"])) >= 3):
            evidence["has_application_form"] = True
            break

    # 3. Check for job-specific apply buttons/links
    for el in soup.find_all(["a", "button"]):
        btn_txt = el.get_text(" ", strip=True).lower()
        href = (el.get("href") or el.get("data-url") or el.get("data-href") or "").strip()
        if any(
            kw in btn_txt
            for kw in (
                "jetzt bewerben",
                "online bewerben",
                "direkt bewerben",
                "hier bewerben",
                "zur bewerbung",
                "online-bewerbung",
                "bewerbungsformular",
                "apply now",
                "apply online",
            )
        ):
            evidence["has_apply_button"] = True
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                full_h = urljoin(final_url, href)
                if full_h not in evidence["apply_button_urls"]:
                    evidence["apply_button_urls"].append(full_h)

    # 4. Check for login requirement
    login_cues = ("bitte melden sie sich an", "bewerberkonto", "anmelden, um sich zu bewerben", "login required", "registrieren sie sich")
    if any(cue in text_low for cue in login_cues) or any(
        p in final_url.lower() for p in ("/login", "/signin", "/register", "bewerbungverwalten.html")
    ):
        evidence["has_login_wall"] = True

    return evidence


def classify_and_validate_destination(
    url: str,
    company: str = "",
    job_title: str = "",
    search_keyword: str = "",
    job_listing_url: str = "",
    session: Optional[requests.Session] = None,
    html_override: Optional[str] = None,
    fetch_if_needed: bool = False,
) -> Dict[str, Any]:
    """
    Classifies and validates a candidate application URL using structural and page evidence.

    Returns a dictionary containing:
      - application_url_original
      - application_url_final
      - application_url_type (ApplicationDestinationType value)
      - application_url_verified (bool)
      - application_url_validation_reason (str)
      - application_url_redirect_chain (List[str])
      - application_url_job_match (bool)
      - application_url_employer_match (bool)
      - employer_website_url (str)
      - discovered_email (str, if found on destination page)
    """
    orig_url = str(url or "").strip()
    out = {
        "application_url_original": orig_url,
        "application_url_final": orig_url,
        "application_url_type": ApplicationDestinationType.IRRELEVANT_PAGE.value,
        "application_url_verified": False,
        "application_url_validation_reason": "Empty or missing URL",
        "application_url_redirect_chain": [orig_url] if orig_url else [],
        "application_url_job_match": False,
        "application_url_employer_match": False,
        "employer_website_url": "",
        "discovered_email": "",
    }

    if not orig_url or not orig_url.startswith(("http://", "https://")):
        return out

    if "mailto:" in orig_url.lower() or "tel:" in orig_url.lower():
        out["application_url_validation_reason"] = "Non-HTTP protocol (mailto/tel)"
        return out

    if "bewerbungverwalten.html" in orig_url.lower():
        out["application_url_type"] = ApplicationDestinationType.LOGIN_REQUIRED.value
        out["application_url_verified"] = False
        out["application_url_employer_match"] = True
        out["application_url_job_match"] = True
        out["application_url_validation_reason"] = "Arbeitsagentur portal login required (bewerbungVerwalten)"
        return out

    if is_advice_or_generic_page(orig_url):
        out["application_url_type"] = ApplicationDestinationType.IRRELEVANT_PAGE.value
        out["application_url_validation_reason"] = f"Advice or non-application page: {orig_url}"
        return out

    final_url = orig_url
    html = html_override or ""
    status_code = 200

    # Follow redirects / fetch page if requested and session provided
    if fetch_if_needed and session is not None and html_override is None:
        try:
            resp = session.get(orig_url, timeout=6, allow_redirects=True)
            status_code = resp.status_code
            chain = [r.url for r in resp.history] + [resp.url]
            out["application_url_redirect_chain"] = chain
            final_url = resp.url or orig_url
            out["application_url_final"] = final_url
            if status_code == 200:
                html = resp.text or ""
            elif status_code in (404, 410) or status_code >= 500:
                out["application_url_type"] = ApplicationDestinationType.BROKEN_URL.value
                out["application_url_validation_reason"] = f"HTTP {status_code} on destination URL"
                return out
            elif status_code in (401, 403, 406, 429):
                out["application_url_type"] = ApplicationDestinationType.REQUIRES_MANUAL_REVIEW.value
                out["application_url_validation_reason"] = f"HTTP {status_code} access restriction requires browser/manual review"
                return out
        except Exception as exc:
            out["application_url_type"] = ApplicationDestinationType.BROKEN_URL.value
            out["application_url_validation_reason"] = f"Connection/request failed: {type(exc).__name__}"
            return out

    u_low = final_url.lower()
    parsed = urlparse(final_url)
    netloc = (parsed.netloc or "").lower()
    path = (parsed.path or "").strip("/").lower()

    # Check if URL is identical to an ordinary portal listing URL without an apply endpoint
    if is_portal_domain(final_url):
        is_portal_apply = any(
            p in u_low
            for p in (
                "ausbildung.de/direktbewerbung",
                "/bewerben",
                "/schnellbewerbung",
                "bewerbungverwalten.html",
            )
        )
        # Partner deep links (e.g. yourfirm.de/job/detail/..., stellenanzeigen.de/job/detail/..., hogapage.de/jobs/..., kalaydo.de/jobs/..., heyjobs.co/de-de/jobs/...)
        is_partner_job_detail = any(
            dom in netloc for dom in ("yourfirm.de", "stellenanzeigen.de", "hogapage.de", "kalaydo.de", "heyjobs.co", "hotelcareer.de", "jobs4us.de")
        ) and len([s for s in path.split("/") if s]) >= 2

        if is_portal_apply:
            if "bewerbungverwalten.html" in u_low:
                out["application_url_type"] = ApplicationDestinationType.LOGIN_REQUIRED.value
                out["application_url_verified"] = False
                out["application_url_employer_match"] = True
                out["application_url_job_match"] = True
                out["application_url_validation_reason"] = "Arbeitsagentur portal login required (bewerbungVerwalten)"
                return out
            out["application_url_type"] = ApplicationDestinationType.DIRECT_APPLICATION_FORM.value
            out["application_url_verified"] = True
            out["application_url_employer_match"] = True
            out["application_url_job_match"] = True
            out["application_url_validation_reason"] = "Portal direct application endpoint"
            return out

        if is_partner_job_detail:
            out["application_url_type"] = ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE.value
            out["application_url_verified"] = True
            out["application_url_employer_match"] = True
            out["application_url_job_match"] = True
            out["application_url_validation_reason"] = "Verified partner job-specific application page"
            return out

        out["application_url_type"] = ApplicationDestinationType.RECRUITMENT_PORTAL.value
        out["application_url_verified"] = False
        out["application_url_validation_reason"] = f"Portal listing or root URL ({netloc}) is not a direct application destination"
        return out

    # Check if structural generic employer homepage or generic careers overview page
    is_generic, generic_type = _classify_structural_generic_homepage(final_url)
    emp_match = _check_employer_match_in_destination(final_url, html, company)
    job_match = _check_job_match_in_destination(final_url, html, job_title, search_keyword)
    out["application_url_employer_match"] = emp_match
    out["application_url_job_match"] = job_match

    if is_generic:
        evidence = _inspect_html_for_application_evidence(html, final_url) if html else {}
        if not evidence.get("has_application_form"):
            out["application_url_type"] = generic_type
            out["application_url_verified"] = False
            out["employer_website_url"] = final_url
            out["application_url_validation_reason"] = (
                f"Generic employer {'careers overview' if generic_type == ApplicationDestinationType.EMPLOYER_CAREERS_PAGE.value else 'homepage'} "
                f"without job-specific application form ({final_url})"
            )
            return out

    # Check known ATS signatures
    is_known_ats = any(sig in u_low for sig in KNOWN_ATS_SIGNATURES)
    if is_known_ats:
        # Must still have a job-specific path or query and not be a bare ATS root
        if not path and not parsed.query:
            out["application_url_type"] = ApplicationDestinationType.EMPLOYER_CAREERS_PAGE.value
            out["application_url_verified"] = False
            out["application_url_validation_reason"] = "Bare ATS root without job path or identifier"
            return out

        # Check for login-gated ATS registration (e.g. Deutsche Bahn Register?jobId=...)
        if "/register" in path and "jobid=" in u_low:
            out["application_url_type"] = ApplicationDestinationType.DIRECT_APPLICATION_FORM.value
            out["application_url_verified"] = True
            out["application_url_job_match"] = True
            out["application_url_employer_match"] = True
            out["application_url_validation_reason"] = "Verified ATS job-specific registration/application workflow"
            return out

        out["application_url_type"] = ApplicationDestinationType.DIRECT_APPLICATION_FORM.value
        out["application_url_verified"] = True
        out["application_url_job_match"] = True
        out["application_url_employer_match"] = True
        out["application_url_validation_reason"] = f"Verified external ATS application endpoint ({netloc})"
        return out

    # Non-ATS employer URL with a deep path or query
    evidence = _inspect_html_for_application_evidence(html, final_url) if html else {}

    # Check explicit form paths (e.g. /kurzbewerbung/, /bewerbungsformular, /apply, /bewerbung/stelle-...)
    has_explicit_form_path = any(
        fp in u_low
        for fp in (
            "/kurzbewerbung",
            "/bewerbungsformular",
            "/online-bewerbung",
            "/onlinebewerbung",
            "/bewerbung/stelle",
            "/apply",
            "/application",
            "initiativbewerbung",
            "formular",
            "bewerbform",
            "applicationform",
            "bewerbungs-formular",
            "/bewerbung",
            "/schnellbewerbung",
            "/anmeldung",
        )
    )
    if has_explicit_form_path or evidence.get("has_application_form"):
        out["application_url_type"] = ApplicationDestinationType.DIRECT_APPLICATION_FORM.value
        out["application_url_verified"] = True
        out["application_url_validation_reason"] = "Verified employer application form page"
        return out

    # Check if URL is a job-specific employer page (e.g. /jobs/ausbildung-koch-mwd, ?post_type=job_listing&p=1746, /auszubildende-r-koch-m-w-d/, /studium/...)
    has_job_specific_path = (
        job_match
        or evidence.get("has_job_posting_schema")
        or evidence.get("has_apply_button")
        or bool(re.search(r"/(?:jobs?|stellen(?:angebote)?|ausbildung(?:-[a-z0-9]+)?|karriere|offer|vacancies|studium|studienangebote)[/-][a-z0-9_.-]{4,}", u_low))
        or "post_type=job_listing" in u_low
        or "studiumplus" in u_low
        or bool(re.search(r"(?:[?&](?:ac=jobad|ac=apply|job_?id=\d+|id=\d+|ad_?id=\d+|crmid=[a-z0-9]+))", u_low))
        or bool(re.search(r"/(?:anmeldung|registration|apply)/[0-9a-fA-F-]{16,}", u_low))
    )
    if has_job_specific_path:
        out["application_url_type"] = ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE.value
        out["application_url_verified"] = True
        out["application_url_job_match"] = True
        out["application_url_validation_reason"] = "Verified employer job-specific application page"
        return out

    # Otherwise, if it's a general career section without job specificity
    if any(k in u_low for k in ("karriere", "career", "jobs", "ausbildung", "stellen")):
        out["application_url_type"] = ApplicationDestinationType.EMPLOYER_CAREERS_PAGE.value
        out["application_url_verified"] = False
        out["employer_website_url"] = final_url
        out["application_url_validation_reason"] = "Employer careers overview page without specific job match"
        return out

    out["application_url_type"] = ApplicationDestinationType.GENERIC_EMPLOYER_WEBSITE.value
    out["application_url_verified"] = False
    out["employer_website_url"] = final_url
    out["application_url_validation_reason"] = "Generic employer website without verifiable application workflow"
    return out


_EMPLOYER_CRAWL_CACHE: Dict[Tuple[str, Tuple[str, ...]], Dict[str, Any]] = {}
_EMPLOYER_CRAWL_LOCK = threading.Lock()


def follow_generic_employer_website(
    start_url: str,
    company: str = "",
    job_title: str = "",
    search_keyword: str = "",
    session: Optional[requests.Session] = None,
    initial_html: str = "",
    max_requests: int = 4,
) -> Dict[str, Any]:
    """
    Part 1.5 & Part 3.3 Step 5:
    Given a generic employer homepage, careers overview page, or 404 career page on an employer domain:
    1. Searches for relevant pages (Karriere, Ausbildung, Stellenangebote, Jobs, Bewerbung, Offene Stellen).
    2. Searches for links matching the searched occupation / job title (e.g. 'Koch').
    3. Follows up to `max_requests` links (depth <= 2) to locate a job-specific application page, form, or email.
    """
    result = {
        "resolved_application_url": "",
        "resolved_url_type": "",
        "resolved_has_form": False,
        "discovered_email": "",
        "discovered_phone": "",
        "employer_website_url": start_url,
        "diagnostic_reason": "",
    }
    if not start_url or not start_url.startswith(("http://", "https://")) or is_portal_domain(start_url):
        return result

    sess = session or requests.Session()
    visited: Set[str] = set()
    req_count = 0

    # Determine core occupation keywords to match links (e.g. "koch", "fachinformatiker")
    target_text = f"{job_title or ''} {search_keyword or ''}".lower()
    occ_keywords: List[str] = []
    for kw in ("koch", "koechin", "köchin", "küche", "kueche", "fachinformatik", "informatik",
               "kaufmann", "kauffrau", "elektronik", "mechatronik", "pflege", "bäcker", "baecker",
               "erzieher", "erzieherin", "pädagog", "paedagog"):
        if kw in target_text:
            occ_keywords.append(kw)

    base_parsed = urlparse(start_url)
    base_domain = extract_registrable_domain(start_url)
    use_crawl_cache = bool(base_domain and not initial_html and isinstance(sess, requests.Session))
    cache_key = (base_domain, tuple(sorted(occ_keywords)))
    if use_crawl_cache:
        with _EMPLOYER_CRAWL_LOCK:
            cached_crawl = _EMPLOYER_CRAWL_CACHE.get(cache_key)
            if cached_crawl is not None:
                out_cached = dict(cached_crawl)
                out_cached["employer_website_url"] = start_url
                return out_cached

    def _cache_and_return(res_dict: Dict[str, Any]) -> Dict[str, Any]:
        if use_crawl_cache:
            with _EMPLOYER_CRAWL_LOCK:
                if len(_EMPLOYER_CRAWL_CACHE) > 1000:
                    _EMPLOYER_CRAWL_CACHE.clear()
                _EMPLOYER_CRAWL_CACHE[cache_key] = dict(res_dict)
        return res_dict

    def fetch_page(u: str) -> Tuple[int, str, str]:
        nonlocal req_count
        if req_count >= max_requests or u in visited:
            return 0, u, ""
        visited.add(u)
        req_count += 1
        try:
            r = sess.get(u, timeout=5, allow_redirects=True)
            return r.status_code, (r.url or u), (r.text or "")
        except Exception:
            return 0, u, ""

    # Step 1: Inspect initial page (or fetch it if initial_html not provided)
    if initial_html:
        visited.add(start_url)
        status_0, final_0, html_0 = 200, start_url, initial_html
    else:
        status_0, final_0, html_0 = fetch_page(start_url)

    if status_0 in (401, 403, 406, 429):
        result["manual_review_required"] = True
        result["diagnostic_reason"] = f"Employer career portal returned HTTP {status_0} (requires browser/manual review)"
        return result

    # Even if status_0 is 404 (like Schloss Wackerbarth /jobs-karriere/ausbildung/koch),
    # custom 404 pages on employer sites contain the updated navigation links (/jobs-und-karriere/ausbildung)!
    if not html_0 and status_0 != 200:
        # Try root homepage as fallback if deep link failed
        root_url = f"{base_parsed.scheme}://{base_parsed.netloc}/"
        if root_url != start_url:
            status_0, final_0, html_0 = fetch_page(root_url)
            if status_0 in (401, 403, 406, 429):
                result["manual_review_required"] = True
                result["diagnostic_reason"] = f"Employer website returned HTTP {status_0} (requires browser/manual review)"
                return result

    if not html_0:
        result["diagnostic_reason"] = "Redirect target unavailable"
        return result

    # Check if Softgarden JSON feed exists on this host (e.g. jobs.umg-gastronomie.de/jobs.feed.json)
    if "/jobs.feed.json" in html_0:
        feed_url = urljoin(final_0, "/jobs.feed.json")
        st_f, _, feed_txt = fetch_page(feed_url)
        if st_f == 200 and feed_txt:
            try:
                feed_data = json.loads(feed_txt)
                jobs_list = feed_data if isinstance(feed_data, list) else feed_data.get("jobs", []) or feed_data.get("data", [])
                for j_item in jobs_list:
                    if isinstance(j_item, dict):
                        j_t = str(j_item.get("title") or j_item.get("name") or "").lower()
                        j_u = str(j_item.get("url") or j_item.get("applyUrl") or "").strip()
                        if j_u and (not occ_keywords or any(k in j_t or k in j_u.lower() for k in occ_keywords)):
                            result["resolved_application_url"] = urljoin(final_0, j_u)
                            result["resolved_url_type"] = ApplicationDestinationType.JOB_SPECIFIC_APPLICATION_PAGE.value
                            result["resolved_has_form"] = True
                            result["diagnostic_reason"] = "Resolved job-specific URL via employer job feed"
                            return result
            except Exception:
                pass

    def score_candidate_link(href: str, anchor_text: str) -> int:
        full_u = urljoin(final_0, href)
        u_l = full_u.lower()
        t_l = (anchor_text or "").lower()
        comb = f"{u_l} {t_l}"

        if any(bad in u_l for bad in (".pdf", ".jpg", ".png", ".zip", "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "datenschutz", "agb")):
            return -1
        cand_dom = extract_registrable_domain(full_u)
        is_ats = any(sig in u_l for sig in KNOWN_ATS_SIGNATURES)
        if cand_dom != base_domain and not is_ats:
            return -1

        score = 0
        # Highest priority: matches the specific occupation (e.g. "/ausbildung/koch" or "Koch (m/w/d)")
        if occ_keywords and any(k in comb for k in occ_keywords):
            score += 50
        if is_ats:
            score += 40
        if any(k in comb for k in ("kurzbewerbung", "bewerbungsformular", "online-bewerbung", "jetzt bewerben")):
            score += 35
        if any(k in comb for k in ("ausbildung", "azubi", "lehrstelle")):
            score += 25
        if any(k in comb for k in ("stellenangebote", "offene-stellen", "offene stellen", "jobsuche", "vacancies")):
            score += 20
        if any(k in comb for k in ("karriere", "jobs", "bewerbung", "career")):
            score += 15
        return score

    def collect_ranked_links(page_html: str, page_url: str) -> List[str]:
        soup = BeautifulSoup(page_html, "html.parser")
        scored: List[Tuple[int, str]] = []
        seen_u: Set[str] = set()
        for a in soup.find_all("a", href=True):
            h = (a.get("href") or "").strip()
            if not h or h.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            full_h = urljoin(page_url, h)
            if full_h in visited or full_h in seen_u:
                continue
            sc = score_candidate_link(full_h, a.get_text(" ", strip=True))
            if sc > 0:
                seen_u.add(full_h)
                scored.append((sc, full_h))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [u for _, u in scored]

    # Collect hop-1 candidate links from initial page
    hop1_links = collect_ranked_links(html_0, final_0)

    # Also check if initial page itself has emails
    from services.contamination_detector import is_email_compatible_with_employer
    for em in extract_all_emails_including_obfuscated(html_0):
        ok_e, _ = is_email_compatible_with_employer(em, company, employer_website=final_0)
        if ok_e and not result["discovered_email"]:
            result["discovered_email"] = em

    hop2_queue: List[str] = []
    for cand_url in hop1_links[:3]:
        if req_count >= max_requests:
            break
        st, fin_u, sub_html = fetch_page(cand_url)
        if st != 200 or not sub_html:
            continue

        # Extract any valid emails (including TYPO3 data-mailto-token!) on this career/job page
        for em in extract_all_emails_including_obfuscated(sub_html):
            ok_e, _ = is_email_compatible_with_employer(em, company, employer_website=fin_u)
            if ok_e:
                # Prioritize emails found on a job/career subpage over generic root emails
                result["discovered_email"] = em
                break

        # Validate if this subpage is a verified job-specific application page or form
        cls_res = classify_and_validate_destination(
            fin_u,
            company=company,
            job_title=job_title,
            search_keyword=search_keyword,
            html_override=sub_html,
            fetch_if_needed=False,
        )
        if cls_res["application_url_verified"]:
            result["resolved_application_url"] = fin_u
            result["resolved_url_type"] = cls_res["application_url_type"]
            result["resolved_has_form"] = (
                cls_res["application_url_type"] == ApplicationDestinationType.DIRECT_APPLICATION_FORM.value
            )
            result["diagnostic_reason"] = f"Resolved via employer career crawl: {fin_u}"
            return _cache_and_return(result)

        # Collect hop-2 links (e.g. /jobs-und-karriere/ausbildung -> /jobs-und-karriere/ausbildung/koch)
        for h2 in collect_ranked_links(sub_html, fin_u)[:2]:
            if h2 not in hop2_queue:
                hop2_queue.append(h2)

    # Check hop-2 links if we still have budget and haven't resolved a job-specific URL
    for cand_url2 in hop2_queue:
        if req_count >= max_requests:
            break
        st2, fin_u2, sub_html2 = fetch_page(cand_url2)
        if st2 != 200 or not sub_html2:
            continue

        for em in extract_all_emails_including_obfuscated(sub_html2):
            ok_e, _ = is_email_compatible_with_employer(em, company, employer_website=fin_u2)
            if ok_e:
                result["discovered_email"] = em
                break

        cls_res2 = classify_and_validate_destination(
            fin_u2,
            company=company,
            job_title=job_title,
            search_keyword=search_keyword,
            html_override=sub_html2,
            fetch_if_needed=False,
        )
        if cls_res2["application_url_verified"]:
            result["resolved_application_url"] = fin_u2
            result["resolved_url_type"] = cls_res2["application_url_type"]
            result["resolved_has_form"] = (
                cls_res2["application_url_type"] == ApplicationDestinationType.DIRECT_APPLICATION_FORM.value
            )
            result["diagnostic_reason"] = f"Resolved via hop-2 employer career crawl: {fin_u2}"
            return _cache_and_return(result)

    if hop1_links:
        result["diagnostic_reason"] = "Employer careers page found, job not found"
    else:
        result["diagnostic_reason"] = "No application method exposed on employer website"
    return _cache_and_return(result)
