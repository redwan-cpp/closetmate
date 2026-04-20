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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import {
  sendChatMessage,
  ChatHistoryEntry,
  SuggestedOutfitItem,
} from '@/src/api/ai';

const { width } = Dimensions.get('window');
const DEMO_USER_ID = 'demo_user';

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

  if (item.image_url && !imgError) {
    return (
      <View style={[styles.outfitCard, { backgroundColor: isDark ? '#2C2C2E' : '#E8E8ED' }]}>
        <Image
          source={{ uri: item.image_url }}
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
}

function Bubble({ msg, isDark }: BubbleProps) {
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
          </View>
        )}
      </View>
    </View>
  );
}

// ─────────────────────────────────────────────
// Main screen
// ─────────────────────────────────────────────

export default function StylistScreen() {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [isThinking, setIsThinking] = useState(false);

  const flatRef = useRef<FlatList>(null);
  const inputRef = useRef<TextInput>(null);

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

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      flatRef.current?.scrollToEnd({ animated: true });
    }, 80);
  }, []);

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
      scrollToBottom();

      try {
        const history = buildHistory();
        const result = await sendChatMessage(DEMO_USER_ID, trimmed, history);

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
        scrollToBottom();
      }
    },
    [isThinking, buildHistory, scrollToBottom]
  );

  const handleSend = useCallback(() => sendMessage(inputText), [inputText, sendMessage]);



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
          <View style={[styles.statusDot, { backgroundColor: '#30D158' }]} />
        </View>

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
            onContentSizeChange={scrollToBottom}
            renderItem={({ item }) => <Bubble msg={item} isDark={isDark} />}
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

  // Input bar
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: 12,
    paddingVertical: 10,
    paddingBottom: Platform.OS === 'ios' ? 28 : 10,
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
});