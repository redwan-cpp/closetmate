"""Skin tone detection endpoint."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from services.skin_tone_detector import detect_skin_tone

router = APIRouter()


@router.post(
    "/analyze-skin-tone",
    summary="Detect skin tone from a selfie image and return recommended colors",
)
async def analyze_skin_tone(file: UploadFile = File(...)) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        image_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}") from e

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        result = detect_skin_tone(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Skin tone detection failed: {e}") from e

    return result
