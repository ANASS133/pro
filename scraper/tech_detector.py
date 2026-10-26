"""
CMS & Technology Stack Detector.
Analyzes HTML meta tags, scripts, stylesheets, and headers to identify
the Content Management System, web frameworks, and marketing tools in use.
"""

import logging
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Technology signature dictionary
TECH_SIGNATURES = {
    "WordPress": {
        "category": "CMS",
        "patterns": [
            re.compile(r"/wp-content/", re.IGNORECASE),
            re.compile(r"/wp-includes/", re.IGNORECASE),
            re.compile(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']WordPress', re.IGNORECASE),
        ],
    },
    "TYPO3": {
        "category": "CMS",
        "patterns": [
            re.compile(r"/typo3conf/", re.IGNORECASE),
            re.compile(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']TYPO3', re.IGNORECASE),
            re.compile(r"typo3temp/", re.IGNORECASE),
        ],
    },
    "Shopify": {
        "category": "Shop",
        "patterns": [
            re.compile(r"cdn\.shopify\.com", re.IGNORECASE),
            re.compile(r"Shopify\.theme", re.IGNORECASE),
            re.compile(r'<meta[^>]+id=["\']shopify-digital-wallet', re.IGNORECASE),
        ],
    },
    "Shopware": {
        "category": "Shop",
        "patterns": [
            re.compile(r"/bundles/storefront/", re.IGNORECASE),
            re.compile(r"/engine/Shopware/", re.IGNORECASE),
            re.compile(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']Shopware', re.IGNORECASE),
        ],
    },
    "Webflow": {
        "category": "CMS",
        "patterns": [
            re.compile(r"assets\.website-files\.com", re.IGNORECASE),
            re.compile(r'<html[^>]+data-wf-page', re.IGNORECASE),
            re.compile(r'<meta[^>]+content=["\']Webflow', re.IGNORECASE),
        ],
    },
    "Wix": {
        "category": "CMS",
        "patterns": [
            re.compile(r"static\.wixstatic\.com", re.IGNORECASE),
            re.compile(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']Wix\.com', re.IGNORECASE),
        ],
    },
    "Squarespace": {
        "category": "CMS",
        "patterns": [
            re.compile(r"static1\.squarespace\.com", re.IGNORECASE),
            re.compile(r"Squarespace\.Constants", re.IGNORECASE),
        ],
    },
    "React": {
        "category": "Framework",
        "patterns": [
            re.compile(r"data-reactroot", re.IGNORECASE),
            re.compile(r"react(?:-dom)?(?:\.min)?\.js", re.IGNORECASE),
            re.compile(r"/_next/static/", re.IGNORECASE),
        ],
    },
    "Next.js": {
        "category": "Framework",
        "patterns": [
            re.compile(r"/_next/static/", re.IGNORECASE),
            re.compile(r'<script[^>]+id=["\']__NEXT_DATA__', re.IGNORECASE),
        ],
    },
    "Vue.js": {
        "category": "Framework",
        "patterns": [
            re.compile(r"data-v-[a-f0-9]+", re.IGNORECASE),
            re.compile(r"vue(?:\.runtime)?(?:\.min)?\.js", re.IGNORECASE),
            re.compile(r"/_nuxt/", re.IGNORECASE),
        ],
    },
    "Angular": {
        "category": "Framework",
        "patterns": [
            re.compile(r"ng-version=", re.IGNORECASE),
            re.compile(r"ng-app=", re.IGNORECASE),
        ],
    },
    "Bootstrap": {
        "category": "UI",
        "patterns": [
            re.compile(r"bootstrap(?:\.bundle)?(?:\.min)?\.(?:css|js)", re.IGNORECASE),
        ],
    },
    "Tailwind CSS": {
        "category": "UI",
        "patterns": [
            re.compile(r"tailwindcss", re.IGNORECASE),
        ],
    },
    "HubSpot": {
        "category": "Marketing",
        "patterns": [
            re.compile(r"js\.hs-scripts\.com", re.IGNORECASE),
            re.compile(r"hs-banner", re.IGNORECASE),
        ],
    },
    "Matomo": {
        "category": "Analytics",
        "patterns": [
            re.compile(r"matomo\.js", re.IGNORECASE),
            re.compile(r"_paq\.push", re.IGNORECASE),
        ],
    },
    "Google Tag Manager": {
        "category": "Analytics",
        "patterns": [
            re.compile(r"googletagmanager\.com/gtm\.js", re.IGNORECASE),
        ],
    },
}


class TechDetector:
    """Detects website CMS, frameworks, and analytics technologies."""

    @classmethod
    def detect(cls, html_content: str, headers: Optional[Dict] = None) -> Dict:
        """Analyze HTML content and response headers to detect technologies."""
        detected = []
        categories = {}
        primary_cms = ""
        primary_framework = ""

        if not html_content:
            return {
                "technologies": [],
                "primary_cms": "",
                "primary_framework": "",
                "summary": "",
            }

        headers_str = str(headers or "")

        for tech_name, spec in TECH_SIGNATURES.items():
            is_match = False
            for pattern in spec["patterns"]:
                if pattern.search(html_content) or (headers_str and pattern.search(headers_str)):
                    is_match = True
                    break

            if is_match:
                detected.append(tech_name)
                cat = spec["category"]
                categories.setdefault(cat, []).append(tech_name)

                if cat in ["CMS", "Shop"] and not primary_cms:
                    primary_cms = tech_name
                elif cat == "Framework" and not primary_framework:
                    primary_framework = tech_name

        # Primary tech preference: Framework first if available, else CMS
        primary_tech = primary_framework or primary_cms or (detected[0] if detected else "")

        return {
            "technologies": detected,
            "primary_cms": primary_cms,
            "primary_framework": primary_framework,
            "primary_tech": primary_tech,
            "summary": ", ".join(detected[:4]),
        }
