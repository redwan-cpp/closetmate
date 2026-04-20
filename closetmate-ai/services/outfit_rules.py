# services/outfit_rules.py
# ─────────────────────────────────────────────────────────────────
# Hard outfit combination rules.
# These are ABSOLUTE — no AI or scoring can override them.
# Based on South Asian + Western cultural norms.
# ─────────────────────────────────────────────────────────────────

from typing import List, Dict, Tuple, Optional

# ─────────────────────────────────────────────
# GARMENT FAMILY DEFINITIONS
# Each garment belongs to exactly one family.
# Families define what can pair with what.
# ─────────────────────────────────────────────

GARMENT_FAMILIES = {

    # ── South Asian complete garments (need NO bottom) ──
    "sa_complete": [
        "saree", "sari",
        "lehenga",           # lehenga comes with its own skirt
        "anarkali",          # long enough to be standalone
        "sharara",           # wide-leg palazzo-style, standalone
        "gharara",           # standalone
        "maxi_dress",
    ],

    # ── South Asian tops (MUST pair with sa_bottom or sa_complete_bottom) ──
    "sa_top": [
        "panjabi", "punjabi",
        "kurta", "kurti",
        "fatua",
        "kameez",
        "blouse",            # saree blouse — only pairs with saree
        "choli",             # lehenga choli — only pairs with lehenga
        "salwar_kameez_top",
    ],

    # ── South Asian bottoms (pair ONLY with sa_top) ──
    "sa_bottom": [
        "pajama", "pyjama",
        "churidar",
        "salwar",
        "dhoti",
        "lungi",
        "palazzo",
        "sharara_bottom",
    ],

    # ── Western complete garments (no bottom needed) ──
    "western_complete": [
        "dress",
        "jumpsuit",
        "romper",
        "gown",
        "maxi",
        "mini_dress",
        "midi_dress",
    ],

    # ── Western tops ──
    "western_top": [
        "t_shirt", "tshirt",
        "shirt",
        "dress_shirt",
        "blouse",
        "polo",
        "sweater",
        "hoodie",
        "sweatshirt",
        "crop_top",
        "tank_top",
        "cardigan",
        "blazer",
    ],

    # ── Western bottoms ──
    "western_bottom": [
        "jeans",
        "trousers",
        "pants",
        "chinos",
        "shorts",
        "skirt",
        "pencil_skirt",
        "leggings",
        "sweatpants",
        "cargo_pants",
    ],

    # ── Middle Eastern complete ──
    "me_complete": [
        "thobe", "dishdasha", "kandura",
        "abaya",
        "kaftan", "caftan",
        "jalabiya",
        "jilbab",
    ],

    # ── East Asian complete ──
    "ea_complete": [
        "saree",
        "kimono",
        "yukata",
        "qipao", "cheongsam",
        "hanbok",
        "ao_dai",
    ],

    # ── Outerwear (layers over anything) ──
    "outerwear": [
        "jacket",
        "coat",
        "blazer",
        "waistcoat",
        "vest",
        "dupatta",
        "shawl",
        "orna",
        "denim_jacket",
        "trench_coat",
        "puffer",
        "cardigan",
        "bisht",
        "haori",
    ],

    # ── Footwear (pairs with anything) ──
    "footwear": [
        "shoes", "shoe",
        "sandals", "sandal",
        "boots", "boot",
        "sneakers", "sneaker",
        "heels", "heel",
        "loafers", "loafer",
        "oxfords",
        "kolhapuri",
        "nagra",
        "mojari",
        "flip_flops",
        "slippers",
    ],
}

# ─────────────────────────────────────────────
# ABSOLUTE INCOMPATIBILITY RULES
# (garment_family_1, garment_family_2) → reason
# These combos are ALWAYS rejected.
# ─────────────────────────────────────────────

INCOMPATIBLE_PAIRS: List[Tuple[str, str, str]] = [

    # Saree / complete SA garments + any separate bottom = NEVER
    ("sa_complete",      "sa_bottom",       "A saree or lehenga is a complete garment — never pair with a separate bottom"),
    ("sa_complete",      "western_bottom",  "A saree or lehenga cannot be worn with pants, jeans, or skirts"),
    ("sa_complete",      "sa_top",          "A saree or lehenga does not need a separate top (blouse/choli is part of the set)"),

    # Western complete + anything below = NEVER
    ("western_complete", "western_bottom",  "A dress or jumpsuit is complete — never pair with separate pants or skirts"),
    ("western_complete", "sa_bottom",       "A dress cannot be paired with salwar or pajama"),
    ("western_complete", "western_top",     "A dress does not need a separate top"),
    ("western_complete", "sa_top",          "A dress cannot be paired with a kurta or panjabi"),

    # ME/EA complete + bottoms = NEVER
    ("me_complete",      "western_bottom",  "A thobe or abaya is a complete garment — no separate pants"),
    ("me_complete",      "sa_bottom",       "A kaftan or abaya does not pair with salwar or pajama"),
    ("ea_complete",      "western_bottom",  "A kimono or qipao is a complete garment — no separate pants"),
    ("ea_complete",      "sa_bottom",       "A kimono or qipao does not pair with salwar"),

    # Cross-cultural tops + bottoms = NEVER
    ("sa_top",           "western_bottom",  "Traditional South Asian tops like panjabi/kurta are not worn with jeans or trousers — pair with pajama or churidar"),
    ("western_top",      "sa_bottom",       "Western tops like t-shirts or shirts are not worn with salwar or pajama — pair with jeans or trousers"),

    # Blouse/choli without their pair = flag
    # (these are handled in REQUIRED_PAIRS below)
]

