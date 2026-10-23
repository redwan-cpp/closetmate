/**
 * src/api/ai.ts — client for the ClosetMate backend (wardrobe, AI tagging, stylist chat).
 *
 * Every call goes through authFetch: it attaches the access token and, on a 401,
 * refreshes it once and retries. Failures are thrown as ApiError, so the UI can
 * react to `err.status` / `err.code` ("quota_exceeded", "rate_limited"); the
 * `err.message` is already user-friendly.
 */
import { AI_BASE_URL } from './config';
import { authFetch, AuthFetchInit, toApiError } from './session';

export { AI_BASE_URL };

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/**
 * Resolves any stored image_path to a displayable URI:
 *  - file://... / data:...  → returned as-is
 *  - https://...            → GCS or other URL, returned as-is
 *  - uploads/...            → server-relative path, prefixed with the backend URL
 */
export function resolveImageUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith('file://') || path.startsWith('data:')) return path;
  if (path.startsWith('http')) return path;
  return `${AI_BASE_URL}/${path.replace(/\\/g, '/').replace(/^\//, '')}`;
}

/** Build a multipart FormData with a single "file" field from a local URI. */
function buildImageFormData(uri: string): FormData {
  const formData = new FormData();
  formData.append('file', {
    uri,
    name: 'image.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);
  return formData;
}

/** authFetch + friendly errors. `label` names the action in error messages. */
async function request(url: string, init: AuthFetchInit, label: string): Promise<Response> {
  let res: Response;
  try {
    res = await authFetch(url, init);
  } catch (e) {
    if (__DEV__) console.warn(`[api] ${label}: request failed`, e);
    if (e instanceof Error && e.name === 'AbortError') {
      throw new Error(`${label}: the request timed out. Please try again.`);
    }
    throw new Error('Could not reach the server. Check your connection and try again.');
  }
  if (!res.ok) throw await toApiError(res, label);
  return res;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SuggestedMetadata {
  category: string;
  subcategory: string;
  primary_color: string;
  material: string;
  pattern: string;
  formality: string;
  culture: string;
}

export interface AnalyzeClothingResult {
  image_path: string;
  cached: boolean;
  suggested: SuggestedMetadata;
}

export interface AddItemPayload {
  user_id: string;
  image_path: string;
  category: string;
  subcategory: string;
  primary_color: string;
  material: string;
  pattern: string;
  formality: string;
  culture: string;
}

export interface AddItemResult {
  status: string;
  item_id: string;
}

/** Role of a garment in an outfit; assigned by the backend (services/outfit_layout.py). */
export type Slot = 'outer' | 'dress' | 'top' | 'bottom' | 'shoes' | 'accessory';

export interface WardrobeItem {
  item_id: string;
  user_id: string;
  slot?: Slot;
  category: string | null;
  subcategory: string | null;
  primary_color: string | null;
  material: string | null;
  pattern: string | null;
  formality_level: string | null;
  cultural_style: string | null;
  image_path: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Wardrobe
// ---------------------------------------------------------------------------

/** POST /upload/analyze-clothing — AI-suggested category, colour, material… (counts toward the scan quota). */
export async function analyzeClothing(uri: string): Promise<AnalyzeClothingResult> {
  const res = await request(
    `${AI_BASE_URL}/upload/analyze-clothing`,
    { method: 'POST', body: buildImageFormData(uri), timeoutMs: 60_000 },
    'Analysis failed'
  );
  return (await res.json()) as AnalyzeClothingResult;
}

/** POST /wardrobe/add-item */
export async function addWardrobeItem(payload: AddItemPayload): Promise<AddItemResult> {
  const res = await request(
    `${AI_BASE_URL}/wardrobe/add-item`,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload), timeoutMs: 30_000 },
    'Save failed'
  );
  return (await res.json()) as AddItemResult;
}

/** GET /wardrobe/items/{userId} */
export async function getWardrobeItems(userId: string): Promise<WardrobeItem[]> {
  const res = await request(
    `${AI_BASE_URL}/wardrobe/items/${encodeURIComponent(userId)}?_t=${Date.now()}`,
    { headers: { 'Cache-Control': 'no-cache' }, timeoutMs: 30_000 },
    'Could not load your wardrobe'
  );
  const items = (await res.json()) as WardrobeItem[];
  // Resolve relative image paths so <Image> can load them.
  return items.map((item) => ({ ...item, image_path: resolveImageUrl(item.image_path) }));
}

/** DELETE /wardrobe/item/{itemId} */
export async function deleteWardrobeItem(itemId: string): Promise<void> {
  await request(
    `${AI_BASE_URL}/wardrobe/item/${encodeURIComponent(itemId)}`,
    { method: 'DELETE', timeoutMs: 30_000 },
    'Delete failed'
  );
}

/** PATCH /wardrobe/item/{itemId}/image — point an item at a new photo (its id, looks and history stay). */
export async function replaceItemImage(itemId: string, imagePath: string): Promise<void> {
  await request(
    `${AI_BASE_URL}/wardrobe/item/${encodeURIComponent(itemId)}/image`,
    { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify({ image_path: imagePath }), timeoutMs: 30_000 },
    'Could not update the photo'
  );
}

// ---------------------------------------------------------------------------
// Images
// ---------------------------------------------------------------------------

/**
 * POST /remove-bg — returns a `data:image/jpeg;base64,…` URI with the background
 * removed. Used for the on-screen preview and saved to the device by the caller.
 */
export async function removeBackground(uri: string): Promise<string> {
  const res = await request(
    `${AI_BASE_URL}/remove-bg`,
    { method: 'POST', body: buildImageFormData(uri), timeoutMs: 60_000 },
    'Background removal failed'
  );
  const json = (await res.json()) as { image?: unknown };
  if (typeof json.image !== 'string' || json.image.length === 0) {
    throw new Error('The server returned an empty image. Please try again.');
  }
  return `data:image/jpeg;base64,${json.image}`;
}

export interface StudioShotResult {
  /** `data:image/webp;base64,…` — 640×800, transparent background. */
  image: string;
  /** Same picture at 320×400, for grids. */
  thumb: string;
  /** False when the cutout looks like it failed (the whole photo was kept). */
  cutoutOk: boolean;
}

/**
 * POST /studio-shot — a clean, centred cutout on a transparent 4:5 canvas, plus a thumbnail.
 * This is what makes the closet look like a boutique shelf instead of a camera roll.
 * Counts toward the background-removal quota.
 */
export async function studioShot(uri: string): Promise<StudioShotResult> {
  const res = await request(
    `${AI_BASE_URL}/studio-shot`,
    { method: 'POST', body: buildImageFormData(uri), timeoutMs: 60_000 },
    'Could not prepare this photo'
  );
  const json = (await res.json()) as {
    image?: unknown; thumb?: unknown; mime?: unknown; cutout_ok?: unknown;
  };
  if (typeof json.image !== 'string' || typeof json.thumb !== 'string' || !json.image || !json.thumb) {
    throw new Error('The server returned an empty image. Please try again.');
  }
  const mime = typeof json.mime === 'string' ? json.mime : 'image/webp';
  return {
    image: `data:${mime};base64,${json.image}`,
    thumb: `data:${mime};base64,${json.thumb}`,
    cutoutOk: json.cutout_ok !== false,
  };
}

export interface UploadClothingResult {
  /** Server path or storage URL, e.g. "uploads/processed/abc123.jpg" or "https://storage.googleapis.com/…" */
  image_path: string;
  status: string;
}

/**
 * POST /upload/upload-clothing — server-side background removal + durable storage
 * (GCS in production). Not used by the add-item screen yet; it is the path to
 * photos that survive a reinstall (see the photo-storage phase).
 */
export async function uploadClothing(uri: string): Promise<UploadClothingResult> {
  const res = await request(
    `${AI_BASE_URL}/upload/upload-clothing`,
    { method: 'POST', body: buildImageFormData(uri), timeoutMs: 60_000 },
    'Upload failed'
  );
  return (await res.json()) as UploadClothingResult;
}

// ---------------------------------------------------------------------------
// Stylist chat
// ---------------------------------------------------------------------------

export interface ChatHistoryEntry {
  role: 'user' | 'assistant';
  content: string;
}

export interface SuggestedOutfitItem {
  subcategory: string;
  color: string;
  item_id?: string | null;
  image_url?: string | null;
  category?: string | null;
  slot?: Slot | null;
}

/** Facts shown as chips on an outfit card. Only things the backend could actually check. */
export interface LookMeta {
  weather?: {
    city?: string;
    temperature?: number;
    condition?: string;
    condition_icon?: string;
    environment?: string;
  } | null;
  palette?: { matched: number; total: number; tone: string | null; undertone: string | null } | null;
}

/** Weather context that can be attached to each chat message. */
export interface WeatherContext {
  city?: string | null;
  lat?: number | null;
  lon?: number | null;
  environment: 'indoor' | 'outdoor' | 'both';
}

/** Weather data returned by POST /chat/weather */
export interface WeatherInfo {
  city: string;
  country: string;
  temperature: number;
  feels_like: number;
  humidity: number;
  wind_speed: number;
  condition: string;
  condition_icon: string;
  uv_index: number;
  is_day: boolean;
  environment: string;
  context_string: string;
  style_advisory: string;
}

export interface ChatResponse {
  reply: string;
  suggested_items: SuggestedOutfitItem[] | null;
  weather_summary?: {
    city: string;
    temperature: number;
    condition: string;
    condition_icon: string;
    humidity: number;
    environment: string;
  } | null;
  look_meta?: LookMeta | null;
}

/** POST /chat/weather — real-time weather for a city or coordinates. */
export async function fetchWeather(
  city?: string | null,
  lat?: number | null,
  lon?: number | null,
  environment: 'indoor' | 'outdoor' | 'both' = 'outdoor'
): Promise<WeatherInfo> {
  const res = await request(
    `${AI_BASE_URL}/chat/weather`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ city, lat, lon, environment }),
      timeoutMs: 20_000,
    },
    'Weather fetch failed'
  );
  return (await res.json()) as WeatherInfo;
}

