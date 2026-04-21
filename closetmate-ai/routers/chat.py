# routers/chat.py
# ─────────────────────────────────────────────────────────────────
# POST /chat/message
# Primary:  OpenAI GPT-4o-mini (12 s timeout)
# Fallback: Gemini 2.0 Flash REST (no extra SDK)
# ─────────────────────────────────────────────────────────────────

import os
import json
import asyncio
import logging
import pathlib

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from openai import AsyncOpenAI
from sqlalchemy import text

from database import engine

log = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = """You are ClosetMate, a warm, knowledgeable, and CULTURALLY ACCURATE personal AI stylist.
You have access to the user's actual wardrobe items listed below.

═══════════════════════════════════════════
ABSOLUTE OUTFIT COMBINATION RULES — NEVER BREAK THESE
═══════════════════════════════════════════

SOUTH ASIAN RULES:
- Saree is a COMPLETE garment. NEVER pair saree with pants, jeans, trousers, skirt, or any separate bottom. EVER.
- Lehenga is a COMPLETE set (choli + skirt). NEVER add separate pants or tops.
- Anarkali, sharara, gharara are COMPLETE. No separate bottoms.
- Panjabi / kurta MUST be paired with: pajama, churidar, or salwar. NEVER with jeans or trousers.
- Salwar kameez is a SET. Never mix the top with western bottoms.
- Saree blouse is ONLY worn under a saree. Never standalone.

WESTERN RULES:
- Dresses, jumpsuits, gowns are COMPLETE. Never add pants or skirts underneath.
- T-shirts, shirts, blouses pair with: jeans, trousers, chinos, shorts, or skirts. NEVER with salwar or pajama.

MIDDLE EASTERN RULES:
- Thobe, abaya, kaftan, dishdasha are COMPLETE garments. No separate bottoms.

EAST ASIAN RULES:
- Kimono, qipao, hanbok are COMPLETE garments. No separate bottoms.

CROSS-CULTURAL MIXING:
- NEVER mix South Asian tops (kurta/panjabi) with Western bottoms (jeans/trousers).
- NEVER mix Western tops (t-shirt/shirt) with South Asian bottoms (salwar/pajama).
- Exception: indo-western fusion is allowed ONLY if the user explicitly asks for it.

═══════════════════════════════════════════
ACCURACY RULES
═══════════════════════════════════════════

1. ONLY suggest items that actually exist in the user's wardrobe below.
   DO NOT invent items. DO NOT suggest "maybe add a belt" unless belt is in their wardrobe.
2. If the wardrobe has no suitable outfit for the occasion, say so honestly.
   Say: "I don't see a perfect match in your wardrobe for this — here's the closest option: ..."
3. Always consider: occasion + weather + culture together. Never just one.
4. Be specific: say "your white cotton shirt" not just "a shirt".
5. If suggesting a full outfit, ALWAYS verify the combo follows the rules above before responding.

═══════════════════════════════════════════
OUTFIT BLOCK RULE — THIS IS MANDATORY
═══════════════════════════════════════════

EVERY TIME you mention or recommend one or more specific clothing items from the wardrobe,
you MUST append the following JSON block at the very end of your reply — NO EXCEPTIONS:

<outfit>{"items": [{"item_id": "<EXACT item_id from wardrobe>", "subcategory": "shirt", "color": "white"}, {"item_id": "<EXACT item_id from wardrobe>", "subcategory": "jeans", "color": "light blue"}]}</outfit>

RULES for the outfit block:
- Use the EXACT item_id value shown in [item_id: ...] in the wardrobe list below.
- Include ALL items you mentioned in the text — every shirt, every pair of jeans, every accessory.
- If the user says "not the black one" and you suggest an alternative — put the alternative in the block.
- If you mentioned even ONE item by name, the block is required.
- The ONLY time to omit the block is if your reply contains zero clothing references (e.g. a greeting).

Response style: warm, confident, 2-4 sentences. Never say "I think" or "maybe".

User's wardrobe:
{wardrobe}
"""



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
    item_id: Optional[str] = None
    image_url: Optional[str] = None


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
        try:
            if hasattr(r, 'keys'):
                item_id = r["item_id"]         or ""
                color   = r["primary_color"]   or "unknown color"
                sub     = r["subcategory"]     or r["category"] or "item"
                mat     = r["material"]        or ""
                pattern = r["pattern"]         or ""
                formal  = r["formality_level"] or ""
                culture = r["cultural_style"]  or ""
            else:
                item_id = r[0] or ""
                color   = r[3] or "unknown color"
                sub     = r[2] or r[1] or "item"
                mat     = r[4] or ""
                pattern = r[5] or ""
                formal  = r[6] or ""
                culture = r[7] or ""
            extras = [x for x in [mat, pattern, formal, culture]
                      if x and x.lower() not in ("", "unknown", "none")]
            # IMPORTANT: item_id must be in the line so the AI can reference it
            line = f"- [item_id: {item_id}] {color} {sub}"
            if extras:
                line += f" ({', '.join(extras)})"
            lines.append(line)
        except Exception as e:
            lines.append(f"- (item unreadable: {e})")
    return "\n".join(lines)


