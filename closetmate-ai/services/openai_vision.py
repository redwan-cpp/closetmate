"""
OpenAI Vision service for multi-cultural clothing metadata extraction.

Uses GPT-4o-mini with strict JSON output to analyse garments from any cultural
tradition (South Asian, Western, Middle Eastern, East Asian, etc.) and return
normalised structured metadata.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import pathlib
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env loader — 3-layer: env var → dotenv → manual parse
# ---------------------------------------------------------------------------

def _load_env_key(key: str) -> Optional[str]:
    val = os.getenv(key)
    if val:
        return val
    try:
        from dotenv import load_dotenv
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        load_dotenv(dotenv_path=env_path, override=True)
        val = os.getenv(key)
        if val:
            return val
    except Exception:
        pass
    env_path = pathlib.Path(__file__).parent.parent / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.strip().strip('"').strip("'")
                if k.strip() == key and v:
                    os.environ[key] = v
                    return v
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------

_OPENAI_MODEL = "gpt-4o-mini"   # locked — never switch to another model

_REQUIRED_FIELDS = {
    "category", "subcategory", "culture",
    "primary_color", "material", "pattern", "formality",
}


# ---------------------------------------------------------------------------
# Synonym / normalisation tables
# ---------------------------------------------------------------------------

# Maps raw AI output → canonical value (all lowercase comparisons)
_SUBCATEGORY_SYNONYMS: dict[str, str] = {
    # South Asian
    "kurta":           "panjabi",
    "punjabi":         "panjabi",
    "panjabi shirt":   "panjabi",
    "tshirt":          "t-shirt",
    "t shirt":         "t-shirt",
    "tee":             "t-shirt",
    "tee shirt":       "t-shirt",
    "polo shirt":      "polo",
    "button down":     "shirt",
    "button-down":     "shirt",
    "button up":       "shirt",
    "dress shirt":     "shirt",
    "salwar":          "salwar kameez",
    "shalwar kameez":  "salwar kameez",
    "shalwar":         "salwar kameez",
    "kameez":          "salwar kameez",
    "lehenga choli":   "lehenga",
    "ghagra":          "lehenga",
    "sherwani coat":   "sherwani",
    "sherwaani":       "sherwani",
    "saari":           "saree",
    "sari":            "saree",
    # Western
    "trousers":        "trousers",
    "pants":           "trousers",
    "slacks":          "trousers",
    "chinos":          "trousers",
    "sweatshirt":      "hoodie",
    "pullover":        "sweater",
    "jumper":          "sweater",
    "overcoat":        "coat",
    "parka":           "jacket",
    "windbreaker":     "jacket",
    "denim jacket":    "jacket",
    "blouse":          "blouse",
    # Middle Eastern
    "thobe":           "thobe",
    "thoub":           "thobe",
    "dishdasha":       "thobe",
    "jalabiya":        "jalabiya",
    "hijab dress":     "abaya",
    # East Asian
    "qipao":           "cheongsam",
    "hanfu robe":      "hanfu",
}

_CULTURE_SYNONYMS: dict[str, str] = {
    "south asian":       "south_asian",
    "southasian":        "south_asian",
    "indian":            "south_asian",
    "bangladeshi":       "south_asian",
    "pakistani":         "south_asian",
    "western":           "western",
    "european":          "western",
    "american":          "western",
    "east asian":        "east_asian",
    "eastasian":         "east_asian",
    "chinese":           "east_asian",
    "japanese":          "east_asian",
    "korean":            "east_asian",
    "middle eastern":    "middle_eastern",
    "middleeastern":     "middle_eastern",
    "arab":              "middle_eastern",
    "arabic":            "middle_eastern",
    "global":            "global",
    "universal":         "global",
    "unisex":            "global",
}

_CATEGORY_SYNONYMS: dict[str, str] = {
    "upper body":    "top",
    "upper-body":    "top",
    "shirt":         "top",
    "lower body":    "bottom",
    "lower-body":    "bottom",
    "pants":         "bottom",
    "full body":     "dress",
    "full-body":     "dress",
    "one piece":     "dress",
    "one-piece":     "dress",
    "shoes":         "footwear",
    "shoe":          "footwear",
    "sneakers":      "footwear",
    "boots":         "footwear",
    "sandals":       "footwear",
    "outer":         "outerwear",
    "outer layer":   "outerwear",
    "sari":          "traditional",
    "saree":         "traditional",
    "panjabi":       "traditional",
    "sherwani":      "traditional",
    "lehenga":       "traditional",
    "abaya":         "traditional",
    "thobe":         "traditional",
    "kimono":        "traditional",
    "hanfu":         "traditional",
    "cheongsam":     "traditional",
}

_FORMALITY_SYNONYMS: dict[str, str] = {
    "traditional":   "festive",
    "formal wear":   "formal",
    "casual wear":   "casual",
    "sport":         "sportswear",
    "athletic":      "sportswear",
    "activewear":    "sportswear",
    "semi formal":   "semi-formal",
    "smart-casual":  "smart casual",
}


def _normalise(value: str, table: dict[str, str]) -> str:
    """Lowercase match against synonym table; return original if not found."""
    lower = value.lower().strip()
    return table.get(lower, lower)


def _normalise_result(raw: dict) -> dict:
    """Apply synonym tables and lowercase normalisation to all fields."""
    def _s(v: object) -> str:
        return str(v).strip().lower() if v else ""

    subcategory = _normalise(_s(raw.get("subcategory")), _SUBCATEGORY_SYNONYMS)
    culture     = _normalise(_s(raw.get("culture")),     _CULTURE_SYNONYMS)
    category    = _normalise(_s(raw.get("category")),    _CATEGORY_SYNONYMS)
    formality   = _normalise(_s(raw.get("formality")),   _FORMALITY_SYNONYMS)

    return {
        "category":      category      or "unknown",
        "subcategory":   subcategory   or "unknown",
        "culture":       culture       or "global",
        "primary_color": _s(raw.get("primary_color")) or "unknown",
        "material":      _s(raw.get("material"))      or "unknown",
        "pattern":       _s(raw.get("pattern"))       or "solid",
        "formality":     formality     or "casual",
    }


# ---------------------------------------------------------------------------
# Prompts — multicultural, high-accuracy
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a professional global fashion expert with deep expertise in clothing from every major culture and tradition.

Your role is to analyze the clothing item shown in the image and return precise metadata as strict JSON.

You MUST:
- Correctly identify South Asian clothing: panjabi, saree, salwar kameez, lehenga, sherwani, kurta, dhoti, lungi
- Correctly identify Western clothing: shirt, t-shirt, blazer, jeans, trousers, hoodie, coat, dress, skirt
- Correctly identify Middle Eastern clothing: abaya, thobe, jalabiya, keffiyeh
- Correctly identify East Asian clothing: kimono, hanfu, cheongsam, hanbok, ao dai
- Correctly identify the dominant visible color — never say "unknown" if color is clearly visible
- Never guess randomly. If genuinely uncertain, pick the closest known category.

Return STRICT JSON ONLY. No markdown, no explanation, no extra text."""

