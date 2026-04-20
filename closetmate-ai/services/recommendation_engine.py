# services/recommendation_engine.py
# ─────────────────────────────────────────────────────────────────
# Pinterest/social-media-inspired outfit recommendation engine
# Layers: Cultural Filter → Scoring Algorithm → AI Refinement
# ─────────────────────────────────────────────────────────────────

import os
import json
import httpx
from typing import List, Dict, Optional, Tuple
from services.cultural_context import (
    get_occasion_garments,
    get_taboo_colors,
    get_auspicious_colors,
    get_modesty_level,
    detect_culture_from_garment,
    CULTURAL_PROFILES,
)
from services.outfit_rules import validate_outfit, fix_outfit

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ─────────────────────────────────────────────
# PINTEREST-INSPIRED COLOR PALETTE SYSTEM
# Derived from observing trending outfit combos
# across Pinterest, Instagram, and K/J/SA fashion
# ─────────────────────────────────────────────

COLOR_PALETTES = {
    # Neutrals — match everything
    "neutrals": ["white", "cream", "beige", "ivory", "light_grey", "grey", "black", "charcoal"],

    # Earth tones — trending heavily on Pinterest
    "earth_tones": ["brown", "tan", "camel", "rust", "terracotta", "olive", "khaki", "mustard"],

    # Pastels — K-fashion, spring fits
    "pastels": ["baby_pink", "lavender", "mint", "sky_blue", "peach", "lilac", "powder_blue"],

    # Jewel tones — South Asian formal + Western party
    "jewel_tones": ["emerald", "sapphire", "ruby", "amethyst", "teal", "cobalt", "deep_purple"],

    # Festive — South Asian + Middle Eastern occasions
    "festive":  ["golden", "gold", "maroon", "deep_red", "royal_blue", "hot_pink", "fuchsia"],

    # Monochromes — minimalist, East Asian inspired
    "monochrome": ["all_black", "all_white", "all_grey", "tonal_navy", "tonal_beige"],
}

# Pinterest-observed color harmony rules
# (top_color, bottom_color) → compatibility score 0.0–1.0
COLOR_HARMONY_MATRIX: Dict[str, Dict[str, float]] = {
    "white":       {"any": 1.0},
    "black":       {"any": 1.0},
    "cream":       {"any": 0.9},
    "beige":       {"navy": 1.0, "brown": 1.0, "olive": 0.9, "white": 0.9, "black": 0.8},
    "navy":        {"white": 1.0, "beige": 1.0, "grey": 0.9, "light_blue": 0.8, "red": 0.8},
    "grey":        {"white": 1.0, "black": 1.0, "navy": 0.9, "pink": 0.8, "blue": 0.8},
    "mustard":     {"white": 1.0, "navy": 0.9, "brown": 0.9, "olive": 0.8, "black": 0.8},
    "yellow":      {"white": 1.0, "green": 0.9, "navy": 0.8, "brown": 0.7},
    "golden":      {"maroon": 1.0, "deep_red": 1.0, "cream": 0.9, "dark_green": 0.9, "black": 0.8},
    "red":         {"white": 1.0, "black": 1.0, "cream": 0.9, "golden": 0.9, "navy": 0.8},
    "maroon":      {"cream": 1.0, "golden": 1.0, "white": 0.9, "beige": 0.9},
    "green":       {"white": 1.0, "beige": 0.9, "yellow": 0.8, "golden": 0.8},
    "olive":       {"white": 1.0, "beige": 1.0, "camel": 0.9, "brown": 0.9, "black": 0.8},
    "blue":        {"white": 1.0, "grey": 0.9, "beige": 0.8, "navy": 0.7},
    "light_blue":  {"white": 1.0, "navy": 0.9, "grey": 0.8, "beige": 0.8},
    "pink":        {"white": 1.0, "grey": 0.9, "cream": 0.9, "navy": 0.8, "black": 0.8},
    "brown":       {"beige": 1.0, "cream": 1.0, "white": 0.9, "camel": 0.9, "olive": 0.8},
    "orange":      {"white": 1.0, "brown": 0.9, "beige": 0.8, "navy": 0.7},
    "teal":        {"white": 1.0, "cream": 0.9, "beige": 0.8, "golden": 0.8},
    "purple":      {"white": 1.0, "cream": 0.9, "grey": 0.8, "black": 0.8},
    "camel":       {"white": 1.0, "black": 1.0, "navy": 0.9, "brown": 0.8},
}

