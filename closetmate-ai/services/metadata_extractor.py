"""
Clothing metadata extraction service.

Pipeline:
  PRIMARY  → OpenAI Vision (GPT-4o-mini) — full 7-field metadata in one call
  FALLBACK → Hybrid classifier (CV rules + MobileNetV3) + Gemini details + CV KMeans color
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import pathlib
from typing import Optional

import numpy as np
import requests as _requests
from PIL import Image
from rembg import remove

from services.clothing_classifier import classifier as _hybrid_classifier

log = logging.getLogger(__name__)


def get_image_hash(image_bytes: bytes) -> str:
    """Return the MD5 hex digest of raw image bytes — used as cache key."""
    return hashlib.md5(image_bytes).hexdigest()




# ---------------------------------------------------------------------------
# Robust .env loading — works regardless of how/where uvicorn is launched
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
    # Direct .env parse — no dependency needed
    env_path = pathlib.Path(__file__).parent.parent / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.strip().strip('"').strip("'")
                if k.strip() == key:
                    os.environ[key] = v
                    return v
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Gemini REST endpoints — tried in order, first success wins
# ---------------------------------------------------------------------------

_GEMINI_ENDPOINTS = [
    ("gemini-2.0-flash",
     "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"),
    ("gemini-2.0-flash-lite",
     "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"),
    ("gemini-1.5-flash",
     "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent"),
    ("gemini-1.5-flash-8b",
     "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash-8b:generateContent"),
    ("gemini-1.5-flash-latest",
     "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash-latest:generateContent"),
]

# Gemini is asked ONLY about visual details — not category (that's the hybrid classifier's job)
_GEMINI_DETAILS_PROMPT = """\
You are an expert fashion analyst. Look at this clothing image and return a single JSON object with EXACTLY these three keys:

"pattern" — the surface pattern. Be specific:
  solid, striped, pinstripe, vertical stripes, horizontal stripes,
  plaid, checked, houndstooth, tartan,
  floral, botanical, tropical,
  paisley, ikat, batik, tie-dye,
  geometric, abstract, color block,
  polka dot, heart print, star print,
  animal print, leopard print, zebra print, camouflage,
  graphic print, text print, logo print,
  embroidered, sequined, lace, quilted, ombre,
  other (describe briefly if truly unique)

"primary_color" — dominant garment color, be specific:
  e.g. "navy blue", "olive green", "burnt orange", "cherry red", "dusty pink",
  "cream", "charcoal gray", "burgundy", "cobalt blue", "coral pink"

"formality_level" — ONE of: casual, smart casual, formal, semi-formal, traditional, sportswear

