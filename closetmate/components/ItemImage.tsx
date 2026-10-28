/**
 * ItemImage — one garment picture.
 *
 * Tries the small thumbnail first (…_t.webp, written next to every new studio shot) so a
 * grid of 100 items doesn't decode 100 full-size images, and quietly falls back to the
 * full image for older items that don't have a thumbnail.
 */
import React, { memo, useState } from 'react';
import { StyleProp } from 'react-native';
import { Image, ImageStyle } from 'expo-image';
import { thumbUri } from '@/src/api/images';

interface Props {
  uri: string | null | undefined;
  style?: StyleProp<ImageStyle>;
  /** Prefer the thumbnail (default). Pass false for big previews. */
  thumb?: boolean;
  /** The server's thumbnail for this photo, when it has one (stored photos). Else the file-name rule is tried. */
  thumbSrc?: string | null;
  contentFit?: 'contain' | 'cover';
}

/** Images known to have no thumbnail, so a remounted cell doesn't 404 on it all over again. */
const missingThumb = new Set<string>();

/**
 * A stored photo's link changes every few hours (a new signature), but its picture never does:
 * caching under the link without its query string keeps it on the phone instead of re-downloading.
 */
function sourceFor(uri: string) {
  return /^https?:\/\//.test(uri) && uri.includes('?') ? { uri, cacheKey: uri.split('?')[0] } : { uri };
}

export const ItemImage = memo(function ItemImage({ uri, style, thumb = true, thumbSrc, contentFit = 'contain' }: Props) {
  const [, rerender] = useState(0);

  if (!uri) return null;
  const source = thumb && !missingThumb.has(uri) ? (thumbSrc ?? thumbUri(uri) ?? uri) : uri;

  return (
    <Image
      source={sourceFor(source)}
      style={style}
      contentFit={contentFit}
      transition={160}
      cachePolicy="memory-disk"
      recyclingKey={uri}
      onError={() => {
        if (source !== uri) {
          missingThumb.add(uri);
          rerender((n) => n + 1);
        }
      }}
      accessible={false}
    />
  );
});