/**
 * POST /chat/message — ask the AI stylist.
 * The backend allows ~12 s for OpenAI and ~12 s more for the Gemini fallback,
 * so the client waits 30 s (it used to give up at 15 s, before the fallback could answer).
 */
export async function sendChatMessage(
  userId: string,
  message: string,
  history: ChatHistoryEntry[] = [],
  weatherContext?: WeatherContext | null
): Promise<ChatResponse> {
  const res = await request(
    `${AI_BASE_URL}/chat/message`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ user_id: userId, message, history, weather: weatherContext ?? null }),
      timeoutMs: 30_000,
    },
    'The stylist could not answer'
  );
  return (await res.json()) as ChatResponse;
}

// ---------------------------------------------------------------------------
// Worn history & insights
// ---------------------------------------------------------------------------

/** POST /wardrobe/log-worn */
export async function logWornOutfit(userId: string, itemIds: string[]): Promise<void> {
  await request(
    `${AI_BASE_URL}/wardrobe/log-worn`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ user_id: userId, item_ids: itemIds }),
      timeoutMs: 20_000,
    },
    'Could not log this outfit'
  );
}

export interface WornHistoryItem {
  item_id: string;
  slot?: Slot;
  image_path: string | null;
  category: string | null;
  subcategory: string | null;
  primary_color: string | null;
}

