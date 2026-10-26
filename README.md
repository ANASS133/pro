# 🚀 JobScout – AI Job Application Studio & Outreach Suite

JobScout is an end-to-end automated job search, candidate profile matching, personalized application letter generation, and bulk outreach platform tailored for the German job market (including **Ausbildung**, **Duales Studium**, and **Fachkräfte** roles).

---

## 🌟 Key Highlights

- **Multi-Portal Scraping Engine**: Unified scraping across **Arbeitsagentur**, **Ausbildung.de**, **Aubi-Plus**, **Azubiyo**, **IHK**, and **Google Maps / Overpass**.
- **Contact & Tech Intelligence**: Deep crawler that extracts recruiter emails, Impressum contacts, detected tech stacks, and email patterns.
- **AI Studio powered by GPT-5.6 Luna**:
  - ⚡ **ATS Keyword Tailoring**: Re-aligns candidate experience bullets to match target job descriptions with exact keywords (~$0.00003).
  - ✨ **"Warum wir?" Golden Hook**: Generates personalized, attention-grabbing opening lines tailored to the company (~$0.000015).
  - 🎯 **Culture & Vibe Radar**: Identifies team culture, work style, and candidate alignment directly on job search cards.
  - 📊 **Visual ATS Heatmap**: Color-coded match analysis (Match, Transferable, Gap) with match score and actionable tips.
  - 💾 **Smart Zero-Cost Caching**: SHA-256 hashed prompt responses cached locally in `data/ats_cache.json` for 0-token ($0.00) instant re-evaluations.
- **Candidate Profile & AI Memory Hub**: Visual skill cloud and editable candidate bio modal synced with candidate JSON profiles.
- **Dual PDF Anschreiben Generator**:
  - Pixel-perfect **ReportLab** overlay onto design letterhead PDFs.
  - Modern **Selenium HTML/CSS** print engine with `@page` support.
  - Dynamic template variables (`{{Firma}}`, `{{Beruf}}`, `{{Anrede}}`, `{{heutigenDatum}}`, etc.).
- **Email Outreach Pipeline**: Built-in throttler, spam score analyzer, contact validator, and automated follow-up scheduler.
- **AI Autofill Hub**: Embedded test sandboxes (`/test-form` and `/french-form`) and history tracking for the companion AI Job Autofill Chrome Extension.

---

## 📁 Project Architecture

```text
├── app.py                     # Main Flask web application & API routing
├── routes/                    # Modular Blueprint routes
│   └── pdf_routes.py          # ATS, Golden Hook, Vibe Radar & PDF endpoints
├── scraper/                   # Multi-platform scraping & intelligence engine
│   ├── working_email_extractor.py # Unified Arbeitsagentur search & extractor
│   ├── ausbildung_de_scraper.py   # Ausbildung.de scraper
│   ├── aubi_plus_scraper.py       # Aubi-Plus scraper
│   ├── azubiyo_scraper.py         # Azubiyo portal scraper
│   ├── ihk_scraper.py             # IHK Lehrstellenbörse scraper
│   ├── career_crawler.py          # Deep company website crawler
│   ├── impressum_extractor.py     # Legal notice contact parser
│   ├── tech_detector.py           # Tech stack analyzer
│   └── email_pattern_guesser.py   # Corporate email pattern prediction
├── pdf_generator/             # PDF generation engine
│   ├── services/
│   │   ├── ats_service.py     # Luna AI ATS, Hook, Vibe & Heatmap service
│   │   ├── pdf_service.py     # ReportLab canvas & Selenium HTML-to-PDF
│   │   └── template_service.py# Variable interpolation & placeholders
│   └── frontend/              # Standalone PDF generator prototype
├── email_sender/              # Bulk email delivery & safeguards
│   ├── throttler.py           # Rate limiting and cooldowns
│   ├── spam_analyzer.py       # Heuristic spam scoring
│   ├── validator.py           # Email MX & syntax validation
│   └── follow_up.py           # Automated follow-up sequencing
├── ai-job-autofill/           # Browser extension & candidate profiles
│   └── server/profiles/       # Candidate profile JSON data (e.g. anass_sibbi.json)
├── templates/                 # Jinja2 HTML templates
│   ├── app_shell.html         # Unified modern SPA shell
│   ├── test_form.html         # Autofill testing sandbox (German)
│   └── french_test_form.html  # Autofill testing sandbox (French)
├── static/spa/                # Single Page Application frontend
│   ├── app.js                 # Global navigation & Profile Hub controller
│   ├── app.css                # Plus Jakarta Sans styling & UI system
│   └── sections/              # Dynamic SPA views (search, PDF, email, autofill)
├── data/                      # Local SQLite DB, exports, and ats_cache.json
└── tests/                     # Automated unit and integration test suite
```

