"""
studio.py — turn a phone photo of a garment into a "studio shot".

A studio shot is a clean cutout, tightly cropped, centred and scaled onto a
transparent 4:5 canvas. Every item then has the same framing and visual weight, so:

  * the closet reads like a boutique shelf instead of a camera roll, and
  * items can be composed into outfit collages (lookboards) without fiddling.

Pipeline: cutout -> clean the matte -> keep the main subject -> crop -> fit to canvas -> WebP.

Colour is deliberately left untouched (no auto-contrast or white balance): in fashion the
colour IS the product, and a "fix" that turns navy into black is worse than a dull photo.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageOps

from services.image_processing import remove_background_with_model
from settings import get_settings

log = logging.getLogger(__name__)

CANVAS: Tuple[int, int] = (640, 800)      # 4:5 — a clothing-friendly portrait ratio
THUMB: Tuple[int, int] = (320, 400)
FILL = 0.88                               # the item may use up to 88% of each canvas axis
MAX_UPSCALE = 3.0                         # never blow a small crop up beyond 3x (it would blur)
_MAX_SOURCE_SIDE = 1280                   # cap the cutout input; keeps CPU and RAM bounded
_MIN_SUBJECT_FRACTION = 0.004             # smaller than 0.4% of the photo => nothing to show
_SUSPECT_FRACTION = 0.92                  # >92% opaque => the background probably wasn't removed


class StudioShotError(ValueError):
    """The photo has no usable subject (blank, too small, or not an image)."""


@dataclass(frozen=True)
class StudioShot:
    full: bytes            # WebP, CANVAS size, transparent background
    thumb: bytes           # WebP, THUMB size
    width: int
    height: int
    cutout_ok: bool        # False when the matte looks like a failed background removal


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------

def _open(image_bytes: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise StudioShotError("That file isn't a readable image.") from exc
    if max(img.size) > _MAX_SOURCE_SIDE:
        img.thumbnail((_MAX_SOURCE_SIDE, _MAX_SOURCE_SIDE), Image.LANCZOS)
    return img


def _cutout(img: Image.Image) -> Image.Image:
    """Background removal. Isolated so tests can stub it without loading a model."""
    return remove_background_with_model(img, get_settings().studio_model)


def _clean_matte(cut: Image.Image) -> Image.Image:
    """Drop faint haze and stray specks, then tighten and soften the edge."""
    arr = np.array(cut.convert("RGBA"))
    alpha = arr[:, :, 3]

    # 1. Faint haze (<5% opacity) is noise from the matting model, not garment.
    alpha = np.where(alpha < 12, 0, alpha).astype(np.uint8)

    # 2. Keep the main subject plus anything substantial (a pair of shoes is two blobs of
    #    similar size; a speck of lint is not). Small components vanish.
    solid = (alpha > 128).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    if count > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        floor = max(int(areas.max() * 0.04), 50)
        keep_ids = [i + 1 for i, area in enumerate(areas) if area >= floor]
        keep = np.isin(labels, keep_ids).astype(np.uint8)
        keep = cv2.dilate(keep, np.ones((7, 7), np.uint8))      # let soft edge pixels survive
        alpha = np.where(keep > 0, alpha, 0).astype(np.uint8)

    # 3. A 1px erosion removes the bright halo bright backgrounds leave on the edge;
    #    a light blur then anti-aliases it.
    matte = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))

    arr[:, :, 3] = np.array(matte)
    return Image.fromarray(arr, "RGBA")


def _crop_to_subject(cut: Image.Image) -> Tuple[Image.Image, bool]:
    alpha = np.array(cut)[:, :, 3]
    ys, xs = np.where(alpha > 24)
    if len(xs) == 0:
        raise StudioShotError("We couldn't find the item in this photo. Try a plainer background.")

    solid_fraction = float((alpha > 128).sum()) / alpha.size
    if solid_fraction < _MIN_SUBJECT_FRACTION:
        raise StudioShotError("The item is too small in this photo. Move closer and try again.")

    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    # A matte that is almost fully opaque means the model kept the whole photo.
    return cut.crop(box), solid_fraction < _SUSPECT_FRACTION


def _fit_to_canvas(item: Image.Image) -> Image.Image:
    max_w, max_h = int(CANVAS[0] * FILL), int(CANVAS[1] * FILL)
    scale = min(max_w / item.width, max_h / item.height, MAX_UPSCALE)
    size = (max(1, round(item.width * scale)), max(1, round(item.height * scale)))
    item = item.resize(size, Image.LANCZOS)      # Pillow resizes RGBA premultiplied: no dark fringes

    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    x = (CANVAS[0] - item.width) // 2
    y = int((CANVAS[1] - item.height) * 0.48)    # a touch above centre: optically balanced
    canvas.alpha_composite(item, (x, y))
    return canvas


def _encode(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, alpha_quality=100, method=4)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def make_studio_shot(image_bytes: bytes) -> StudioShot:
    """
    Photo bytes in, studio shot out. CPU-bound (runs a segmentation model): call from a
    worker thread. Raises StudioShotError if there is nothing usable in the photo.
    """
    source = _open(image_bytes)
    matte = _clean_matte(_cutout(source))
    subject, cutout_ok = _crop_to_subject(matte)
    canvas = _fit_to_canvas(subject)
    thumb = canvas.resize(THUMB, Image.LANCZOS)
    return StudioShot(
        full=_encode(canvas, 88),
        thumb=_encode(thumb, 82),
        width=CANVAS[0],
        height=CANVAS[1],
        cutout_ok=cutout_ok,
    )
