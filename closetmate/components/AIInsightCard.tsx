import React from 'react';
import { StyleSheet, View } from 'react-native';
import { ThemedText } from './themed-text';
import { Colors, Spacing, BorderRadius } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Ionicons } from '@expo/vector-icons';

interface AIInsightCardProps {
    text: string;
}

export function AIInsightCard({ text }: AIInsightCardProps) {
    const colorScheme = useColorScheme();
    const theme = colorScheme ?? 'light';

    return (
        <View style={[styles.container, { backgroundColor: Colors[theme].secondary }]}>
            <View style={styles.header}>
                <Ionicons name="sparkles" size={16} color={Colors[theme].tint} />
                <ThemedText type="defaultSemiBold" style={styles.title}>Style Insight</ThemedText>
            </View>
            <ThemedText style={styles.text}>{text}</ThemedText>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        padding: Spacing.m,
        borderRadius: BorderRadius.m,
        marginBottom: Spacing.m,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: Spacing.s,
        gap: 6
    },
    title: {
        fontSize: 14,
        color: '#666',
    },
    text: {
        fontSize: 14,
        lineHeight: 20,
    }
});