# ─────────────────────────────────────────────
# REQUIRED PAIRS
# Some garments MUST come with a specific partner.
# ─────────────────────────────────────────────

REQUIRED_PAIRS: Dict[str, Dict] = {
    "blouse": {
        "must_pair_with": ["saree", "sari"],
        "reason": "A saree blouse is only worn with a saree",
    },
    "choli": {
        "must_pair_with": ["lehenga"],
        "reason": "A choli is only worn with a lehenga",
    },
    "salwar_kameez_top": {
        "must_pair_with": ["salwar", "churidar", "palazzo"],
        "reason": "Salwar kameez top must be worn with matching salwar or churidar",
    },
}

# ─────────────────────────────────────────────
# HELPER: get family for a garment
# ─────────────────────────────────────────────

def get_family(subcategory: str) -> Optional[str]:
    sub = subcategory.lower().replace(" ", "_").replace("-", "_")
    for family, members in GARMENT_FAMILIES.items():
        if sub in members:
            return family
    return None


# ─────────────────────────────────────────────
# MAIN VALIDATOR
# Call this before returning ANY outfit to user.
# Returns (is_valid, reason)
# ─────────────────────────────────────────────

def validate_outfit(items: List[Dict]) -> Tuple[bool, str]:
    """
    Validates a list of clothing items against hard combination rules.
    Returns (True, "") if valid, (False, reason) if invalid.
    """

    # Get families for all non-footwear, non-outerwear items
    core_items = [
        i for i in items
        if get_family(i.get("subcategory", "")) not in ("footwear", "outerwear", None)
    ]

    families = []
    for item in core_items:
        sub = item.get("subcategory", "")
        family = get_family(sub)
        if family:
            families.append((family, sub, item))

    # Check every pair of core items against incompatibility rules
    for i in range(len(families)):
        for j in range(i + 1, len(families)):
            f1, sub1, _ = families[i]
            f2, sub2, _ = families[j]

            for (bad_f1, bad_f2, reason) in INCOMPATIBLE_PAIRS:
                if (f1 == bad_f1 and f2 == bad_f2) or (f1 == bad_f2 and f2 == bad_f1):
                    return False, f"Cannot pair {sub1} with {sub2}: {reason}"

    # Check required pairs
    for item in core_items:
        sub = item.get("subcategory", "").lower().replace(" ", "_")
        if sub in REQUIRED_PAIRS:
            rule = REQUIRED_PAIRS[sub]
            partner_subs = [i.get("subcategory", "").lower() for i in core_items]
            if not any(p in partner_subs for p in rule["must_pair_with"]):
                return False, rule["reason"]

    return True, ""


# ─────────────────────────────────────────────
# OUTFIT FIXER
# Tries to auto-fix common wrong combos
# by removing the offending item.
# ─────────────────────────────────────────────

def fix_outfit(items: List[Dict]) -> List[Dict]:
    """
    Attempts to auto-fix an invalid outfit by removing
    the item that violates the rules.
    """
    is_valid, reason = validate_outfit(items)
    if is_valid:
        return items

    core_items = [i for i in items if get_family(i.get("subcategory","")) not in ("footwear","outerwear",None)]
    footwear_outerwear = [i for i in items if get_family(i.get("subcategory","")) in ("footwear","outerwear")]

    complete_families = ["sa_complete", "western_complete", "me_complete", "ea_complete"]

    # If there's a complete garment, strip all bottoms and extra tops
    complete_items = [i for i in core_items if get_family(i.get("subcategory","")) in complete_families]
    if complete_items:
        # Keep only the complete garment + footwear/outerwear
        return complete_items[:1] + footwear_outerwear

    # Otherwise remove the last added item that caused the conflict
    for i in range(len(core_items) - 1, -1, -1):
        candidate = core_items[:i] + core_items[i+1:]
        test_valid, _ = validate_outfit(candidate + footwear_outerwear)
        if test_valid:
            return candidate + footwear_outerwear

    return items  # fallback — return as-is if can't fix
