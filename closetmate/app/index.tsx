import { Redirect } from 'expo-router';
import { useAuth } from '@/src/context/AuthContext';
import { View, ActivityIndicator } from 'react-native';

export default function Index() {
  const { token, isLoaded } = useAuth();

  if (!isLoaded) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0A0A0F' }}>
        <ActivityIndicator size="large" color="#7C3AED" />
      </View>
    );
  }

  return <Redirect href={token ? '/(tabs)/stylist' : '/login'} />;
}
