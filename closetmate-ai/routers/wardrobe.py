# routers/wardrobe.py
# ─────────────────────────────────────────────────────────────────
# Wardrobe CRUD + worn-history. Every route requires a valid access token
# (applied in main.py) and only ever touches the *authenticated* user's rows.
#
#   GET    /wardrobe/items/{user_id}         list the user's wardrobe
#   POST   /wardrobe/add-item                save a new item
#   DELETE /wardrobe/item/{item_id}          delete one of the user's items
#   POST   /wardrobe/recommend               AI outfit recommendation (quota: chat)
#   POST   /wardrobe/log-worn                record an outfit as worn today
#   GET    /wardrobe/worn-history/{user_id}  recent worn outfits with item images
#   POST   /wardrobe/looks                   save an outfit ("Look")
#   GET    /wardrobe/looks/{user_id}          the user's saved looks, newest first
#   DELETE /wardrobe/looks/{look_id}          delete a saved look
# ─────────────────────────────────────────────────────────────────

import asyncio
import json
import logging
import re
import threading
import uuid
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import bindparam, text

from database import engine, get_db
from quota import metered
from ratelimit import rate_limit_user
from security import current_user_id, require_same_user
from services.outfit_layout import outfit_slot
from services.recommendation_engine import ai_refine_outfits, build_outfits, get_weather_category
from settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────

_IMAGE_PATH_RE = re.compile(r"^(file://|content://|uploads/|https://storage\.googleapis\.com/)")


def _checked_image_path(value: str) -> str:
    """Shared by every payload that carries an image location (add-item, replace-image)."""
    # The app renders this as an image URI, so don't let it point at arbitrary hosts.
    if not _IMAGE_PATH_RE.match(value):
        raise ValueError("image_path must be a device file, an uploads/ path or a storage URL")
    # The app renders BACKEND_URL + "/" + path for uploads/ values: forbid ".." so
    # "uploads/../health" can't make it request an arbitrary same-origin URL.
    # Percent-decode first (twice, for double encoding): URL parsers treat "%2e%2e" as "..".
    decoded = value
    for _ in range(2):
        decoded = unquote(decoded)
    if ".." in decoded.replace("\\", "/").split("/"):
        raise ValueError("image_path must not contain '..' segments")
    return value


class AddItemPayload(BaseModel):
    user_id: str
    image_path: str = Field(max_length=2048)

    @field_validator("image_path")
    @classmethod
    def _known_image_location(cls, value: str) -> str:
        return _checked_image_path(value)

    category: str = Field(max_length=60)
    subcategory: Optional[str] = Field(default=None, max_length=60)
    primary_color: Optional[str] = Field(default=None, max_length=60)
    material: Optional[str] = Field(default=None, max_length=60)
    pattern: Optional[str] = Field(default=None, max_length=60)
    formality: Optional[str] = Field(default=None, max_length=40)
    culture: Optional[str] = Field(default=None, max_length=40)


class ReplaceImagePayload(BaseModel):
    image_path: str = Field(max_length=2048)

    @field_validator("image_path")
    @classmethod
    def _known_image_location(cls, value: str) -> str:
        return _checked_image_path(value)


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
    slot: str = "accessory"       # outer | dress | top | bottom | shoes | accessory (see outfit_layout)


class RecommendationRequest(BaseModel):
    wardrobe:    List[dict] = Field(max_length=300)
    occasion:    str = Field(max_length=40)
    temperature: float
    humidity:    float
    culture:     Optional[str] = Field(default="south_asian", max_length=40)
    top_n:       Optional[int] = Field(default=3, ge=1, le=10)


# ─────────────────────────────────────────────
# GET /wardrobe/items/{user_id}
# ─────────────────────────────────────────────

