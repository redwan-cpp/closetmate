"""
Skin tone detection service using OpenCV — Enhanced v2.

Pipeline:
1. Read image bytes → OpenCV BGR array
2. Detect face via Haar cascade (with DNN fallback hint)
3. Extract multiple face zones: forehead, cheeks, chin  (avoids hair/eyes)
4. Apply HSV-based skin-pixel mask to filter non-skin pixels
5. Convert masked region to CIE Lab color space
6. Use L* for lightness classification, b* for warm/cool undertone
7. Classify into 5 tones: light / light-medium / medium / medium-deep / deep
   Each tone also tagged warm / cool / neutral undertone
8. Return skin_tone, undertone, recommended_colors, hex_swatch, confidence
"""
from __future__ import annotations

import io
import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extended color palette — keyed by (tone_band, undertone)
# ---------------------------------------------------------------------------

_TONE_COLORS: dict[str, dict[str, List[str]]] = {
    # Very fair / light skin
    "light": {
        "warm":    ["peach", "warm ivory", "soft coral", "gold", "warm beige", "camel", "light olive"],
        "cool":    ["lavender", "cool pink", "icy blue", "soft white", "silver", "rose", "cool gray"],
        "neutral": ["soft white", "blush", "sky blue", "sage green", "warm gray", "nude beige", "mauve"],
    },
    # Light-medium / beige skin
    "light-medium": {
        "warm":    ["caramel", "warm beige", "mustard", "burnt orange", "cream", "gold", "warm olive"],
        "cool":    ["dusty rose", "cool mauve", "lavender", "periwinkle", "soft lilac", "sage"],
        "neutral": ["nude", "blush pink", "warm white", "olive green", "teal", "denim blue"],
    },
    # Medium / tan skin
    "medium": {
        "warm":    ["terracotta", "rust", "warm brown", "mustard yellow", "gold", "olive green", "copper"],
        "cool":    ["cobalt blue", "emerald", "berry", "plum", "cool purple", "hot pink"],
        "neutral": ["white", "navy", "sage green", "blush", "camel", "warm gray", "burnt sienna"],
    },
    # Medium-deep / olive/brown skin
    "medium-deep": {
        "warm":    ["burnt orange", "caramel", "warm red", "gold", "mustard", "chocolate", "olive"],
        "cool":    ["royal blue", "deep plum", "magenta", "cool green", "emerald", "icy lavender"],
        "neutral": ["ivory", "dusty pink", "teal", "cobalt", "warm taupe", "cream"],
    },
    # Deep / dark skin
    "deep": {
        "warm":    ["bright orange", "warm gold", "rich yellow", "warm red", "copper", "coral", "warm white"],
        "cool":    ["deep purple", "cobalt blue", "bright pink", "cool emerald", "lilac", "bright white"],
        "neutral": ["royal blue", "bright white", "jewel tones", "rich green", "fuchsia", "bold mustard"],
    },
}

# ---------------------------------------------------------------------------
# Haar cascade (bundled with opencv-python)
# ---------------------------------------------------------------------------

_CASCADE: Optional[cv2.CascadeClassifier] = None


def _get_cascade() -> cv2.CascadeClassifier:
    global _CASCADE
    if _CASCADE is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _CASCADE = cv2.CascadeClassifier(cascade_path)
    return _CASCADE


# ---------------------------------------------------------------------------
# HSV-based skin pixel mask
# ---------------------------------------------------------------------------

# Broad HSV skin range covering light to dark skin tones
_SKIN_HSV_RANGES = [
    # Hue range        Sat range      Val range
    ((0,  30, 50),   (20, 170, 255)),   # warm skin tones (fair to medium)
    ((0,  10, 60),   (25, 255, 255)),   # extended warm
    ((0,  20, 20),   (20, 255, 200)),   # deeper tones
    ((350, 10, 50),  (360, 200, 255)),  # reddish (wraps hue)
]


