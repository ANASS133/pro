# Architecture Audit — 13: Cross-Platform Capability & Comparison Matrix

> **Scope:** Comparative audit of all 6 supported platforms  
> **Target Platforms:** Arbeitsagentur, Ausbildung.de, Azubiyo, AUBI-plus, IHK, Google Maps  
> **Status:** Current Codebase Implementation

---

### 1. Comprehensive Platform Capability Matrix

| Feature / Capability | Arbeitsagentur | Ausbildung.de | Azubiyo | AUBI-plus | IHK | Google Maps |
|---|---|---|---|---|---|---|
| **Official Public API** | Implemented (`pc/v6/jobs`) | Not Available (HTML Scraping) | Not Available (Semantic URLs) | Not Available (Query HTML) | Not Available (Query HTML) | Partial (Overpass OSM API) |
| **HTTP Fast-Path** | Implemented (SSR Angular JSON) | Implemented (JSON-LD / Meta) | Implemented (Offer Cards) | Implemented (Sidebar Table) | Implemented (Chamber Table) | Implemented (Static Crawl) |
| **Selenium Fallback** | Implemented (On-demand) | Implemented (On-demand) | Implemented (On-demand) | Implemented (On-demand) | Implemented (On-demand) | Implemented (Maps Browser) |
| **Direct Recruiter Email** | High (Detail + Fallback) | Medium (Redirect / ATS) | Medium (Sidebar / ATS) | High (Contact Person) | High (Chamber Supervisor) | High (Verified Career) |
| **Impressum Email Fallback** | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented |
| **Application Form Discovery** | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented |
| **ATS Domain Detection** | Implemented (30+ ATS) | Implemented (30+ ATS) | Implemented (30+ ATS) | Implemented (30+ ATS) | Implemented (30+ ATS) | Implemented (30+ ATS) |
| **Tracking Redirect Unwrapping** | Implemented | Implemented | Implemented | Implemented | Implemented | N/A |
| **Cloudflare Email De-obfuscation** | N/A | Implemented | Implemented | Implemented | Implemented | Implemented |
| **Cookie Modal Auto-Dismiss** | Implemented (OneTrust) | Implemented (Usercentrics) | Implemented (Cookiebot) | Implemented | Implemented | Implemented (Google Consent) |
| **CAPTCHA / Challenge Detection** | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented |
| **Webshare Proxy Routing** | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented |
| **Fail-Closed Proxy Policy** | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented |
| **Real-time Worker Telemetry** | Implemented | Implemented | Implemented | Implemented | Implemented | Implemented |

---

### 2. Relative Platform Strengths & Bottlenecks

```mermaid
quadrantChart
    title Platform Extraction Efficiency vs. Contact Richness
    x-axis Low Efficiency (Heavy Selenium) --> High Efficiency (Fast HTTP/API)
    y-axis Low Direct Contact --> High Direct Contact
    quadrant-1 High Value, Fast Flow
    quadrant-2 High Value, Resource Heavy
    quadrant-3 Low Value, Resource Heavy
    quadrant-4 Fast Flow, Needs Enrichment
    "Arbeitsagentur": [0.85, 0.88]
    "IHK Lehrstellenbörse": [0.78, 0.82]
    "AUBI-plus": [0.72, 0.75]
    "Ausbildung.de": [0.45, 0.58]
    "Azubiyo": [0.55, 0.52]
    "Google Maps": [0.35, 0.80]
```

1. **Arbeitsagentur:** Fastest discovery and extraction due to official REST API and Angular SSR JSON scripts. Yields highest volume of direct recruiter email contacts.
2. **IHK Lehrstellenbörse:** Extremely high data quality and verified chamber contacts; minimal bot protection.
3. **AUBI-plus:** Clean tabular layout with designated *Ansprechpartner* boxes; fast HTTP parsing.
4. **Ausbildung.de & Azubiyo:** Heavy reliance on external tracking redirects and modern ATS portals. Lower direct email yield, but high yield for online application forms (`has_form = True`).
5. **Google Maps:** Highest computational resource usage (Overpass + Selenium + multi-page career crawling), but unlocks exclusive unadvertised opportunities unavailable on standard job boards.