# ─────────────────────────────────────────────
# LAYERING RULES
# Inspired by Pinterest outfit layering trends
# ─────────────────────────────────────────────

LAYERING_RULES = {
    "south_asian": {
        "dupatta_over": ["salwar_kameez", "lehenga", "anarkali"],
        "waistcoat_over": ["kurta", "panjabi"],
        "shawl_over": ["any"],
    },
    "western": {
        "blazer_over": ["t_shirt", "dress_shirt", "blouse", "turtleneck"],
        "denim_jacket_over": ["t_shirt", "dress", "hoodie"],
        "trench_over": ["any"],
        "cardigan_over": ["t_shirt", "blouse"],
        "hoodie_under": ["jacket", "coat"],
    },
    "middle_eastern": {
        "bisht_over": ["thobe", "dishdasha"],
        "hijab_with": ["abaya", "jalabiya", "kaftan"],
        "belt_over": ["abaya", "kaftan"],
    },
    "east_asian": {
        "haori_over": ["kimono"],
        "vest_over": ["hanfu_shirt"],
        "modern_layer": ["blazer_over_tshirt", "oversized_over_fitted"],
    }
}

# ─────────────────────────────────────────────
# PATTERN MIXING RULES
# What patterns work together (Pinterest-observed)
# ─────────────────────────────────────────────

PATTERN_COMPATIBILITY: Dict[str, List[str]] = {
    "solid":       ["any"],          # solid pairs with everything
    "stripes":     ["solid", "denim"],
    "plaid":       ["solid"],
    "floral":      ["solid", "denim"],
    "geometric":   ["solid"],
    "embroidery":  ["solid"],        # embroidered items need solid base
    "block_print": ["solid"],
    "animal_print":["solid", "denim"],
    "abstract":    ["solid"],
    "checks":      ["solid", "stripes"],
    "polka_dots":  ["solid"],
    "jamdani":     ["solid"],
    "arabesque":   ["solid"],
    "minimal":     ["any"],
}

# ─────────────────────────────────────────────
# WEATHER ENGINE
# ─────────────────────────────────────────────

def get_weather_category(temperature: float, humidity: float) -> str:
    if temperature >= 32 and humidity >= 65:   return "hot_humid"
    elif temperature >= 32:                    return "hot_dry"
    elif temperature >= 20:                    return "mild"
    elif temperature >= 10:                    return "cold"
    else:                                      return "very_cold"

WEATHER_FABRIC_RULES = {
    "hot_humid":  {"prefer": ["cotton", "linen", "muslin", "chambray"],         "avoid": ["wool", "polyester", "velvet", "fleece", "denim"]},
    "hot_dry":    {"prefer": ["cotton", "linen", "chambray"],                   "avoid": ["wool", "velvet", "fleece"]},
    "mild":       {"prefer": ["cotton", "linen", "chiffon", "silk", "denim"],   "avoid": []},
    "cold":       {"prefer": ["wool", "denim", "flannel", "knit", "fleece"],    "avoid": ["linen", "chiffon", "muslin"]},
    "very_cold":  {"prefer": ["wool", "cashmere", "fleece", "down", "thermal"], "avoid": ["linen", "cotton", "chiffon", "muslin"]},
}

WEATHER_COLOR_TRENDS = {
    "hot_humid":  ["white", "cream", "light_blue", "mint", "pastel"],
    "hot_dry":    ["white", "beige", "cream", "light_grey"],
    "mild":       ["any"],
    "cold":       ["navy", "brown", "olive", "rust", "burgundy", "camel"],
    "very_cold":  ["black", "charcoal", "dark_grey", "navy", "deep_burgundy"],
}

# ─────────────────────────────────────────────
# SCORING HELPERS
# ─────────────────────────────────────────────

