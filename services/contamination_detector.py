"""
Contact Provenance & Cross-Employer Contamination Detection for JobScout.

Responsibilities:
1. Record and validate provenance for every extracted contact field:
   - email (email_source_url, email_source_section, email_verified)
   - direct_application_url (application_url_source, application_url_verified)
   - form_link (form_link_source, form_link_verified)
   - phone (phone_source, phone_verified)
   - contact_person (contact_person_source, contact_person_verified)
   - validation_status & validation_reason
2. Keep raw candidates separate from validated output fields.
3. Classify extraction status into accurate semantic states:
   - verified_email
   - verified_application_form
   - verified_application_link
   - no_contact_found
   - manual_review_required
   - extraction_failed
   (alongside extraction_completed: bool)
4. Detect and eliminate cross-employer contact contamination across batch results
   before saving or exporting to Excel.
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from services.data_validator import (
    GENERIC_PORTAL_ROOTS,
    is_advice_or_generic_page,
    sanitize_contact_person,
    validate_application_url,
    validate_form_link,
    validate_phone_number,
)
from services.employer_cache import (
    INVALID_COMPANY_NAMES,
    PORTAL_DOMAINS,
    SHORTENER_DOMAINS,
    is_portal_domain,
    is_shortener_domain,
    normalize_company_identity,
)

logger = logging.getLogger(__name__)

# Educational institutions / study-advisor domains that advertise on youth portals
# Their emails are valid ONLY when the job's employer is actually that institution.
EDUCATIONAL_ADVISOR_DOMAINS = {
    "macromedia.de": ("macromedia",),
    "iu.org": ("iu ", "internationale hochschule", "iu hochschule"),
    "iu-fernstudium.de": ("iu ", "internationale hochschule"),
    "sae.edu": ("sae ", "sae institute"),
    "fom.de": ("fom ", "fom hochschule"),
    "wb-fernstudium.de": ("wilhelm büchner", "wb fernstudium"),
    "ibb.com": ("ibb ", "institut für berufliche bildung"),
    "wbs-training.de": ("wbs ", "wbs training"),
    "gfnbildungszentrum.de": ("gfn ",),
}

# Known shared recruitment agencies or corporate group domains where multiple subsidiary names
# legitimately share a central recruiting contact when verified on the job page itself.
KNOWN_CORPORATE_GROUP_DOMAINS = {
    "deutschebahn.com": ("db ", "deutsche bahn"),
    "telekom.de": ("telekom", "t-systems"),
    "rewe-group.com": ("rewe", "penny", "toom"),
    "edeka.de": ("edeka", "netto"),
    "schwarz-gruppe.de": ("lidl", "kaufland", "schwarz"),
    "vinci-energies.de": ("vinci", "actemium", "axians", "omexom", "ske ", "building solutions"),
    "gauselmann.de": ("gauselmann", "merkur", "adp merkur", "schloss benkhausen"),
    "gauselmann.softgarden.io": ("gauselmann", "merkur", "adp merkur", "schloss benkhausen"),
    "merkur.com": ("gauselmann", "merkur", "adp merkur", "schloss benkhausen"),
}

# Portal support / hotline phone numbers that must never be exported as employer phones
PORTAL_SUPPORT_PHONES = {
    "+498941614100",   # Azubiyo / Funke Works GmbH Munich support
    "+495741301800",   # AUBI-plus GmbH Hüllhorst support
    "+49234971530",    # Ausbildung.de / Territory / Funke Bochum support
    "+498004555500",   # Bundesagentur für Arbeit general hotline
    "+498004555520",   # Bundesagentur für Arbeit employer hotline
}

EMAIL_FORMAT_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_employer_group_key(company: str) -> str:
    """
    Produces a normalized corporate group key so subsidiaries of the same company
    (e.g., 'steute Technologies GmbH & Co. KG' and 'steute Technologies') match,
    while unrelated employers remain distinct.
    """
    c = normalize_company_identity(company)
    if not c:
        return ""
    # Check known corporate groups
    for group_key, aliases in KNOWN_CORPORATE_GROUP_DOMAINS.items():
        if any(alias in c for alias in aliases):
            return f"group:{group_key}"
    # Strip common legal forms and punctuation
    legal_pattern = r"\b(gmbh|ag|kg|co|se|ohg|gbr|mbh|kgaa|e\.?\s*v\.?|stiftung|holding|gruppe|group|deutschland|international|inc|ltd)\b"
    cleaned = re.sub(legal_pattern, " ", c, flags=re.IGNORECASE)
    tokens = [t for t in re.split(r"[^a-z0-9äöüß]+", cleaned) if len(t) >= 2]
    if not tokens:
        return c
    # Use the first 2 significant tokens as the employer root identity
    return " ".join(tokens[:2])


def is_email_compatible_with_employer(email: str, company: str, employer_website: str = "") -> Tuple[bool, str]:
    """
    Verifies that an email address is valid and not an educational-advisor or portal address
    misassigned to an unrelated employer.
    """
    clean_email = str(email or "").strip().lower()
    if not clean_email or not EMAIL_FORMAT_RE.match(clean_email):
        return False, "Invalid email format"

    domain = clean_email.split("@")[-1].strip()
    if is_portal_domain(domain):
        return False, f"Portal infrastructure email domain '{domain}' cannot be an employer email"

    if any(bad in clean_email for bad in ("example.", "sentry.", "wix.", "noreply@", "no-reply@", "donotreply@", "datenschutz@")):
        if not clean_email.startswith(("bewerbung@", "karriere@", "personal@", "jobs@", "hr@", "ausbildung@")):
            return False, f"Non-application system/privacy address: {clean_email}"

    comp_lower = str(company or "").strip().lower()
    for edu_domain, allowed_keywords in EDUCATIONAL_ADVISOR_DOMAINS.items():
        if domain == edu_domain or domain.endswith("." + edu_domain):
            if not comp_lower or comp_lower in INVALID_COMPANY_NAMES:
                return False, f"Educational advisor email '{clean_email}' on job with unknown employer '{company}'"
            if not any(kw in comp_lower for kw in allowed_keywords):
                return False, (
                    f"Educational advisor email '{clean_email}' ({edu_domain}) does not belong to employer '{company}'"
                )

    return True, ""


def is_url_compatible_with_job(url: str, company: str = "", job_listing_url: str = "") -> Tuple[bool, str]:
    """
    Verifies that an application URL or form link is a genuine job/employer destination
    and not a generic portal advice page, educational material page, report-abuse form,
    or naked job-board homepage.
    """
    raw = str(url or "").strip()
    if not raw:
        return False, "Empty URL"

    ok, clean_url, reason = validate_application_url(raw, job_listing_url=job_listing_url)
    if not ok:
        return False, reason

    u_lower = clean_url.lower()
    parsed = urlparse(u_lower)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    # Reject Azubiyo/portal non-application paths
    bad_portal_subpaths = (
        "/unterrichtsmaterial",
        "/arbeitshefte",
        "/kopiervorlagen",
        "/formular-zur-meldung",
        "/berufswahltest",
        "/welcher-beruf-passt-zu-mir",
        "/azubi-wissen",
        "/schuelerrabatte",
        "/arbeitgeber/kontakt",
        "/arbeitgeber/stellen-schalten",
        "/arbeitgeber/mediadaten",
        "/stellenmarkt",
        "/suchmaschine",
    )
    if any(bp in path for bp in bad_portal_subpaths):
        return False, f"Non-application portal/educational/navigation path: {clean_url}"

    # Reject naked portal roots or generic partner roots (e.g. https://jobs.hogapage.de, https://www.stellenanzeigen.de)
    clean_netloc = netloc[4:] if netloc.startswith("www.") else netloc
    if netloc in GENERIC_PORTAL_ROOTS or clean_netloc in PORTAL_DOMAINS:
        if not path or path in ("/jobs", "/de-de/jobs", "/stellenangebote", "/stellen", "/jobsuche", "/ausbildung"):
            return False, f"Generic portal root '{netloc}{path}' is not a specific job application URL"

    # Reject bewerbung2go and similar template/advice sites
    if "bewerbung2go.de" in netloc or "funkeworks.de" in netloc:
        return False, f"Portal footer/template link '{netloc}' is not an employer application URL"

    return True, ""


def classify_extraction_outcome(record: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Determines the canonical `extraction_status` and `extraction_completed` boolean
    distinguishing technical completion from contact validity:
      - verified_email
      - verified_application_form
      - verified_application_link
      - no_contact_found
      - manual_review_required
      - extraction_failed
    """
    raw_status = str(record.get("extraction_status") or "").strip().lower()
    if raw_status.startswith("error") or raw_status in ("failed", "extraction_failed", "timed_out"):
        return "extraction_failed", False

    if (
        record.get("manual_review_required")
        or raw_status in ("manual_required", "review_required", "manual_review_required", "captcha_restricted")
        or record.get("validation_status") == "rejected_contamination"
    ):
        # If despite contamination rejection on one field, another verified channel exists, check it
        has_verified_email = bool(record.get("email") and "@" in str(record.get("email")) and record.get("email_verified", True))
        has_verified_form = bool(record.get("has_form") and (record.get("form_link") or record.get("direct_application_url")))
        has_verified_link = bool(record.get("direct_application_url") and not has_verified_form)
        if not (has_verified_email or has_verified_form or has_verified_link):
            return "manual_review_required", True

    email_val = str(record.get("email") or "").strip()
    has_email = bool(email_val and "@" in email_val and not email_val.lower().startswith("error"))
    has_form = bool(record.get("has_form") and (record.get("form_link") or record.get("direct_application_url")))
    has_link = bool(record.get("direct_application_url") and not has_form)

    if has_email:
        return "verified_email", True
    if has_form:
        return "verified_application_form", True
    if has_link:
        return "verified_application_link", True

    return "no_contact_found", True


