/**
 * src/api/studioFiles.ts — keep studio shots on the device.
 *
 * A studio shot is saved as `item_<stamp>.webp` (640×800, transparent) with a smaller
 * `item_<stamp>_t.webp` (320×400) beside it for grids. The database stores only the full path;
 * the thumbnail is found by naming convention (see thumbUri in images.ts) and is optional.
 */
import * as FileSystem from 'expo-file-system/legacy';
import type { StudioShotResult } from '@/src/api/ai';

const stripDataUri = (dataUri: string) => dataUri.replace(/^data:image\/[\w+]+;base64,/, '');

/** `…/item_1.webp` → `…/item_1_t.webp`. */
export function thumbPathOf(fullPath: string): string {
  return fullPath.replace(/\.webp$/, '_t.webp');
}

/** Write a studio shot (and its thumbnail) into the app's document directory; returns the full image path. */
export async function saveStudioShot(shot: StudioShotResult): Promise<string> {
  const dir = `${FileSystem.documentDirectory ?? ''}closetmate_images/`;
  await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
  const full = `${dir}item_${Date.now()}.webp`;
  await FileSystem.writeAsStringAsync(full, stripDataUri(shot.image), { encoding: FileSystem.EncodingType.Base64 });
  await FileSystem.writeAsStringAsync(thumbPathOf(full), stripDataUri(shot.thumb), {
    encoding: FileSystem.EncodingType.Base64,
  }).catch(() => {});   // the thumbnail is optional
  return full;
}

/** Best-effort removal of files we wrote (missing files are fine). */
export function deleteFiles(paths: string[]): void {
  paths.forEach((p) => { FileSystem.deleteAsync(p, { idempotent: true }).catch(() => {}); });
}
