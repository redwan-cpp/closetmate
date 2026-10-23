/**
 * src/context/AuthContext.tsx
 * Global auth state. The tokens themselves live in src/api/session.ts (secure
 * storage + automatic refresh); this context only tells the UI who is signed in.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState, ReactNode } from 'react';
import { logoutServer } from '@/src/api/auth';
import { clearSession, getSession, loadSession, onSignedOut, saveSession, Session } from '@/src/api/session';
import { clearCloset } from '@/src/state/closetCache';

interface AuthState {
  /** Access token captured at sign-in. Use it only as a "signed in" flag — requests go through authFetch. */
  token: string | null;
  user_id: string | null;
  isLoaded: boolean;
}

interface AuthContextValue extends AuthState {
  signIn: (session: Session) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const SIGNED_OUT: AuthState = { token: null, user_id: null, isLoaded: true };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>({ token: null, user_id: null, isLoaded: false });

  useEffect(() => {
    let active = true;

    // A rejected refresh token (revoked / expired / reused) signs the UI out.
    onSignedOut(() => {
      clearCloset();
      if (active) setAuth(SIGNED_OUT);
    });

    loadSession().then((session) => {
      if (!active) return;
      setAuth(
        session
          ? { token: session.accessToken, user_id: session.userId, isLoaded: true }
          : SIGNED_OUT
      );
    });

    return () => {
      active = false;
      onSignedOut(null);
    };
  }, []);

  const signIn = useCallback(async (session: Session) => {
    await saveSession(session);
    setAuth({ token: session.accessToken, user_id: session.userId, isLoaded: true });
  }, []);

  const signOut = useCallback(async () => {
    const refreshToken = getSession()?.refreshToken;
    await clearSession();
    clearCloset();
    setAuth(SIGNED_OUT);
    // Revoke server-side too, without making the user wait for it.
    if (refreshToken) logoutServer(refreshToken);
  }, []);

  const value = useMemo(() => ({ ...auth, signIn, signOut }), [auth, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
