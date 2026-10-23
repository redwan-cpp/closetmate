/**
 * Lookboard — an outfit composed as a collage on a paper-coloured card.
 *
 * Pieces are placed by *slot* (see backend services/outfit_layout.py): a dress or a top +
 * bottom in the middle, outerwear tucked behind, shoes underneath, accessories down the
 * right edge. No AI image generation is involved — it is the user's own cutouts arranged
 * on the phone, so it is instant and free.
 */
import React, { memo, useMemo } from 'react';
import { Pressable, StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Brand } from '@/constants/theme';
import { isCutout } from '@/src/api/images';
import { ItemImage } from '@/components/ItemImage';

export type Slot = 'outer' | 'dress' | 'top' | 'bottom' | 'shoes' | 'accessory';

export interface LookPiece {
  id: string;
  uri: string | null | undefined;
  slot?: string | null;
  label?: string;
}

interface Props {
  pieces: LookPiece[];
  width: number;
  /** Tap a piece (used for "swap this piece"). */
  onPiecePress?: (piece: LookPiece) => void;
  style?: StyleProp<ViewStyle>;
  radius?: number;
}

/** Centre-x, centre-y, width, height — all as fractions of the board (which is 4:5). */
interface Box { cx: number; cy: number; w: number; h: number }

const WITH_DRESS: Partial<Record<Slot, Box>> = {
  outer: { cx: 0.56, cy: 0.33, w: 0.52, h: 0.44 },
  dress: { cx: 0.42, cy: 0.45, w: 0.70, h: 0.78 },
  shoes: { cx: 0.42, cy: 0.91, w: 0.46, h: 0.19 },
};
const SEPARATES: Partial<Record<Slot, Box>> = {
  outer: { cx: 0.33, cy: 0.30, w: 0.56, h: 0.48 },
  bottom: { cx: 0.42, cy: 0.64, w: 0.60, h: 0.54 },
  top: { cx: 0.42, cy: 0.27, w: 0.64, h: 0.46 },
  shoes: { cx: 0.42, cy: 0.92, w: 0.46, h: 0.17 },
};
const SOLO: Box = { cx: 0.5, cy: 0.5, w: 0.88, h: 0.9 };
const SIDE_COLUMN: Box[] = [
  { cx: 0.87, cy: 0.17, w: 0.23, h: 0.19 },
  { cx: 0.87, cy: 0.40, w: 0.23, h: 0.19 },
  { cx: 0.87, cy: 0.63, w: 0.23, h: 0.19 },
];
const GRID_2X2: Box[] = [
  { cx: 0.27, cy: 0.28, w: 0.42, h: 0.38 },
  { cx: 0.73, cy: 0.28, w: 0.42, h: 0.38 },
  { cx: 0.27, cy: 0.72, w: 0.42, h: 0.38 },
  { cx: 0.73, cy: 0.72, w: 0.42, h: 0.38 },
];
/** Draw order, back to front. */
const Z_ORDER: Slot[] = ['outer', 'bottom', 'top', 'dress', 'shoes', 'accessory'];

interface Placed { piece: LookPiece; box: Box }

/** Decide where each piece goes. Pure, so it is easy to reason about and to test. */
export function layoutPieces(pieces: LookPiece[]): Placed[] {
  const bySlot = new Map<Slot, LookPiece[]>();
  for (const piece of pieces) {
    const slot = (Z_ORDER.includes(piece.slot as Slot) ? piece.slot : 'accessory') as Slot;
    bySlot.set(slot, [...(bySlot.get(slot) ?? []), piece]);
  }

  const structural = Z_ORDER.filter((s) => s !== 'accessory' && bySlot.has(s));
  const spill: LookPiece[] = [];          // 2nd top, 2nd pair of shoes… join the accessories
  const placed: Placed[] = [];

  if (structural.length === 0) {
    const loose = (bySlot.get('accessory') ?? []).slice(0, 4);
    return loose.map((piece, i) => ({ piece, box: loose.length === 1 ? SOLO : GRID_2X2[i] }));
  }

  const layout = bySlot.has('dress') ? WITH_DRESS : SEPARATES;
  const onlyOne = pieces.length === 1;

  for (const slot of Z_ORDER) {
    if (slot === 'accessory') continue;
    const group = bySlot.get(slot) ?? [];
    if (group.length === 0) continue;
    const box = onlyOne ? SOLO : layout[slot];
    if (box) placed.push({ piece: group[0], box });
    else spill.push(group[0]);            // e.g. a bottom alongside a dress has no spot
    spill.push(...group.slice(1));
  }

  [...(bySlot.get('accessory') ?? []), ...spill].slice(0, SIDE_COLUMN.length).forEach((piece, i) =>
    placed.push({ piece, box: SIDE_COLUMN[i] })
  );
  return placed;
}

export const Lookboard = memo(function Lookboard({ pieces, width, onPiecePress, style, radius = 24 }: Props) {
  const height = Math.round(width * 1.25);
  const placed = useMemo(() => layoutPieces(pieces), [pieces]);

  return (
    <View style={[styles.board, { width, height, borderRadius: radius }, style]}>
      {placed.length === 0 && (
        <View style={styles.empty}>
          <Ionicons name="shirt-outline" size={32} color="rgba(22,20,26,0.25)" />
        </View>
      )}
      {placed.map(({ piece, box }) => (
        <Pressable
          key={piece.id}
          disabled={!onPiecePress}
          onPress={() => onPiecePress?.(piece)}
          accessible={!!onPiecePress}
          accessibilityRole={onPiecePress ? 'button' : undefined}
          accessibilityLabel={onPiecePress && piece.label ? `Swap ${piece.label}` : undefined}
          // Old white-background photos are multiplied into the paper so they don't show as
          // boxes. The blend must sit on the node whose PARENT is the paper board: Android only
          // blends a child against its direct parent's layer, and a wrapper with no background
          // would have nothing to multiply with.
          style={[
            {
              position: 'absolute',
              left: (box.cx - box.w / 2) * width,
              top: (box.cy - box.h / 2) * height,
              width: box.w * width,
              height: box.h * height,
            },
            !isCutout(piece.uri) && styles.multiply,
          ]}
        >
          {/* Boards wider than ~220dp would stretch the 320px thumbnail, so use the full image there. */}
          <ItemImage uri={piece.uri} style={StyleSheet.absoluteFill} contentFit="contain" thumb={width < 220} />
        </Pressable>
      ))}
    </View>
  );
});

const styles = StyleSheet.create({
  board: {
    backgroundColor: Brand.paper,
    overflow: 'hidden',
    isolation: 'isolate',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: Brand.hairline,
  },
  multiply: { mixBlendMode: 'multiply' },
  empty: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
});
