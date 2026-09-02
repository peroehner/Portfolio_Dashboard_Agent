import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { AuthProvider, useAuth } from "@/lib/AuthContext";
import { StarredSymbolsProvider } from "@/lib/StarredSymbolsContext";
import { colors } from "@/lib/theme";

function AuthGate({ children }: { children: React.ReactNode }) {
  const { ready, authRequired, signedIn } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    const onLogin = segments[0] === "login";
    if (authRequired && !signedIn && !onLogin) {
      router.replace("/login");
      return;
    }
    if (signedIn && onLogin) {
      router.replace("/(tabs)");
    }
  }, [ready, authRequired, signedIn, segments, router]);

  if (!ready) {
    return (
      <View style={styles.boot}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (authRequired && !signedIn && segments[0] !== "login") {
    return (
      <View style={styles.boot}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <StarredSymbolsProvider>
        <StatusBar style="light" />
        <AuthGate>
          <Stack
            screenOptions={{
              headerStyle: { backgroundColor: colors.bg },
              headerTintColor: colors.text,
              headerTitleStyle: { fontWeight: "600" },
              contentStyle: { backgroundColor: colors.bg },
            }}
          >
            <Stack.Screen name="login" options={{ headerShown: false }} />
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen
              name="symbol/[symbol]"
              options={{
                title: "Symbol",
                presentation: "card",
              }}
            />
          </Stack>
        </AuthGate>
      </StarredSymbolsProvider>
    </AuthProvider>
  );
}

const styles = StyleSheet.create({
  boot: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
});
