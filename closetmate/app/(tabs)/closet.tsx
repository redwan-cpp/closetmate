import React, { useState, useCallback, useRef, memo } from 'react';
import {
  StyleSheet,
  View,
  SafeAreaView,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  Animated,
  Dimensions,
  Text,
  Pressable,
  Alert,
  Vibration,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Colors, Spacing, BorderRadius } from '@/constants/theme';
import { getWardrobeItems, deleteWardrobeItem, WardrobeItem } from '@/src/api/ai';
import ActionSheetModal from '@/components/ActionSheetModal';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const { width } = Dimensions.get('window');
const H_PAD = 20;
const GAP = 14;
const CARD_W = (width - H_PAD * 2 - GAP) / 2;
const CARD_H = CARD_W * 1.35;
const DEMO_USER_ID = 'demo_user';

const CATEGORIES = [
  { key: 'top',         label: 'Tops',        icon: 'shirt-outline' as const },
  { key: 'bottom',      label: 'Bottoms',     icon: 'filter-outline' as const },
  { key: 'dress',       label: 'Dresses',     icon: 'body-outline' as const },
  { key: 'traditional', label: 'Traditional', icon: 'sparkles-outline' as const },
  { key: 'outerwear',   label: 'Outerwear',   icon: 'umbrella-outline' as const },
  { key: 'footwear',    label: 'Footwear',    icon: 'footsteps-outline' as const },
  { key: 'accessory',   label: 'Accessories', icon: 'watch-outline' as const },
];

// ---------------------------------------------------------------------------
// Colour-dot helper
// ---------------------------------------------------------------------------
const COLOR_MAP: Record<string, string> = {
  red: '#E53935', coral: '#FF7043', orange: '#FB8C00', mustard: '#F9A825',
  yellow: '#FDD835', green: '#43A047', olive: '#827717', teal: '#00897B',
  blue: '#1E88E5', navy: '#1A237E', purple: '#8E24AA', lavender: '#9575CD',
  pink: '#F06292', white: '#F5F5F5', black: '#212121', gray: '#757575',
  grey: '#757575', brown: '#6D4C41', beige: '#D7CCC8', cream: '#FFF8E1',
  charcoal: '#37474F',
};
function resolveColorDot(c: string | null) {
  if (!c) return null;
  const l = c.toLowerCase();
  for (const k of Object.keys(COLOR_MAP)) if (l.includes(k)) return COLOR_MAP[k];
  return null;
}

// ---------------------------------------------------------------------------
// CategoryCard
// ---------------------------------------------------------------------------
interface CategoryCardProps {
  label: string;
  icon: React.ComponentProps<typeof Ionicons>['name'];
  count: number;
  previewUri: string | null;
  isDark: boolean;
  onPress: () => void;
}

const CategoryCard = memo(({ label, icon, count, previewUri, isDark, onPress }: CategoryCardProps) => {
  const scale = useRef(new Animated.Value(1)).current;
  const imgOpacity = useRef(new Animated.Value(0)).current;

  const onPressIn = () => Animated.spring(scale, { toValue: 0.96, useNativeDriver: true, speed: 30 }).start();
  const onPressOut = () => Animated.spring(scale, { toValue: 1, useNativeDriver: true, speed: 20 }).start();
  const onLoad = () => Animated.timing(imgOpacity, { toValue: 1, duration: 300, useNativeDriver: true }).start();

  const ok = !!previewUri && (
    previewUri.startsWith('data:') || previewUri.startsWith('file:') || previewUri.startsWith('http')
  );

  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <Pressable
        onPressIn={onPressIn} onPressOut={onPressOut} onPress={onPress}
        style={[styles.card, { backgroundColor: isDark ? '#1A1A1A' : '#FFF', width: CARD_W, height: CARD_H, shadowColor: isDark ? '#000' : '#AAA' }]}
      >
        {ok ? (
          <Animated.Image source={{ uri: previewUri! }} style={[StyleSheet.absoluteFillObject, styles.cardImage, { opacity: imgOpacity }]} resizeMode="cover" onLoad={onLoad} />
        ) : (
          <View style={[StyleSheet.absoluteFillObject, styles.cardPlaceholder, { backgroundColor: isDark ? '#252525' : '#F5F5F5' }]}>
            <Ionicons name={icon} size={40} color={isDark ? '#3A3A3A' : '#DCDCDC'} />
          </View>
        )}
        <View style={styles.labelRow}>
          <Text style={styles.labelTitle}>{label}</Text>
          <Text style={styles.labelCount}>{count} item{count !== 1 ? 's' : ''}</Text>
        </View>
      </Pressable>
    </Animated.View>
  );
});

