# routers/chat.py
# ─────────────────────────────────────────────────────────────────
# POST /chat/message         AI stylist             (monthly quota: "chat")
# POST /chat/weather         weather for a location (rate-limited)
# GET  /chat/insights/{id}   personalised insights  (monthly quota: "insights")
#
# Every route needs a valid access token (applied in main.py) and only ever
# reads the *authenticated* user's wardrobe. The wardrobe/profile are loaded in
# a short DB session that is CLOSED before the slow LLM call, so a pooled
# connection is never held while waiting on a provider.
# Suggested items carry their outfit `slot` (top/bottom/dress/…) so the app can compose
# them into a lookboard, and the reply carries `look_meta` (colour match, weather) for chips.
# Primary: OpenAI. Fallback: Gemini. Both go through services/llm_gateway.py,
# which owns model IDs, timeouts and per-call usage metering.
# ─────────────────────────────────────────────────────────────────

import asyncio
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import db_session
from models.profile import split_skin_tone
from quota import metered
from ratelimit import rate_limit_user
from security import current_user_id, require_same_user
from services.llm_gateway import gemini_generate, openai_chat
from settings import get_settings
from services.outfit_layout import look_meta, outfit_slot
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
ACCESSORIES — ALWAYS CHECK THE WARDROBE FOR THESE
═══════════════════════════════════════════

When building any outfit recommendation, ALWAYS check the wardrobe for accessories and include them if present:
- ⌚ WATCH: suggest a watch from the wardrobe if one exists. Pair dress/metal-strap watches with formal outfits; sport/rubber-strap watches with casual.
- 👜 BAG: suggest a bag if the occasion calls for it (work → tote/structured bag, casual → backpack/crossbody, evening → clutch).
- 🕶️ SUNGLASSES: suggest sunglasses for outdoor daytime looks if available.
- 👒 CAP/HAT: suggest caps for casual/sporty looks; structured hats for formal.
- 💍 JEWELRY: suggest necklaces, bracelets, earrings for formal, festive, or date outfits if in wardrobe.
- 👔 TIE/POCKET SQUARE: always include with formal suit outfits if available.
- 👝 BELT: suggest belts with trousers/jeans when a belt is in the wardrobe.
- 🧣 SCARF: suggest scarves in cold weather or as a style accent.

ACCESSORY RULES:
- ALWAYS include accessories in the <outfit> block with their exact item_id.
- A watch does NOT replace clothing. It goes ON TOP of a complete outfit.
- Never suggest jewelry with sportswear unless explicitly asked.
- For formal/festive outfits, always check for and mention jewelry/ties if they exist.
- Match metals: silver/white-gold jewelry → cool tones; gold/rose-gold → warm tones.

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
    message: str = Field(min_length=1, max_length=1000)
    history: Optional[List[HistoryEntry]] = Field(default=[], max_length=20)
    weather: Optional[WeatherContext] = None


class SuggestedItem(BaseModel):
    subcategory: str
    color: str
    item_id: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    slot: Optional[str] = None      # outer | dress | top | bottom | shoes | accessory


class ChatResponse(BaseModel):
    reply: str
    suggested_items: Optional[List[SuggestedItem]] = None
    weather_summary: Optional[dict] = None    # ← echo back weather so frontend can display it
    look_meta: Optional[dict] = None          # facts for the outfit card chips (colour match, weather)

class StyleInsightsResponse(BaseModel):
    best_colors: List[str]
    avoid_colors: List[str]
    silhouettes: List[str]
    wardrobe_gaps: List[str]
    general_tip: str


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

def _known_colour(value: Optional[str]) -> Optional[str]:
    """A usable colour name, or None for blank / "unknown" (the default for items saved without one)."""
    text = (value or "").strip()
    return text if text and text.lower() != "unknown" else None


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
# DB context — short session, closed before any LLM call
# ─────────────────────────────────────────────

_PROVIDER_TIMEOUT = 12.0     # seconds allowed per provider attempt


