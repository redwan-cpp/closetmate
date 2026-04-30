# routers/chat.py
# ─────────────────────────────────────────────────────────────────
# POST /chat/message
# POST /chat/weather   ← NEW: fetch weather context for location
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

from database import get_db
from fastapi import Depends
from services.weather_service import (
    get_weather_by_city,
    get_weather_by_coords,
    weather_to_context_string,
    WeatherData,
)

log = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = """You are ClosetMate, a warm, knowledgeable, and CULTURALLY ACCURATE personal AI stylist.
You have access to the user's actual wardrobe items listed below.

═══════════════════════════════════════════
USER PROFILE — ALWAYS USE THIS WHEN RECOMMENDING
═══════════════════════════════════════════

{user_profile}

PROFILE RULES:
- Skin tone affects which COLORS flatter the user most. Always prioritize their recommended palette.
- Body shape affects SILHOUETTE and FIT recommendations:
  * hourglass    → emphasize waist, fitted clothes, wrap styles
  * pear         → A-line skirts, wide-leg pants, statement tops, dark bottoms
  * apple        → empire waist, flowy tops, V-necks, avoid clingy fabrics around midsection
  * rectangle    → create curves with ruffles, peplum, belted waists, layering
  * inverted_triangle → balance shoulders with wide-leg pants, A-line, avoid shoulder pads
- Always mention briefly why a recommendation suits THEIR specific tone and shape.
- If skin_tone or body_shape is unknown, ask the user to complete their profile scan.

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
WEATHER & ENVIRONMENT AWARENESS
═══════════════════════════════════════════

{weather_context}

WEATHER RULES:
- If the user is going OUTDOORS: account for temperature, rain, wind, and UV when recommending fabrics and layers.
- If the user is INDOORS: focus on comfort and style; ignore outdoor weather harshness.
- Never suggest heavy wool/denim in extreme heat (>32°C).
- If it's raining: avoid white/light-colored loose garments outdoors.
- If it's very cold: recommend layering strategies.
- Always mention the weather influence briefly in your reply so the user understands your reasoning.

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

_NO_WEATHER_CONTEXT = """No location/weather data provided yet.
If the user mentions going somewhere or asks about weather-based suggestions,
kindly ask: "Are you heading indoors or outdoors? Share your city or location and I'll tailor my suggestions to today's weather!"
"""

# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────

class HistoryEntry(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class WeatherContext(BaseModel):
    """Optional weather context the client can attach to each chat message."""
    city: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    environment: str = "outdoor"   # "indoor" | "outdoor" | "both"


class ChatRequest(BaseModel):
    user_id: str
    message: str
    history: Optional[List[HistoryEntry]] = []
    weather: Optional[WeatherContext] = None


class SuggestedItem(BaseModel):
    subcategory: str
    color: str
    item_id: Optional[str] = None
    image_url: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    suggested_items: Optional[List[SuggestedItem]] = None
    weather_summary: Optional[dict] = None    # ← echo back weather so frontend can display it


# ─────────────────────────────────────────────
# Weather endpoint models
# ─────────────────────────────────────────────

class WeatherRequest(BaseModel):
    city: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    environment: str = "outdoor"


class WeatherResponse(BaseModel):
    city: str
    country: str
    temperature: float
    feels_like: float
    humidity: int
    wind_speed: float
    condition: str
    condition_icon: str
    uv_index: float
    is_day: bool
    environment: str
    context_string: str         # human-readable summary for display
    style_advisory: str


# ─────────────────────────────────────────────
# Fallback profile context
# ─────────────────────────────────────────────

_NO_PROFILE_CONTEXT = (
    "Skin Tone: unknown (user has not completed face scan)\n"
    "Body Shape: unknown (user has not completed profile)\n"
    "→ Suggest versatile, universally flattering styles and recommend completing the profile scan."
)

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
            line = f"- [item_id: {item_id}] {color} {sub}"
            if extras:
                line += f" ({', '.join(extras)})"
            lines.append(line)
        except Exception as e:
            lines.append(f"- (item unreadable: {e})")
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
        items = []
        for i in data.get("items", []):
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
# Weather fetch helper
# ─────────────────────────────────────────────

async def _resolve_weather(ctx: Optional[WeatherContext]) -> Optional[WeatherData]:
    """Fetch WeatherData from the provided context asynchronously."""
    if ctx is None:
        return None
    try:
        if ctx.lat is not None and ctx.lon is not None:
            return await asyncio.to_thread(
                get_weather_by_coords, ctx.lat, ctx.lon, ctx.city or ""
            )
        elif ctx.city:
            return await asyncio.to_thread(get_weather_by_city, ctx.city)
    except Exception as exc:
        log.warning("Weather fetch error: %s", exc)
    return None


# ─────────────────────────────────────────────
# OpenAI call
# ─────────────────────────────────────────────

_TIMEOUT = 12.0


async def _call_openai(messages: list, api_key: str) -> str:
    client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT)
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=350,
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
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 350},
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
# Weather endpoint
# ─────────────────────────────────────────────

@router.post("/weather", response_model=WeatherResponse)
async def get_weather(request: WeatherRequest):
    """
    Fetch real-time weather for a location and return it formatted for ClosetMate.
    The frontend calls this when the user shares their location, then passes
    the result back in subsequent chat messages.
    """
    ctx = WeatherContext(
        city=request.city,
        lat=request.lat,
        lon=request.lon,
        environment=request.environment,
    )
    weather = await _resolve_weather(ctx)
    if weather is None:
        raise HTTPException(
            status_code=404,
            detail="Could not fetch weather. Check the city name or coordinates.",
        )

    ctx_str = weather_to_context_string(weather, request.environment)

    # Extract the advisory line
    advisory_line = ""
    for line in ctx_str.splitlines():
        if "Style Advisories:" in line:
            advisory_line = line.replace("⚠️ Style Advisories: ", "").strip()
            break

    return WeatherResponse(
        city=weather.city,
        country=weather.country,
        temperature=weather.temperature,
        feels_like=weather.feels_like,
        humidity=weather.humidity,
        wind_speed=weather.wind_speed,
        condition=weather.condition,
        condition_icon=weather.condition_icon,
        uv_index=weather.uv_index,
        is_day=weather.is_day,
        environment=request.environment,
        context_string=ctx_str,
        style_advisory=advisory_line,
    )


# ─────────────────────────────────────────────
# Chat endpoint
# ─────────────────────────────────────────────

@router.post("/message", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db=Depends(get_db)):
    return await _handle_chat(request, db)


async def _handle_chat(request: ChatRequest, db) -> ChatResponse:
    # Fetch wardrobe
    raw_rows = db.execute(
        text("""SELECT item_id, category, subcategory, primary_color, material,
                  pattern, formality_level, cultural_style, image_path
           FROM wardrobe_items WHERE user_id = :uid"""),
        {"uid": str(request.user_id)},
    ).fetchall()
    rows = [dict(r._mapping) for r in raw_rows]

    image_index = {
        r["item_id"]: r["image_path"]
        for r in rows
        if r["item_id"] and r["image_path"]
    }

    # ── User profile (skin tone + body shape) ────────────────────────────────
    user_profile_str = _NO_PROFILE_CONTEXT
    try:
        profile_row = db.execute(
            text("SELECT skin_tone, body_shape, gender FROM users WHERE user_id = :uid"),
            {"uid": str(request.user_id)},
        ).fetchone()
        if profile_row:
            profile = dict(profile_row._mapping)
            skin   = profile.get("skin_tone") or "unknown"
            body   = profile.get("body_shape") or "unknown"
            gender = profile.get("gender") or "unknown"

            # Parse out undertone if stored as "light (warm)" format
            undertone = "unknown"
            skin_band = skin
            if "(" in skin and ")" in skin:
                skin_band = skin.split("(")[0].strip()
                undertone = skin.split("(")[1].replace(")", "").strip()

            from services.skin_tone_detector import _TONE_COLORS
            rec_colors = (
                _TONE_COLORS.get(skin_band, {}).get(undertone)
                or _TONE_COLORS.get(skin_band, {}).get("neutral")
                or []
            )
            color_list = ", ".join(rec_colors[:6]) if rec_colors else "versatile palette"

            user_profile_str = (
                f"👤 Gender: {gender}\n"
                f"🎨 Skin Tone: {skin_band} with {undertone} undertone\n"
                f"✨ Best Colors for This Tone: {color_list}\n"
                f"📐 Body Shape: {body}"
            )
    except Exception as exc:
        log.warning("Could not fetch user profile: %s", exc)

    # ── Weather context ───────────────────────────────────────────────────────
    weather_data: Optional[WeatherData] = None
    weather_summary: Optional[dict] = None

    if request.weather:
        weather_data = await _resolve_weather(request.weather)
        if weather_data:
            weather_summary = {
                "city":          weather_data.city,
                "temperature":   weather_data.temperature,
                "condition":     weather_data.condition,
                "condition_icon": weather_data.condition_icon,
                "humidity":      weather_data.humidity,
                "environment":   request.weather.environment,
            }

    if weather_data:
        weather_ctx_str = weather_to_context_string(weather_data, request.weather.environment)
    else:
        weather_ctx_str = _NO_WEATHER_CONTEXT

    system = (
        _SYSTEM_PROMPT
        .replace("{user_profile}", user_profile_str)
        .replace("{wardrobe}", _wardrobe_context(rows))
        .replace("{weather_context}", weather_ctx_str)
    )

    messages: list = [{"role": "system", "content": system}]
    for turn in (request.history or [])[-6:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": request.message})

    raw: Optional[str] = None

    # ── Primary: OpenAI ───────────────────────────────────────────────────────
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

    # ── Fallback: Gemini ──────────────────────────────────────────────────────
    if raw is None:
        raw = await _call_gemini(messages)

    if raw is None:
        raise HTTPException(
            status_code=503,
            detail="AI stylist unavailable. Check OPENAI_API_KEY / GEMINI_API_KEY and restart.",
        )

    reply, suggested_items = _extract_outfit(raw)

    # ── Attach image paths to suggested items ─────────────────────────────────
    if suggested_items:
        # Fuzzy match by (subcategory, color) → image + item_id (same wardrobe row).
        # LLMs often omit or corrupt item_id; without id, "log worn" cannot POST to /wardrobe/log-worn.
        fuzzy_by_subcolor: dict = {}
        for r in rows:
            sub = (r.get("subcategory") or r.get("category") or "").lower().strip()
            col = (r.get("primary_color") or "").lower().strip()
            img = r.get("image_path")
            iid = r.get("item_id")
            if sub and img and (sub, col) not in fuzzy_by_subcolor:
                fuzzy_by_subcolor[(sub, col)] = {"image_path": img, "item_id": iid}

        def _resolve_image_url(img_path: str) -> str:
            """Normalize stored image_path to a value the frontend can use.
            - GCS / any https:// URL   → return as-is (frontend renders directly)
            - file:// device-local path → return as-is (frontend renders directly)
            - uploads/... relative path → return as-is (frontend will prepend AI_BASE_URL)
            """
            p = img_path.replace("\\", "/")
            if p.startswith("http") or p.startswith("file://"):
                return p  # already a usable URL
            # Relative server path — strip any leading slash so frontend can prefix
            return p.lstrip("/")

        enriched = []
        for item in suggested_items:
            image_url: Optional[str] = None
            resolved_item_id: Optional[str] = item.item_id

            if item.item_id and item.item_id in image_index:
                img_path = image_index[item.item_id]
                if img_path:
                    image_url = _resolve_image_url(img_path)

            if not image_url:
                sub_key = item.subcategory.lower().strip()
                col_key = item.color.lower().strip()
                match = fuzzy_by_subcolor.get((sub_key, col_key))
                if not match:
                    match = next(
                        (v for (s, c), v in fuzzy_by_subcolor.items() if s == sub_key),
                        None,
                    )
                if match:
                    img_path = match["image_path"]
                    if img_path:
                        image_url = _resolve_image_url(img_path)
                    if not resolved_item_id:
                        resolved_item_id = match.get("item_id")

            enriched.append(SuggestedItem(
                subcategory=item.subcategory,
                color=item.color,
                item_id=resolved_item_id,
                image_url=image_url,
            ))
        suggested_items = enriched

    log.info("Reply len=%d outfit_items=%d", len(reply), len(suggested_items or []))
    return ChatResponse(
        reply=reply,
        suggested_items=suggested_items,
        weather_summary=weather_summary,
    )
