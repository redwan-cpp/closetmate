"""Pydantic models for outfit recommendations."""
from __future__ import annotations

from typing import List
from pydantic import BaseModel


class OutfitRecommendationRequest(BaseModel):
    user_id: str
    occasion: str
    environment: str = "indoor"
    temperature: float = 25.0
    humidity: float = 60.0


class OutfitRecommendationResponse(BaseModel):
    outfits: List[List[str]]  # Each inner list is one outfit combination