def _load_wardrobe_and_profile(uid: str, *, with_images: bool):
    """Return (wardrobe_rows, profile_dict_or_None) using one short DB session."""
    columns = ("item_id, category, subcategory, primary_color, material, "
               "pattern, formality_level, cultural_style")
    if with_images:
        columns += ", image_path"
    # Newest N items only: every wardrobe row becomes prompt tokens, so an unbounded
    # closet would make the cost of ONE quota unit unbounded.
    limit = get_settings().chat_wardrobe_limit
    with db_session() as db:   # `columns` is a code constant, never user input
        raw_rows = db.execute(
            text(f"SELECT {columns} FROM wardrobe_items WHERE user_id = :uid "
                 "ORDER BY created_at DESC LIMIT :lim"),
            {"uid": uid, "lim": limit},
        ).fetchall()
        profile_row = db.execute(
            text("SELECT skin_tone, body_shape, gender FROM users WHERE user_id = :uid"),
            {"uid": uid},
        ).fetchone()
    rows = [dict(r._mapping) for r in raw_rows]
    profile = dict(profile_row._mapping) if profile_row else None
    return rows, profile


def _profile_context(profile: Optional[dict], *, emoji: bool) -> str:
    """Profile block for a prompt — the one implementation shared by chat and insights."""
    if not profile:
        return _NO_PROFILE_CONTEXT
    skin_band, undertone = split_skin_tone(profile.get("skin_tone"))
    body = profile.get("body_shape") or "unknown"
    gender = profile.get("gender") or "unknown"

    from services.skin_tone_detector import _TONE_COLORS
    palette = (
        _TONE_COLORS.get(skin_band, {}).get(undertone)
        or _TONE_COLORS.get(skin_band, {}).get("neutral")
        or []
    )
    color_list = ", ".join(palette[:6]) if palette else "versatile palette"

    if emoji:
        return (
            f"👤 Gender: {gender}\n"
            f"🎨 Skin Tone: {skin_band} with {undertone} undertone\n"
            f"✨ Best Colors for This Tone: {color_list}\n"
            f"📐 Body Shape: {body}"
        )
    return (
        f"Gender: {gender}\n"
        f"Skin Tone: {skin_band} (undertone: {undertone})\n"
        f"Algorithmically Recommended Colors: {color_list}\n"
        f"Body Shape: {body}"
    )

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
# Weather endpoint
# ─────────────────────────────────────────────

@router.post("/weather", response_model=WeatherResponse)
async def get_weather(
    request: WeatherRequest,
    _rate: None = Depends(rate_limit_user("weather", 30, 60)),
):
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
async def chat_message(
    request: ChatRequest,
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("chat", 20, 60)),
):
    require_same_user(request.user_id, uid)
    # Consumes a monthly unit; refunds it only if WE fail before a provider answers.
    async with metered(uid, "chat"):
        return await _handle_chat(request, uid)


