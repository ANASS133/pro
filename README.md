# Arbeitsagentur Scraper

This project automates a simple outreach workflow:

1. Search jobs from Arbeitsagentur
2. Extract company contact details from job pages
3. Generate PDF application letters
4. Send bulk emails with attachments

## Current structure

```text
app.py
scraper/
pdf_generator/
email_sender/
templates/
static/
data/
```

- `app.py`: main Flask app and route orchestration
- `scraper/`: Arbeitsagentur search and contact extraction
- `pdf_generator/`: PDF frontend and services
- `email_sender/`: reusable email transport package
- `data/`: runtime files, generated exports, progress snapshots, and PDF assets

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Optional local environment values in `.env`:

```env
SECRET_KEY=change-me
SELENIUM_BROWSER=auto
TRUECAPTCHA_USERID=
TRUECAPTCHA_APIKEY=
GMAIL_SENDER_EMAIL=
GMAIL_APP_PASSWORD=
```

## HTML/CSS application letters

Paste a full HTML document (including its `<style>` block) or an HTML fragment
into the Anschreiben template editor, save it, then use the PDF preview or batch
generation. HTML is detected automatically. Existing text templates and basic
bold/italic formatting continue to work as before.

HTML templates use installed Chrome/Edge through Selenium. CSS controls the
layout, including `@page` and `@media print`; the default is A4 with zero page
margins. Text layout controls and uploaded PDF backgrounds do not apply to HTML.
Placeholders such as `{{company}}` and `{{heutigenDatum}}` still work, with data
escaped as HTML text. Use inline CSS, HTTPS assets, or embedded data images/fonts;
relative/local assets and JavaScript are not supported. Rendering requires a
working browser driver (downloaded automatically by webdriver-manager).

## Tests

Run the built-in automated checks:

```powershell
python -m unittest discover -s tests
```

## Cleanup notes

- Runtime progress and generated downloads now belong under `data/`
- The old standalone `email sender/` app is replaced by the `email_sender/` package
- The unified extractor is `scraper/working_email_extractor.py`
