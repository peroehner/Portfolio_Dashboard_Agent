import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";

import { api, ApiError, setAccessToken } from "@/lib/api";
import type { PromptGoogleSession } from "@/lib/GoogleSignInBridge";

const TOKEN_KEY = "pda.mobile.accessToken";

export interface AuthUser {
  id: number;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
  plan?: string | null;
}

interface AuthContextValue {
  ready: boolean;
  authEnabled: boolean;
  /** True when Expo Google client IDs are present (required for Sign in with Google). */
  googleConfigured: boolean;
  user: AuthUser | null;
  accessToken: string | null;
  signingIn: boolean;
  error: string | null;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function googleClientIds() {
  return {
    iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim() || undefined,
    webClientId:
      process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID?.trim() ||
      process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim() ||
      undefined,
  };
}

function isGoogleConfigured(): boolean {
  const clients = googleClientIds();
  return Boolean(clients.iosClientId || clients.webClientId);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setTokenState] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const googleConfigured = isGoogleConfigured();
  const googlePromptRef = useRef<PromptGoogleSession | null>(null);
  const [, setGoogleReady] = useState(false);
  const [GoogleBridge, setGoogleBridge] = useState<ComponentType<{
    onReady: (prompt: PromptGoogleSession | null, requestReady: boolean) => void;
  }> | null>(null);

  const applyToken = useCallback(async (token: string | null) => {
    setTokenState(token);
    setAccessToken(token);
    if (token) {
      await AsyncStorage.setItem(TOKEN_KEY, token);
    } else {
      await AsyncStorage.removeItem(TOKEN_KEY);
    }
  }, []);

  const refreshMe = useCallback(async () => {
    await api.wake();
    const me = await api.me();
    setAuthEnabled(Boolean(me.authEnabled));
    if (me.user) {
      setUser({
        id: me.user.id,
        email: me.user.email,
        name: me.user.name,
        picture: me.user.picture,
        plan: me.user.plan,
      });
    } else {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stored = await AsyncStorage.getItem(TOKEN_KEY);
        if (stored) {
          setAccessToken(stored);
          setTokenState(stored);
        }
        await api.wake();
        const me = await api.me();
        if (cancelled) return;
        setAuthEnabled(Boolean(me.authEnabled));
        if (me.user) {
          setUser({
            id: me.user.id,
            email: me.user.email,
            name: me.user.name,
            picture: me.user.picture,
            plan: me.user.plan,
          });
        } else if (stored) {
          setAccessToken(null);
          setTokenState(null);
          await AsyncStorage.removeItem(TOKEN_KEY);
        }
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : "Could not restore session";
          if (err instanceof ApiError && err.status === 401) {
            setAuthEnabled(true);
            setUser(null);
            setAccessToken(null);
            setTokenState(null);
            await AsyncStorage.removeItem(TOKEN_KEY);
          } else {
            // Network / cold start — keep the shell usable.
            setError(message);
          }
        }
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Dynamically load Google auth only when client IDs exist — avoids pulling
  // expo-auth-session/expo-crypto into the default Simulator/TestFlight path.
  useEffect(() => {
    if (!googleConfigured) {
      setGoogleBridge(null);
      return;
    }
    let cancelled = false;
    void import("@/lib/GoogleSignInBridge")
      .then((mod) => {
        if (!cancelled) setGoogleBridge(() => mod.GoogleSignInBridge);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Google sign-in module failed to load",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [googleConfigured]);

  const onGoogleBridgeReady = useCallback(
    (prompt: PromptGoogleSession | null, requestReady: boolean) => {
      googlePromptRef.current = prompt;
      setGoogleReady(requestReady);
    },
    [],
  );

  const signInWithGoogle = useCallback(async () => {
    setError(null);
    if (!googleConfigured) {
      setError(
        "Missing EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID / EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID in the mobile env.",
      );
      return;
    }
    const prompt = googlePromptRef.current;
    if (!prompt) {
      setError("Google sign-in is not ready yet. Try again in a moment.");
      return;
    }
    setSigningIn(true);
    try {
      const session = await prompt();
      await applyToken(session.accessToken);
      setUser(session.user);
      setAuthEnabled(true);
    } catch (err) {
      if (err instanceof Error && err.message === "__cancelled__") return;
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Sign-in failed";
      setError(message);
    } finally {
      setSigningIn(false);
    }
  }, [applyToken, googleConfigured]);

  const signOut = useCallback(async () => {
    setError(null);
    try {
      await api.mobileLogout();
    } catch {
      // Best-effort revoke; always clear local session.
    }
    await applyToken(null);
    setUser(null);
  }, [applyToken]);

  const value = useMemo<AuthContextValue>(
    () => ({
      ready,
      authEnabled,
      googleConfigured,
      user,
      accessToken,
      signingIn,
      error,
      signInWithGoogle,
      signOut,
      refreshMe,
    }),
    [
      ready,
      authEnabled,
      googleConfigured,
      user,
      accessToken,
      signingIn,
      error,
      signInWithGoogle,
      signOut,
      refreshMe,
    ],
  );

  return (
    <AuthContext.Provider value={value}>
      {GoogleBridge ? <GoogleBridge onReady={onGoogleBridgeReady} /> : null}
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}

/**
 * Gate the app behind Google sign-in only when auth is on, the user has no
 * session, and Google client IDs are configured. If Google isn't configured,
 * fall through so MOBILE_DEV_TOKEN / existing sessions can still work.
 */
export function needsSignIn(auth: AuthContextValue): boolean {
  return auth.ready && auth.authEnabled && !auth.user && auth.googleConfigured;
}
