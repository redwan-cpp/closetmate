/**
 * photoBackup — move the photos that only exist on THIS phone into the user's private cloud storage.
 *
 * Older versions kept every photo in the app's own folder and saved a file:// path in the closet.
 * Reinstalling the app, or switching phones, would lose them all. Backing up uploads each one,
 * points its item at the stored copy, and only then removes the local file.
 *
 * One at a time: kind to mobile data, easy to resume, and a failure only affects its own photo.
 * It costs no AI quota — it is storage only.
 */
import * as FileSystem from 'expo-file-system/legacy';
import { WardrobeItem, discardPhoto, replaceItemImage, uploadPhoto } from '@/src/api/ai';
import { isCutout, prepareForUpload } from '@/src/api/images';
import { deleteFiles, isOwnLocalPhoto, thumbPathOf } from '@/src/api/studioFiles';

export interface BackupProgress {
  total: number;
  done: number;
  /** The upload or the update failed (no connection, server error): worth retrying. */
  failed: number;
  /** The file is no longer on this phone (cleared storage): it can't be recovered. */
  missing: number;
}

/** Items whose photo is a file on this phone. */
export function localPhotoItems(items: WardrobeItem[]): WardrobeItem[] {
  return items.filter((i) => !!i.image_path && i.image_path.startsWith('file://'));
}

export async function backUpLocalPhotos(
  items: WardrobeItem[],
  onProgress: (progress: BackupProgress) => void,
  shouldStop: () => boolean = () => false,
): Promise<BackupProgress> {
  const todo = localPhotoItems(items);
  const progress: BackupProgress = { total: todo.length, done: 0, failed: 0, missing: 0 };
  onProgress({ ...progress });

  for (const item of todo) {
    if (shouldStop()) break;
    const path = item.image_path as string;
    try {
      const info = await FileSystem.getInfoAsync(path);
      if (!info.exists) {
        progress.missing += 1;
      } else {
        // Cutouts (WebP/PNG) are tiny and must stay transparent: send them as they are.
        // Opaque photos are shrunk first; the server re-encodes them anyway.
        const source = isCutout(path) ? path : await prepareForUpload(path);
        const photo = await uploadPhoto(source);
        try {
          await replaceItemImage(item.item_id, photo.imagePath);
        } catch (e) {
          discardPhoto(photo.photoId);          // nothing points at it
          throw e;
        }
        if (isOwnLocalPhoto(path)) deleteFiles([path, thumbPathOf(path)]);
        progress.done += 1;
      }
    } catch {
      progress.failed += 1;
    }
    onProgress({ ...progress });
  }
  return progress;
}
