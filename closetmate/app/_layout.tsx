import { Stack } from "expo-router";
import { AuthProvider } from "@/src/context/AuthContext";

export default function Layout() {
  return (
    <AuthProvider>
      <Stack>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="add-item" options={{ headerShown: false, presentation: 'modal' }} />
        <Stack.Screen name="login" options={{ headerShown: false }} />
        <Stack.Screen name="register" options={{ headerShown: false }} />
        {/* register-face and register-body are unused — registration is handled in register.tsx */}
      </Stack>
    </AuthProvider>
  );
}
