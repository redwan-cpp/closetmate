/**
 * LookCard — the AI stylist's outfit suggestion as a picture.
 *
 *   ┌───────────────────────┐
 *   │      lookboard        │   the user's own cutouts, composed (tap a piece to swap it)
 *   └───────────────────────┘
 *   chips: "2 of 3 in your best colors" · "☀ 28° outdoor"       (only facts we verified)
 *   white linen shirt · light blue jeans
 *   [ Wear today ]  [ ♡ ]
 */
import React, { memo, useCallback, useMemo, useRef, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import * as Haptics from 'expo-haptics';
import { Ionicons } from '@expo/vector-icons';
import { Brand } from '@/constants/theme';
import { LookMeta, SuggestedOutfitItem, WardrobeItem, resolveImageUrl, saveLook } from '@/src/api/ai';
import { Lookboard, LookPiece } from '@/components/Lookboard';
import { SwapSheet } from '@/components/SwapSheet';

/** Identifies an outfit by the pieces in it (order doesn't matter). '' when none has an id. */
export function outfitKey(items: SuggestedOutfitItem[]): string {
  return items.map((i) => i.item_id).filter((id): id is string => !!id).sort().join(',');
}

interface Props {
  /** The outfit as it is NOW. The parent owns it, so swaps survive the list recycling this cell. */
  items: SuggestedOutfitItem[];
  /** Facts about the outfit. The parent drops the colour fact once a piece has been swapped. */
  meta?: LookMeta | null;
  userId: string;
  dark: boolean;
  /** outfitKey() of the outfit already logged as worn today, if any. */
  wornKey: string | null;
  /** A piece was swapped: the new outfit. */
  onChange: (items: SuggestedOutfitItem[]) => void;
  /** Called with the outfit as it is NOW (after any swaps). May return a promise. */
  onWear: (items: SuggestedOutfitItem[]) => void | Promise<void>;
}

export const LookCard = memo(function LookCard({ items, meta, userId, dark, wornKey, onChange, onWear }: Props) {
  const { width: screenWidth } = useWindowDimensions();
  const boardWidth = Math.min(screenWidth - 32 - 38, 340);   // chat gutters + the stylist avatar

  const [swapIndex, setSwapIndex] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  // The slot being swapped outlives swapIndex, so the sheet keeps its title while it slides away.
  const [swapSlot, setSwapSlot] = useState<string | null>(null);
  const wearing = useRef(false);

  const pieces: LookPiece[] = useMemo(
    () => items.map((item, i) => ({
      id: item.item_id ?? `${item.slot ?? item.subcategory}-${i}`,
      uri: resolveImageUrl(item.image_url),
      slot: item.slot,
      label: `${item.color} ${item.subcategory}`.trim(),
    })),
    [items]
  );
  const hasImages = pieces.some((p) => p.uri);
  const savableIds = useMemo(
    () => items.map((i) => i.item_id).filter((id): id is string => !!id),
    [items]
  );
  // Worn only if THIS outfit (with any swaps) is the one that was logged.
  const wornToday = wornKey !== null && wornKey !== '' && wornKey === outfitKey(items);

  // Ignore a second tap while the first is still being logged (the button only flips to
  // "worn" once the server answers, so a double tap would otherwise log the outfit twice).
  const onWearPress = useCallback(async () => {
    if (wearing.current) return;
    wearing.current = true;
    try {
      await onWear(items);
    } finally {
      wearing.current = false;
    }
  }, [onWear, items]);

  const chips = useMemo(() => {
    const out: { icon: keyof typeof Ionicons.glyphMap; text: string }[] = [];
    if (meta?.palette && meta.palette.matched > 0) {
      const { matched, total } = meta.palette;
      out.push({ icon: 'color-palette-outline', text: `${matched} of ${total} in your best colors` });
    }
    const w = meta?.weather;
    if (w && typeof w.temperature === 'number') {
      const where = w.environment ? ` · ${w.environment}` : '';
      out.push({ icon: 'partly-sunny-outline', text: `${Math.round(w.temperature)}°${where}` });
    }
    return out;
  }, [meta]);

  const onSave = useCallback(async () => {
    if (saving || saved || savableIds.length === 0) return;
    setSaving(true);
    try {
      await saveLook(userId, savableIds);
      setSaved(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e) {
      Alert.alert('Could not save this look', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setSaving(false);
    }
  }, [saving, saved, savableIds, userId]);

  const onPick = useCallback((picked: WardrobeItem) => {
    onChange(items.map((item, i) => (i === swapIndex ? {
      subcategory: picked.subcategory ?? item.subcategory,
      color: picked.primary_color ?? item.color,
      item_id: picked.item_id,
      image_url: picked.image_path,
      category: picked.category,
      slot: picked.slot ?? item.slot,
    } : item)));
    setSaved(false);
    setSwapIndex(null);
    Haptics.selectionAsync().catch(() => {});
  }, [items, onChange, swapIndex]);

  const onPiecePress = useCallback((piece: LookPiece) => {
    const index = pieces.findIndex((p) => p.id === piece.id);
    const slot = index >= 0 ? items[index]?.slot : null;
    if (slot) {
      setSwapSlot(slot);
      setSwapIndex(index);
    }
  }, [pieces, items]);

  const ink = dark ? '#FFFFFF' : Brand.ink;
  const muted = dark ? 'rgba(255,255,255,0.6)' : 'rgba(22,20,26,0.55)';

  return (
    <View style={styles.wrap}>
      <Text style={[styles.kicker, { color: muted }]}>Styled for you</Text>

      {hasImages ? (
        <Lookboard pieces={pieces} width={boardWidth} onPiecePress={onPiecePress} />
      ) : (
        // No photos on file for these pieces: fall back to plain colour chips.
        <View style={styles.fallback}>
          {items.map((item, i) => (
            <View key={`${item.item_id ?? i}`} style={[styles.chip, { backgroundColor: dark ? Brand.nightCard : '#F0ECF6' }]}>
              <Text style={[styles.chipText, { color: ink }]}>{item.color} {item.subcategory}</Text>
            </View>
          ))}
        </View>
      )}

      {chips.length > 0 && (
        <View style={styles.chipRow}>
          {chips.map((chip) => (
            <View
              key={chip.text}
              style={[styles.chip, { backgroundColor: dark ? Brand.accentSoftDark : Brand.accentSoft }]}
            >
              <Ionicons name={chip.icon} size={13} color={Brand.accent} />
              <Text style={[styles.factText, { color: dark ? '#D9CCFB' : '#4B2A9A' }]}>{chip.text}</Text>
            </View>
          ))}
        </View>
      )}

      <Text style={[styles.caption, { color: muted }]} numberOfLines={2}>
        {items.map((i) => `${i.color} ${i.subcategory}`).join(' · ')}
      </Text>
      {hasImages && items.some((i) => i.slot) && (
        <Text style={[styles.hint, { color: muted }]}>Tap a piece to swap it</Text>
      )}

      <View style={styles.actions}>
        <Pressable
          onPress={wornToday ? undefined : onWearPress}
          accessibilityRole="button"
          accessibilityState={{ disabled: wornToday }}
          style={({ pressed }) => [
            styles.wear,
            wornToday
              ? { backgroundColor: 'transparent', borderColor: '#30D158', borderWidth: 1 }
              : { backgroundColor: dark ? '#FFFFFF' : Brand.ink },
            { transform: [{ scale: pressed && !wornToday ? 0.96 : 1 }] },
          ]}
        >
          <Text style={[styles.wearText, { color: wornToday ? '#30D158' : dark ? Brand.ink : '#FFFFFF' }]}>
            {wornToday ? '✓ Logged as worn today' : 'Wear today'}
          </Text>
        </Pressable>

        {savableIds.length > 0 && (
          <Pressable
            onPress={onSave}
            disabled={saving}
            accessibilityRole="button"
            accessibilityLabel={saved ? 'Saved to your looks' : 'Save this look'}
            style={({ pressed }) => [
              styles.save,
              { borderColor: dark ? Brand.hairlineDark : Brand.hairline, transform: [{ scale: pressed ? 0.96 : 1 }] },
            ]}
          >
            <Ionicons
              name={saved ? 'heart' : 'heart-outline'}
              size={20}
              color={saved ? '#E5484D' : ink}
            />
          </Pressable>
        )}
      </View>

      <SwapSheet
        visible={swapIndex !== null}
        slot={swapSlot}
        userId={userId}
        excludeIds={savableIds}
        dark={dark}
        onPick={onPick}
        onClose={() => setSwapIndex(null)}
      />
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: { marginTop: 8, gap: 10 },
  kicker: { fontSize: 11, fontWeight: '600', letterSpacing: 0.8, textTransform: 'uppercase' },
  fallback: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  chipText: { fontSize: 12, fontWeight: '600', textTransform: 'capitalize' },
  // Sentences ("2 of 3 in your best colors"), not names: no title-casing.
  factText: { fontSize: 12, fontWeight: '600' },
  caption: { fontSize: 13, lineHeight: 18, textTransform: 'capitalize' },
  hint: { fontSize: 11, marginTop: -4 },
  actions: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 2 },
  wear: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 999,
    paddingHorizontal: 20,
    height: 44,
  },
  wearText: { fontSize: 14, fontWeight: '700' },
  save: {
    width: 44,
    height: 44,
    borderRadius: 22,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