def attach_contact_provenance(
    record: Dict[str, Any],
    *,
    source_url: str = "",
    section: str = "",
    extraction_method: str = "",
    verified: Optional[bool] = None,
    email_source_section: str = "",
    email_verified: Optional[bool] = None,
    application_url_source: str = "",
    application_url_verified: Optional[bool] = None,
    form_link_source: str = "",
    form_link_verified: Optional[bool] = None,
    phone_source: str = "",
    phone_verified: Optional[bool] = None,
    contact_person_source: str = "",
    contact_person_verified: Optional[bool] = None,
    validation_status: str = "",
    validation_reason: str = "",
) -> Dict[str, Any]:
    """
    Attaches and validates structured provenance metadata for all contact fields on a job record.
    Stores raw candidates separately from validated output fields.
    """
    if not isinstance(record, dict):
        return record

    if extraction_method and not record.get("extraction_method"):
        record["extraction_method"] = extraction_method
    if section:
        email_source_section = email_source_section or section
        application_url_source = application_url_source or section
        form_link_source = form_link_source or section
        phone_source = phone_source or section
        contact_person_source = contact_person_source or section
    if verified is not None:
        if email_verified is None:
            email_verified = verified
        if application_url_verified is None:
            application_url_verified = verified
        if form_link_verified is None:
            form_link_verified = verified
        if phone_verified is None:
            phone_verified = verified
        if contact_person_verified is None:
            contact_person_verified = verified

    company = str(record.get("company") or record.get("firma") or "").strip()
    listing_url = str(source_url or record.get("job_listing_url") or record.get("url") or "").strip()

    # Preserve raw candidates before validation
    raw_candidates = dict(record.get("raw_candidates") or {})
    for field in ("email", "phone", "contact_person", "direct_application_url", "form_link"):
        val = record.get(field)
        if val and field not in raw_candidates:
            raw_candidates[field] = val
    record["raw_candidates"] = raw_candidates

    reasons: List[str] = []
    if validation_reason:
        reasons.append(validation_reason)

    # 1. Validate email + provenance
    email_val = str(record.get("email") or "").strip().lower()
    if email_val:
        email_ok, email_err = is_email_compatible_with_employer(email_val, company)
        if not email_ok:
            record["email"] = ""
            record["email_extracted"] = False
            record["email_verified"] = False
            reasons.append(email_err)
        else:
            record["email"] = email_val
            record["email_extracted"] = True
            record["email_verified"] = True if email_verified is None else bool(email_verified)
            record["email_source_url"] = record.get("email_source_url") or listing_url
            record["email_source_section"] = (
                email_source_section
                or record.get("email_source_section")
                or ("job_detail_page" if record.get("extraction_method") != "cache" else "verified_employer_cache")
            )
    else:
        record["email"] = ""
        record["email_extracted"] = False
        record["email_verified"] = False
        record.setdefault("email_source_url", "")
        record.setdefault("email_source_section", "")

    # 2. Validate phone + provenance
    phone_val = str(record.get("phone") or "").strip()
    if phone_val:
        p_ok, clean_p, p_err = validate_phone_number(phone_val)
        if not p_ok or clean_p in PORTAL_SUPPORT_PHONES:
            record["phone"] = ""
            record["phone_verified"] = False
            if clean_p in PORTAL_SUPPORT_PHONES:
                reasons.append(f"Rejected portal hotline phone number: {clean_p}")
        else:
            record["phone"] = clean_p
            record["phone_verified"] = True if phone_verified is None else bool(phone_verified)
            record["phone_source"] = phone_source or record.get("phone_source") or listing_url
    else:
        record["phone"] = ""
        record["phone_verified"] = False
        record.setdefault("phone_source", "")

    # 3. Validate contact person + provenance
    cp_val = str(record.get("contact_person") or record.get("arbeitsgeber") or "").strip()
    if cp_val:
        cp_ok, clean_cp, _ = sanitize_contact_person(cp_val)
        if not cp_ok:
            record["contact_person"] = ""
            record["arbeitsgeber"] = ""
            record["contact_person_verified"] = False
        else:
            record["contact_person"] = clean_cp
            record["arbeitsgeber"] = clean_cp
            record["contact_person_verified"] = True if contact_person_verified is None else bool(contact_person_verified)
            record["contact_person_source"] = contact_person_source or record.get("contact_person_source") or listing_url
    else:
        record["contact_person"] = ""
        record["arbeitsgeber"] = ""
        record["contact_person_verified"] = False
        record.setdefault("contact_person_source", "")

    # 4. Validate direct_application_url & form_link + provenance
    direct_val = str(record.get("direct_application_url") or "").strip()
    if direct_val:
        u_ok, u_err = is_url_compatible_with_job(direct_val, company=company, job_listing_url=listing_url)
        if not u_ok:
            record["direct_application_url"] = ""
            record["application_url_verified"] = False
            reasons.append(u_err)
        else:
            record["application_url_verified"] = True if application_url_verified is None else bool(application_url_verified)
            record["application_url_source"] = application_url_source or record.get("application_url_source") or listing_url
    else:
        record["application_url_verified"] = False
        record.setdefault("application_url_source", "")

    form_val = str(record.get("form_link") or "").strip()
    if form_val:
        f_ok, clean_f, f_err = validate_form_link(form_val, has_form=bool(record.get("has_form", True)))
        u_ok, u_err = is_url_compatible_with_job(form_val, company=company, job_listing_url=listing_url)
        if not (f_ok and u_ok):
            record["form_link"] = ""
            record["has_form"] = False
            record["form_link_verified"] = False
            reasons.append(f_err or u_err)
        else:
            record["form_link"] = clean_f
            record["form_link_verified"] = True if form_link_verified is None else bool(form_link_verified)
            record["form_link_source"] = form_link_source or record.get("form_link_source") or listing_url
    else:
        record["form_link_verified"] = False
        record.setdefault("form_link_source", "")

    # Determine overall validation_status
    has_any_verified = any(
        bool(record.get(k))
        for k in ("email_verified", "application_url_verified", "form_link_verified", "phone_verified", "contact_person_verified")
    )
    if validation_status:
        record["validation_status"] = validation_status
    elif has_any_verified:
        record["validation_status"] = "verified"
    elif reasons:
        record["validation_status"] = "rejected_invalid"
    else:
        record["validation_status"] = record.get("validation_status") or "no_contact"

    record["validation_reason"] = "; ".join(r for r in reasons if r) or record.get("validation_reason") or ""

    # Structured provenance summary
    record["contact_provenance"] = {
        "email_source_url": record.get("email_source_url", ""),
        "email_source_section": record.get("email_source_section", ""),
        "email_verified": bool(record.get("email_verified")),
        "application_url_source": record.get("application_url_source", ""),
        "application_url_verified": bool(record.get("application_url_verified")),
        "form_link_source": record.get("form_link_source", ""),
        "form_link_verified": bool(record.get("form_link_verified")),
        "phone_source": record.get("phone_source", ""),
        "phone_verified": bool(record.get("phone_verified")),
        "contact_person_source": record.get("contact_person_source", ""),
        "contact_person_verified": bool(record.get("contact_person_verified")),
        "validation_status": record.get("validation_status", ""),
        "validation_reason": record.get("validation_reason", ""),
    }

    status_label, is_completed = classify_extraction_outcome(record)
    record["extraction_status"] = status_label
    record["extraction_completed"] = is_completed
    return record


