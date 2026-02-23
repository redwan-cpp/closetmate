/**
 * Below are the colors that are used in the app. The colors are defined in the light and dark mode.
 */

const tintColorLight = '#1A1A1A'; // Dark charcoal for primary actions in light mode
const tintColorDark = '#FFFFFF';   // White for primary actions in dark mode

export const Colors = {
  light: {
    text: '#1A1A1A',
    textSecondary: '#666666',
    background: '#FFFFFF',
    surface: '#F8F8F8', // Slightly off-white for cards/sections
    tint: tintColorLight,
    icon: '#1A1A1A',
    tabIconDefault: '#CCCCCC',
    tabIconSelected: tintColorLight,
    border: '#E5E5E5',
    error: '#D32F2F',
    success: '#388E3C',
    primary: '#1A1A1A',
    secondary: '#F0F0F0',
  },
  dark: {
    text: '#FFFFFF',
    textSecondary: '#A0A0A0',
    background: '#000000',
    surface: '#121212', // Dark grey for cards/sections
    tint: tintColorDark,
    icon: '#FFFFFF',
    tabIconDefault: '#555555',
    tabIconSelected: tintColorDark,
    border: '#333333',
    error: '#EF5350',
    success: '#66BB6A',
    primary: '#FFFFFF',
    secondary: '#1A1A1A',
  },
};

export const Spacing = {
  xs: 4,
  s: 8,
  m: 16,
  l: 24,
  xl: 32,
  xxl: 48,
};

export const BorderRadius = {
  s: 4,
  m: 8,
  l: 16,
  xl: 24,
  round: 9999,
};

export const Typography = {
  title: {
    fontSize: 32,
    fontWeight: '700' as '700',
    lineHeight: 38,
    letterSpacing: -0.5,
  },
  subtitle: {
    fontSize: 24,
    fontWeight: '600' as '600',
    lineHeight: 30,
    letterSpacing: -0.3,
  },
  heading: {
    fontSize: 20,
    fontWeight: '600' as '600',
    lineHeight: 26,
  },
  body: {
    fontSize: 16,
    fontWeight: '400' as '400',
    lineHeight: 24,
  },
  caption: {
    fontSize: 14,
    fontWeight: '400' as '400',
    lineHeight: 20,
    color: '#666666',
  },
  button: {
    fontSize: 16,
    fontWeight: '600' as '600',
    lineHeight: 24,
  },
};
