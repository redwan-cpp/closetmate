# routers/chat.py
# ─────────────────────────────────────────────────────────────────
# POST /chat/message
# Primary:  OpenAI GPT-4o-mini (12 s timeout)
# Fallback: Gemini 2.0 Flash REST (no extra SDK)
# ─────────────────────────────────────────────────────────────────

import os
import json
import asyncio
import sqlite3
import logging
import pathlib

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
3. Keep responses SHORT (2-3 sentences max). No bullet lists, no long paragraphs.
4. Consider cultural context (South Asian, Western, Middle Eastern, East Asian) based on the occasion.
5. If weather or occasion is mentioned, factor that in to your advice.

IMPORTANT — outfit block rule:
- If the user asks for an outfit, recommendation, suggestion, or what to wear → you MUST end your reply with:
<outfit>{"items": [{"subcategory": "shirt", "color": "white"}, {"subcategory": "jeans", "color": "navy"}]}</outfit>
- Use the EXACT subcategory and color values from the wardrobe list below.
- If NOT suggesting a specific outfit, reply naturally without the block.
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
        start = raw.index("<outfit>") + len("<outfit>")
        end   = raw.index("</outfit>")
        data  = json.loads(raw[start:end].strip())
        items = [SuggestedItem(**i) for i in data.get("items", [])]
        clean = (raw[:raw.index("<outfit>")] +
                 raw[raw.index("</outfit>") + len("</outfit>"):]).strip()
        return clean, items or None
    except Exception as e:
        log.warning("outfit parse failed: %s", e)
        return raw[:raw.index("<outfit>")].strip(), None


# ─────────────────────────────────────────────
# Env key loader
# ─────────────────────────────────────────────

def _load_key(name: str) -> Optional[str]:
    val = os.getenv(name)
    if val:
        return val
    env_path = pathlib.Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ─────────────────────────────────────────────
# OpenAI call
# ─────────────────────────────────────────────

_TIMEOUT = 12.0   # reduced from 25 s → faster failure & Gemini kicks in sooner


async def _call_openai(messages: list, api_key: str) -> str:
    client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT)
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=250,
        temperature=0.5,
    )
    return resp.choices[0].message.content.strip()


# ─────────────────────────────────────────────
# Gemini fallback (REST — no extra SDK)
# ─────────────────────────────────────────────

async def _call_gemini(messages: list) -> Optional[str]:
    """Call Gemini 2.0 Flash as a fallback when OpenAI fails/times out."""
    import requests as _req

    api_key = _load_key("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY not set — no fallback available")
        return None

    # Convert OpenAI message format → Gemini contents list
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            contents.append({"role": "user",  "parts": [{"text": msg["content"]}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I'll follow these instructions."}]})
        elif msg["role"] == "user":
            contents.append({"role": "user",  "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 250},
    }
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    try:
        resp = await asyncio.to_thread(
            _req.post, url, params={"key": api_key}, json=payload, timeout=12
        )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            log.info("Gemini fallback OK, len=%d", len(text))
            return text
        log.warning("Gemini fallback HTTP %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("Gemini fallback exception: %s", exc)
    return None


# ─────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────

@router.post("/message", response_model=ChatResponse)
async def chat_message(
    request: ChatRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    # ── Wardrobe context ─────────────────────────────────────────────────────
    rows = db.execute(
        """SELECT category, subcategory, primary_color, material,
                  pattern, formality_level, cultural_style
           FROM wardrobe_items WHERE user_id = ?""",
        (str(request.user_id),),
    ).fetchall()

    system = _SYSTEM_PROMPT + f"\n\nUser's wardrobe:\n{_wardrobe_context(rows)}"

    messages: list = [{"role": "system", "content": system}]
    for turn in (request.history or [])[-6:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": request.message})

    raw: Optional[str] = None

    # ── Primary: OpenAI ──────────────────────────────────────────────────────
    openai_key = _load_key("OPENAI_API_KEY")
    if openai_key:
        try:
            raw = await asyncio.wait_for(_call_openai(messages, openai_key), timeout=_TIMEOUT)
            log.info("OpenAI chat OK len=%d", len(raw))
        except asyncio.TimeoutError:
            log.warning("OpenAI timed out after %.0fs — falling back to Gemini", _TIMEOUT)
        except Exception as exc:
            log.warning("OpenAI failed: %s — falling back to Gemini", exc)
    else:
        log.warning("OPENAI_API_KEY not configured — trying Gemini directly")

    # ── Fallback: Gemini ─────────────────────────────────────────────────────
    if raw is None:
        raw = await _call_gemini(messages)

    if raw is None:
        raise HTTPException(
            status_code=503,
            detail="AI stylist unavailable. Check OPENAI_API_KEY / GEMINI_API_KEY and restart.",
        )

    reply, suggested_items = _extract_outfit(raw)
    log.info("Reply len=%d outfit_items=%d", len(reply), len(suggested_items or []))
    return ChatResponse(reply=reply, suggested_items=suggested_items)
