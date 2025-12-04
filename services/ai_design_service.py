"""
AI Design Generation Service
Generates color schemes, typography, and design recommendations
"""

import logging
import json
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class AIDesignGenerator:
    """Generate AI-powered designs for WordPress sites"""

    def __init__(self):
        self.color_palettes = self._load_color_palettes()

    def _load_color_palettes(self) -> Dict[str, List[Dict]]:
        """Pre-defined color palettes for different business types"""
        return {
            "ecommerce": [
                {
                    "name": "Bold & Modern",
                    "primary": "#FF6B6B",
                    "secondary": "#4ECDC4",
                    "accent": "#FFE66D",
                    "mood": "Energetic, youthful, approachable",
                },
                {
                    "name": "Luxury Retail",
                    "primary": "#1A1A1D",
                    "secondary": "#C3073F",
                    "accent": "#E5E5E5",
                    "mood": "Sophisticated, premium, elegant",
                },
                {
                    "name": "Natural & Organic",
                    "primary": "#2D6A4F",
                    "secondary": "#95D5B2",
                    "accent": "#F4A261",
                    "mood": "Eco-friendly, trustworthy, calm",
                },
                {
                    "name": "Tech & Innovation",
                    "primary": "#3A86FF",
                    "secondary": "#8338EC",
                    "accent": "#FB5607",
                    "mood": "Modern, innovative, dynamic",
                },
                {
                    "name": "Minimalist Chic",
                    "primary": "#000000",
                    "secondary": "#FFFFFF",
                    "accent": "#FF6B35",
                    "mood": "Clean, professional, sophisticated",
                },
            ],
            "blog": [
                {
                    "name": "Creative Writer",
                    "primary": "#264653",
                    "secondary": "#2A9D8F",
                    "accent": "#E76F51",
                    "mood": "Professional, creative, engaging",
                },
                {
                    "name": "Lifestyle & Fashion",
                    "primary": "#FFB3BA",
                    "secondary": "#FFDFBA",
                    "accent": "#FFFFBA",
                    "mood": "Soft, feminine, approachable",
                },
                {
                    "name": "Tech Blog",
                    "primary": "#0F172A",
                    "secondary": "#3B82F6",
                    "accent": "#10B981",
                    "mood": "Technical, modern, trustworthy",
                },
            ],
            "business": [
                {
                    "name": "Corporate Professional",
                    "primary": "#1E3A8A",
                    "secondary": "#3B82F6",
                    "accent": "#F59E0B",
                    "mood": "Professional, trustworthy, established",
                },
                {
                    "name": "Creative Agency",
                    "primary": "#7C3AED",
                    "secondary": "#EC4899",
                    "accent": "#F59E0B",
                    "mood": "Creative, bold, innovative",
                },
                {
                    "name": "Consulting Firm",
                    "primary": "#374151",
                    "secondary": "#6366F1",
                    "accent": "#10B981",
                    "mood": "Authoritative, professional, modern",
                },
            ],
            "portfolio": [
                {
                    "name": "Designer Portfolio",
                    "primary": "#FF6B9D",
                    "secondary": "#C44569",
                    "accent": "#FFC371",
                    "mood": "Creative, vibrant, artistic",
                },
                {
                    "name": "Photographer",
                    "primary": "#000000",
                    "secondary": "#FAFAFA",
                    "accent": "#FF6B6B",
                    "mood": "Clean, elegant, focused",
                },
                {
                    "name": "Developer Portfolio",
                    "primary": "#0F172A",
                    "secondary": "#22D3EE",
                    "accent": "#F472B6",
                    "mood": "Technical, modern, professional",
                },
            ],
            "basic": [
                {
                    "name": "Classic Blue",
                    "primary": "#0066CC",
                    "secondary": "#00AAFF",
                    "accent": "#FF6B00",
                    "mood": "Professional, trustworthy, accessible",
                },
                {
                    "name": "Modern Neutral",
                    "primary": "#2D3748",
                    "secondary": "#4A5568",
                    "accent": "#48BB78",
                    "mood": "Clean, modern, versatile",
                },
            ],
        }

    def generate_design(
        self, template_type: str, business_description: str
    ) -> Dict[str, Any]:
        """
        Generate a complete design based on template type and business description

        Args:
            template_type: Type of template (ecommerce, blog, business, portfolio, basic)
            business_description: Description of the business

        Returns:
            Complete design configuration
        """
        logger.info(
            f"Generating design for {template_type}: {business_description[:50]}..."
        )

        # Get color variations for this template type
        color_variations = self.color_palettes.get(
            template_type, self.color_palettes["basic"]
        )

        # Select primary scheme (first one)
        primary_scheme = color_variations[0]

        # Generate typography based on template type
        typography = self._generate_typography(template_type, business_description)

        # Generate logo prompt
        logo_prompt = self._generate_logo_prompt(business_description, primary_scheme)

        # Generate CSS variables
        css_variables = self._generate_css_variables(primary_scheme, typography)

        return {
            "success": True,
            "design": {
                "template_type": template_type,
                "primary_style": {"color_scheme": primary_scheme},
                "color_variations": color_variations,
                "typography": typography,
                "logo_generation_prompt": logo_prompt,
                "css_variables": css_variables,
                "layout_recommendations": self._generate_layout_recommendations(
                    template_type
                ),
            },
        }

    def _generate_typography(
        self, template_type: str, description: str
    ) -> Dict[str, str]:
        """Generate typography recommendations"""

        typography_sets = {
            "ecommerce": {
                "heading": "Montserrat, sans-serif",
                "body": "Open Sans, sans-serif",
            },
            "blog": {"heading": "Playfair Display, serif", "body": "Lato, sans-serif"},
            "business": {"heading": "Roboto, sans-serif", "body": "Inter, sans-serif"},
            "portfolio": {
                "heading": "Poppins, sans-serif",
                "body": "Work Sans, sans-serif",
            },
            "basic": {"heading": "Inter, sans-serif", "body": "Inter, sans-serif"},
        }

        return typography_sets.get(template_type, typography_sets["basic"])

    def _generate_logo_prompt(
        self, business_description: str, color_scheme: Dict
    ) -> str:
        """Generate a DALL-E/Midjourney prompt for logo generation"""

        # Extract key words from description
        keywords = business_description.lower()

        style_words = []
        if "modern" in keywords or "tech" in keywords:
            style_words.append("modern")
        if "luxury" in keywords or "premium" in keywords:
            style_words.append("luxury")
        if "eco" in keywords or "sustainable" in keywords:
            style_words.append("minimalist eco-friendly")
        if "creative" in keywords or "artistic" in keywords:
            style_words.append("artistic creative")

        style = ", ".join(style_words) if style_words else "professional modern"

        prompt = f"A {style} logo design for {business_description[:100]}, "
        prompt += (
            f"using colors {color_scheme['primary']} and {color_scheme['secondary']}, "
        )
        prompt += "clean vector style, simple and memorable, white background, "
        prompt += "professional branding, scalable design"

        return prompt

    def _generate_css_variables(self, color_scheme: Dict, typography: Dict) -> str:
        """Generate CSS custom properties"""

        css = f"""
:root {{
    /* Color Scheme */
    --color-primary: {color_scheme['primary']};
    --color-secondary: {color_scheme['secondary']};
    --color-accent: {color_scheme['accent']};
    
    /* Typography */
    --font-heading: {typography['heading']};
    --font-body: {typography['body']};
    
    /* Spacing */
    --spacing-xs: 0.5rem;
    --spacing-sm: 1rem;
    --spacing-md: 1.5rem;
    --spacing-lg: 2rem;
    --spacing-xl: 3rem;
    
    /* Border Radius */
    --radius-sm: 4px;
    --radius-md: 8px;
    --radius-lg: 16px;
}}

/* Apply to common elements */
body {{
    font-family: var(--font-body);
    color: #333;
}}

h1, h2, h3, h4, h5, h6 {{
    font-family: var(--font-heading);
}}

.btn-primary {{
    background-color: var(--color-primary);
    color: white;
    border: none;
    padding: var(--spacing-sm) var(--spacing-md);
    border-radius: var(--radius-md);
}}

.btn-secondary {{
    background-color: var(--color-secondary);
    color: white;
}}

a {{
    color: var(--color-primary);
}}

a:hover {{
    color: var(--color-accent);
}}
""".strip()

        return css

    def _generate_layout_recommendations(self, template_type: str) -> Dict[str, Any]:
        """Generate layout and structure recommendations"""

        layouts = {
            "ecommerce": {
                "homepage": "Hero banner with featured products, category grid, testimonials",
                "product_page": "Large product images, detailed specs, reviews, related products",
                "recommended_plugins": ["Product filters", "Quick view", "Wishlist"],
            },
            "blog": {
                "homepage": "Featured posts, recent articles grid, author bio, newsletter signup",
                "post_layout": "Wide featured image, readable typography, related posts",
                "recommended_plugins": ["Social sharing", "Reading time", "Author box"],
            },
            "business": {
                "homepage": "Services overview, team section, client logos, contact CTA",
                "services_page": "Service cards, case studies, pricing tables",
                "recommended_plugins": [
                    "Contact form",
                    "Testimonials",
                    "Team showcase",
                ],
            },
        }

        return layouts.get(template_type, {})

    def generate_color_schemes(
        self, template_type: str, business_description: str, count: int = 5
    ) -> List[Dict]:
        """Generate additional color scheme variations"""

        base_schemes = self.color_palettes.get(
            template_type, self.color_palettes["basic"]
        )

        # Return available schemes, cycling if needed
        schemes = []
        for i in range(count):
            schemes.append(base_schemes[i % len(base_schemes)])

        return schemes
