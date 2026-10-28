"""
routers/files.py — GET /files/photos/<user_id>/<photo_id>[_t].<ext>?e=<expiry>&s=<signature>

The only way a stored photo leaves the (private) bucket. The link carries its own proof of
access: an HMAC over the key and an expiry that the API only hands to the photo's owner
(services/photo_store.link). It is deliberately NOT behind the bearer token, because image views
in the app can't refresh an expired token mid-load; the signature is the capability.

A photo's content never changes under its key, so responses are cacheable forever.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from ratelimit import rate_limit_ip
from services.photo_store import content_type_for, get_store, verify_link

log = logging.getLogger(__name__)
router = APIRouter()


# Generous: one cold closet screen is ~100 requests, and a whole mobile carrier can share one IP.
# The signature, not this limit, is the access control; this only bounds abuse of a leaked link.
@router.get("/{key:path}", dependencies=[Depends(rate_limit_ip("files", 3000, 60))])
async def get_photo(key: str, e: str = "", s: str = "") -> Response:
    if not verify_link(key, e, s):
        # One answer for a bad signature, an expired link and a malformed key: nothing to learn.
        raise HTTPException(status_code=403, detail="This link is invalid or has expired")
    try:
        data = await asyncio.to_thread(get_store().get, key)
    except Exception:  # noqa: BLE001
        log.exception("could not read a stored photo")
        raise HTTPException(status_code=502, detail="Could not load the photo")
    if data is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=data,
        media_type=content_type_for(key),
        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )
