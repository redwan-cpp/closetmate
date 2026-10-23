/**
 * app/(tabs)/profile.tsx
 * ClosetMate — User Profile
 * Shows: avatar (uploadable), name, body shape, skin tone, worn history
 * All data pulled from the backend using the logged-in user_id.
 */
import React, { useState, useCallback } from 'react';
import {
  StyleSheet, View, Text, ScrollView, TouchableOpacity,
  useColorScheme, ActivityIndicator, Alert, Image, Modal
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { useAuth } from '@/src/context/AuthContext';
import { getWornHistory, WornLog, getStyleInsights, StyleInsights } from '@/src/api/ai';
import { getProfile, updateProfile, detectSkinTone } from '@/src/api/auth';
import { useRouter } from 'expo-router';
import { useFocusEffect } from '@react-navigation/native';


// ── Skin tone display map ─────────────────────
// Keys are the backend's canonical bands (hyphenated); colours match the register screen.
const SKIN_TONE_MAP: Record<string, { color: string; label: string }> = {
  'light':        { color: '#FDDBB4', label: 'Light' },
  'light-medium': { color: '#E8A87C', label: 'Light Medium' },
  'medium':       { color: '#C68642', label: 'Medium' },
  'medium-deep':  { color: '#8D5524', label: 'Medium Deep' },
  'deep':         { color: '#3B1A0A', label: 'Deep' },
};

/** "light-medium (warm)" -> { band: 'light-medium', undertone: 'warm' }. Tolerates legacy values. */
function parseSkinTone(value: string | null | undefined): { band: string; undertone: string | null } | null {
  if (!value) return null;
  const match = value.toLowerCase().match(/^\s*([^()]+?)\s*(?:\(\s*([^()]+?)\s*\))?\s*$/);
  if (!match) return null;
  const legacy: Record<string, string> = { fair: 'light', 'medium-dark': 'medium-deep', dark: 'deep' };
  const raw = match[1].replace(/_/g, '-');
  const band = legacy[raw] ?? raw;
  if (!SKIN_TONE_MAP[band]) return null;
  return { band, undertone: match[2] ?? null };
}

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

export default function ProfileScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const c = isDark ? dark : light;
  const router = useRouter();
  const { user_id, token, signOut } = useAuth();
  // The (tabs) layout redirects to /login when signed out, so user_id is set here.
  const activeUserId = user_id ?? '';

  const [profile, setProfile]       = useState<UserProfile | null>(null);
  const [wornHistory, setWornHistory] = useState<WornLog[]>([]);
  const [avatarUri, setAvatarUri]    = useState<string | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(true);

  const [insights, setInsights] = useState<StyleInsights | null>(null);
  const [loadingInsights, setLoadingInsights] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);

  const [showShapePicker, setShowShapePicker] = useState(false);
  const [showSkinPicker, setShowSkinPicker] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);

  // ── Fetch profile ──
  const fetchProfile = useCallback(async () => {
    if (!token) {
      setLoadingProfile(false);
      return;
    }
    try {
      setProfile(await getProfile());
    } catch (e) {
      console.warn('Profile fetch error:', e);
    } finally {
      setLoadingProfile(false);
    }
  }, [token]);

  // ── Fetch worn history ──
  const fetchWornHistory = useCallback(async () => {
    try {
      const data = await getWornHistory(activeUserId, 7);
      setWornHistory(data);
    } catch (e) {
      console.warn('Worn history fetch error:', e);
    } finally {
      setLoadingHistory(false);
    }
  }, [activeUserId]);

  useFocusEffect(
    useCallback(() => {
      fetchProfile();
      fetchWornHistory();
    }, [fetchProfile, fetchWornHistory])
  );

  const handleGenerateInsights = async () => {
    setLoadingInsights(true);
    setInsightsError(null);
    try {
      const data = await getStyleInsights(activeUserId);
      setInsights(data);
    } catch (e) {
      setInsightsError(e instanceof Error ? e.message : 'Failed to generate insights');
    } finally {
      setLoadingInsights(false);
    }
  };

  const handleUpdateShape = async (shapeId: string) => {
    setShowShapePicker(false);
    setSavingProfile(true);
    try {
      const updated = await updateProfile({ body_shape: shapeId });
      setProfile(updated);
    } catch (e) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Failed to update body shape');
    } finally {
      setSavingProfile(false);
    }
  };

  const handleUpdateSkin = async (skinId: string) => {
    setShowSkinPicker(false);
    setSavingProfile(true);
    try {
      const updated = await updateProfile({ skin_tone: skinId });
      setProfile(updated);
    } catch (e) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Failed to update skin tone');
    } finally {
      setSavingProfile(false);
    }
  };

  const handleAnalyzeSkin = async () => {
    setShowSkinPicker(false);
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('Permission needed', 'Camera access is required to analyze your skin tone.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });
    if (result.canceled || !result.assets[0]) return;

    setSavingProfile(true);
    try {
      const analysis = await detectSkinTone(result.assets[0].uri);
      if (!analysis.face_detected) {
        Alert.alert('No Face Detected', 'Please take a clear picture of your face in good lighting.');
        return;
      }
      // Save the full label ("light-medium (warm)") so the undertone reaches the stylist. 
       
      
      const updated = await updateProfile({ skin_tone: analysis.display_label });
      setProfile(updated);
      Alert.alert('Skin Tone Analyzed', `Detected: ${analysis.display_label}`);
    } catch (e) {
      Alert.alert('Error', e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setSavingProfile(false);
    }
  };

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

  const parsedSkin = parseSkinTone(profile?.skin_tone);
  const skinInfo  = parsedSkin ? { ...SKIN_TONE_MAP[parsedSkin.band], undertone: parsedSkin.undertone } : null;
  const shapeInfo = profile?.body_shape ? BODY_SHAPE_MAP[profile.body_shape] : null;

  // Build history entries from real worn logs
  const historyEntries = wornHistory.map((log) => {
    const imgUrls = log.items
      .map((it) => it.image_path)
      .filter((u): u is string => !!u);
    const label = new Date(log.worn_date + 'T00:00:00').toLocaleDateString('en-US', {
      month: 'short', day: 'numeric',
    });
    const pieceLabels = log.items
      .map((it) => [it.primary_color, it.subcategory].filter(Boolean).join(' '))
      .filter(Boolean);
    return { log_id: log.log_id, label, imgUrls, pieceCount: log.items.length, pieceLabels };
  });

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
          <View style={[styles.cardHeader, { justifyContent: 'space-between' }]}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Body Shape</Text>
            <TouchableOpacity onPress={() => setShowShapePicker(true)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Text style={{ color: c.text, fontSize: 14, fontWeight: '600' }}>Edit</Text>
            </TouchableOpacity>
          </View>
          {savingProfile && !showShapePicker && !showSkinPicker ? (
            <ActivityIndicator color={c.text} style={{ marginVertical: 10 }} />
          ) : shapeInfo ? (
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
          <View style={[styles.cardHeader, { justifyContent: 'space-between' }]}>
            <Text style={[styles.cardTitle, { color: c.text }]}>Skin Tone</Text>
            <TouchableOpacity onPress={() => setShowSkinPicker(true)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Text style={{ color: c.text, fontSize: 14, fontWeight: '600' }}>Edit</Text>
            </TouchableOpacity>
          </View>
          {savingProfile && !showShapePicker && !showSkinPicker ? (
            <ActivityIndicator color={c.text} style={{ marginVertical: 10 }} />
          ) : skinInfo ? (
            <View style={styles.skinRow}>
              <View style={[styles.skinSwatchLarge, { backgroundColor: skinInfo.color }]} />
              <View>
                <Text style={[styles.skinLabel, { color: c.text }]}>
                  {skinInfo.label}{skinInfo.undertone ? ` · ${skinInfo.undertone}` : ''}
                </Text>
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
            <Text style={[styles.cardTitle, { color: c.text }]}>Worn History</Text>
            <Text style={[styles.cardMeta, { color: c.subtext }]}>
              {wornHistory.length} outfit{wornHistory.length !== 1 ? 's' : ''} logged
            </Text>
          </View>

          {loadingHistory ? (
            <ActivityIndicator color={c.subtext} style={{ marginVertical: 20 }} />
          ) : wornHistory.length === 0 ? (
            <EmptyState
              icon="shirt-outline"
              message="No outfits logged yet."
              subMessage={'Tap "Wearing this today" in the AI Stylist chat to start tracking.'}
              c={c}
            />
          ) : (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.historyScroll}
            >
              {historyEntries.map(({ log_id, label, imgUrls, pieceCount, pieceLabels }) => (
                <View key={log_id} style={[styles.historyCard, { backgroundColor: c.bg, borderColor: c.border }]}>
                  {/* Dynamic image grid */}
                  <View style={[styles.historyGrid, { backgroundColor: c.surface }]}>
                    {(() => {
                      if (imgUrls.length === 0) {
                        return (
                          <View style={styles.historyGridEmpty}>
                            <Ionicons name="shirt-outline" size={28} color={c.border} />
                          </View>
                        );
                      }
                      if (imgUrls.length === 1) {
                        return <Image source={{ uri: imgUrls[0] }} style={{ width: '100%', height: '100%' }} resizeMode="cover" />;
                      }
                      if (imgUrls.length === 2) {
                        return (
                          <>
                            <Image source={{ uri: imgUrls[0] }} style={{ width: '50%', height: '100%' }} resizeMode="cover" />
                            <Image source={{ uri: imgUrls[1] }} style={{ width: '50%', height: '100%' }} resizeMode="cover" />
                          </>
                        );
                      }
                      if (imgUrls.length === 3) {
                        return (
                          <>
                            <Image source={{ uri: imgUrls[0] }} style={{ width: '50%', height: '100%' }} resizeMode="cover" />
                            <View style={{ width: '50%', height: '100%' }}>
                              <Image source={{ uri: imgUrls[1] }} style={{ width: '100%', height: '50%' }} resizeMode="cover" />
                              <Image source={{ uri: imgUrls[2] }} style={{ width: '100%', height: '50%' }} resizeMode="cover" />
                            </View>
                          </>
                        );
                      }
                      return [0, 1, 2, 3].map((idx) => (
                        <Image
                          key={idx}
                          source={{ uri: imgUrls[idx] }}
                          style={styles.historyGridImg}
                          resizeMode="cover"
                        />
                      ));
                    })()}
                  </View>
                  {/* Labels */}
                  <Text style={[styles.historyCardDate, { color: c.text }]} numberOfLines={1}>{label}</Text>
                  <Text style={[styles.historyCardPieces, { color: c.subtext }]} numberOfLines={1}>
                    {pieceCount} piece{pieceCount !== 1 ? 's' : ''}
                  </Text>
                  {pieceLabels.length > 0 && (
                    <Text style={[styles.historyCardItems, { color: c.border }]} numberOfLines={2}>
                      {pieceLabels.slice(0, 3).join(' · ')}
                    </Text>
                  )}
                </View>
              ))}
            </ScrollView>
          )}
        </View>


        {/* ── Style Insights ── */}
        <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={[styles.cardHeader, { marginBottom: 10 }]}>
            <Ionicons name="sparkles" size={16} color={c.text} />
            <Text style={[styles.cardTitle, { color: c.text, marginLeft: 8 }]}>AI Style Insights</Text>
          </View>
          
          {loadingInsights ? (
            <View style={{ padding: 20, alignItems: 'center' }}>
              <ActivityIndicator color={c.subtext} />
              <Text style={{ color: c.subtext, marginTop: 10 }}>Analyzing your wardrobe...</Text>
            </View>
          ) : insights ? (
            <View style={styles.insightsWrap}>
              <Text style={[styles.insightTip, { color: c.text }]}>&ldquo;{insights.general_tip}&rdquo;</Text>
              
              <View style={styles.insightSection}>
                <Text style={[styles.insightSectionTitle, { color: c.text }]}>🎨 Best Colors For You</Text>
                <View style={styles.chipWrap}>
                  {insights.best_colors.map((color, i) => (
                    <View key={i} style={[styles.insightChip, { backgroundColor: c.bg, borderColor: c.border }]}><Text style={{color: c.text, fontSize: 13, textTransform: 'capitalize'}}>{color}</Text></View>
                  ))}
                </View>
              </View>

              {insights.avoid_colors.length > 0 && (
                <View style={styles.insightSection}>
                  <Text style={[styles.insightSectionTitle, { color: c.text }]}>🚫 Colors to Avoid</Text>
                  <View style={styles.chipWrap}>
                    {insights.avoid_colors.map((color, i) => (
                      <View key={i} style={[styles.insightChip, { backgroundColor: c.bg, borderColor: c.border }]}><Text style={{color: c.subtext, fontSize: 13, textTransform: 'capitalize'}}>{color}</Text></View>
                    ))}
                  </View>
                </View>
              )}

              <View style={styles.insightSection}>
                <Text style={[styles.insightSectionTitle, { color: c.text }]}>✂️ Best Silhouettes</Text>
                <View style={styles.chipWrap}>
                  {insights.silhouettes.map((shape, i) => (
                    <View key={i} style={[styles.insightChip, { backgroundColor: c.bg, borderColor: c.border }]}><Text style={{color: c.text, fontSize: 13, textTransform: 'capitalize'}}>{shape}</Text></View>
                  ))}
                </View>
              </View>

              {insights.wardrobe_gaps.length > 0 && (
                <View style={styles.insightSection}>
                  <Text style={[styles.insightSectionTitle, { color: c.text }]}>🛍️ Wardrobe Gaps</Text>
                  {insights.wardrobe_gaps.map((gap, i) => (
                    <Text key={i} style={{ color: c.subtext, fontSize: 13, marginBottom: 4, textTransform: 'capitalize' }}>• {gap}</Text>
                  ))}
                </View>
              )}
              
              <TouchableOpacity onPress={handleGenerateInsights} style={[styles.generateBtn, { borderColor: c.border, borderWidth: 1 }]}>
                <Text style={{ color: c.text, fontWeight: '600' }}>Regenerate Insights</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View>
              {profile && (shapeInfo || skinInfo) ? (
                <Text style={[styles.insightText, { color: c.subtext, marginBottom: 16 }]}>
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
                  message="No basic style info yet."
                  subMessage="Complete your profile with body shape and skin tone to help the AI."
                  c={c}
                />
              )}
              
              {insightsError && <Text style={{ color: 'red', marginBottom: 10, textAlign: 'center' }}>{insightsError}</Text>}

              <TouchableOpacity onPress={handleGenerateInsights} style={[styles.generateBtn, { backgroundColor: c.text }]}>
                <Ionicons name="sparkles" size={16} color={c.bg} style={{ marginRight: 6 }} />
                <Text style={{ color: c.bg, fontWeight: '700' }}>Generate Deep Insights</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>

        <View style={{ height: 120 }} />
      </ScrollView>

      {/* ── Shape Picker Modal ── */}
      <Modal visible={showShapePicker} transparent animationType="slide">
        <View style={styles.modalBg}>
          <View style={[styles.modalContent, { backgroundColor: c.bg }]}>
            <Text style={[styles.modalTitle, { color: c.text }]}>Select Body Shape</Text>
            <ScrollView style={{ maxHeight: 400 }}>
              {Object.entries(BODY_SHAPE_MAP).map(([key, info]) => (
                <TouchableOpacity key={key} style={[styles.modalRow, { borderBottomColor: c.border }]} onPress={() => handleUpdateShape(key)}>
                  <Text style={styles.modalEmoji}>{info.emoji}</Text>
                  <Text style={[styles.modalLabel, { color: c.text }]}>{info.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity onPress={() => setShowShapePicker(false)} style={styles.modalCancel}>
              <Text style={{ color: c.text, fontWeight: '600' }}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* ── Skin Tone Picker Modal ── */}
      <Modal visible={showSkinPicker} transparent animationType="slide">
        <View style={styles.modalBg}>
          <View style={[styles.modalContent, { backgroundColor: c.bg }]}>
            <Text style={[styles.modalTitle, { color: c.text }]}>Select Skin Tone</Text>
            <TouchableOpacity style={[styles.analyzeBtn, { backgroundColor: c.text }]} onPress={handleAnalyzeSkin}>
              <Ionicons name="camera" size={18} color={c.bg} style={{ marginRight: 8 }} />
              <Text style={{ color: c.bg, fontWeight: '700' }}>Analyze via Camera</Text>
            </TouchableOpacity>
            <Text style={{ textAlign: 'center', color: c.subtext, marginVertical: 14 }}>— or select manually —</Text>
            <ScrollView style={{ maxHeight: 300 }}>
              {Object.entries(SKIN_TONE_MAP).map(([key, info]) => (
                <TouchableOpacity key={key} style={[styles.modalRow, { borderBottomColor: c.border }]} onPress={() => handleUpdateSkin(key)}>
                  <View style={[styles.skinSwatchSmall, { backgroundColor: info.color }]} />
                  <Text style={[styles.modalLabel, { color: c.text }]}>{info.label}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            <TouchableOpacity onPress={() => setShowSkinPicker(false)} style={styles.modalCancel}>
              <Text style={{ color: c.text, fontWeight: '600' }}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
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

  // ── Worn history horizontal scroll cards ──
  historyScroll: {
    paddingBottom: 4,
    paddingRight: 4,
  },
  historyCard: {
    width: 120,
    borderRadius: 14,
    borderWidth: 1,
    marginRight: 10,
    padding: 8,
    overflow: 'hidden',
  },
  historyGrid: {
    width: '100%',
    aspectRatio: 1,
    flexDirection: 'row',
    flexWrap: 'wrap',
    borderRadius: 10,
    overflow: 'hidden',
    marginBottom: 8,
  },
  historyGridImg: {
    width: '50%',
    height: '50%',
  },
  historyGridEmpty: {
    width: '100%',
    height: '100%',
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 10,
  },
  historyCardDate:   { fontSize: 12, fontWeight: '700', marginBottom: 2 },
  historyCardPieces: { fontSize: 11, marginBottom: 2 },
  historyCardItems:  { fontSize: 10, lineHeight: 14 },

  insightText: { fontSize: 14, lineHeight: 22 },

  insightsWrap: { paddingTop: 6 },
  insightTip: { fontSize: 15, fontWeight: '600', fontStyle: 'italic', marginBottom: 16, lineHeight: 22 },
  insightSection: { marginBottom: 16 },
  insightSectionTitle: { fontSize: 14, fontWeight: '700', marginBottom: 8 },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  insightChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 16, borderWidth: 1 },
  generateBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    paddingVertical: 12, borderRadius: 12, marginTop: 8
  },

  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalContent: { borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20, paddingBottom: 40 },
  modalTitle: { fontSize: 18, fontWeight: '700', marginBottom: 16, textAlign: 'center' },
  modalRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14, borderBottomWidth: 1 },
  modalEmoji: { fontSize: 24, marginRight: 12 },
  modalLabel: { fontSize: 16, fontWeight: '500' },
  modalCancel: { marginTop: 20, alignItems: 'center', paddingVertical: 12 },
  analyzeBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', padding: 14, borderRadius: 12 },
  skinSwatchSmall: { width: 24, height: 24, borderRadius: 12, marginRight: 12, borderWidth: 1, borderColor: 'rgba(0,0,0,0.1)' },
});
