import React from 'react';
import { StyleSheet, Image, View, Dimensions, TouchableOpacity } from 'react-native';
import { ThemedText } from './themed-text';
import { ThemedView } from './themed-view';
import { Colors, Spacing, BorderRadius } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Ionicons } from '@expo/vector-icons';

const { width } = Dimensions.get('window');

interface OutfitCardProps {
    image: string; // URL for the main collage image
    title: string;
    description: string; // "Why it works" text
    onPress?: () => void;
    onWearPress?: () => void;
}

export function OutfitCard({ image, title, description, onPress, onWearPress }: OutfitCardProps) {
    const colorScheme = useColorScheme();
    const theme = colorScheme ?? 'light';
    const isDark = theme === 'dark';

    return (
        <TouchableOpacity onPress={onPress} activeOpacity={0.95}>
            <ThemedView style={[styles.card, { backgroundColor: isDark ? '#1C1C1E' : '#FFFFFF' }]}>
                {/* Hero Image / Collage */}
                <Image source={{ uri: image }} style={styles.image} resizeMode="cover" />

                <View style={styles.content}>
                    {/* Title */}
                    <ThemedText type="subtitle" style={styles.title}>
                        {title}
                    </ThemedText>

                    {/* Why it works */}
                    <ThemedText style={styles.sectionHeader}>WHY IT WORKS</ThemedText>
                    <ThemedText style={styles.description}>
                        {description}
                    </ThemedText>

                    {/* CTA Button */}
                    <TouchableOpacity
                        style={[styles.wearButton, { backgroundColor: Colors[theme].tint }]}
                        onPress={onWearPress}
                        activeOpacity={0.8}
                    >
                        <ThemedText style={styles.wearButtonText}>
                            I’m wearing this today
                        </ThemedText>
                    </TouchableOpacity>
                </View>
            </ThemedView>
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    card: {
        width: width * 0.85, // Editorial width inside chat
        borderRadius: BorderRadius.l,
        overflow: 'hidden',
        marginVertical: Spacing.s,
        shadowColor: '#000',
        shadowOffset: {
            width: 0,
            height: 2,
        },
        shadowOpacity: 0.1,
        shadowRadius: 8,
        elevation: 3,
        borderWidth: 1,
        borderColor: 'rgba(150,150,150,0.1)',
    },
    image: {
        width: '100%',
        height: 350, // Tall editorial image
        backgroundColor: '#E0E0E0',
    },
    content: {
        padding: Spacing.l,
    },
    title: {
        marginBottom: Spacing.m,
        fontSize: 20,
    },
    sectionHeader: {
        fontSize: 11,
        fontWeight: '700',
        letterSpacing: 1,
        marginBottom: Spacing.xs,
        opacity: 0.6,
        textTransform: 'uppercase',
    },
    description: {
        fontSize: 15,
        lineHeight: 22,
        opacity: 0.8,
        marginBottom: Spacing.xl,
    },
    wearButton: {
        paddingVertical: 14,
        borderRadius: BorderRadius.m,
        alignItems: 'center',
        justifyContent: 'center',
    },
    wearButtonText: {
        color: 'white',
        fontWeight: '600',
        fontSize: 16,
    },
});
