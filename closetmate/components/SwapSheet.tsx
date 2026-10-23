/**
 * SwapSheet — pick a different piece for one slot of an outfit.
 * Lists the closet items that fill the same role (another top, another pair of shoes…).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, FlatList, Modal, Pressable, StyleSheet, Text, useWindowDimensions, View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Brand } from '@/constants/theme';
import { WardrobeItem } from '@/src/api/ai';
import { getClosetItems, peekCloset } from '@/src/state/closetCache';
import { ItemCard } from '@/components/ItemCard';

interface Props {
  visible: boolean;
  slot: string | null;
  userId: string;
  /** Items already in the outfit are not offered again. */
  excludeIds: string[];
  dark: boolean;
  onPick: (item: WardrobeItem) => void;
  onClose: () => void;
}

const SLOT_NAME: Record<string, string> = {
  outer: 'outerwear', dress: 'dress', top: 'top', bottom: 'bottoms', shoes: 'shoes', accessory: 'accessory',
};
const SIDE = 22;
const GAP = 12;

export function SwapSheet({ visible, slot, userId, excludeIds, dark, onPick, onClose }: Props) {
  const { width: screenWidth } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [items, setItems] = useState<WardrobeItem[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!visible) return;
    let active = true;
    setItems(peekCloset(userId));           // a warm cache shows instantly; null shows the spinner
    setError(false);
    getClosetItems(userId)
      .then((all) => active && setItems(all))
      .catch(() => active && setError(true));
    return () => { active = false; };
  }, [visible, userId]);

  const options = useMemo(
    () => (items ?? []).filter((i) => i.slot === slot && !excludeIds.includes(i.item_id)),
    [items, slot, excludeIds]
  );

  const pickById = useCallback((id: string) => {
    const picked = options.find((i) => i.item_id === id);
    if (picked) onPick(picked);
  }, [options, onPick]);

  const cardWidth = Math.floor((screenWidth - SIDE * 2 - GAP * 2) / 3);
  const name = SLOT_NAME[slot ?? ''] ?? 'piece';
  const text = dark ? '#FFFFFF' : Brand.ink;
  const muted = dark ? 'rgba(255,255,255,0.6)' : 'rgba(22,20,26,0.55)';

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" />
      <View
        style={[
          styles.sheet,
          { backgroundColor: dark ? Brand.nightCard : '#FFFFFF', paddingBottom: 16 + insets.bottom },
        ]}
      >
        <View style={[styles.grabber, { backgroundColor: dark ? Brand.hairlineDark : Brand.hairline }]} />
        <View style={styles.header}>
          <Text style={[styles.title, { color: text }]}>Swap {name}</Text>
          <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button" accessibilityLabel="Close">
            <Ionicons name="close" size={22} color={muted} />
          </Pressable>
        </View>

        {error ? (
          <Text style={[styles.note, { color: muted }]}>Could not load your closet. Try again in a moment.</Text>
        ) : items === null ? (
          <ActivityIndicator style={styles.loading} color={muted} />
        ) : options.length === 0 ? (
          <Text style={[styles.note, { color: muted }]}>
            You don’t have another {name} in your closet yet. Add one and it will show up here.
          </Text>
        ) : (
          <FlatList
            data={options}
            keyExtractor={(i) => i.item_id}
            numColumns={3}
            columnWrapperStyle={styles.row}
            contentContainerStyle={styles.grid}
            showsVerticalScrollIndicator={false}
            renderItem={({ item, index }) => (
              <ItemCard
                id={item.item_id}
                uri={item.image_path}
                title={item.subcategory}
                color={item.primary_color}
                width={cardWidth}
                dark={dark}
                index={index}
                onPress={pickById}
              />
            )}
          />
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    maxHeight: '72%',
    minHeight: 280,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
  },
  row: { gap: GAP, paddingHorizontal: SIDE, marginBottom: GAP + 6 },
  grabber: { alignSelf: 'center', width: 38, height: 4, borderRadius: 2, marginTop: 10 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: SIDE,
    paddingTop: 16,
    paddingBottom: 14,
  },
  title: { fontSize: 20, fontWeight: '700', letterSpacing: -0.3, textTransform: 'capitalize' },
  loading: { marginTop: 48 },
  note: { fontSize: 14, lineHeight: 20, textAlign: 'center', paddingHorizontal: 32, marginTop: 36 },
  grid: { paddingBottom: 12 },
});