def normalize(val: Optional[str]) -> str:
    if not val:
        return ""
    return val.lower().replace(" ", "_").replace("-", "_")


def color_harmony_score(color1: str, color2: str) -> float:
    c1, c2 = normalize(color1), normalize(color2)
    if c1 == c2:
        return 0.85  # monochrome — good but not perfect
    row = COLOR_HARMONY_MATRIX.get(c1, {})
    if row.get("any"):
        return row["any"]
    score = row.get(c2)
    if score:
        return score
    # check reverse
    row2 = COLOR_HARMONY_MATRIX.get(c2, {})
    if row2.get("any"):
        return row2["any"]
    return row2.get(c1, 0.4)  # default: low compatibility


def pattern_compatibility_score(pattern1: str, pattern2: str) -> float:
    p1, p2 = normalize(pattern1), normalize(pattern2)
    compatible = PATTERN_COMPATIBILITY.get(p1, [])
    if "any" in compatible or p2 in compatible:
        return 1.0
    compatible2 = PATTERN_COMPATIBILITY.get(p2, [])
    if "any" in compatible2 or p1 in compatible2:
        return 1.0
    return 0.3  # pattern clash


def fabric_score(fabric: Optional[str], weather_cat: str) -> float:
    if not fabric:
        return 0.5
    f = normalize(fabric)
    rules = WEATHER_FABRIC_RULES.get(weather_cat, {})
    if f in [normalize(x) for x in rules.get("prefer", [])]:
        return 1.0
    if f in [normalize(x) for x in rules.get("avoid", [])]:
        return 0.0
    return 0.6


def weather_color_score(color: str, weather_cat: str) -> float:
    trending = WEATHER_COLOR_TRENDS.get(weather_cat, [])
    if "any" in trending or normalize(color) in [normalize(c) for c in trending]:
        return 1.0
    return 0.5


# ─────────────────────────────────────────────
# ITEM SCORER
# ─────────────────────────────────────────────

def score_item(
    item: Dict,
    occasion: str,
    weather_cat: str,
    culture: str,
) -> Tuple[float, Dict]:
    """Score a single item. Returns (score, breakdown)."""

    breakdown = {}
    score = 0.0

    item_color      = normalize(item.get("color", ""))
    item_formality  = normalize(item.get("formality", ""))
    item_culture    = normalize(item.get("culture", ""))
    item_sub        = normalize(item.get("subcategory", ""))
    item_fabric     = item.get("material") or item.get("fabric", "")
    item_pattern    = normalize(item.get("pattern", "solid"))

    # If culture not tagged on item, try to infer from subcategory
    if not item_culture:
        inferred = detect_culture_from_garment(item_sub)
        item_culture = normalize(inferred) if inferred else ""

    # 1. Cultural garment match (+3)
    preferred_garments = [normalize(g) for g in get_occasion_garments(culture, occasion)]
    if preferred_garments and item_sub in preferred_garments:
        score += 3.0
        breakdown["cultural_garment"] = 3.0

    # 2. Auspicious color (+2.5)
    auspicious = [normalize(c) for c in get_auspicious_colors(culture, occasion)]
    if auspicious and item_color in auspicious:
        score += 2.5
        breakdown["auspicious_color"] = 2.5

    # 3. Taboo color penalty (-3)
    taboo = [normalize(c) for c in get_taboo_colors(culture, occasion)]
    if taboo and item_color in taboo:
        score -= 3.0
        breakdown["taboo_color_penalty"] = -3.0

    # 4. Weather-appropriate fabric (+1.5)
    f_score = fabric_score(item_fabric, weather_cat) * 1.5
    score += f_score
    breakdown["fabric_weather"] = round(f_score, 2)

    # 5. Weather-trending color (+1)
    wc_score = weather_color_score(item_color, weather_cat)
    score += wc_score
    breakdown["weather_color"] = wc_score

    # 6. Culture identity match (+1)
    preferred_culture = normalize(culture)
    if item_culture == preferred_culture:
        score += 1.0
        breakdown["culture_match"] = 1.0

    return round(score, 2), breakdown