// ---------------------------------------------------------------------------
// DetailCard — with long-press
// ---------------------------------------------------------------------------
interface DetailCardProps {
  item: WardrobeItem;
  isDark: boolean;
  onLongPress: (item: WardrobeItem) => void;
}

const DetailCard = memo(({ item, isDark, onLongPress }: DetailCardProps) => {
  const scale = useRef(new Animated.Value(1)).current;
  const opacity = useRef(new Animated.Value(0)).current;

  const uri = item.image_path ?? '';
  const ok = uri.startsWith('data:') || uri.startsWith('file:') || uri.startsWith('http');
  const colorDot = resolveColorDot(item.primary_color);

  const onPressIn = () => Animated.spring(scale, { toValue: 0.96, useNativeDriver: true, speed: 30 }).start();
  const onPressOut = () => Animated.spring(scale, { toValue: 1, useNativeDriver: true, speed: 20 }).start();

  const handleLongPress = () => {
    Vibration.vibrate(40); // subtle haptic pulse
    onLongPress(item);
  };

  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <Pressable
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        onLongPress={handleLongPress}
        delayLongPress={380}
        style={[styles.card, {
          backgroundColor: isDark ? '#1A1A1A' : '#FFF',
          width: CARD_W, height: CARD_H,
          shadowColor: isDark ? '#000' : '#AAA',
        }]}
      >
        {ok ? (
          <Animated.Image
            source={{ uri }}
            style={[styles.cardImage, { opacity }]}
            resizeMode="cover"
            onLoad={() => Animated.timing(opacity, { toValue: 1, duration: 280, useNativeDriver: true }).start()}
          />
        ) : (
          <View style={[styles.cardPlaceholder, { backgroundColor: isDark ? '#252525' : '#F5F5F5' }]}>
            <Ionicons name="shirt-outline" size={36} color={isDark ? '#3A3A3A' : '#DDD'} />
          </View>
        )}

        {/* Category badge */}
        {!!(item.subcategory ?? item.category) && (
          <View style={styles.labelBadge}>
            <Text style={styles.labelText} numberOfLines={1}>
              {item.subcategory ?? item.category}
            </Text>
          </View>
        )}

        {/* Colour dot */}
        {!!colorDot && <View style={[styles.colorDot, { backgroundColor: colorDot }]} />}
      </Pressable>
    </Animated.View>
  );
});

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------
export default function ClosetScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const theme = colorScheme ?? 'light';
  const C = Colors[theme];
  const router = useRouter();

  const [items, setItems] = useState<WardrobeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  // Action sheet state
  const [activeItem, setActiveItem] = useState<WardrobeItem | null>(null);
  const [sheetVisible, setSheetVisible] = useState(false);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      setLoading(true);
      setError(null);
      getWardrobeItems(DEMO_USER_ID)
        .then((data) => { if (active) setItems(data); })
        .catch(() => { if (active) setError('Could not load wardrobe. Is the backend running?'); })
        .finally(() => { if (active) setLoading(false); });
      return () => { active = false; };
    }, [])
  );

  // ── Long-press handler ────────────────────────────────────────────────────
  const handleLongPress = useCallback((item: WardrobeItem) => {
    setActiveItem(item);
    setSheetVisible(true);
  }, []);

  const closeSheet = useCallback(() => {
    setSheetVisible(false);
  }, []);

  // ── Delete ────────────────────────────────────────────────────────────────
  const handleDelete = useCallback(async () => {
    if (!activeItem) return;
    const id = activeItem.item_id;
    // Optimistic remove
    setItems((prev) => prev.filter((i) => i.item_id !== id));
    try {
      await deleteWardrobeItem(id);
    } catch (e) {
      // Revert on failure
      setItems((prev) => [activeItem, ...prev]);
      Alert.alert('Delete failed', e instanceof Error ? e.message : String(e));
    }
  }, [activeItem]);

  // ── Edit (navigate to add-item with pre-filled data) ──────────────────────
  const handleEdit = useCallback(() => {
    if (!activeItem) return;
    router.push({
      pathname: '/add-item',
      params: {
        editMode: '1',
        item_id: activeItem.item_id,
        imageUri: activeItem.image_path ?? '',
        category: activeItem.category ?? '',
        subcategory: activeItem.subcategory ?? '',
        primary_color: activeItem.primary_color ?? '',
        material: activeItem.material ?? '',
        pattern: activeItem.pattern ?? '',
        formality: activeItem.formality_level ?? '',
      },
    });
  }, [activeItem, router]);

  // ── Actions array ─────────────────────────────────────────────────────────
  const actions = [
    { label: 'Edit Item', onPress: handleEdit },
    { label: 'Delete Item', onPress: handleDelete, destructive: true },
    { label: 'Cancel', onPress: closeSheet },
  ];

  // ── Category sections ─────────────────────────────────────────────────────
  const categorySections = CATEGORIES.map((cat) => {
    const matched = items.filter((i) => (i.category ?? '').toLowerCase() === cat.key);
    return { ...cat, count: matched.length, previewUri: matched[0]?.image_path ?? null };
  }).filter((c) => c.count > 0);

  const knownKeys = new Set(CATEGORIES.map((c) => c.key));
  const otherItems = items.filter((i) => !knownKeys.has((i.category ?? '').toLowerCase()));
  if (otherItems.length > 0) {
    categorySections.push({
      key: 'other', label: 'Other', icon: 'grid-outline' as const,
      count: otherItems.length, previewUri: otherItems[0]?.image_path ?? null,
    });
  }

  const detailItems = selectedCategory
    ? items.filter((i) => (i.category ?? '').toLowerCase() === selectedCategory)
    : [];

  // Group into row pairs
  function toPairs<T>(arr: T[]): T[][] {
    const result: T[][] = [];
    for (let i = 0; i < arr.length; i += 2) result.push(arr.slice(i, i + 2));
    return result;
  }

  const selectedLabel = CATEGORIES.find((c) => c.key === selectedCategory)?.label ?? 'Other';
  const activeItemLabel = activeItem
    ? [activeItem.subcategory, activeItem.category].filter(Boolean).join(' · ')
    : undefined;

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: C.background }]}>
      {/* ── Header ── */}
      <View style={styles.header}>
        {selectedCategory ? (
          <TouchableOpacity onPress={() => setSelectedCategory(null)} style={styles.backRow}>
            <Ionicons name="chevron-back" size={22} color={C.text} />
            <Text style={[styles.headerTitle, { color: C.text }]}>{selectedLabel}</Text>
          </TouchableOpacity>
        ) : (
          <Text style={[styles.headerTitle, { color: C.text }]}>My Closet</Text>
        )}
        <Text style={[styles.headerCount, { color: C.textSecondary }]}>
          {items.length} item{items.length !== 1 ? 's' : ''}
        </Text>
      </View>

      {/* ── Body ── */}
      {loading ? (
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={C.tint} />
          <Text style={[styles.stateText, { color: C.textSecondary }]}>Loading…</Text>
        </View>
      ) : error ? (
        <View style={styles.centered}>
          <Ionicons name="cloud-offline-outline" size={52} color={isDark ? '#444' : '#DDD'} />
          <Text style={[styles.stateText, { color: C.textSecondary }]}>{error}</Text>
        </View>
      ) : items.length === 0 ? (
        <View style={styles.centered}>
          <Ionicons name="shirt-outline" size={72} color={isDark ? '#2A2A2A' : '#E8E8E8'} />
          <Text style={[styles.emptyTitle, { color: C.text }]}>No items yet</Text>
          <Text style={[styles.stateText, { color: C.textSecondary }]}>Tap + to add your first piece</Text>
        </View>
      ) : selectedCategory ? (
        /* ── Detail grid ── */
        <FlatList
          data={toPairs(detailItems)}
          keyExtractor={(_, i) => `row-${i}`}
          contentContainerStyle={styles.grid}
          showsVerticalScrollIndicator={false}
          renderItem={({ item: row }) => (
            <View style={styles.row}>
              {row.map((item) => (
                <DetailCard key={item.item_id} item={item} isDark={isDark} onLongPress={handleLongPress} />
              ))}
              {row.length === 1 && <View style={{ width: CARD_W }} />}
            </View>
          )}
        />
      ) : (
        /* ── Category overview ── */
        <FlatList
          data={toPairs(categorySections)}
          keyExtractor={(_, i) => `cat-row-${i}`}
          contentContainerStyle={styles.grid}
          showsVerticalScrollIndicator={false}
          renderItem={({ item: pair }) => (
            <View style={styles.row}>
              {pair.map((cat) => (
                <CategoryCard
                  key={cat.key}
                  label={cat.label}
                  icon={cat.icon}
                  count={cat.count}
                  previewUri={cat.previewUri}
                  isDark={isDark}
                  onPress={() => setSelectedCategory(cat.key)}
                />
              ))}
              {pair.length === 1 && <View style={{ width: CARD_W }} />}
            </View>
          )}
        />
      )}

      {/* ── Action sheet ── */}
      <ActionSheetModal
        visible={sheetVisible}
        title={activeItemLabel}
        actions={actions}
        onClose={closeSheet}
      />
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const styles = StyleSheet.create({
  safe: { flex: 1 },
  header: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: H_PAD, paddingTop: Spacing.l, paddingBottom: Spacing.m,
  },
  headerTitle: { fontSize: 28, fontWeight: '700', letterSpacing: -0.5 },
  headerCount: { fontSize: 13 },
  backRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  grid: { paddingHorizontal: H_PAD, paddingBottom: 120, gap: GAP },
  row: { flexDirection: 'row', justifyContent: 'space-between' },
  card: {
    borderRadius: 20, overflow: 'hidden',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.09, shadowRadius: 14, elevation: 4,
  },
  cardImage: { width: '100%', height: '100%' },
  cardPlaceholder: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  labelRow: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    paddingHorizontal: 14, paddingVertical: 14,
    backgroundColor: 'rgba(0,0,0,0.45)', gap: 2,
  },
  labelTitle: { fontSize: 15, fontWeight: '700', color: '#FFF', letterSpacing: 0.1 },
  labelCount: { fontSize: 12, color: 'rgba(255,255,255,0.75)' },
  labelBadge: {
    position: 'absolute', top: 10, left: 10,
    backgroundColor: 'rgba(0,0,0,0.40)',
    borderRadius: 20, paddingHorizontal: 9, paddingVertical: 3,
  },
  labelText: { fontSize: 11, fontWeight: '600', color: '#FFF', textTransform: 'capitalize' },
  colorDot: {
    position: 'absolute', bottom: 10, right: 10,
    width: 12, height: 12, borderRadius: 6,
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.6)',
  },
  centered: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: 12, paddingBottom: 80 },
  emptyTitle: { fontSize: 18, fontWeight: '600', letterSpacing: -0.2 },
  stateText: { fontSize: 14, textAlign: 'center', paddingHorizontal: 40, lineHeight: 20 },
});