@router.get("/items/{user_id}", response_model=List[WardrobeItemOut])
def get_wardrobe_items(
    user_id: str,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Return all wardrobe items for the authenticated user."""
    require_same_user(user_id, uid)
    rows = db.execute(
        text("SELECT * FROM wardrobe_items WHERE user_id = :uid ORDER BY created_at DESC"),
        {"uid": uid},
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row._mapping)
        item["slot"] = outfit_slot(item.get("category"), item.get("subcategory"))
        items.append(item)
    return items


# ─────────────────────────────────────────────
# POST /wardrobe/add-item
# ─────────────────────────────────────────────

@router.post(
    "/add-item",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_user("add_item", 60, 60))],
)
def add_wardrobe_item(
    payload: AddItemPayload,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Save a new clothing item to the authenticated user's wardrobe."""
    require_same_user(payload.user_id, uid)

    # Bounds storage and — because the wardrobe is sent to the LLM — prompt size per call.
    limit = get_settings().max_wardrobe_items
    count = db.execute(
        text("SELECT COUNT(*) AS n FROM wardrobe_items WHERE user_id = :uid"), {"uid": uid}
    ).fetchone()["n"]
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "wardrobe_full",
                    "message": f"Your closet is full ({limit} items). Remove something to add more."},
        )

    item_id = str(uuid.uuid4())

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
            "user_id": uid,
            "category": payload.category,
            "subcategory": payload.subcategory,
            "primary_color": payload.primary_color,
            "material": payload.material,
            "pattern": payload.pattern,
            "formality": payload.formality,
            "culture": payload.culture,
            "image_path": payload.image_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.commit()
    return {"status": "success", "item_id": item_id}


# ─────────────────────────────────────────────
# PATCH /wardrobe/item/{item_id}/image
# ─────────────────────────────────────────────

