/**
 * ItemCard — a garment cutout floating on a soft pastel tile, with its name underneath.
 *
 * The tile colour is a stable function of the item id, so the closet is colourful but never
 * changes between renders. Tiles stay light in dark mode too: legacy photos (white-background
 * JPEGs from before studio shots) are multiplied into the tile, which on a dark tile would
 * crush them to near-black, and dark garments need a light backdrop to read at all.
 */
import React, { memo, useEffect, useMemo, useRef } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';
import { Brand, Elevation, tintFor } from '@/constants/theme';
import { isCutout } from '@/src/api/images';
import { ItemImage } from '@/components/ItemImage';

interface Props {
  id: string;
  uri: string | null | undefined;
  /** Server thumbnail (stored photos). */
  thumb?: string | null;
  title?: string | null;
  color?: string | null;
  width: number;
  dark: boolean;
  /** Position in the grid: the first few cards ease in one after another. */
  index?: number;
  /** Receive the item id, so one stable callback can serve the whole grid (keeps memo effective). */
  onPress?: (id: string) => void;
  onLongPress?: (id: string) => void;
}

const RADIUS = 22;
const ENTER_MAX_INDEX = 14;

export const ItemCard = memo(function ItemCard({
  id, uri, thumb, title, color, width, dark, index = 0, onPress, onLongPress,
}: Props) {
  const height = Math.round(width * 1.25);
  const enter = useRef(new Animated.Value(index < ENTER_MAX_INDEX ? 0 : 1)).current;
  const translateY = useMemo(() => enter.interpolate({ inputRange: [0, 1], outputRange: [10, 0] }), [enter]);

  useEffect(() => {
    if (index >= ENTER_MAX_INDEX) return;
    const anim = Animated.timing(enter, {
      toValue: 1,
      duration: 320,
      delay: index * 35,
      easing: Easing.bezier(0.2, 0, 0, 1),
      useNativeDriver: true,
    });
    anim.start();
    return () => anim.stop();
  }, [enter, index]);

  const label = [color, title].filter(Boolean).join(' ');
  const legacy = !isCutout(uri);
  const tint = tintFor(id, false);

  return (
    <Animated.View style={{ width, opacity: enter, transform: [{ translateY }] }}>
      <Pressable
        onPress={onPress ? () => onPress(id) : undefined}
        onLongPress={onLongPress ? () => onLongPress(id) : undefined}
        delayLongPress={380}
        accessibilityRole="button"
        accessibilityLabel={label || 'Clothing item'}
        accessibilityHint="Opens options for this item"
        style={({ pressed }) => [{ transform: [{ scale: pressed ? 0.96 : 1 }] }]}
      >
        {/* Shadow lives on the outer view (opaque, or Android draws no elevation); the inner one
            clips the image to the rounded tile and is the backdrop the legacy multiply blends with. */}
        <View style={[Elevation.card, { width, height, borderRadius: RADIUS, backgroundColor: tint }]}>
          <View style={[styles.tile, { borderRadius: RADIUS, backgroundColor: tint }]}>
            <View style={[styles.imageWrap, legacy && styles.multiply]}>
              <ItemImage uri={uri} thumbSrc={thumb} style={StyleSheet.absoluteFill} contentFit="contain" />
            </View>
          </View>
        </View>
      </Pressable>
      <Text
        numberOfLines={1}
        accessibilityElementsHidden
        importantForAccessibility="no"
        style={[styles.label, { color: dark ? 'rgba(255,255,255,0.72)' : 'rgba(22,20,26,0.62)' }]}
      >
        {label || ' '}
      </Text>
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  tile: { flex: 1, overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth, borderColor: Brand.hairline },
  imageWrap: { ...StyleSheet.absoluteFillObject, padding: 6 },
  multiply: { mixBlendMode: 'multiply' },
  label: {
    marginTop: 8,
    paddingHorizontal: 4,
    fontSize: 12,
    fontWeight: '500',
    textTransform: 'capitalize',
    letterSpacing: 0.1,
  },
});
