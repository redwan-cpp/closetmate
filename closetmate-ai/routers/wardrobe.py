# routers/wardrobe.py
# ─────────────────────────────────────────────────────────────────
# Wardrobe CRUD + outfit recommendation
# Endpoints:
#   GET    /wardrobe/items/{user_id}   — list user's wardrobe
#   POST   /wardrobe/add-item          — save a new item
#   DELETE /wardrobe/item/{item_id}    — delete an item
#   POST   /wardrobe/recommend         — AI outfit recommendation
# ─────────────────────────────────────────────────────────────────

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from database import get_db
from services.recommendation_engine import build_outfits, ai_refine_outfits, get_weather_category

router = APIRouter()


# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────

class AddItemPayload(BaseModel):
    user_id: str
    image_path: str
    category: str
    subcategory: Optional[str] = None
    primary_color: Optional[str] = None
    material: Optional[str] = None
    pattern: Optional[str] = None
    formality: Optional[str] = None
    culture: Optional[str] = None


class WardrobeItemOut(BaseModel):
    item_id: str
    user_id: str
    category: Optional[str]
    subcategory: Optional[str]
    primary_color: Optional[str]
    material: Optional[str]
    pattern: Optional[str]
    formality_level: Optional[str]
    cultural_style: Optional[str]
    image_path: Optional[str]
    created_at: str


class RecommendationRequest(BaseModel):
    wardrobe:    List[dict]
    occasion:    str
    temperature: float
    humidity:    float
    culture:     Optional[str] = "south_asian"
    top_n:       Optional[int] = 3


# ─────────────────────────────────────────────
# GET /wardrobe/items/{user_id}
# ─────────────────────────────────────────────

@router.get("/items/{user_id}", response_model=List[WardrobeItemOut])
def get_wardrobe_items(
    user_id: str,
    db: Any = Depends(get_db),
):
    """Return all wardrobe items for a given user."""
    rows = db.execute(
        text("SELECT * FROM wardrobe_items WHERE user_id = :uid ORDER BY created_at DESC"),
        {"uid": user_id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


# ─────────────────────────────────────────────
# POST /wardrobe/add-item
# ─────────────────────────────────────────────

@router.post("/add-item")
def add_wardrobe_item(
    payload: AddItemPayload,
    db: Any = Depends(get_db),
):
    """Save a new clothing item to the user's wardrobe."""
    item_id  = str(uuid.uuid4())
    now      = datetime.now(timezone.utc).isoformat()

    db.execute(
        text("""
        INSERT INTO wardrobe_items
          (item_id, user_id, category, subcategory, primary_color,
           material, pattern, formality_level, cultural_style, image_path, created_at)
        VALUES (:item_id, :user_id, :category, :subcategory, :primary_color,
                :material, :pattern, :formality, :culture, :image_path, :created_at)
        """),
        {
            "item_id": item_id,
            "user_id": payload.user_id,
            "category": payload.category,
            "subcategory": payload.subcategory,
            "primary_color": payload.primary_color,
            "material": payload.material,
            "pattern": payload.pattern,
            "formality": payload.formality,
            "culture": payload.culture,
            "image_path": payload.image_path,
            "created_at": now,
        },
    )
    db.commit()
    return {"status": "success", "item_id": item_id}


# ─────────────────────────────────────────────
# DELETE /wardrobe/item/{item_id}
# ─────────────────────────────────────────────

@router.delete("/item/{item_id}")
def delete_wardrobe_item(
    item_id: str,
    db: Any = Depends(get_db),
):
    """Permanently delete a clothing item by ID."""
    result = db.execute(
        text("DELETE FROM wardrobe_items WHERE item_id = :item_id"),
        {"item_id": item_id},
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "deleted", "item_id": item_id}


# ─────────────────────────────────────────────
# POST /wardrobe/recommend
# ─────────────────────────────────────────────

VALID_OCCASIONS = [
    "holud", "wedding", "eid", "office", "casual", "party",
    "funeral", "prayer", "beach", "festival", "new_year",
]

@router.post("/recommend")
async def recommend_outfits(request: RecommendationRequest):
    """AI-powered outfit recommendation from an explicit wardrobe payload."""
    if request.occasion.lower() not in VALID_OCCASIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid occasion. Choose from: {VALID_OCCASIONS}",
        )

    weather_cat = get_weather_category(request.temperature, request.humidity)

    outfits = build_outfits(
        wardrobe=request.wardrobe,
        occasion=request.occasion,
        temperature=request.temperature,
        humidity=request.humidity,
        culture=request.culture,
        top_n=request.top_n,
    )

    if not outfits:
        raise HTTPException(
            status_code=404,
            detail="No suitable outfits found. Try adding more items to your wardrobe.",
        )

    result = await ai_refine_outfits(
        outfits=outfits,
        occasion=request.occasion,
        weather_cat=weather_cat,
        culture=request.culture,
    )
    return result


# ─────────────────────────────────────────────
# POST /wardrobe/log-worn
# ─────────────────────────────────────────────

class LogWornPayload(BaseModel):
    user_id: str
    item_ids: List[str]  # list of item_id strings from the AI suggestion


@router.post("/log-worn")
def log_worn_outfit(
    payload: LogWornPayload,
    db: Any = Depends(get_db),
):
    """Record that the user is wearing a specific outfit today."""
    import json as _json
    log_id  = str(uuid.uuid4())
    now     = datetime.now(timezone.utc)
    worn_date = now.date().isoformat()   # "2026-04-25"

    db.execute(
        text("""
        INSERT INTO worn_logs (log_id, user_id, worn_date, item_ids, created_at)
        VALUES (:log_id, :user_id, :worn_date, :item_ids, :created_at)
        """),
        {
            "log_id":    log_id,
            "user_id":   payload.user_id,
            "worn_date": worn_date,
            "item_ids":  _json.dumps(payload.item_ids),
            "created_at": now.isoformat(),
        },
    )
    db.commit()
    return {"status": "logged", "log_id": log_id, "worn_date": worn_date}


# ─────────────────────────────────────────────
# GET /wardrobe/worn-history/{user_id}
# ─────────────────────────────────────────────

class WornItem(BaseModel):
    item_id: str
    image_path: Optional[str]
    category: Optional[str]
    subcategory: Optional[str]
    primary_color: Optional[str]

class WornLogOut(BaseModel):
    log_id: str
    worn_date: str
    items: List[WornItem]

@router.get("/worn-history/{user_id}", response_model=List[WornLogOut])
def get_worn_history(
    user_id: str,
    limit: int = 7,
    db: Any = Depends(get_db),
):
    """Return the last `limit` worn outfit logs for the user, with item images."""
    import json as _json

    rows = db.execute(
        text("""
        SELECT log_id, worn_date, item_ids
        FROM worn_logs
        WHERE user_id = :uid
        ORDER BY worn_date DESC, created_at DESC
        LIMIT :lim
        """),
        {"uid": user_id, "lim": limit},
    ).fetchall()

    result = []
    for row in rows:
        item_ids = _json.loads(row["item_ids"])
        items = []
        for iid in item_ids:
            w = db.execute(
                text("SELECT item_id, image_path, category, subcategory, primary_color FROM wardrobe_items WHERE item_id = :iid"),
                {"iid": iid},
            ).fetchone()
            if w:
                items.append(WornItem(
                    item_id=w["item_id"],
                    image_path=w["image_path"],
                    category=w["category"],
                    subcategory=w["subcategory"],
                    primary_color=w["primary_color"],
                ))
        result.append(WornLogOut(
            log_id=row["log_id"],
            worn_date=row["worn_date"],
            items=items,
        ))
    return result