@router.patch(
    "/item/{item_id}/image",
    dependencies=[Depends(rate_limit_user("replace_image", 60, 60))],
)
def replace_item_image(
    item_id: str,
    payload: ReplaceImagePayload,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """
    Point one of the caller's items at a new photo (the app uses it to upgrade an old photo to a
    studio shot). Only the photo changes; the item keeps its id, so saved looks and wear history
    stay intact. Scoped by user_id: someone else's item looks exactly like a missing one (404).
    """
    result = db.execute(
        text("UPDATE wardrobe_items SET image_path = :image_path WHERE item_id = :item_id AND user_id = :uid"),
        {"image_path": payload.image_path, "item_id": item_id, "uid": uid},
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"status": "updated", "item_id": item_id}


# ─────────────────────────────────────────────
# DELETE /wardrobe/item/{item_id}
# ─────────────────────────────────────────────

@router.delete("/item/{item_id}")
def delete_wardrobe_item(
    item_id: str,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Permanently delete one of the authenticated user's items."""
    # Scoped by user_id: someone else's item looks exactly like a missing one (404).
    result = db.execute(
        text("DELETE FROM wardrobe_items WHERE item_id = :item_id AND user_id = :uid"),
        {"item_id": item_id, "uid": uid},
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
async def recommend_outfits(
    request: RecommendationRequest,
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("recommend", 10, 60)),
):
    """AI-powered outfit recommendation from an explicit wardrobe payload."""
    if request.occasion.lower() not in VALID_OCCASIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid occasion. Choose from: {VALID_OCCASIONS}",
        )

    weather_cat = get_weather_category(request.temperature, request.humidity)

    # Free CPU work first, off the event loop. Only the paid LLM call below is metered,
    # so invalid or empty requests never consume a quota unit.
    outfits = await asyncio.to_thread(
        build_outfits,
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

    async with metered(uid, "chat"):
        return await ai_refine_outfits(
            outfits=outfits,
            occasion=request.occasion,
            weather_cat=weather_cat,
            culture=request.culture,
        )


# ─────────────────────────────────────────────
# POST /wardrobe/log-worn
# ─────────────────────────────────────────────

class LogWornPayload(BaseModel):
    user_id: str
    item_ids: List[str] = Field(min_length=1, max_length=20)


@router.post("/log-worn")
def log_worn_outfit(
    payload: LogWornPayload,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Record that the user is wearing a specific outfit today."""
    require_same_user(payload.user_id, uid)

    # Only items that really belong to this user may be logged.
    owned_rows = db.execute(
        text("SELECT item_id FROM wardrobe_items WHERE user_id = :uid AND item_id IN :ids")
        .bindparams(bindparam("ids", expanding=True)),
        {"uid": uid, "ids": payload.item_ids},
    ).fetchall()
    owned = {r["item_id"] for r in owned_rows}
    item_ids = [i for i in payload.item_ids if i in owned]
    if not item_ids:
        raise HTTPException(status_code=400, detail="None of these items are in your wardrobe")

    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    worn_date = now.date().isoformat()   # "2026-04-25"

    db.execute(
        text("""
        INSERT INTO worn_logs (log_id, user_id, worn_date, item_ids, created_at)
        VALUES (:log_id, :user_id, :worn_date, :item_ids, :created_at)
        """),
        {
            "log_id": log_id,
            "user_id": uid,
            "worn_date": worn_date,
            "item_ids": json.dumps(item_ids),
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
    slot: str = "accessory"

class WornLogOut(BaseModel):
    log_id: str
    worn_date: str
    items: List[WornItem]

@router.get("/worn-history/{user_id}", response_model=List[WornLogOut])
def get_worn_history(
    user_id: str,
    limit: int = Query(default=7, ge=1, le=50),
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Return the last `limit` worn outfit logs for the user, with item images."""
    require_same_user(user_id, uid)

    logs = db.execute(
        text("""
        SELECT log_id, worn_date, item_ids
        FROM worn_logs
        WHERE user_id = :uid
        ORDER BY worn_date DESC, created_at DESC
        LIMIT :lim
        """),
        {"uid": uid, "lim": limit},
    ).fetchall()

    parsed = []
    wanted: set = set()
    for row in logs:
        try:
            ids = [i for i in json.loads(row["item_ids"]) if isinstance(i, str)]
        except (TypeError, ValueError):
            ids = []
        parsed.append((row["log_id"], row["worn_date"], ids))
        wanted.update(ids)

    # One query for every item across all logs (was one query per item).
    items_by_id = {}
    if wanted:
        item_rows = db.execute(
            text("""SELECT item_id, image_path, category, subcategory, primary_color
                    FROM wardrobe_items WHERE user_id = :uid AND item_id IN :ids""")
            .bindparams(bindparam("ids", expanding=True)),
            {"uid": uid, "ids": sorted(wanted)},
        ).fetchall()
        items_by_id = {r["item_id"]: r for r in item_rows}

    return [
        WornLogOut(
            log_id=log_id,
            worn_date=worn_date,
            items=[
                WornItem(
                    item_id=w["item_id"],
                    image_path=w["image_path"],
                    category=w["category"],
                    subcategory=w["subcategory"],
                    primary_color=w["primary_color"],
                    slot=outfit_slot(w["category"], w["subcategory"]),
                )
                for w in (items_by_id.get(i) for i in ids)
                if w is not None
            ],
        )
        for log_id, worn_date, ids in parsed
    ]


# ─────────────────────────────────────────────
# Saved looks — outfits the user chose to keep (the "Looks" tab)
# ─────────────────────────────────────────────

class SaveLookPayload(BaseModel):
    user_id: str
    item_ids: List[str] = Field(min_length=1, max_length=8)
    name: Optional[str] = Field(default=None, max_length=60)


class LookItem(BaseModel):
    item_id: str
    image_path: Optional[str]
    category: Optional[str]
    subcategory: Optional[str]
    primary_color: Optional[str]
    slot: str = "accessory"


class LookOut(BaseModel):
    look_id: str
    name: Optional[str]
    created_at: str
    items: List[LookItem]


def _owned_items(db, uid: str, ids) -> dict:
    """{item_id: row} for the ids that belong to uid — one query, never one per item."""
    ids = sorted(set(ids))
    if not ids:
        return {}
    rows = db.execute(
        text("""SELECT item_id, image_path, category, subcategory, primary_color
                FROM wardrobe_items WHERE user_id = :uid AND item_id IN :ids""")
        .bindparams(bindparam("ids", expanding=True)),
        {"uid": uid, "ids": ids},
    ).fetchall()
    return {r["item_id"]: r for r in rows}


# Saves by one user are serialised, so "is this outfit already saved?" and "is there room for
# another?" can't both be answered yes to two simultaneous requests (a double tap would store
# the outfit twice; a burst could overshoot MAX_SAVED_LOOKS). The in-process lock covers
# threads and the dev SQLite file; the Postgres advisory lock covers other instances. The
# stripe count only bounds memory — two users sharing a stripe merely wait for each other.
_SAVE_LOCKS = tuple(threading.Lock() for _ in range(64))


@contextmanager
def _one_save_at_a_time(db, uid: str):
    with _SAVE_LOCKS[zlib.crc32(uid.encode("utf-8")) % len(_SAVE_LOCKS)]:
        if engine.dialect.name == "postgresql":
            # Held until this request's transaction commits or rolls back.
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"saved_looks:{uid}"})
        yield


@router.post("/looks", status_code=status.HTTP_201_CREATED)
def save_look(
    payload: SaveLookPayload,
    response: Response,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Keep an outfit. Saving the same set of items twice returns the existing look (HTTP 200)."""
    require_same_user(payload.user_id, uid)

    owned = _owned_items(db, uid, payload.item_ids)
    item_ids = [i for i in dict.fromkeys(payload.item_ids) if i in owned]   # de-dupe, keep order
    if not item_ids:
        raise HTTPException(status_code=400, detail="None of these items are in your wardrobe")

    with _one_save_at_a_time(db, uid):
        existing = db.execute(
            text("SELECT look_id, item_ids FROM saved_looks WHERE user_id = :uid"), {"uid": uid}
        ).fetchall()
        wanted = sorted(item_ids)
        for row in existing:
            try:
                if sorted(json.loads(row["item_ids"])) == wanted:
                    response.status_code = status.HTTP_200_OK
                    return {"status": "exists", "look_id": row["look_id"]}
            except (TypeError, ValueError):
                continue

        limit = get_settings().max_saved_looks
        if len(existing) >= limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "looks_full",
                        "message": f"You have {limit} saved looks. Delete one to save another."},
            )

        look_id = str(uuid.uuid4())
        db.execute(
            text("""INSERT INTO saved_looks (look_id, user_id, name, item_ids, created_at)
                    VALUES (:look_id, :uid, :name, :item_ids, :created_at)"""),
            {
                "look_id": look_id,
                "uid": uid,
                "name": (payload.name or "").strip() or None,
                "item_ids": json.dumps(item_ids),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.commit()           # still inside the lock: the next save must see this row
    return {"status": "saved", "look_id": look_id}


@router.get("/looks/{user_id}", response_model=List[LookOut])
def list_looks(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    """Saved looks, newest first, each with its items (one query for all of them)."""
    require_same_user(user_id, uid)

    looks = db.execute(
        text("""SELECT look_id, name, item_ids, created_at FROM saved_looks
                WHERE user_id = :uid ORDER BY created_at DESC LIMIT :lim"""),
        {"uid": uid, "lim": limit},
    ).fetchall()

    parsed = []
    wanted: set = set()
    for row in looks:
        try:
            ids = [i for i in json.loads(row["item_ids"]) if isinstance(i, str)]
        except (TypeError, ValueError):
            ids = []
        parsed.append((row, ids))
        wanted.update(ids)

    items = _owned_items(db, uid, wanted)
    result = []
    for row, ids in parsed:
        present = [
            LookItem(
                item_id=r["item_id"], image_path=r["image_path"], category=r["category"],
                subcategory=r["subcategory"], primary_color=r["primary_color"],
                slot=outfit_slot(r["category"], r["subcategory"]),
            )
            for r in (items.get(i) for i in ids) if r is not None
        ]
        if present:     # a look whose pieces were all deleted has nothing left to show
            result.append(LookOut(look_id=row["look_id"], name=row["name"],
                                  created_at=str(row["created_at"]), items=present))
    return result


@router.delete("/looks/{look_id}")
def delete_look(
    look_id: str,
    uid: str = Depends(current_user_id),
    db: Any = Depends(get_db),
):
    result = db.execute(
        text("DELETE FROM saved_looks WHERE look_id = :look_id AND user_id = :uid"),
        {"look_id": look_id, "uid": uid},
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Look not found")
    return {"status": "deleted", "look_id": look_id}