def _does_contact_belong_to_employer(field: str, value: str, company: str) -> bool:
    """
    Checks whether a contact value (email or URL) has explicit lexical/domain affinity
    with the given employer name (used to identify the true owner when a value was
    contaminated across multiple employers).
    """
    comp_norm = normalize_company_identity(company)
    if not comp_norm:
        return False
    val_lower = str(value or "").strip().lower()
    if "@" in val_lower:
        domain = val_lower.split("@")[-1].split(".")[0]
    else:
        parsed = urlparse(val_lower)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        domain = host.split(".")[0] if host else ""

    legal = {"gmbh", "ag", "kg", "co", "se", "ohg", "gbr", "mbh", "kgaa", "holding", "gruppe", "group", "jobs", "karriere", "careers", "career"}
    comp_tokens = [t for t in re.split(r"[^a-z0-9äöüß]+", comp_norm) if len(t) >= 3 and t not in legal]
    for tok in comp_tokens:
        tok_ascii = tok.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        if tok in val_lower or tok_ascii in val_lower or (domain and len(domain) >= 3 and (domain in tok or domain in tok_ascii)):
            return True
    return False


def detect_and_clean_cross_employer_contamination(
    records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Audits a batch of extracted job records before export or persistence.
    Groups records by:
      - email
      - direct_application_url
      - form_link
      - phone
      - contact_person
    Detects unverified repetitions across distinct unrelated employers and strips
    contaminated values so they are NEVER exported to Excel.

    Returns:
      (cleaned_records, audit_report)
    """
    if not records:
        return [], {"total_records": 0, "contaminated_records_cleaned": 0, "flagged_values": {}}

    cleaned: List[Dict[str, Any]] = [attach_contact_provenance(dict(r)) for r in records if isinstance(r, dict)]

    # Group indices by field value and employer group key
    fields_to_audit = ("email", "direct_application_url", "form_link", "phone", "contact_person")
    value_to_indices: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    value_to_employers: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for idx, rec in enumerate(cleaned):
        emp_group = normalize_employer_group_key(rec.get("company") or rec.get("firma") or "") or f"unknown_emp_{idx}"
        for field in fields_to_audit:
            val = str(rec.get(field) or "").strip()
            if not val:
                continue
            norm_val = val.lower()
            value_to_indices[(field, norm_val)].append(idx)
            value_to_employers[(field, norm_val)].add(emp_group)

    flagged_values: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    contaminated_indices: Set[int] = set()

    for (field, norm_val), indices in value_to_indices.items():
        distinct_employers = value_to_employers[(field, norm_val)]
        if len(distinct_employers) <= 1:
            continue

        # Check if this is a legitimate shared corporate group or verified per-job recruiting agency
        # A contact shared across 2+ unrelated employers is contaminated UNLESS:
        # 1. Every record has explicit job-page provenance (not from cache, not from generic full-page fallback), AND
        # 2. For URLs: it is NOT a shortened link (short.sg) and NOT a specific job-ID link belonging to another company.
        is_shortener = field in ("direct_application_url", "form_link") and is_shortener_domain(norm_val)

        # Find which indices actually own this contact (by lexical/domain match to employer name)
        owner_indices = [
            i for i in indices
            if _does_contact_belong_to_employer(field, norm_val, cleaned[i].get("company") or "")
        ]

        # Also check if all records were genuinely verified on their own job page without any owner conflict
        all_explicitly_verified_on_job_page = all(
            cleaned[i].get("extraction_method") != "cache"
            and bool(cleaned[i].get(f"{field}_verified" if field != "direct_application_url" else "application_url_verified"))
            and "fallback" not in str(cleaned[i].get("email_source_section") or "").lower()
            for i in indices
        )

        # If one specific employer clearly owns the domain/email (e.g. claudia.guenther@nordwasser.de -> Nordwasser,
        # soliver-group.com -> s.Oliver, dentsplysirona.com -> Dentsply Sirona, macromedia.de -> Macromedia),
        # then any OTHER unrelated employer having that value is 100% contaminated!
        if owner_indices:
            owner_groups = {
                normalize_employer_group_key(cleaned[i].get("company") or "")
                for i in owner_indices
            }
            victims = [
                i for i in indices
                if normalize_employer_group_key(cleaned[i].get("company") or "") not in owner_groups
            ]
        elif is_shortener or len(distinct_employers) >= 3 or not all_explicitly_verified_on_job_page:
            # No employer lexically matches, or it's an unresolved shortener / cached leak across multiple unrelated companies
            victims = list(indices)
        else:
            victims = []

        if victims:
            flagged_values[field].append({
                "value": norm_val,
                "distinct_employers": len(distinct_employers),
                "affected_records": len(victims),
            })
            for v_idx in victims:
                rec = cleaned[v_idx]
                contaminated_indices.add(v_idx)
                reason_msg = (
                    f"Rejected cross-employer contamination on {field}='{norm_val}' "
                    f"(repeated across {len(distinct_employers)} distinct employers)"
                )
                if field == "email":
                    rec["email"] = ""
                    rec["email_extracted"] = False
                    rec["email_verified"] = False
                elif field == "direct_application_url":
                    rec["direct_application_url"] = ""
                    rec["application_url_verified"] = False
                    if rec.get("bewerbung_link") and str(rec.get("bewerbung_link")).strip().lower() == norm_val:
                        rec["bewerbung_link"] = rec.get("job_listing_url") or rec.get("url") or ""
                elif field == "form_link":
                    rec["form_link"] = ""
                    rec["has_form"] = False
                    rec["form_link_verified"] = False
                elif field == "phone":
                    rec["phone"] = ""
                    rec["phone_verified"] = False
                elif field == "contact_person":
                    rec["contact_person"] = ""
                    rec["arbeitsgeber"] = ""
                    rec["contact_person_verified"] = False

                rec["validation_status"] = "rejected_contamination"
                prev_reason = str(rec.get("validation_reason") or "").strip()
                rec["validation_reason"] = f"{prev_reason}; {reason_msg}".lstrip("; ")
                if isinstance(rec.get("contact_provenance"), dict):
                    rec["contact_provenance"]["validation_status"] = "rejected_contamination"
                    rec["contact_provenance"]["validation_reason"] = rec["validation_reason"]

                status_label, is_completed = classify_extraction_outcome(rec)
                rec["extraction_status"] = status_label
                rec["extraction_completed"] = is_completed
                if status_label == "manual_review_required":
                    rec["manual_review_required"] = True
                    rec["manual_review_reason"] = rec["validation_reason"]

    audit_report = {
        "total_records": len(cleaned),
        "contaminated_records_cleaned": len(contaminated_indices),
        "contaminated_rows_cleaned": len(contaminated_indices),
        "flagged_values": dict(flagged_values),
    }
    if contaminated_indices:
        logger.warning(
            "[ContaminationDetector] Cleaned %d contaminated records across batch of %d: %s",
            len(contaminated_indices),
            len(cleaned),
            dict(flagged_values),
        )
    return cleaned, audit_report
