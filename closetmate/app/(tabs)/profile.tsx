import React, { useState } from 'react';
import {
  StyleSheet,
  View,
  SafeAreaView,
  ScrollView,
  Image,
  TouchableOpacity,
  useColorScheme,
  Dimensions,
} from 'react-native';
import { ThemedText } from '@/components/themed-text';
import { MOCK_PROFILE_EXTENDED, SKIN_TONE_COLORS } from '@/constants/MockData';
import { Spacing } from '@/constants/theme';
import { Ionicons } from '@expo/vector-icons';

const { width } = Dimensions.get('window');
const DAY_SIZE = (width - Spacing.m * 2 - 6 * 8) / 7;

export default function ProfileScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const [selectedSkinTone, setSelectedSkinTone] = useState(MOCK_PROFILE_EXTENDED.skinToneIndex);

  const cardBg = isDark ? '#1C1C1E' : '#FFFFFF';
  const cardBorder = isDark ? 'transparent' : '#E5E5EA';
  const textPrimary = isDark ? '#FFFFFF' : '#000000';
  const textSecondary = isDark ? '#AEAEB2' : '#3C3C43';

  return (
    <SafeAreaView style={[styles.safeArea, { backgroundColor: isDark ? '#000' : '#FFF' }]}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* Header: avatar + name */}
        <View style={styles.header}>
          <Image source={{ uri: MOCK_PROFILE_EXTENDED.avatar }} style={styles.avatar} />
          <ThemedText type="title" style={styles.profileName}>
            {MOCK_PROFILE_EXTENDED.name}
          </ThemedText>
        </View>

        {/* Body Shape card */}
        <View style={[styles.card, { backgroundColor: cardBg, borderColor: cardBorder }]}>
          <ThemedText type="heading" style={[styles.cardTitle, { color: textPrimary }]}>
            Body Shape
          </ThemedText>
          <View style={styles.bodyShapeRow}>
            <View style={[styles.bodyShapeIcon, { backgroundColor: isDark ? '#2C2C2E' : '#F2F2F7' }]}>
              <Ionicons name="ellipse-outline" size={40} color={isDark ? '#AEAEB2' : '#666'} />
            </View>
            <ThemedText style={[styles.bodyShapeLabel, { color: textSecondary }]}>
              {MOCK_PROFILE_EXTENDED.bodyShape}
            </ThemedText>
          </View>
        </View>

        {/* Skin Tone card */}
        <View style={[styles.card, { backgroundColor: cardBg, borderColor: cardBorder }]}>
          <ThemedText type="heading" style={[styles.cardTitle, { color: textPrimary }]}>
            Skin Tone
          </ThemedText>
          <View style={styles.skinToneRow}>
            {SKIN_TONE_COLORS.map((color, index) => (
              <TouchableOpacity
                key={index}
                style={[
                  styles.skinToneSwatch,
                  { backgroundColor: color },
                  selectedSkinTone === index && styles.skinToneSwatchSelected,
                ]}
                onPress={() => setSelectedSkinTone(index)}
              />
            ))}
          </View>
        </View>

        {/* Worn History card */}
        <View style={[styles.card, { backgroundColor: cardBg, borderColor: cardBorder }]}>
          <ThemedText type="heading" style={[styles.cardTitle, { color: textPrimary }]}>
            Worn History
          </ThemedText>
          <View style={styles.weekRow}>
            {MOCK_PROFILE_EXTENDED.wornHistory.map((day, index) => (
              <View key={index} style={styles.dayColumn}>
                <ThemedText type="caption" style={{ color: textSecondary, marginBottom: 6 }}>
                  {day.day}
                </ThemedText>
                <View style={[styles.dayCell, { backgroundColor: isDark ? '#2C2C2E' : '#F2F2F7' }]}>
                  {day.image ? (
                    <Image source={{ uri: day.image }} style={styles.dayImage} resizeMode="cover" />
                  ) : (
                    <ThemedText type="caption" style={{ color: textSecondary }}>{day.date}</ThemedText>
                  )}
                </View>
              </View>
            ))}
          </View>
        </View>

        {/* Style Insights card */}
        <View style={[styles.card, { backgroundColor: cardBg, borderColor: cardBorder }]}>
          <View style={styles.insightHeader}>
            <Ionicons name="sparkles" size={18} color={isDark ? '#0A84FF' : '#007AFF'} />
            <ThemedText type="heading" style={[styles.cardTitle, { color: textPrimary, marginBottom: 0, marginLeft: 6 }]}>
              Style Insights
            </ThemedText>
          </View>
          <ThemedText style={[styles.insightText, { color: textSecondary }]}>
            {MOCK_PROFILE_EXTENDED.styleInsight}
          </ThemedText>
        </View>

        <View style={{ height: 100 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1 },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: Spacing.m, paddingTop: Spacing.l },
  header: {
    alignItems: 'center',
    marginBottom: Spacing.l,
  },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: 44,
    marginBottom: Spacing.s,
    backgroundColor: '#E5E5EA',
  },
  profileName: {
    textAlign: 'center',
  },
  card: {
    borderRadius: 16,
    padding: Spacing.m,
    marginBottom: Spacing.m,
    borderWidth: 1,
  },
  cardTitle: {
    marginBottom: Spacing.m,
  },
  bodyShapeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.m,
  },
  bodyShapeIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    justifyContent: 'center',
    alignItems: 'center',
  },
  bodyShapeLabel: {
    fontSize: 16,
  },
  skinToneRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  skinToneSwatch: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  skinToneSwatchSelected: {
    borderColor: '#007AFF',
  },
  weekRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  dayColumn: {
    alignItems: 'center',
    flex: 1,
    marginHorizontal: 2,
  },
  dayCell: {
    width: DAY_SIZE,
    height: DAY_SIZE,
    borderRadius: 8,
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
  },
  dayImage: {
    width: '100%',
    height: '100%',
  },
  insightHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: Spacing.s,
  },
  insightText: {
    fontSize: 15,
    lineHeight: 22,
  },
});
