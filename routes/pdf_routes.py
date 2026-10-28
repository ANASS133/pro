import io
from flask import Blueprint, jsonify, request, send_file
from pdf_generator.services.pdf_service import DIN_5008_PRESETS, PDFService
from pdf_generator.services.background_templates import get_template_pdf_path

pdf_bp = Blueprint("pdf_routes", __name__)


@pdf_bp.route("/api/pdf/fonts", methods=["GET"])
def get_fonts():
    """List supported fonts for PDF generation."""
    service = PDFService()
    return jsonify({
        "success": True,
        "default_font": service.font,
        "default_font_size": service.font_size,
        "supported_fonts": service.get_supported_fonts(),
        "custom_fonts": list(service.custom_fonts.keys()),
    }), 200


@pdf_bp.route("/api/pdf/din5008-presets", methods=["GET"])
def get_din5008_presets():
    """List German DIN 5008 layout presets (Form A and Form B specifications)."""
    return jsonify({
        "success": True,
        "presets": DIN_5008_PRESETS,
    }), 200


@pdf_bp.route("/api/pdf/stream-preview", methods=["POST"])
def preview_pdf_stream():
    """Generate in-memory PDF preview without saving temporary files to disk."""
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"success": False, "error": "Content is required"}), 400

    layout_options = data.get("layout_options")
    metadata = data.get("metadata", {"title": "Preview Document"})
    
    # Resolve design background from path or template_id
    design_pdf_path = data.get("design_pdf_path")
    template_id = data.get("template_id")
    if not design_pdf_path and template_id:
        resolved_path = get_template_pdf_path(template_id)
        if resolved_path:
            design_pdf_path = str(resolved_path)

    try:
        service = PDFService()
        stream = service.create_pdf_stream(
            content=content,
            metadata=metadata,
            design_pdf_path=design_pdf_path,
            layout_options=layout_options,
        )
        return send_file(
            stream,
            mimetype="application/pdf",
            as_attachment=False,
            download_name="preview.pdf",
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@pdf_bp.route("/api/pdf/ats-tailor", methods=["POST"])
def ats_tailor_route():
    """Tailor applicant bullet points to job posting keywords using GPT Luna."""
    data = request.get_json(silent=True) or {}
    job_title = data.get("job_title", "")
    company_name = data.get("company_name", "")
    job_requirements = data.get("job_requirements", "")
    current_bullets = data.get("current_bullets", "")
    profile_id = data.get("profile_id", "anass_sibbi")

    from pdf_generator.services.ats_service import tailor_ats_keywords
    result = tailor_ats_keywords(
        job_title=job_title,
        company_name=company_name,
        job_requirements=job_requirements,
        current_bullets=current_bullets,
        profile_id=profile_id
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@pdf_bp.route("/api/pdf/golden-hook", methods=["POST"])
def golden_hook_route():
    """Generate 1 authentic German opening hook for the cover letter."""
    data = request.get_json(silent=True) or {}
    company_name = data.get("company_name", "")
    job_title = data.get("job_title", "")
    job_requirements = data.get("job_requirements", "")
    profile_id = data.get("profile_id", "anass_sibbi")

    from pdf_generator.services.ats_service import generate_golden_hook
    result = generate_golden_hook(
        company_name=company_name,
        job_title=job_title,
        job_requirements=job_requirements,
        profile_id=profile_id
    )
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@pdf_bp.route("/api/pdf/culture-vibe", methods=["POST"])
def culture_vibe_route():
    """Analyze company culture vibe and formality (Du vs Sie)."""
    data = request.get_json(silent=True) or {}
    company_name = data.get("company_name", "")
    job_title = data.get("job_title", "")
    snippet = data.get("snippet", "")

    from pdf_generator.services.ats_service import detect_culture_vibe
    result = detect_culture_vibe(
        company_name=company_name,
        job_title=job_title,
        snippet=snippet
    )
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@pdf_bp.route("/api/pdf/ats-heatmap", methods=["POST"])
def ats_heatmap_route():
    """Generate visual ATS heatmap pills comparing candidate profile to job requirements."""
    data = request.get_json(silent=True) or {}
    company_name = data.get("company_name", "")
    job_title = data.get("job_title", "")
    requirements = data.get("requirements", "")
    profile_id = data.get("profile_id", "anass_sibbi")

    from pdf_generator.services.ats_service import generate_ats_heatmap
    result = generate_ats_heatmap(
        company_name=company_name,
        job_title=job_title,
        requirements=requirements,
        profile_id=profile_id
    )
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@pdf_bp.route("/api/pdf/batch-ats-eval", methods=["POST"])
def batch_ats_eval_route():
    """Batch evaluate multiple scraped job postings and rank them by ATS match percentage."""
    data = request.get_json(silent=True) or {}
    jobs = data.get("jobs", [])
    profile_id = data.get("profile_id", "anass_sibbi")

    if not isinstance(jobs, list):
        return jsonify({"success": False, "error": "jobs list is required"}), 400

    from pdf_generator.services.ats_service import batch_evaluate_ats_jobs
    ranked_jobs = batch_evaluate_ats_jobs(jobs, profile_id=profile_id)
    return jsonify({"success": True, "count": len(ranked_jobs), "jobs": ranked_jobs}), 200



