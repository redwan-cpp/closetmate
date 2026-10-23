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

// ─────────────────────────────────────────────────────────────────────────────
// "Boutique" design tokens used by the closet, lookboards and outfit cards.
// Warm ivory + ink, soft pastel tiles that make cutouts pop, one violet accent
// (the same family as the login gradient).
// ─────────────────────────────────────────────────────────────────────────────
export const Brand = {
  ink: '#16141A',
  ivory: '#FBF8F4',        // screen background (light)
  paper: '#F6F1EA',        // lookboard "paper" — always light, so garment cutouts stay readable
  night: '#0F0E12',        // screen background (dark)
  nightCard: '#1A181E',
  hairline: 'rgba(22,20,26,0.08)',
  hairlineDark: 'rgba(255,255,255,0.10)',
  accent: '#7C3AED',
  accentSoft: '#EFE9FD',
  accentSoftDark: '#2A2145',
  // Pastel tiles. A stable tint per item id keeps the closet colourful without being noisy.
  tints: ['#F8E6EA', '#ECE6F8', '#F8F0D9', '#E3F1E9', '#E1EDF8', '#F9E9DE'],
  tintsDark: ['#2B2026', '#241F31', '#2B2820', '#1E2A24', '#1D2631', '#2D2420'],
};

/** Deterministic pastel tile colour for an item (same item, same tint, every render). */
export function tintFor(id: string, dark: boolean): string {
  let hash = 5381;
  for (let i = 0; i < id.length; i++) hash = ((hash << 5) + hash + id.charCodeAt(i)) | 0;
  const palette = dark ? Brand.tintsDark : Brand.tints;
  return palette[Math.abs(hash) % palette.length];
}

/** Soft, layered elevation (shadows are for depth; borders are for structure). */
export const Elevation = {
  card: {
    shadowColor: '#2A1F3D',
    shadowOpacity: 0.08,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3,
  },
  lifted: {
    shadowColor: '#2A1F3D',
    shadowOpacity: 0.16,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 14 },
    elevation: 8,
  },
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
