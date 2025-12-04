"""
AI Design API Routes
Endpoints for AI-powered design generation
"""

from flask import Blueprint, request, jsonify
import logging

from services.ai_design_service import AIDesignGenerator

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__)

design_generator = AIDesignGenerator()


@ai_bp.route("/generate-design", methods=["POST"])
def generate_design():
    """
    Generate AI design based on business description

    POST /api/ai/generate-design
    {
        "template_type": "ecommerce",
        "business_description": "Modern sustainable fashion boutique..."
    }
    """
    try:
        data = request.get_json()

        template_type = data.get("template_type", "basic")
        business_description = data.get("business_description", "")

        if not business_description:
            return (
                jsonify(
                    {"success": False, "error": "Business description is required"}
                ),
                400,
            )

        # Generate design
        result = design_generator.generate_design(
            template_type=template_type, business_description=business_description
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"AI design generation error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@ai_bp.route("/color-schemes", methods=["POST"])
def generate_color_schemes():
    """
    Generate additional color scheme variations

    POST /api/ai/color-schemes
    {
        "template_type": "ecommerce",
        "business_description": "Fashion boutique",
        "count": 5
    }
    """
    try:
        data = request.get_json()

        template_type = data.get("template_type", "basic")
        business_description = data.get("business_description", "")
        count = data.get("count", 5)

        # Generate color schemes
        schemes = design_generator.generate_color_schemes(
            template_type=template_type,
            business_description=business_description,
            count=count,
        )

        return jsonify({"success": True, "color_schemes": schemes})

    except Exception as e:
        logger.error(f"Color scheme generation error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
