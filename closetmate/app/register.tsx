/**
 * app/register.tsx
 * ClosetMate — Registration Step 1/3
 * Name · Email · Password · Gender
 * Leads to face-scan (step 2) then body-shape (step 3)
 */
import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ScrollView, ActivityIndicator, Alert, KeyboardAvoidingView,
  Platform, useColorScheme, StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';

const GENDERS = ['Male', 'Female', 'Non-binary', 'Prefer not to say'];

export default function RegisterScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;

  const [name, setName]         = useState('');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm]   = useState('');
  const [gender, setGender]     = useState('');
  const [showPw, setShowPw]     = useState(false);
  const [showCf, setShowCf]     = useState(false);

  const handleNext = () => {
    if (!name.trim()) { Alert.alert('Required', 'Please enter your name.'); return; }
    if (!email.trim()) { Alert.alert('Required', 'Please enter your email.'); return; }
    if (!password || password.length < 6) { Alert.alert('Weak password', 'Password must be at least 6 characters.'); return; }
    if (password !== confirm) { Alert.alert('Mismatch', 'Passwords do not match.'); return; }
    if (!gender) { Alert.alert('Required', 'Please select your gender.'); return; }

    // Navigate to face scan, passing draft registration data as params
    router.push({
      pathname: '/register-face',
      params: {
        name: name.trim(),
        email: email.trim().toLowerCase(),
        password,
        gender,
      },
    });
  };

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>

          {/* ── Back + Progress ── */}
          <View style={styles.topBar}>
            <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
              <Ionicons name="arrow-back" size={24} color={c.text} />
            </TouchableOpacity>
            <View style={styles.progressRow}>
              {[1, 2, 3].map((s) => (
                <View
                  key={s}
                  style={[
                    styles.progressDot,
                    { backgroundColor: s === 1 ? '#7C3AED' : c.border },
                    s === 1 && styles.progressDotActive,
                  ]}
                />
              ))}
            </View>
            <View style={{ width: 24 }} />
          </View>

          {/* ── Header ── */}
          <View style={styles.header}>
            <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.stepBadge}>
              <Text style={styles.stepBadgeText}>1</Text>
            </LinearGradient>
            <Text style={[styles.title, { color: c.text }]}>Create account</Text>
            <Text style={[styles.sub, { color: c.subtext }]}>Step 1 of 3 — Your details</Text>
          </View>

          {/* ── Form ── */}
          <View style={[styles.card, { backgroundColor: c.card }]}>

            {/* Name */}
            <Field label="Full Name" icon="person-outline" isDark={isDark} c={c}>
              <TextInput
                style={[styles.input, { color: c.text }]}
                value={name} onChangeText={setName}
                placeholder="Alex Rahman" placeholderTextColor={c.placeholder}
                autoCapitalize="words"
              />
            </Field>

            {/* Email */}
            <Field label="Email" icon="mail-outline" isDark={isDark} c={c}>
              <TextInput
                style={[styles.input, { color: c.text }]}
                value={email} onChangeText={setEmail}
                placeholder="you@example.com" placeholderTextColor={c.placeholder}
                keyboardType="email-address" autoCapitalize="none" autoCorrect={false}
              />
            </Field>

            {/* Password */}
            <Field label="Password" icon="lock-closed-outline" isDark={isDark} c={c}
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

            {/* Confirm Password */}
            <Field label="Confirm Password" icon="shield-checkmark-outline" isDark={isDark} c={c}
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
            <Text style={[styles.label, { color: c.subtext, marginTop: 4 }]}>Gender</Text>
            <View style={styles.genderGrid}>
              {GENDERS.map((g) => (
                <TouchableOpacity
                  key={g}
                  onPress={() => setGender(g)}
                  activeOpacity={0.8}
                  style={[
                    styles.genderChip,
                    { borderColor: gender === g ? '#7C3AED' : c.border, backgroundColor: gender === g ? '#7C3AED18' : c.inputBg },
                  ]}
                >
                  <Text style={[styles.genderChipText, { color: gender === g ? '#7C3AED' : c.subtext }]}>{g}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* ── Next ── */}
          <TouchableOpacity onPress={handleNext} activeOpacity={0.85} style={styles.primaryBtn}>
            <LinearGradient colors={['#7C3AED', '#4F46E5']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={styles.primaryBtnInner}>
              <Text style={styles.primaryBtnText}>Next — Face Scan</Text>
              <Ionicons name="arrow-forward" size={18} color="#FFF" style={{ marginLeft: 8 }} />
            </LinearGradient>
          </TouchableOpacity>

          {/* ── Already have account ── */}
          <View style={styles.footer}>
            <Text style={[styles.footerText, { color: c.subtext }]}>Already have an account? </Text>
            <TouchableOpacity onPress={() => router.replace('/login')} activeOpacity={0.7}>
              <Text style={styles.footerLink}>Sign in</Text>
            </TouchableOpacity>
          </View>

        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// ── Field wrapper component ──────────────────

interface FieldProps {
  label: string;
  icon: string;
  children: React.ReactNode;
  isDark: boolean;
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
  bg: '#F5F4FF', card: '#FFFFFF', text: '#1A1A2E', subtext: '#6B7280',
  inputBg: '#F9FAFB', border: '#E5E7EB', icon: '#9CA3AF',
  placeholder: '#D1D5DB', shadow: '#000',
};
const dark = {
  bg: '#0A0A0F', card: '#14141F', text: '#F9FAFB', subtext: '#9CA3AF',
  inputBg: '#1E1E2E', border: '#2D2D3F', icon: '#6B7280',
  placeholder: '#4B5563', shadow: '#7C3AED',
};

// ── Styles ───────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingBottom: 40 },

  topBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingTop: 16, paddingBottom: 8 },
  progressRow: { flexDirection: 'row', gap: 8 },
  progressDot: { width: 28, height: 4, borderRadius: 2 },
  progressDotActive: { width: 40 },

  header: { alignItems: 'center', paddingVertical: 20 },
  stepBadge: {
    width: 56, height: 56, borderRadius: 18,
    justifyContent: 'center', alignItems: 'center', marginBottom: 12,
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 6 }, shadowOpacity: 0.3, shadowRadius: 12, elevation: 8,
  },
  stepBadgeText: { fontSize: 22, fontWeight: '800', color: '#FFF' },
  title: { fontSize: 24, fontWeight: '800', letterSpacing: -0.4, marginBottom: 4 },
  sub: { fontSize: 14 },

  card: { borderRadius: 20, padding: 20, marginBottom: 20 },

  fieldWrap: { marginBottom: 14 },
  label: { fontSize: 13, fontWeight: '600', marginBottom: 8 },
  inputRow: { flexDirection: 'row', alignItems: 'center', borderRadius: 14, borderWidth: 1, paddingHorizontal: 14, height: 52 },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, fontSize: 15 },

  genderGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  genderChip: { borderRadius: 20, borderWidth: 1.5, paddingHorizontal: 16, paddingVertical: 8 },
  genderChipText: { fontSize: 14, fontWeight: '600' },

  primaryBtn: { borderRadius: 14, overflow: 'hidden', marginBottom: 24 },
  primaryBtnInner: {
    height: 54, flexDirection: 'row', justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.3, shadowRadius: 8,
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700', color: '#FFF' },

  footer: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center' },
  footerText: { fontSize: 14 },
  footerLink: { fontSize: 14, fontWeight: '700', color: '#7C3AED' },
});
