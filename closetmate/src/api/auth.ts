/**
 * src/api/auth.ts
 * Auth API layer — register, login, OAuth placeholders, skin-tone upload.
 */
import { AI_BASE_URL } from './ai';

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

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResult {
  token: string;
  user_id: string;
}

export interface SkinToneResult {
  skin_tone: string;           // "warm" | "cool" | "neutral"
  recommended_colors: string[];
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

async function post<T>(path: string, body: object): Promise<T> {
  const url = `${AI_BASE_URL}${path}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = `HTTP ${res.status}`;
    try { detail = JSON.parse(text).detail ?? detail; } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ─────────────────────────────────────────────
// Auth endpoints
// ─────────────────────────────────────────────

export async function registerUser(payload: RegisterPayload): Promise<RegisterResult> {
  return post<RegisterResult>('/auth/register', payload);
}

export async function loginUser(payload: LoginPayload): Promise<LoginResult> {
  return post<LoginResult>('/auth/login', payload);
}

// ─────────────────────────────────────────────
// Skin-tone detection — POST /analyze-skin-tone
// ─────────────────────────────────────────────

export async function detectSkinTone(imageUri: string): Promise<SkinToneResult> {
  const url = `${AI_BASE_URL}/analyze-skin-tone`;
  const formData = new FormData();
  formData.append('file', {
    uri: imageUri,
    name: 'selfie.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);

  const res = await fetch(url, { method: 'POST', body: formData });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = `HTTP ${res.status}`;
    try { detail = JSON.parse(text).detail ?? detail; } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<SkinToneResult>;
}
