import { View, StyleSheet } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

export default function TabBarBackground() {
    return (
        <View style={{ flex: 1, backgroundColor: 'transparent' }} />
    );
}

export function useBottomTabOverflow() {
    const insets = useSafeAreaInsets();
    return insets.bottom;
}
