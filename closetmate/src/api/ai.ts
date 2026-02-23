import { Platform } from "react-native";
import * as FileSystem from "expo-file-system";

const AI_BASE_URL =
  Platform.OS === "android"
    ? "http://10.0.2.2:8000"
    : "http://127.0.0.1:8000";

/** Optional: set to your PC's LAN IP (e.g. "192.168.1.5") if 10.0.2.2 fails on Android emulator */
const ANDROID_HOST_OVERRIDE: string | null = null;
const RESOLVED_AI_BASE_URL =
  Platform.OS === "android" && ANDROID_HOST_OVERRIDE
    ? `http://${ANDROID_HOST_OVERRIDE}:8000`
    : AI_BASE_URL;

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const len = bytes.length;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export async function styleImage(uri: string): Promise<string> {
  const formData = new FormData();
  formData.append("file", {
    uri,
    name: "image.jpg",
    type: "image/jpeg",
  } as unknown as Blob);

  const url = `${RESOLVED_AI_BASE_URL}/style-image`;
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
    throw new Error(
      `Cannot reach backend (${url}). ${msg}. On Android emulator, ensure backend runs on your PC and try setting ANDROID_HOST_OVERRIDE in src/api/ai.ts to your PC's IP (e.g. 192.168.1.x).`
    );
  }

  if (!response.ok) {
    const status = response.status;
    const text = await response.text().catch(() => "");
    throw new Error(
      `Backend error (${status})${text ? `: ${text.slice(0, 120)}` : ""}`
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
    return filePath;
  }

  return `data:image/jpeg;base64,${base64}`;
}
