/**
 * app/register.tsx
 * ClosetMate — Registration (all steps combined)
 * Step 1: Name, Email, Password, Gender
 * Step 2: Body Shape (full list)
 * Step 3: Skin tone (from face scan or manual pick)
 * Final: POST to backend → auto-login → home
 */
import React, { useState, useRef, useEffect } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ScrollView, ActivityIndicator, Alert, KeyboardAvoidingView,
  Platform, useColorScheme, StatusBar, Dimensions, Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import * as ImagePicker from 'expo-image-picker';
import { registerUser, loginUser, detectSkinTone } from '@/src/api/auth';
import { useAuth } from '@/src/context/AuthContext';

const { width } = Dimensions.get('window');
const CARD_W = (width - 24 * 2 - 12) / 2;
const FACE_RING = width * 0.48;

// Maps API skin_tone values → display config for the selfie ring badge
const TONE_CONFIG: Record<string, { label: string; hex: string; gradient: [string, string] }> = {
  'light':        { label: 'Light',        hex: '#FDDBB4', gradient: ['#FDDBB4', '#F5C5A3'] },
  'light-medium': { label: 'Light Medium', hex: '#E8A87C', gradient: ['#E8A87C', '#D4956A'] },
  'medium':       { label: 'Medium',       hex: '#C68642', gradient: ['#C68642', '#A07030'] },
  'medium-deep':  { label: 'Medium Deep',  hex: '#8D5524', gradient: ['#8D5524', '#6B3A15'] },
  'deep':         { label: 'Deep',         hex: '#3B1A0A', gradient: ['#6B3A2A', '#3B1A0A'] },
};

// ─────────────────────────────────────────────
// Data
// ─────────────────────────────────────────────

const GENDERS = ['Male', 'Female', 'Non-binary', 'Prefer not to say'];

const BODY_SHAPES = [
  {
    id: 'hourglass',
    label: 'Hourglass',
    emoji: '⌛',
    desc: 'Balanced bust & hips, defined waist',
  },
  {
    id: 'pear',
    label: 'Pear / Triangle',
    emoji: '🍐',
    desc: 'Hips wider than shoulders',
  },
  {
    id: 'apple',
    label: 'Apple / Round',
    emoji: '🍎',
    desc: 'Fuller midsection, narrow hips',
  },
  {
    id: 'rectangle',
    label: 'Rectangle',
    emoji: '▬',
    desc: 'Shoulders, waist & hips similar width',
  },
  {
    id: 'inverted_triangle',
    label: 'Inverted Triangle',
    emoji: '🔺',
    desc: 'Broad shoulders, narrow hips',
  },
  {
    id: 'oval',
    label: 'Oval / Diamond',
    emoji: '💎',
    desc: 'Narrower shoulders & hips, wider mid',
  },
  {
    id: 'athletic',
    label: 'Athletic',
    emoji: '🏋️',
    desc: 'Muscular build, defined shoulders',
  },
  {
    id: 'petite',
    label: 'Petite',
    emoji: '🌸',
    desc: 'Smaller frame, shorter stature',
  },
  {
    id: 'tall',
    label: 'Tall / Lean',
    emoji: '📏',
    desc: 'Slender frame, long limbs',
  },
  {
    id: 'curvy',
    label: 'Curvy / Plus',
    emoji: '🌊',
    desc: 'Full figure, rounded proportions',
  },
];

// IDs match the API's skin_tone field values (hyphens, not underscores)
const SKIN_TONES = [
  { id: 'light',        label: 'Light',        color: '#FDDBB4' },
  { id: 'light-medium', label: 'Light Medium', color: '#E8A87C' },
  { id: 'medium',       label: 'Medium',       color: '#C68642' },
  { id: 'medium-deep',  label: 'Medium Deep',  color: '#8D5524' },
  { id: 'deep',         label: 'Deep',         color: '#3B1A0A' },
];

// ─────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────