export interface WornLog {
  log_id: string;
  worn_date: string;
  items: WornHistoryItem[];
}

/** GET /wardrobe/worn-history/{userId} */
export async function getWornHistory(userId: string, limit = 7): Promise<WornLog[]> {
  const res = await request(
    `${AI_BASE_URL}/wardrobe/worn-history/${encodeURIComponent(userId)}?limit=${limit}&_t=${Date.now()}`,
    { headers: { 'Cache-Control': 'no-cache' }, timeoutMs: 30_000 },
    'Could not load your worn history'
  );
  const logs = (await res.json()) as WornLog[];
  return logs.map((entry) => ({
    ...entry,
    items: entry.items.map((item) => ({ ...item, image_path: resolveImageUrl(item.image_path) })),
  }));
}

export interface StyleInsights {
  best_colors: string[];
  avoid_colors: string[];
  silhouettes: string[];
  wardrobe_gaps: string[];
  general_tip: string;
}

// ---------------------------------------------------------------------------
// Saved looks (the "Looks" tab)
// ---------------------------------------------------------------------------

export interface LookItemData {
  item_id: string;
  image_path: string | null;
  category: string | null;
  subcategory: string | null;
  primary_color: string | null;
  slot: Slot;
}

export interface Look {
  look_id: string;
  name: string | null;
  created_at: string;
  items: LookItemData[];
}

/** POST /wardrobe/looks — keep an outfit. Saving the same set of items twice is a no-op. */
export async function saveLook(userId: string, itemIds: string[], name?: string): Promise<{ look_id: string; status: string }> {
  const res = await request(
    `${AI_BASE_URL}/wardrobe/looks`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ user_id: userId, item_ids: itemIds, name: name ?? null }),
      timeoutMs: 20_000,
    },
    'Could not save this look'
  );
  return (await res.json()) as { look_id: string; status: string };
}

/** GET /wardrobe/looks/{userId} */
export async function getLooks(userId: string): Promise<Look[]> {
  const res = await request(
    `${AI_BASE_URL}/wardrobe/looks/${encodeURIComponent(userId)}?_t=${Date.now()}`,
    { headers: { 'Cache-Control': 'no-cache' }, timeoutMs: 30_000 },
    'Could not load your looks'
  );
  const looks = (await res.json()) as Look[];
  return looks.map((look) => ({
    ...look,
    items: look.items.map((item) => ({ ...item, image_path: resolveImageUrl(item.image_path) })),
  }));
}

/** DELETE /wardrobe/looks/{lookId} */
export async function deleteLook(lookId: string): Promise<void> {
  await request(
    `${AI_BASE_URL}/wardrobe/looks/${encodeURIComponent(lookId)}`,
    { method: 'DELETE', timeoutMs: 20_000 },
    'Could not delete this look'
  );
}

/** GET /chat/insights/{userId} (counts toward the insights quota) */
export async function getStyleInsights(userId: string): Promise<StyleInsights> {
  const res = await request(
    `${AI_BASE_URL}/chat/insights/${encodeURIComponent(userId)}?_t=${Date.now()}`,
    { headers: { 'Cache-Control': 'no-cache' }, timeoutMs: 40_000 },
    'Could not generate insights'
  );
  return (await res.json()) as StyleInsights;
}
