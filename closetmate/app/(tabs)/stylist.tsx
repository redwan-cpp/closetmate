import React, { useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  Image,
  TouchableOpacity,
  useColorScheme,
  SafeAreaView,
  Dimensions,
  TextInput,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const { width } = Dimensions.get('window');

export default function StylistScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const [inputText, setInputText] = useState('');

  const styles = createStyles(isDark);

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          {/* Header */}
          <Text style={styles.header}>Stylist</Text>

          {/* User Message - right aligned */}
          <View style={styles.userMessageContainer}>
            <View style={styles.userBubble}>
              <Text style={styles.userBubbleText}>
                I have a Holud ceremony tonight. Something festive but comfy.
              </Text>
            </View>
          </View>

          {/* AI Response - left aligned with CM badge */}
          <View style={styles.aiMessageContainer}>
            <View style={styles.aiBadge}>
              <Text style={styles.aiBadgeText}>CM</Text>
            </View>
            <View style={styles.aiBubble}>
              <Text style={styles.aiBubbleText}>
                Exciting! For a Holud, let's go vibrant and breathable. How about this combination?
              </Text>
            </View>
          </View>

        {/* Outfit Card */}
        <View style={styles.outfitCard}>
          {/* Outfit Images Grid */}
          <View style={styles.outfitGrid}>
            {/* Left side - Large image */}
            <View style={styles.outfitImageLarge}>
              <Image
                source={{ uri: 'https://images.unsplash.com/photo-1610701596007-11502861dcfa?w=400&h=600&fit=crop' }}
                style={styles.imageFill}
                resizeMode="cover"
              />
            </View>

            {/* Right side - Small images */}
            <View style={styles.outfitImagesRight}>
              <View style={styles.outfitImageSmall}>
                <Image
                  source={{ uri: 'https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?w=200&h=200&fit=crop' }}
                  style={styles.imageFill}
                  resizeMode="cover"
                />
              </View>
              <View style={styles.outfitImageSmall}>
                <Image
                  source={{ uri: 'https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=200&h=200&fit=crop' }}
                  style={styles.imageFill}
                  resizeMode="cover"
                />
              </View>
            </View>
          </View>

          {/* Why it works section */}
          <View style={styles.whyItWorksSection}>
            <Text style={styles.whyItWorksTitle}>Why it works:</Text>
            <Text style={styles.whyItWorksText}>
              The mustard yellow complements your warm undertones beautifully for an evening event. The block heels ensure comfort for dancing.
            </Text>
          </View>

          {/* CTA Button */}
          <TouchableOpacity style={styles.ctaButton} activeOpacity={0.8}>
            <Text style={styles.ctaButtonText}>I'm wearing this today</Text>
            <View style={styles.checkmark}>
              <Text style={styles.checkmarkText}>✓</Text>
            </View>
          </TouchableOpacity>
        </View>
        </ScrollView>

        {/* Chat input bar */}
        <View style={[styles.inputBar, { backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7' }]}>
          <TouchableOpacity style={styles.inputIcon} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
            <Ionicons name="camera-outline" size={24} color={isDark ? '#AEAEB2' : '#3C3C43'} />
          </TouchableOpacity>
          <TextInput
            style={[styles.textInput, { color: isDark ? '#FFFFFF' : '#000000' }]}
            placeholder="Message..."
            placeholderTextColor={isDark ? '#636366' : '#8E8E93'}
            value={inputText}
            onChangeText={setInputText}
          />
          <TouchableOpacity style={styles.inputIcon} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
            <Ionicons name="mic-outline" size={24} color={isDark ? '#AEAEB2' : '#3C3C43'} />
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function createStyles(isDark: boolean) {
  return StyleSheet.create({
    flex: { flex: 1 },
    container: {
      flex: 1,
      backgroundColor: isDark ? '#000000' : '#FFFFFF',
    },
    scrollView: {
      flex: 1,
    },
    scrollContent: {
      paddingHorizontal: 20,
      paddingTop: 8,
      paddingBottom: 24,
    },
    header: {
      fontSize: 34,
      fontWeight: '700',
      color: isDark ? '#FFFFFF' : '#000000',
      marginBottom: 24,
      letterSpacing: -0.5,
    },

    // User Message - right aligned
    userMessageContainer: {
      flexDirection: 'row',
      justifyContent: 'flex-end',
      marginBottom: 16,
    },
    userBubble: {
      maxWidth: '85%',
      backgroundColor: isDark ? '#2C2C2E' : '#1C1C1E',
      borderRadius: 18,
      padding: 14,
      borderBottomRightRadius: 4,
    },
    userBubbleText: {
      fontSize: 15,
      lineHeight: 20,
      color: '#FFFFFF',
    },

    // AI Message - left with CM badge
    aiMessageContainer: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      marginBottom: 20,
      gap: 8,
    },
    aiBadge: {
      width: 28,
      height: 28,
      borderRadius: 14,
      backgroundColor: isDark ? '#3A3A3C' : '#E5E5EA',
      justifyContent: 'center',
      alignItems: 'center',
    },
    aiBadgeText: {
      fontSize: 10,
      fontWeight: '700',
      color: isDark ? '#FFFFFF' : '#000000',
    },
    aiBubble: {
      flex: 1,
      backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7',
      borderRadius: 18,
      padding: 14,
      borderBottomLeftRadius: 4,
    },
    aiBubbleText: {
      fontSize: 15,
      lineHeight: 20,
      color: isDark ? '#FFFFFF' : '#000000',
    },

    // Outfit Card
    outfitCard: {
      backgroundColor: isDark ? '#1C1C1E' : '#FFFFFF',
      borderRadius: 20,
      padding: 16,
      marginLeft: 36,
      borderWidth: isDark ? 0 : 1,
      borderColor: isDark ? 'transparent' : '#E5E5EA',
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: isDark ? 0.3 : 0.08,
      shadowRadius: 8,
      elevation: 3,
    },
    outfitGrid: {
      flexDirection: 'row',
      gap: 12,
      marginBottom: 16,
    },
    outfitImageLarge: {
      flex: 2,
      aspectRatio: 0.75,
      borderRadius: 12,
      overflow: 'hidden',
      backgroundColor: isDark ? '#2C2C2E' : '#F2F2F7',
    },
    outfitImagesRight: {
      flex: 1,
      gap: 12,
    },
    outfitImageSmall: {
      flex: 1,
      borderRadius: 12,
      overflow: 'hidden',
      backgroundColor: isDark ? '#2C2C2E' : '#F2F2F7',
    },
    imageFill: {
      width: '100%',
      height: '100%',
    },
    whyItWorksSection: {
      marginBottom: 16,
    },
    whyItWorksTitle: {
      fontSize: 15,
      fontWeight: '600',
      color: isDark ? '#FFFFFF' : '#000000',
      marginBottom: 6,
    },
    whyItWorksText: {
      fontSize: 14,
      lineHeight: 19,
      color: isDark ? '#AEAEB2' : '#3C3C43',
    },
    ctaButton: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: '#FF6B6B',
      borderRadius: 12,
      paddingVertical: 14,
      paddingHorizontal: 20,
      gap: 8,
    },
    ctaButtonText: {
      fontSize: 16,
      fontWeight: '600',
      color: '#FFFFFF',
    },
    checkmark: {
      width: 20,
      height: 20,
      borderRadius: 10,
      backgroundColor: 'rgba(255, 255, 255, 0.3)',
      justifyContent: 'center',
      alignItems: 'center',
    },
    checkmarkText: {
      fontSize: 12,
      color: '#FFFFFF',
      fontWeight: '700',
    },

    // Input bar
    inputBar: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 12,
      paddingVertical: 10,
      paddingBottom: Platform.OS === 'ios' ? 28 : 10,
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: 'rgba(128,128,128,0.3)',
    },
    inputIcon: {
      padding: 4,
    },
    textInput: {
      flex: 1,
      fontSize: 16,
      paddingVertical: 10,
      paddingHorizontal: 16,
      marginHorizontal: 8,
      borderRadius: 20,
      backgroundColor: 'rgba(128,128,128,0.15)',
      maxHeight: 100,
    },
  });
}