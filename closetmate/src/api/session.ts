/**
 * src/api/session.ts — token storage and an authenticated fetch.
 *
 * - Tokens live in the platform keystore (expo-secure-store), not plain
 *   AsyncStorage. SecureStore has no web implementation, so web falls back to
 *   AsyncStorage (web is a dev convenience only).
 * - `authFetch` attaches the access token and, on a 401, refreshes it ONCE
 *   (single-flight, so parallel requests share one refresh) and retries.
 * - If the refresh token itself is rejected the session is cleared and the
 *   app is signed out via the handler registered by AuthContext.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { AI_BASE_URL } from './config';

export interface Session {
  accessToken: string;
  refreshToken: string;
  userId: string;
}

const KEY = 'closetmate_session_v2';
// Sessions from before JWTs held a forgeable "dev-<user_id>" token; drop them.
const LEGACY_KEY = 'closetmate_auth';

const useSecureStore = Platform.OS !== 'web';

const storage = {
  get: () => (useSecureStore ? SecureStore.getItemAsync(KEY) : AsyncStorage.getItem(KEY)),
  set: (value: string) =>
    useSecureStore ? SecureStore.setItemAsync(KEY, value) : AsyncStorage.setItem(KEY, value),
  remove: () => (useSecureStore ? SecureStore.deleteItemAsync(KEY) : AsyncStorage.removeItem(KEY)),
};

let current: Session | null = null;
let signedOutHandler: (() => void) | null = null;
let refreshInFlight: Promise<Session | null> | null = null;

export function onSignedOut(handler: (() => void) | null): void {
  signedOutHandler = handler;
}

export function getSession(): Session | null {
  return current;
}

export async function loadSession(): Promise<Session | null> {
  AsyncStorage.removeItem(LEGACY_KEY).catch(() => {});
  try {
    const raw = await storage.get();
    current = raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    current = null;
  }
  return current;
}

export async function saveSession(session: Session): Promise<void> {
  current = session;
  await storage.set(JSON.stringify(session));
}

export async function clearSession(): Promise<void> {
  current = null;
  try {
    await storage.remove();
  } catch {
    // nothing to clear
  }
}

async function signOutLocally(): Promise<void> {
  await clearSession();
  signedOutHandler?.();
}

/** Exchange the refresh token for a new pair. Returns null if it could not be refreshed. */
async function refreshSession(): Promise<Session | null> {
  if (!current) return null;
  if (refreshInFlight) return refreshInFlight;

  const refreshToken = current.refreshToken;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${AI_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        // 401: revoked / expired / reused -> the user must sign in again.
        // Anything else (5xx, rate limit) is transient: keep the session.
        if (res.status === 401) await signOutLocally();
        return null;
      }
      const data = await res.json();
      const next: Session = {
        accessToken: data.token,
        refreshToken: data.refresh_token,
        userId: data.user_id,
      };
      await saveSession(next);
      return next;
    } catch {
      return null; // offline: keep the session, the original request just fails
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export interface AuthFetchInit extends RequestInit {
  /** Abort the request after this many milliseconds. */
  timeoutMs?: number;
}

/** fetch() with the Bearer token attached and one transparent refresh-and-retry on 401. */
export async function authFetch(url: string, init: AuthFetchInit = {}): Promise<Response> {
  const { timeoutMs, ...rest } = init;

  const send = async (accessToken: string | null): Promise<Response> => {
    const controller = new AbortController();
    const timer = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      const headers = new Headers(rest.headers);
      if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
      return await fetch(url, { ...rest, headers, signal: controller.signal });
    } finally {
      if (timer) clearTimeout(timer);
    }
  };

  let res = await send(current?.accessToken ?? null);
  if (res.status === 401 && current) {
    const refreshed = await refreshSession();
    if (refreshed) res = await send(refreshed.accessToken);
  }
  return res;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  /** Machine-readable code from the backend, e.g. "quota_exceeded" or "rate_limited". */
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/** Build an ApiError from a non-OK response, using the backend's `detail` when present. */
export async function toApiError(res: Response, fallback: string): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = JSON.parse(await res.text())?.detail ?? null;
  } catch {
    // body was not JSON
  }

  let message = `${fallback} (HTTP ${res.status})`;
  let code: string | undefined;
  if (typeof detail === 'string') {
    message = detail;
  } else if (Array.isArray(detail)) {
    // FastAPI validation errors: [{ msg, loc, ... }]
    const msgs = detail.map((d) => (d && typeof d.msg === 'string' ? d.msg : '')).filter(Boolean);
    if (msgs.length) message = msgs.join('; ');
  } else if (detail && typeof detail === 'object') {
    const d = detail as { message?: unknown; code?: unknown };
    if (typeof d.message === 'string') message = d.message;
    if (typeof d.code === 'string') code = d.code;
  }
  return new ApiError(message, res.status, code);
}
