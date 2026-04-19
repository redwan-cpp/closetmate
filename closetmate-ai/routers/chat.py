# routers/chat.py
# ─────────────────────────────────────────────────────────────────
# POST /chat/message
# Uses the official openai library (AsyncOpenAI) + asyncio.wait_for
# for a hard 25-second timeout that actually kills the connection.
# ─────────────────────────────────────────────────────────────────

import os
import json
import asyncio
import sqlite3
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from openai import AsyncOpenAI

from database import get_db

log = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = """You are ClosetMate, a warm and knowledgeable personal AI stylist.
You have access to the user's actual wardrobe items listed below.

Rules:
1. When suggesting outfits, ALWAYS reference specific items from their wardrobe by color and type.
2. Be conversational, warm, and confident — like a stylish friend giving advice.
3. Keep responses concise (2-4 sentences) unless asked for detail.
4. Consider cultural context (South Asian, Western, Middle Eastern, East Asian) based on the occasion.
5. If weather or occasion is mentioned, factor that in to your advice.

If you are suggesting a specific outfit combination, append a JSON block at the END:
<outfit>{"items": [{"subcategory": "panjabi", "color": "white"}, {"subcategory": "churidar", "color": "cream"}]}</outfit>

If NOT suggesting a specific outfit, reply naturally without the block.
Always be encouraging and positive about the user's style."""


# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────

class HistoryEntry(BaseModel):
    role: str       # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    user_id: str
    message: str
    history: Optional[List[HistoryEntry]] = []

class SuggestedItem(BaseModel):
    subcategory: str
    color: str

class ChatResponse(BaseModel):
    reply: str
    suggested_items: Optional[List[SuggestedItem]] = None


# ─────────────────────────────────────────────
# Wardrobe → context string
# ─────────────────────────────────────────────

def _wardrobe_context(rows) -> str:
    if not rows:
        return "(No items in wardrobe yet — encourage the user to add some!)"
    lines = []
    for r in rows:
        color   = r["primary_color"]   or "unknown color"
        sub     = r["subcategory"]     or r["category"] or "item"
        mat     = r["material"]        or ""
        pattern = r["pattern"]         or ""
        formal  = r["formality_level"] or ""
        culture = r["cultural_style"]  or ""
        extras  = [x for x in [mat, pattern, formal, culture]
                   if x and x.lower() not in ("", "unknown", "none")]
        line = f"- {color} {sub}"
        if extras:
            line += f" ({', '.join(extras)})"
        lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Parse outfit block
# ─────────────────────────────────────────────

def _extract_outfit(raw: str):
    if "<outfit>" not in raw or "</outfit>" not in raw:
        return raw.strip(), None
    try:
        start    = raw.index("<outfit>") + len("<outfit>")
        end      = raw.index("</outfit>")
        data     = json.loads(raw[start:end].strip())
        items    = [SuggestedItem(**i) for i in data.get("items", [])]
        clean    = (raw[:raw.index("<outfit>")] +
                    raw[raw.index("</outfit>") + len("</outfit>"):]).strip()
        return clean, items or None
    except Exception as e:
        log.warning("outfit parse failed: %s", e)
        return raw[:raw.index("<outfit>")].strip(), None


# ─────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────

_TIMEOUT = 25.0  # seconds — hard kill via asyncio.wait_for


async def _call_openai(messages: list, api_key: str) -> str:
    client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT)
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=400,
        temperature=0.8,
    )
    return resp.choices[0].message.content.strip()


@router.post("/message", response_model=ChatResponse)
async def chat_message(
    request: ChatRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    # ── API key ────────────────────────────────────────────────────────────────
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    # ── Wardrobe context ───────────────────────────────────────────────────────
    rows = db.execute(
        """SELECT category, subcategory, primary_color, material,
                  pattern, formality_level, cultural_style
           FROM wardrobe_items WHERE user_id = ?""",
        (str(request.user_id),),
    ).fetchall()

    system = _SYSTEM_PROMPT + f"\n\nUser's wardrobe:\n{_wardrobe_context(rows)}"

    # ── Build messages ─────────────────────────────────────────────────────────
    messages = [{"role": "system", "content": system}]
    for turn in (request.history or [])[-6:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": request.message})

    # ── Call OpenAI with hard timeout ──────────────────────────────────────────
    try:
        raw = await asyncio.wait_for(_call_openai(messages, api_key), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="AI stylist timed out (25 s). Please try again.",
        )
    except Exception as e:
        log.exception("OpenAI call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"OpenAI error: {e}")

    reply, suggested_items = _extract_outfit(raw)
    log.info("Chat reply len=%d items=%d", len(reply), len(suggested_items or []))
    return ChatResponse(reply=reply, suggested_items=suggested_items)
