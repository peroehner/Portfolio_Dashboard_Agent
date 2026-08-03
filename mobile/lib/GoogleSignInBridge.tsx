import * as AuthSession from "expo-auth-session";
import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { useEffect, type ComponentType } from "react";
import { Platform } from "react-native";

import { api } from "@/lib/api";
import type { AuthUser } from "@/lib/AuthContext";

WebBrowser.maybeCompleteAuthSession();

export type MobileSession = {
  accessToken: string;
  user: AuthUser;
};

export type PromptGoogleSession = () => Promise<MobileSession>;

function googleClientIds() {
  return {
    iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim() || undefined,
    webClientId:
      process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID?.trim() ||
      process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim() ||
      undefined,
  };
}

function platformClientId(clients: ReturnType<typeof googleClientIds>): string | undefined {
  if (Platform.OS === "ios") return clients.iosClientId || clients.webClientId;
  return clients.webClientId || clients.iosClientId;
}

/**
 * On native iOS/Android, Google returns an auth `code` from the browser sheet.
 * `promptAsync()` resolves with that raw result *before* Expo's hook finishes
 * exchanging the code for tokens — so `params.id_token` is often empty there.
 * Exchange the code ourselves when needed.
 */
async function resolveGoogleIdToken(
  result: AuthSession.AuthSessionResult,
  request: AuthSession.AuthRequest | null,
  clientId: string,
): Promise<string | null> {
  if (result.type !== "success") return null;

  const direct =
    (result.params as { id_token?: string } | undefined)?.id_token ||
    result.authentication?.idToken ||
    null;
  if (direct) return direct;

  const code = (result.params as { code?: string } | undefined)?.code;
  if (!code || !request?.redirectUri) return null;

  const token = await AuthSession.exchangeCodeAsync(
    {
      clientId,
      code,
      redirectUri: request.redirectUri,
      extraParams: {
        code_verifier: request.codeVerifier || "",
      },
    },
    Google.discovery,
  );
  return token.idToken ?? null;
}

/**
 * Loaded only when Google client IDs are configured. Keeping expo-auth-session
 * out of the default AuthContext import path avoids ExpoCryptoAES crashes in
 * Expo Go / simulator when Google sign-in is not in use.
 */
export function GoogleSignInBridge({
  onReady,
}: {
  onReady: (prompt: PromptGoogleSession | null, requestReady: boolean) => void;
}) {
  const clients = googleClientIds();
  const clientId = platformClientId(clients);
  const [request, , promptAsync] = Google.useIdTokenAuthRequest({
    iosClientId: clients.iosClientId,
    webClientId: clients.webClientId,
    clientId: clients.webClientId || clients.iosClientId,
    selectAccount: true,
  });

  useEffect(() => {
    if (!request || !clientId) {
      onReady(null, false);
      return;
    }
    const prompt: PromptGoogleSession = async () => {
      const result = await promptAsync();
      if (result.type !== "success") {
        if (result.type === "dismiss" || result.type === "cancel") {
          throw new Error("__cancelled__");
        }
        throw new Error("Google sign-in did not complete.");
      }

      let idToken: string | null = null;
      try {
        idToken = await resolveGoogleIdToken(result, request, clientId);
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        throw new Error(`Google token exchange failed: ${detail}`);
      }

      if (!idToken) {
        const keys = Object.keys(result.params || {}).join(", ") || "(none)";
        throw new Error(
          `Google did not return an ID token (response keys: ${keys}). Rebuild the app after Google client IDs are set in EAS.`,
        );
      }

      const session = await api.exchangeGoogleIdToken(idToken);
      return {
        accessToken: session.accessToken,
        user: {
          id: session.user.id,
          email: session.user.email,
          name: session.user.name,
          picture: session.user.picture,
          plan: session.user.plan,
        },
      };
    };
    onReady(prompt, true);
  }, [onReady, promptAsync, request, clientId]);

  return null;
}

export type GoogleSignInBridgeComponent = ComponentType<{
  onReady: (prompt: PromptGoogleSession | null, requestReady: boolean) => void;
}>;
