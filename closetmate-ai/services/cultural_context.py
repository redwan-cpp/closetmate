# services/cultural_context.py
# ─────────────────────────────────────────────────────────────────
# Detailed cultural context engine covering:
# South Asian · Western · Middle Eastern · East Asian
# ─────────────────────────────────────────────────────────────────

from typing import Dict, List, Optional

# ─────────────────────────────────────────────
# CULTURAL PROFILES
# Each profile defines:
# - garments        : known clothing items
# - formal_events   : occasion → preferred garments
# - taboo_colors    : colors avoided in certain contexts
# - modesty_level   : 1 (low) → 3 (high coverage)
# - layering_style  : typical layering approach
# - pattern_norms   : what patterns are culturally common
# ─────────────────────────────────────────────

CULTURAL_PROFILES: Dict[str, Dict] = {

    "south_asian": {
        "countries": ["bangladesh", "india", "pakistan", "sri_lanka", "nepal"],
        "garments": {
            "male":   ["panjabi", "kurta", "sherwani", "lungi", "dhoti", "waistcoat", "fatua"],
            "female": ["saree", "salwar_kameez", "lehenga", "anarkali", "gharara", "dupatta"],
            "unisex": ["kurta", "shawl"]
        },
        "occasions": {
            "wedding":  ["sherwani", "saree", "lehenga", "anarkali"],
            "holud":    ["panjabi", "kurta", "saree", "salwar_kameez"],
            "eid":      ["panjabi", "kurta", "salwar_kameez", "saree"],
            "casual":   ["panjabi", "kurta", "fatua", "salwar_kameez"],
            "office":   ["kurta", "salwar_kameez", "dress_shirt", "trousers"],
            "party":    ["sherwani", "lehenga", "anarkali", "panjabi"],
            "funeral":  ["white_kurta", "white_saree"],
        },
        "taboo_colors": {
            "funeral":  ["red", "bright_pink", "orange", "yellow"],
            "general":  []
        },
        "auspicious_colors": {
            "wedding":  ["red", "maroon", "golden", "cream"],
            "holud":    ["yellow", "orange", "golden", "green"],
            "eid":      ["white", "green", "cream", "sky_blue"],
        },
        "modesty_level": 2,
        "layering_style": "dupatta_over_shoulder",
        "pattern_norms": ["embroidery", "block_print", "floral", "geometric", "solid", "jamdani"],
        "fabric_preferences": ["cotton", "silk", "muslin", "georgette", "chiffon", "linen"],
    },

    "western": {
        "countries": ["usa", "uk", "canada", "australia", "europe"],
        "garments": {
            "male":   ["suit", "blazer", "dress_shirt", "chinos", "jeans", "t_shirt", "polo", "shorts"],
            "female": ["dress", "blouse", "skirt", "jeans", "blazer", "jumpsuit", "cardigan"],
            "unisex": ["hoodie", "denim_jacket", "trench_coat", "sneakers"]
        },
        "occasions": {
            "wedding":  ["suit", "tuxedo", "dress", "gown"],
            "casual":   ["t_shirt", "jeans", "shorts", "sneakers"],
            "office":   ["suit", "blazer", "dress_shirt", "chinos", "pencil_skirt"],
            "party":    ["blazer", "dress", "jumpsuit"],
            "funeral":  ["black_suit", "black_dress"],
            "beach":    ["shorts", "swimwear", "linen_shirt"],
        },
        "taboo_colors": {
            "funeral":  ["bright_colors", "neon", "white"],
            "general":  []
        },
        "auspicious_colors": {
            "wedding":  ["white", "ivory", "champagne"],
            "party":    ["black", "gold", "silver", "red"],
        },
        "modesty_level": 1,
        "layering_style": "jacket_or_blazer_over_shirt",
        "pattern_norms": ["solid", "stripes", "plaid", "floral", "abstract", "minimalist"],
        "fabric_preferences": ["cotton", "denim", "wool", "polyester", "linen", "leather"],
    },

    "middle_eastern": {
        "countries": ["saudi_arabia", "uae", "egypt", "turkey", "iran", "jordan", "morocco"],
        "garments": {
            "male":   ["thobe", "dishdasha", "kandura", "bisht", "keffiyeh", "agal", "jubba"],
            "female": ["abaya", "hijab", "niqab", "kaftan", "jalabiya", "jilbab"],
            "unisex": ["kaftan", "shawl"]
        },
        "occasions": {
            "wedding":  ["bisht", "embroidered_thobe", "embroidered_abaya", "kaftan"],
            "eid":      ["thobe", "dishdasha", "abaya", "kaftan"],
            "casual":   ["thobe", "dishdasha", "abaya", "kaftan"],
            "office":   ["thobe", "suit_over_thobe", "abaya_with_blazer"],
            "party":    ["embroidered_kaftan", "bisht", "embroidered_abaya"],
            "prayer":   ["thobe", "abaya", "hijab"],
            "funeral":  ["white_thobe", "black_abaya"],
        },
        "taboo_colors": {
            "funeral":  ["bright_colors", "red", "gold"],
            "prayer":   ["transparent", "revealing"],
            "general":  []
        },
        "auspicious_colors": {
            "wedding":  ["gold", "white", "cream", "royal_blue", "emerald"],
            "eid":      ["white", "cream", "gold", "pastel"],
        },
        "modesty_level": 3,
        "layering_style": "full_coverage_robes",
        "pattern_norms": ["solid", "embroidery", "geometric", "arabesque", "minimal"],
        "fabric_preferences": ["cotton", "linen", "silk", "wool_blend", "crepe"],
    },

    "east_asian": {
        "countries": ["china", "japan", "korea", "taiwan", "vietnam"],
        "garments": {
            "male":   ["hanfu", "tang_suit", "changshan", "haori", "hanbok_top", "ao_dai"],
            "female": ["qipao", "cheongsam", "hanfu", "kimono", "hanbok", "ao_dai"],
            "unisex": ["yukata", "modern_streetwear"]
        },
        "occasions": {
            "wedding":  ["qipao", "cheongsam", "hanbok", "kimono", "tang_suit"],
            "new_year": ["hanfu", "qipao", "tang_suit", "hanbok"],
            "casual":   ["modern_streetwear", "k_fashion", "minimalist"],
            "office":   ["suit", "dress_shirt", "modern_korean_business"],
            "party":    ["qipao", "modern_hanfu", "k_fashion"],
            "funeral":  ["white_hanbok", "black_suit", "white_kimono"],
            "festival": ["hanfu", "yukata", "hanbok"],
        },
        "taboo_colors": {
            "funeral":  ["red", "bright_colors"],
            "general":  ["white_in_some_contexts"]  # white = mourning in some East Asian cultures
        },
        "auspicious_colors": {
            "wedding":  ["red", "gold", "pink"],
            "new_year": ["red", "gold"],
            "festival": ["red", "gold", "bright_colors"],
        },
        "modesty_level": 2,
        "layering_style": "structured_minimalist",
        "pattern_norms": ["solid", "floral", "crane", "dragon", "geometric", "minimalist", "wave"],
        "fabric_preferences": ["silk", "cotton", "linen", "satin", "brocade"],
    }
}

