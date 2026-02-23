import React from 'react';
import { StyleSheet, View, Image } from 'react-native';
import { ThemedText } from './themed-text';
import { ThemedView } from './themed-view';
import { Spacing, BorderRadius } from '@/constants/theme';

interface ProfileInfoCardProps {
    name: string;
    handle: string;
    avatar: string;
    followers: string;
    following: string;
    stats: {
        items: number;
        outfits: number;
    };
}

export function ProfileInfoCard({ name, handle, avatar, followers, following, stats }: ProfileInfoCardProps) {
    return (
        <ThemedView style={styles.container}>
            <View style={styles.header}>
                <Image source={{ uri: avatar }} style={styles.avatar} />
                <View style={styles.info}>
                    <ThemedText type="title">{name}</ThemedText>
                    <ThemedText type="caption" style={styles.handle}>{handle}</ThemedText>
                    <View style={styles.statsRow}>
                        <View style={styles.stat}>
                            <ThemedText type="defaultSemiBold">{followers}</ThemedText>
                            <ThemedText type="caption">Followers</ThemedText>
                        </View>
                        <View style={styles.divider} />
                        <View style={styles.stat}>
                            <ThemedText type="defaultSemiBold">{following}</ThemedText>
                            <ThemedText type="caption">Following</ThemedText>
                        </View>
                    </View>
                </View>
            </View>

            <View style={styles.summary}>
                <View style={styles.summaryItem}>
                    <ThemedText type="heading">{stats.items}</ThemedText>
                    <ThemedText type="caption">Items</ThemedText>
                </View>
                <View style={styles.summaryItem}>
                    <ThemedText type="heading">{stats.outfits}</ThemedText>
                    <ThemedText type="caption">Outfits</ThemedText>
                </View>
            </View>
        </ThemedView>
    );
}

const styles = StyleSheet.create({
    container: {
        padding: Spacing.m,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: Spacing.l,
    },
    avatar: {
        width: 80,
        height: 80,
        borderRadius: 40,
        marginRight: Spacing.m,
        backgroundColor: '#eee',
    },
    info: {
        flex: 1,
    },
    handle: {
        marginBottom: Spacing.s,
    },
    statsRow: {
        flexDirection: 'row',
        alignItems: 'center',
    },
    stat: {
        alignItems: 'center',
    },
    divider: {
        width: 1,
        height: 20,
        backgroundColor: '#ccc',
        marginHorizontal: Spacing.m,
    },
    summary: {
        flexDirection: 'row',
        justifyContent: 'space-around',
        paddingVertical: Spacing.m,
        borderTopWidth: StyleSheet.hairlineWidth,
        borderBottomWidth: StyleSheet.hairlineWidth,
        borderColor: '#e5e5e5',
    },
    summaryItem: {
        alignItems: 'center',
    }

});
