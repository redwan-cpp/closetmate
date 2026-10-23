"""
routers/upload.py — clothing image ingestion and AI tagging.

POST /upload/upload-clothing   background-removed copy stored (GCS in prod, disk locally)
POST /upload/analyze-clothing  vision-model metadata, DB-cached by image hash

Both require an access token (main.py). Vision calls cost money, so a monthly
"vision" quota unit is consumed only on a cache MISS and refunded if our side
fails. Heavy image work runs in a worker thread so it cannot stall other users.
"""
import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import get_cached_metadata, save_metadata_cache
from quota import metered
from ratelimit import rate_limit_user
from security import current_user_id
from services.image_processing import normalize_to_jpeg, remove_background_and_save
from services.metadata_extractor import extract_clothing_metadata, get_image_hash
from services.uploads import read_upload, require_image_content_type

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class UploadClothingResponse(BaseModel):
    image_path: str
    status: str


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

def _save_original(body: bytes) -> str:
    """
    Fallback when background removal fails: keep a clean JPEG copy of the photo.

    The bytes are always decoded and re-encoded (see normalize_to_jpeg) and stored with a
    fixed image/jpeg type — never the client's raw bytes or Content-Type, which would let
    anyone host arbitrary files on our bucket and would publish EXIF GPS coordinates.
    """
    jpeg = normalize_to_jpeg(body)
    filename = f"{uuid.uuid4().hex}.jpg"

    from services.gcs_storage import upload_bytes
    url = upload_bytes(jpeg, filename, content_type="image/jpeg")
    if url:
        return url

    folder = Path(__file__).resolve().parent.parent / "uploads" / "processed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(jpeg)
    return f"uploads/processed/{filename}"


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

@router.post("/upload-clothing", response_model=UploadClothingResponse)
async def upload_clothing(
    file: UploadFile = File(...),
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("upload", 20, 60)),
) -> UploadClothingResponse:
    """
    Upload a clothing image, attempt background removal, and store the result.
    If background removal fails the original image is stored instead so the
    caller always gets a valid server-side path.
    """
    require_image_content_type(file)
    body = await read_upload(file)

    try:
        image_path = await asyncio.to_thread(remove_background_and_save, body)
        status = "background_removed"
    except Exception as bg_err:  # noqa: BLE001
        log.warning("background removal failed (%s); keeping a clean copy", type(bg_err).__name__)
        try:
            image_path = await asyncio.to_thread(_save_original, body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Cannot decode image") from exc
        status = "original_saved"

    return UploadClothingResponse(image_path=image_path, status=status)


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
