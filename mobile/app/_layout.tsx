import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { SignInScreen } from "@/components/SignInScreen";
import { AuthProvider, needsSignIn, useAuth } from "@/lib/AuthContext";
import { StarredSymbolsProvider } from "@/lib/StarredSymbolsContext";
import { TickerSegmentsProvider } from "@/lib/TickerSegmentsContext";
import { SymbolFilterProvider } from "@/lib/usePersistedSymbolFilter";
import { colors } from "@/lib/theme";

function RootNavigator() {
  const auth = useAuth();

  if (!auth.ready) {
    return (
      <View style={styles.boot}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (needsSignIn(auth)) {
    return <SignInScreen />;
  }

  return (
    <StarredSymbolsProvider>
      <TickerSegmentsProvider>
        <SymbolFilterProvider>
          <StatusBar style="light" />
          <Stack
            screenOptions={{
              headerStyle: { backgroundColor: colors.bg },
              headerTintColor: colors.text,
              headerTitleStyle: { fontWeight: "600" },
              contentStyle: { backgroundColor: colors.bg },
            }}
          >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen
            name="symbol/[symbol]"
            options={{
              title: "Symbol",
              presentation: "card",
            }}
          />
          <Stack.Screen
            name="tax-trim"
            options={{
              title: "Tax & Trim",
              headerBackTitle: "Portfolio",
              presentation: "card",
            }}
          />
          <Stack.Screen
            name="trade-plan"
            options={{
              title: "Buy/Sell Plan",
              headerBackTitle: "Portfolio",
              presentation: "card",
            }}
          />
        </Stack>
        </SymbolFilterProvider>
      </TickerSegmentsProvider>
    </StarredSymbolsProvider>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <RootNavigator />
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