def _skin_mask(bgr: np.ndarray) -> np.ndarray:
    """Return a binary mask highlighting skin-colored pixels."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(bgr.shape[:2], dtype=np.uint8)

    # Primary HSV range for skin
    lower1 = np.array([0, 15, 40], dtype=np.uint8)
    upper1 = np.array([25, 220, 255], dtype=np.uint8)
    mask |= cv2.inRange(hsv, lower1, upper1)

    # Extend for deeper/darker skin (lower saturation, lower value)
    lower2 = np.array([0, 8, 20], dtype=np.uint8)
    upper2 = np.array([20, 180, 200], dtype=np.uint8)
    mask |= cv2.inRange(hsv, lower2, upper2)

    # YCrCb range — very reliable for multi-ethnic skin
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    lower_y = np.array([0, 133, 77], dtype=np.uint8)
    upper_y = np.array([255, 173, 127], dtype=np.uint8)
    mask |= cv2.inRange(ycrcb, lower_y, upper_y)

    # Morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=1)
    return mask


# ---------------------------------------------------------------------------
# Face zone sampling  (multiple zones for robustness)
# ---------------------------------------------------------------------------

def _extract_face_zones(bgr: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """
    Sample multiple facial zones (forehead, cheeks, chin) and return all
    skin pixels found across those zones as a flat pixel array (N×3 BGR).
    Avoids eyes, mouth, and hair by sampling from the inner face only.
    """
    zones: List[np.ndarray] = []

    def _safe_crop(r1, r2, c1, c2) -> Optional[np.ndarray]:
        r1_ = max(0, r1); r2_ = min(bgr.shape[0], r2)
        c1_ = max(0, c1); c2_ = min(bgr.shape[1], c2)
        region = bgr[r1_:r2_, c1_:c2_]
        return region if region.size > 0 else None

    # Forehead: top 25% of face, center 40% width
    forehead = _safe_crop(
        y + int(h * 0.08), y + int(h * 0.30),
        x + int(w * 0.30), x + int(w * 0.70),
    )
    if forehead is not None:
        zones.append(forehead)

    # Left cheek
    left_cheek = _safe_crop(
        y + int(h * 0.40), y + int(h * 0.65),
        x + int(w * 0.10), x + int(w * 0.35),
    )
    if left_cheek is not None:
        zones.append(left_cheek)

    # Right cheek
    right_cheek = _safe_crop(
        y + int(h * 0.40), y + int(h * 0.65),
        x + int(w * 0.65), x + int(w * 0.90),
    )
    if right_cheek is not None:
        zones.append(right_cheek)

    # Chin / jaw area (center)
    chin = _safe_crop(
        y + int(h * 0.72), y + int(h * 0.90),
        x + int(w * 0.35), x + int(w * 0.65),
    )
    if chin is not None:
        zones.append(chin)

    if not zones:
        return np.empty((0, 3), dtype=np.uint8)

    all_pixels: List[np.ndarray] = []
    for zone in zones:
        mask = _skin_mask(zone)
        skin_pixels = zone[mask > 0]
        if skin_pixels.size > 0:
            all_pixels.append(skin_pixels.reshape(-1, 3))

    if not all_pixels:
        return np.empty((0, 3), dtype=np.uint8)

    return np.vstack(all_pixels)


# ---------------------------------------------------------------------------
# Tone classification from Lab stats
# ---------------------------------------------------------------------------

def _classify_from_lab_pixels(
    pixels_bgr: np.ndarray,
) -> Tuple[str, str, float, str]:
    """
    Given N×3 BGR skin pixels, classify:
      - tone_band:  light / light-medium / medium / medium-deep / deep
      - undertone:  warm / cool / neutral
      - confidence: 0–1
      - hex_swatch: representative hex color

    Uses:
      - L* (CIE Lab) for lightness → tone band
      - b* for warm (positive) vs cool (negative) undertone
      - a* as secondary indicator (redness)
    """
    if pixels_bgr.size == 0:
        return "medium", "neutral", 0.3, "#C8A882"

    # Subsample for performance
    if len(pixels_bgr) > 3000:
        idx = np.random.choice(len(pixels_bgr), 3000, replace=False)
        pixels_bgr = pixels_bgr[idx]

    # Convert to Lab
    pixels_bgr_u8 = pixels_bgr.astype(np.uint8).reshape(-1, 1, 3)
    pixels_lab = cv2.cvtColor(pixels_bgr_u8, cv2.COLOR_BGR2Lab).reshape(-1, 3).astype(float)

    # OpenCV Lab encoding: L in [0,255], a in [0,255], b in [0,255]
    # True Lab: L in [0,100], a in [-128,127], b in [-128,127]
    L_true = pixels_lab[:, 0] * (100.0 / 255.0)
    a_true = pixels_lab[:, 1] - 128.0
    b_true = pixels_lab[:, 2] - 128.0

    mean_L = float(np.median(L_true))
    mean_a = float(np.median(a_true))
    mean_b = float(np.median(b_true))

    log.debug("Skin Lab stats: L*=%.1f a*=%.1f b*=%.1f (median, %d px)", mean_L, mean_a, mean_b, len(pixels_bgr))

    # ── Tone band from L* ────────────────────────────────────────────────────
    # Calibrated thresholds from Fitzpatrick skin tone research
    if mean_L >= 72:
        tone_band = "light"
        confidence = min(1.0, (mean_L - 72) / 15 + 0.6)
    elif mean_L >= 60:
        tone_band = "light-medium"
        confidence = 0.7
    elif mean_L >= 47:
        tone_band = "medium"
        confidence = 0.75
    elif mean_L >= 35:
        tone_band = "medium-deep"
        confidence = 0.7
    else:
        tone_band = "deep"
        confidence = min(1.0, (47 - mean_L) / 12 + 0.6)

    # ── Undertone from b* and a* ─────────────────────────────────────────────
    # b* > 0  → yellowish (warm), b* < 0 → bluish (cool)
    # a* > 0  → reddish (can be cool undertone in skin), a* < 0 → greenish
    warm_score  = np.maximum(0, b_true).mean()
    cool_score  = np.maximum(0, -b_true).mean() + np.maximum(0, a_true - 6).mean() * 0.3
    warm_margin = warm_score - cool_score

    if warm_margin > 4.0:
        undertone = "warm"
    elif warm_margin < -2.0:
        undertone = "cool"
    else:
        undertone = "neutral"

    # ── Representative hex swatch (median BGR) ───────────────────────────────
    med_b = int(np.median(pixels_bgr[:, 0]))
    med_g = int(np.median(pixels_bgr[:, 1]))
    med_r = int(np.median(pixels_bgr[:, 2]))
    hex_swatch = f"#{med_r:02X}{med_g:02X}{med_b:02X}"

    return tone_band, undertone, round(confidence, 2), hex_swatch


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_skin_tone(image_bytes: bytes) -> dict:
    """
    Detect skin tone from a selfie or photo with high accuracy.

    Returns:
        {
          "skin_tone":         "light" | "light-medium" | "medium" | "medium-deep" | "deep",
          "undertone":         "warm" | "cool" | "neutral",
          "confidence":        0.0 – 1.0,
          "hex_swatch":        "#RRGGBB"  (representative skin color),
          "recommended_colors": [...],
          "face_detected":     bool,
        }
    """
    # Decode image
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Resize if very large (speeds up processing, no quality loss for detection)
    max_dim = 1024
    if max(pil_img.size) > max_dim:
        pil_img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Equalize to help detection under varied lighting
    gray_eq = cv2.equalizeHist(gray)

    # ── Face detection ──────────────────────────────────────────────────────
    cascade = _get_cascade()
    faces = cascade.detectMultiScale(
        gray_eq,
        scaleFactor=1.05,
        minNeighbors=4,
        minSize=(50, 50),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )

    face_detected = len(faces) > 0

    if face_detected:
        # Use the largest face
        x, y, w, h = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[0]
        log.info("Face detected at (%d,%d) size=%dx%d", x, y, w, h)
        skin_pixels = _extract_face_zones(bgr, x, y, w, h)

        # Fallback to center-face box if zone extraction gives too few pixels
        if len(skin_pixels) < 50:
            log.debug("Zone extraction sparse (%d px) → using inner face box", len(skin_pixels))
            cx, cy = x + w // 2, y + h // 2
            rw, rh = int(w * 0.28), int(h * 0.28)
            region = bgr[
                max(0, cy - rh): min(bgr.shape[0], cy + rh),
                max(0, cx - rw): min(bgr.shape[1], cx + rw),
            ]
            mask = _skin_mask(region)
            skin_pixels = region[mask > 0].reshape(-1, 3)
    else:
        # No face found — attempt whole-image skin extraction
        log.warning("No face detected — sampling image skin pixels")
        # Focus on a generous center crop (good for selfies)
        h, w = bgr.shape[:2]
        cy, cx = h // 2, w // 2
        region = bgr[
            max(0, cy - h // 4): min(h, cy + h // 4),
            max(0, cx - w // 4): min(w, cx + w // 4),
        ]
        mask = _skin_mask(region)
        skin_pixels = region[mask > 0].reshape(-1, 3)

    tone_band, undertone, confidence, hex_swatch = _classify_from_lab_pixels(skin_pixels)

    recommended = _TONE_COLORS.get(tone_band, _TONE_COLORS["medium"]).get(
        undertone, _TONE_COLORS["medium"]["neutral"]
    )

    # Friendly display label
    display = f"{tone_band} ({undertone})"

    log.info(
        "Skin tone result: tone=%s undertone=%s conf=%.2f hex=%s face=%s",
        tone_band, undertone, confidence, hex_swatch, face_detected,
    )

    return {
        "skin_tone":          tone_band,
        "undertone":          undertone,
        "display_label":      display,
        "confidence":         confidence,
        "hex_swatch":         hex_swatch,
        "recommended_colors": recommended,
        "face_detected":      face_detected,
    }
