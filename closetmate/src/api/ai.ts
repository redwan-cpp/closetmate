import { Platform } from "react-native";
import * as FileSystem from "expo-file-system";

// ---------------------------------------------------------------------------
// Network configuration
// ---------------------------------------------------------------------------

/**
 * Set this to your PC's local IPv4 address (e.g. "192.168.1.42") when
 * testing on a PHYSICAL Android or iOS device connected to the same Wi-Fi
 * network as your development PC.
 *
 * Leave as null to use the automatic emulator/simulator addresses below.
 *
 * Find your IP:
 *   Windows → open PowerShell → run `ipconfig` → look for "IPv4 Address"
 *   macOS   → System Settings → Wi-Fi → Details → IP Address
 */
const PHYSICAL_DEVICE_IP: string | null = null;

/**
 * Resolved base URL for all AI API requests.
 *
 * Priority order:
 *  1. PHYSICAL_DEVICE_IP  → http://<ip>:8000           (physical Android OR iOS)
 *  2. Android             → http://10.0.2.2:8000        (Android emulator → host loopback)
 *  3. iOS/other           → http://127.0.0.1:8000       (iOS simulator)
 */
export const AI_BASE_URL: string = (() => {
  if (PHYSICAL_DEVICE_IP) {
    return `http://${PHYSICAL_DEVICE_IP}:8000`;
  }
  if (Platform.OS === "android") {
    return "http://10.0.2.2:8000";
  }
  return "http://127.0.0.1:8000";
})();

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

// ---------------------------------------------------------------------------
// removeBackground — calls POST /remove-bg, returns a data: URI
// ---------------------------------------------------------------------------

/**
 * Upload an image to the FastAPI /remove-bg endpoint and return a
 * displayable `data:image/png;base64,...` URI with the background removed.
 *
 * @param uri  Local file URI from ImagePicker (file:// or similar)
 * @returns    Data URI string ready for use in <Image source={{ uri }} />
 */
export async function removeBackground(uri: string): Promise<string> {
  const url = `${AI_BASE_URL}/remove-bg`;
  console.log("[removeBackground] Uploading to:", url);

  // Build multipart form — field name MUST match FastAPI parameter: "file"
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
      // Do NOT set Content-Type manually — the runtime must set it to
      // multipart/form-data with the correct boundary.
      body: formData,
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

  // Parse JSON
  let json: unknown;
  try {
    json = await response.json();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("[removeBackground] Failed to parse JSON:", msg);
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

  const dir =
    FileSystem.documentDirectory ?? FileSystem.cacheDirectory ?? null;

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