# ─────────────────────────────────────────────
# OUTFIT SCORER (combines items)
# ─────────────────────────────────────────────

def score_outfit(
    items: List[Dict],
    occasion: str,
    weather_cat: str,
    culture: str,
) -> Tuple[float, Dict]:
    """Score a full outfit combination."""

    total_score = 0.0
    all_breakdowns = {}

    # Score each item individually
    for item in items:
        item_score, breakdown = score_item(item, occasion, weather_cat, culture)
        total_score += item_score
        all_breakdowns[item.get("subcategory", "item")] = breakdown

    # Color harmony bonus (Pinterest rule: good combos get boosted)
    if len(items) >= 2:
        colors = [item.get("color", "") for item in items if item.get("category") != "footwear"]
        if len(colors) >= 2:
            harmony = color_harmony_score(colors[0], colors[1])
            harmony_bonus = harmony * 2.0  # max +2
            total_score += harmony_bonus
            all_breakdowns["color_harmony"] = round(harmony_bonus, 2)

    # Pattern mixing score
    if len(items) >= 2:
        patterns = [item.get("pattern", "solid") for item in items]
        if len(patterns) >= 2:
            pat_score = pattern_compatibility_score(patterns[0], patterns[1]) * 1.5
            total_score += pat_score
            all_breakdowns["pattern_mix"] = round(pat_score, 2)

    # Layering bonus — reward correct cultural layering
    culture_layers = LAYERING_RULES.get(normalize(culture), {})
    item_subs = [normalize(i.get("subcategory", "")) for i in items]
    for layer_key, layer_bases in culture_layers.items():
        layer_item = layer_key.replace("_over", "").replace("_with", "").replace("_under", "")
        if layer_item in item_subs:
            for base in layer_bases:
                if base == "any" or base in item_subs:
                    total_score += 1.0
                    all_breakdowns["layering_bonus"] = 1.0
                    break

    return round(total_score, 2), all_breakdowns


# ─────────────────────────────────────────────
# OUTFIT BUILDER
# ─────────────────────────────────────────────

def build_outfits(
    wardrobe: List[Dict],
    occasion: str,
    temperature: float,
    humidity: float,
    culture: str = "south_asian",
    top_n: int = 3,
) -> List[Dict]:

    weather_cat = get_weather_category(temperature, humidity)
    occasion    = normalize(occasion)
    culture     = normalize(culture)

    # Bucket items by category
    def bucket(categories):
        return [i for i in wardrobe if normalize(i.get("category", "")) in categories]

    tops       = bucket(["top", "shirt", "tops", "upper"])
    bottoms    = bucket(["bottom", "pants", "bottoms", "lower", "skirt"])
    full_body  = bucket(["full_body", "dress", "saree", "sherwani", "abaya", "thobe",
                         "kimono", "hanbok", "qipao", "kaftan", "jumpsuit"])
    footwear   = bucket(["footwear", "shoes", "sandals", "boots"])
    outerwear  = bucket(["outerwear", "jacket", "blazer", "coat", "dupatta", "shawl"])

    outfits = []

    def best_footwear(anchor_color: str) -> Optional[Dict]:
        if not footwear:
            return None
        scored_fw = sorted(
            footwear,
            key=lambda x: color_harmony_score(anchor_color, x.get("color", "")),
            reverse=True
        )
        return scored_fw[0]

    def best_outerwear(base_sub: str, culture_key: str) -> Optional[Dict]:
        if not outerwear:
            return None
        layers = LAYERING_RULES.get(culture_key, {})
        for layer_key, bases in layers.items():
            if base_sub in bases or "any" in bases:
                layer_type = layer_key.replace("_over", "").replace("_with", "")
                match = next((o for o in outerwear if normalize(o.get("subcategory","")) == layer_type), None)
                if match:
                    return match
        return None

    # Strategy A: Full-body outfits
    for fb in full_body:
        outfit_items = [fb]
        fw = best_footwear(fb.get("color", ""))
        if fw:
            outfit_items.append(fw)
        ow = best_outerwear(normalize(fb.get("subcategory", "")), culture)
        if ow:
            outfit_items.append(ow)

        # ── Validate / fix before appending ──────────────────────────────
        is_valid, reason = validate_outfit(outfit_items)
        if not is_valid:
            outfit_items = fix_outfit(outfit_items)
            is_valid, reason = validate_outfit(outfit_items)
            if not is_valid:
                continue  # skip permanently invalid outfits

        total_score, breakdown = score_outfit(outfit_items, occasion, weather_cat, culture)
        outfits.append({
            "type":      "full_body",
            "items":     outfit_items,
            "score":     total_score,
            "breakdown": breakdown,
            "weather":   weather_cat,
            "occasion":  occasion,
        })

    # Strategy B: Top + Bottom combos
    for top in tops:
        for bottom in bottoms:
            outfit_items = [top, bottom]
            fw = best_footwear(top.get("color", ""))
            if fw:
                outfit_items.append(fw)
            ow = best_outerwear(normalize(top.get("subcategory", "")), culture)
            if ow:
                outfit_items.append(ow)

            # ── Validate / fix before appending ──────────────────────────
            is_valid, reason = validate_outfit(outfit_items)
            if not is_valid:
                outfit_items = fix_outfit(outfit_items)
                is_valid, reason = validate_outfit(outfit_items)
                if not is_valid:
                    continue  # skip permanently invalid outfits

            total_score, breakdown = score_outfit(outfit_items, occasion, weather_cat, culture)
            outfits.append({
                "type":      "top_bottom",
                "items":     outfit_items,
                "score":     total_score,
                "breakdown": breakdown,
                "weather":   weather_cat,
                "occasion":  occasion,
            })

    # Sort and return top N
    outfits.sort(key=lambda x: x["score"], reverse=True)
    return outfits[:top_n]


