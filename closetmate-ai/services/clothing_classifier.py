"""
Hybrid clothing classifier.

Combines:
  Layer 1 — OpenCV rule-based shape analysis (fast, works offline, great for South Asian garments)
  Layer 2 — MobileNetV3-Small pretrained on ImageNet (no training, cached after first download)
  Fusion   — weighted score merge → final category + confidence + method

Pattern / color / formality are NOT handled here; those come from Gemini in metadata_extractor.py.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MobileNetV3 — lazy-loaded singleton so startup stays fast
# ---------------------------------------------------------------------------
_mobilenet = None
_imagenet_labels: list[str] = []


def _get_mobilenet():
    """Load MobileNetV3-Small on first call; returns (model, preprocess, labels) or None."""
    global _mobilenet, _imagenet_labels
    if _mobilenet is not None:
        return _mobilenet, _imagenet_labels

    try:
        import torch
        import torchvision.models as models
        import torchvision.transforms as T
        from torchvision.models import MobileNet_V3_Small_Weights

        weights = MobileNet_V3_Small_Weights.DEFAULT
        model = models.mobilenet_v3_small(weights=weights)
        model.eval()

        preprocess = weights.transforms()
        labels = weights.meta["categories"]

        _mobilenet = (model, preprocess)
        _imagenet_labels = labels
        log.info("MobileNetV3-Small loaded (%d ImageNet classes)", len(labels))
        return _mobilenet, _imagenet_labels
    except Exception as exc:
        log.warning("MobileNetV3 unavailable: %s — using CV only", exc)
        _mobilenet = False  # Mark as failed so we don't retry every call
        return None, []


# ---------------------------------------------------------------------------
# ImageNet label → clothing category mapping
# Maps (partial) ImageNet class names to our clothing categories.
# ---------------------------------------------------------------------------
_IMAGENET_TO_CLOTHING: list[tuple[list[str], str, float]] = [
    # keywords                           → category        base_conf
    (["jersey", "tee shirt", "t-shirt"],                   "T-Shirt",      0.80),
    (["sweatshirt"],                                       "Sweatshirt",   0.82),
    (["cardigan"],                                         "Cardigan",     0.82),
    (["suit", "suit of clothes"],                          "Blazer",       0.72),
    (["trench coat", "trench"],                            "Trench Coat",  0.84),
    (["raincoat"],                                         "Raincoat",     0.82),
    (["gown"],                                             "Evening Gown", 0.78),
    (["miniskirt", "mini"],                                "Mini Skirt",   0.80),
    (["kimono"],                                           "Kurta",        0.65),
    (["sarong"],                                           "Saree",        0.70),
    (["jean", "denim"],                                    "Jeans",        0.80),
    (["jean"],                                             "Jeans",        0.80),
    (["pajama", "pyjama"],                                 "Joggers",      0.68),
    (["bow tie", "bow-tie"],                               "Accessory",    0.70),
    (["brassiere", "bra"],                                 "Top",          0.70),
    (["bikini"],                                           "Top",          0.70),
    (["maillot"],                                          "Top",          0.65),
    (["military uniform"],                                 "Jacket",       0.70),
    (["academic gown"],                                    "Dress",        0.65),
    (["apron"],                                            "Dress",        0.60),
    (["poncho"],                                           "Poncho",       0.80),
    (["parka"],                                            "Puffer Jacket",0.80),
    (["lab coat"],                                         "Shirt",        0.65),
    (["windsor tie", "tie"],                               "Accessory",    0.72),
    (["sock"],                                             "Accessory",    0.70),
    (["hoopskirt", "crinoline"],                           "Dress",        0.70),
    (["overskirt"],                                        "Skirt",        0.70),
    (["dress"],                                            "Dress",        0.78),
    (["shirt"],                                            "Shirt",        0.75),
    (["skirt"],                                            "Skirt",        0.78),
    (["coat"],                                             "Coat",         0.75),
    (["jacket"],                                           "Jacket",       0.75),
    (["pants", "trouser"],                                 "Trousers",     0.78),
]


def _map_imagenet_to_clothing(label: str, score: float) -> Optional[tuple[str, float]]:
    """Map an ImageNet label+score to (clothing_category, confidence). Returns None if no match."""
    label_lower = label.lower()
    for keywords, category, base_conf in _IMAGENET_TO_CLOTHING:
        if any(kw in label_lower for kw in keywords):
            return category, min(0.95, base_conf * (score ** 0.3))
    return None


# ---------------------------------------------------------------------------
# Layer 1: OpenCV rule-based classifier
# ---------------------------------------------------------------------------

def _cv_classify(img_rgb: np.ndarray) -> tuple[str, float, str]:
    """
    Returns (category, confidence, method='cv_rules').
    Works on the original RGB image (no background removal needed).
    """
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)

    # Find overall bounding box of non-background content
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return "Unknown", 0.1, "cv_rules"

    x, y, w, h = cv2.boundingRect(coords)
    if w == 0 or h == 0:
        return "Unknown", 0.1, "cv_rules"

    aspect_ratio = h / w
    img_h, img_w = img_rgb.shape[:2]

    # --- Saree detection ---
    # Very wide OR very large continuous flowing garment
    if aspect_ratio > 2.8:
        return "Saree", 0.75, "cv_rules"

    # --- Two-leg split detection (pants/jeans/trousers) ---
    bottom_region = thresh[y + int(h * 0.55): y + h, x: x + w]
    if bottom_region.shape[0] > 5:
        col_filled = (bottom_region > 0).mean(axis=0)
        # Look for a valley in the middle (two-leg gap)
        mid = len(col_filled) // 2
        quarter = max(1, len(col_filled) // 4)
        left_density = col_filled[quarter: mid].mean() if mid > quarter else 0
        right_density = col_filled[mid: mid + quarter].mean() if (mid + quarter) <= len(col_filled) else 0
        center_density = col_filled[mid - 5: mid + 5].mean() if len(col_filled) > 10 else 1.0
        if center_density < 0.25 and left_density > 0.4 and right_density > 0.4:
            return "Pants", 0.85, "cv_rules"

    # --- Button region analysis (center vertical strip edge density) ---
    center_strip = gray[y: y + h, x + w // 3: x + 2 * w // 3]
    edges = cv2.Canny(center_strip, 50, 150)
    edge_density = edges.mean()

    # Divide garment into thirds vertically
    third = h // 3
    top_strip_edges = cv2.Canny(gray[y: y + third, x + w // 3: x + 2 * w // 3], 50, 150).mean()
    bottom_strip_edges = cv2.Canny(gray[y + 2 * third: y + h, x + w // 3: x + 2 * w // 3], 50, 150).mean()

    # --- Panjabi / Kurta detection ---
    # Long garment (tall relative to width), buttons only in upper portion
    if aspect_ratio > 1.8:
        has_upper_buttons = top_strip_edges > 8 and top_strip_edges > bottom_strip_edges * 1.5
        if has_upper_buttons:
            return "Panjabi", 0.80, "cv_rules"
        # Long garment, no strong bottom button pattern → Kurta / Dress
        if aspect_ratio > 2.0:
            return "Dress", 0.68, "cv_rules"

    # --- Shirt detection ---
    # Shorter garment with full vertical button line (edge density roughly uniform)
    if 0.7 < aspect_ratio <= 1.8:
        has_full_buttons = edge_density > 8 and top_strip_edges > 5 and bottom_strip_edges > 5
        if has_full_buttons:
            return "Shirt", 0.75, "cv_rules"

    # --- Dress detection ---
    # Continuous structure, waist narrowing
    if 1.2 < aspect_ratio <= 2.8:
        # Check for waist-narrowing (hourglass): top + bottom wider than middle
        top_width = (thresh[y: y + third, x: x + w] > 0).mean(axis=0).mean()
        mid_width = (thresh[y + third: y + 2 * third, x: x + w] > 0).mean(axis=0).mean()
        bot_width = (thresh[y + 2 * third: y + h, x: x + w] > 0).mean(axis=0).mean()
        if mid_width < top_width * 0.85 and mid_width < bot_width * 0.85:
            return "Dress", 0.75, "cv_rules"
        # Continuous vertical structure with no leg split → dress candidate
        return "Dress", 0.62, "cv_rules"

    # --- Top / Shirt fallback ---
    if aspect_ratio <= 0.85:
        return "Top", 0.60, "cv_rules"
    if aspect_ratio <= 1.2:
        return "Shirt", 0.62, "cv_rules"

    return "Clothing", 0.40, "cv_rules"


# ---------------------------------------------------------------------------
# Layer 2: MobileNetV3 model classifier
# ---------------------------------------------------------------------------

def _model_classify(pil_image: Image.Image) -> Optional[tuple[str, float, str]]:
    """
    Returns (category, confidence, method='mobilenet') or None if model unavailable.
    """
    result = _get_mobilenet()
    if result[0] is None or result[0] is False:
        return None

    model_tuple, labels = result
    model, preprocess = model_tuple

    try:
        import torch

        # Resize to not be too large (model handles this but let's be safe)
        img = pil_image.convert("RGB").resize((224, 224), Image.LANCZOS)
        tensor = preprocess(img).unsqueeze(0)

        with torch.no_grad():
            logits = model(tensor)
            probs = torch.nn.functional.softmax(logits[0], dim=0)

        # Get top-5 predictions
        top5_probs, top5_idxs = torch.topk(probs, 5)

        for prob, idx in zip(top5_probs.tolist(), top5_idxs.tolist()):
            label = labels[idx] if idx < len(labels) else ""
            mapped = _map_imagenet_to_clothing(label, prob)
            if mapped:
                category, confidence = mapped
                log.debug("MobileNet: label=%s prob=%.3f → %s (conf=%.2f)", label, prob, category, confidence)
                return category, confidence, "mobilenet"

        log.debug("MobileNet top-5 had no clothing match")
        return None

    except Exception as exc:
        log.warning("MobileNet inference failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Fusion: combine rule-based + model scores
# ---------------------------------------------------------------------------

_CATEGORY_WEIGHT = {
    # Rule-based is stronger for South Asian garments
    "Saree":   (0.80, 0.20),  # (cv_weight, model_weight)
    "Panjabi": (0.75, 0.25),
    "Kurta":   (0.70, 0.30),
    # Model is stronger for well-represented Western garments
    "T-Shirt": (0.35, 0.65),
    "Jeans":   (0.40, 0.60),
    "Dress":   (0.50, 0.50),
}
_DEFAULT_WEIGHTS = (0.55, 0.45)


def _fuse(cv_result: tuple, model_result: Optional[tuple]) -> dict:
    """Merge CV and model results into final classification."""
    cv_cat, cv_conf, _ = cv_result
    
    if model_result is None:
        return {"category": cv_cat, "confidence": round(cv_conf, 2), "method": "cv_rules"}

    model_cat, model_conf, _ = model_result

    if cv_cat == model_cat:
        # Both agree → boost confidence
        final_conf = min(0.97, (cv_conf + model_conf) / 2 + 0.10)
        return {"category": cv_cat, "confidence": round(final_conf, 2), "method": "hybrid_cv+model"}

    # Disagreement — use weighted scores
    cv_w, model_w = _CATEGORY_WEIGHT.get(cv_cat, _DEFAULT_WEIGHTS)
    cv_score = cv_conf * cv_w
    model_score = model_conf * model_w

    if model_score >= cv_score:
        final_cat, final_conf = model_cat, model_conf
        method = "hybrid_model_wins"
    else:
        final_cat, final_conf = cv_cat, cv_conf
        method = "hybrid_cv_wins"

    log.info("Fusion: cv=%s(%.2f) vs model=%s(%.2f) → %s [%s]",
             cv_cat, cv_conf, model_cat, model_conf, final_cat, method)
    return {"category": final_cat, "confidence": round(final_conf, 2), "method": method}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class HybridClothingClassifier:
    """
    Singleton-style classifier. Pre-warms MobileNet on first call.
    Thread-safe for concurrent async use via asyncio.to_thread.
    """

    def classify(self, image_bytes: bytes) -> dict:
        """
        Classify clothing from raw image bytes.
        Returns: {category, confidence, method}
        """
        try:
            pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            log.error("Cannot open image: %s", exc)
            return {"category": "Unknown", "confidence": 0.0, "method": "error"}

        img_rgb = np.array(pil_img)

        # Layer 1: CV rules
        cv_result = _cv_classify(img_rgb)
        log.info("CV result: %s (conf=%.2f)", cv_result[0], cv_result[1])

        # Layer 2: MobileNet
        model_result = _model_classify(pil_img)
        if model_result:
            log.info("Model result: %s (conf=%.2f)", model_result[0], model_result[1])

        # Fusion
        final = _fuse(cv_result, model_result)
        log.info("✅ Hybrid final: %s", final)
        return final

    def prewarm(self) -> None:
        """Load MobileNet weights in background on startup."""
        _get_mobilenet()


# Shared singleton
classifier = HybridClothingClassifier()
