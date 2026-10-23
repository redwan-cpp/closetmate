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
  contentFit?: 'contain' | 'cover';
}

/** Images known to have no thumbnail, so a remounted cell doesn't 404 on it all over again. */
const missingThumb = new Set<string>();

export const ItemImage = memo(function ItemImage({ uri, style, thumb = true, contentFit = 'contain' }: Props) {
  const [, rerender] = useState(0);

  if (!uri) return null;
  const source = thumb && !missingThumb.has(uri) ? (thumbUri(uri) ?? uri) : uri;

  return (
    <Image
      source={{ uri: source }}
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