def _build_image_index(rows) -> dict:
    """Return a dict mapping item_id → image_path for quick lookup."""
    return {
        r["item_id"]: r["image_path"]
        for r in rows
        if r["item_id"] and r["image_path"]
    }


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
        items = []
        for i in data.get("items", []):
            # Accept both old (no item_id) and new (with item_id) AI output
            items.append(SuggestedItem(
                subcategory=i.get("subcategory", "item"),
                color=i.get("color", "unknown"),
                item_id=i.get("item_id"),
            ))
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
async def chat_message(request: ChatRequest):
    with engine.connect() as db:
        return await _handle_chat(request, db)


async def _handle_chat(request: ChatRequest, db) -> ChatResponse:
    # Single query — include item_id so _wardrobe_context can expose it to the AI
    raw_rows = db.execute(
        text("""SELECT item_id, category, subcategory, primary_color, material,
                  pattern, formality_level, cultural_style, image_path
           FROM wardrobe_items WHERE user_id = :uid"""),
        {"uid": str(request.user_id)},
    ).fetchall()
    # Convert to plain dicts so r["column"] works regardless of Row type
    rows = [dict(r._mapping) for r in raw_rows]

    # Build image index: item_id → relative image path
    image_index = {
        r["item_id"]: r["image_path"]
        for r in rows
        if r["item_id"] and r["image_path"]
    }

    system = _SYSTEM_PROMPT.replace("{wardrobe}", _wardrobe_context(rows))

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

    # ── Attach image paths to suggested items ────────────────────────────────
    if suggested_items:
        # Build a fuzzy index: (subcategory, color) → image_path for fallback matching
        fuzzy_index: dict = {}
        for r in rows:
            sub = (r.get("subcategory") or r.get("category") or "").lower().strip()
            col = (r.get("primary_color") or "").lower().strip()
            img = r.get("image_path")
            if sub and img and (sub, col) not in fuzzy_index:
                fuzzy_index[(sub, col)] = img

        enriched = []
        for item in suggested_items:
            image_url: Optional[str] = None

            # 1. Exact item_id match
            if item.item_id and item.item_id in image_index:
                img_path = image_index[item.item_id]
                image_url = img_path.replace("\\", "/").lstrip("/")

            # 2. Fuzzy fallback: match by subcategory + color
            if not image_url:
                sub_key = item.subcategory.lower().strip()
                col_key = item.color.lower().strip()
                img_path = fuzzy_index.get((sub_key, col_key))
                # Try just subcategory if color doesn't match exactly
                if not img_path:
                    img_path = next(
                        (v for (s, c), v in fuzzy_index.items() if s == sub_key),
                        None,
                    )
                if img_path:
                    image_url = img_path.replace("\\", "/").lstrip("/")

            enriched.append(SuggestedItem(
                subcategory=item.subcategory,
                color=item.color,
                item_id=item.item_id,
                image_url=image_url,
            ))
        suggested_items = enriched

    log.info("Reply len=%d outfit_items=%d", len(reply), len(suggested_items or []))
    return ChatResponse(reply=reply, suggested_items=suggested_items)
