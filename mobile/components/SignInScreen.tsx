import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/lib/AuthContext";
import { getApiHostLabel } from "@/lib/api";
import { colors, radii, spacing } from "@/lib/theme";

export function SignInScreen() {
  const { signInWithGoogle, signingIn, error } = useAuth();

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.card}>
        <Text style={styles.title}>Portfolio Dashboard</Text>
        <Text style={styles.subtitle}>
          Sign in with Google to open your own portfolio. Each account is isolated — you never see
          another tester's holdings.
        </Text>
        <Pressable
          style={({ pressed }) => [styles.button, pressed && styles.buttonPressed, signingIn && styles.buttonDisabled]}
          onPress={() => void signInWithGoogle()}
          disabled={signingIn}
          accessibilityRole="button"
        >
          {signingIn ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.buttonText}>Sign in with Google</Text>
          )}
        </Pressable>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <Text style={styles.host}>{getApiHostLabel()}</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.bg,
    justifyContent: "center",
    padding: spacing.lg,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.xl,
    gap: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: 22,
    fontWeight: "700",
    textAlign: "center",
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center",
  },
  button: {
    marginTop: spacing.sm,
    backgroundColor: colors.text,
    borderRadius: radii.md,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonPressed: { opacity: 0.88 },
  buttonDisabled: { opacity: 0.7 },
  buttonText: {
    color: colors.bg,
    fontSize: 16,
    fontWeight: "700",
  },
  error: {
    color: colors.danger,
    fontSize: 13,
    textAlign: "center",
  },
  host: {
    color: colors.textMuted,
    fontSize: 11,
    textAlign: "center",
    marginTop: spacing.xs,
  },
});