---

## ⚡ Quickstart

### 1. Prerequisites
- Python 3.10+
- Google Chrome or Microsoft Edge installed (for headless HTML-to-PDF rendering and deep web crawling)

### 2. Installation

```powershell
# Clone repository and navigate to folder
cd c:\Users\sibbi\Desktop\scraper

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration (`.env`)

Create or update `.env` in the root directory:

```env
SECRET_KEY=your-super-secret-key
SELENIUM_BROWSER=auto

# Luna AI / OpenAI API configuration
OPENAI_API_KEY=your-openai-or-luna-api-key
OPENAI_BASE_URL=https://api.openai.com/v1    # Or custom Luna endpoint
OPENAI_MODEL=gpt-5.6-luna                    # Default fallback: gpt-4o-mini

# Gmail SMTP (For Email Sender)
GMAIL_SENDER_EMAIL=your.email@gmail.com
GMAIL_APP_PASSWORD=your-16-character-app-password

# Optional: Supabase & Captcha
SUPABASE_URL=
SUPABASE_KEY=
TRUECAPTCHA_USERID=
TRUECAPTCHA_APIKEY=
```

### 4. Run the Application

```powershell
python app.py
```

Open your browser at **`http://127.0.0.1:5000`**.

---

## 🧠 AI Studio & Cost Optimization

JobScout uses **GPT-5.6 Luna** (with fallback to `gpt-4o-mini`) engineered with extreme cost-efficiency:

| Feature | Where to find | Typical Cost | Cache Cost |
| :--- | :--- | :--- | :--- |
| **⚡ ATS Keyword Tailor** | Anschreiben Editor | ~$0.00003 | **$0.00 (0 Tokens)** |
| **✨ "Warum wir?" Golden Hook** | Anschreiben Editor | ~$0.000015 | **$0.00 (0 Tokens)** |
| **🎯 Culture & Vibe Radar** | Search Job Cards | ~$0.00002 | **$0.00 (0 Tokens)** |
| **📊 Visual ATS Heatmap** | Search Job Cards | ~$0.00003 | **$0.00 (0 Tokens)** |

All queries check [`data/ats_cache.json`](file:///c:/Users/sibbi/Desktop/scraper/data/ats_cache.json) first via deterministic SHA-256 hashing. If an identical role/company was evaluated previously, results return in < 5ms with zero token consumption.

---

## 📄 Application Letter (Anschreiben) Features

- **Text or Full HTML/CSS**: Write standard text with quick placeholder tags, or supply a complete HTML/CSS design with `@page { size: A4; margin: 0; }`.
- **Micro-Toolbar**:
  - `KI-Platzhalter`: Auto-detects company names and placeholders.
  - `⚡ ATS Tailor`: Opens AI keyword optimizer modal.
  - `✨ Golden Hook`: Generates personalized opening hook.
  - `Extrahieren`: Pulls text directly from uploaded reference PDFs.
  - `Hintergrund-PDF`: Upload stationery or letterhead to overlay text on top.
- **Multiple Variants**: Create, test, and save different versions per industry or job profile.
- **Live PDF Preview**: High-fidelity modal preview before generating bulk documents.

---

## 🧪 Testing

Run the automated test suite across all modules:

```powershell
# Run all tests
python -m unittest discover -s tests

# Run ATS and Luna AI service tests
python -m unittest tests/test_ats_service.py

# Run Flask application routes tests
python -m unittest tests/test_app_routes.py

# Run HTML template validation
python -m unittest tests/test_html_templates.py
```

---

## 🔒 Privacy & Safety

- Local-first architecture: Contact details and generated PDF documents are stored locally in the [`data/`](file:///c:/Users/sibbi/Desktop/scraper/data/) folder.
- SMTP safeguard: Throttling limits outbound emails to prevent spam flags or inbox suspensions.
