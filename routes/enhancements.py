"""
Enhancement API routes for map visualization, spam scoring,
follow-up automation, and technology stack discovery.
"""

import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request

from email_sender.follow_up import FollowUpManager
from email_sender.spam_analyzer import SpamScoreAnalyzer
from scraper.fast_web_crawler import FastWebCrawler
from scraper.overpass_scraper import OverpassBusinessScraper
from scraper.tech_detector import TechDetector

logger = logging.getLogger(__name__)

enhancements_bp = Blueprint("enhancements", __name__)
GOOGLE_MAPS_EXPORT_DIR = Path("data") / "google_maps_exports"


@enhancements_bp.route("/api/map-data", methods=["GET"])
def api_map_data():
    """Return geolocated business points for interactive map display."""
    markers = []

    # 1. Load latest Google Maps export if available
    try:
        if GOOGLE_MAPS_EXPORT_DIR.exists():
            json_files = sorted(GOOGLE_MAPS_EXPORT_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            if json_files:
                with open(json_files[0], "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        name = item.get("name") or item.get("Unternehmensname") or ""
                        email = item.get("email") or item.get("emails") or item.get("E-Mail") or ""
                        if isinstance(email, list):
                            email = ", ".join(email)
                        phone = item.get("phone") or item.get("Telefon") or ""
                        website = item.get("website") or item.get("Webseite") or ""
                        address = item.get("address") or item.get("Adresse") or ""
                        lat = item.get("lat") or item.get("latitude")
                        lon = item.get("lon") or item.get("longitude")

                        # If lat/lon available or fallback
                        markers.append({
                            "name": name,
                            "email": email,
                            "phone": phone,
                            "website": website,
                            "address": address,
                            "lat": lat,
                            "lon": lon,
                            "has_email": bool(email),
                            "geschaeftsfuehrer": item.get("geschaeftsfuehrer", ""),
                        })
    except Exception as exc:
        logger.warning("Could not read exports for map markers: %s", exc)

    return jsonify({
        "success": True,
        "count": len(markers),
        "markers": markers[:300],
    })


@enhancements_bp.route("/api/email/analyze-spam", methods=["POST"])
def api_analyze_spam():
    """Pre-flight spam score analysis of email subject and body."""
    data = request.get_json(silent=True) or {}
    subject = str(data.get("subject") or "").strip()
    body = str(data.get("body") or "").strip()

    analysis = SpamScoreAnalyzer.analyze(subject, body)
    return jsonify({
        "success": True,
        "analysis": analysis,
    })


@enhancements_bp.route("/api/email/follow-ups", methods=["GET"])
def api_get_follow_ups():
    """Retrieve companies eligible for a courteous German follow-up."""
    min_days = int(request.args.get("min_days", 5))
    max_days = int(request.args.get("max_days", 21))

    manager = FollowUpManager()
    eligible = manager.find_eligible_follow_ups(min_days=min_days, max_days=max_days)

    return jsonify({
        "success": True,
        "count": len(eligible),
        "eligible": eligible,
    })


@enhancements_bp.route("/api/email/follow-up/draft", methods=["POST"])
def api_draft_follow_up():
    """Draft customized follow-up letter text."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip()
    job_title = str(data.get("job_title") or "").strip()
    sender_name = str(data.get("sender_name") or "").strip()
    salutation = str(data.get("salutation") or "Sehr geehrte Damen und Herren,").strip()
    days_ago = int(data.get("days_ago") or 7)

    candidate_entry = {
        "email": email,
        "days_ago": days_ago,
        "initial_subject": str(data.get("initial_subject") or ""),
    }

    draft = FollowUpManager.generate_follow_up(
        candidate_entry=candidate_entry,
        sender_name=sender_name,
        job_title=job_title,
        salutation=salutation,
    )

    return jsonify({
        "success": True,
        "draft": draft,
    })


@enhancements_bp.route("/api/scraper/overpass", methods=["POST"])
def api_search_overpass():
    """Search businesses via OpenStreetMap Overpass without browser overhead."""
    data = request.get_json(silent=True) or {}
    city = str(data.get("city") or "").strip()
    category = str(data.get("category") or "handwerk").strip()
    limit = min(int(data.get("limit") or 50), 200)

    if not city:
        return jsonify({"success": False, "message": "Bitte eine Stadt angeben"}), 400

    scraper = OverpassBusinessScraper()
    businesses = scraper.search_businesses(city=city, category=category, limit=limit)

    return jsonify({
        "success": True,
        "count": len(businesses),
        "businesses": businesses,
    })


@enhancements_bp.route("/api/scraper/detect-tech", methods=["POST"])
def api_detect_tech():
    """Detect CMS and web frameworks for a website URL."""
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "message": "Bitte eine URL angeben"}), 400

    crawler = FastWebCrawler(max_pages=1, timeout=8)
    html = crawler._fetch_url(url)
    if not html:
        return jsonify({"success": False, "message": "Seite konnte nicht geladen werden"}), 502

    tech_info = TechDetector.detect(html)
    return jsonify({
        "success": True,
        "url": url,
        "tech_info": tech_info,
    })
