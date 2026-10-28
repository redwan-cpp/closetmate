"""
routers/images.py — image utilities: background removal, lighting analysis, styling.

Mounted twice by main.py: under /images/* and at the root (older app builds
call /remove-bg directly). All endpoints require an access token.

Endpoints:
  POST /analyze-lighting   brightness / contrast / warmth
  POST /remove-bg          base64 JPEG on white (what the app uses; quota: bgremove)
  POST /remove-background  transparent PNG      (quota: bgremove)
  POST /style              garment on an editorial gradient (quota: bgremove)
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

from quota import metered, release_quota
from ratelimit import rate_limit_user
from database import db_session
from routers.photos import PHOTOS_FULL, save_photo_for
from security import current_user_id
from services.image_processing import process_image_bytes, remove_background_image
from services.photo_store import photo_count
from services.studio import StudioShotError, make_studio_shot
from services.uploads import heavy_image_work, read_upload, require_image_content_type
from settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()

_CANVAS = (768, 768)


# ---------------------------------------------------------------------------
# Helpers (CPU-bound — always run via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _open_image(body: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(body))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Cannot decode image") from exc


def _analyze_lighting(image: Image.Image) -> dict:
    img = image.convert("RGB")
    grayscale = img.convert("L")
    stat = ImageStat.Stat(grayscale)
    np_img = np.asarray(img)
    warmth = (float(np_img[:, :, 0].mean()) - float(np_img[:, :, 2].mean())) / 255.0
    return {
        "brightness": round(stat.mean[0] / 255.0, 3),
        "contrast": round(min(stat.stddev[0] / 128.0, 1.0), 3),
        "warmth": round(warmth, 3),
    }


def _editorial_background(size=_CANVAS) -> Image.Image:
    """Soft vertical gradient, built with numpy (the per-pixel Python loop it replaces took ~0.5 s)."""
    width, height = size
    ratio = np.linspace(0.0, 1.0, height, dtype=np.float32)
    rows = (250 * (1 - ratio) + 241 * ratio).astype(np.uint8)
    arr = np.empty((height, width, 4), dtype=np.uint8)
    arr[:, :, :3] = rows[:, None, None]
    arr[:, :, 3] = 255
    return Image.fromarray(arr, "RGBA")


def _style_image(body: bytes) -> bytes:
    original = _open_image(body).convert("RGBA")
    foreground = remove_background_image(original)

    canvas = _editorial_background()
    scale = min(_CANVAS[0] / foreground.width, _CANVAS[1] / foreground.height) * 0.88
    foreground = foreground.resize(
        (max(1, int(foreground.width * scale)), max(1, int(foreground.height * scale))),
        Image.LANCZOS,
    )
    x = (_CANVAS[0] - foreground.width) // 2
    y = int((_CANVAS[1] - foreground.height) * 0.38)

    shadow = Image.new("RGBA", foreground.size, (0, 0, 0, 90)).filter(ImageFilter.GaussianBlur(28))
    canvas.paste(shadow, (x + 6, y + 18), shadow)
    canvas.paste(foreground, (x, y), foreground)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _remove_background_png(body: bytes) -> bytes:
    output = remove_background_image(_open_image(body))
    buf = io.BytesIO()
    output.save(buf, format="PNG")
    return buf.getvalue()


async def _metered(uid: str, work):
    """Consume a bgremove unit, run ``work`` in a thread, refund if our side fails."""
    try:
        async with metered(uid, "bgremove"):
            return await asyncio.to_thread(work)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        log.exception("image processing failed")
        raise HTTPException(status_code=500, detail="Image processing failed. Please try again.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze-lighting", summary="Analyze image lighting: brightness, contrast, warmth")
async def analyze_lighting_endpoint(
    file: UploadFile = File(...),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("lighting", 30, 60)),
) -> dict:
    require_image_content_type(file)
    body = await read_upload(file)
    return await asyncio.to_thread(lambda: _analyze_lighting(_open_image(body)))


@router.post("/remove-bg", summary="Remove background and return a base64-encoded JPEG")
async def remove_bg_endpoint(
    file: UploadFile = File(...),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("bgremove", 20, 60)),
) -> dict:
    require_image_content_type(file)
    body = await read_upload(file)
    processed = await _metered(uid, lambda: process_image_bytes(body))
    return {"image": base64.standard_b64encode(processed).decode("ascii")}


class _UnusablePhoto(HTTPException):
    """A 422 for a photo we could not turn into a studio shot (no garment found, too small…)."""

    def __init__(self, detail: str):
        super().__init__(status_code=422, detail=detail)


def _studio_shot_work(body: bytes, uid: str = "", store: bool = False) -> dict:
    if store:
        # Check the cap BEFORE the expensive segmentation, not after: a user whose storage is full
        # must not be able to burn CPU on results that can never be kept.
        with db_session() as db:
            if photo_count(db, uid) >= get_settings().max_photos_per_user:
                raise HTTPException(status_code=403, detail=PHOTOS_FULL)
    try:
        shot = make_studio_shot(body)
    except StudioShotError as exc:
        # The photo is the problem, not us: a clear 422 the app can show as-is.
        raise _UnusablePhoto(str(exc)) from exc
    result = {
        "image": base64.standard_b64encode(shot.full).decode("ascii"),
        "thumb": base64.standard_b64encode(shot.thumb).decode("ascii"),
        "mime": "image/webp",
        "width": shot.width,
        "height": shot.height,
        "cutout_ok": shot.cutout_ok,
    }
    if store:
        # Keep it in the user's private storage right away: one round trip, and the app never
        # has to hold the only copy of a photo on the phone.
        saved = save_photo_for(uid, shot.full, shot.thumb, "webp")
        result.update(
            image_path=saved["image_path"], photo_id=saved["photo_id"],
            image_url=saved["image_url"], thumb_url=saved["thumb_url"],
        )
    return result


@router.post(
    "/studio-shot",
    summary="Clean cutout on a transparent 4:5 canvas: returns a full image and a thumbnail (WebP, base64)",
)
async def studio_shot_endpoint(
    file: UploadFile = File(...),
    store: bool = Query(False, description="Also keep the result in the caller's private photo storage"),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("bgremove", 20, 60)),
) -> dict:
    require_image_content_type(file)
    body = await read_upload(file)
    try:
        async with heavy_image_work:        # waits (without having been charged) while two others are running
            return await _metered(uid, lambda: _studio_shot_work(body, uid, store))
    except _UnusablePhoto:
        # Segmentation is local CPU work (no provider was billed), and a photo with no findable
        # garment is an ordinary thing for a person to try: don't charge them for it. Abuse is
        # bounded by the per-user rate limit above.
        await release_quota(uid, "bgremove")
        raise
    except HTTPException as exc:
        # Storage full: the user did nothing wrong that a charge should punish.
        if exc.status_code == 403 and isinstance(exc.detail, dict) and exc.detail.get("code") == "photos_full":
            await release_quota(uid, "bgremove")
        raise


@router.post("/remove-background", summary="Remove background and return a PNG with transparency")
async def remove_background_endpoint(
    file: UploadFile = File(...),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("bgremove", 20, 60)),
) -> Response:
    require_image_content_type(file)
    body = await read_upload(file)
    png = await _metered(uid, lambda: _remove_background_png(body))
    return Response(content=png, media_type="image/png")


@router.post("/style", summary="Remove background and place the garment on an editorial background")
async def style_image_endpoint(
    file: UploadFile = File(...),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("bgremove", 20, 60)),
) -> Response:
    require_image_content_type(file)
    body = await read_upload(file)
    jpeg = await _metered(uid, lambda: _style_image(body))
    return Response(content=jpeg, media_type="image/jpeg")