_USER_PROMPT = """\
Analyze the clothing item in this image. Return a JSON object with EXACTLY these 7 fields:

"category"     — ONE of: top, bottom, footwear, dress, outerwear, accessory, traditional
"subcategory"  — specific garment: panjabi, saree, salwar kameez, lehenga, sherwani, t-shirt, shirt, polo, blazer, suit, jacket, coat, hoodie, sweater, cardigan, jeans, trousers, shorts, skirt, dress, abaya, thobe, kimono, hanfu, cheongsam, sneakers, sandals, boots, other
"culture"      — ONE of: south_asian, western, east_asian, middle_eastern, global
"primary_color"— the single dominant garment color, be specific (e.g. "mustard yellow", "navy blue", "ivory white", "forest green", "cherry red", "charcoal gray")
"material"     — most likely fabric: cotton, silk, denim, linen, polyester, wool, leather, chiffon, velvet, rayon, knit, jersey, synthetic, unknown
"pattern"      — ONE of: solid, striped, floral, checked, plaid, polka dot, printed, embroidered, graphic, abstract, color block, animal print, camouflage, tie-dye, paisley, houndstooth, geometric, lace, sequined
"formality"    — ONE of: casual, smart casual, semi-formal, formal, festive, sportswear

Rules:
- All 7 keys must be present.
- All values must be plain strings (no arrays, no nested objects).
- Return ONLY the JSON object."""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_clothing_with_openai(image_base64: str) -> Optional[dict]:
    """
    Send a base64-encoded clothing image to GPT-4o-mini.

    Returns a normalised dict with 7 keys:
        category, subcategory, culture, primary_color, material, pattern, formality
    Returns None if the call fails or the API key is missing.
    """
    api_key = _load_env_key("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set — skipping OpenAI Vision")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        log.error("openai package not installed — run: pip install openai")
        return None

    log.info("Using OpenAI Vision (%s) — multicultural mode", _OPENAI_MODEL)

    client = OpenAI(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _USER_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high",  # high detail for accurate cultural recognition
                            },
                        },
                    ],
                },
            ],
            max_tokens=400,
            temperature=0.1,   # low temp = deterministic, consistent output
        )

        raw = response.choices[0].message.content.strip()
        log.debug("OpenAI raw response: %.500s", raw)

        # Strip markdown code fences if the model wraps in ```json … ```
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(ln for ln in lines if not ln.strip().startswith("```")).strip()

        parsed = json.loads(raw)

        # Validate all required fields are present before normalising
        missing = [f for f in _REQUIRED_FIELDS if not str(parsed.get(f, "")).strip()]
        if missing:
            log.error(
                "OpenAI response missing required fields %s — raw: %.300s", missing, raw
            )
            return None

        result = _normalise_result(parsed)
        log.info(
            "Detected clothing: %s, culture: %s | full=%s",
            result["subcategory"], result["culture"], result,
        )
        return result

    except json.JSONDecodeError as exc:
        log.error("OpenAI returned invalid JSON: %s", exc)
        return None
    except Exception as exc:
        log.error("OpenAI Vision call failed: %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Image helper — bytes → resized base64 JPEG
# ---------------------------------------------------------------------------

def image_bytes_to_base64(image_bytes: bytes, max_size: int = 1024) -> str:
    """
    Convert raw image bytes to a base64 JPEG string.
    Resizes to max_size on the longest side.
    1024 px gives good cultural detail recognition without excessive token cost.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
