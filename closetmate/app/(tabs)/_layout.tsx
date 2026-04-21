import { Tabs } from 'expo-router';
import React from 'react';
import { Platform, View, StyleSheet } from 'react-native';

import { HapticTab } from '@/components/haptic-tab';
import TabBarBackground from '@/components/ui/TabBarBackground';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Ionicons } from '@expo/vector-icons';
import { FloatingCameraButton } from '@/components/FloatingCameraButton';

export default function TabLayout() {
  const colorScheme = useColorScheme();
  const theme = colorScheme ?? 'light';
  const isDark = theme === 'dark';

  return (
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
            height: 85,
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
            height: 70,
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

      {/* 1. Stylist Tab */}
      <Tabs.Screen
        name="stylist"
        options={{
          title: 'Stylist',
          tabBarIcon: ({ color, focused }) => <Ionicons size={24} name={focused ? 'chatbubble-ellipses' : 'chatbubble-ellipses-outline'} color={color} />,
        }}
      />

      {/* 2. Closet Tab */}
      <Tabs.Screen
        name="closet"
        options={{
          title: 'Closet',
          tabBarIcon: ({ color, focused }) => <Ionicons size={24} name={focused ? 'shirt' : 'shirt-outline'} color={color} />,
        }}
      />

      {/* 3. Floating Camera Button (Middle) */}
      <Tabs.Screen
        name="add-item-placeholder"
        options={{
          title: '',
          tabBarButton: (props) => {
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const { onPress, onLongPress, ref, ...otherProps } = props;
            return (
              <View {...otherProps} style={[props.style, styles.floatingButtonContainer]}>
                <FloatingCameraButton />
              </View>
            );
          },
        }}
        listeners={{
          tabPress: (e) => {
            e.preventDefault();
          }
        }}
      />

      {/* 4. Profile Tab */}
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarIcon: ({ color, focused }) => <Ionicons size={24} name={focused ? 'person' : 'person-outline'} color={color} />,
        }}
      />

      {/* Hidden — explore still exists as a file but not shown in tabs */}
      <Tabs.Screen
        name="explore"
        options={{ href: null }}
      />

    </Tabs>
  );
}

const styles = StyleSheet.create({
  floatingButtonContainer: {
    top: -14,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 10,
  }
})
