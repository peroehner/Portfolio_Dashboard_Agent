import * as Google from "expo-auth-session/providers/google";
import * as WebBrowser from "expo-web-browser";
import { useEffect, type ComponentType } from "react";

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
  const [request, , promptAsync] = Google.useIdTokenAuthRequest({
    iosClientId: clients.iosClientId,
    webClientId: clients.webClientId,
    clientId: clients.webClientId || clients.iosClientId,
  });

  useEffect(() => {
    if (!request) {
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
      const idToken =
        (result.params as { id_token?: string }).id_token ||
        (result as { authentication?: { idToken?: string | null } }).authentication?.idToken;
      if (!idToken) {
        throw new Error("Google did not return an ID token.");
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
  }, [onReady, promptAsync, request]);

  return null;
}

export type GoogleSignInBridgeComponent = ComponentType<{
  onReady: (prompt: PromptGoogleSession | null, requestReady: boolean) => void;
}>;