async def _handle_chat(request: ChatRequest, uid: str) -> ChatResponse:
    rows, profile = await asyncio.to_thread(_load_wardrobe_and_profile, uid, with_images=True)

    image_index = {
        r["item_id"]: r["image_path"]
        for r in rows
        if r["item_id"] and r["image_path"]
    }

    user_profile_str = _profile_context(profile, emoji=True)

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
        # Only user/assistant turns: a client must not be able to inject "system" messages.
        if turn.role in ("user", "assistant"):
            messages.append({"role": turn.role, "content": turn.content[:2000]})
    messages.append({"role": "user", "content": request.message})

    raw: Optional[str] = None

    # ── Primary: OpenAI ───────────────────────────────────────────────────────
    try:
        raw = await openai_chat(
            messages, feature="chat", user_id=uid,
            max_tokens=350, temperature=0.5, timeout=_PROVIDER_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — any provider failure falls through to Gemini
        log.warning("OpenAI chat failed (%s) — falling back to Gemini", type(exc).__name__)

    # ── Fallback: Gemini ──────────────────────────────────────────────────────
    if not raw:
        raw = await gemini_generate(
            messages, feature="chat", user_id=uid,
            max_tokens=350, temperature=0.5, timeout=_PROVIDER_TIMEOUT,
        )

    if not raw:
        raise HTTPException(
            status_code=503,
            detail="The AI stylist is temporarily unavailable. Please try again in a moment.",
        )

    reply, suggested_items = _extract_outfit(raw)

    # Colours the "in your best colors" chip is judged on, one per suggested item.
    palette_colors: list[Optional[str]] = []

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
        rows_by_id = {r["item_id"]: r for r in rows if r.get("item_id")}
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

            row = rows_by_id.get(resolved_item_id) if resolved_item_id else None
            category = row.get("category") if row else None
            # Judge the real garment, not the model's wording: the row's colour wins. Only an
            # item with no wardrobe row falls back to what the model said, and "unknown" is
            # never counted as a colour.
            if row is not None:
                palette_colors.append(_known_colour(row.get("primary_color")))
            else:
                palette_colors.append(_known_colour(item.color))
            enriched.append(SuggestedItem(
                subcategory=item.subcategory,
                color=item.color,
                item_id=resolved_item_id,
                image_url=image_url,
                category=category,
                slot=outfit_slot(category, (row.get("subcategory") if row else None) or item.subcategory),
            ))
        suggested_items = enriched

    log.info("Reply len=%d outfit_items=%d", len(reply), len(suggested_items or []))
    meta = None
    if suggested_items:
        meta = look_meta(
            [{"color": c} for c in palette_colors],
            (profile or {}).get("skin_tone"),
            weather_summary,
        )
    return ChatResponse(
        reply=reply,
        suggested_items=suggested_items,
        weather_summary=weather_summary,
        look_meta=meta,
    )

# ─────────────────────────────────────────────
# Style Insights Endpoint
# ─────────────────────────────────────────────

_INSIGHTS_PROMPT = """You are an expert AI fashion stylist.
Analyze the user's profile and their actual wardrobe items.
Generate a highly personalized style insight profile.

You MUST return ONLY valid JSON matching exactly this structure:
{
  "best_colors": ["color1", "color2", "color3"],
  "avoid_colors": ["color1", "color2"],
  "silhouettes": ["shape1", "shape2", "shape3"],
  "wardrobe_gaps": ["item1", "item2"],
  "general_tip": "One concise, empowering sentence about their style."
}

User Profile:
{user_profile}

Current Wardrobe:
{wardrobe}
"""

@router.get("/insights/{user_id}", response_model=StyleInsightsResponse)
async def get_style_insights(
    user_id: str,
    uid: str = Depends(current_user_id),
    _rate: None = Depends(rate_limit_user("insights", 6, 60)),
):
    require_same_user(user_id, uid)
    async with metered(uid, "insights"):
        return await _generate_insights(uid)


async def _generate_insights(uid: str) -> StyleInsightsResponse:
    rows, profile = await asyncio.to_thread(_load_wardrobe_and_profile, uid, with_images=False)

    prompt = (
        _INSIGHTS_PROMPT
        .replace("{user_profile}", _profile_context(profile, emoji=False))
        .replace("{wardrobe}", _wardrobe_context(rows))
    )
    messages = [{"role": "system", "content": prompt}]

    raw: Optional[str] = None
    try:
        raw = await openai_chat(
            messages, feature="insights", user_id=uid,
            max_tokens=300, temperature=0.4, timeout=15.0, json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenAI insights failed (%s) — falling back to Gemini", type(exc).__name__)

    if not raw:
        raw = await gemini_generate(
            messages, feature="insights", user_id=uid,
            max_tokens=300, temperature=0.4, timeout=15.0, json_mode=True,
        )

    if not raw:
        raise HTTPException(status_code=503, detail="Could not generate insights at this time.")

    try:
        data = json.loads(raw)
        return StyleInsightsResponse(
            best_colors=data.get("best_colors", []),
            avoid_colors=data.get("avoid_colors", []),
            silhouettes=data.get("silhouettes", []),
            wardrobe_gaps=data.get("wardrobe_gaps", []),
            general_tip=data.get("general_tip", "Stay stylish!"),
        )
    except Exception:  # noqa: BLE001
        log.error("insights JSON could not be parsed (%d chars)", len(raw))
        raise HTTPException(status_code=502, detail="Invalid insights data returned.")