# ─────────────────────────────────────────────
# AI REFINEMENT LAYER (OpenAI)
# Picks the best outfit and explains WHY
# like a real stylist would
# ─────────────────────────────────────────────

async def ai_refine_outfits(
    outfits: List[Dict],
    occasion: str,
    weather_cat: str,
    culture: str,
) -> Dict:
    """
    Takes top scored outfits, sends to OpenAI,
    gets back: best pick + stylist-quality explanation.
    """

    if not outfits:
        return {"best_outfit": None, "stylist_note": "No outfits found."}

    # Build a clean summary for the prompt
    outfit_summaries = []
    for i, outfit in enumerate(outfits):
        items_desc = ", ".join([
            f"{it.get('color','')} {it.get('subcategory', it.get('category','item'))} "
            f"({it.get('material','unknown fabric')}, {it.get('pattern','solid')})"
            for it in outfit["items"]
        ])
        outfit_summaries.append(f"Outfit {i+1} [score {outfit['score']}]: {items_desc}")

    prompt = f"""You are ClosetMate, a personal AI stylist. A user needs an outfit for:
- Occasion: {occasion}
- Weather: {weather_cat}
- Cultural context: {culture}

Here are the top scored outfit options from the wardrobe algorithm:
{chr(10).join(outfit_summaries)}

Your task:
1. Pick the BEST outfit (by number)
2. Write a short, warm, confident stylist note (2-3 sentences) explaining WHY it's the best choice.
   Mention: color harmony, cultural appropriateness, weather suitability.
   Speak like a friendly personal stylist, not a robot.

Respond ONLY in this JSON format:
{{
  "best_outfit_index": 0,
  "stylist_note": "..."
}}"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 300,
                    "temperature": 0.7,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            raw = data["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if present
            raw = raw.replace("```json", "").replace("```", "").strip()
            result = json.loads(raw)

            best_index = result.get("best_outfit_index", 0)
            return {
                "best_outfit": outfits[best_index],
                "all_outfits": outfits,
                "stylist_note": result.get("stylist_note", ""),
                "weather_category": weather_cat,
            }

    except Exception as e:
        # Fallback: return top scored outfit without AI note
        return {
            "best_outfit": outfits[0],
            "all_outfits": outfits,
            "stylist_note": f"Top pick based on your wardrobe for {occasion}.",
            "weather_category": weather_cat,
            "ai_error": str(e),
        }
