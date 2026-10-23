/**
 * app/(tabs)/closet.tsx — the closet as a boutique shelf.
 *
 *  Closet | Looks
 *  • Closet: category chips + a dense grid of studio-shot cutouts on pastel tiles.
 *  • Looks:  the outfits you saved from the stylist, shown as lookboards.
 */
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, Animated, Easing, FlatList, Modal, Pressable, RefreshControl,
  ScrollView, StyleSheet, Text, useWindowDimensions, View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Brand, Elevation, tintFor } from '@/constants/theme';
import {
  Look, WardrobeItem, deleteLook, deleteWardrobeItem, getLooks, logWornOutfit, replaceItemImage, studioShot,
} from '@/src/api/ai';
import { isCutout, prepareForUpload } from '@/src/api/images';
import { deleteFiles, saveStudioShot, thumbPathOf } from '@/src/api/studioFiles';
import { getClosetItems, invalidateCloset, peekCloset, removeFromCloset } from '@/src/state/closetCache';
import { useAuth } from '@/src/context/AuthContext';
import ActionSheetModal from '@/components/ActionSheetModal';
import { ItemCard } from '@/components/ItemCard';
import { Lookboard, LookPiece } from '@/components/Lookboard';

const SIDE = 20;
const GAP = 12;

const CATEGORY_LABELS: Record<string, string> = {
  top: 'Tops',
  bottom: 'Bottoms',
  dress: 'Dresses',
  traditional: 'Traditional',
  outerwear: 'Outerwear',
  footwear: 'Footwear',
  accessory: 'Accessories',
};

const categoryOf = (item: WardrobeItem) => (item.category ?? '').toLowerCase();

const toPieces = (look: Look): LookPiece[] =>
  look.items.map((i) => ({
    id: i.item_id,
    uri: i.image_path,
    slot: i.slot,
    label: [i.primary_color, i.subcategory].filter(Boolean).join(' '),
  }));

// ---------------------------------------------------------------------------
// Small pieces
// ---------------------------------------------------------------------------

