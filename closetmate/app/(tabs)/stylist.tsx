/**
 * app/(tabs)/stylist.tsx
 * ─────────────────────────────────────────────
 * ClosetMate AI Stylist — full conversational chat UI
 * Features:
 *  · Live FlatList chat (auto-scroll to bottom)
 *  · Animated 3-dot typing indicator
 *  · Outfit suggestion cards rendered inline
 *  · Quick-prompt chips on first load
 *  · Proper keyboard avoidance
 *  · Weather-aware suggestions with location input
 *  · Error bubbles when backend is unreachable
 * ─────────────────────────────────────────────
 */

import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
} from 'react';
import {
  View,
  Text,
  FlatList,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  Animated,
  Easing,
  useColorScheme,
  Dimensions,
  Image,
  ScrollView,
  Keyboard,
  Modal,
  Alert,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import {
  sendChatMessage,
  fetchWeather,
  ChatHistoryEntry,
  SuggestedOutfitItem,
  WeatherContext,
  WeatherInfo,
  logWornOutfit,
  resolveImageUrl,
} from '@/src/api/ai';
import { useAuth } from '@/src/context/AuthContext';

const { width } = Dimensions.get('window');

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

type MessageRole = 'user' | 'assistant' | 'error';

interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  outfitItems?: SuggestedOutfitItem[] | null;
  timestamp: Date;
}

type Environment = 'indoor' | 'outdoor' | 'both';

// ─────────────────────────────────────────────
// Quick prompt chips (shown before first message)
// ─────────────────────────────────────────────

// ─────────────────────────────────────────────
// Quick prompt chips (shown before first message)
// ─────────────────────────────────────────────

const QUICK_PROMPTS = [
  'Recommend an outfit for today',
  'What should I wear to a wedding?',
  'Suggest something casual',
  'Outfit for the office',
];

// ─────────────────────────────────────────────
// Animated message entry wrapper
// ─────────────────────────────────────────────

function AnimatedMessage({ children }: { children: React.ReactNode }) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(10)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: 220,
        easing: Easing.out(Easing.ease),
        useNativeDriver: true,
      }),
      Animated.spring(translateY, {
        toValue: 0,
        tension: 90,
        friction: 10,
        useNativeDriver: true,
      }),
    ]).start();
  }, []);

  return (
    <Animated.View style={{ opacity, transform: [{ translateY }] }}>
      {children}
    </Animated.View>
  );
}


