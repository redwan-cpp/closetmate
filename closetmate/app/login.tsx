/**
 * app/login.tsx — ClosetMate premium login screen
 */
import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, useColorScheme, StatusBar,
  ScrollView, ActivityIndicator, Alert, Dimensions,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { loginUser } from '@/src/api/auth';
import { useAuth } from '@/src/context/AuthContext';

const { height } = Dimensions.get('window');

export default function LoginScreen() {
  const router = useRouter();
  const { signIn } = useAuth();
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;

  const [email, setEmail]         = useState('');
  const [password, setPassword]   = useState('');
  const [showPw, setShowPw]       = useState(false);
  const [loading, setLoading]     = useState(false);
  const [emailFocused, setEmailFocused] = useState(false);
  const [pwFocused, setPwFocused]       = useState(false);

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
      Alert.alert('Login failed', e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={[styles.root, { backgroundColor: isDark ? '#0A0A0F' : '#F5F4FF' }]}>
      <StatusBar barStyle="light-content" />

      {/* ── Gradient hero ── */}
      <LinearGradient
        colors={['#7C3AED', '#4F46E5']}
        start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
        style={[styles.hero, { paddingTop: insets.top + 28 }]}
      >
        <View style={styles.logoWrap}>
          <Text style={styles.logoIcon}>✦</Text>
        </View>
        <Text style={styles.brand}>ClosetMate</Text>
        <Text style={styles.tagline}>Your AI personal stylist</Text>
      </LinearGradient>

      {/* ── Form ── */}
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={[styles.scroll, { paddingBottom: insets.bottom + 32 }]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={[styles.card, { backgroundColor: c.card }]}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Welcome back</Text>
            <Text style={[styles.cardSub, { color: c.subtext }]}>Sign in to your wardrobe</Text>

            {/* Email */}
            <View style={styles.fieldWrap}>
              <Text style={[styles.label, { color: c.subtext }]}>Email</Text>
              <View style={[
                styles.inputRow,
                { backgroundColor: c.inputBg, borderColor: emailFocused ? '#7C3AED' : c.border },
              ]}>
                <Ionicons name="mail-outline" size={18}
                  color={emailFocused ? '#7C3AED' : c.icon} style={styles.inputIcon} />
                <TextInput
                  style={[styles.input, { color: c.text }]}
                  value={email} onChangeText={setEmail}
                  placeholder="you@example.com" placeholderTextColor={c.placeholder}
                  keyboardType="email-address" autoCapitalize="none" autoCorrect={false}
                  onFocus={() => setEmailFocused(true)}
                  onBlur={() => setEmailFocused(false)}
                />
              </View>
            </View>

            {/* Password */}
            <View style={styles.fieldWrap}>
              <Text style={[styles.label, { color: c.subtext }]}>Password</Text>
              <View style={[
                styles.inputRow,
                { backgroundColor: c.inputBg, borderColor: pwFocused ? '#7C3AED' : c.border },
              ]}>
                <Ionicons name="lock-closed-outline" size={18}
                  color={pwFocused ? '#7C3AED' : c.icon} style={styles.inputIcon} />
                <TextInput
                  style={[styles.input, { color: c.text }]}
                  value={password} onChangeText={setPassword}
                  placeholder="••••••••" placeholderTextColor={c.placeholder}
                  secureTextEntry={!showPw}
                  onFocus={() => setPwFocused(true)}
                  onBlur={() => setPwFocused(false)}
                />
                <TouchableOpacity onPress={() => setShowPw(!showPw)} style={styles.eyeBtn}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                  <Ionicons name={showPw ? 'eye-outline' : 'eye-off-outline'} size={18} color={c.icon} />
                </TouchableOpacity>
              </View>
            </View>

            {/* Sign in button */}
            <TouchableOpacity onPress={handleLogin} disabled={loading} activeOpacity={0.85} style={{ marginTop: 8 }}>
              <LinearGradient
                colors={['#7C3AED', '#4F46E5']}
                start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }}
                style={styles.primaryBtn}
              >
                {loading
                  ? <ActivityIndicator color="#FFF" />
                  : <>
                      <Text style={styles.primaryBtnText}>Sign In</Text>
                      <Ionicons name="arrow-forward" size={18} color="#FFF" style={{ marginLeft: 8 }} />
                    </>
                }
              </LinearGradient>
            </TouchableOpacity>
          </View>

          {/* Footer */}
          <View style={styles.footer}>
            <Text style={[styles.footerText, { color: c.subtext }]}>Don't have an account? </Text>
            <TouchableOpacity onPress={() => router.push('/register')} activeOpacity={0.7}>
              <Text style={styles.footerLink}>Create one</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const light = {
  card: '#FFFFFF', text: '#1A1A2E', subtext: '#6B7280',
  inputBg: '#F9F8FF', border: '#E5E7EB', icon: '#9CA3AF', placeholder: '#D1D5DB',
};
const dark = {
  card: '#14141F', text: '#F9FAFB', subtext: '#9CA3AF',
  inputBg: '#1E1E2E', border: '#2D2D3F', icon: '#6B7280', placeholder: '#4B5563',
};

const styles = StyleSheet.create({
  root: { flex: 1 },
  flex: { flex: 1 },

  hero: {
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingBottom: 40,
  },
  logoWrap: {
    width: 72, height: 72, borderRadius: 24,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.3)',
    justifyContent: 'center', alignItems: 'center', marginBottom: 14,
  },
  logoIcon: { fontSize: 32, color: '#FFF' },
  brand: { fontSize: 30, fontWeight: '800', color: '#FFF', letterSpacing: -0.5, marginBottom: 6 },
  tagline: { fontSize: 15, color: 'rgba(255,255,255,0.75)' },

  scroll: { paddingHorizontal: 24, paddingTop: 24 },

  card: {
    borderRadius: 24, padding: 24, marginBottom: 24,
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.12, shadowRadius: 24, elevation: 8,
  },
  cardTitle: { fontSize: 22, fontWeight: '800', letterSpacing: -0.3, marginBottom: 4 },
  cardSub: { fontSize: 14, marginBottom: 24 },

  fieldWrap: { marginBottom: 16 },
  label: { fontSize: 13, fontWeight: '600', marginBottom: 8 },
  inputRow: {
    flexDirection: 'row', alignItems: 'center',
    borderRadius: 14, borderWidth: 1.5, paddingHorizontal: 14, height: 54,
  },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, fontSize: 15 },
  eyeBtn: { padding: 4 },

  primaryBtn: {
    height: 54, borderRadius: 14,
    flexDirection: 'row', justifyContent: 'center', alignItems: 'center',
    shadowColor: '#7C3AED', shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35, shadowRadius: 10, elevation: 6,
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700', color: '#FFF' },

  footer: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center' },
  footerText: { fontSize: 14 },
  footerLink: { fontSize: 14, fontWeight: '700', color: '#7C3AED' },
});
