import * as FileSystem from "expo-file-system/legacy";

// ---------------------------------------------------------------------------
// Network configuration
// ---------------------------------------------------------------------------

export const AI_BASE_URL = "https://closetmate-3ros.onrender.com";

console.log("[ai.ts] AI_BASE_URL =", AI_BASE_URL);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const len = bytes.length;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/** Build a multipart FormData with a single "file" field from a local URI. */
function buildImageFormData(uri: string): FormData {
  const formData = new FormData();
  formData.append("file", {
    uri,
    name: "image.jpg",
    type: "image/jpeg",
  } as unknown as Blob);
  return formData;
}

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

export interface WardrobeItem {
  item_id: string;
  user_id: string;
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
// analyzeClothing — POST /upload/analyze-clothing
// ---------------------------------------------------------------------------

/**
 * Upload an image to the FastAPI analyze-clothing endpoint.
 * Returns suggested metadata (category, color, material, pattern, etc.)
 * Uses MD5 cache — same image returns instantly on subsequent calls.
 */
export async function analyzeClothing(uri: string): Promise<AnalyzeClothingResult> {
  const url = `${AI_BASE_URL}/upload/analyze-clothing`;
  console.log("[analyzeClothing] Uploading to:", url);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      body: buildImageFormData(uri),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[analyzeClothing] Network error:", msg);
    throw new Error(
      `Cannot reach backend at ${url}.\n${msg}\n\n` +
      "On a physical device, set PHYSICAL_DEVICE_IP in src/api/ai.ts to your PC's local IP."
    );
  }

