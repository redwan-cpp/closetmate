"""
Skin tone detection service using OpenCV.

Pipeline:
1. Read image bytes → OpenCV BGR array
2. Detect face via Haar cascade
3. Extract face region → convert to HSV
4. Sample skin pixels, compute mean hue
5. Classify: warm / cool / neutral
6. Return skin_tone + curated recommended_colors list
"""
from __future__ import annotations

import io
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Color recommendations per skin tone
# ---------------------------------------------------------------------------
_TONE_COLORS: dict[str, List[str]] = {
    "warm": ["olive", "cream", "mustard", "burnt orange", "warm beige",
             "caramel", "terracotta", "gold"],
    "cool": ["lavender", "cool gray", "dusty rose", "cobalt blue",
             "emerald", "plum", "icy pink"],
    "neutral": ["white", "navy", "soft blush", "sage green",
                "warm gray", "mauve", "taupe"],
}

# ---------------------------------------------------------------------------
# Haar cascade (bundled with opencv-python)
# ---------------------------------------------------------------------------
_CASCADE = None


def _get_cascade() -> cv2.CascadeClassifier:
    global _CASCADE
    if _CASCADE is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _CASCADE = cv2.CascadeClassifier(cascade_path)
    return _CASCADE


# ---------------------------------------------------------------------------
# Tone classification from HSV mean hue
# ---------------------------------------------------------------------------
def _classify_tone_from_lab(bgr_region: np.ndarray) -> str:
    """
    Convert to Lab color space and use the 'b' channel to distinguish warm/cool.
    Positive b* → yellowish (warm), negative b* → bluish (cool).
    """
    if bgr_region.size == 0:
        return "neutral"

    lab = cv2.cvtColor(bgr_region, cv2.COLOR_BGR2Lab)
    b_channel = lab[:, :, 2].astype(float)  # OpenCV stores as 0-255, center is 128
    mean_b = b_channel.mean()

    if mean_b > 133:
        return "warm"
    elif mean_b < 123:
        return "cool"
    return "neutral"


def detect_skin_tone(image_bytes: bytes) -> dict:
    """
    Detect the skin tone from a selfie or photo.

    Returns:
        {
          "skin_tone": "warm" | "cool" | "neutral",
          "recommended_colors": [...]
        }
    """
    # Decode image
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Try face detection
    cascade = _get_cascade()
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(60, 60),
    )

    if len(faces) > 0:
        # Use the largest detected face
        x, y, w, h = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[0]
        # Take center 60% of the face to avoid hair/background contamination
        cx, cy = x + w // 2, y + h // 2
        rw, rh = int(w * 0.3), int(h * 0.3)
        skin_region = bgr[
            max(0, cy - rh): min(bgr.shape[0], cy + rh),
            max(0, cx - rw): min(bgr.shape[1], cx + rw),
        ]
    else:
        # Fallback: use center strip of the image (likely contains skin)
        ch, cw = bgr.shape[0] // 2, bgr.shape[1] // 2
        rh, rw = bgr.shape[0] // 6, bgr.shape[1] // 6
        skin_region = bgr[
            max(0, ch - rh): ch + rh,
            max(0, cw - rw): cw + rw,
        ]

    tone = _classify_tone_from_lab(skin_region)
    return {
        "skin_tone": tone,
        "recommended_colors": _TONE_COLORS[tone],
    }
