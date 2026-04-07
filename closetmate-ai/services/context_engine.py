"""
Multi-cultural context-aware outfit recommendation engine.

Pipeline
--------
1. Fetch user wardrobe from DB
2. Apply cultural rules (occasion → culture + formality)
3. Filter by weather (fabric weight, color safety)
4. Build outfit combinations (top+bottom+footwear, or dress+footwear)
5. Score each combination (color harmony + weather suitability + cultural relevance)
6. Return best_outfit + top-2 alternatives

Modular design — swap the scoring layer for an AI ranker in future.

Version: 1.1.0
- Fixed sqlite3.Row.get() → safe column access via _row_get()
- Added east_asian occasion entries
- Added per-outfit score breakdown in API response
- Hardened user_id type coercion
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cultural rules
# ---------------------------------------------------------------------------

CULTURE_RULES: Dict[str, Dict[str, Any]] = {
    "south_asian": {
        "events": [
            "biye", "wedding", "holud", "dawat", "dinner", "eid",
            "puja", "ceremony", "reception", "mehndi", "akika",
        ],
        "styles": ["traditional", "south_asian"],
        "preferred_fabrics": ["cotton", "silk", "muslin", "chiffon", "linen"],
        "preferred_formalities": ["festive", "formal", "semi-formal"],
    },
    "western": {
        "events": [
            "office", "work", "meeting", "date", "casual", "gym",
            "party", "brunch", "college", "university",
        ],
        "styles": ["western", "global"],
        "preferred_fabrics": ["cotton", "denim", "polyester", "wool", "jersey", "linen"],
        "preferred_formalities": ["casual", "smart casual", "semi-formal", "formal", "sportswear"],
    },
    "middle_eastern": {
        "events": ["jumma", "prayer", "eid", "ceremony", "modest occasion"],
        "styles": ["middle_eastern", "modest"],
        "preferred_fabrics": ["cotton", "linen", "silk", "chiffon"],
        "preferred_formalities": ["formal", "festive", "semi-formal"],
    },
    "east_asian": {
        "events": ["new year", "festival", "ceremony", "celebration", "lunar new year", "chinese new year"],
        "styles": ["east_asian", "traditional"],
        "preferred_fabrics": ["silk", "cotton", "linen", "satin"],
        "preferred_formalities": ["festive", "formal", "semi-formal"],
    },
    "global": {
        "events": [],
        "styles": ["global", "western", "south_asian", "east_asian", "middle_eastern"],
        "preferred_fabrics": [],
        "preferred_formalities": [],
    },
}


# ---------------------------------------------------------------------------
# Occasion → structured context mapping
# ---------------------------------------------------------------------------

_OCCASION_MAP: Dict[str, Dict[str, str]] = {
    # South Asian cultural occasions
    "holud":        {"culture": "south_asian", "formality": "festive"},
    "biye":         {"culture": "south_asian", "formality": "formal"},
    "wedding":      {"culture": "south_asian", "formality": "formal"},
    "dawat":        {"culture": "south_asian", "formality": "semi-formal"},
    "dinner":       {"culture": "south_asian", "formality": "semi-formal"},
    "eid":          {"culture": "south_asian", "formality": "festive"},
    "puja":         {"culture": "south_asian", "formality": "festive"},
    "ceremony":     {"culture": "south_asian", "formality": "formal"},
    "reception":    {"culture": "south_asian", "formality": "formal"},
    "mehndi":       {"culture": "south_asian", "formality": "festive"},
    "akika":        {"culture": "south_asian", "formality": "festive"},
    # Middle Eastern
    "jumma":        {"culture": "middle_eastern", "formality": "formal"},
    "prayer":       {"culture": "middle_eastern", "formality": "formal"},
    # Western everyday
    "office":       {"culture": "western", "formality": "semi-formal"},
    "work":         {"culture": "western", "formality": "semi-formal"},
    "meeting":      {"culture": "western", "formality": "formal"},
    "date":         {"culture": "western", "formality": "smart casual"},
    "brunch":       {"culture": "western", "formality": "casual"},
    "party":        {"culture": "western", "formality": "festive"},
    "college":      {"culture": "western", "formality": "casual"},
    "university":   {"culture": "western", "formality": "casual"},
    "gym":              {"culture": "western", "formality": "sportswear"},
    "workout":          {"culture": "western", "formality": "sportswear"},
    # East Asian
    "lunar new year":   {"culture": "east_asian", "formality": "festive"},
    "chinese new year": {"culture": "east_asian", "formality": "festive"},
    "festival":         {"culture": "east_asian", "formality": "festive"},
    # Universal
    "casual":           {"culture": "global", "formality": "casual"},
    "outdoor":          {"culture": "global", "formality": "casual"},
    "travel":           {"culture": "global", "formality": "casual"},
}


def resolve_occasion(occasion: str) -> Dict[str, str]:
    """Map a raw occasion string to {culture, formality}. Case-insensitive."""
    return _OCCASION_MAP.get(
        occasion.lower().strip(),
        {"culture": "global", "formality": "casual"},
    )


# ---------------------------------------------------------------------------
# Weather thresholds
# ---------------------------------------------------------------------------

_HOT       = 30.0   # °C — prefer lightweight fabrics
_VERY_HOT  = 35.0   # °C — avoid heavy/dark items
_HUMID     = 75.0   # % — prefer breathable fabrics
_RAINY     = 85.0   # % humidity proxy for rain risk

_LIGHT_FABRICS  = {"cotton", "linen", "muslin", "chiffon", "rayon", "jersey"}
_HEAVY_FABRICS  = {"wool", "denim", "velvet", "leather", "tweed", "synthetic"}
_LIGHT_COLORS   = {"white", "off-white", "cream", "ivory", "beige", "light gray"}


def _weather_fabric_ok(material: str, temp: float, humidity: float) -> bool:
    """Return False if this fabric is unsuitable for the weather."""
    mat = (material or "").lower()
    if temp >= _HOT and mat in _HEAVY_FABRICS:
        return False
    return True


def _weather_item_ok(item: sqlite3.Row, temp: float, humidity: float) -> bool:
    """Return False if this item should be excluded for weather reasons."""
    material = (item["material"] or "").lower()
    color    = (item["primary_color"] or "").lower()
    # Avoid heavy fabrics in heat
    if temp >= _HOT and material in _HEAVY_FABRICS:
        return False
    # Avoid light long garments in heavy rain/high humidity
    if humidity >= _RAINY:
        if color in _LIGHT_COLORS:
            log.debug(
                "Weather filter: excluded light-colored item %s (humidity=%.0f%%)",
                item["item_id"][:6], humidity,
            )
            return False
    return True


# ---------------------------------------------------------------------------
# Color harmony
# ---------------------------------------------------------------------------

# RGB approximations for color names
_COLOR_RGB: Dict[str, Tuple[int, int, int]] = {
    "white":       (255, 255, 255),
    "off-white":   (250, 245, 230),
    "cream":       (255, 250, 230),
    "ivory":       (255, 255, 240),
    "black":       (20,  20,  20),
    "charcoal":    (55,  55,  60),
    "gray":        (128, 128, 128),
    "grey":        (128, 128, 128),
    "navy":        (15,  30,  90),
    "blue":        (45,  85,  185),
    "sky blue":    (100, 165, 220),
    "cobalt blue": (0,   71,  171),
    "teal":        (0,   128, 128),
    "green":       (40,  140, 70),
    "olive":       (100, 110, 40),
    "forest green":(34,  100, 34),
    "red":         (200, 30,  30),
    "maroon":      (120, 25,  25),
    "cherry red":  (180, 20,  30),
    "coral":       (230, 100, 80),
    "orange":      (220, 120, 30),
    "mustard":     (195, 160, 40),
    "mustard yellow": (195, 160, 40),
    "yellow":      (235, 215, 40),
    "gold":        (200, 170, 30),
    "pink":        (220, 110, 135),
    "dusty pink":  (200, 150, 155),
    "lavender":    (175, 150, 220),
    "purple":      (130, 50,  180),
    "brown":       (130, 80,  40),
    "beige":       (225, 200, 160),
    "tan":         (210, 180, 140),
    "camel":       (196, 154, 108),
}


def _color_rgb(name: str) -> Optional[Tuple[int, int, int]]:
    n = (name or "").lower().strip()
    for k, v in _COLOR_RGB.items():
        if n == k or n in k or k in n:
            return v
    return None


def _color_distance(a: str, b: str) -> float:
    """Euclidean RGB distance, normalised 0–1. Lower = more similar."""
    ra = _color_rgb(a)
    rb = _color_rgb(b)
    if not ra or not rb:
        return 0.5   # unknown — neutral
    d = sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5
    return d / 441.7   # max distance ≈ sqrt(3*255^2)


def _harmony_score(colors: List[str]) -> float:
    """
    Score 0–1 for how well a set of colors work together.
    Rewards neutral anchors and penalises colours that clash.
    """
    if len(colors) < 2:
        return 0.7

    _NEUTRALS = {"white", "black", "gray", "grey", "charcoal", "navy",
                 "beige", "cream", "off-white", "ivory", "tan", "camel"}

    neutral_count = sum(1 for c in colors if any(n in c.lower() for n in _NEUTRALS))
    scores: List[float] = []
    for i in range(len(colors)):
        for j in range(i + 1, len(colors)):
            d = _color_distance(colors[i], colors[j])
            # Very similar colors (same hue family) → good (monochromatic)
            # Very different (complementary or neutral pair) → also good
            # Mid-range clash territory → penalised
            if d < 0.15:      # nearly identical
                scores.append(0.75)
            elif d > 0.45:    # high contrast / complementary
                scores.append(0.85)
            else:             # moderate difference — can clash
                scores.append(0.55)

    base = sum(scores) / len(scores) if scores else 0.7
    # Bonus for having a neutral anchor
    bonus = min(0.15, neutral_count * 0.08)
    return min(1.0, base + bonus)


# ---------------------------------------------------------------------------
# SQLite Row helpers
# ---------------------------------------------------------------------------

def _row_get(row: sqlite3.Row, key: str, default: str = "") -> str:
    """
    Safe column access for sqlite3.Row.

    sqlite3.Row does not support .get(key, default) — it raises IndexError
    for missing columns.  This helper returns `default` in that case.
    """
    try:
        val = row[key]
        return val if val is not None else default
    except IndexError:
        return default


# ---------------------------------------------------------------------------
# Item helpers
# ---------------------------------------------------------------------------

_BROAD_CATEGORY_GROUPS = {
    "top": {
        "top", "shirt", "t-shirt", "polo", "blouse", "kurta", "panjabi",
        "kameez", "salwar kameez", "outerwear", "hoodie", "sweater",
        "cardigan", "jacket", "blazer", "coat",
    },
    "bottom": {
        "bottom", "jeans", "trousers", "pants", "shorts", "skirt",
        "legging", "salwar", "dhoti", "lungi",
    },
    "dress": {
        "dress", "saree", "lehenga", "abaya", "kimono", "hanfu",
        "cheongsam", "traditional", "sherwani",
    },
    "footwear": {"footwear", "sneakers", "sandals", "boots", "shoes"},
}


def _get_slot(item: sqlite3.Row) -> str:
    """Return broad slot: top / bottom / dress / footwear / other."""
    cat = _row_get(item, "category").lower().strip()
    # subcategory may not exist on every DB version; fall back to cultural_style
    sub_raw = _row_get(item, "subcategory") or _row_get(item, "cultural_style")
    sub = sub_raw.lower().strip()
    for slot, keywords in _BROAD_CATEGORY_GROUPS.items():
        if cat in keywords or sub in keywords:
            return slot
    # Additional heuristics
    if cat in ("traditional",):
        # Distinguish panjabi/kurta (top) from saree/lehenga (dress)
        if sub in ("panjabi", "kurta", "sherwani", "salwar kameez", "kameez"):
            return "top"
        return "dress"
    return "other"


def _item_culture(item: sqlite3.Row) -> str:
    return (_row_get(item, "cultural_style") or "global").lower()


def _item_formality(item: sqlite3.Row) -> str:
    return (_row_get(item, "formality_level") or "casual").lower()


def _item_material(item: sqlite3.Row) -> str:
    return _row_get(item, "material").lower()


def _item_color(item: sqlite3.Row) -> str:
    return _row_get(item, "primary_color").lower()


def _describe(item: sqlite3.Row) -> Dict[str, Any]:
    """Produce a rich description dict for the API response."""
    return {
        "item_id":       _row_get(item, "item_id"),
        "category":      _row_get(item, "category")       or "unknown",
        "subcategory":   _row_get(item, "subcategory")    or "unknown",
        "primary_color": _row_get(item, "primary_color")  or "unknown",
        "material":      _row_get(item, "material")       or "unknown",
        "pattern":       _row_get(item, "pattern")        or "solid",
        "formality":     _row_get(item, "formality_level") or "casual",
        "culture":       _row_get(item, "cultural_style")  or "global",
        "image_path":    _row_get(item, "image_path")     or None,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class OutfitScore:
    color_score:   float = 0.0
    weather_score: float = 0.0
    culture_score: float = 0.0
    total:         float = 0.0


def _score_outfit(
    items: List[sqlite3.Row],
    target_culture: str,
    target_formality: str,
    temp: float,
    humidity: float,
) -> OutfitScore:
    """Score an outfit combination 0–1 on three axes."""
    colors     = [_item_color(i) for i in items if _item_color(i)]
    materials  = [_item_material(i) for i in items]
    cultures   = [_item_culture(i) for i in items]
    formalities = [_item_formality(i) for i in items]

    # 1. Color harmony
    color_score = _harmony_score(colors)

    # 2. Weather suitability
    fabric_scores: List[float] = []
    for mat in materials:
        if temp >= _VERY_HOT:
            fabric_scores.append(1.0 if mat in _LIGHT_FABRICS else 0.2)
        elif temp >= _HOT or humidity >= _HUMID:
            fabric_scores.append(0.9 if mat in _LIGHT_FABRICS else 0.5)
        else:
            fabric_scores.append(0.8)   # neutral in temperate weather
    weather_score = sum(fabric_scores) / len(fabric_scores) if fabric_scores else 0.7

    # 3. Cultural relevance
    culture_rule = CULTURE_RULES.get(target_culture, CULTURE_RULES["global"])
    allowed_styles  = set(culture_rule["styles"])
    preferred_fmls  = set(culture_rule["preferred_formalities"])

    culture_points = 0.0
    for c in cultures:
        if c in allowed_styles or target_culture == "global":
            culture_points += 1.0
        elif "global" in (c, target_culture):
            culture_points += 0.6
        else:
            culture_points += 0.2

    for f in formalities:
        if f == target_formality:
            culture_points += 1.0
        elif f in preferred_fmls:
            culture_points += 0.5
        else:
            culture_points += 0.1

    max_pts = (len(items) + len(formalities)) * 1.0
    culture_score = culture_points / max_pts if max_pts else 0.5
    culture_score = min(1.0, culture_score)

    # Weighted total
    total = 0.35 * color_score + 0.30 * weather_score + 0.35 * culture_score

    return OutfitScore(
        color_score=round(color_score, 3),
        weather_score=round(weather_score, 3),
        culture_score=round(culture_score, 3),
        total=round(total, 3),
    )


# ---------------------------------------------------------------------------
# Outfit builder
# ---------------------------------------------------------------------------

def _build_combinations(
    tops: List[sqlite3.Row],
    bottoms: List[sqlite3.Row],
    dresses: List[sqlite3.Row],
    footwear: List[sqlite3.Row],
    max_combos: int = 9,
) -> List[List[sqlite3.Row]]:
    """Generate candidate outfit combinations."""
    combos: List[List[sqlite3.Row]] = []
    foot_pool = footwear[:2]

    # top + bottom (+ optional footwear)
    for t in tops[:4]:
        for b in bottoms[:4]:
            if len(combos) >= max_combos:
                break
            base = [t, b]
            if foot_pool:
                combos.append(base + [foot_pool[0]])
            else:
                combos.append(base)
        if len(combos) >= max_combos:
            break

    # dress / traditional (+ optional footwear)
    for d in dresses[:3]:
        if len(combos) >= max_combos:
            break
        base = [d]
        if foot_pool:
            combos.append(base + [foot_pool[0]])
        else:
            combos.append(base)

    # Fallback: just top items
    if not combos:
        all_items = tops + dresses
        for item in all_items[:3]:
            combos.append([item])

    return combos


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_outfits(
    user_id: str,
    occasion: str,
    environment: str,
    temperature: float,
    humidity: float,
    db: sqlite3.Connection,
) -> Dict[str, Any]:
    """
    Generate outfit recommendations for a given context.

    Returns:
        {
            "best_outfit":   [item_dict, ...],
            "alternatives":  [[item_dict, ...], ...],
            "scores":        {"best": {...}, "alternatives": [{...}, ...]},
            "context":       {"culture": ..., "formality": ..., "occasion": ...},
            "weather":       {"temperature": ..., "humidity": ..., "advisory": ...},
        }
    """
    log.info(
        "Generating outfits — user=%s occasion=%s temp=%.1f°C humidity=%.0f%%",
        str(user_id), occasion, temperature, humidity,
    )

    # ── 1. Resolve cultural context ──────────────────────────────────────────
    ctx = resolve_occasion(occasion)
    target_culture   = ctx["culture"]
    target_formality = ctx["formality"]
    log.info(
        "Applying cultural rules: occasion=%r → culture=%s formality=%s",
        occasion, target_culture, target_formality,
    )

    # ── 2. Fetch wardrobe ────────────────────────────────────────────────────
    # Coerce user_id to str for consistent DB querying
    uid = str(user_id)
    rows = db.execute(
        "SELECT * FROM wardrobe_items WHERE user_id = ?", (uid,)
    ).fetchall()

    if not rows:
        log.warning("No wardrobe items found for user=%s", uid)
        return {
            "best_outfit":  [],
            "alternatives": [],
            "scores":       {"best": None, "alternatives": []},
            "context":  {"culture": target_culture, "formality": target_formality, "occasion": occasion},
            "weather":  _weather_summary(temperature, humidity),
        }

    # ── 3. Weather filter ────────────────────────────────────────────────────
    log.info(
        "Filtering by weather: temp=%.1f°C humidity=%.0f%% (items before=%d)",
        temperature, humidity, len(rows),
    )
    weather_ok = [r for r in rows if _weather_item_ok(r, temperature, humidity)]
    if len(weather_ok) < 2:
        log.warning(
            "Weather filter too strict (%d items left) — relaxing to use all %d items",
            len(weather_ok), len(rows),
        )
        weather_ok = list(rows)   # relax if we'd end up with nothing
    else:
        log.info("Weather filter: %d/%d items passed", len(weather_ok), len(rows))

    # ── 4. Slot separation ───────────────────────────────────────────────────
    tops     = [r for r in weather_ok if _get_slot(r) == "top"]
    bottoms  = [r for r in weather_ok if _get_slot(r) == "bottom"]
    dresses  = [r for r in weather_ok if _get_slot(r) == "dress"]
    footwear = [r for r in weather_ok if _get_slot(r) == "footwear"]
    log.debug(
        "Slot counts — tops=%d bottoms=%d dresses=%d footwear=%d",
        len(tops), len(bottoms), len(dresses), len(footwear),
    )

    # ── 5. Build combinations ────────────────────────────────────────────────
    combos = _build_combinations(tops, bottoms, dresses, footwear)
    if not combos:
        # Last resort: return top-3 items individually
        combos = [[r] for r in weather_ok[:3]]

    # ── 6. Score & rank ──────────────────────────────────────────────────────
    log.info("Ranking outfits (%d candidates)", len(combos))
    scored: List[Tuple[float, OutfitScore, List[sqlite3.Row]]] = []
    for combo in combos:
        s = _score_outfit(combo, target_culture, target_formality, temperature, humidity)
        log.debug(
            "Combo [%s] → color=%.2f weather=%.2f culture=%.2f total=%.2f",
            ", ".join(_item_color(i) for i in combo),
            s.color_score, s.weather_score, s.culture_score, s.total,
        )
        scored.append((s.total, s, combo))

    scored.sort(key=lambda x: x[0], reverse=True)

    # ── 7. Build response ────────────────────────────────────────────────────
    def _score_dict(s: OutfitScore) -> Dict[str, float]:
        return {
            "color_harmony":      s.color_score,
            "weather_suitability": s.weather_score,
            "cultural_relevance": s.culture_score,
            "total":              s.total,
        }

    best_combo = scored[0][2] if scored else []
    best_score = scored[0][1] if scored else None

    best         = [_describe(i) for i in best_combo]
    alternatives = [
        [_describe(i) for i in combo]
        for _, _s, combo in scored[1:3]
    ]
    alt_scores = [
        _score_dict(s) for _, s, _combo in scored[1:3]
    ]

    log.info(
        "✅ Best outfit: %s (score=%.3f)",
        ", ".join(f"{i['primary_color']} {i['subcategory']}" for i in best),
        best_score.total if best_score else 0.0,
    )

    return {
        "best_outfit":  best,
        "alternatives": alternatives,
        "scores": {
            "best":         _score_dict(best_score) if best_score else None,
            "alternatives": alt_scores,
        },
        "context": {
            "culture":   target_culture,
            "formality": target_formality,
            "occasion":  occasion,
        },
        "weather": _weather_summary(temperature, humidity),
    }


def _weather_summary(temperature: float, humidity: float) -> Dict[str, Any]:
    if temperature >= _VERY_HOT:
        advisory = "Very hot — lightweight breathable fabrics recommended"
    elif temperature >= _HOT:
        advisory = "Hot — prefer cotton, linen, or chiffon"
    elif humidity >= _RAINY:
        advisory = "High humidity — avoid light-coloured long garments"
    elif humidity >= _HUMID:
        advisory = "Humid — breathable fabrics preferred"
    else:
        advisory = "Comfortable conditions — no fabric restrictions"

    return {
        "temperature": temperature,
        "humidity":    humidity,
        "advisory":    advisory,
    }
