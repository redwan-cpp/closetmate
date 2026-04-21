/**
 * app/register-face.tsx
 * ClosetMate — Registration Step 2/3
 * Face scan → skin tone detection via backend
 */
import React, { useState, useRef, useEffect } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator,
  Alert, useColorScheme, StatusBar, Dimensions, Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import * as ImagePicker from 'expo-image-picker';
import { detectSkinTone } from '@/src/api/auth';

const { width } = Dimensions.get('window');
const RING_SIZE = width * 0.68;

const TONE_CONFIG = {
  warm: {
    label: 'Warm',
    emoji: '🌟',
    desc: 'Golden, olive, and earthy tones suit you best',
    gradient: ['#F59E0B', '#D97706'] as [string, string],
  },
  cool: {
    label: 'Cool',
    emoji: '❄️',
    desc: 'Blues, purples, and cool pinks are your colours',
    gradient: ['#818CF8', '#6366F1'] as [string, string],
  },
  neutral: {
    label: 'Neutral',
    emoji: '✨',
    desc: 'You can rock almost any colour palette',
    gradient: ['#6EE7B7', '#3B82F6'] as [string, string],
  },
};

export default function RegisterFaceScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;

  const params = useLocalSearchParams<{
    name: string; email: string; password: string; gender: string;
  }>();

  const [imageUri, setImageUri]       = useState<string | null>(null);
  const [skinTone, setSkinTone]       = useState<string | null>(null);
  const [recommended, setRecommended] = useState<string[]>([]);
  const [scanning, setScanning]       = useState(false);
  const [skipped, setSkipped]         = useState(false);

  const takeSelfie = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Camera access is required for skin tone detection.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      // Use the front-facing camera for selfies
      cameraType: ImagePicker.CameraType.front,
      quality: 0.85,
      allowsEditing: false, // no forced crop — full face captures better
    });
    if (!result.canceled) {
      const uri = result.assets[0].uri;
      setImageUri(uri);
      await runScan(uri);
    }
  };

  // Auto-launch the camera when the screen first appears
  useEffect(() => {
    const timer = setTimeout(takeSelfie, 400); // slight delay for screen animation
    return () => clearTimeout(timer);
  }, []);

  const runScan = async (uri: string) => {
    setScanning(true);
    setSkinTone(null);
    setRecommended([]);
    try {
      const result = await detectSkinTone(uri);
      setSkinTone(result.skin_tone);
      setRecommended(result.recommended_colors);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      Alert.alert('Scan failed', `${msg}\n\nYou can skip this step and set it later.`);
    } finally {
      setScanning(false);
    }
  };

  const handleNext = () => {
    const tone = skipped ? undefined : skinTone ?? undefined;
    router.push({
      pathname: '/register-body',
      params: { ...params, skin_tone: tone ?? '' },
    });
  };

  const handleSkip = () => {
    setSkipped(true);
    router.push({
      pathname: '/register-body',
      params: { ...params, skin_tone: '' },
    });
  };

  const toneConfig = skinTone ? TONE_CONFIG[skinTone as keyof typeof TONE_CONFIG] : null;

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
            <View key={s} style={[styles.progressDot, { backgroundColor: s <= 2 ? '#7C3AED' : c.border }, s === 2 && styles.progressDotActive]} />
          ))}
        </View>
        <TouchableOpacity onPress={handleSkip}>
          <Text style={[styles.skipText, { color: c.subtext }]}>Skip</Text>
        </TouchableOpacity>
      </View>

      {/* ── Header ── */}
      <View style={styles.header}>
        <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.stepBadge}>
          <Text style={styles.stepBadgeText}>2</Text>
        </LinearGradient>
        <Text style={[styles.title, { color: c.text }]}>Face Scan</Text>
        <Text style={[styles.sub, { color: c.subtext }]}>
          Take a selfie so we can detect your skin tone and recommend colours that truly suit you
        </Text>
      </View>

      {/* ── Selfie ring ── */}
      <View style={styles.ringWrap}>
        <LinearGradient
          colors={toneConfig ? toneConfig.gradient : ['#7C3AED', '#4F46E5']}
          start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
          style={styles.ringGradient}
        >
          <View style={[styles.ringInner, { backgroundColor: c.bg }]}>
            {imageUri ? (
              <Image source={{ uri: imageUri }} style={styles.selfieImage} />
            ) : (
              <View style={styles.ringPlaceholder}>
                <Ionicons name="person" size={72} color={isDark ? '#3D3D5C' : '#DDD8FF'} />
              </View>
            )}
            {scanning && (
              <View style={styles.scanOverlay}>
                <ActivityIndicator size="large" color="#FFF" />
                <Text style={styles.scanLabel}>Analysing skin tone…</Text>
              </View>
            )}
          </View>
        </LinearGradient>

        {/* Scan result badge */}
        {toneConfig && !scanning && (
          <View style={[styles.toneBadge, { backgroundColor: c.card }]}>
            <LinearGradient colors={toneConfig.gradient} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.toneBadgeGrad}>
              <Text style={styles.toneBadgeEmoji}>{toneConfig.emoji}</Text>
              <Text style={styles.toneBadgeLabel}>{toneConfig.label} Undertone</Text>
            </LinearGradient>
          </View>
        )}
      </View>

      {/* ── Tone description ── */}
      {toneConfig && !scanning && (
        <View style={styles.toneInfo}>
          <Text style={[styles.toneDesc, { color: c.subtext }]}>{toneConfig.desc}</Text>
          <View style={styles.colorPills}>
            {recommended.slice(0, 5).map((col) => (
              <View key={col} style={[styles.colorPill, { backgroundColor: c.inputBg, borderColor: c.border }]}>
                <Text style={[styles.colorPillText, { color: c.text }]}>{col}</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {/* ── No image yet ── */}
      {!imageUri && !scanning && (
        <View style={styles.instructions}>
          <View style={styles.tipRow}>
            <Ionicons name="sunny-outline" size={18} color="#F59E0B" />
            <Text style={[styles.tipText, { color: c.subtext }]}>Use good lighting for best results</Text>
          </View>
          <View style={styles.tipRow}>
            <Ionicons name="eye-outline" size={18} color="#6366F1" />
            <Text style={[styles.tipText, { color: c.subtext }]}>Look directly at the camera</Text>
          </View>
          <View style={styles.tipRow}>
            <Ionicons name="lock-closed-outline" size={18} color="#10B981" />
            <Text style={[styles.tipText, { color: c.subtext }]}>Your photo is never stored or shared</Text>
          </View>
        </View>
      )}

      {/* ── Actions ── */}
      <View style={styles.actionsWrap}>
        {!skinTone ? (
          <TouchableOpacity onPress={takeSelfie} disabled={scanning} activeOpacity={0.85} style={styles.primaryBtn}>
            <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.primaryBtnInner}>
              <Ionicons name="camera" size={20} color="#FFF" style={{ marginRight: 10 }} />
              <Text style={styles.primaryBtnText}>Take Selfie</Text>
            </LinearGradient>
          </TouchableOpacity>
        ) : (
          <>
            <TouchableOpacity onPress={handleNext} activeOpacity={0.85} style={styles.primaryBtn}>
              <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.primaryBtnInner}>
                <Text style={styles.primaryBtnText}>Next — Body Shape</Text>
                <Ionicons name="arrow-forward" size={18} color="#FFF" style={{ marginLeft: 8 }} />
              </LinearGradient>
            </TouchableOpacity>
            <TouchableOpacity onPress={takeSelfie} style={[styles.secondaryBtn, { borderColor: c.border }]} activeOpacity={0.7}>
              <Ionicons name="refresh" size={16} color={c.subtext} style={{ marginRight: 6 }} />
              <Text style={[styles.secondaryBtnText, { color: c.subtext }]}>Retake</Text>
            </TouchableOpacity>
          </>
        )}
      </View>
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

  topBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 24, paddingTop: 16, paddingBottom: 8 },
  progressRow: { flexDirection: 'row', gap: 8 },
  progressDot: { width: 28, height: 4, borderRadius: 2 },
  progressDotActive: { width: 40 },
  skipText: { fontSize: 14, fontWeight: '600' },

  header: { alignItems: 'center', paddingHorizontal: 24, paddingVertical: 16 },
  stepBadge: {
    width: 56, height: 56, borderRadius: 18,
    justifyContent: 'center', alignItems: 'center', marginBottom: 12,
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 6 }, shadowOpacity: 0.3, shadowRadius: 12, elevation: 8,
  },
  stepBadgeText: { fontSize: 22, fontWeight: '800', color: '#FFF' },
  title: { fontSize: 24, fontWeight: '800', letterSpacing: -0.4, marginBottom: 8 },
  sub: { fontSize: 14, textAlign: 'center', lineHeight: 20, paddingHorizontal: 8 },

  ringWrap: { alignItems: 'center', marginVertical: 16 },
  ringGradient: {
    width: RING_SIZE + 8, height: RING_SIZE + 8, borderRadius: (RING_SIZE + 8) / 2,
    justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 12 }, shadowOpacity: 0.3, shadowRadius: 24, elevation: 12,
  },
  ringInner: {
    width: RING_SIZE, height: RING_SIZE, borderRadius: RING_SIZE / 2,
    overflow: 'hidden', justifyContent: 'center', alignItems: 'center',
  },
  ringPlaceholder: { justifyContent: 'center', alignItems: 'center', flex: 1, width: '100%' },
  selfieImage: { width: RING_SIZE, height: RING_SIZE },
  scanOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.65)', justifyContent: 'center', alignItems: 'center', gap: 12,
  },
  scanLabel: { color: '#FFF', fontSize: 14, fontWeight: '600' },

  toneBadge: {
    position: 'absolute', bottom: -14, borderRadius: 20,
    overflow: 'hidden', shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.15, shadowRadius: 8, elevation: 6,
  },
  toneBadgeGrad: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8, gap: 8 },
  toneBadgeEmoji: { fontSize: 16 },
  toneBadgeLabel: { fontSize: 14, fontWeight: '700', color: '#FFF' },

  toneInfo: { alignItems: 'center', paddingHorizontal: 24, marginTop: 24 },
  toneDesc: { fontSize: 14, textAlign: 'center', marginBottom: 12 },
  colorPills: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'center' },
  colorPill: { borderRadius: 12, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 5 },
  colorPillText: { fontSize: 12, fontWeight: '500', textTransform: 'capitalize' },

  instructions: { paddingHorizontal: 36, marginTop: 12, gap: 12 },
  tipRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  tipText: { fontSize: 13, flex: 1 },

  actionsWrap: { paddingHorizontal: 24, marginTop: 'auto', paddingTop: 16, gap: 10, paddingBottom: 8 },
  primaryBtn: { borderRadius: 14, overflow: 'hidden' },
  primaryBtnInner: {
    height: 54, flexDirection: 'row', justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8,
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700', color: '#FFF' },
  secondaryBtn: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', height: 44, borderRadius: 12, borderWidth: 1 },
  secondaryBtnText: { fontSize: 14, fontWeight: '600' },
});
