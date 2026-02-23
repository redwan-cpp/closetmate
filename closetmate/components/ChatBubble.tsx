import React from 'react';
import { StyleSheet, View, Image } from 'react-native';
import { ThemedText } from './themed-text';
import { Colors, Spacing, BorderRadius } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

interface ChatBubbleProps {
    message: {
        id: string;
        text?: string;
        sender: 'user' | 'system';
        imageUrl?: string;
    };
}

export function ChatBubble({ message }: ChatBubbleProps) {
    const colorScheme = useColorScheme();
    const theme = colorScheme ?? 'light';
    const isUser = message.sender === 'user';

    const backgroundColor = isUser
        ? Colors[theme].tint
        : Colors[theme].surface;

    const textColor = isUser
        ? (theme === 'light' ? '#fff' : '#000') // Contrast based on tint
        : Colors[theme].text;

    if (message.imageUrl) {
        return (
            <View style={[styles.container, isUser ? styles.userContainer : styles.systemContainer]}>
                <Image source={{ uri: message.imageUrl }} style={styles.image} />
            </View>
        );
    }

    return (
        <View style={[
            styles.container,
            isUser ? styles.userContainer : styles.systemContainer,
            { backgroundColor }
        ]}>
            <ThemedText style={{ color: textColor }}>
                {message.text}
            </ThemedText>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        maxWidth: '80%',
        padding: Spacing.m,
        borderRadius: BorderRadius.l,
        marginBottom: Spacing.m,
    },
    userContainer: {
        alignSelf: 'flex-end',
        borderBottomRightRadius: 2,
    },
    systemContainer: {
        alignSelf: 'flex-start',
        borderBottomLeftRadius: 2,
    },
    image: {
        width: 200,
        height: 300,
        borderRadius: BorderRadius.m,
        backgroundColor: '#E0E0E0',
    },
});
