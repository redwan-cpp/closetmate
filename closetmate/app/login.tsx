/**
 * app/login.tsx
 * ClosetMate — Login screen
 * Supports: Email/Password · Google (placeholder) · GitHub (placeholder)
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
import { loginUser } from '@/src/api/auth';
import { useAuth } from '@/src/context/AuthContext';

export default function LoginScreen() {
  const router = useRouter();
  const { signIn } = useAuth();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw]     = useState(false);
  const [loading, setLoading]   = useState(false);

  const handleLogin = async () => {
    const em = email.trim().toLowerCase();
    if (!em || !password) {
      Alert.alert('Missing fields', 'Please enter your email and password.');
      return;
    }
    setLoading(true);
    try {
      const { token, user_id } = await loginUser({ email: em, password });
      await signIn(token, user_id);
      router.replace('/(tabs)/stylist');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      Alert.alert('Login failed', msg);
    } finally {
      setLoading(false);
    }
  };

  const handleOAuth = (provider: 'google' | 'github') => {
    Alert.alert(
      `${provider === 'google' ? 'Google' : 'GitHub'} Sign-In`,
      'OAuth integration requires configuring credentials in your backend. Coming soon!',
      [{ text: 'OK' }]
    );
  };

  const c = isDark ? dark : light;

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: c.bg }]}>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* ── Logo / Header ── */}
          <View style={styles.header}>
            <LinearGradient
              colors={['#7C3AED', '#4F46E5']}
              start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
              style={styles.logoGradient}
            >
              <Text style={styles.logoIcon}>✦</Text>
            </LinearGradient>
            <Text style={[styles.brand, { color: c.text }]}>ClosetMate</Text>
            <Text style={[styles.tagline, { color: c.subtext }]}>
              Your AI personal stylist
            </Text>
          </View>

          {/* ── Card ── */}
          <View style={[styles.card, { backgroundColor: c.card, shadowColor: c.shadow }]}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Welcome back</Text>
            <Text style={[styles.cardSub, { color: c.subtext }]}>Sign in to your wardrobe</Text>

            {/* Email */}
            <View style={styles.fieldWrap}>
              <Text style={[styles.label, { color: c.subtext }]}>Email</Text>
              <View style={[styles.inputRow, { backgroundColor: c.inputBg, borderColor: c.border }]}>
                <Ionicons name="mail-outline" size={18} color={c.icon} style={styles.inputIcon} />
                <TextInput
                  style={[styles.input, { color: c.text }]}
                  value={email}
                  onChangeText={setEmail}
                  placeholder="you@example.com"
                  placeholderTextColor={c.placeholder}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>
            </View>

            {/* Password */}
            <View style={styles.fieldWrap}>
              <Text style={[styles.label, { color: c.subtext }]}>Password</Text>
              <View style={[styles.inputRow, { backgroundColor: c.inputBg, borderColor: c.border }]}>
                <Ionicons name="lock-closed-outline" size={18} color={c.icon} style={styles.inputIcon} />
                <TextInput
                  style={[styles.input, { color: c.text }]}
                  value={password}
                  onChangeText={setPassword}
                  placeholder="••••••••"
                  placeholderTextColor={c.placeholder}
                  secureTextEntry={!showPw}
                />
                <TouchableOpacity onPress={() => setShowPw(!showPw)} style={styles.eyeBtn} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                  <Ionicons name={showPw ? 'eye-outline' : 'eye-off-outline'} size={18} color={c.icon} />
                </TouchableOpacity>
              </View>
            </View>

            {/* Login button */}
            <TouchableOpacity
              onPress={handleLogin}
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
                  : <Text style={styles.primaryBtnText}>Sign In</Text>
                }
              </LinearGradient>
            </TouchableOpacity>

            {/* Divider */}
            <View style={styles.divider}>
              <View style={[styles.dividerLine, { backgroundColor: c.border }]} />
              <Text style={[styles.dividerText, { color: c.subtext }]}>or continue with</Text>
              <View style={[styles.dividerLine, { backgroundColor: c.border }]} />
            </View>

            {/* OAuth buttons */}
            <View style={styles.oauthRow}>
              <TouchableOpacity
                onPress={() => handleOAuth('google')}
                style={[styles.oauthBtn, { backgroundColor: c.inputBg, borderColor: c.border }]}
                activeOpacity={0.8}
              >
                <Text style={styles.oauthEmoji}>🇬</Text>
                <Text style={[styles.oauthLabel, { color: c.text }]}>Google</Text>
              </TouchableOpacity>

              <TouchableOpacity
                onPress={() => handleOAuth('github')}
                style={[styles.oauthBtn, { backgroundColor: c.inputBg, borderColor: c.border }]}
                activeOpacity={0.8}
              >
                <Ionicons name="logo-github" size={20} color={c.text} />
                <Text style={[styles.oauthLabel, { color: c.text }]}>GitHub</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* ── Footer ── */}
          <View style={styles.footer}>
            <Text style={[styles.footerText, { color: c.subtext }]}>Don't have an account? </Text>
            <TouchableOpacity onPress={() => router.push('/register')} activeOpacity={0.7}>
              <Text style={styles.footerLink}>Create one</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// ── Color tokens ─────────────────────────────

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

  header: { alignItems: 'center', paddingTop: 48, paddingBottom: 32 },
  logoGradient: {
    width: 72, height: 72, borderRadius: 22,
    justifyContent: 'center', alignItems: 'center', marginBottom: 16,
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.4, shadowRadius: 16, elevation: 12,
  },
  logoIcon: { fontSize: 32, color: '#FFF' },
  brand: { fontSize: 28, fontWeight: '800', letterSpacing: -0.5 },
  tagline: { fontSize: 14, marginTop: 4 },

  card: {
    borderRadius: 24, padding: 24,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08, shadowRadius: 20, elevation: 6,
  },
  cardTitle: { fontSize: 22, fontWeight: '700', letterSpacing: -0.3, marginBottom: 4 },
  cardSub: { fontSize: 14, marginBottom: 24 },

  fieldWrap: { marginBottom: 16 },
  label: { fontSize: 13, fontWeight: '600', marginBottom: 8 },
  inputRow: {
    flexDirection: 'row', alignItems: 'center',
    borderRadius: 14, borderWidth: 1, paddingHorizontal: 14, height: 52,
  },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, fontSize: 15 },
  eyeBtn: { padding: 4 },

  primaryBtn: { marginTop: 8, borderRadius: 14, overflow: 'hidden' },
  primaryBtnInner: {
    height: 52, justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3, shadowRadius: 8,
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700', color: '#FFF' },

  divider: { flexDirection: 'row', alignItems: 'center', marginVertical: 20 },
  dividerLine: { flex: 1, height: 1 },
  dividerText: { marginHorizontal: 12, fontSize: 13 },

  oauthRow: { flexDirection: 'row', gap: 12 },
  oauthBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    height: 48, borderRadius: 12, borderWidth: 1, gap: 8,
  },
  oauthEmoji: { fontSize: 18 },
  oauthLabel: { fontSize: 14, fontWeight: '600' },

  footer: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', marginTop: 28 },
  footerText: { fontSize: 14 },
  footerLink: { fontSize: 14, fontWeight: '700', color: '#7C3AED' },
});
