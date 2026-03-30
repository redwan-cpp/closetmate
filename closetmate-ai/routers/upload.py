import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import get_cached_metadata, save_metadata_cache
from services.image_processing import remove_background_and_save_from_path
from services.metadata_extractor import extract_clothing_metadata, get_image_hash

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
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload-clothing", response_model=UploadClothingResponse)
async def upload_clothing(file: UploadFile = File(...)) -> UploadClothingResponse:
    """
    Upload a clothing image, run background removal, and save the result under
    uploads/processed/. Returns the path to the processed image.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        body = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}") from e

    if not body:
        raise HTTPException(status_code=400, detail="Empty file")

    suffix = Path(file.filename or "image").suffix or ".jpg"
    # On Windows, NamedTemporaryFile with delete=True holds an exclusive lock,
    # preventing other code from opening the file by path. Use delete=False and
    # clean up manually in a finally block instead.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(body)
            tmp_path = tmp.name  # file is closed after the with-block exits

        try:
            image_path = remove_background_and_save_from_path(tmp_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Processing failed: {e}") from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return UploadClothingResponse(
        image_path=image_path,
        status="background_removed",
    )


@router.post(
    "/analyze-clothing",
    response_model=AnalyzeClothingResponse,
    summary="Analyze a clothing image and return structured metadata",
)
async def analyze_clothing(file: UploadFile = File(...)) -> AnalyzeClothingResponse:
    """
    Full metadata extraction pipeline with MD5 caching.

    PRIMARY  → DB cache lookup (instant)
    SECONDARY → OpenAI Vision GPT-4o-mini (first call only)
    FALLBACK → Local CV pipeline (if OpenAI unavailable)

    Returns: image_path, cached flag, and 7-field suggested metadata.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        image_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}") from e

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    print("Image received")

    # ── 1. Compute MD5 hash ──────────────────────────────────────────────
    image_hash = get_image_hash(image_bytes)
    image_path = f"uploads/analyzed/{image_hash}.jpg"

    # ── 2. Cache lookup ──────────────────────────────────────────────────
    cached_row = get_cached_metadata(image_hash)
    if cached_row:
        print("Cache hit")
        print("Returning response")
        return AnalyzeClothingResponse(
            image_path=image_path,
            cached=True,
            suggested=SuggestedMetadata(
                category=cached_row.get("category") or "unknown",
                subcategory=cached_row.get("subcategory") or "unknown",
                primary_color=cached_row.get("primary_color") or "unknown",
                material=cached_row.get("material") or "unknown",
                pattern=cached_row.get("pattern") or "solid",
                formality=cached_row.get("formality") or "casual",
                culture=cached_row.get("culture") or "global",
            ),
        )

    # ── 3. Cache miss → run pipeline ─────────────────────────────────────
    print("Cache miss")
    print("Calling OpenAI Vision")

    try:
        metadata = await extract_clothing_metadata(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metadata extraction failed: {e}") from e

    # ── 4. Save result to cache ──────────────────────────────────────────
    try:
        save_metadata_cache(image_hash, metadata)
    except Exception as e:
        # Non-fatal — log and continue
        print(f"Warning: failed to write cache: {e}")

    print("Returning response")

    return AnalyzeClothingResponse(
        image_path=image_path,
        cached=False,
        suggested=SuggestedMetadata(
            category=metadata.get("category") or "unknown",
            subcategory=metadata.get("subcategory") or "unknown",
            primary_color=metadata.get("primary_color") or "unknown",
            material=metadata.get("material") or "unknown",
            pattern=metadata.get("pattern") or "solid",
            formality=metadata.get("formality") or metadata.get("formality_level") or "casual",
            culture=metadata.get("culture") or "global",
        ),
    )
