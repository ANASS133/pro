"""
Dynamic Hook & Personalized Salutation Generator for Outreach Letters.
Generates tailored German cover letter opening hooks, salutations, and
closing call-to-actions based on job titles, company context, location, and tech stack.
"""

import re
from typing import Dict, Optional

from .impressum_extractor import ImpressumExtractor


class DynamicHookGenerator:
    """Creates personalized German cover letter hooks and salutations."""

    @classmethod
    def generate_salutation(
        cls,
        ansprechpartner: Optional[str] = None,
        geschaeftsfuehrer: Optional[str] = None,
        anrede_hint: Optional[str] = None,
    ) -> str:
        """
        Generate grammatically correct German salutation.
        Prefers specific recruiter/ansprechpartner, then geschaeftsfuehrer, then formal default.
        """
        target = str(ansprechpartner or "").strip() or str(geschaeftsfuehrer or "").strip()
        if not target:
            if anrede_hint and "herr" in str(anrede_hint).lower():
                return "Sehr geehrter Herr,"
            if anrede_hint and "frau" in str(anrede_hint).lower():
                return "Sehr geehrte Frau,"
            return "Sehr geehrte Damen und Herren,"

        return ImpressumExtractor.generate_salutation(target)

    @classmethod
    def generate_hook(
        cls,
        job_title: str = "",
        company: str = "",
        city: str = "",
        tech: str = "",
    ) -> str:
        """
        Generate dynamic, compelling opening hook in German tailored to company, role, and tech.
        """
        clean_title = re.sub(r"\s+", " ", str(job_title or "")).strip()
        clean_company = re.sub(r"\s+", " ", str(company or "")).strip()
        clean_city = re.sub(r"\s+", " ", str(city or "")).strip()
        clean_tech = re.sub(r"\s+", " ", str(tech or "")).strip()

        tech_clause = f" sowie Ihrem Einsatz von {clean_tech}" if clean_tech else ""

        # 1. When title, company, and city are available
        if clean_title and clean_company and clean_city:
            return (
                f"mit großem Interesse habe ich Ihre Ausschreibung für die Position als {clean_title} "
                f"bei {clean_company} in {clean_city} aufmerksam verfolgt. Da meine fachlichen Qualifikationen{tech_clause} "
                f"und meine Motivation genau zu Ihren Anforderungen passen, möchte ich mich Ihnen gerne vorstellen."
            )

        # 2. When title and city are available
        if clean_title and clean_city:
            return (
                f"mit großer Begeisterung habe ich Ihre aktuelle Stellenausschreibung als {clean_title} "
                f"in {clean_city} gelesen. Mit meinen fundierten Kenntnissen und meiner engagierten Arbeitsweise "
                f"möchte ich Ihr Team tatkräftig unterstützen."
            )

        # 3. When title and company are available
        if clean_title and clean_company:
            return (
                f"mit großem Interesse bewerbe ich mich bei {clean_company} auf die Stelle als {clean_title}. "
                f"Ihre Firmenphilosophie und das beschriebene Aufgabenfeld sprechen mich fachlich wie persönlich außerordentlich an."
            )

        # 4. When only title is available
        if clean_title:
            return (
                f"mit großem Interesse bewerbe ich mich bei Ihnen auf die offene Position als {clean_title}. "
                f"Meine bisherigen Erfahrungen und meine Lernbereitschaft bieten die optimale Grundlage für diese Position."
            )

        # 5. General unsolicited outreach fallback
        loc_str = f" in {clean_city}" if clean_city else ""
        return (
            f"auf der Suche nach einer neuen beruflichen Herausforderung{loc_str} bin ich auf Ihr Unternehmen aufmerksam geworden. "
            f"Gerne möchte ich mich Ihnen mit meinen Fähigkeiten und meinem Engagement initiativ vorstellen."
        )

    @classmethod
    def generate_enrichment(cls, row_data: Dict) -> Dict[str, str]:
        """
        Enrich row data with dynamic placeholders:
        - custom_hook
        - salutation
        - ansprechpartner
        - geschaeftsfuehrer
        - detected_tech
        - primary_tech
        """
        data = row_data or {}

        title = (
            data.get("job_title")
            or data.get("title")
            or data.get("beruf")
            or data.get("stelle")
            or ""
        )
        company = (
            data.get("company")
            or data.get("arbeitsgeber")
            or data.get("arbeitgeber")
            or data.get("firma")
            or ""
        )
        city = (
            data.get("city")
            or data.get("stadt")
            or data.get("ort")
            or data.get("location")
            or ""
        )
        contact = (
            data.get("ansprechpartner")
            or data.get("contact_person")
            or data.get("kontaktperson")
            or ""
        )
        director = (
            data.get("geschaeftsfuehrer")
            or data.get("inhaber")
            or ""
        )
        anrede = data.get("anrede") or ""

        # Tech placeholders
        primary_tech = data.get("primary_tech") or ""
        detected_tech = data.get("detected_tech") or data.get("technologies") or primary_tech
        if isinstance(detected_tech, list):
            detected_tech = ", ".join(detected_tech)

        salutation = cls.generate_salutation(
            ansprechpartner=contact,
            geschaeftsfuehrer=director,
            anrede_hint=anrede,
        )

        hook = cls.generate_hook(
            job_title=title,
            company=company,
            city=city,
            tech=str(primary_tech or detected_tech or ""),
        )

        return {
            "custom_hook": hook,
            "salutation": salutation,
            "ansprechpartner": contact,
            "geschaeftsfuehrer": director,
            "detected_tech": str(detected_tech or ""),
            "primary_tech": str(primary_tech or ""),
        }
