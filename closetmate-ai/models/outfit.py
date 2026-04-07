"""Pydantic models for outfit recommendations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class OutfitRecommendationRequest(BaseModel):
    user_id: str
    occasion: str
    environment: str = "indoor"
    temperature: float = 25.0
    humidity: float = 60.0


class OutfitItem(BaseModel):
    """A single clothing item inside a recommended outfit."""
    item_id:       str
    category:      Optional[str] = None
    subcategory:   Optional[str] = None
    primary_color: Optional[str] = None
    material:      Optional[str] = None
    pattern:       Optional[str] = None
    formality:     Optional[str] = None
    culture:       Optional[str] = None
    image_path:    Optional[str] = None


class WeatherSummary(BaseModel):
    temperature: float
    humidity:    float
    advisory:    str


class OutfitContext(BaseModel):
    culture:   str
    formality: str
    occasion:  str


class OutfitScoreBreakdown(BaseModel):
    """Per-outfit scoring details returned alongside recommendations."""
    color_harmony:       float
    weather_suitability: float
    cultural_relevance:  float
    total:               float


class OutfitScores(BaseModel):
    """Score breakdowns for the best outfit and each alternative."""
    best:         Optional[OutfitScoreBreakdown] = None
    alternatives: List[OutfitScoreBreakdown] = []


class OutfitRecommendationResponse(BaseModel):
    best_outfit:  List[OutfitItem]                  # top-ranked outfit
    alternatives: List[List[OutfitItem]]             # next 2 outfits
    scores:       Optional[OutfitScores] = None      # ranking score breakdown
    context:      Optional[OutfitContext] = None
    weather:      Optional[WeatherSummary] = None

    # Legacy field — keeps older clients working
    outfits: List[List[str]] = []


# Keep backward-compat alias
OutfitRecommendationRequest = OutfitRecommendationRequest