# ─────────────────────────────────────────────
# SEASON PROFILES (by hemisphere + climate)
# ─────────────────────────────────────────────

SEASON_PROFILES = {
    "tropical": {
        "year_round": {"fabrics": ["cotton", "linen", "muslin"], "avoid": ["wool", "velvet", "fleece"]},
    },
    "temperate": {
        "spring":  {"fabrics": ["cotton", "linen", "light_knit"], "colors": ["pastel", "floral"]},
        "summer":  {"fabrics": ["cotton", "linen", "chambray"],   "colors": ["bright", "white", "neon"]},
        "autumn":  {"fabrics": ["denim", "wool_blend", "flannel"], "colors": ["earth_tones", "rust", "brown"]},
        "winter":  {"fabrics": ["wool", "fleece", "cashmere"],    "colors": ["dark", "navy", "grey", "black"]},
    },
    "arid": {
        "year_round": {"fabrics": ["cotton", "linen"], "avoid": ["dark_heavy_fabrics"]},
    }
}

# ─────────────────────────────────────────────
# LOOKUP HELPERS
# ─────────────────────────────────────────────

def get_cultural_profile(culture: str) -> Optional[Dict]:
    return CULTURAL_PROFILES.get(culture.lower().replace(" ", "_"))


def get_occasion_garments(culture: str, occasion: str) -> List[str]:
    profile = get_cultural_profile(culture)
    if not profile:
        return []
    return profile.get("occasions", {}).get(occasion.lower(), [])


def get_taboo_colors(culture: str, occasion: str) -> List[str]:
    profile = get_cultural_profile(culture)
    if not profile:
        return []
    taboos = profile.get("taboo_colors", {})
    return taboos.get(occasion.lower(), []) + taboos.get("general", [])


def get_auspicious_colors(culture: str, occasion: str) -> List[str]:
    profile = get_cultural_profile(culture)
    if not profile:
        return []
    return profile.get("auspicious_colors", {}).get(occasion.lower(), [])


def get_modesty_level(culture: str) -> int:
    profile = get_cultural_profile(culture)
    return profile.get("modesty_level", 1) if profile else 1


def detect_culture_from_garment(subcategory: str) -> Optional[str]:
    """Infer culture from garment name if user hasn't specified."""
    sub = subcategory.lower().replace(" ", "_")
    for culture, profile in CULTURAL_PROFILES.items():
        all_garments = []
        for g_list in profile.get("garments", {}).values():
            all_garments.extend(g_list)
        if sub in all_garments:
            return culture
    return None
