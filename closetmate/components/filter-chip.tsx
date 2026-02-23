import React from 'react';
import { StyleSheet, TouchableOpacity } from 'react-native';
import { ThemedText } from './themed-text';
import { Colors, Spacing, BorderRadius } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

interface FilterChipProps {
    label: string;
    selected?: boolean;
    onPress?: () => void;
}

export function FilterChip({ label, selected, onPress }: FilterChipProps) {
    const colorScheme = useColorScheme();
    const theme = colorScheme ?? 'light';

    const backgroundColor = selected
        ? Colors[theme].tint
        : (theme === 'light' ? '#F0F0F0' : '#333');

    const textColor = selected
        ? (theme === 'light' ? '#FFFFFF' : '#000000')
        : Colors[theme].text;

    return (
        <TouchableOpacity
            style={[styles.container, { backgroundColor }]}
            onPress={onPress}
            activeOpacity={0.7}
        >
            <ThemedText style={[styles.text, { color: textColor }]}>
                {label}
            </ThemedText>
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    container: {
        paddingHorizontal: Spacing.m,
        paddingVertical: Spacing.s,
        borderRadius: BorderRadius.round,
        marginRight: Spacing.s,
    },
    text: {
        fontSize: 14,
        fontWeight: '500',
    }
});
