import React, { useEffect, useRef } from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  TouchableWithoutFeedback,
  Animated,
  StyleSheet,
  Platform,
} from 'react-native';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Colors, BorderRadius } from '@/constants/theme';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface ActionItem {
  label: string;
  onPress: () => void;
  destructive?: boolean;
}

interface ActionSheetModalProps {
  visible: boolean;
  title?: string;
  actions: ActionItem[];
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function ActionSheetModal({
  visible,
  title,
  actions,
  onClose,
}: ActionSheetModalProps) {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const C = Colors[colorScheme ?? 'light'];

  // Slide-up animation
  const slideY = useRef(new Animated.Value(300)).current;
  const backdropOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (visible) {
      Animated.parallel([
        Animated.spring(slideY, {
          toValue: 0,
          useNativeDriver: true,
          damping: 22,
          stiffness: 220,
        }),
        Animated.timing(backdropOpacity, {
          toValue: 1,
          duration: 220,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      Animated.parallel([
        Animated.timing(slideY, {
          toValue: 300,
          duration: 200,
          useNativeDriver: true,
        }),
        Animated.timing(backdropOpacity, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [visible]);

  const sheetBg = isDark ? '#1C1C1E' : '#FFFFFF';
  const separatorColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)';
  const titleColor = isDark ? '#8E8E93' : '#8E8E93';

  return (
    <Modal
      transparent
      visible={visible}
      animationType="none"
      statusBarTranslucent
      onRequestClose={onClose}
    >
      {/* Backdrop */}
      <TouchableWithoutFeedback onPress={onClose}>
        <Animated.View style={[styles.backdrop, { opacity: backdropOpacity }]} />
      </TouchableWithoutFeedback>

      {/* Sheet */}
      <Animated.View
        style={[
          styles.sheetContainer,
          { transform: [{ translateY: slideY }] },
        ]}
        pointerEvents="box-none"
      >
        <View style={[styles.sheet, { backgroundColor: sheetBg }]}>
          {/* Handle pill */}
          <View style={[styles.handle, { backgroundColor: isDark ? '#3A3A3C' : '#D1D1D6' }]} />

          {/* Optional title */}
          {!!title && (
            <>
              <Text style={[styles.title, { color: titleColor }]}>{title}</Text>
              <View style={[styles.separator, { backgroundColor: separatorColor }]} />
            </>
          )}

          {/* Action rows */}
          {actions.map((action, index) => (
            <View key={action.label}>
              <TouchableOpacity
                onPress={() => {
                  onClose();
                  // Small delay so modal closes before action executes
                  setTimeout(action.onPress, 180);
                }}
                activeOpacity={0.6}
                style={styles.actionRow}
              >
                <Text
                  style={[
                    styles.actionText,
                    {
                      color: action.destructive
                        ? '#FF3B30'
                        : C.text,
                      fontWeight: action.destructive ? '500' : '400',
                    },
                  ]}
                >
                  {action.label}
                </Text>
              </TouchableOpacity>
              {index < actions.length - 1 && (
                <View style={[styles.separator, { backgroundColor: separatorColor }]} />
              )}
            </View>
          ))}

          {/* Safe area spacer */}
          <View style={styles.safeBottom} />
        </View>
      </Animated.View>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.45)',
  },
  sheetContainer: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
  },
  sheet: {
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingTop: 10,
    overflow: 'hidden',
  },
  handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    alignSelf: 'center',
    marginBottom: 12,
  },
  title: {
    fontSize: 13,
    textAlign: 'center',
    paddingBottom: 12,
    paddingHorizontal: 20,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    marginHorizontal: 0,
  },
  actionRow: {
    paddingVertical: 18,
    paddingHorizontal: 24,
    alignItems: 'center',
  },
  actionText: {
    fontSize: 17,
    letterSpacing: -0.1,
  },
  safeBottom: {
    height: Platform.OS === 'ios' ? 28 : 16,
  },
});
