"""
Deliverability & Spam Score Analyzer.
Evaluates email subject and body text for spam triggers, aggressive language,
formatting anomalies, and excessive links to maximize Gmail inbox delivery rates.
"""

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

# High-risk spam triggers (German and English)
SPAM_TRIGGERS_GERMAN = [
    "100% kostenlos", "garantiert", "ohne risiko", "geld verdienen",
    "reich werden", "exklusives angebot", "gewinnspiel", "gratis",
    "jetzt handeln", "dringend", "letzte chance", "sofortige auszahlung",
    "klicken sie hier", "keine werbung", "unverbindlich testen",
    "nur heute", "sonderangebot", "rabattcode", "wahnsinn"
]

SPAM_TRIGGERS_ENGLISH = [
    "100% free", "guaranteed", "no risk", "make money",
    "get rich", "exclusive deal", "winner", "urgent",
    "act now", "limited time", "click here", "buy direct",
    "instant cash", "risk-free", "congratulations"
]

SIGN_OFF_PATTERNS = [
    re.compile(r"mit\s+freundlichen\s+grüßen", re.IGNORECASE),
    re.compile(r"viele\s+grüße", re.IGNORECASE),
    re.compile(r"beste\s+grüße", re.IGNORECASE),
    re.compile(r"herzliche\s+grüße", re.IGNORECASE),
    re.compile(r"best\s+regards", re.IGNORECASE),
    re.compile(r"sincerely", re.IGNORECASE),
]


class SpamScoreAnalyzer:
    """Pre-flight spam score analysis and deliverability advisor."""

    @classmethod
    def analyze(cls, subject: str, body: str) -> Dict:
        """
        Analyzes subject and body, computing a deliverability score (0-100),
        risk level ('LOW', 'MEDIUM', 'HIGH'), and actionable recommendations.
        """
        score = 100
        triggers_found: List[str] = []
        warnings: List[str] = []
        recommendations: List[str] = []

        sub_clean = str(subject or "").strip()
        body_clean = str(body or "").strip()
        combined_text = f"{sub_clean}\n{body_clean}".lower()

        # 1. Subject line checks
        if not sub_clean:
            score -= 30
            warnings.append("Betreffzeile ist leer.")
        else:
            # Check length
            if len(sub_clean) > 80:
                score -= 10
                warnings.append("Betreffzeile ist sehr lang (> 80 Zeichen).")
                recommendations.append("Halten Sie die Betreffzeile prägnant (unter 50 Zeichen).")

            # Check uppercase ratio in subject
            letters = [c for c in sub_clean if c.isalpha()]
            if letters:
                upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
                if upper_ratio > 0.4:
                    score -= 25
                    warnings.append("Betreffzeile enthält übermäßig viele Großbuchstaben (Versalien).")
                    recommendations.append("Vermeiden Sie reine Großschreibung im Betreff.")

            # Check excessive punctuation in subject
            if re.search(r"[!?]{2,}", sub_clean):
                score -= 20
                warnings.append("Betreff enthält mehrfache Ausrufe- oder Fragezeichen (z. B. '!!').")
                recommendations.append("Entfernen Sie doppelte Ausrufezeichen aus dem Betreff.")

        # 2. Body spam trigger phrases
        for trigger in SPAM_TRIGGERS_GERMAN + SPAM_TRIGGERS_ENGLISH:
            if trigger in combined_text:
                score -= 12
                triggers_found.append(trigger)

        if triggers_found:
            warnings.append(f"Spam-verdächtige Signalwörter gefunden: {', '.join(triggers_found[:5])}")
            recommendations.append("Ersetzen Sie reißerische Wörter durch sachliche, professionelle Formulierungen.")

        # 3. Excessive punctuation in body
        exclamation_count = body_clean.count("!")
        if exclamation_count > 4:
            score -= 10
            warnings.append(f"Viele Ausrufezeichen im Text ({exclamation_count}x gefunden).")
            recommendations.append("Reduzieren Sie Ausrufezeichen im Anschreiben auf maximal 1-2.")

        # 4. Link count check (more than 3 links in cold email often triggers spam)
        url_matches = re.findall(r"https?://[^\s<>\"']+", body_clean)
        if len(url_matches) > 3:
            score -= 15
            warnings.append(f"Sehr viele Links im Text ({len(url_matches)} Links gefunden).")
            recommendations.append("Beschränken Sie Links im Erstkontakt auf 1-2 relevante Verweise.")

        # 5. Check professional closing / sign-off
        has_signoff = any(p.search(body_clean) for p in SIGN_OFF_PATTERNS)
        if not has_signoff and len(body_clean) > 50:
            score -= 8
            warnings.append("Keine standardmäßige deutsche Grußformel erkannt (z. B. 'Mit freundlichen Grüßen').")
            recommendations.append("Fügen Sie eine professionelle Grußformel und Signatur hinzu.")

        # Floor score between 0 and 100
        final_score = max(0, min(100, score))

        # Risk classification
        if final_score >= 80:
            risk = "LOW"
        elif final_score >= 55:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

        return {
            "score": final_score,
            "risk": risk,
            "is_safe": final_score >= 70,
            "triggers_found": triggers_found,
            "warnings": warnings,
            "recommendations": recommendations,
        }
