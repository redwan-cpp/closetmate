import React from 'react';
import { StyleSheet, View, TouchableOpacity, Platform, ActionSheetIOS, Alert } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRouter } from 'expo-router';

export function FloatingCameraButton() {
    const router = useRouter();
    const colorScheme = useColorScheme();
    const theme = colorScheme ?? 'light';
    const isDark = theme === 'dark';

    const handleTakePhoto = async () => {
        try {
            const { status } = await ImagePicker.requestCameraPermissionsAsync();
            if (status !== 'granted') {
                Alert.alert('Permission needed', 'Camera permission is required to take photos.');
                return;
            }

            const result = await ImagePicker.launchCameraAsync({
                mediaTypes: ['images'],
                allowsEditing: false,
                quality: 0.9,
            });

            if (!result.canceled && result.assets && result.assets.length > 0) {
                router.push({
                    pathname: '/add-item',
                    params: { imageUri: result.assets[0].uri }
                });
            }
        } catch (error) {
            console.error('Error taking photo:', error);
            Alert.alert('Error', 'Failed to take photo.');
        }
    };

    const handleUploadPhoto = async () => {
        try {
            const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
            if (status !== 'granted') {
                Alert.alert('Permission needed', 'Library permission is required to select photos.');
                return;
            }

            const result = await ImagePicker.launchImageLibraryAsync({
                mediaTypes: ['images'],
                allowsEditing: false,
                quality: 0.9,
            });

            if (!result.canceled && result.assets && result.assets.length > 0) {
                router.push({
                    pathname: '/add-item',
                    params: { imageUri: result.assets[0].uri }
                });
            }
        } catch (error) {
            console.error('Error picking photo:', error);
            Alert.alert('Error', 'Failed to pick photo.');
        }
    };

    const handlePress = () => {
        if (Platform.OS === 'ios') {
            ActionSheetIOS.showActionSheetWithOptions(
                {
                    options: ['Cancel', 'Take Photo', 'Upload from Library'],
                    cancelButtonIndex: 0,
                    userInterfaceStyle: isDark ? 'dark' : 'light',
                },
                (buttonIndex) => {
                    if (buttonIndex === 1) {
                        handleTakePhoto();
                    } else if (buttonIndex === 2) {
                        handleUploadPhoto();
                    }
                }
            );
        } else {
            Alert.alert(
                'Add Item',
                'Choose an option',
                [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Take Photo', onPress: handleTakePhoto },
                    { text: 'Upload from Library', onPress: handleUploadPhoto },
                ],
                { cancelable: true }
            );
        }
    };

    return (
        <TouchableOpacity
            activeOpacity={0.85}
            onPress={handlePress}
            style={[
                styles.container,
                { backgroundColor: isDark ? '#FFFFFF' : '#1A1A1A' },
            ]}
        >
            <Ionicons
                name="add"
                size={26}
                color={isDark ? '#000000' : '#FFFFFF'}
            />
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    container: {
        width: 52,
        height: 52,
        borderRadius: 26,
        justifyContent: 'center',
        alignItems: 'center',
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.18,
        shadowRadius: 6,
        elevation: 5,
    },
});
