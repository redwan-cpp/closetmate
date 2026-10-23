/**
 * src/api/auth.ts
 * Auth API layer — register, login, refresh/logout, profile, skin-tone scan.
 *
 * register / login / skin-tone are called while signed out, so they use plain
 * fetch. Everything that needs a signed-in user goes through authFetch.
 */
import { AI_BASE_URL } from './config';
import { prepareForUpload } from './images';
import { authFetch, toApiError } from './session';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
  gender: string;
  body_shape?: string;
  skin_tone?: string;
  style_preference?: string;
}

export interface RegisterResult {
  user_id: string;
}

export interface ProfileUpdatePayload {
  body_shape?: string;
  /** "light-medium" or "light-medium (warm)" — the backend normalises either form. */
  skin_tone?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResult {
  /** Short-lived access token (JWT). */
  token: string;
  refresh_token: string;
  token_type: string;
  /** Access-token lifetime in seconds. */
  expires_in: number;
  user_id: string;
}

export interface UserProfile {
  user_id: string;
  name: string;
  email: string;
  gender: string;
  body_shape: string | null;
  skin_tone: string | null;
  style_preference: string | null;
  created_at: string;
}

export interface SkinToneResult {
  skin_tone: string;            // e.g. "light-medium", "medium", "deep"
  undertone: string;            // "warm" | "cool" | "neutral"
  display_label: string;        // e.g. "light-medium (warm)"
  confidence: number;           // 0–1
  hex_swatch: string;           // e.g. "#C8A882"
  recommended_colors: string[];
  face_detected: boolean;
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

/** POST JSON without credentials (sign-up / sign-in). */
async function postPublic<T>(path: string, body: object): Promise<T> {
  const url = `${AI_BASE_URL}${path}`;

  // 20 s: Cloud Run can take up to ~15 s to cold-start.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);

  let res: Response;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      throw new Error(
        'The server is warming up — this can take up to 20 seconds.\nPlease tap the button again to retry.'
      );
    }
    throw new Error('Could not reach the server. Check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) throw await toApiError(res, 'Request failed');
  return res.json() as Promise<T>;
}

// ─────────────────────────────────────────────
// Auth endpoints
// ─────────────────────────────────────────────

export function registerUser(payload: RegisterPayload): Promise<RegisterResult> {
  return postPublic<RegisterResult>('/auth/register', payload);
}

export function loginUser(payload: LoginPayload): Promise<LoginResult> {
  return postPublic<LoginResult>('/auth/login', payload);
}

/** Best-effort server-side revoke of a refresh token. Never throws. */
export async function logoutServer(refreshToken: string): Promise<void> {
  try {
    await fetch(`${AI_BASE_URL}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    // offline: the token will simply expire
  }
}

export async function getProfile(): Promise<UserProfile> {
  const res = await authFetch(`${AI_BASE_URL}/auth/profile`, { timeoutMs: 20_000 });
  if (!res.ok) throw await toApiError(res, 'Could not load your profile');
  return res.json() as Promise<UserProfile>;
}

export async function updateProfile(payload: ProfileUpdatePayload): Promise<UserProfile> {
  const res = await authFetch(`${AI_BASE_URL}/auth/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    timeoutMs: 20_000,
  });
  if (!res.ok) throw await toApiError(res, 'Could not update your profile');
  return res.json() as Promise<UserProfile>;
}

// ─────────────────────────────────────────────
// Skin-tone detection — POST /analyze-skin-tone (public: used before an account exists)
// ─────────────────────────────────────────────

export async function detectSkinTone(imageUri: string): Promise<SkinToneResult> {
  // The detector works on a ≤1024 px copy anyway; don't upload a full-resolution selfie.
  const uploadUri = await prepareForUpload(imageUri, 1280);
  const formData = new FormData();
  formData.append('file', {
    uri: uploadUri,
    name: 'selfie.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const res = await fetch(`${AI_BASE_URL}/analyze-skin-tone`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    if (!res.ok) throw await toApiError(res, 'Skin tone scan failed');
    return (await res.json()) as SkinToneResult;
  } finally {
    clearTimeout(timer);
  }
}
