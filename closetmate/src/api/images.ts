/**
 * src/api/images.ts — shrink photos on the device before uploading them.
 *
 * Camera photos are 3–12 MB and often 12–50 megapixels. The server resizes them
 * anyway (and rejects anything above its pixel cap), so uploading the original
 * only burns the user's data plan, slows the scan, and costs us bandwidth.
 * ~1600 px on the long side is plenty for background removal and clothing tagging.
 */
import * as ImageManipulator from 'expo-image-manipulator';
import { Image } from 'react-native';

export const UPLOAD_MAX_SIDE = 1600;

const WEBP = /\.webp(\?.*)?$/i;
const WEBP_THUMB = /_t\.webp(\?.*)?$/i;

/**
 * Studio shots are saved as `item_123.webp` with a small `item_123_t.webp` beside it.
 * Returns the thumbnail path for such a file; anything else (old JPEGs, remote URLs) is
 * returned unchanged, so callers can always use the result.
 */
export function thumbUri(uri: string | null | undefined): string | null {
  if (!uri) return null;
  if (WEBP.test(uri) && !WEBP_THUMB.test(uri)) return uri.replace(WEBP, '_t.webp$1');
  return uri;
}

/** True for images that already have a transparent background (studio shots, PNGs). */
export function isCutout(uri: string | null | undefined): boolean {
  return !!uri && /\.(webp|png)(\?.*)?$/i.test(uri);
}

function getImageSize(uri: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    Image.getSize(uri, (width, height) => resolve({ width, height }), reject);
  });
}

/**
 * Returns the URI of a JPEG whose longest side is at most `maxSide`.
 * If anything goes wrong (unsupported URI, low memory) the ORIGINAL uri is returned,
 * so an upload is never blocked by this optimisation.
 */
export async function prepareForUpload(uri: string, maxSide: number = UPLOAD_MAX_SIDE): Promise<string> {
  try {
    const { width, height } = await getImageSize(uri);
    const actions: ImageManipulator.Action[] =
      Math.max(width, height) > maxSide
        ? [{ resize: width >= height ? { width: maxSide } : { height: maxSide } }]
        : [];
    const result = await ImageManipulator.manipulateAsync(uri, actions, {
      compress: 0.85,
      format: ImageManipulator.SaveFormat.JPEG,
    });
    return result.uri;
  } catch (e) {
    if (__DEV__) console.warn('[images] could not downscale, uploading the original', e);
    return uri;
  }
}
