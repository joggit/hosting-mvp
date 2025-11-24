"""
AI Design Service
Generates color schemes, typography, and brand assets for WordPress sites
Located at: services/ai_design.py
"""

import colorsys
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict


@dataclass
class ColorScheme:
    """Color scheme for a website"""

    primary: str
    secondary: str
    background: str
    text: str
    accent: str
    name: str
    mood: str


@dataclass
class DesignStyle:
    """Complete design style package"""

    color_scheme: ColorScheme
    typography: Dict[str, str]
    spacing: str
    border_radius: str
    style_name: str


class AIDesignService:
    """Generate design systems based on business description"""

    # Industry color palettes
    INDUSTRY_COLORS = {
        "ecommerce": {
            "fashion": ["#FF6B9D", "#C44569", "#8B4789"],
            "electronics": ["#2C3E50", "#3498DB", "#E74C3C"],
            "food": ["#E67E22", "#D35400", "#27AE60"],
            "jewelry": ["#8E44AD", "#2C3E50", "#F39C12"],
            "sports": ["#E74C3C", "#2ECC71", "#3498DB"],
            "default": ["#3498DB", "#2ECC71", "#E74C3C"],
        },
        "blog": {
            "tech": ["#2C3E50", "#3498DB", "#1ABC9C"],
            "lifestyle": ["#E91E63", "#FF9800", "#9C27B0"],
            "business": ["#34495E", "#16A085", "#F39C12"],
            "personal": ["#9B59B6", "#3498DB", "#1ABC9C"],
            "default": ["#3498DB", "#9B59B6", "#E67E22"],
        },
        "business": {
            "consulting": ["#2C3E50", "#3498DB", "#16A085"],
            "finance": ["#2C3E50", "#2980B9", "#27AE60"],
            "healthcare": ["#3498DB", "#1ABC9C", "#2ECC71"],
            "legal": ["#2C3E50", "#34495E", "#7F8C8D"],
            "creative": ["#E74C3C", "#F39C12", "#9B59B6"],
            "default": ["#3498DB", "#2C3E50", "#16A085"],
        },
    }

    # Typography pairings
    FONT_PAIRINGS = {
        "modern": {"heading": "Poppins, sans-serif", "body": "Inter, sans-serif"},
        "elegant": {"heading": "Playfair Display, serif", "body": "Lato, sans-serif"},
        "minimal": {
            "heading": "Montserrat, sans-serif",
            "body": "Open Sans, sans-serif",
        },
        "bold": {"heading": "Oswald, sans-serif", "body": "Roboto, sans-serif"},
        "professional": {
            "heading": "Raleway, sans-serif",
            "body": "Source Sans Pro, sans-serif",
        },
    }

    def __init__(self, openai_api_key: Optional[str] = None):
        """Initialize AI design service"""
        self.openai_api_key = openai_api_key
        self.use_openai = openai_api_key is not None

    def generate_color_scheme(
        self,
        template_type: str,
        business_description: str,
        industry: Optional[str] = None,
    ) -> ColorScheme:
        """Generate color scheme based on template and business description"""

        keywords = self._extract_keywords(business_description.lower())

        if not industry:
            industry = self._detect_industry(template_type, keywords)

        # Get base colors
        if template_type in self.INDUSTRY_COLORS:
            industry_colors = self.INDUSTRY_COLORS[template_type].get(
                industry, self.INDUSTRY_COLORS[template_type]["default"]
            )
        else:
            industry_colors = ["#3498DB", "#2ECC71", "#E74C3C"]

        primary = industry_colors[0]
        secondary = (
            industry_colors[1]
            if len(industry_colors) > 1
            else self._generate_complementary(primary)
        )
        accent = (
            industry_colors[2]
            if len(industry_colors) > 2
            else self._generate_triadic(primary)
        )

        mood = self._determine_mood(keywords)

        # Adjust colors based on mood
        if mood == "calm":
            primary = self._adjust_saturation(primary, -20)
            secondary = self._adjust_saturation(secondary, -20)
        elif mood == "energetic":
            primary = self._adjust_saturation(primary, 20)
            accent = self._adjust_brightness(accent, 10)
        elif mood == "elegant":
            primary = self._adjust_saturation(primary, -10)
            secondary = self._adjust_brightness(secondary, -10)

        return ColorScheme(
            primary=primary,
            secondary=secondary,
            background="#FFFFFF",
            text="#2C3E50",
            accent=accent,
            name=f"{industry.capitalize()} {mood.capitalize()}",
            mood=mood,
        )

    def generate_design_style(
        self,
        template_type: str,
        business_description: str,
        industry: Optional[str] = None,
    ) -> DesignStyle:
        """Generate complete design style"""

        color_scheme = self.generate_color_scheme(
            template_type, business_description, industry
        )
        font_style = self._choose_typography(color_scheme.mood)
        typography = self.FONT_PAIRINGS[font_style]

        if color_scheme.mood in ["modern", "minimal"]:
            spacing = "loose"
            border_radius = "12px"
        elif color_scheme.mood == "elegant":
            spacing = "comfortable"
            border_radius = "4px"
        else:
            spacing = "compact"
            border_radius = "8px"

        style_name = f"{color_scheme.name} - {font_style.capitalize()}"

        return DesignStyle(
            color_scheme=color_scheme,
            typography=typography,
            spacing=spacing,
            border_radius=border_radius,
            style_name=style_name,
        )

    def generate_logo_prompt(self, business_description: str) -> str:
        """Generate prompt for AI image generation"""
        prompt = f"Modern minimalist logo design for {business_description}, "
        prompt += f"simple geometric shapes, professional, clean lines, "
        prompt += f"flat design, vector style, single color variations, "
        prompt += f"suitable for web use, white background, centered composition"
        return prompt

    def generate_brand_assets(
        self, template_type: str, business_description: str
    ) -> Dict:
        """Generate complete brand package"""

        design_style = self.generate_design_style(template_type, business_description)
        logo_prompt = self.generate_logo_prompt(business_description)

        variations = []
        for i in range(3):
            variant = self.generate_color_scheme(
                template_type, business_description + f" variation {i}"
            )
            variations.append(asdict(variant))

        return {
            "primary_style": asdict(design_style),
            "color_variations": variations,
            "logo_generation_prompt": logo_prompt,
            "typography": design_style.typography,
            "recommended_images": self._suggest_image_style(template_type),
            "css_variables": self._generate_css_variables(design_style),
        }

    # Helper methods
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords"""
        keywords = []

        industry_terms = {
            "fashion": ["fashion", "clothing", "apparel", "style", "boutique"],
            "food": ["food", "restaurant", "cafe", "catering", "bakery"],
            "tech": ["technology", "software", "digital", "tech", "app"],
            "health": ["health", "medical", "wellness", "fitness", "healthcare"],
            "creative": ["creative", "design", "art", "agency", "studio"],
        }

        mood_terms = {
            "calm": ["calm", "peaceful", "serene", "minimal", "zen"],
            "energetic": ["energetic", "vibrant", "dynamic", "bold", "exciting"],
            "elegant": ["elegant", "luxury", "premium", "sophisticated", "refined"],
            "modern": ["modern", "contemporary", "sleek", "innovative"],
            "professional": ["professional", "corporate", "business", "formal"],
        }

        for category, terms in {**industry_terms, **mood_terms}.items():
            for term in terms:
                if term in text:
                    keywords.append(category)
                    break

        return keywords

    def _detect_industry(self, template_type: str, keywords: List[str]) -> str:
        """Detect industry from keywords"""
        if template_type == "ecommerce":
            industries = ["fashion", "electronics", "food", "jewelry", "sports"]
        elif template_type == "blog":
            industries = ["tech", "lifestyle", "business", "personal"]
        else:
            industries = ["consulting", "finance", "healthcare", "legal", "creative"]

        for industry in industries:
            if industry in keywords:
                return industry

        return "default"

    def _determine_mood(self, keywords: List[str]) -> str:
        """Determine design mood"""
        moods = ["calm", "energetic", "elegant", "modern", "professional"]
        for mood in moods:
            if mood in keywords:
                return mood
        return "modern"

    def _choose_typography(self, mood: str) -> str:
        """Choose typography based on mood"""
        typography_map = {
            "calm": "minimal",
            "energetic": "bold",
            "elegant": "elegant",
            "modern": "modern",
            "professional": "professional",
        }
        return typography_map.get(mood, "modern")

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        """Convert hex to RGB"""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, r: int, g: int, b: int) -> str:
        """Convert RGB to hex"""
        return f"#{r:02x}{g:02x}{b:02x}"

    def _adjust_saturation(self, hex_color: str, amount: int) -> str:
        """Adjust color saturation"""
        r, g, b = self._hex_to_rgb(hex_color)
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        s = max(0, min(1, s + amount / 100))
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return self._rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))

    def _adjust_brightness(self, hex_color: str, amount: int) -> str:
        """Adjust color brightness"""
        r, g, b = self._hex_to_rgb(hex_color)
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        v = max(0, min(1, v + amount / 100))
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return self._rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))

    def _generate_complementary(self, hex_color: str) -> str:
        """Generate complementary color"""
        r, g, b = self._hex_to_rgb(hex_color)
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        h = (h + 0.5) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return self._rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))

    def _generate_triadic(self, hex_color: str) -> str:
        """Generate triadic color"""
        r, g, b = self._hex_to_rgb(hex_color)
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        h = (h + 0.33) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return self._rgb_to_hex(int(r * 255), int(g * 255), int(b * 255))

    def _suggest_image_style(self, template_type: str) -> Dict[str, str]:
        """Suggest image style"""
        styles = {
            "ecommerce": {
                "product_photos": "Clean white background, professional lighting",
                "hero_images": "Lifestyle photography, natural lighting",
                "background": "Subtle patterns or gradients",
            },
            "blog": {
                "featured_images": "High-quality photography, relevant to content",
                "author_photo": "Professional headshot, warm and approachable",
                "background": "Minimal patterns, light textures",
            },
            "business": {
                "hero_images": "Professional team photos, modern office spaces",
                "service_images": "Icons or illustrations, consistent style",
                "background": "Subtle gradients, professional colors",
            },
        }
        return styles.get(template_type, styles["business"])

    def _generate_css_variables(self, design_style: DesignStyle) -> str:
        """Generate CSS custom properties"""
        cs = design_style.color_scheme

        css = f"""/* AI-Generated Design Variables */
:root {{
    /* Colors */
    --color-primary: {cs.primary};
    --color-secondary: {cs.secondary};
    --color-accent: {cs.accent};
    --color-background: {cs.background};
    --color-text: {cs.text};
    
    /* Typography */
    --font-heading: {design_style.typography['heading']};
    --font-body: {design_style.typography['body']};
    
    /* Spacing */
    --spacing-unit: {self._get_spacing_value(design_style.spacing)};
    
    /* Borders */
    --border-radius: {design_style.border_radius};
    
    /* Shadows */
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
    --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
}}"""
        return css

    def _get_spacing_value(self, spacing: str) -> str:
        """Get spacing value"""
        spacing_map = {"compact": "4px", "comfortable": "8px", "loose": "12px"}
        return spacing_map.get(spacing, "8px")
