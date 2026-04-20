/**
 * app/register-body.tsx
 * ClosetMate — Registration Step 3/3
 * Body shape selection → final registration call
 */
import React, { useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
  ActivityIndicator, Alert, useColorScheme, StatusBar, Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { registerUser } from '@/src/api/auth';
import { loginUser } from '@/src/api/auth';
import { useAuth } from '@/src/context/AuthContext';

const { width } = Dimensions.get('window');
const CARD_W = (width - 24 * 2 - 12) / 2;

// ─────────────────────────────────────────────
// Body shape definitions
// ─────────────────────────────────────────────

const BODY_SHAPES = [
  {
    id: 'hourglass',
    label: 'Hourglass',
    emoji: '⌛',
    desc: 'Balanced bust & hips, defined waist',
    tips: 'Wrap dresses, fitted tops, belted styles',
    gradient: ['#EC4899', '#BE185D'] as [string, string],
  },
  {
    id: 'pear',
    label: 'Pear / Triangle',
    emoji: '🍐',
    desc: 'Hips wider than shoulders',
    tips: 'A-line skirts, boat necks, wide sleeves',
    gradient: ['#10B981', '#047857'] as [string, string],
  },
  {
    id: 'apple',
    label: 'Apple / Round',
    emoji: '🍎',
    desc: 'Fuller midsection, narrow hips',
    tips: 'V-necks, empire waist, flowy fabrics',
    gradient: ['#EF4444', '#B91C1C'] as [string, string],
  },
  {
    id: 'rectangle',
    label: 'Rectangle',
    emoji: '▬',
    desc: 'Shoulders, waist & hips similar width',
    tips: 'Ruffles, peplums, layered looks',
    gradient: ['#3B82F6', '#1D4ED8'] as [string, string],
  },
  {
    id: 'inverted_triangle',
    label: 'Inverted Triangle',
    emoji: '🔺',
    desc: 'Broad shoulders, narrow hips',
    tips: 'Wide-leg pants, A-line skirts, low-rise',
    gradient: ['#F59E0B', '#B45309'] as [string, string],
  },
  {
    id: 'oval',
    label: 'Oval / Diamond',
    emoji: '💎',
    desc: 'Narrower shoulders and hips, wider mid',
    tips: 'Straight lines, monochrome, longline layers',
    gradient: ['#8B5CF6', '#6D28D9'] as [string, string],
  },
];

export default function RegisterBodyScreen() {
  const router = useRouter();
  const { signIn } = useAuth();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;

  const params = useLocalSearchParams<{
    name: string; email: string; password: string; gender: string; skin_tone: string;
  }>();

  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  const handleFinish = async () => {
    if (!selected) {
      Alert.alert('Required', 'Please select your body shape, or tap Skip.');
      return;
    }
    await submit(selected);
  };

  const handleSkip = () => submit(null);

  const submit = async (bodyShape: string | null) => {
    setLoading(true);
    try {
      // Register
      await registerUser({
        name: params.name,
        email: params.email,
        password: params.password,
        gender: params.gender,
        skin_tone: params.skin_tone || undefined,
        body_shape: bodyShape ?? undefined,
      });

      // Auto-login after registration
      const { token, user_id } = await loginUser({ email: params.email, password: params.password });
      await signIn(token, user_id);

      router.replace('/(tabs)/stylist');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      Alert.alert('Registration failed', msg);
    } finally {
      setLoading(false);
    }
  };

  const selectedShape = BODY_SHAPES.find((s) => s.id === selected);

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} />

      {/* ── Top bar ── */}
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
          <Ionicons name="arrow-back" size={24} color={c.text} />
        </TouchableOpacity>
        <View style={styles.progressRow}>
          {[1, 2, 3].map((s) => (
            <View key={s} style={[styles.progressDot, { backgroundColor: '#7C3AED' }]} />
          ))}
        </View>
        <TouchableOpacity onPress={handleSkip} disabled={loading}>
          <Text style={[styles.skipText, { color: c.subtext }]}>Skip</Text>
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        {/* ── Header ── */}
        <View style={styles.header}>
          <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.stepBadge}>
            <Text style={styles.stepBadgeText}>3</Text>
          </LinearGradient>
          <Text style={[styles.title, { color: c.text }]}>Body Shape</Text>
          <Text style={[styles.sub, { color: c.subtext }]}>
            This helps us recommend outfits that flatter YOUR silhouette
          </Text>
        </View>

        {/* ── Grid ── */}
        <View style={styles.grid}>
          {BODY_SHAPES.map((shape) => {
            const isSelected = selected === shape.id;
            return (
              <TouchableOpacity
                key={shape.id}
                onPress={() => setSelected(isSelected ? null : shape.id)}
                activeOpacity={0.8}
                style={[
                  styles.shapeCard,
                  { width: CARD_W, backgroundColor: isSelected ? '#7C3AED12' : c.card, borderColor: isSelected ? '#7C3AED' : c.border },
                ]}
              >
                <LinearGradient
                  colors={isSelected ? shape.gradient : [c.inputBg, c.inputBg]}
                  start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
                  style={styles.shapeEmojiBg}
                >
                  <Text style={styles.shapeEmoji}>{shape.emoji}</Text>
                </LinearGradient>
                <Text style={[styles.shapeLabel, { color: isSelected ? '#7C3AED' : c.text }]}>{shape.label}</Text>
                <Text style={[styles.shapeDesc, { color: c.subtext }]} numberOfLines={2}>{shape.desc}</Text>
                {isSelected && (
                  <View style={styles.checkBadge}>
                    <Ionicons name="checkmark" size={14} color="#FFF" />
                  </View>
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        {/* ── Style tip for selected ── */}
        {selectedShape && (
          <View style={[styles.tipCard, { backgroundColor: c.card, borderColor: '#7C3AED40' }]}>
            <LinearGradient colors={selectedShape.gradient} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.tipBar} />
            <View style={styles.tipContent}>
              <Ionicons name="sparkles" size={16} color="#7C3AED" />
              <Text style={[styles.tipCardText, { color: c.subtext }]}>
                <Text style={{ fontWeight: '700', color: c.text }}>Style tip: </Text>
                {selectedShape.tips}
              </Text>
            </View>
          </View>
        )}

        {/* ── CTA ── */}
        <TouchableOpacity
          onPress={handleFinish}
          disabled={loading || !selected}
          activeOpacity={0.85}
          style={[styles.primaryBtn, { opacity: selected ? 1 : 0.55 }]}
        >
          <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.primaryBtnInner}>
            {loading
              ? <ActivityIndicator color="#FFF" />
              : <>
                  <Text style={styles.primaryBtnText}>Create My Wardrobe</Text>
                  <Ionicons name="checkmark-circle" size={20} color="#FFF" style={{ marginLeft: 8 }} />
                </>
            }
          </LinearGradient>
        </TouchableOpacity>

        <Text style={[styles.footNote, { color: c.subtext }]}>
          You can update your preferences anytime in Profile
        </Text>

      </ScrollView>
    </SafeAreaView>
  );
}

// ── Palette ──────────────────────────────────

const light = {
  bg: '#F5F4FF', card: '#FFFFFF', text: '#1A1A2E', subtext: '#6B7280',
  inputBg: '#F3F4F6', border: '#E5E7EB', icon: '#9CA3AF', placeholder: '#D1D5DB',
};
const dark = {
  bg: '#0A0A0F', card: '#14141F', text: '#F9FAFB', subtext: '#9CA3AF',
  inputBg: '#1E1E2E', border: '#2D2D3F', icon: '#6B7280', placeholder: '#4B5563',
};

// ── Styles ───────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { paddingHorizontal: 24, paddingBottom: 40 },

  topBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 24, paddingTop: 16, paddingBottom: 8 },
  progressRow: { flexDirection: 'row', gap: 8 },
  progressDot: { width: 40, height: 4, borderRadius: 2 },
  skipText: { fontSize: 14, fontWeight: '600' },

  header: { alignItems: 'center', paddingVertical: 16 },
  stepBadge: {
    width: 56, height: 56, borderRadius: 18,
    justifyContent: 'center', alignItems: 'center', marginBottom: 12,
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 6 }, shadowOpacity: 0.3, shadowRadius: 12, elevation: 8,
  },
  stepBadgeText: { fontSize: 22, fontWeight: '800', color: '#FFF' },
  title: { fontSize: 24, fontWeight: '800', letterSpacing: -0.4, marginBottom: 8 },
  sub: { fontSize: 14, textAlign: 'center', lineHeight: 20, paddingHorizontal: 8 },

  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginBottom: 16 },
  shapeCard: {
    borderRadius: 18, borderWidth: 1.5, padding: 14,
    alignItems: 'center', position: 'relative',
  },
  shapeEmojiBg: { width: 56, height: 56, borderRadius: 16, justifyContent: 'center', alignItems: 'center', marginBottom: 10 },
  shapeEmoji: { fontSize: 26 },
  shapeLabel: { fontSize: 13, fontWeight: '700', textAlign: 'center', marginBottom: 4 },
  shapeDesc: { fontSize: 11, textAlign: 'center', lineHeight: 15 },
  checkBadge: {
    position: 'absolute', top: 10, right: 10,
    width: 22, height: 22, borderRadius: 11, backgroundColor: '#7C3AED',
    justifyContent: 'center', alignItems: 'center',
  },

  tipCard: { borderRadius: 16, borderWidth: 1, overflow: 'hidden', marginBottom: 24 },
  tipBar: { height: 4 },
  tipContent: { flexDirection: 'row', alignItems: 'flex-start', padding: 14, gap: 10 },
  tipCardText: { flex: 1, fontSize: 13, lineHeight: 19 },

  primaryBtn: { borderRadius: 14, overflow: 'hidden', marginBottom: 16 },
  primaryBtnInner: {
    height: 54, flexDirection: 'row', justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8,
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700', color: '#FFF' },
  footNote: { fontSize: 12, textAlign: 'center' },
});
