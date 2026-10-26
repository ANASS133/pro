"""
Campaign management Blueprint.
Provides fast REST endpoints backed by the persistent SQLite CampaignStore.
"""

from pathlib import Path
from flask import Blueprint, jsonify, request, send_file
from services.campaign_store import campaign_store

campaigns_bp = Blueprint("campaigns", __name__)


@campaigns_bp.route("/api/campaigns", methods=["GET"])
def list_campaigns():
    """List all saved email campaigns."""
    camps = campaign_store.list_campaigns()
    return jsonify({"success": True, "count": len(camps), "campaigns": camps}), 200


@campaigns_bp.route("/api/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    """Retrieve full details for a campaign."""
    camp = campaign_store.get_campaign(campaign_id, include_b64=request.args.get("include_b64", "false").lower() == "true")
    if not camp:
        return jsonify({"success": False, "error": "Campaign not found"}), 404
    return jsonify({"success": True, "campaign": camp}), 200


@campaigns_bp.route("/api/campaigns/<campaign_id>", methods=["DELETE"])
def delete_campaign(campaign_id):
    """Delete a campaign and associated disk assets."""
    deleted = campaign_store.delete_campaign(campaign_id)
    return jsonify({"success": deleted, "message": "Campaign deleted"}), 200


@campaigns_bp.route("/api/campaigns/<campaign_id>/attachments/<attachment_id>", methods=["GET"])
def download_attachment(campaign_id, attachment_id):
    """Directly stream an attachment file from disk without base64 decoding overhead."""
    camp = campaign_store.get_campaign(campaign_id)
    if not camp:
        return jsonify({"success": False, "error": "Campaign not found"}), 404

    target_att = next((a for a in camp.get("attachments", []) if a.get("id") == attachment_id), None)
    if not target_att:
        return jsonify({"success": False, "error": "Attachment not found"}), 404

    file_path = Path(target_att.get("file_path", ""))
    if not file_path.exists():
        return jsonify({"success": False, "error": "Attachment file missing from disk"}), 404

    return send_file(
        str(file_path),
        mimetype=target_att.get("mimetype", "application/pdf"),
        as_attachment=True,
        download_name=target_att.get("filename", "document.pdf")
    )
