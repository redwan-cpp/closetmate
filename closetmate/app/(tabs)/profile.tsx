/**
 * app/(tabs)/profile.tsx
 * ClosetMate — User Profile
 * Shows: avatar (uploadable), name, body shape, skin tone, worn history
 * All data pulled from the backend using the logged-in user_id.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  StyleSheet, View, Text, ScrollView, TouchableOpacity,
  useColorScheme, ActivityIndicator, Alert, Image,
  Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { useAuth } from '@/src/context/AuthContext';
import { AI_BASE_URL } from '@/src/api/ai';
import { useRouter } from 'expo-router';

const { width } = Dimensions.get('window');

// ── Skin tone display map ─────────────────────
const SKIN_TONE_MAP: Record<string, { color: string; label: string }> = {
  fair:         { color: '#FDDBB4', label: 'Fair' },
  light:        { color: '#F5C5A3', label: 'Light' },
  light_medium: { color: '#E8A87C', label: 'Light Medium' },
  medium:       { color: '#C68642', label: 'Medium' },
  medium_dark:  { color: '#A0522D', label: 'Medium Dark' },
  dark:         { color: '#6B3A2A', label: 'Dark' },
  deep:         { color: '#3B1A0A', label: 'Deep' },
  warm:         { color: '#D2905A', label: 'Warm' },
  cool:         { color: '#C4A882', label: 'Cool' },
  neutral:      { color: '#C8956C', label: 'Neutral' },
};

// ── Body shape display map ────────────────────
const BODY_SHAPE_MAP: Record<string, { emoji: string; label: string; tip: string }> = {
  hourglass:        { emoji: '⌛', label: 'Hourglass',         tip: 'Wrap dresses, fitted tops, belted styles' },
  pear:             { emoji: '🍐', label: 'Pear / Triangle',   tip: 'A-line skirts, boat necks, wide sleeves' },
  apple:            { emoji: '🍎', label: 'Apple / Round',     tip: 'V-necks, empire waist, flowy fabrics' },
  rectangle:        { emoji: '▬', label: 'Rectangle',          tip: 'Ruffles, peplums, layered looks' },
  inverted_triangle:{ emoji: '🔺', label: 'Inverted Triangle', tip: 'Wide-leg pants, A-line skirts, low-rise' },
  oval:             { emoji: '💎', label: 'Oval / Diamond',    tip: 'Straight lines, monochrome, longline layers' },
  athletic:         { emoji: '🏋️', label: 'Athletic',          tip: 'Structured blazers, fitted trousers' },
  petite:           { emoji: '🌸', label: 'Petite',            tip: 'High-waist cuts, vertical patterns, heels' },
  tall:             { emoji: '📏', label: 'Tall / Lean',        tip: 'Bold patterns, layering, statement pieces' },
  curvy:            { emoji: '🌊', label: 'Curvy / Plus',      tip: 'Wrap styles, defined waist, quality fabrics' },
};

// ── Days of week ──────────────────────────────
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

interface UserProfile {
  user_id: string;
  name: string;
  email: string;
  gender: string;
  body_shape: string | null;
  skin_tone: string | null;
  style_preference: string | null;
  created_at: string;
}

interface WardrobeItem {
  item_id: string;
  image_path: string | null;
  category: string | null;
  created_at: string;
}

export default function ProfileScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;
  const router = useRouter();
  const { user_id, token, signOut } = useAuth();

  const [profile, setProfile]       = useState<UserProfile | null>(null);
  const [wardrobe, setWardrobe]      = useState<WardrobeItem[]>([]);
  const [avatarUri, setAvatarUri]    = useState<string | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [loadingWardrobe, setLoadingWardrobe] = useState(true);

  // ── Fetch profile ──
  const fetchProfile = useCallback(async () => {
    if (!token) {
      setLoadingProfile(false);
      return;
    }
    try {
      const res = await fetch(`${AI_BASE_URL}/auth/profile`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: UserProfile = await res.json();
      setProfile(data);
    } catch (e) {
      console.warn('Profile fetch error:', e);
    } finally {
      setLoadingProfile(false);
    }
  }, [token]);

  // ── Fetch wardrobe for recent history ──
  const fetchWardrobe = useCallback(async () => {
    if (!user_id) {
      setLoadingWardrobe(false);
      return;
    }
    try {
      const res = await fetch(`${AI_BASE_URL}/wardrobe/items/${user_id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: WardrobeItem[] = await res.json();
      setWardrobe(data);
    } catch (e) {
      console.warn('Wardrobe fetch error:', e);
    } finally {
      setLoadingWardrobe(false);
    }
  }, [user_id]);

  useEffect(() => {
    fetchProfile();
    fetchWardrobe();
  }, [fetchProfile, fetchWardrobe]);

  // ── Avatar pick ──
  const pickAvatar = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('Permission needed', 'Allow photo library access to change your avatar.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });
    if (!result.canceled && result.assets[0]) {
      setAvatarUri(result.assets[0].uri);
    }
  };

  // ── Sign out ──
  const handleSignOut = () => {
    Alert.alert('Sign out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign out', style: 'destructive',
        onPress: async () => {
          await signOut();
          router.replace('/login');
        },
      },
    ]);
  };

  const skinInfo  = profile?.skin_tone  ? SKIN_TONE_MAP[profile.skin_tone]   : null;
  const shapeInfo = profile?.body_shape ? BODY_SHAPE_MAP[profile.body_shape] : null;

  // ── Recent 7 items as "worn history" slots ──
  const historySlots = Array.from({ length: 7 }, (_, i) => ({
    day: DAYS[i],
    item: wardrobe[i] ?? null,
  }));

  if (loadingProfile) {
    return (
      <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={c.text} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >

        {/* ── Header ── */}
        <View style={styles.headerRow}>
          <Text style={[styles.screenTitle, { color: c.text }]}>Profile</Text>
          <TouchableOpacity onPress={handleSignOut} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
            <Ionicons name="log-out-outline" size={22} color={c.subtext} />
          </TouchableOpacity>
        </View>

        {/* ── Avatar + Name ── */}
        <View style={styles.avatarSection}>
          <TouchableOpacity onPress={pickAvatar} activeOpacity={0.8} style={styles.avatarWrap}>
            {avatarUri ? (
              <Image source={{ uri: avatarUri }} style={styles.avatar} />
            ) : (
              <View style={[styles.avatarPlaceholder, { backgroundColor: c.surface, borderColor: c.border }]}>
                <Ionicons name="person" size={42} color={c.subtext} />
              </View>
            )}
            <View style={[styles.avatarEditBadge, { backgroundColor: c.text }]}>
              <Ionicons name="camera" size={12} color={c.bg} />
            </View>
          </TouchableOpacity>

          <Text style={[styles.profileName, { color: c.text }]}>{profile?.name ?? '—'}</Text>
          <Text style={[styles.profileEmail, { color: c.subtext }]}>{profile?.email ?? ''}</Text>
          {profile?.gender ? (
            <View style={[styles.genderBadge, { backgroundColor: c.surface, borderColor: c.border }]}>
              <Text style={[styles.genderBadgeText, { color: c.subtext }]}>{profile.gender}</Text>
            </View>
          ) : null}
        </View>

        {/* ── Body Shape ── */}
        <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={styles.cardHeader}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Body Shape</Text>
          </View>
          {shapeInfo ? (
            <View style={styles.shapeRow}>
              <View style={[styles.shapeIconBox, { backgroundColor: c.bg, borderColor: c.border }]}>
                <Text style={styles.shapeEmoji}>{shapeInfo.emoji}</Text>
              </View>
              <View style={styles.shapeInfo}>
                <Text style={[styles.shapeLabel, { color: c.text }]}>{shapeInfo.label}</Text>
                <Text style={[styles.shapeTip, { color: c.subtext }]}>{shapeInfo.tip}</Text>
              </View>
            </View>
          ) : (
            <EmptyState
              icon="body-outline"
              message="No body shape set yet."
              subMessage="Update it in your settings to get better outfit recommendations."
              c={c}
            />
          )}
        </View>

        {/* ── Skin Tone ── */}
        <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={styles.cardHeader}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Skin Tone</Text>
          </View>
          {skinInfo ? (
            <View style={styles.skinRow}>
              <View style={[styles.skinSwatchLarge, { backgroundColor: skinInfo.color }]} />
              <View>
                <Text style={[styles.skinLabel, { color: c.text }]}>{skinInfo.label}</Text>
                <Text style={[styles.skinSub, { color: c.subtext }]}>Used to suggest complementary colors</Text>
              </View>
            </View>
          ) : (
            <EmptyState
              icon="color-palette-outline"
              message="No skin tone set yet."
              subMessage="Add it during registration or update it in your settings."
              c={c}
            />
          )}
        </View>

        {/* ── Worn History ── */}
        <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={styles.cardHeader}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Wardrobe History</Text>
            <Text style={[styles.cardMeta, { color: c.subtext }]}>{wardrobe.length} item{wardrobe.length !== 1 ? 's' : ''}</Text>
          </View>

          {loadingWardrobe ? (
            <ActivityIndicator color={c.subtext} style={{ marginVertical: 20 }} />
          ) : wardrobe.length === 0 ? (
            <EmptyState
              icon="shirt-outline"
              message="Your wardrobe is empty."
              subMessage="Add your first clothing item using the camera button below."
              c={c}
            />
          ) : (
            <View style={styles.historyRow}>
              {historySlots.map(({ day, item }, i) => {
                const imgUrl = item?.image_path
                  ? `${AI_BASE_URL}/${item.image_path}`
                  : null;
                return (
                  <View key={i} style={styles.historyColumn}>
                    <Text style={[styles.historyDay, { color: c.subtext }]}>{day}</Text>
                    <View style={[styles.historyCell, { backgroundColor: c.bg, borderColor: c.border }]}>
                      {imgUrl ? (
                        <Image source={{ uri: imgUrl }} style={styles.historyImage} resizeMode="cover" />
                      ) : (
                        <Ionicons name="shirt-outline" size={16} color={c.border} />
                      )}
                    </View>
                  </View>
                );
              })}
            </View>
          )}
        </View>

        {/* ── Style Insights ── */}
        <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={[styles.cardHeader, { marginBottom: 10 }]}>
            <Ionicons name="sparkles" size={16} color={c.text} />
            <Text style={[styles.cardTitle, { color: c.text, marginLeft: 8 }]}>Style Insights</Text>
          </View>
          {profile && (shapeInfo || skinInfo) ? (
            <Text style={[styles.insightText, { color: c.subtext }]}>
              {shapeInfo && skinInfo
                ? `Your ${shapeInfo.label} shape and ${skinInfo.label} skin tone work beautifully together. Focus on ${shapeInfo.tip.toLowerCase()} in tones that complement your complexion.`
                : shapeInfo
                  ? `With a ${shapeInfo.label} shape, you'll look great in: ${shapeInfo.tip.toLowerCase()}.`
                  : `Your ${skinInfo!.label} skin tone pairs well with earth tones and complementary shades.`
              }
            </Text>
          ) : (
            <EmptyState
              icon="bulb-outline"
              message="No style insights yet."
              subMessage="Complete your profile with body shape and skin tone to get personalized AI insights."
              c={c}
            />
          )}
        </View>

        <View style={{ height: 120 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Empty state component ─────────────────────

function EmptyState({ icon, message, subMessage, c }: {
  icon: string; message: string; subMessage: string;
  c: typeof light;
}) {
  return (
    <View style={emptyStyles.wrap}>
      <Ionicons name={icon as any} size={32} color={c.border} />
      <Text style={[emptyStyles.msg, { color: c.subtext }]}>{message}</Text>
      <Text style={[emptyStyles.sub, { color: c.border }]}>{subMessage}</Text>
    </View>
  );
}

const emptyStyles = StyleSheet.create({
  wrap: { alignItems: 'center', paddingVertical: 20, gap: 8 },
  msg:  { fontSize: 14, fontWeight: '600', textAlign: 'center' },
  sub:  { fontSize: 12, textAlign: 'center', lineHeight: 18 },
});

// ── Palette ───────────────────────────────────

const light = {
  bg: '#FFFFFF', surface: '#F8F8F8', text: '#1A1A1A', subtext: '#666666',
  border: '#E5E5E5',
};
const dark = {
  bg: '#000000', surface: '#121212', text: '#FFFFFF', subtext: '#A0A0A0',
  border: '#333333',
};

// ── Styles ────────────────────────────────────

const SLOT_SIZE = (width - 24 * 2 - 6 * 8) / 7;

const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { flex: 1 },
  scrollContent: { paddingHorizontal: 24, paddingTop: 16 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },

  headerRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    marginBottom: 28,
  },
  screenTitle: { fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },

  avatarSection: { alignItems: 'center', marginBottom: 32 },
  avatarWrap: { marginBottom: 14, position: 'relative' },
  avatar: { width: 96, height: 96, borderRadius: 48 },
  avatarPlaceholder: {
    width: 96, height: 96, borderRadius: 48,
    justifyContent: 'center', alignItems: 'center', borderWidth: 1,
  },
  avatarEditBadge: {
    position: 'absolute', bottom: 2, right: 2,
    width: 28, height: 28, borderRadius: 14,
    justifyContent: 'center', alignItems: 'center',
  },
  profileName:  { fontSize: 22, fontWeight: '800', letterSpacing: -0.3, marginBottom: 4 },
  profileEmail: { fontSize: 14, marginBottom: 10 },
  genderBadge:  { borderRadius: 20, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 5 },
  genderBadgeText: { fontSize: 13, fontWeight: '600' },

  card: {
    borderRadius: 18, padding: 18, borderWidth: 1, marginBottom: 16,
  },
  cardHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14,
  },
  cardTitle: { fontSize: 16, fontWeight: '700' },
  cardMeta:  { fontSize: 13 },

  shapeRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  shapeIconBox: {
    width: 60, height: 60, borderRadius: 16,
    justifyContent: 'center', alignItems: 'center', borderWidth: 1,
  },
  shapeEmoji: { fontSize: 28 },
  shapeInfo:  { flex: 1 },
  shapeLabel: { fontSize: 16, fontWeight: '700', marginBottom: 4 },
  shapeTip:   { fontSize: 13, lineHeight: 18 },

  skinRow: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  skinSwatchLarge: { width: 52, height: 52, borderRadius: 26 },
  skinLabel: { fontSize: 16, fontWeight: '700', marginBottom: 4 },
  skinSub:   { fontSize: 13 },

  historyRow: { flexDirection: 'row', justifyContent: 'space-between' },
  historyColumn: { alignItems: 'center', flex: 1, marginHorizontal: 2 },
  historyDay:  { fontSize: 10, fontWeight: '600', marginBottom: 6 },
  historyCell: {
    width: SLOT_SIZE, height: SLOT_SIZE, borderRadius: 8,
    overflow: 'hidden', justifyContent: 'center', alignItems: 'center', borderWidth: 1,
  },
  historyImage: { width: '100%', height: '100%' },

  insightText: { fontSize: 14, lineHeight: 22 },
});
