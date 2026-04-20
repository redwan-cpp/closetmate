/**
 * src/context/AuthContext.tsx
 * Global auth state — persisted in AsyncStorage.
 */
import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

interface AuthState {
  token: string | null;
  user_id: string | null;
  isLoaded: boolean;
}

interface AuthContextValue extends AuthState {
  signIn: (token: string, user_id: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = 'closetmate_auth';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>({ token: null, user_id: null, isLoaded: false });

  // Load persisted session on mount
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        if (raw) {
          const parsed = JSON.parse(raw) as { token: string; user_id: string };
          setAuth({ token: parsed.token, user_id: parsed.user_id, isLoaded: true });
        } else {
          setAuth((prev) => ({ ...prev, isLoaded: true }));
        }
      })
      .catch(() => setAuth((prev) => ({ ...prev, isLoaded: true })));
  }, []);

  const signIn = async (token: string, user_id: string) => {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user_id }));
    setAuth({ token, user_id, isLoaded: true });
  };

  const signOut = async () => {
    await AsyncStorage.removeItem(STORAGE_KEY);
    setAuth({ token: null, user_id: null, isLoaded: true });
  };

  return (
    <AuthContext.Provider value={{ ...auth, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
