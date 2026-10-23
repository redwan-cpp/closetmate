"""Skin tone detection endpoint.

Deliberately NOT behind login: the registration flow scans a selfie *before* the
account exists. It is CPU-only (no paid API), IP rate-limited, and the photo is
processed in memory and never stored.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import UnidentifiedImageError

from ratelimit import rate_limit_ip
from services.skin_tone_detector import detect_skin_tone
from services.uploads import read_upload, require_image_content_type

log = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/analyze-skin-tone",
    summary="Detect skin tone from a selfie image and return recommended colors",
    dependencies=[Depends(rate_limit_ip("skin_tone", 10, 3600))],
)
async def analyze_skin_tone(file: UploadFile = File(...)) -> dict:
    require_image_content_type(file)
    image_bytes = await read_upload(file, max_bytes=8 * 1024 * 1024)

    try:
        return await asyncio.to_thread(detect_skin_tone, image_bytes)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Cannot decode image") from exc
    except Exception:  # noqa: BLE001
        log.exception("skin tone detection failed")
        raise HTTPException(status_code=500, detail="Skin tone detection failed")
