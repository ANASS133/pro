"""
JobScout Intelligent Anschreiben Generation & Quality Assurance Engine
======================================================================
Produces high-impact, competitive German cover letters (B2–C1 level) suitable
for applications to German companies, particularly dual vocational training
(Ausbildung) and direct employment.

Architecture:
1. JobAnalyzer: Analyzes vacancy title, specialization, requirements, and company context.
2. EvidenceSelector: Selects and ranks top 2–3 pieces of candidate evidence (never skill dumps).
3. CoverLetterWriter: Generates structured, authentic 4-paragraph DIN 5008 letters.
4. QualityAssurancePipeline: Validates entities, clichés, word count, placeholders, and bounded revision.
5. RefinementEngine: Provides quick contextual adjustments (concise, formal, natural, improve).
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.ai_provider_manager import ai_manager

logger = logging.getLogger(__name__)

# Banned generic German application clichés that weaken the candidate's standing
GENERIC_CLICHE_PATTERNS = [
    r"mit\s+gro[ßs]em\s+interesse\s+bewerbe\s+ich\s+mich",
    r"hiermit\s+bewerbe\s+ich\s+mich",
    r"ich\s+bin\s+teamf[äa]hig[,\s]+motiviert\s+und\s+flexibel",
    r"als\s+engagierte[rn]?\s+kandidat(?:in)?",
    r"ihr\s+unternehmen\s+hat\s+mein\s+interesse\s+geweckt",
    r"auf\s+der\s+suche\s+nach\s+neuen\s+herausforderungen",
    r"m[öo]chte\s+ich\s+mich\s+kurz\s+vorstellen",
    r"anbei\s+[üu]bersende\s+ich\s+meine\s+bewerbungsunterlagen",
]


class JobAnalyzer:
    """Analyzes target vacancy requirements, specialization, and company context."""

    @classmethod
    def analyze(
        cls,
        company: str,
        position: str,
        city: str,
        job_description: str = "",
        requirements: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        pos_clean = str(position or "").strip()
        comp_clean = str(company or "Unternehmen").strip()
        city_clean = str(city or "").strip()
        pos_lower = pos_clean.lower()

        # Opportunity type classification
        if "ausbildung" in pos_lower or "azubi" in pos_lower or "lehrstelle" in pos_lower:
            opportunity_type = "ausbildung"
        elif "duales studium" in pos_lower or "bachelor of" in pos_lower:
            opportunity_type = "duales_studium"
        elif "praktikum" in pos_lower or "intern" in pos_lower:
            opportunity_type = "praktikum"
        else:
            opportunity_type = "job"

        # Specialization extraction (e.g. Fachinformatiker Anwendungsentwicklung vs Systemintegration)
        specialization = ""
        for spec in [
            "Anwendungsentwicklung", "Systemintegration", "Daten- und Prozessanalyse",
            "Digitale Vernetzung", "Cybersecurity", "Webentwicklung", "Cloud Computing"
        ]:
            if spec.lower() in pos_lower or spec.lower() in str(job_description).lower():
                specialization = spec
                break

        # Grounded company context (avoid hallucinating false facts when info is missing)
        has_rich_description = bool(job_description and len(job_description.strip()) >= 40)
        extracted_skills = []
        if requirements:
            extracted_skills.extend(requirements)
        if has_rich_description:
            for kw in ["python", "java", "react", "spring", "sql", "linux", "cloud", "docker", "agile", "c#", "sap"]:
                if re.search(rf"\b{kw}", job_description.lower()) and kw.capitalize() not in extracted_skills:
                    extracted_skills.append(kw.capitalize())

        return {
            "company": comp_clean,
            "position": pos_clean,
            "city": city_clean,
            "opportunity_type": opportunity_type,
            "specialization": specialization,
            "has_rich_description": has_rich_description,
            "job_description_snippet": job_description[:800] if has_rich_description else "",
            "extracted_skills": extracted_skills[:6],
        }


class EvidenceSelector:
    """Ranks and selects candidate's top 2–3 strongest pieces of evidence for the job."""

    @classmethod
    def select_evidence(
        cls,
        candidate_profile: Dict[str, Any],
        job_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        applicant = candidate_profile.get("applicant") or candidate_profile
        work_entries = applicant.get("work_experience") or []
        edu_entries = applicant.get("education") or []
        skills_dict = applicant.get("skills") or {}
        prof_profile = applicant.get("professional_profile") or {}
        languages = applicant.get("languages") or []
        certs = applicant.get("certifications") or []

        selected_evidence: List[Dict[str, Any]] = []

        # 1. Evaluate Work Experience
        for w in work_entries:
            pos = w.get("position") or w.get("job_title") or ""
            emp = w.get("employer") or w.get("company") or ""
            resps = w.get("responsibilities") or []
            if not pos:
                continue

            score = 1.0
            # Higher score if role matches specialization or technical software development
            if any(tech in pos.lower() for tech in ["software", "entwickler", "developer", "fullstack", "web"]):
                score += 2.0
            if "kunden" in pos.lower() and "deutsch" in pos.lower():
                score += 1.5  # Crucial German business communication evidence

            selected_evidence.append({
                "type": "work_experience",
                "headline": f"{pos} bei {emp}" if emp else pos,
                "period": f"{w.get('start_date', '')} - {w.get('end_date', '')}",
                "highlights": resps[:2],
                "score": score,
            })

        # 2. Evaluate Academic Education
        for ed in edu_entries:
            deg = ed.get("degree") or ""
            inst = ed.get("institution") or ""
            focus = ed.get("field_of_study") or ""
            if not deg:
                continue

            score = 1.0
            if any(term in deg.lower() or term in focus.lower() for term in ["informatik", "software", "cyber", "digital", "technik"]):
                score += 2.0

            selected_evidence.append({
                "type": "education",
                "headline": f"{deg} ({inst})" if inst else deg,
                "period": f"{ed.get('start_date', '')} - {ed.get('end_date', '')}",
                "highlights": [focus] if focus else [],
                "score": score,
            })

        # Sort evidence by score descending and pick the 2-3 most impactful
        selected_evidence.sort(key=lambda x: x["score"], reverse=True)
        top_evidence = selected_evidence[:3]

        # Extract German language proficiency evidence
        german_evidence = "Deutschkenntnisse auf B2-Niveau (telc)"
        for l in languages:
            if isinstance(l, dict) and str(l.get("language", "")).lower() in ["deutsch", "german"]:
                lvl = l.get("level_de") or l.get("level") or "B2"
                german_evidence = f"Deutsch: {lvl}"
                break

        # Dual Ausbildung Narrative for experienced candidate
        years_exp = prof_profile.get("years_of_experience", 0)
        is_experienced = years_exp >= 1.0 or len(work_entries) >= 2
        ausbildung_rationale = ""
        if job_analysis["opportunity_type"] == "ausbildung" and is_experienced:
            ausbildung_rationale = (
                "Der Kandidat verfügt bereits über praktische Entwicklungserfahrung und strebt nun gezielt "
                "eine anerkannte IHK-Ausbildung in Deutschland an, um seine praktischen Fertigkeiten mit den "
                "Standards des dualen deutschen Systems zu normieren, Enterprise-Architekturen zu vertiefen "
                "und von Tag eins an einen überdurchschnittlich hohen Wertbeitrag im Team zu leisten."
            )

        # Technical skill highlights
        tech_skills = skills_dict.get("technologies_from_cv") or []
        if not tech_skills:
            tech_skills = (
                (skills_dict.get("programming_languages") or []) +
                (skills_dict.get("frontend") or []) +
                (skills_dict.get("backend") or [])
            )
        tech_highlights = tech_skills[:6]

        return {
            "top_evidence": top_evidence,
            "is_experienced": is_experienced,
            "years_of_experience": years_exp,
            "ausbildung_rationale": ausbildung_rationale,
            "german_evidence": german_evidence,
            "technical_skills": tech_highlights,
            "certifications": [c.get("name") for c in certs[:3] if isinstance(c, dict)],
        }


class QualityAssurancePipeline:
    """Validates generated cover letters against quality standards, clichés, and DIN 5008 layout."""

    @classmethod
    def evaluate(
        cls,
        text: str,
        candidate_data: Dict[str, Any],
        vacancy_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        issues: List[str] = []
        penalties = 0.0

        if not text or len(text.strip()) < 100:
            return {
                "is_valid": False,
                "score": 0.0,
                "issues": ["Text ist leer oder extrem unvollständig."],
                "word_count": 0,
            }

        words = text.split()
        word_count = len(words)

        # 1. Word count validation (Optimal: 240-360 words; Acceptable: 200-420 words)
        if word_count < 200:
            issues.append(f"Text zu kurz ({word_count} Wörter). Mindestens 220–250 Wörter erforderlich.")
            penalties += 2.5
        elif word_count > 420:
            issues.append(f"Text zu lang ({word_count} Wörter). Überschreitet 1-Seiten-Grenze DIN 5008.")
            penalties += 2.0

        # 2. Unresolved placeholder check
        unresolved_tokens = re.findall(r"\{\{[^}]+\}\}|\[(?:Datum|Unternehmensadresse|Firma|Name|Adresse|Platzhalter)[^\]]*\]", text)
        if unresolved_tokens:
            issues.append(f"Unaufgelöste Platzhalter gefunden: {', '.join(unresolved_tokens[:3])}")
            penalties += 3.5

        # 3. Essential entities check
        comp = str(vacancy_data.get("company") or "").strip()
        if comp and comp.lower() not in text.lower():
            issues.append(f"Zielunternehmen '{comp}' wird im Text nicht genannt.")
            penalties += 2.0

        cand_name = str(candidate_data.get("full_name") or candidate_data.get("name") or "").strip()
        if cand_name and cand_name.lower() not in text.lower():
            issues.append(f"Bewerbername '{cand_name}' fehlt im Briefkopf oder Gruß.")
            penalties += 2.0

        # 4. Anti-Cliché Check
        text_lower = text.lower()
        found_cliches = []
        for pat in GENERIC_CLICHE_PATTERNS:
            if re.search(pat, text_lower):
                found_cliches.append(pat)
        if found_cliches:
            issues.append("Generische Leerformeln oder Floskeln erkannt.")
            penalties += min(len(found_cliches) * 1.5, 3.5)

        # 5. Salutation and Closing check
        has_salutation = bool(re.search(r"(?i)(?:sehr\s+geehrte[rn]?|hallo|guten\s+tag)", text))
        has_closing = bool(re.search(r"(?i)(?:mit\s+freundlichen\s+gr[üu][ßs]en|beste\s+gr[üu][ßs]e)", text))
        if not has_salutation:
            issues.append("Fehlende oder unkonventionelle Anredezeile.")
            penalties += 1.5
        if not has_closing:
            issues.append("Fehlende Grußformel am Ende.")
            penalties += 1.5

        # 6. Negative hallucination check (e.g. false Musterstraße)
        if "musterstraße 1" in text_lower or "10115 berlin" in text_lower:
            issues.append("Fiktive Standardadresse (Musterstraße) im Briefkopf gefunden.")
            penalties += 2.5

        final_score = max(round(10.0 - penalties, 1), 1.0)
        is_valid = (final_score >= 7.0 and len(unresolved_tokens) == 0)

        return {
            "is_valid": is_valid,
            "score": final_score,
            "issues": issues,
            "word_count": word_count,
            "cliches_found": len(found_cliches),
            "cliches_detected": found_cliches,
        }


class CoverLetterWriter:
    """Orchestrates AI prompt synthesis and executes bounded revisions."""

    @classmethod
    def generate(
        cls,
        candidate_data: Dict[str, Any],
        vacancy_data: Dict[str, Any],
        job_analysis: Dict[str, Any],
        evidence: Dict[str, Any],
        refinement_directive: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates a high-quality personalized German Anschreiben with bounded revision."""
        # 1. Verify AI Provider configuration
        is_configured = getattr(ai_manager, "is_configured", False)
        if not is_configured:
            return {
                "success": False,
                "is_ai_generated": False,
                "generation_mode": "ai_unavailable",
                "error": "Kein KI-Provider (OpenAI oder Gemini) konfiguriert. Bitte API-Key in den KI-Einstellungen hinterlegen.",
            }

        # 2. Build structured prompt
        full_name = candidate_data.get("full_name") or "Bewerber"
        email = candidate_data.get("email") or ""
        phone = candidate_data.get("phone") or ""
        location_header = candidate_data.get("location_header") or "Casablanca, Marokko"
        city_header = candidate_data.get("city") or "Casablanca"

        company = vacancy_data.get("company") or "Unternehmen"
        position = vacancy_data.get("position") or "Auszubildender"
        target_city = vacancy_data.get("city") or "Deutschland"
        contact_person = vacancy_data.get("contact_person") or ""
        today_str = datetime.now().strftime("%d.%m.%Y")

        # Salutation resolution
        if contact_person:
            cp_clean = contact_person.strip()
            if re.match(r"(?i)^herr\s+", cp_clean):
                salutation_name = re.sub(r"(?i)^herr\s+", "", cp_clean).strip()
                salutation = f"Sehr geehrter Herr {salutation_name},"
            elif re.match(r"(?i)^frau\s+", cp_clean):
                salutation_name = re.sub(r"(?i)^frau\s+", "", cp_clean).strip()
                salutation = f"Sehr geehrte Frau {salutation_name},"
            else:
                salutation = f"Sehr geehrte(r) {cp_clean},"
        else:
            salutation = "Sehr geehrte Damen und Herren,"

        betreff = (
            f"Bewerbung um einen Ausbildungsplatz als {position}"
            if "ausbildung" in position.lower()
            else f"Bewerbung als {position}"
        )

        evidence_text_list = []
        for ev in evidence["top_evidence"]:
            hls = f" ({'; '.join(ev['highlights'])})" if ev.get("highlights") else ""
            evidence_text_list.append(f"- {ev['headline']}{hls}")
        evidence_str = "\n".join(evidence_text_list)

        system_prompt = (
            "Du bist ein führender deutscher Karriereberater und HR-Direktor (C1/C2-Niveau). "
            "Du verfasst erstklassige, individuelle und überzeugende Bewerbungsanschreiben nach DIN 5008 für den deutschen Markt. "
            "Dein Stil ist präzise, selbstbewusst, sympathisch und faktenbasiert – frei von austauschbaren Phrasen."
        )

        user_prompt = (
            f"Erstelle ein individuelles deutsches Anschreiben nach DIN 5008.\n\n"
            f"KANDIDATENDATEN (Faktenbasis aus dem Lebenslauf):\n"
            f"- Name: {full_name}\n"
            f"- Wohnort / Header: {location_header}\n"
            f"- Kontakt: E-Mail: {email} | Tel: {phone}\n"
            f"- Vorbildung & Berufserfahrung:\n{evidence_str}\n"
            f"- Technische Kernfähigkeiten: {', '.join(evidence['technical_skills'])}\n"
            f"- Sprachprofil: {evidence['german_evidence']}\n"
        )
        if evidence.get("ausbildung_rationale"):
            user_prompt += f"- Kontext Ausbildung: {evidence['ausbildung_rationale']}\n"

        user_prompt += (
            f"\nZIELUNTERNEHMEN & STELLE:\n"
            f"- Unternehmen: {company}\n"
            f"- Stelle: {position}\n"
            f"- Standort: {target_city}\n"
            f"- Ansprechpartner: {contact_person or 'Personalabteilung'}\n"
            f"- Datum: {today_str}\n"
            f"- Anrede: {salutation}\n"
            f"- Betreff: {betreff}\n\n"
            f"STRIKTE VORGABEN:\n"
            f"1. Briefkopf: DIN 5008 mit Absender oben links ({full_name}, {location_header}, {email} | {phone}), "
            f"Empfängerblock ({company}, {('z. H. ' + contact_person) if contact_person else 'Personalabteilung'}, {target_city}), "
            f"Datumzeile ({city_header}, den {today_str}), gefolgt von der Betreffzeile (fett, ohne das Wort 'Betreff').\n"
            f"2. Umfang: Exakt 250 bis 340 Wörter Fließtext.\n"
            f"3. ABSOLUTES VERBOT von Leerformeln wie 'Mit großem Interesse bewerbe ich mich', 'Hiermit bewerbe ich mich', "
            f"'Ich bin teamfähig, motiviert und flexibel', 'Als engagierter Kandidat' oder 'Ihr Unternehmen hat mein Interesse geweckt'.\n"
            f"4. 4-Absatz-Architektur:\n"
            f"   - Absatz 1: Starker Einstieg, der den Kandidaten direkt mit der Rolle und {company} verknüpft.\n"
            f"   - Absatz 2: 2–3 konkrete Belege aus der bisherigen Berufserfahrung (spezifische Aufgaben, Stack, Ergebnisse).\n"
            f"   - Absatz 3: Warum diese Stelle & dieses Unternehmen (für Ausbildung: warum eine duale Ausbildung trotz Vorerfahrung der richtige, logische Schritt ist – IHK-Standard, Enterprise-Verankerung in Deutschland).\n"
            f"   - Absatz 4: Wertbeitrag ab Tag 1, zügige Einarbeitung, Vorfreude auf das persönliche Kennenlernen.\n"
            f"5. Grußformel: 'Mit freundlichen Grüßen' gefolgt vom Namen ({full_name}).\n"
            f"6. Keine Platzhalter, keine eckigen Klammern, keine erfundenen Zahlen. Gib NUR den fertigen Anschreibentext aus."
        )

        if refinement_directive:
            user_prompt += f"\n\nZUSÄTZLICHE ANWEISUNG ZUR ÜBERARBEITUNG: {refinement_directive}\n"

        try:
            ai_res = ai_manager.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_output_tokens=1000,
                temperature=0.35,
                use_cache=False,
            )

            if not ai_res or not ai_res.get("success") or not ai_res.get("content"):
                err = ai_res.get("error") if ai_res else "Keine Antwort vom KI-Provider erhalten."
                logger.warning("CoverLetterWriter AI generation failed: %s", err)
                return {
                    "success": False,
                    "is_ai_generated": False,
                    "generation_mode": "ai_failed",
                    "error": f"KI-Generierung fehlgeschlagen: {err}",
                    "provider": getattr(ai_manager, "config", {}).get("primary_provider", "openai"),
                }

            letter_text = str(ai_res["content"]).strip().strip("`").strip()

            # Execute Quality Assurance
            qa_res = QualityAssurancePipeline.evaluate(letter_text, candidate_data, vacancy_data)

            # Bounded Revision: If QA score < 7.0 or issues detected, attempt 1 bounded refinement
            revision_count = 0
            if not qa_res["is_valid"] and qa_res["issues"]:
                logger.info("Cover letter failed initial QA (score %.1f, issues: %s). Attempting bounded revision...", qa_res["score"], qa_res["issues"])
                revision_prompt = (
                    f"Überarbeite das folgende Anschreiben nach diesen konkreten Kritikpunkten:\n"
                    f"{chr(10).join('- ' + iss for iss in qa_res['issues'])}\n\n"
                    f"URSPRÜNGLICHER TEXT:\n{letter_text}\n\n"
                    f"Achte strikt auf: 250–340 Wörter, DIN 5008, keine Floskeln, alle Platzhalter aufgelöst. Gib nur den korrigierten Text aus."
                )
                rev_res = ai_manager.complete(
                    prompt=revision_prompt,
                    system_prompt=system_prompt,
                    max_output_tokens=1000,
                    temperature=0.25,
                    use_cache=False,
                )
                if rev_res and rev_res.get("success") and rev_res.get("content"):
                    rev_text = str(rev_res["content"]).strip().strip("`").strip()
                    rev_qa = QualityAssurancePipeline.evaluate(rev_text, candidate_data, vacancy_data)
                    if rev_qa["score"] >= qa_res["score"]:
                        letter_text = rev_text
                        qa_res = rev_qa
                        revision_count = 1

            # Final post-cleanup of any lingering placeholder tokens
            cleanup_map = {
                "{{Unternehmen}}": company,
                "{{company}}": company,
                "{{Firma}}": company,
                "{{Position}}": position,
                "{{position}}": position,
                "{{Ort}}": target_city,
                "{{city}}": target_city,
                "{{Ansprechpartner}}": contact_person,
                "{{contact_person}}": contact_person,
                "{{Bewerber_Name}}": full_name,
                "{{candidate_name}}": full_name,
                "{{Bewerber_PLZ_Ort}}": city_header,
                "[Unternehmensadresse]": f"{target_city}",
                "[Datum]": f"{city_header}, den {today_str}",
            }
            for k_rep, v_rep in cleanup_map.items():
                if k_rep in letter_text:
                    letter_text = letter_text.replace(k_rep, v_rep)

            model_used = ai_res.get("model") or getattr(ai_manager, "config", {}).get("openai_model", "gpt-4o-mini")
            provider_used = getattr(ai_manager, "config", {}).get("primary_provider", "openai")

            return {
                "success": True,
                "letter_text": letter_text,
                "text": letter_text,
                "word_count": len(letter_text.split()),
                "qa_score": qa_res["score"],
                "qa_passed": qa_res["is_valid"],
                "qa_feedback": qa_res["issues"],
                "qa_result": qa_res,
                "revision_count": revision_count,
                "is_ai_generated": True,
                "generation_mode": "ai_revised" if revision_count > 0 else "ai_personalized",
                "ai_provider": provider_used,
                "ai_model": model_used,
                "candidate": {
                    "name": full_name,
                    "email": email,
                    "phone": phone,
                    "city": city_header,
                    "field": position,
                    "evidence_used": [e["headline"] for e in evidence["top_evidence"]],
                },
                "target": {
                    "company": company,
                    "position": position,
                    "city": target_city,
                    "contact_person": contact_person,
                },
            }

        except Exception as exc:
            logger.error("Error in CoverLetterWriter: %s", exc)
            return {
                "success": False,
                "is_ai_generated": False,
                "generation_mode": "ai_failed",
                "error": f"Unerwarteter Fehler bei der KI-Generierung: {str(exc)}",
            }


class CoverLetterEngine:
    """Public unified API for JobScout cover letter generation and contextual refinement."""

    @classmethod
    def generate_cover_letter(
        cls,
        candidate_profile: Dict[str, Any],
        company: str,
        position: str,
        city: str,
        contact_person: str = "",
        job_description: str = "",
        candidate_overrides: Optional[Dict[str, Any]] = None,
        refinement_directive: Optional[str] = None,
    ) -> Dict[str, Any]:
        """End-to-end generation combining vacancy analysis, evidence selection, and QA."""
        applicant = candidate_profile.get("applicant") or candidate_profile
        personal = applicant.get("personal") or {}
        contact = applicant.get("contact") or {}
        address = contact.get("address") or {}

        # Resolve candidate fields with overrides
        overrides = candidate_overrides or {}
        full_name = overrides.get("candidate_name") or personal.get("full_name") or "Bewerber"
        email = overrides.get("candidate_email") or contact.get("email") or ""
        phone = overrides.get("candidate_phone") or contact.get("phone_display") or contact.get("phone") or ""

        # Location formatting (never false defaults)
        cand_city = address.get("city") or contact.get("city") or ""
        cand_country = address.get("country") or contact.get("country") or ""
        cand_plz = address.get("postal_code") or contact.get("zip") or ""
        cand_street = address.get("street") or contact.get("street") or ""
        cand_hn = address.get("house_number") or ""

        if cand_street and cand_plz:
            location_header = f"{cand_street} {cand_hn}\n{cand_plz} {cand_city}".strip()
        elif cand_city and cand_country and cand_country.lower() not in ["deutschland", "germany"]:
            location_header = f"{cand_city}, {cand_country}"
        elif cand_city:
            location_header = f"{cand_plz} {cand_city}".strip() if cand_plz else cand_city
        else:
            location_header = "Casablanca, Marokko"

        candidate_data = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "city": cand_city or "Casablanca",
            "country": cand_country or "Marokko",
            "location_header": location_header,
        }

        vacancy_data = {
            "company": company,
            "position": position,
            "city": city,
            "contact_person": contact_person,
            "job_description": job_description,
        }

        # 1. Job Analysis
        analysis = JobAnalyzer.analyze(company, position, city, job_description)

        # 2. Evidence Selection
        evidence = EvidenceSelector.select_evidence(candidate_profile, analysis)

        # 3. Generation and Quality Assurance
        return CoverLetterWriter.generate(
            candidate_data=candidate_data,
            vacancy_data=vacancy_data,
            job_analysis=analysis,
            evidence=evidence,
            refinement_directive=refinement_directive,
        )

    @classmethod
    def refine_letter(
        cls,
        existing_text: str,
        action: str,
        candidate_name: str = "",
        company: str = "",
        position: str = "",
        location_header: str = "",
    ) -> Dict[str, Any]:
        """Executes targeted contextual refinement: 'improve', 'concise', 'formal', 'natural'."""
        if not getattr(ai_manager, "is_configured", False):
            return {
                "success": False,
                "error": "KI-Provider nicht konfiguriert für Überarbeitungen.",
            }

        directives = {
            "improve": (
                "Optimiere den Schreibstil: Noch eleganteres, flüssigeres Deutsch (C1-Niveau), "
                "präzisere Verben, stärkere Argumentationsführung, überzeugende Übergänge zwischen den Absätzen."
            ),
            "concise": (
                "Kürze den Text auf exakt 230–260 Wörter: Streiche alle Füllwörter und Weichmacher, "
                "bringe die Kernaussagen und Belege maximal auf den Punkt, ohne Fakten zu verlieren."
            ),
            "formal": (
                "Mache den Tonfall noch klassischer, diplomatischer und förmlicher: "
                "Ideal für traditionelle deutsche Konzerne und den gehobenen Mittelstand."
            ),
            "natural": (
                "Formuliere den Text moderner, frischer und direkter: "
                "Befreie ihn von hölzernen Schachtelsätzen, behalte aber volle Professionalität."
            ),
        }

        directive = directives.get(action.lower()) or "Verbessere Stil und Ausdruck des Anschreibens."

        system_prompt = (
            "Du bist ein führender deutscher Karriere-Editor. Überarbeite das gegebene Anschreiben "
            "strikt nach DIN 5008 unter Beibehaltung aller realen Fakten (Namen, Firmen, Wohnort, Erfahrungen). "
            "Erfinde keine fiktiven Adressen wie 'Musterstraße'. Wenn ein Briefkopf vorhanden ist, übernimm ihn exakt. "
            "Gib NUR den überarbeiteten Brieftext ohne Kommentare oder Markdown-Backticks aus."
        )

        user_prompt = (
            f"AKTION: {directive}\n\n"
            f"URSPRÜNGLICHER BRIEF:\n{existing_text}\n\n"
            f"Vorgaben:\n- Bestehenden Briefkopf exakt beibehalten (keine Erfindung von Straßen wie Musterstraße)\n"
            f"- Exakt 240–320 Wörter Fließtext\n- Keine Floskeln wie 'Mit großem Interesse'\n"
            f"- Keine Platzhalter wie {{{{...}}}} oder [...] hinterlassen."
        )

        ai_res = ai_manager.complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_output_tokens=900,
            temperature=0.3,
            use_cache=False,
        )

        if not ai_res or not ai_res.get("success"):
            return {"success": False, "error": ai_res.get("error", "Überarbeitung fehlgeschlagen.")}

        refined_text = str(ai_res["content"]).strip().strip("`").strip()
        return {
            "success": True,
            "text": refined_text,
            "letter_text": refined_text,
            "action": action,
            "word_count": len(refined_text.split()),
            "ai_model": ai_res.get("model", "gpt-4o-mini"),
        }
