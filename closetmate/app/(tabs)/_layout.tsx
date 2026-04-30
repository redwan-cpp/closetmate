import { Tabs, usePathname } from 'expo-router';
import React from 'react';
import { Platform, View, StyleSheet } from 'react-native';

import { HapticTab } from '@/components/haptic-tab';
import TabBarBackground from '@/components/ui/TabBarBackground';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Ionicons } from '@expo/vector-icons';
import { FloatingCameraButton } from '@/components/FloatingCameraButton';

// Must match the tabBarStyle heights below
const TAB_BAR_HEIGHT_IOS = 85;
const TAB_BAR_HEIGHT_ANDROID = 70;
const TAB_BAR_HEIGHT = Platform.OS === 'ios' ? TAB_BAR_HEIGHT_IOS : TAB_BAR_HEIGHT_ANDROID;

/**
 * Renders the floating camera button only when the Closet tab is active.
 * Positioned at the bottom-right corner, floating above the tab bar.
 */
function ClosetCameraButton() {
  const pathname = usePathname();
  const isCloset = pathname === '/closet' || pathname.endsWith('/closet');
  if (!isCloset) return null;

  return (
    <View style={styles.cameraButtonWrapper} pointerEvents="box-none">
      <FloatingCameraButton />
    </View>
  );
}

export default function TabLayout() {
  const colorScheme = useColorScheme();
  const theme = colorScheme ?? 'light';
  const isDark = theme === 'dark';

  return (
    <View style={{ flex: 1 }}>
      <Tabs
        screenOptions={{
          tabBarActiveTintColor: Colors[theme].tint,
          tabBarInactiveTintColor: isDark ? '#888' : '#999',
          headerShown: false,
          tabBarButton: HapticTab,
          tabBarBackground: TabBarBackground,
          tabBarStyle: Platform.select({
            ios: {
              position: 'absolute',
              height: TAB_BAR_HEIGHT_IOS,
              paddingBottom: 25,
              paddingTop: 10,
              borderTopWidth: 0,
              backgroundColor: isDark ? '#000000' : '#FFFFFF',
              shadowColor: '#000',
              shadowOffset: { width: 0, height: -2 },
              shadowOpacity: 0.1,
              shadowRadius: 4,
            },
            default: {
              height: TAB_BAR_HEIGHT_ANDROID,
              paddingBottom: 10,
              paddingTop: 10,
              backgroundColor: isDark ? '#000000' : '#FFFFFF',
              borderTopWidth: 0,
              elevation: 8,
            },
          }),
          tabBarLabelStyle: {
            fontSize: 10,
            fontWeight: '600',
            marginTop: 2,
          },
        }}>

        {/* 1. Stylist */}
        <Tabs.Screen
          name="stylist"
          options={{
            title: 'Stylist',
            tabBarIcon: ({ color, focused }) => (
              <Ionicons size={24} name={focused ? 'chatbubble-ellipses' : 'chatbubble-ellipses-outline'} color={color} />
            ),
          }}
        />

        {/* 2. Closet */}
        <Tabs.Screen
          name="closet"
          options={{
            title: 'Closet',
            tabBarIcon: ({ color, focused }) => (
              <Ionicons size={24} name={focused ? 'shirt' : 'shirt-outline'} color={color} />
            ),
          }}
        />

        {/* 3. Profile */}
        <Tabs.Screen
          name="profile"
          options={{
            title: 'Profile',
            tabBarIcon: ({ color, focused }) => (
              <Ionicons size={24} name={focused ? 'person' : 'person-outline'} color={color} />
            ),
          }}
        />

        {/* Hidden — not shown in tab bar */}
        <Tabs.Screen name="explore" options={{ href: null }} />
        <Tabs.Screen name="add-item-placeholder" options={{ href: null }} />

      </Tabs>

      {/* Floating camera button — bottom-right, above tab bar, Closet tab only */}
      <ClosetCameraButton />
    </View>
  );
}

const styles = StyleSheet.create({
  cameraButtonWrapper: {
    position: 'absolute',
    right: 20,
    bottom: TAB_BAR_HEIGHT + 16,
    zIndex: 100,
  },
});
