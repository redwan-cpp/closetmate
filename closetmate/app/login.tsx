/**
 * app/login.tsx
 * ClosetMate — Login screen (redesigned to match app theme)
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
  const c = isDark ? dark : light;

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
            <View style={[styles.logoWrap, { backgroundColor: isDark ? '#1A1A1A' : '#F0F0F0' }]}>
              <Text style={[styles.logoText, { color: c.text }]}>✦</Text>
            </View>
            <Text style={[styles.brand, { color: c.text }]}>ClosetMate</Text>
            <Text style={[styles.tagline, { color: c.subtext }]}>
              Your AI personal stylist
            </Text>
          </View>

          {/* ── Card ── */}
          <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}>
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

            {/* Sign In button */}
            <TouchableOpacity
              onPress={handleLogin}
              disabled={loading}
              activeOpacity={0.85}
              style={[styles.primaryBtn, { backgroundColor: c.text }]}
            >
              {loading
                ? <ActivityIndicator color={c.bg} />
                : <Text style={[styles.primaryBtnText, { color: c.bg }]}>Sign In</Text>
              }
            </TouchableOpacity>
          </View>

          {/* ── Footer ── */}
          <View style={styles.footer}>
            <Text style={[styles.footerText, { color: c.subtext }]}>Don't have an account? </Text>
            <TouchableOpacity onPress={() => router.push('/register')} activeOpacity={0.7}>
              <Text style={[styles.footerLink, { color: c.text }]}>Create one</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const light = {
  bg: '#FFFFFF', card: '#F8F8F8', text: '#1A1A1A', subtext: '#666666',
  inputBg: '#FFFFFF', border: '#E5E5E5', icon: '#999999',
  placeholder: '#CCCCCC',
};
const dark = {
  bg: '#000000', card: '#121212', text: '#FFFFFF', subtext: '#A0A0A0',
  inputBg: '#1A1A1A', border: '#333333', icon: '#666666',
  placeholder: '#444444',
};

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, paddingHorizontal: 24, paddingBottom: 40 },

  header: { alignItems: 'center', paddingTop: 52, paddingBottom: 36 },
  logoWrap: {
    width: 68, height: 68, borderRadius: 20,
    justifyContent: 'center', alignItems: 'center', marginBottom: 18,
  },
  logoText: { fontSize: 30, fontWeight: '800' },
  brand: { fontSize: 28, fontWeight: '800', letterSpacing: -0.5, marginBottom: 6 },
  tagline: { fontSize: 15 },

  card: {
    borderRadius: 20, padding: 24, borderWidth: 1, marginBottom: 28,
  },
  cardTitle: { fontSize: 22, fontWeight: '700', letterSpacing: -0.3, marginBottom: 4 },
  cardSub: { fontSize: 14, marginBottom: 24 },

  fieldWrap: { marginBottom: 16 },
  label: { fontSize: 13, fontWeight: '600', marginBottom: 8 },
  inputRow: {
    flexDirection: 'row', alignItems: 'center',
    borderRadius: 12, borderWidth: 1, paddingHorizontal: 14, height: 52,
  },
  inputIcon: { marginRight: 10 },
  input: { flex: 1, fontSize: 15 },
  eyeBtn: { padding: 4 },

  primaryBtn: {
    height: 52, borderRadius: 12, justifyContent: 'center', alignItems: 'center', marginTop: 8,
  },
  primaryBtnText: { fontSize: 16, fontWeight: '700' },

  footer: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center' },
  footerText: { fontSize: 14 },
  footerLink: { fontSize: 14, fontWeight: '700' },
});
