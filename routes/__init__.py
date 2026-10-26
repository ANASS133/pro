"""Application routes package."""
from .health import health_bp
from .jobs import jobs_bp
from .pdf_routes import pdf_bp
from .enhancements import enhancements_bp
from .autofill import autofill_bp
from .campaigns import campaigns_bp

__all__ = ["health_bp", "jobs_bp", "pdf_bp", "enhancements_bp", "autofill_bp", "campaigns_bp"]

