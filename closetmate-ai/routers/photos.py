"""
routers/photos.py — keep a closet photo in the user's private cloud storage.

POST /photos   multipart "file" -> stored (re-encoded, EXIF stripped, thumbnail made)
               returns {image_path, image_url, thumb_url, width, height, ...}

`image_path` is the object key to save on the item (add-item / PATCH item image); the two urls are
short-lived links for showing it right away. See services/photo_store.py.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import text

from database import db_session, get_db
from ratelimit import rate_limit_user
from security import current_user_id
from services.photo_store import (
    AccountGone, PhotoError, PhotoLimitError, content_type_for, delete_photo, prepare_photo, present, store_encoded,
)
from services.uploads import heavy_image_work, read_upload, require_image_content_type

log = logging.getLogger(__name__)
router = APIRouter()

PHOTOS_FULL = {
    "code": "photos_full",
    "message": "Your photo storage is full. Remove some pieces to add more.",
}


def save_photo_for(user_id: str, full: bytes, thumb: bytes, ext: str) -> dict:
    """Store + record one photo (runs in a worker thread). Raises HTTPException on user-facing errors."""
    try:
        with db_session() as db:
            saved = store_encoded(db, user_id, full, thumb, ext)
    except PhotoLimitError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PHOTOS_FULL)
    except AccountGone:
        # 401, not 403: the app reads it as "your session is over" and signs the user out.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:  # noqa: BLE001
        log.exception("could not store a photo")
        raise HTTPException(status_code=500, detail="Could not save the photo. Please try again.")
    image_url, thumb_url = present(saved["image_path"])
    return {**saved, "image_url": image_url, "thumb_url": thumb_url, "mime": content_type_for(saved["image_path"])}


@router.delete("/{photo_id}", dependencies=[Depends(rate_limit_user("photos", 60, 60))])
def delete_unused_photo(photo_id: str, uid: str = Depends(current_user_id), db: Any = Depends(get_db)) -> dict:
    """Discard a photo that was stored but never attached to an item (e.g. the user cancelled)."""
    row = None
    if re.fullmatch(r"[0-9a-f]{32}", photo_id):
        row = db.execute(
            text("SELECT key FROM photos WHERE photo_id = :p AND user_id = :u"), {"p": photo_id, "u": uid}
        ).fetchone()
    if row is None:                                   # someone else's photo looks exactly like a missing one
        raise HTTPException(status_code=404, detail="Photo not found")
    in_use = db.execute(
        text("SELECT 1 FROM wardrobe_items WHERE user_id = :u AND image_path = :k"), {"u": uid, "k": row["key"]}
    ).fetchone()
    if in_use:
        raise HTTPException(status_code=409, detail="This photo belongs to an item in your closet")
    delete_photo(db, uid, row["key"])
    return {"status": "deleted", "photo_id": photo_id}


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit_user("photos", 60, 60))])
async def upload_photo(file: UploadFile = File(...), uid: str = Depends(current_user_id)) -> dict:
    require_image_content_type(file)
    body = await read_upload(file)
    try:
        async with heavy_image_work:
            prepared = await asyncio.to_thread(prepare_photo, body)
    except PhotoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = await asyncio.to_thread(save_photo_for, uid, prepared.full, prepared.thumb, prepared.ext)
    return {**saved, "width": prepared.width, "height": prepared.height}
