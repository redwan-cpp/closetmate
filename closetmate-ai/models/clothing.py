"""Pydantic models for wardrobe clothing items."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ClothingCreate(BaseModel):
    """Fields provided by the client when adding a new item."""
    user_id: str

    # Core metadata — accept both the analyse-endpoint names and the DB names
    category: Optional[str] = None
    subcategory: Optional[str] = None
    primary_color: Optional[str] = None
    material: Optional[str] = None
    pattern: Optional[str] = None

    # formality: frontend sends "formality"; DB column is formality_level
    formality: Optional[str] = None
    formality_level: Optional[str] = None

    # culture: frontend sends "culture"; DB column is cultural_style
    culture: Optional[str] = None
    cultural_style: Optional[str] = None

    image_path: Optional[str] = None

    @property
    def resolved_formality(self) -> Optional[str]:
        return self.formality_level or self.formality

    @property
    def resolved_culture(self) -> Optional[str]:
        return self.cultural_style or self.culture


class ClothingItem(BaseModel):
    """Full clothing item as stored and returned from the database."""
    item_id: str
    user_id: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    primary_color: Optional[str] = None
    material: Optional[str] = None
    pattern: Optional[str] = None
    formality_level: Optional[str] = None
    cultural_style: Optional[str] = None
    image_path: Optional[str] = None
    created_at: datetime


class AddItemResponse(BaseModel):
    """Response returned after successfully adding an item."""
    status: str
    item_id: str
