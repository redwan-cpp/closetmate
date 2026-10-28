/**
 * src/api/studioFiles.ts — housekeeping for photo files that live on the phone.
 *
 * New photos are kept in the cloud (see uploadPhoto / studioShot({ store: true })). Files in the
 * app's own folder are only what OLDER versions left behind (closetmate_images/…), plus the
 * temporary copies made while uploading.
 */
import * as FileSystem from 'expo-file-system/legacy';

/** True for a photo file that belongs to this app's own storage (older versions kept photos there). */
export function isOwnLocalPhoto(uri: string | null | undefined): boolean {
  return !!uri && uri.startsWith('file://') && uri.includes('/closetmate_images/');
}

/** Best-effort removal of files we wrote (missing files are fine). */
export function deleteFiles(paths: string[]): void {
  paths.forEach((p) => { FileSystem.deleteAsync(p, { idempotent: true }).catch(() => {}); });
}

/** `…/item_1.webp` → `…/item_1_t.webp`: the thumbnail older versions wrote beside a studio shot. */
export function thumbPathOf(fullPath: string): string {
  return fullPath.replace(/\.webp$/, '_t.webp');
}

/**
 * A local file the uploader can read. Links to stored photos are fetched into the cache first,
 * because a multipart upload needs a file on the phone. Returns the path and whether it is temporary.
 */
export async function localCopy(uri: string): Promise<{ uri: string; temporary: boolean }> {
  if (!/^https?:\/\//.test(uri)) return { uri, temporary: false };
  const dest = `${FileSystem.cacheDirectory}download_${Date.now()}.jpg`;
  const result = await FileSystem.downloadAsync(uri, dest);
  if (result.status !== 200) {
    deleteFiles([dest]);
    throw new Error('Could not load this photo. Check your connection and try again.');
  }
  return { uri: dest, temporary: true };
}