function Segmented({ value, onChange, dark }: {
  value: 'closet' | 'looks'; onChange: (v: 'closet' | 'looks') => void; dark: boolean;
}) {
  const track = dark ? 'rgba(255,255,255,0.08)' : 'rgba(22,20,26,0.06)';
  return (
    <View style={[styles.segTrack, { backgroundColor: track }]} accessibilityRole="tablist">
      {(['closet', 'looks'] as const).map((key) => {
        const active = value === key;
        return (
          <Pressable
            key={key}
            onPress={() => { if (!active) { Haptics.selectionAsync().catch(() => {}); onChange(key); } }}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            style={[styles.segItem, active && { backgroundColor: dark ? Brand.nightCard : '#FFFFFF' }, active && Elevation.card]}
          >
            <Text style={[styles.segText, { color: dark ? '#FFF' : Brand.ink, opacity: active ? 1 : 0.62 }]}>
              {key === 'closet' ? 'Closet' : 'Looks'}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Chip({ label, active, onPress, dark }: { label: string; active: boolean; onPress: () => void; dark: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      hitSlop={{ top: 5, bottom: 5 }}
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      style={({ pressed }) => [
        styles.chip,
        active
          ? { backgroundColor: dark ? '#FFFFFF' : Brand.ink, borderColor: 'transparent' }
          : { borderColor: dark ? Brand.hairlineDark : Brand.hairline },
        { transform: [{ scale: pressed ? 0.96 : 1 }] },
      ]}
    >
      <Text style={[styles.chipText, { color: active ? (dark ? Brand.ink : '#FFFFFF') : dark ? 'rgba(255,255,255,0.75)' : 'rgba(22,20,26,0.7)' }]}>
        {label}
      </Text>
    </Pressable>
  );
}

/** Soft pulsing placeholders while the closet loads (a spinner on a blank page feels broken). */
function SkeletonGrid({ cardWidth, dark }: { cardWidth: number; dark: boolean }) {
  const pulse = useRef(new Animated.Value(0.45)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 800, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0.45, duration: 800, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  return (
    <View
      style={styles.skeletonWrap}
      accessible
      accessibilityLabel="Loading your closet"
      accessibilityState={{ busy: true }}
    >
      {Array.from({ length: 9 }).map((_, i) => (
        <Animated.View
          key={i}
          style={{
            width: cardWidth, height: Math.round(cardWidth * 1.25), borderRadius: 22, opacity: pulse,
            backgroundColor: tintFor(`skeleton-${i}`, dark),
          }}
        />
      ))}
    </View>
  );
}

function EmptyState({ icon, title, body, dark, actionLabel, onAction }: {
  icon: keyof typeof Ionicons.glyphMap; title: string; body: string; dark: boolean;
  actionLabel?: string; onAction?: () => void;
}) {
  return (
    <View style={styles.empty}>
      <View style={[styles.emptyIcon, { backgroundColor: dark ? Brand.accentSoftDark : Brand.accentSoft }]}>
        <Ionicons name={icon} size={30} color={Brand.accent} />
      </View>
      <Text style={[styles.emptyTitle, { color: dark ? '#FFF' : Brand.ink }]}>{title}</Text>
      <Text style={[styles.emptyBody, { color: dark ? 'rgba(255,255,255,0.6)' : 'rgba(22,20,26,0.55)' }]}>{body}</Text>
      {actionLabel && onAction && (
        <Pressable
          onPress={onAction}
          accessibilityRole="button"
          style={({ pressed }) => [
            styles.emptyAction,
            { backgroundColor: dark ? '#FFFFFF' : Brand.ink, transform: [{ scale: pressed ? 0.96 : 1 }] },
          ]}
        >
          <Text style={[styles.primaryText, { color: dark ? Brand.ink : '#FFFFFF' }]}>{actionLabel}</Text>
        </Pressable>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Look detail
// ---------------------------------------------------------------------------

function LookDetail({ look, userId, dark, onClose, onDelete }: {
  look: Look | null; userId: string; dark: boolean; onClose: () => void; onDelete: (look: Look) => void;
}) {
  const { width } = useWindowDimensions();
  const [wearing, setWearing] = useState(false);
  const [worn, setWorn] = useState(false);
  const pieces = useMemo(() => (look ? toPieces(look) : []), [look]);

  if (!look) return null;
  // Modal gutter (16) + card padding (16) on each side.
  const board = Math.min(width - 64, 380);
  const ink = dark ? '#FFFFFF' : Brand.ink;
  const muted = dark ? 'rgba(255,255,255,0.6)' : 'rgba(22,20,26,0.55)';

  const wear = async () => {
    if (wearing || worn) return;
    setWearing(true);
    try {
      await logWornOutfit(userId, look.items.map((i) => i.item_id));
      setWorn(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e) {
      Alert.alert('Could not log this outfit', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      setWearing(false);
    }
  };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={styles.scrim} onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" />
      <View style={styles.detailWrap} pointerEvents="box-none">
        <View style={[styles.detailCard, Elevation.lifted, { backgroundColor: dark ? Brand.nightCard : Brand.ivory }]}>
          <View style={styles.detailHeader}>
            <Text style={[styles.detailTitle, { color: ink }]} numberOfLines={1}>
              {look.name ?? 'Saved look'}
            </Text>
            <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button" accessibilityLabel="Close">
              <Ionicons name="close" size={22} color={muted} />
            </Pressable>
          </View>
          <Lookboard pieces={pieces} width={board} />
          <Text style={[styles.detailCaption, { color: muted }]} numberOfLines={2}>
            {look.items.map((i) => [i.primary_color, i.subcategory].filter(Boolean).join(' ')).join(' · ')}
          </Text>
          <View style={styles.detailActions}>
            <Pressable
              onPress={wear}
              accessibilityRole="button"
              style={({ pressed }) => [
                styles.primary,
                worn
                  ? { borderColor: '#30D158', borderWidth: 1 }
                  : { backgroundColor: dark ? '#FFFFFF' : Brand.ink },
                { transform: [{ scale: pressed && !worn ? 0.96 : 1 }] },
              ]}
            >
              {wearing
                ? <ActivityIndicator color={dark ? Brand.ink : '#FFF'} />
                : <Text style={[styles.primaryText, { color: worn ? '#30D158' : dark ? Brand.ink : '#FFFFFF' }]}>
                    {worn ? '✓ Logged as worn today' : 'Wear today'}
                  </Text>}
            </Pressable>
            <Pressable
              onPress={() => onDelete(look)}
              accessibilityRole="button"
              accessibilityLabel="Delete this look"
              style={({ pressed }) => [styles.iconButton, { borderColor: dark ? Brand.hairlineDark : Brand.hairline, transform: [{ scale: pressed ? 0.96 : 1 }] }]}
            >
              <Ionicons name="trash-outline" size={19} color="#E5484D" />
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/** One saved look in the Looks grid. Memoised so a refresh doesn't redraw every lookboard. */
const LookTile = memo(function LookTile({ look, width, ink, onOpen, onDelete }: {
  look: Look; width: number; ink: string; onOpen: (look: Look) => void; onDelete: (look: Look) => void;
}) {
  const pieces = useMemo(() => toPieces(look), [look]);
  return (
    <Pressable
      onPress={() => onOpen(look)}
      onLongPress={() => onDelete(look)}
      delayLongPress={380}
      accessibilityRole="button"
      accessibilityLabel={look.name ?? 'Saved look'}
      accessibilityHint="Opens this look"
      style={({ pressed }) => [{ width, transform: [{ scale: pressed ? 0.96 : 1 }] }]}
    >
      {/* Opaque background so Android draws the elevation shadow. */}
      <View style={[Elevation.card, { borderRadius: 24, backgroundColor: Brand.paper }]}>
        <Lookboard pieces={pieces} width={width} />
      </View>
      <Text style={[styles.lookName, { color: ink }]} numberOfLines={1}>
        {look.name ?? `${look.items.length} ${look.items.length === 1 ? 'piece' : 'pieces'}`}
      </Text>
    </Pressable>
  );
});

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function ClosetScreen() {
  const dark = useColorScheme() === 'dark';
  const { width } = useWindowDimensions();
  const { user_id } = useAuth();
  const uid = user_id ?? '';

  const [tab, setTab] = useState<'closet' | 'looks'>('closet');
  const [filter, setFilter] = useState<string>('all');

  const [items, setItems] = useState<WardrobeItem[]>(() => peekCloset(uid) ?? []);
  const [itemsLoading, setItemsLoading] = useState(() => peekCloset(uid) === null);
  const [itemsError, setItemsError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const [looks, setLooks] = useState<Look[]>([]);
  const [looksLoading, setLooksLoading] = useState(true);
  const [openLook, setOpenLook] = useState<Look | null>(null);

  const [activeItem, setActiveItem] = useState<WardrobeItem | null>(null);
  const [sheetVisible, setSheetVisible] = useState(false);
  // The piece whose old photo is being turned into a studio shot (one at a time).
  const [upgradingId, setUpgradingId] = useState<string | null>(null);
  const upgrading = useRef(false);

  const ink = dark ? '#FFFFFF' : Brand.ink;
  const muted = dark ? 'rgba(255,255,255,0.6)' : 'rgba(22,20,26,0.55)';

  const itemWidth = Math.floor((width - SIDE * 2 - GAP * 2) / 3);
  const lookWidth = Math.floor((width - SIDE * 2 - GAP) / 2);

  // Every load takes a ticket; a delete takes one too. Only the newest ticket may write state, so a
  // slow response that started before a delete can't bring the deleted piece back.
  const itemsTicket = useRef(0);
  const looksTicket = useRef(0);

  const loadItems = useCallback(async (force = false) => {
    if (!uid) return;
    const ticket = ++itemsTicket.current;
    try {
      const fetched = await getClosetItems(uid, { force });
      if (ticket === itemsTicket.current) {
        setItemsError(false);
        setItems(fetched);
      }
    } catch {
      if (ticket === itemsTicket.current) setItemsError(true);
    } finally {
      setItemsLoading(false);
    }
  }, [uid]);

  const loadLooks = useCallback(async () => {
    if (!uid) return;
    const ticket = ++looksTicket.current;
    try {
      const fetched = await getLooks(uid);
      if (ticket === looksTicket.current) setLooks(fetched);
    } catch {
      // The Looks tab shows its empty state; the closet itself is unaffected.
    } finally {
      setLooksLoading(false);
    }
  }, [uid]);

  useFocusEffect(useCallback(() => {
    loadItems();
    loadLooks();
  }, [loadItems, loadLooks]));

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([loadItems(true), loadLooks()]);
    setRefreshing(false);
  }, [loadItems, loadLooks]);

  // Chips: only categories that actually have pieces.
  const chips = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      const key = categoryOf(item) in CATEGORY_LABELS ? categoryOf(item) : 'other';
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const ordered = [...Object.keys(CATEGORY_LABELS), 'other'].filter((k) => counts.has(k));
    return [
      { key: 'all', label: `All ${items.length}` },
      ...ordered.map((k) => ({ key: k, label: `${CATEGORY_LABELS[k] ?? 'Other'} ${counts.get(k)}` })),
    ];
  }, [items]);

  const visible = useMemo(() => {
    if (filter === 'all') return items;
    return items.filter((i) => {
      const key = categoryOf(i) in CATEGORY_LABELS ? categoryOf(i) : 'other';
      return key === filter;
    });
  }, [items, filter]);

  // If the chosen category empties out (last piece deleted), fall back to "All".
  useEffect(() => {
    if (filter !== 'all' && !chips.some((c) => c.key === filter)) setFilter('all');
  }, [chips, filter]);

  const deleteItem = useCallback(async (target: WardrobeItem) => {
    itemsTicket.current += 1;                       // invalidate any load still in flight
    const index = items.findIndex((i) => i.item_id === target.item_id);
    setItems((prev) => prev.filter((i) => i.item_id !== target.item_id));   // optimistic
    try {
      await deleteWardrobeItem(target.item_id);
      removeFromCloset(uid, target.item_id);
      loadLooks();       // looks drop pieces that no longer exist
    } catch (e) {
      setItems((prev) => {
        if (prev.some((i) => i.item_id === target.item_id)) return prev;
        const next = [...prev];
        next.splice(Math.min(Math.max(index, 0), next.length), 0, target);   // back where it was
        return next;
      });
      Alert.alert('Delete failed', e instanceof Error ? e.message : String(e));
    }
  }, [items, uid, loadLooks]);

  // Deleting a piece also removes it from every saved look, so ask first.
  const confirmDeleteItem = useCallback(() => {
    if (!activeItem) return;
    const target = activeItem;
    Alert.alert('Delete this piece?', 'It will also disappear from any saved looks that use it.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => { deleteItem(target); } },
    ]);
  }, [activeItem, deleteItem]);

  const confirmDeleteLook = useCallback((look: Look) => {
    Alert.alert('Delete this look?', 'The pieces stay in your closet.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive',
        onPress: async () => {
          looksTicket.current += 1;                 // a load that started earlier must not resurrect it
          setOpenLook(null);
          setLooks((prev) => prev.filter((l) => l.look_id !== look.look_id));
          try {
            await deleteLook(look.look_id);
          } catch (e) {
            Alert.alert('Could not delete', e instanceof Error ? e.message : 'Please try again.');
            loadLooks();
          }
        },
      },
    ]);
  }, [loadLooks]);

  // Old photos (a white-background JPEG on this device) can be upgraded to a studio shot. It costs
  // one background-removal unit, so it's an explicit choice per piece, never automatic.
  const upgradePhoto = useCallback(async (item: WardrobeItem) => {
    const oldPath = item.image_path;
    if (!oldPath || upgrading.current) return;
    upgrading.current = true;
    setUpgradingId(item.item_id);
    try {
      const shot = await studioShot(await prepareForUpload(oldPath));
      if (!shot.cutoutOk) {
        Alert.alert('No clean studio shot', 'We couldn’t make out this piece clearly in the photo, so it stays as it is.');
        return;
      }
      const newPath = await saveStudioShot(shot);
      try {
        await replaceItemImage(item.item_id, newPath);
      } catch (e) {
        deleteFiles([newPath, thumbPathOf(newPath)]);      // nothing points at them
        throw e;
      }
      if (oldPath.includes('/closetmate_images/')) deleteFiles([oldPath]);   // our own copy, now unused
      invalidateCloset();
      itemsTicket.current += 1;                            // a load that started earlier has the old path
      setItems((prev) => prev.map((i) => (i.item_id === item.item_id ? { ...i, image_path: newPath } : i)));
      loadLooks();                                         // saved looks show the new photo too
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e) {
      Alert.alert('Could not make a studio shot', e instanceof Error ? e.message : 'Please try again.');
    } finally {
      upgrading.current = false;
      setUpgradingId(null);
    }
  }, [loadLooks]);

  const canUpgrade = !!activeItem?.image_path?.startsWith('file://') && !isCutout(activeItem.image_path);
  const actions = [
    ...(canUpgrade && activeItem
      ? [{ label: 'Make studio shot', onPress: () => { upgradePhoto(activeItem); } }]
      : []),
    { label: 'Delete Item', onPress: confirmDeleteItem, destructive: true },
    { label: 'Cancel', onPress: () => setSheetVisible(false) },
  ];
  const sheetTitle = activeItem
    ? [activeItem.subcategory, activeItem.category].filter(Boolean).join(' · ')
    : undefined;

  // One stable callback for the whole grid (ItemCard hands back the id), so memoised cards
  // don't all re-render whenever this screen does.
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const openItemSheet = useCallback((id: string) => {
    const item = itemsRef.current.find((i) => i.item_id === id);
    if (!item) return;
    Haptics.selectionAsync().catch(() => {});
    setActiveItem(item);
    setSheetVisible(true);
  }, []);

  const renderItem = useCallback(({ item, index }: { item: WardrobeItem; index: number }) => (
    <ItemCard
      id={item.item_id}
      uri={item.image_path}
      title={item.subcategory ?? item.category}
      color={item.primary_color}
      width={itemWidth}
      dark={dark}
      index={index}
      onPress={openItemSheet}
      onLongPress={openItemSheet}
    />
  ), [itemWidth, dark, openItemSheet]);

  const renderLook = useCallback(({ item: look }: { item: Look }) => (
    <LookTile
      look={look}
      width={lookWidth}
      ink={ink}
      onOpen={setOpenLook}
      onDelete={confirmDeleteLook}
    />
  ), [lookWidth, ink, confirmDeleteLook]);

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: dark ? Brand.night : Brand.ivory }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: ink }]} accessibilityRole="header">Closet</Text>
        <Text style={[styles.subtitle, { color: muted }]}>
          {items.length} {items.length === 1 ? 'piece' : 'pieces'} · {looks.length} {looks.length === 1 ? 'look' : 'looks'}
        </Text>
      </View>

      <View style={styles.segmentWrap}>
        <Segmented value={tab} onChange={setTab} dark={dark} />
      </View>

      {/* Both tabs stay mounted (the idle one is just hidden) so each keeps its scroll position. */}
      <View style={[styles.pane, tab !== 'closet' && styles.hidden]}>
        {itemsLoading ? (
          <SkeletonGrid cardWidth={itemWidth} dark={dark} />
        ) : itemsError && items.length === 0 ? (
          <EmptyState
            icon="cloud-offline-outline"
            title="Can’t reach your closet"
            body="Check your connection and try again."
            dark={dark}
            actionLabel="Try again"
            onAction={() => loadItems(true)}
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon="shirt-outline"
            title="Your closet is empty"
            body="Tap + to photograph your first piece. We’ll turn it into a clean studio shot."
            dark={dark}
          />
        ) : (
          <>
            <View>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.chipRow}
              >
                {chips.map((c) => (
                  <Chip key={c.key} label={c.label} active={filter === c.key} dark={dark} onPress={() => setFilter(c.key)} />
                ))}
              </ScrollView>
            </View>
            <FlatList
              data={visible}
              keyExtractor={(i) => i.item_id}
              renderItem={renderItem}
              numColumns={3}
              columnWrapperStyle={styles.gridRow}
              contentContainerStyle={styles.grid}
              showsVerticalScrollIndicator={false}
              initialNumToRender={5}
              windowSize={7}
              refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={muted} />}
            />
          </>
        )}
      </View>

      <View style={[styles.pane, tab !== 'looks' && styles.hidden]}>
        {looksLoading ? (
          <ActivityIndicator style={styles.loading} color={muted} />
        ) : looks.length === 0 ? (
          <EmptyState
            icon="heart-outline"
            title="No saved looks yet"
            body="Ask the stylist for an outfit and tap the heart to keep it here."
            dark={dark}
          />
        ) : (
          <FlatList
            data={looks}
            keyExtractor={(l) => l.look_id}
            numColumns={2}
            columnWrapperStyle={styles.gridRow}
            contentContainerStyle={styles.grid}
            showsVerticalScrollIndicator={false}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={muted} />}
            renderItem={renderLook}
          />
        )}
      </View>

      {upgradingId !== null && (
        <View style={styles.busy} accessibilityLiveRegion="polite" accessibilityLabel="Creating your studio shot">
          <ActivityIndicator color="#FFFFFF" size="large" />
          <Text style={styles.busyText}>Creating your studio shot…</Text>
        </View>
      )}
      <ActionSheetModal
        visible={sheetVisible}
        title={sheetTitle}
        actions={actions}
        onClose={() => setSheetVisible(false)}
      />
      <LookDetail
        key={openLook?.look_id ?? 'none'}
        look={openLook}
        userId={uid}
        dark={dark}
        onClose={() => setOpenLook(null)}
        onDelete={confirmDeleteLook}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  pane: { flex: 1 },
  hidden: { display: 'none' },
  busy: {
    ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center',
    justifyContent: 'center', gap: 14, zIndex: 50,
  },
  busyText: { color: '#FFFFFF', fontSize: 15, fontWeight: '600' },
  header: { paddingHorizontal: SIDE, paddingTop: 12 },
  title: { fontSize: 34, fontWeight: '800', letterSpacing: -0.9 },
  subtitle: { fontSize: 13, fontWeight: '500', marginTop: 2 },
  segmentWrap: { paddingHorizontal: SIDE, paddingTop: 16, paddingBottom: 14 },
  segTrack: { flexDirection: 'row', borderRadius: 14, padding: 3 },
  segItem: { flex: 1, alignItems: 'center', justifyContent: 'center', height: 40, borderRadius: 11 },
  segText: { fontSize: 14, fontWeight: '700' },
  chipRow: { paddingHorizontal: SIDE, gap: 8, paddingBottom: 14 },
  chip: {
    height: 34, paddingHorizontal: 14, borderRadius: 17, borderWidth: 1,
    alignItems: 'center', justifyContent: 'center',
  },
  chipText: { fontSize: 13, fontWeight: '600' },
  grid: { paddingBottom: 126 },
  gridRow: { gap: GAP, paddingHorizontal: SIDE, marginBottom: 14 },
  skeletonWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: GAP, paddingHorizontal: SIDE, rowGap: 24 },
  loading: { marginTop: 60 },
  lookName: { marginTop: 8, paddingHorizontal: 4, fontSize: 13, fontWeight: '600' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 40, paddingBottom: 120 },
  emptyIcon: { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center', marginBottom: 18 },
  emptyTitle: { fontSize: 20, fontWeight: '700', letterSpacing: -0.3, marginBottom: 6 },
  emptyBody: { fontSize: 14, lineHeight: 20, textAlign: 'center' },
  emptyAction: { marginTop: 20, height: 46, paddingHorizontal: 28, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  scrim: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.5)' },
  detailWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  detailCard: { borderRadius: 32, padding: 16, gap: 12, alignItems: 'center' },
  detailHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', alignSelf: 'stretch', paddingHorizontal: 4 },
  detailTitle: { flex: 1, fontSize: 18, fontWeight: '700', letterSpacing: -0.2, marginRight: 12 },
  detailCaption: { fontSize: 13, lineHeight: 18, textTransform: 'capitalize', textAlign: 'center', alignSelf: 'stretch' },
  detailActions: { flexDirection: 'row', alignItems: 'center', gap: 10, alignSelf: 'stretch' },
  primary: { flex: 1, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  primaryText: { fontSize: 14, fontWeight: '700' },
  iconButton: { width: 46, height: 46, borderRadius: 23, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
});
