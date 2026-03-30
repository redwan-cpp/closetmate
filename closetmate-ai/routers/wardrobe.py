"""Wardrobe management CRUD endpoints."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from database import get_db
from models.clothing import AddItemResponse, ClothingCreate, ClothingItem

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /wardrobe/add-item
# ---------------------------------------------------------------------------
@router.post(
    "/add-item",
    response_model=AddItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a clothing item to a user's wardrobe",
)
def add_item(
    payload: ClothingCreate,
    db: sqlite3.Connection = Depends(get_db),
) -> AddItemResponse:
    item_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    db.execute(
        """
        INSERT INTO wardrobe_items (
            item_id, user_id, category, primary_color, material,
            pattern, formality_level, cultural_style, image_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            payload.user_id,
            payload.category,
            payload.primary_color,
            payload.material,
            payload.pattern,
            payload.resolved_formality,
            payload.resolved_culture,
            payload.image_path,
            created_at,
        ),
    )
    db.commit()

    return AddItemResponse(status="success", item_id=item_id)


# ---------------------------------------------------------------------------
# GET /wardrobe/items/{user_id}
# ---------------------------------------------------------------------------
@router.get(
    "/items/{user_id}",
    response_model=List[ClothingItem],
    summary="List all wardrobe items for a user",
)
def list_items(
    user_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> List[ClothingItem]:
    rows = db.execute(
        "SELECT * FROM wardrobe_items WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()

    return [
        ClothingItem(
            item_id=row["item_id"],
            user_id=row["user_id"],
            category=row["category"],
            subcategory=None,          # not in schema yet — forward-compatible
            primary_color=row["primary_color"],
            material=row["material"],
            pattern=row["pattern"],
            formality_level=row["formality_level"],
            cultural_style=row["cultural_style"],
            image_path=row["image_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# DELETE /wardrobe/item/{item_id}
# ---------------------------------------------------------------------------
@router.delete(
    "/item/{item_id}",
    summary="Delete a clothing item by ID",
)
def delete_item(
    item_id: str,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    result = db.execute(
        "DELETE FROM wardrobe_items WHERE item_id = ?",
        (item_id,),
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item '{item_id}' not found",
        )
    db.commit()
    return {"deleted": item_id}
