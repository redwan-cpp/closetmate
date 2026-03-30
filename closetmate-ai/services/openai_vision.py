"""
OpenAI Vision service for clothing metadata extraction.

Uses GPT-4o-mini to analyze clothing images and return structured metadata.
Falls back gracefully if the API key is missing or the call fails.
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
# Env loading — same robust 3-layer approach as metadata_extractor
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
# Model — single source of truth, never changes to another model
# ---------------------------------------------------------------------------

_OPENAI_MODEL = "gpt-4o-mini"  # locked; do NOT change to any other model

_REQUIRED_FIELDS = {"category", "subcategory", "primary_color", "pattern", "material", "formality", "culture"}

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an expert fashion analyst with deep knowledge of global clothing styles. "
    "Your task is to carefully examine clothing items in images and return STRICT JSON only — "
    "no markdown, no explanation, no extra text whatsoever. "
    "Be precise and specific in your analysis. Never guess category from context — analyze the garment itself."
)

_USER_PROMPT = """\
Carefully analyze the clothing item visible in this image and return a JSON object with EXACTLY these 7 keys:

"category"     — broad category (pick ONE): top, bottom, footwear, dress, outerwear, accessory, traditional
"subcategory"  — specific garment type: shirt, panjabi, kurta, saree, lehenga, salwar, t-shirt, polo, tank top, jeans, trousers, shorts, skirt, dress, blazer, suit, jacket, coat, cardigan, hoodie, sweater, sneakers, sandals, boots, etc.
"primary_color"— the single most dominant color of the garment. Be specific: e.g. "mustard yellow", "navy blue", "cherry red", "forest green", "charcoal gray", "ivory white"
"pattern"      — surface pattern (pick ONE): solid, striped, floral, checked, plaid, polka dot, printed, embroidered, graphic, abstract, color block, animal print, camouflage, tie-dye, paisley, houndstooth, geometric, lace, sequined
"material"     — most likely fabric: cotton, silk, denim, linen, polyester, wool, leather, chiffon, velvet, rayon, knit, jersey, tweed, synthetic, unknown
"formality"    — ONE of: casual, smart casual, semi-formal, formal, festive, sportswear
"culture"      — cultural origin or style: south_asian, western, east_asian, middle_eastern, global

Rules:
- Return ONLY the JSON object, nothing else.
- All 7 keys must be present.
- Values must be plain strings (no arrays, no objects)."""


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def analyze_clothing_with_openai(image_base64: str) -> Optional[dict]:
    """
    Send a base64-encoded image to GPT-4o-mini and get structured clothing metadata.

    Args:
        image_base64: Base64-encoded JPEG/PNG image string (no data URL prefix).

    Returns:
        dict with keys: category, subcategory, primary_color, pattern,
                        material, formality, culture
        or None if the call fails.
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

    log.info("Using OpenAI Vision (%s)...", _OPENAI_MODEL)

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
                                "detail": "auto",  # auto selects best quality for accuracy
                            },
                        },
                    ],
                },
            ],
            max_tokens=400,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        log.debug("OpenAI raw response: %s", raw[:500])

        # Strip markdown fences if model wraps in ```json ... ```
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(ln for ln in lines if not ln.strip().startswith("```")).strip()

        result = json.loads(raw)

        def _clean(v: object) -> Optional[str]:
            s = str(v).strip() if v else ""
            return s if s else None

        out = {
            "category":      _clean(result.get("category")),
            "subcategory":   _clean(result.get("subcategory")),
            "primary_color": _clean(result.get("primary_color")),
            "pattern":       _clean(result.get("pattern")),
            "material":      _clean(result.get("material")),
            "formality":     _clean(result.get("formality")),
            "culture":       _clean(result.get("culture")),
        }

        # Validate all required fields are present and non-empty
        missing = [k for k in _REQUIRED_FIELDS if not out.get(k)]
        if missing:
            log.error("OpenAI response missing required fields: %s — raw: %s", missing, raw[:300])
            return None

        log.info("✅ OpenAI Vision (%s) result: %s", _OPENAI_MODEL, out)
        return out

    except json.JSONDecodeError as exc:
        log.error("OpenAI returned invalid JSON: %s", exc)
        return None
    except Exception as exc:
        log.error("OpenAI Vision call failed: %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Helper: bytes → base64 JPEG string (resized for speed + cost)
# ---------------------------------------------------------------------------

def image_bytes_to_base64(image_bytes: bytes, max_size: int = 768) -> str:
    """
    Convert raw image bytes to a base64 JPEG string.
    Resizes to max_size on the longest side to reduce token cost and latency.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    # Resize preserving aspect ratio
    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")
