import { Text, type TextProps, StyleSheet } from 'react-native';

import { useThemeColor } from '@/hooks/use-theme-color';
import { Typography } from '@/constants/theme';

export type ThemedTextProps = TextProps & {
  lightColor?: string;
  darkColor?: string;
  type?: 'default' | 'title' | 'defaultSemiBold' | 'subtitle' | 'link' | 'caption' | 'heading';
};

export function ThemedText({
  style,
  lightColor,
  darkColor,
  type = 'default',
  ...rest
}: ThemedTextProps) {
  const color = useThemeColor({ light: lightColor, dark: darkColor }, 'text');

  return (
    <Text
      style={[
        { color },
        type === 'default' ? Typography.body : undefined,
        type === 'title' ? Typography.title : undefined,
        type === 'defaultSemiBold' ? { ...Typography.body, fontWeight: '600' } : undefined,
        type === 'subtitle' ? Typography.subtitle : undefined,
        type === 'heading' ? Typography.heading : undefined,
        type === 'caption' ? Typography.caption : undefined,
        type === 'link' ? { ...Typography.body, color: '#0a7ea4' } : undefined,
        style,
      ]}
      {...rest}
    />
  );
}
