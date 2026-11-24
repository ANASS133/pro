"""Application routes package."""
from .health import health_bp
from .jobs import jobs_bp
from .pdf_routes import pdf_bp
from .enhancements import enhancements_bp
from .autofill import autofill_bp
from .campaigns import campaigns_bp
from .clients import clients_bp
from .supabase_onboarding import supabase_onboarding_bp
from .ai_settings import ai_settings_bp
from .whatsapp import whatsapp_bp
from .conductor import conductor_bp
from .cover_letters import cover_letters_bp
from .search import search_bp

__all__ = [
    "health_bp",
    "jobs_bp",
    "pdf_bp",
    "enhancements_bp",
    "autofill_bp",
    "campaigns_bp",
    "clients_bp",
    "supabase_onboarding_bp",
    "ai_settings_bp",
    "whatsapp_bp",
    "conductor_bp",
    "cover_letters_bp",
    "search_bp",
]
