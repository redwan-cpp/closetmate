"""
POST /recommend/outfit — context-aware, multi-cultural outfit recommendation.

Input:
    { "user_id": "...", "occasion": "holud", "temperature": 32, "humidity": 85 }

Output:
    {
        "best_outfit":  [{item}, ...],
        "alternatives": [[{item}, ...], [{item}, ...]],
        "scores":       {
            "best":         {"color_harmony": 0.8, "weather_suitability": 0.9,
                             "cultural_relevance": 0.95, "total": 0.88},
            "alternatives": [...]
        },
        "context":      {"culture": "south_asian", "formality": "festive", "occasion": "holud"},
        "weather":      {"temperature": 32, "humidity": 85, "advisory": "..."},
        "outfits":      []   ← legacy field for backward compat
    }
"""
from __future__ import annotations

import logging
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from database import get_db
from models.outfit import (
    OutfitContext,
    OutfitItem,
    OutfitRecommendationRequest,
    OutfitRecommendationResponse,
    OutfitScoreBreakdown,
    OutfitScores,
    WeatherSummary,
)
from services.context_engine import recommend_outfits

log = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/outfit",
    response_model=OutfitRecommendationResponse,
    summary="Generate multi-cultural outfit recommendations based on occasion and weather",
)
def outfit_recommendation(
    payload: OutfitRecommendationRequest,
    db: sqlite3.Connection = Depends(get_db),
) -> OutfitRecommendationResponse:
    """
    Generate ranked outfit combinations from the user's wardrobe.

    - Cultural rules map the occasion to the correct style/formality profile.
    - Weather filtering excludes inappropriate fabrics and colors.
    - Color harmony and cultural relevance scores determine the final ranking.
    - The `scores` field exposes the full breakdown for each returned outfit.
    """
    try:
        result = recommend_outfits(
            user_id=payload.user_id,
            occasion=payload.occasion,
            environment=payload.environment,
            temperature=payload.temperature,
            humidity=payload.humidity,
            db=db,
        )
    except Exception as exc:
        log.exception("outfit_recommendation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Recommendation failed: {exc}") from exc

    # ── Parse Pydantic models from raw dicts ────────────────────────────────
    def _parse_items(raw_list: list) -> List[OutfitItem]:
        return [OutfitItem(**item) for item in raw_list]

    def _parse_score(raw: dict | None) -> OutfitScoreBreakdown | None:
        if not raw:
            return None
        return OutfitScoreBreakdown(**raw)

    ctx_raw  = result.get("context", {})
    wthr_raw = result.get("weather",  {})
    scores_raw = result.get("scores", {})

    # Build OutfitScores model
    scores_model: OutfitScores | None = None
    if scores_raw:
        scores_model = OutfitScores(
            best=_parse_score(scores_raw.get("best")),
            alternatives=[
                OutfitScoreBreakdown(**s)
                for s in (scores_raw.get("alternatives") or [])
                if s
            ],
        )

    return OutfitRecommendationResponse(
        best_outfit=_parse_items(result.get("best_outfit", [])),
        alternatives=[_parse_items(alt) for alt in result.get("alternatives", [])],
        scores=scores_model,
        context=OutfitContext(**ctx_raw)    if ctx_raw  else None,
        weather=WeatherSummary(**wthr_raw)  if wthr_raw else None,
        outfits=[],   # legacy field — kept for backward compat
    )
