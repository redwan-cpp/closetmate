"""
routers/upload.py — clothing image ingestion and AI tagging.

POST /upload/analyze-clothing  vision-model metadata, DB-cached by image hash
POST /upload/upload-clothing   RETIRED (410): it published photos to a public bucket. Photos are
                               stored privately through POST /photos or POST /studio-shot?store=1.

Requires an access token (main.py). Vision calls cost money, so a monthly
"vision" quota unit is consumed only on a cache MISS and refunded if our side
fails. Heavy image work runs in a worker thread so it cannot stall other users.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import get_cached_metadata, save_metadata_cache
from quota import metered
from ratelimit import rate_limit_user
from security import current_user_id
from services.metadata_extractor import extract_clothing_metadata, get_image_hash
from services.uploads import read_upload, require_image_content_type

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SuggestedMetadata(BaseModel):
    category: str
    subcategory: str
    primary_color: str
    material: str
    pattern: str
    formality: str
    culture: str


class AnalyzeClothingResponse(BaseModel):
    image_path: str
    cached: bool
    suggested: SuggestedMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suggested(meta: dict) -> SuggestedMetadata:
    return SuggestedMetadata(
        category=meta.get("category") or "unknown",
        subcategory=meta.get("subcategory") or "unknown",
        primary_color=meta.get("primary_color") or "unknown",
        material=meta.get("material") or "unknown",
        pattern=meta.get("pattern") or "solid",
        formality=meta.get("formality") or meta.get("formality_level") or "casual",
        culture=meta.get("culture") or "global",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload-clothing", include_in_schema=False)
async def upload_clothing_retired(uid: str = Depends(current_user_id)) -> None:
    """Retired: it wrote photos to a PUBLIC bucket. Current apps use POST /studio-shot?store=1."""
    raise HTTPException(status_code=410, detail="This feature was retired. Please update the app.")


@router.post(
    "/analyze-clothing",
    response_model=AnalyzeClothingResponse,
    summary="Analyze a clothing image and return structured metadata",
)
async def analyze_clothing(
    file: UploadFile = File(...),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("analyze", 20, 60)),
) -> AnalyzeClothingResponse:
    """
    PRIMARY   → DB cache lookup (free, instant)
    SECONDARY → OpenAI vision (costs money: consumes one "vision" quota unit)
    FALLBACK  → local CV pipeline if the provider is unavailable
    """
    require_image_content_type(file)
    image_bytes = await read_upload(file)

    image_hash = get_image_hash(image_bytes)
    image_path = f"uploads/analyzed/{image_hash}.jpg"

    cached_row = await asyncio.to_thread(get_cached_metadata, image_hash)
    if cached_row:
        return AnalyzeClothingResponse(image_path=image_path, cached=True, suggested=_suggested(cached_row))

    try:
        # One vision unit, refunded only if we fail BEFORE the provider answers.
        async with metered(uid, "vision"):
            metadata = await extract_clothing_metadata(image_bytes, user_id=uid)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        log.exception("metadata extraction failed")
        raise HTTPException(status_code=500, detail="Could not analyze this image. Please try again.")

    try:
        await asyncio.to_thread(save_metadata_cache, image_hash, metadata)
    except Exception:  # noqa: BLE001 — non-fatal: the user still gets their result
        log.warning("failed to write metadata cache", exc_info=True)

    return AnalyzeClothingResponse(image_path=image_path, cached=False, suggested=_suggested(metadata))
