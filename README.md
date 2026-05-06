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
TRUECAPTCHA_USERID=
TRUECAPTCHA_APIKEY=
GMAIL_SENDER_EMAIL=
GMAIL_APP_PASSWORD=
```

## Tests

Run the built-in automated checks:

```powershell
python -m unittest discover -s tests
```

## Cleanup notes

- Runtime progress and generated downloads now belong under `data/`
- The old standalone `email sender/` app is replaced by the `email_sender/` package
- The unified extractor is `scraper/working_email_extractor.py`