  console.log("[analyzeClothing] Response status:", response.status);

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error("[analyzeClothing] Backend error:", text);
    throw new Error(
      `Analyze failed (HTTP ${response.status})` +
      (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch (e) {
    throw new Error("Analyze response is not valid JSON");
  }

  console.log("[analyzeClothing] Result:", JSON.stringify(json).slice(0, 200));
  return json as AnalyzeClothingResult;
}

// ---------------------------------------------------------------------------
// addWardrobeItem — POST /wardrobe/add-item
// ---------------------------------------------------------------------------

/**
 * Save a clothing item to the user's wardrobe.
 * Returns { status: "success", item_id }.
 */
export async function addWardrobeItem(payload: AddItemPayload): Promise<AddItemResult> {
  const url = `${AI_BASE_URL}/wardrobe/add-item`;
  console.log("[addWardrobeItem] POST", url, payload);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Cannot reach backend at ${url}.\n${msg}`);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Save failed (HTTP ${response.status})` +
      (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }

  const json = await response.json();
  console.log("[addWardrobeItem] Result:", json);
  return json as AddItemResult;
}

// ---------------------------------------------------------------------------
// getWardrobeItems — GET /wardrobe/items/{userId}
// ---------------------------------------------------------------------------

/**
 * Fetch all wardrobe items for a given user.
 */
export async function getWardrobeItems(userId: string): Promise<WardrobeItem[]> {
  const url = `${AI_BASE_URL}/wardrobe/items/${encodeURIComponent(userId)}`;
  console.log("[getWardrobeItems] GET", url);

  let response: Response;
  try {
    response = await fetch(url);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Cannot reach backend at ${url}.\n${msg}`);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Fetch wardrobe failed (HTTP ${response.status})` +
      (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }

  const json = await response.json();
  console.log("[getWardrobeItems] count:", (json as unknown[]).length);
  return json as WardrobeItem[];
}

// ---------------------------------------------------------------------------
// deleteWardrobeItem — DELETE /wardrobe/item/{itemId}
// ---------------------------------------------------------------------------

/**
 * Permanently delete a clothing item by ID.
 */
export async function deleteWardrobeItem(itemId: string): Promise<void> {
  const url = `${AI_BASE_URL}/wardrobe/item/${encodeURIComponent(itemId)}`;
  console.log("[deleteWardrobeItem] DELETE", url);

  let response: Response;
  try {
    response = await fetch(url, { method: "DELETE" });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Cannot reach backend at ${url}.\n${msg}`);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Delete failed (HTTP ${response.status})` +
      (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }
  console.log("[deleteWardrobeItem] Deleted:", itemId);
}


// ---------------------------------------------------------------------------
// removeBackground — calls POST /remove-bg, returns a data: URI (display only)
// ---------------------------------------------------------------------------

/**
 * Upload an image to the FastAPI /remove-bg endpoint and return a
 * displayable `data:image/png;base64,...` URI with the background removed.
 * Used for on-screen preview only — NOT for saving to the wardrobe.
 *
 * @param uri  Local file URI from ImagePicker (file:// or similar)
 * @returns    Data URI string ready for use in <Image source={{ uri }} />
 */
export async function removeBackground(uri: string): Promise<string> {
  const url = `${AI_BASE_URL}/remove-bg`;
  console.log("[removeBackground] Uploading to:", url);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      body: buildImageFormData(uri),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[removeBackground] Network request failed:", msg);
    throw new Error(
      `Cannot reach backend at ${url}.\n${msg}\n\n` +
      "On a physical device, set PHYSICAL_DEVICE_IP in src/api/ai.ts to your PC's local IP."
    );
  }

  console.log("[removeBackground] Response status:", response.status);

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error("[removeBackground] Backend error body:", text);
    throw new Error(
      `Backend returned HTTP ${response.status}` +
      (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Backend response is not valid JSON: ${msg}`);
  }

  console.log("[removeBackground] JSON keys:", Object.keys(json as object));

  const imageB64 = (json as Record<string, unknown>)["image"];

  if (typeof imageB64 !== "string" || imageB64.length === 0) {
    console.error("[removeBackground] Empty or missing base64 in response:", json);
    throw new Error(
      'Backend JSON does not contain a valid "image" base64 string.'
    );
  }

  console.log(
    "[removeBackground] Received base64 length:",
    imageB64.length,
    "chars"
  );

  return `data:image/png;base64,${imageB64}`;
}

// ---------------------------------------------------------------------------
// uploadClothing — POST /upload/upload-clothing
// Saves image server-side and returns the server path for DB storage
// ---------------------------------------------------------------------------

export interface UploadClothingResult {
  /** Relative server path, e.g. "uploads/processed/abc123.png" */
  image_path: string;
  status: string;
}

/**
 * Upload an image to /upload/upload-clothing.
 * The backend runs background removal and saves the result to disk.
 * Returns the server-relative path that should be stored in the DB,
 * so the chat endpoint can later serve the image via the /uploads static mount.
 */
export async function uploadClothing(uri: string): Promise<UploadClothingResult> {
  const url = `${AI_BASE_URL}/upload/upload-clothing`;
  console.log("[uploadClothing] Uploading to:", url);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      body: buildImageFormData(uri),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[uploadClothing] Network error:", msg);
    throw new Error(
      `Cannot reach backend at ${url}.\n${msg}\n\n` +
      "On a physical device, set PHYSICAL_DEVICE_IP in src/api/ai.ts to your PC's local IP."
    );
  }

  console.log("[uploadClothing] Response status:", response.status);

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error("[uploadClothing] Backend error body:", text);
    throw new Error(
      `Upload failed (HTTP ${response.status})` +
      (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }

  const json = await response.json();
  console.log("[uploadClothing] Result:", json);
  return json as UploadClothingResult;
}

// ---------------------------------------------------------------------------
// styleImage — existing full editorial-style pipeline (keep for other uses)
// ---------------------------------------------------------------------------

/**
 * Upload an image to /style-image. Returns a local file URI or data URI of
 * the editorially-styled result (background replaced with gradient, lighting
 * corrected).
 */
export async function styleImage(uri: string): Promise<string> {
  const url = `${AI_BASE_URL}/style-image`;
  console.log("[styleImage] Uploading to:", url);

  const formData = new FormData();
  formData.append("file", {
    uri,
    name: "image.jpg",
    type: "image/jpeg",
  } as unknown as Blob);

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      body: formData,
      headers: {
        Accept: "image/jpeg",
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[styleImage] Network request failed:", msg);
    throw new Error(
      `Cannot reach backend at ${url}.\n${msg}\n\n` +
      "On a physical device, set PHYSICAL_DEVICE_IP in src/api/ai.ts to your PC's local IP."
    );
  }

  console.log("[styleImage] Response status:", response.status);

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    console.error("[styleImage] Backend error body:", text);
    throw new Error(
      `Backend returned HTTP ${response.status}` +
      (text ? `:\n${text.slice(0, 120)}` : "")
    );
  }

  const arrayBuffer = await response.arrayBuffer();
  const base64 = arrayBufferToBase64(arrayBuffer);

  const dir = FileSystem.documentDirectory ?? FileSystem.cacheDirectory ?? null;

  if (dir) {
    const fileName = `styled-${Date.now()}.jpg`;
    const filePath = `${dir}${fileName}`;
    await FileSystem.writeAsStringAsync(filePath, base64, {
      encoding: FileSystem.EncodingType.Base64,
    });
    console.log("[styleImage] Saved to:", filePath);
    return filePath;
  }

  return `data:image/jpeg;base64,${base64}`;
}

// ---------------------------------------------------------------------------
// Chat types
// ---------------------------------------------------------------------------

export interface ChatHistoryEntry {
  role: "user" | "assistant";
  content: string;
}

export interface SuggestedOutfitItem {
  subcategory: string;
  color: string;
  item_id?: string | null;
  image_url?: string | null;
}

export interface ChatResponse {
  reply: string;
  suggested_items: SuggestedOutfitItem[] | null;
}

// ---------------------------------------------------------------------------
// sendChatMessage — POST /chat/message
// ---------------------------------------------------------------------------

/**
 * Send a message to the ClosetMate AI stylist.
 * The backend loads the user's wardrobe, builds context, and calls GPT-4o-mini.
 */
export async function sendChatMessage(
  userId: string,
  message: string,
  history: ChatHistoryEntry[] = []
): Promise<ChatResponse> {
  const url = `${AI_BASE_URL}/chat/message`;
  console.log("[sendChatMessage] POST", url);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000); // 15s — just after backend's 12s hard kill

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, message, history }),
      signal: controller.signal,
    });
  } catch (e) {
    clearTimeout(timeout);
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error("Request timed out after 30s. The AI stylist took too long to respond.");
    }
    const msg = e instanceof Error ? e.message : String(e);
    throw new Error(`Cannot reach backend at ${url}.\n${msg}`);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Chat failed (HTTP ${response.status})` +
        (text ? `:\n${text.slice(0, 200)}` : "")
    );
  }

  const json = await response.json();
  console.log("[sendChatMessage] reply length:", (json as ChatResponse).reply?.length);
  return json as ChatResponse;
}

