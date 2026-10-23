/**
 * src/api/config.ts — where the backend lives.
 *
 * Kept out of ai.ts so that session.ts (token refresh) and ai.ts (API calls)
 * can both import it without creating an import cycle.
 *
 *  - EXPO_PUBLIC_API_BASE_URL (EAS env / .env) always wins.
 *  - `expo start` in development: the LAN host that serves Metro, port 8000.
 *  - Android emulator fallback: 10.0.2.2 (the host machine).
 *  - Release builds: the deployed Cloud Run service.
 */
import Constants from 'expo-constants';
import { Platform } from 'react-native';

const PRODUCTION_API_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL?.trim() ||
  'https://closetmate-ai-801722190488.us-central1.run.app';

function getBackendUrl(): string {
  const explicit = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (explicit) return explicit;

  if (__DEV__) {
    const hostUri = Constants.expoConfig?.hostUri;
    if (hostUri) return `http://${hostUri.split(':')[0]}:8000`;
    if (Platform.OS === 'android' && !Constants.isDevice) return 'http://10.0.2.2:8000';
  }
  return PRODUCTION_API_URL;
}

export const AI_BASE_URL = getBackendUrl();

if (__DEV__) console.log('[config] API base URL =', AI_BASE_URL);
