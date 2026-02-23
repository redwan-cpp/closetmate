import React from 'react';
import { StyleSheet, Image, TouchableOpacity, Dimensions } from 'react-native';
import { Spacing, BorderRadius } from '@/constants/theme';

const { width } = Dimensions.get('window');
// 2 columns with spacing: (Width - (Margin * 3)) / 2
const cardWidth = (width - Spacing.m * 3) / 2;

interface ClothingCardProps {
    image: string;
    onPress?: () => void;
}

export function ClothingCard({ image, onPress }: ClothingCardProps) {
    return (
        <TouchableOpacity
            activeOpacity={0.8}
            style={styles.card}
            onPress={onPress}
        >
            <Image source={{ uri: image }} style={styles.image} resizeMode="cover" />
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    card: {
        width: cardWidth,
        height: cardWidth * 1.25, // Aspect ratio ~4:5
        borderRadius: BorderRadius.m,
        marginBottom: Spacing.m,
        backgroundColor: '#F5F5F5',
        overflow: 'hidden',
    },
    image: {
        width: '100%',
        height: '100%',
    },
});
