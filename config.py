import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Flask Settings
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-local")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")

# Third-party API Credentials
CAPTCHA_USERID = os.getenv("TRUECAPTCHA_USERID", "").strip()
CAPTCHA_APIKEY = os.getenv("TRUECAPTCHA_APIKEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

# Supabase Configuration
SUPABASE_URL = os.environ.get("VITE_SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_ANON_KEY = os.environ.get("VITE_SUPABASE_ANON_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))

# Firebase Configuration
FIREBASE_CONFIG = {
    "apiKey": os.getenv("FIREBASE_API_KEY", "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw"),
    "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", "clients-9d7fe.firebaseapp.com"),
    "projectId": os.getenv("FIREBASE_PROJECT_ID", "clients-9d7fe"),
    "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET", "clients-9d7fe.firebasestorage.app"),
    "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", "489647859812"),
    "appId": os.getenv("FIREBASE_APP_ID", "1:489647859812:web:6f0f06a20beef2ea6a9771"),
}

# Runtime & Data Directories
DATA_DIR = BASE_DIR / "data"
PROGRESS_DIR = DATA_DIR / "progress"
DOWNLOAD_EXPORT_DIR = DATA_DIR / "exports"
PARALLEL_EXPORT_DIR = DATA_DIR / "parallel_exports"
AUTO_EXTRACTION_EXPORT_DIR = DATA_DIR / "auto_extraction_exports"
EMAIL_CAMPAIGN_ASSET_DIR = DATA_DIR / "email_campaign_assets"
GOOGLE_MAPS_EXPORT_DIR = DATA_DIR / "google_maps_exports"

PDF_GENERATOR_DIR = BASE_DIR / "pdf_generator"
PDF_GENERATOR_FRONTEND_DIR = PDF_GENERATOR_DIR / "frontend"
PDF_GENERATOR_SERVICES_DIR = PDF_GENERATOR_DIR / "services"
PDF_GENERATOR_RUNTIME_DIR = DATA_DIR / "pdf_generator"
PDF_GENERATOR_UPLOAD_DIR = PDF_GENERATOR_RUNTIME_DIR / "uploads"
PDF_GENERATOR_TEMP_DIR = PDF_GENERATOR_RUNTIME_DIR / "temp"
PDF_GENERATOR_OUTPUT_DIR = PDF_GENERATOR_RUNTIME_DIR / "generated_pdfs"

# Ensure runtime directories exist
for directory in [
    DATA_DIR,
    PROGRESS_DIR,
    DOWNLOAD_EXPORT_DIR,
    PARALLEL_EXPORT_DIR,
    AUTO_EXTRACTION_EXPORT_DIR,
    EMAIL_CAMPAIGN_ASSET_DIR,
    GOOGLE_MAPS_EXPORT_DIR,
    PDF_GENERATOR_RUNTIME_DIR,
    PDF_GENERATOR_UPLOAD_DIR,
    PDF_GENERATOR_TEMP_DIR,
    PDF_GENERATOR_OUTPUT_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)
