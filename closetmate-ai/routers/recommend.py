"""Outfit recommendation endpoint."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from database import get_db
from models.outfit import OutfitRecommendationRequest, OutfitRecommendationResponse
from services.context_engine import recommend_outfits

router = APIRouter()


@router.post(
    "/outfit",
    response_model=OutfitRecommendationResponse,
    summary="Generate outfit recommendations based on occasion and weather",
)
def outfit_recommendation(
    payload: OutfitRecommendationRequest,
    db: sqlite3.Connection = Depends(get_db),
) -> OutfitRecommendationResponse:
    outfits = recommend_outfits(
        user_id=payload.user_id,
        occasion=payload.occasion,
        environment=payload.environment,
        temperature=payload.temperature,
        humidity=payload.humidity,
        db=db,
    )
    return OutfitRecommendationResponse(outfits=outfits)