export default function RegisterScreen() {
  const router = useRouter();
  const { signIn } = useAuth();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;

  // Step state
  const [step, setStep] = useState(1);
  const scrollRef = useRef<ScrollView>(null);

  // Step 1 fields
  const [name, setName]         = useState('');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm]   = useState('');
  const [gender, setGender]     = useState('');
  const [showPw, setShowPw]     = useState(false);
  const [showCf, setShowCf]     = useState(false);

  // Step 2 fields
  const [bodyShape, setBodyShape] = useState<string | null>(null);

  // Step 3 fields
  const [skinTone, setSkinTone] = useState<string | null>(null);

  // Step 3 — face scan extra state
  const [imageUri, setImageUri]         = useState<string | null>(null);
  const [scanning, setScanning]         = useState(false);
  const [scanHex, setScanHex]           = useState<string | null>(null);   // hex from API
  const [scanLabel, setScanLabel]       = useState<string | null>(null);  // display_label from API

  // Auto-launch camera when Step 3 appears
  useEffect(() => {
    if (step === 3) {
      const t = setTimeout(takeSelfie, 350);
      return () => clearTimeout(t);
    }
  }, [step]);

  const takeSelfie = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Camera access is required for skin tone detection.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      cameraType: ImagePicker.CameraType.front,
      quality: 0.85,
      allowsEditing: false,
    });
    if (!result.canceled) {
      const uri = result.assets[0].uri;
      setImageUri(uri);
      await runScan(uri);
    }
  };

  const runScan = async (uri: string) => {
    setScanning(true);
    setSkinTone(null);
    setScanHex(null);
    setScanLabel(null);
    try {
      const result = await detectSkinTone(uri);
      setSkinTone(result.skin_tone);       // e.g. "light-medium"
      setScanHex(result.hex_swatch);       // e.g. "#C8A882"
      setScanLabel(result.display_label);  // e.g. "light-medium (warm)"
    } catch (e) {
      Alert.alert('Scan failed', 'Could not detect skin tone. Pick manually below.');
    } finally {
      setScanning(false);
    }
  };

  const [loading, setLoading] = useState(false);

  const scrollTop = () => scrollRef.current?.scrollTo({ y: 0, animated: true });

  // ── Step 1 validation ──
  const handleStep1Next = () => {
    if (!name.trim()) { Alert.alert('Required', 'Please enter your name.'); return; }
    if (!email.trim()) { Alert.alert('Required', 'Please enter your email.'); return; }
    if (!password || password.length < 6) { Alert.alert('Weak password', 'Password must be at least 6 characters.'); return; }
    if (password !== confirm) { Alert.alert('Mismatch', 'Passwords do not match.'); return; }
    if (!gender) { Alert.alert('Required', 'Please select your gender.'); return; }
    setStep(2);
    scrollTop();
  };

  // ── Step 2 → Step 3 ──
  const handleStep2Next = () => {
    if (!bodyShape) { Alert.alert('Required', 'Please select your body shape.'); return; }
    setStep(3);
    scrollTop();
  };

  // ── Final submit ──
  const handleFinish = async (overrideSkin?: string | null) => {
    const tone = overrideSkin !== undefined ? overrideSkin : skinTone;
    setLoading(true);
    try {
      await registerUser({
        name: name.trim(),
        email: email.trim().toLowerCase(),
        password,
        gender,
        body_shape: bodyShape ?? undefined,
        skin_tone: tone ?? undefined,
      });
      const { token, user_id } = await loginUser({
        email: email.trim().toLowerCase(),
        password,
      });
      await signIn(token, user_id);
      router.replace('/(tabs)/stylist');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      Alert.alert('Registration failed', msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} />

      {/* ── Top bar ── */}
      <View style={[styles.topBar, { borderBottomColor: c.border }]}>
        <TouchableOpacity
          onPress={() => step === 1 ? router.back() : setStep(step - 1)}
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        >
          <Ionicons name="arrow-back" size={22} color={c.text} />
        </TouchableOpacity>

        {/* Step indicator pills */}
        <View style={styles.pillRow}>
          {[1, 2, 3].map((s) => (
            <View
              key={s}
              style={[
                styles.pill,
                {
                  backgroundColor: s <= step ? c.text : c.border,
                  width: s === step ? 32 : 10,
                },
              ]}
            />
          ))}
        </View>

        <Text style={[styles.stepLabel, { color: c.subtext }]}>{step} / 3</Text>
      </View>

      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >

          {/* ══════════ STEP 1 — Your Details ══════════ */}
          {step === 1 && (
            <>
              <View style={styles.stepHeader}>
                <Text style={[styles.stepTitle, { color: c.text }]}>Create account</Text>
                <Text style={[styles.stepSub, { color: c.subtext }]}>Step 1 of 3 — Your details</Text>
              </View>

              <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>

                <Field label="Full Name" icon="person-outline" c={c}>
                  <TextInput
                    style={[styles.input, { color: c.text }]}
                    value={name} onChangeText={setName}
                    placeholder="Alex Rahman" placeholderTextColor={c.placeholder}
                    autoCapitalize="words"
                  />
                </Field>

                <Field label="Email" icon="mail-outline" c={c}>
                  <TextInput
                    style={[styles.input, { color: c.text }]}
                    value={email} onChangeText={setEmail}
                    placeholder="you@example.com" placeholderTextColor={c.placeholder}
                    keyboardType="email-address" autoCapitalize="none" autoCorrect={false}
                  />
                </Field>

                <Field
                  label="Password" icon="lock-closed-outline" c={c}
                  right={
                    <TouchableOpacity onPress={() => setShowPw(!showPw)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                      <Ionicons name={showPw ? 'eye-outline' : 'eye-off-outline'} size={18} color={c.icon} />
                    </TouchableOpacity>
                  }
                >
                  <TextInput
                    style={[styles.input, { color: c.text }]}
                    value={password} onChangeText={setPassword}
                    placeholder="Min 6 characters" placeholderTextColor={c.placeholder}
                    secureTextEntry={!showPw}
                  />
                </Field>

                <Field
                  label="Confirm Password" icon="shield-checkmark-outline" c={c}
                  right={
                    <TouchableOpacity onPress={() => setShowCf(!showCf)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                      <Ionicons name={showCf ? 'eye-outline' : 'eye-off-outline'} size={18} color={c.icon} />
                    </TouchableOpacity>
                  }
                >
                  <TextInput
                    style={[styles.input, { color: c.text }]}
                    value={confirm} onChangeText={setConfirm}
                    placeholder="Re-enter password" placeholderTextColor={c.placeholder}
                    secureTextEntry={!showCf}
                  />
                </Field>

                {/* Gender */}
                <Text style={[styles.label, { color: c.subtext, marginTop: 4, marginBottom: 10 }]}>Gender</Text>
                <View style={styles.chipGrid}>
                  {GENDERS.map((g) => (
                    <TouchableOpacity
                      key={g}
                      onPress={() => setGender(g)}
                      activeOpacity={0.8}
                      style={[
                        styles.chip,
                        {
                          borderColor: gender === g ? c.text : c.border,
                          backgroundColor: gender === g ? c.text : 'transparent',
                        },
                      ]}
                    >
                      <Text style={[styles.chipText, { color: gender === g ? c.bg : c.subtext }]}>{g}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>

              <TouchableOpacity onPress={handleStep1Next} activeOpacity={0.85} style={[styles.primaryBtn, { backgroundColor: c.text }]}>
                <Text style={[styles.primaryBtnText, { color: c.bg }]}>Next — Body Shape</Text>
                <Ionicons name="arrow-forward" size={18} color={c.bg} style={{ marginLeft: 8 }} />
              </TouchableOpacity>

              <View style={styles.footer}>
                <Text style={[styles.footerText, { color: c.subtext }]}>Already have an account? </Text>
                <TouchableOpacity onPress={() => router.replace('/login')} activeOpacity={0.7}>
                  <Text style={[styles.footerLink, { color: c.text }]}>Sign in</Text>
                </TouchableOpacity>
              </View>
            </>
          )}

          {/* ══════════ STEP 2 — Body Shape ══════════ */}
          {step === 2 && (
            <>
              <View style={styles.stepHeader}>
                <Text style={[styles.stepTitle, { color: c.text }]}>Body Shape</Text>
                <Text style={[styles.stepSub, { color: c.subtext }]}>
                  Step 2 of 3 — Helps us tailor outfit recommendations
                </Text>
              </View>

              <View style={styles.bodyGrid}>
                {BODY_SHAPES.map((shape) => {
                  const isSelected = bodyShape === shape.id;
                  return (
                    <TouchableOpacity
                      key={shape.id}
                      onPress={() => setBodyShape(isSelected ? null : shape.id)}
                      activeOpacity={0.8}
                      style={[
                        styles.shapeCard,
                        {
                          width: CARD_W,
                          backgroundColor: isSelected ? c.text : c.card,
                          borderColor: isSelected ? c.text : c.border,
                        },
                      ]}
                    >
                      <Text style={styles.shapeEmoji}>{shape.emoji}</Text>
                      <Text style={[styles.shapeLabel, { color: isSelected ? c.bg : c.text }]}>{shape.label}</Text>
                      <Text style={[styles.shapeDesc, { color: isSelected ? (isDark ? '#ccc' : '#eee') : c.subtext }]} numberOfLines={2}>
                        {shape.desc}
                      </Text>
                      {isSelected && (
                        <View style={[styles.checkBadge, { backgroundColor: c.bg }]}>
                          <Ionicons name="checkmark" size={12} color={c.text} />
                        </View>
                      )}
                    </TouchableOpacity>
                  );
                })}
              </View>

              <TouchableOpacity
                onPress={handleStep2Next}
                activeOpacity={0.85}
                style={[styles.primaryBtn, { backgroundColor: c.text, opacity: bodyShape ? 1 : 0.4 }]}
              >
                <Text style={[styles.primaryBtnText, { color: c.bg }]}>Next — Skin Tone</Text>
                <Ionicons name="arrow-forward" size={18} color={c.bg} style={{ marginLeft: 8 }} />
              </TouchableOpacity>

              <TouchableOpacity onPress={() => { setBodyShape(null); setStep(3); scrollTop(); }} style={styles.skipBtn}>
                <Text style={[styles.skipText, { color: c.subtext }]}>Skip this step</Text>
              </TouchableOpacity>
            </>
          )}

          {/* ══ STEP 3 — Skin Tone (face scan + manual) ══ */}
          {step === 3 && (
            <>
              <View style={styles.stepHeader}>
                <Text style={[styles.stepTitle, { color: c.text }]}>Skin Tone</Text>
                <Text style={[styles.stepSub, { color: c.subtext }]}>
                  Step 3 of 3 — Selfie scan or pick manually
                </Text>
              </View>

              {/* ── Face ring — border color from detected hex swatch ── */}
              <View style={styles.faceSection}>
                <View style={[
                  styles.faceRingGrad,
                  { backgroundColor: scanHex ?? (skinTone && TONE_CONFIG[skinTone] ? TONE_CONFIG[skinTone].hex : '#7C3AED'), padding: 4, borderRadius: 999 },
                ]}>
                  <View style={[styles.faceRingInner, { backgroundColor: c.bg }]}>
                    {imageUri ? (
                      <Image source={{ uri: imageUri }} style={styles.faceImage} />
                    ) : (
                      <View style={styles.facePlaceholder}>
                        <Ionicons name="person" size={60} color={isDark ? '#3D3D5C' : '#DDD8FF'} />
                      </View>
                    )}
                    {scanning && (
                      <View style={styles.scanOverlay}>
                        <ActivityIndicator size="large" color="#FFF" />
                        <Text style={styles.scanLabel}>Detecting skin tone…</Text>
                      </View>
                    )}
                  </View>
                </View>

                {/* Detected result badge — shows actual tone + undertone label */}
                {scanLabel && !scanning && (
                  <View style={[styles.detectedBadge, { backgroundColor: scanHex ?? '#7C3AED' }]}>
                    <View style={[styles.swatchDot, { backgroundColor: scanHex ?? '#888' }]} />
                    <Text style={styles.detectedBadgeText}>
                      {scanLabel}
                    </Text>
                  </View>
                )}

                {/* Camera action */}
                <TouchableOpacity
                  onPress={takeSelfie}
                  disabled={scanning}
                  style={[styles.cameraChip, { borderColor: c.border, backgroundColor: c.card }]}
                  activeOpacity={0.8}
                >
                  <Ionicons name="camera" size={16} color="#7C3AED" style={{ marginRight: 6 }} />
                  <Text style={[styles.cameraChipText, { color: c.text }]}>
                    {imageUri ? 'Retake selfie' : 'Take selfie'}
                  </Text>
                </TouchableOpacity>
              </View>

              {/* Divider */}
              <View style={styles.dividerRow}>
                <View style={[styles.dividerLine, { backgroundColor: c.border }]} />
                <Text style={[styles.dividerText, { color: c.subtext }]}>or pick manually</Text>
                <View style={[styles.dividerLine, { backgroundColor: c.border }]} />
              </View>

              {/* Manual swatches */}
              <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
                <View style={styles.skinGrid}>
                  {SKIN_TONES.map((tone) => {
                    const isSel = skinTone === tone.id;
                    return (
                      <TouchableOpacity
                        key={tone.id}
                        onPress={() => { setImageUri(null); setSkinTone(isSel ? null : tone.id); }}
                        activeOpacity={0.8}
                        style={styles.skinItem}
                      >
                        <View style={[
                          styles.skinSwatch,
                          { backgroundColor: tone.color },
                          isSel && { borderWidth: 3, borderColor: c.text },
                        ]} />
                        <Text style={[styles.skinLabel, { color: isSel ? c.text : c.subtext }]}>{tone.label}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>

              <TouchableOpacity
                onPress={() => handleFinish()}
                disabled={loading}
                activeOpacity={0.85}
                style={styles.primaryBtn}
              >
                <LinearGradient
                  colors={['#7C3AED', '#4F46E5']}
                  start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }}
                  style={styles.primaryBtnInner}
                >
                  {loading
                    ? <ActivityIndicator color="#FFF" />
                    : <>
                        <Text style={styles.primaryBtnText}>Create My Wardrobe</Text>
                        <Ionicons name="checkmark-circle" size={20} color="#FFF" style={{ marginLeft: 8 }} />
                      </>
                  }
                </LinearGradient>
              </TouchableOpacity>

              <TouchableOpacity onPress={() => handleFinish(null)} disabled={loading} style={styles.skipBtn}>
                <Text style={[styles.skipText, { color: c.subtext }]}>Skip — choose later</Text>
              </TouchableOpacity>
            </>
          )}

        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// ── Field wrapper ────────────────────────────

interface FieldProps {
  label: string;
  icon: string;
  children: React.ReactNode;
  c: typeof light;
  right?: React.ReactNode;
}

function Field({ label, icon, children, c, right }: FieldProps) {
  return (
    <View style={styles.fieldWrap}>
      <Text style={[styles.label, { color: c.subtext }]}>{label}</Text>
      <View style={[styles.inputRow, { backgroundColor: c.inputBg, borderColor: c.border }]}>
        <Ionicons name={icon as any} size={18} color={c.icon} style={styles.inputIcon} />
        {children}
        {right}
      </View>
    </View>
  );
}

// ── Palette ──────────────────────────────────

const light = {
  bg: '#FFFFFF', card: '#F8F8F8', text: '#1A1A1A', subtext: '#666666',
  inputBg: '#FFFFFF', border: '#E5E5E5', icon: '#999999', placeholder: '#CCCCCC',
};
const dark = {
  bg: '#000000', card: '#121212', text: '#FFFFFF', subtext: '#A0A0A0',
  inputBg: '#1A1A1A', border: '#333333', icon: '#666666', placeholder: '#444444',
};

// ── Styles ───────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingBottom: 48 },

  topBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 24, paddingVertical: 14, borderBottomWidth: 1,
  },
  pillRow: { flexDirection: 'row', gap: 6, alignItems: 'center' },
  pill: { height: 4, borderRadius: 2 },
  stepLabel: { fontSize: 13, fontWeight: '600', width: 32, textAlign: 'right' },

  stepHeader: { paddingTop: 28, paddingBottom: 20 },
  stepTitle: { fontSize: 26, fontWeight: '800', letterSpacing: -0.5, marginBottom: 6 },
  stepSub: { fontSize: 14, lineHeight: 20 },

  card: { borderRadius: 18, padding: 20, borderWidth: 1, marginBottom: 20 },

  fieldWrap: { marginBottom: 14 },
  label: { fontSize: 13, fontWeight: '600', marginBottom: 8 },
  inputRow: {
    flexDirection: 'row', alignItems: 'center',
    borderRadius: 12, borderWidth: 1, paddingHorizontal: 14, height: 52,
  },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, fontSize: 15 },

  chipGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderRadius: 20, borderWidth: 1.5, paddingHorizontal: 16, paddingVertical: 8 },
  chipText: { fontSize: 14, fontWeight: '600' },

  bodyGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginBottom: 20 },
  shapeCard: {
    borderRadius: 18, borderWidth: 1.5, padding: 14,
    alignItems: 'center', position: 'relative',
  },
  shapeEmoji: { fontSize: 28, marginBottom: 8 },
  shapeLabel: { fontSize: 13, fontWeight: '700', textAlign: 'center', marginBottom: 4 },
  shapeDesc: { fontSize: 11, textAlign: 'center', lineHeight: 15 },
  checkBadge: {
    position: 'absolute', top: 10, right: 10,
    width: 20, height: 20, borderRadius: 10,
    justifyContent: 'center', alignItems: 'center',
  },

  skinGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 16, justifyContent: 'center' },
  skinItem: { alignItems: 'center', width: 68 },
  skinSwatch: { width: 48, height: 48, borderRadius: 24, marginBottom: 8 },
  skinLabel: { fontSize: 11, textAlign: 'center', fontWeight: '600' },

  primaryBtn: { borderRadius: 14, overflow: 'hidden', marginBottom: 16 },
  primaryBtnInner: {
    height: 54, flexDirection: 'row',
    justifyContent: 'center', alignItems: 'center',
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700', color: '#FFF' },

  skipBtn: { alignItems: 'center', paddingVertical: 12, marginBottom: 8 },
  skipText: { fontSize: 14, fontWeight: '600' },

  footer: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', marginTop: 8 },
  footerText: { fontSize: 14 },
  footerLink: { fontSize: 14, fontWeight: '700' },

  // Face scan (Step 3)
  faceSection: { alignItems: 'center', marginBottom: 20, gap: 14 },
  faceRingGrad: {
    width: FACE_RING + 6, height: FACE_RING + 6, borderRadius: (FACE_RING + 6) / 2,
    justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.28, shadowRadius: 16, elevation: 10,
  },
  faceRingInner: {
    width: FACE_RING, height: FACE_RING, borderRadius: FACE_RING / 2,
    overflow: 'hidden', justifyContent: 'center', alignItems: 'center',
  },
  facePlaceholder: { flex: 1, width: '100%', justifyContent: 'center', alignItems: 'center' },
  faceImage: { width: FACE_RING, height: FACE_RING },
  scanOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.65)',
    justifyContent: 'center', alignItems: 'center', gap: 10,
  },
  scanLabel: { color: '#FFF', fontSize: 13, fontWeight: '600' },
  detectedBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    borderRadius: 20, paddingHorizontal: 16, paddingVertical: 8,
  },
  swatchDot: { width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: 'rgba(255,255,255,0.6)' },
  detectedBadgeText: { fontSize: 14, fontWeight: '700', color: '#FFF' },
  cameraChip: {
    flexDirection: 'row', alignItems: 'center',
    borderWidth: 1.5, borderRadius: 20,
    paddingHorizontal: 16, paddingVertical: 8,
  },
  cameraChipText: { fontSize: 14, fontWeight: '600' },
  dividerRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 16 },
  dividerLine: { flex: 1, height: 1 },
  dividerText: { fontSize: 12, fontWeight: '500' },
});
