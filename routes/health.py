import shutil
from datetime import datetime, timezone
from flask import Blueprint, jsonify
from config import DATA_DIR, CAPTCHA_USERID, CAPTCHA_APIKEY, OPENAI_API_KEY, GEMINI_API_KEY, SUPABASE_URL

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
@health_bp.route("/api/health", methods=["GET"])
def health_check():
    """System health check and diagnostic endpoint."""
    total, used, free = shutil.disk_usage(DATA_DIR)
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "true_captcha": bool(CAPTCHA_USERID and CAPTCHA_APIKEY),
            "openai": bool(OPENAI_API_KEY),
            "gemini": bool(GEMINI_API_KEY),
            "supabase": bool(SUPABASE_URL),
        },
        "storage": {
            "data_dir": str(DATA_DIR),
            "free_gb": round(free / (1024 ** 3), 2),
            "total_gb": round(total / (1024 ** 3), 2),
        }
    }), 200
