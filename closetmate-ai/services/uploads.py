"""
uploads.py — bounded reads for user-uploaded files.

``await file.read()`` loads the whole body into memory with no limit, which on
a public endpoint is a one-request way to exhaust a Cloud Run instance. These
helpers cap the size and reject empty bodies.
"""
from __future__ import annotations

import asyncio
import io
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from settings import get_settings

_CHUNK = 64 * 1024

# Decoding a phone photo (or segmenting it) takes hundreds of MB at the top of the size range, and a
# Cloud Run instance serves several requests at once. Two at a time per instance keeps a burst of
# uploads from running it out of memory; the rest simply wait their turn.
heavy_image_work = asyncio.Semaphore(2)


async def read_upload(
    file: UploadFile, *, max_bytes: Optional[int] = None, check_image: bool = True
) -> bytes:
    """
    Read an upload fully, enforcing a size cap. 400 if empty, 413 if too large (bytes or
    pixels), 422 if it is not a decodable image (disable with check_image=False).
    """
    limit = max_bytes or get_settings().max_upload_bytes
    chunks = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,        # literal: Starlette renamed the constant (and warns on the old name)
                detail=f"File too large (max {limit // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    data = b"".join(chunks)
    if check_image:
        _check_image_header(data)
    return data


def _check_image_header(data: bytes) -> None:
    """
    Reject non-images and pixel bombs by reading only the image HEADER (no decode).
    Pillow merely *warns* up to 2x MAX_IMAGE_PIXELS, so a small PNG that expands to
    hundreds of MB would otherwise sail through and be fully decoded later.
    """
    max_pixels = get_settings().max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        # main.py turns the "suspiciously large" warning into an error: that is a size problem, not a crash.
        raise HTTPException(status_code=413, detail="Image resolution too high") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        # Literal 422: the status-constant name changed between Starlette versions.
        raise HTTPException(status_code=422, detail="Cannot decode image") from exc
    if width * height > max_pixels:
        raise HTTPException(
            status_code=413,
            detail=f"Image resolution too high (max {max_pixels // 1_000_000} megapixels)",
        )


def require_image_content_type(file: UploadFile) -> None:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be an image")
