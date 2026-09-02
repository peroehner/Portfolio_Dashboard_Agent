import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  apiFetch,
  fetchConfig,
  setApiBearerToken,
  setApiUnauthorizedHandler,
} from "@/lib/api";
import { clearAccessToken, loadStoredAccessToken, saveAccessToken } from "@/lib/authStorage";
import type { ApiConfig } from "@/lib/types";

WebBrowser.maybeCompleteAuthSession();

export interface AuthUser {
  id: number;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
  plan?: string | null;
}

interface AuthContextValue {
  ready: boolean;
  authRequired: boolean;
  signedIn: boolean;
  user: AuthUser | null;
  config: ApiConfig | null;
  signInWithGoogleIdToken: (idToken: string) => Promise<void>;
  signOut: () => Promise<void>;
  error: string | null;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface MeResponse {
  user?: AuthUser | null;
}

interface GoogleAuthResponse {
  accessToken: string;
  expiresIn?: number;
  user?: AuthUser;
}

async function fetchMe(): Promise<AuthUser | null> {
  const data = await apiFetch<MeResponse>("/me");
  return data.user ?? null;
}

async function exchangeGoogleToken(idToken: string): Promise<GoogleAuthResponse> {
  return apiFetch<GoogleAuthResponse>("/auth/google", {
    method: "POST",
    body: JSON.stringify({ idToken }),
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [config, setConfig] = useState<ApiConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const signOut = useCallback(async () => {
    setAccessToken(null);
    setUser(null);
    setApiBearerToken(null);
    await clearAccessToken();
  }, []);

  useEffect(() => {
    setApiBearerToken(accessToken);
  }, [accessToken]);

  useEffect(() => {
    setApiUnauthorizedHandler(() => {
      void signOut();
    });
    return () => setApiUnauthorizedHandler(null);
  }, [signOut]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        const cfg = await fetchConfig();
        if (cancelled) return;
        setConfig(cfg);
        const required = Boolean(cfg.authEnabled);
        setAuthRequired(required);

        const stored = await loadStoredAccessToken();
        if (stored) {
          setAccessToken(stored);
          setApiBearerToken(stored);
          try {
            const me = await fetchMe();
            if (cancelled) return;
            setUser(me);
          } catch {
            await clearAccessToken();
            setAccessToken(null);
            setApiBearerToken(null);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not reach API");
        }
      } finally {
        if (!cancelled) setReady(true);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const signInWithGoogleIdToken = useCallback(async (idToken: string) => {
    setError(null);
    const result = await exchangeGoogleToken(idToken);
    await saveAccessToken(result.accessToken);
    setAccessToken(result.accessToken);
    setApiBearerToken(result.accessToken);
    setUser(result.user ?? (await fetchMe()));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ready,
      authRequired,
      signedIn: !authRequired || Boolean(accessToken && user),
      user,
      config,
      signInWithGoogleIdToken,
      signOut,
      error,
      clearError: () => setError(null),
    }),
    [ready, authRequired, accessToken, user, config, signInWithGoogleIdToken, signOut, error],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}

/** Hook for the login screen — Google id_token request. */
export function useGoogleIdTokenAuth() {
  const iosClientId = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim();
  const webClientId =
    process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID?.trim() ||
    process.env.EXPO_PUBLIC_GOOGLE_OAUTH_CLIENT_ID?.trim() ||
    iosClientId;

  return Google.useIdTokenAuthRequest({
    iosClientId,
    webClientId,
  });
}
