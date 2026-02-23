import React from 'react';
import { StyleSheet, Image, View, Dimensions, TouchableOpacity } from 'react-native';
import { ThemedText } from './themed-text';
import { ThemedView } from './themed-view';
import { Colors, Spacing, BorderRadius } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Ionicons } from '@expo/vector-icons';

const { width } = Dimensions.get('window');
// Two columns, slight variation if needed. identical to OutfitCard for now but kept separate for potential divergence.
const cardWidth = (width - Spacing.m * 3) / 2;

interface ExploreCardProps {
    image: string;
    title: string;
    author: string;
    likes: number;
}

export function ExploreCard({ image, title, author, likes }: ExploreCardProps) {
    const colorScheme = useColorScheme();
    const theme = colorScheme ?? 'light';
    const iconColor = Colors[theme].icon;

    return (
        <TouchableOpacity activeOpacity={0.9} style={styles.container}>
            <Image source={{ uri: image }} style={styles.image} resizeMode="cover" />
            <View style={styles.overlay}>
                {/* Gradient or subtle scrim could go here */}
            </View>
            <View style={styles.content}>
                <ThemedText type="defaultSemiBold" style={styles.title} numberOfLines={1}>{title}</ThemedText>
                <View style={styles.row}>
                    <ThemedText type="caption" style={styles.author}>{author}</ThemedText>
                    <View style={styles.likes}>
                        <Ionicons name="heart" size={12} color="#fff" />
                        <ThemedText type="caption" style={styles.likesText}>{likes}</ThemedText>
                    </View>
                </View>
            </View>
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    container: {
        width: cardWidth,
        height: 250, // Taller for explore feel
        borderRadius: BorderRadius.m,
        marginBottom: Spacing.m,
        overflow: 'hidden',
        position: 'relative',
        backgroundColor: '#f0f0f0',
    },
    image: {
        width: '100%',
        height: '100%',
    },
    overlay: {
        ...StyleSheet.absoluteFillObject,
        backgroundColor: 'rgba(0,0,0,0.2)', // Darken for text readability
    },
    content: {
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        padding: Spacing.s,
    },
    title: {
        color: '#fff',
        marginBottom: 2,
    },
    row: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
    },
    author: {
        color: '#ddd',
    },
    likes: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    likesText: {
        color: '#fff',
    }
});
