import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useRouter } from "expo-router";

import { useAuth, useGoogleIdTokenAuth } from "@/lib/AuthContext";
import { getApiHostLabel } from "@/lib/api";
import { colors, radii, spacing } from "@/lib/theme";

export default function LoginScreen() {
  const router = useRouter();
  const { signInWithGoogleIdToken, authRequired, signedIn, error, clearError } = useAuth();
  const [request, response, promptAsync] = useGoogleIdTokenAuth();
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const iosClientId = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID?.trim();

  useEffect(() => {
    if (signedIn) {
      router.replace("/(tabs)");
    }
  }, [signedIn, router]);

  useEffect(() => {
    if (response?.type !== "success") return;

    const idToken =
      response.params?.id_token ||
      (response as { authentication?: { idToken?: string } }).authentication?.idToken;

    if (!idToken) {
      setLocalError("Google sign-in succeeded but no id_token was returned.");
      return;
    }

    setBusy(true);
    setLocalError(null);
    clearError();
    void signInWithGoogleIdToken(String(idToken))
      .catch((err: unknown) => {
        setLocalError(err instanceof Error ? err.message : "Sign-in failed");
      })
      .finally(() => setBusy(false));
  }, [response, signInWithGoogleIdToken, clearError]);

  const displayError = localError || error;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Portfolio Dashboard</Text>
      <Text style={styles.subtitle}>
        Sign in with Google to view your portfolio on this device.
      </Text>
      <Text style={styles.host}>API: {getApiHostLabel()}</Text>

      {!authRequired ? (
        <Text style={styles.note}>
          This server does not require sign-in. You can go back to the app.
        </Text>
      ) : null}

      {!iosClientId ? (
        <Text style={styles.error}>
          Missing EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID in mobile/.env (iOS OAuth client from Google
          Cloud Console).
        </Text>
      ) : (
        <Pressable
          style={[styles.button, (!request || busy) && styles.buttonDisabled]}
          disabled={!request || busy}
          onPress={() => {
            setLocalError(null);
            clearError();
            void promptAsync();
          }}
        >
          {busy ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.buttonText}>Sign in with Google</Text>
          )}
        </Pressable>
      )}

      {displayError ? <Text style={styles.error}>{displayError}</Text> : null}

      {!authRequired ? (
        <Pressable style={styles.linkButton} onPress={() => router.replace("/(tabs)")}>
          <Text style={styles.linkText}>Continue without sign-in</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    padding: spacing.xl,
    justifyContent: "center",
    gap: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: 24,
    fontWeight: "700",
    textAlign: "center",
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: 15,
    textAlign: "center",
    lineHeight: 22,
  },
  host: {
    color: colors.textMuted,
    fontSize: 12,
    textAlign: "center",
    marginBottom: spacing.lg,
  },
  button: {
    backgroundColor: colors.text,
    borderRadius: radii.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: colors.bg,
    fontWeight: "600",
    fontSize: 16,
  },
  error: {
    color: colors.danger,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
  note: {
    color: colors.warning,
    fontSize: 14,
    textAlign: "center",
  },
  linkButton: {
    marginTop: spacing.lg,
    alignItems: "center",
  },
  linkText: {
    color: colors.link,
    fontSize: 15,
  },
});
