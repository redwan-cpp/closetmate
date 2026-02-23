import { View } from 'react-native';

// This is a shim for the TabBarBackground component.
// On iOS, you might want to use expo-blur's BlurView here and explicitely install expo-blur.
// Currently using a simple View which fits the transparent background style in _layout.tsx
export default function TabBarBackground() {
    return (
        <View
            style={{
                flex: 1,
                backgroundColor: 'transparent',
            }}
        />
    );
}

export function useBottomTabOverflow() {
    return 0;
}