function TypingIndicator({ isDark }: { isDark: boolean }) {
  const dots = [
    useRef(new Animated.Value(0)).current,
    useRef(new Animated.Value(0)).current,
    useRef(new Animated.Value(0)).current,
  ];

  useEffect(() => {
    const animations = dots.map((dot, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * 150),
          Animated.timing(dot, {
            toValue: 1,
            duration: 350,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
          Animated.timing(dot, {
            toValue: 0,
            duration: 350,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
          Animated.delay((dots.length - i - 1) * 150),
        ])
      )
    );
    Animated.parallel(animations).start();
    return () => animations.forEach(a => a.stop());
  }, []);

  return (
    <View style={styles.aiRow}>
      <View style={[styles.cmBadge, { backgroundColor: isDark ? '#2C2C2E' : '#F0F0F0' }]}>
        <Text style={[styles.cmBadgeText, { color: isDark ? '#FFF' : '#000' }]}>✦</Text>
      </View>
      <View style={[styles.aiBubble, { backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7' }]}>
        <View style={styles.dotsRow}>
          {dots.map((dot, i) => (
            <Animated.View
              key={i}
              style={[
                styles.dot,
                {
                  backgroundColor: isDark ? '#AEAEB2' : '#8E8E93',
                  opacity: dot,
                  transform: [
                    {
                      translateY: dot.interpolate({
                        inputRange: [0, 1],
                        outputRange: [0, -4],
                      }),
                    },
                  ],
                },
              ]}
            />
          ))}
        </View>
      </View>
    </View>
  );
}

// ─────────────────────────────────────────────
// Outfit chip — inline item from AI suggestion
// ─────────────────────────────────────────────

const COLOR_HEX: Record<string, string> = {
  white: '#F5F5F5', cream: '#FFF8E1', beige: '#D7CCC8', black: '#212121',
  grey: '#9E9E9E', gray: '#9E9E9E', navy: '#1A237E', blue: '#1E88E5',
  red: '#E53935', maroon: '#880E4F', green: '#388E3C', olive: '#827717',
  yellow: '#FDD835', golden: '#F59F00', gold: '#F59F00', orange: '#FB8C00',
  pink: '#F06292', purple: '#8E24AA', brown: '#6D4C41', teal: '#00897B',
  mustard: '#F9A825', coral: '#FF7043', lavender: '#9575CD', sky_blue: '#03A9F4',
};

function OutfitItemCard({ item, isDark }: { item: SuggestedOutfitItem; isDark: boolean }) {
  const dot = COLOR_HEX[item.color.toLowerCase().replace(' ', '_')] ?? '#AAA';
  const [imgError, setImgError] = useState(false);

  // Resolve image path — handles file://, https://, and server-relative paths
  const resolvedUrl = resolveImageUrl(item.image_url);

  if (resolvedUrl && !imgError) {
    return (
      <View style={[styles.outfitCard, { backgroundColor: isDark ? '#2C2C2E' : '#E8E8ED' }]}>
      <Image
          source={{ uri: resolvedUrl }}
          style={styles.outfitCardImage}
          onError={() => setImgError(true)}
          resizeMode="cover"
        />
        <View style={styles.outfitCardMeta}>
          <View style={[styles.chipDot, { backgroundColor: dot, marginBottom: 2 }]} />
          <Text
            style={[styles.outfitCardLabel, { color: isDark ? '#FFF' : '#1C1C1E' }]}
            numberOfLines={1}
          >
            {item.color}
          </Text>
          <Text
            style={[styles.outfitCardSub, { color: isDark ? '#AEAEB2' : '#636366' }]}
            numberOfLines={1}
          >
            {item.subcategory}
          </Text>
        </View>
      </View>
    );
  }

  // Fallback: color-dot chip (no image or load error)
  return (
    <View style={[styles.chip, { backgroundColor: isDark ? '#2C2C2E' : '#E8E8ED' }]}>
      <View style={[styles.chipDot, { backgroundColor: dot }]} />
      <Text style={[styles.chipText, { color: isDark ? '#FFF' : '#1C1C1E' }]}>
        {item.color} {item.subcategory}
      </Text>
    </View>
  );
}

// ─────────────────────────────────────────────
// Single message bubble
// ─────────────────────────────────────────────

interface BubbleProps {
  msg: ChatMessage;
  isDark: boolean;
  wornToday: boolean;
  onWearToday: () => void;
}

function Bubble({ msg, isDark, wornToday, onWearToday }: BubbleProps) {
  if (msg.role === 'user') {
    return (
      <View style={styles.userRow}>
        <View style={[styles.userBubble, { backgroundColor: isDark ? '#1C1C1E' : '#1A1A1A' }]}>
          <Text style={styles.userText}>{msg.text}</Text>
        </View>
      </View>
    );
  }

  if (msg.role === 'error') {
    return (
      <View style={styles.aiRow}>
        <View style={[styles.cmBadge, { backgroundColor: '#FF3B30' }]}>
          <Ionicons name="alert" size={12} color="#FFF" />
        </View>
        <View style={[styles.aiBubble, { backgroundColor: isDark ? '#2C1010' : '#FFF2F2', borderColor: '#FF3B30', borderWidth: 1 }]}>
          <Text style={[styles.aiText, { color: isDark ? '#FF6B6B' : '#CC2929' }]}>{msg.text}</Text>
        </View>
      </View>
    );
  }

  // Assistant
  return (
    <View style={styles.aiRow}>
      <View style={[styles.cmBadge, { backgroundColor: isDark ? '#2C2C2E' : '#F0F0F0' }]}>
        <Text style={[styles.cmBadgeText, { color: isDark ? '#FFF' : '#000' }]}>✦</Text>
      </View>
      <View style={{ flex: 1 }}>
        <View style={[styles.aiBubble, { backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7' }]}>
          <Text style={[styles.aiText, { color: isDark ? '#FFF' : '#1C1C1E' }]}>{msg.text}</Text>
        </View>
        {msg.outfitItems && msg.outfitItems.length > 0 && (
          <View style={styles.chipRow}>
            <Text style={[styles.chipLabel, { color: isDark ? '#8E8E93' : '#636366' }]}>
              Suggested outfit ✦
            </Text>
            {/* Use horizontal scroll if any item has an image, otherwise wrap chips */}
            {msg.outfitItems.some(i => i.image_url) ? (
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.outfitCardScroll}
              >
                {msg.outfitItems.map((item, i) => (
                  <OutfitItemCard key={i} item={item} isDark={isDark} />
                ))}
              </ScrollView>
            ) : (
              <View style={styles.chips}>
                {msg.outfitItems.map((item, i) => (
                  <OutfitItemCard key={i} item={item} isDark={isDark} />
                ))}
              </View>
            )}
            {/* Wear today button */}
            <TouchableOpacity
              style={[
                styles.wearButton,
                wornToday && styles.wearButtonDone,
                { borderColor: wornToday ? '#30D158' : isDark ? '#3A3A3C' : '#D1D1D6' },
              ]}
              onPress={wornToday ? undefined : onWearToday}
              activeOpacity={wornToday ? 1 : 0.7}
            >
              <Text style={[
                styles.wearButtonText,
                { color: wornToday ? '#30D158' : isDark ? '#FFF' : '#1C1C1E' },
              ]}>
                {wornToday ? '✓ Logged as worn today' : '👕 Wearing this today'}
              </Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
    </View>
  );
}

// ─────────────────────────────────────────────
// Main screen
// ─────────────────────────────────────────────

// iOS tab bar height (must match _layout.tsx)
const TAB_BAR_HEIGHT_IOS = 85;

export default function StylistScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const insets = useSafeAreaInsets();
  const { user_id } = useAuth();
  const activeUserId = user_id ?? 'demo_user';

  const iosTabBarOffset = Platform.OS === 'ios' ? TAB_BAR_HEIGHT_IOS - insets.bottom : 0;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [isThinking, setIsThinking] = useState(false);

  // ── GPS Location + Weather state ────────────────────────────────────────
  const [weatherInfo, setWeatherInfo]       = useState<WeatherInfo | null>(null);
  const [weatherCtx, setWeatherCtx]         = useState<WeatherContext | null>(null);
  const [showEnvModal, setShowEnvModal]     = useState(false);
  const [environment, setEnvironment]       = useState<Environment>('outdoor');
  const [locationLoading, setLocationLoading] = useState(false);
  const [locationError, setLocationError]   = useState<string | null>(null);
  const [pendingCoords, setPendingCoords]   = useState<{ lat: number; lon: number } | null>(null);
  const [cityInput, setCityInput]           = useState('');
  const [keyboardShown, setKeyboardShown]   = useState(false);

  const flatRef = useRef<FlatList>(null);
  const inputRef = useRef<TextInput>(null);
  const prevMsgCount = useRef(0);

  // Build history from messages for backend context
  const buildHistory = useCallback((): ChatHistoryEntry[] => {
    return messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .slice(-6)
      .map(m => ({
        role: m.role as 'user' | 'assistant',
        content: m.text,
      }));
  }, [messages]);

  const scrollToBottom = useCallback((animated = true) => {
    setTimeout(() => {
      flatRef.current?.scrollToEnd({ animated });
    }, 60);
  }, []);

  // Track keyboard visibility for iOS bottom padding
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboardShown(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboardShown(false));
    return () => { show.remove(); hide.remove(); };
  }, []);

  // ── Auto-detect GPS on mount ─────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== 'granted') return;
        const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        setPendingCoords({ lat: loc.coords.latitude, lon: loc.coords.longitude });
        // Show environment popup once we have coordinates
        setShowEnvModal(true);
      } catch (e) {
        console.warn('[stylist] GPS error:', e);
      }
    })();
  }, []);

  // ── Fetch weather using GPS coords + chosen environment ─────────────────
  const handleConfirmEnvironment = useCallback(async (env: Environment) => {
    setEnvironment(env);
    setShowEnvModal(false);
    const city = cityInput.trim();
    const hasCity = city.length > 0;
    const hasCoords = !!pendingCoords;
    if (!hasCity && !hasCoords) return;
    setLocationLoading(true);
    setLocationError(null);
    try {
      // Prefer city name if typed, else use GPS coords
      const info = hasCity
        ? await fetchWeather(city, null, null, env)
        : await fetchWeather(null, pendingCoords!.lat, pendingCoords!.lon, env);
      setWeatherInfo(info);
      setWeatherCtx(hasCity ? { city, environment: env } : { lat: pendingCoords!.lat, lon: pendingCoords!.lon, environment: env });
      setCityInput('');
    } catch (e) {
      setLocationError(e instanceof Error ? e.message : 'Weather fetch failed. Check the city name.');
    } finally {
      setLocationLoading(false);
    }
  }, [pendingCoords, cityInput]);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isThinking) return;

      setInputText('');
      setIsThinking(true);

      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: 'user',
        text: trimmed,
        timestamp: new Date(),
      };

      setMessages(prev => [...prev, userMsg]);

      try {
        const history = buildHistory();
        const result = await sendChatMessage(activeUserId, trimmed, history, weatherCtx);

        const aiMsg: ChatMessage = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          text: result.reply,
          outfitItems: result.suggested_items,
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, aiMsg]);
      } catch (e) {
        const detail = e instanceof Error ? e.message : String(e);
        const errMsg: ChatMessage = {
          id: `e-${Date.now()}`,
          role: 'error',
          text: `Stylist error: ${detail}`,
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, errMsg]);
      } finally {
        setIsThinking(false);
      }
    },
    [isThinking, buildHistory, weatherCtx]
  );

  const handleSend = useCallback(() => sendMessage(inputText), [inputText, sendMessage]);

  // Auto-scroll when new messages arrive
  useEffect(() => {
    if (messages.length > prevMsgCount.current) {
      scrollToBottom();
    }
    prevMsgCount.current = messages.length;
  }, [messages.length, scrollToBottom]);

  // Track which AI messages have been logged as worn (msgId → true)
  const [wornTodayMap, setWornTodayMap] = useState<Record<string, boolean>>({});

  const handleWearToday = useCallback(async (msgId: string, items: SuggestedOutfitItem[]) => {
    const validIds = items.map(i => i.item_id).filter((id): id is string => !!id);
    if (!validIds.length) {
      Alert.alert(
        'Cannot log outfit',
        'This suggestion is missing wardrobe item IDs. Ask the stylist for an outfit again, or tap a suggestion that shows your items.'
      );
      return;
    }
    try {
      await logWornOutfit(activeUserId, validIds);
      setWornTodayMap(prev => ({ ...prev, [msgId]: true }));
    } catch (e) {
      console.warn('[stylist] logWornOutfit failed:', e);
      Alert.alert('Could not save', e instanceof Error ? e.message : String(e));
    }
  }, [activeUserId]);

  const isEmpty = messages.length === 0 && !isThinking;

  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: isDark ? '#000' : '#FFF' }]}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        {/* ── Header ── */}
        <View style={styles.header}>
          <View>
            <Text style={[styles.headerTitle, { color: isDark ? '#FFF' : '#1A1A1A' }]}>
              AI Stylist
            </Text>
            <Text style={[styles.headerSub, { color: isDark ? '#8E8E93' : '#6C6C70' }]}>
              Powered by your wardrobe
            </Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
            {/* Weather / location button */}
            <TouchableOpacity
              style={[
                styles.weatherBtn,
                { backgroundColor: weatherInfo ? '#0A84FF' : isDark ? '#2C2C2E' : '#F0F0F5' },
              ]}
              onPress={() => setShowEnvModal(true)}
              activeOpacity={0.75}
            >
              <Text style={{ fontSize: weatherInfo ? 15 : 11, color: weatherInfo ? undefined : isDark ? '#AEAEB2' : '#6C6C70', fontWeight: weatherInfo ? '400' : '600', letterSpacing: weatherInfo ? 0 : 0.3 }}>
                {weatherInfo ? weatherInfo.condition_icon : 'Venue'}
              </Text>
              {weatherInfo && (
                <Text style={styles.weatherBtnTemp}>{weatherInfo.temperature.toFixed(0)}°</Text>
              )}
            </TouchableOpacity>
            <View style={[styles.statusDot, { backgroundColor: '#30D158' }]} />
          </View>
        </View>

        {/* ── Weather banner strip (when weather loaded) ── */}
        {weatherInfo && (
          <View style={[styles.weatherBanner, { backgroundColor: isDark ? '#0A2540' : '#E8F4FF' }]}>
            <Text style={[styles.weatherBannerText, { color: isDark ? '#60C0FF' : '#0059B3' }]}>
              {weatherInfo.condition_icon} {weatherInfo.city} · {weatherInfo.temperature.toFixed(0)}°C ·{' '}
              {weatherInfo.condition} · {environment === 'indoor' ? '🏠 Indoor' : environment === 'outdoor' ? '🌿 Outdoor' : '🔄 Both'}
            </Text>
            {weatherInfo.style_advisory ? (
              <Text style={[styles.weatherAdvisory, { color: isDark ? '#A0D8FF' : '#005099' }]} numberOfLines={1}>
                💡 {weatherInfo.style_advisory}
              </Text>
            ) : null}
          </View>
        )}

        {/* ── Empty welcome state ── */}
        {isEmpty && (
          <View style={styles.welcomeArea}>
            <View style={[styles.welcomeBadge, { backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7' }]}>
              <Text style={styles.welcomeEmoji}>✦</Text>
              <Text style={[styles.welcomeTitle, { color: isDark ? '#FFF' : '#1A1A1A' }]}>
                Your personal stylist
              </Text>
              <Text style={[styles.welcomeSub, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>
                Ask me about any occasion, get outfit suggestions from your actual wardrobe, or get style advice.
              </Text>
            
              {!weatherInfo && (
                <TouchableOpacity
                  style={[styles.locationPromptBtn, { borderColor: isDark ? '#3A3A3C' : '#D1D1D6' }]}
                  onPress={() => setShowEnvModal(true)}
                  activeOpacity={0.75}
                >
                  <Text style={{ fontSize: 15 }}>🌍</Text>
                  <Text style={[styles.locationPromptText, { color: isDark ? '#FFF' : '#1A1A1A' }]}>
                    Set venue type for smart suggestions
                  </Text>
                  <Ionicons name="chevron-forward" size={14} color={isDark ? '#636366' : '#AEAEB2'} />
                </TouchableOpacity>
              )}
            </View>

            {/* Quick prompt chips */}
            <View style={styles.quickPromptWrap}>
              {QUICK_PROMPTS.map((prompt) => (
                <TouchableOpacity
                  key={prompt}
                  style={[
                    styles.quickChip,
                    { borderColor: isDark ? '#3A3A3C' : '#D1D1D6',
                      backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7' },
                  ]}
                  onPress={() => sendMessage(prompt)}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.quickChipText, { color: isDark ? '#FFF' : '#1C1C1E' }]}>
                    {prompt}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

          </View>
        )}

        {/* ── Message list ── */}
        {!isEmpty && (
          <FlatList
            ref={flatRef}
            data={messages}
            keyExtractor={m => m.id}
            contentContainerStyle={styles.messageList}
            showsVerticalScrollIndicator={false}
            renderItem={({ item }) => (
              <AnimatedMessage>
                <Bubble
                  msg={item}
                  isDark={isDark}
                  wornToday={!!wornTodayMap[item.id]}
                  onWearToday={() => handleWearToday(item.id, item.outfitItems ?? [])}
                />
              </AnimatedMessage>
            )}
            ListFooterComponent={isThinking ? <TypingIndicator isDark={isDark} /> : null}
          />
        )}

        {/* Thinking state when list is empty (first message) */}
        {isEmpty && isThinking && (
          <View style={styles.firstThinkWrap}>
            <TypingIndicator isDark={isDark} />
          </View>
        )}

        {/* ── Input bar ── */}
        <View
          style={[
            styles.inputBar,
            {
              backgroundColor: isDark ? '#1C1C1E' : '#F2F2F7',
              borderTopColor: isDark ? '#2C2C2E' : '#E5E5EA',
              paddingBottom: Platform.OS === 'ios'
                ? (keyboardShown ? 10 : 10 + iosTabBarOffset)
                : 10,
            },
          ]}
        >
          <TextInput
            ref={inputRef}
            style={[
              styles.textInput,
              {
                color: isDark ? '#FFF' : '#1A1A1A',
                backgroundColor: isDark ? '#2C2C2E' : '#E8E8ED',
              },
            ]}
            placeholder="Message your stylist…"
            placeholderTextColor={isDark ? '#636366' : '#AEAEB2'}
            value={inputText}
            onChangeText={setInputText}
            onSubmitEditing={handleSend}
            returnKeyType="send"
            multiline
            maxLength={500}
          />
          <TouchableOpacity
            onPress={handleSend}
            disabled={!inputText.trim() || isThinking}
            style={[
              styles.sendButton,
              {
                backgroundColor:
                  inputText.trim() && !isThinking
                    ? isDark ? '#FFF' : '#1A1A1A'
                    : isDark ? '#3A3A3C' : '#D1D1D6',
              },
            ]}
            activeOpacity={0.8}
          >
            {isThinking ? (
              <ActivityIndicator size="small" color={isDark ? '#000' : '#FFF'} />
            ) : (
              <Ionicons
                name="arrow-up"
                size={18}
                color={inputText.trim() ? (isDark ? '#000' : '#FFF') : isDark ? '#636366' : '#8E8E93'}
              />
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      {/* ── Indoor / Outdoor Environment Popup ── */}
<Modal
        visible={showEnvModal}
        transparent
        animationType="slide"
        onRequestClose={() => setShowEnvModal(false)}
      >
        <View style={styles.envModalOverlay}>
          <View style={[styles.envModalCard, { backgroundColor: isDark ? '#1C1C1E' : '#FFFFFF' }]}>
            <View style={styles.envModalHeader}>
              <Text style={styles.envModalIcon}>🌤</Text>
              <View style={{ flex: 1 }}>
                <Text style={[styles.envModalTitle, { color: isDark ? '#FFF' : '#1A1A1A' }]}>
                  Venue Type
                </Text>
                <Text style={[styles.envModalSub, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>
                  Your AI stylist uses weather + skin tone + body shape for perfect outfit picks.
                </Text>
              </View>
            </View>
            {/* City override input */}
            <View style={[styles.cityInputRow, { borderColor: isDark ? '#3A3A3C' : '#E5E5EA' }]}>
              <Ionicons name="location-outline" size={16} color={isDark ? '#636366' : '#AEAEB2'} />
              <TextInput
                style={[styles.cityTextInput, { color: isDark ? '#FFF' : '#1A1A1A' }]}
                placeholder="Or type a city (e.g. London, Tokyo)"
                placeholderTextColor={isDark ? '#636366' : '#AEAEB2'}
                value={cityInput}
                onChangeText={setCityInput}
                returnKeyType="done"
                autoCapitalize="words"
              />
              {pendingCoords && !cityInput && (
                <View style={styles.gpsTag}>
                  <Text style={styles.gpsTagText}>📍 GPS</Text>
                </View>
              )}
            </View>
            {locationLoading && (
              <View style={styles.envLoadingRow}>
                <ActivityIndicator size="small" color="#0A84FF" />
                <Text style={[styles.envLoadingText, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>Fetching weather...</Text>
              </View>
            )}
            {locationError && <Text style={styles.weatherErrorText}>{locationError}</Text>}
            <Text style={[styles.envSectionLabel, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>Select venue</Text>
            <TouchableOpacity style={[styles.envBigBtn, { backgroundColor: '#007AFF' }]} onPress={() => handleConfirmEnvironment('indoor')} activeOpacity={0.85}>
              <Text style={styles.envBigIcon}>🏠</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.envBigLabel}>Indoor</Text>
                <Text style={styles.envBigSub}>Office, mall, restaurant, home</Text>
              </View>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.envBigBtn, { backgroundColor: '#34C759' }]} onPress={() => handleConfirmEnvironment('outdoor')} activeOpacity={0.85}>
              <Text style={styles.envBigIcon}>🌿</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.envBigLabel}>Outdoor</Text>
                <Text style={styles.envBigSub}>Park, street, events, travel</Text>
              </View>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.envBigBtn, { backgroundColor: '#FF9500' }]} onPress={() => handleConfirmEnvironment('both')} activeOpacity={0.85}>
              <Text style={styles.envBigIcon}>🔄</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.envBigLabel}>Both</Text>
                <Text style={styles.envBigSub}>Moving between indoor and outdoor</Text>
              </View>
            </TouchableOpacity>
            <TouchableOpacity style={styles.envSkipBtn} onPress={() => setShowEnvModal(false)}>
              <Text style={[styles.envSkipText, { color: isDark ? '#636366' : '#AEAEB2' }]}>Skip for now</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ─────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },

  // Header
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 12,
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: -0.5,
  },
  headerSub: {
    fontSize: 13,
    marginTop: 1,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },

  // Welcome / empty state
  welcomeArea: {
    flex: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  welcomeBadge: {
    borderRadius: 20,
    padding: 20,
    alignItems: 'center',
    marginBottom: 20,
  },
  welcomeEmoji: {
    fontSize: 28,
    marginBottom: 10,
  },
  welcomeTitle: {
    fontSize: 19,
    fontWeight: '700',
    marginBottom: 8,
    letterSpacing: -0.3,
  },
  welcomeSub: {
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
  },
  quickPromptWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  quickChip: {
    borderRadius: 20,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  quickChipText: {
    fontSize: 14,
    fontWeight: '500',
  },

  // Message list
  messageList: {
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 16,
    gap: 12,
  },

  // User bubble
  userRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  userBubble: {
    maxWidth: width * 0.78,
    borderRadius: 20,
    borderBottomRightRadius: 5,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  userText: {
    fontSize: 15,
    lineHeight: 21,
    color: '#FFF',
  },

  // AI bubble
  aiRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  cmBadge: {
    width: 30,
    height: 30,
    borderRadius: 15,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 2,
    flexShrink: 0,
  },
  cmBadgeText: {
    fontSize: 13,
    fontWeight: '700',
  },
  aiBubble: {
    flex: 1,
    borderRadius: 20,
    borderBottomLeftRadius: 5,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  aiText: {
    fontSize: 15,
    lineHeight: 22,
  },

  // Outfit chips / cards
  chipRow: {
    marginTop: 6,
    paddingLeft: 0,
  },
  chipLabel: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 6,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 5,
    gap: 6,
  },
  chipDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '500',
    textTransform: 'capitalize',
  },
  // Outfit image cards
  outfitCardScroll: {
    flexDirection: 'row',
    gap: 10,
    paddingRight: 8,
  },
  outfitCard: {
    width: 110,
    borderRadius: 14,
    overflow: 'hidden',
  },
  outfitCardImage: {
    width: 110,
    height: 130,
    backgroundColor: '#C8C8CD',
  },
  outfitCardMeta: {
    paddingHorizontal: 8,
    paddingVertical: 6,
    alignItems: 'center',
  },
  outfitCardLabel: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'capitalize',
    marginTop: 2,
  },
  outfitCardSub: {
    fontSize: 10,
    textTransform: 'capitalize',
    marginTop: 1,
  },

  // Typing dots
  dotsRow: {
    flexDirection: 'row',
    gap: 5,
    paddingVertical: 4,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },

  firstThinkWrap: {
    paddingHorizontal: 16,
    marginTop: 8,
  },

  // Input bar (paddingBottom is overridden inline to account for absolute tab bar on iOS)
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: 8,
  },
  textInput: {
    flex: 1,
    fontSize: 15,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 22,
    maxHeight: 110,
    lineHeight: 20,
  },
  sendButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 2,
  },

  // Wear today button
  wearButton: {
    marginTop: 10,
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  wearButtonDone: {
    borderColor: '#30D158',
  },
  wearButtonText: {
    fontSize: 13,
    fontWeight: '600',
  },
  // Weather UI
  weatherBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 16,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  weatherBtnTemp: {
    fontSize: 13,
    fontWeight: '700',
    color: '#FFF',
  },
  weatherBanner: {
    marginHorizontal: 12,
    marginBottom: 6,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  weatherBannerText: {
    fontSize: 12,
    fontWeight: '600',
  },
  weatherAdvisory: {
    fontSize: 11,
    marginTop: 2,
  },
  locationPromptBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 12,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 9,
    alignSelf: 'stretch',
  },
  locationPromptText: {
    flex: 1,
    fontSize: 13,
    fontWeight: '500',
  },
  // Modal
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'flex-end',
  },
  modalCard: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 24,
    paddingBottom: 40,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    marginBottom: 6,
  },
  modalSub: {
    fontSize: 14,
    marginBottom: 16,
    lineHeight: 20,
  },
  locationInput: {
    fontSize: 15,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: 16,
  },
  envLabel: {
    fontSize: 13,
    fontWeight: '600',
    marginBottom: 10,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  envRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 16,
  },
  envChip: {
    flex: 1,
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 10,
    gap: 4,
  },
  envChipText: {
    fontSize: 12,
    fontWeight: '600',
  },
  weatherErrorText: {
    color: '#FF453A',
    fontSize: 13,
    marginBottom: 12,
  },
  fetchWeatherBtn: {
    backgroundColor: '#0A84FF',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    marginBottom: 10,
  },
  fetchWeatherBtnText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '700',
  },
  modalCancelBtn: {
    alignItems: 'center',
    paddingVertical: 8,
  },
  modalCancelText: {
    fontSize: 14,
  },
  // Environment modal styles
  envModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  envModalCard: {
    borderRadius: 24,
    padding: 28,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 12,
  },
  envModalIcon: {
    fontSize: 52,
    marginBottom: 12,
  },
  envModalTitle: {
    fontSize: 22,
    fontWeight: '700',
    textAlign: 'center',
    marginBottom: 8,
  },
  envModalSub: {
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 24,
  },
  envLoadingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  envLoadingText: {
    fontSize: 13,
  },
  envBigBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    borderRadius: 16,
    paddingHorizontal: 20,
    paddingVertical: 16,
    marginBottom: 12,
    alignSelf: 'stretch',
  },
  envBigIcon: {
    fontSize: 30,
  },
  envBigLabel: {
    color: '#FFF',
    fontSize: 17,
    fontWeight: '700',
  },
  envBigSub: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 12,
    marginTop: 2,
  },
  envSkipBtn: {
    marginTop: 8,
    paddingVertical: 10,
  },
  envSkipText: {
    fontSize: 13,
  },
  // City input + venue modal extras
  envModalHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    marginBottom: 16,
    alignSelf: 'stretch',
  },
  envSectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 10,
    marginTop: 4,
    alignSelf: 'flex-start',
  },
  cityInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
    marginBottom: 16,
    alignSelf: 'stretch',
  },
  cityTextInput: {
    flex: 1,
    fontSize: 14,
    padding: 0,
  },
  gpsTag: {
    backgroundColor: '#34C759',
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  gpsTagText: {
    color: '#FFF',
    fontSize: 11,
    fontWeight: '700',
  },
});