Return ONLY the JSON object. No markdown, no explanation."""


def _gemini_get_details_sync(image_bytes: bytes) -> Optional[dict]:
    """
    Call Gemini to get pattern, primary_color, formality_level only.
    Category is NOT asked — handled by hybrid classifier.
    Returns dict or None on failure.
    """
    api_key = _load_env_key("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set — skipping Gemini refinement")
        return None

    log.info("Calling Gemini for pattern/color/formality (key len=%d)...", len(api_key))

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        log.error("Failed to encode image for Gemini: %s", exc)
        return None

    payload = {
        "contents": [{
            "parts": [
                {"text": _GEMINI_DETAILS_PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64_image}},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 200,
        },
    }

    for model_id, url in _GEMINI_ENDPOINTS:
        try:
            resp = _requests.post(url, params={"key": api_key}, json=payload, timeout=30)
            if resp.status_code == 429:
                log.warning("Quota exceeded for %s — trying next...", model_id)
                continue
            if resp.status_code != 200:
                log.error("Gemini %s error %d: %s", model_id, resp.status_code, resp.text[:300])
                continue

            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(ln for ln in lines if not ln.strip().startswith("```")).strip()

            result = json.loads(text)

            def _clean(v: object) -> Optional[str]:
                s = str(v).strip() if v else ""
                return s if s else None

            out = {
                "pattern":         _clean(result.get("pattern")),
                "primary_color":   _clean(result.get("primary_color")),
                "formality_level": _clean(result.get("formality_level")),
            }
            log.info("✅ Gemini (%s) details: %s", model_id, out)
            return out

        except json.JSONDecodeError as exc:
            log.error("Gemini %s invalid JSON: %s", model_id, exc)
            continue
        except Exception as exc:
            log.error("Gemini %s failed: %s: %s", model_id, type(exc).__name__, exc)
            continue

    log.error("All Gemini endpoints failed")
    return None


# ---------------------------------------------------------------------------
# CV color fallback (runs in parallel with Gemini for speed)
# ---------------------------------------------------------------------------

_COLOR_PALETTE = [
    ("white",     (255, 255, 255)),
    ("black",     (15,  15,  15)),
    ("gray",      (128, 128, 128)),
    ("charcoal",  (55,  55,  60)),
    ("off-white", (230, 225, 210)),
    ("cream",     (245, 240, 210)),
    ("beige",     (220, 195, 155)),
    ("red",       (200, 30,  30)),
    ("maroon",    (110, 25,  25)),
    ("pink",      (220, 105, 130)),
    ("coral",     (220, 100, 80)),
    ("orange",    (220, 120, 30)),
    ("mustard",   (190, 155, 40)),
    ("yellow",    (235, 215, 45)),
    ("olive",     (95,  110, 40)),
    ("green",     (40,  140, 70)),
    ("teal",      (0,   120, 115)),
    ("navy",      (15,  30,  90)),
    ("blue",      (45,  85,  185)),
    ("sky blue",  (100, 170, 230)),
    ("purple",    (130, 50,  180)),
    ("lavender",  (175, 150, 220)),
    ("brown",     (130, 80,  40)),
]


def _nearest_color(rgb: tuple) -> str:
    r, g, b = rgb
    best, dist = "unknown", float("inf")
    for name, (pr, pg, pb) in _COLOR_PALETTE:
        d = 2*(r-pr)**2 + 4*(g-pg)**2 + 3*(b-pb)**2
        if d < dist:
            dist = d
            best = name
    return best


def _rgb_to_hsl(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[:, 0]/255.0, rgb[:, 1]/255.0, rgb[:, 2]/255.0
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    l = (cmax + cmin) / 2.0
    s = np.where(delta == 0, 0.0, delta / (1.0 - np.abs(2*l - 1) + 1e-8))
    s = np.clip(s, 0, 1)
    h = np.zeros(len(r), dtype=np.float32)
    mr = (cmax == r) & (delta > 0)
    mg = (cmax == g) & (delta > 0)
    mb = (cmax == b) & (delta > 0)
    h[mr] = (60 * ((g[mr]-b[mr]) / delta[mr])) % 360
    h[mg] = (60 * ((b[mg]-r[mg]) / delta[mg]) + 120) % 360
    h[mb] = (60 * ((r[mb]-g[mb]) / delta[mb]) + 240) % 360
    return np.stack([h, s, l], axis=1)


def _dominant_color_from_rgba(rembg_img: Image.Image, orig_img: Image.Image) -> str:
    alpha = np.array(rembg_img.convert("RGBA"), dtype=np.float32)[:, :, 3].reshape(-1)
    rgb_flat = np.array(orig_img.convert("RGB"), dtype=np.float32).reshape(-1, 3)
    mask = alpha >= 200
    rgb = rgb_flat[mask]
    if len(rgb) < 10:
        rgb = rgb_flat[alpha >= 100]
    if len(rgb) < 10:
        return "unknown"
    rgb = rgb[rgb.sum(axis=1) >= 60]
    if len(rgb) < 10:
        return "unknown"
    hsl = _rgb_to_hsl(rgb)
    keep = (hsl[:, 1] > 0.08) | (hsl[:, 2] < 0.25)
    rgb = rgb[keep] if keep.sum() >= 50 else rgb
    if len(rgb) > 20000:
        rgb = rgb[np.random.default_rng(42).choice(len(rgb), 20000, replace=False)]
    n_k = min(6, len(rgb))
    rng = np.random.default_rng(42)
    centers = rgb[rng.choice(len(rgb), n_k, replace=False)].copy()
    assignments = np.zeros(len(rgb), dtype=np.int32)
    for _ in range(40):
        diffs = rgb[:, None, :] - centers[None, :, :]
        assignments = np.argmin(np.sum(diffs**2, axis=2), axis=1)
        new_c = np.array([
            rgb[assignments == k].mean(axis=0) if (assignments == k).any() else centers[k]
            for k in range(n_k)
        ])
        if np.allclose(centers, new_c, atol=0.5):
            break
        centers = new_c
    w = np.bincount(assignments, minlength=n_k) / max(len(rgb), 1)
    ch = _rgb_to_hsl(centers)
    scores = w * (ch[:, 1] + 0.15) * (1.0 - np.abs(ch[:, 2] - 0.40))
    scores[w < 0.03] = -1.0
    return _nearest_color(tuple(int(v) for v in centers[int(np.argmax(scores))]))


# ---------------------------------------------------------------------------
# OpenAI Vision — primary path (full metadata in a single call)
# ---------------------------------------------------------------------------

def _openai_full_metadata_sync(image_bytes: bytes) -> Optional[dict]:
    """
    Convert image bytes to base64, call analyze_clothing_with_openai(), and
    return the result dict or None if any step fails.
    Called once per image — result is not re-requested anywhere else.
    """
    try:
        from services.openai_vision import analyze_clothing_with_openai, image_bytes_to_base64
    except ImportError as exc:
        log.error("Could not import openai_vision: %s", exc)
        return None

    try:
        b64 = image_bytes_to_base64(image_bytes, max_size=768)
    except Exception as exc:
        log.error("Failed to convert image to base64 for OpenAI: %s", exc)
        return None

    print("Using OpenAI Vision")
    log.info("Using OpenAI Vision")
    return analyze_clothing_with_openai(b64)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_clothing_metadata(image_bytes: bytes) -> dict:
    """
    Full pipeline:

    PRIMARY PATH (OpenAI Vision):
      1. Convert image → base64
      2. Call GPT-4o-mini → 7-field JSON (category, subcategory, primary_color,
         pattern, material, formality, culture)
      3. Return structured result

    FALLBACK PATH (if OpenAI unavailable/fails):
      1. Hybrid classifier (CV + MobileNet) — determines category (offline)
      2. rembg + CV KMeans — dominant color fallback
      3. Gemini — refines pattern / primary_color / formality (optional, online)
    """
    # ── Primary: OpenAI Vision ────────────────────────────────────────────
    openai_task = asyncio.to_thread(_openai_full_metadata_sync, image_bytes)
    openai_result = await openai_task

    if openai_result:
        log.info("✅ OpenAI Vision metadata: %s", openai_result)
        # Normalise formality key — endpoint contract uses "formality_level"
        formality = openai_result.get("formality") or openai_result.get("formality_level") or "casual"
        return {
            "category":        openai_result.get("category")      or "unknown",
            "subcategory":     openai_result.get("subcategory")    or "unknown",
            "primary_color":   openai_result.get("primary_color")  or "unknown",
            "pattern":         openai_result.get("pattern")        or "solid",
            "material":        openai_result.get("material")       or "unknown",
            "formality_level": formality,
            "culture":         openai_result.get("culture")        or "global",
            "confidence":      1.0,
            "method":          "openai_vision",
        }

    # ── Fallback: Hybrid CV + Gemini ────────────────────────────────────
    print("Falling back to local CV")
    log.warning("OpenAI Vision failed or unavailable — falling back to local CV")

    original_img: Optional[Image.Image] = None
    try:
        original_img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        pass

    hybrid_task = asyncio.to_thread(_hybrid_classifier.classify, image_bytes)
    gemini_task = asyncio.to_thread(_gemini_get_details_sync, image_bytes)

    # CV color via rembg (CPU-bound — run before awaiting async tasks)
    cv_color = "unknown"
    if original_img is not None:
        try:
            fg_img = remove(original_img)
            cv_color = _dominant_color_from_rgba(fg_img, original_img)
        except Exception as exc:
            log.warning("rembg/color failed: %s", exc)

    hybrid_result = await hybrid_task
    gemini_details = await gemini_task

    category   = hybrid_result.get("category", "Unknown")
    confidence = hybrid_result.get("confidence", 0.0)
    method     = hybrid_result.get("method", "unknown")

    if gemini_details:
        pattern         = gemini_details.get("pattern")         or "solid"
        primary_color   = gemini_details.get("primary_color")   or cv_color
        formality_level = gemini_details.get("formality_level") or "casual"
        method          = method + "+gemini"
    else:
        log.warning("Gemini unavailable — using CV color and defaults for pattern/formality")
        pattern         = "solid"
        primary_color   = cv_color
        formality_level = "casual"

    log.info(
        "✅ Fallback metadata: category=%s conf=%.2f method=%s | pattern=%s color=%s formality=%s",
        category, confidence, method, pattern, primary_color, formality_level,
    )

    return {
        "category":        category,
        "subcategory":     "unknown",
        "confidence":      round(confidence, 2),
        "method":          method,
        "primary_color":   primary_color,
        "pattern":         pattern,
        "material":        "unknown",
        "formality_level": formality_level,
        "culture":         "global",
    }
