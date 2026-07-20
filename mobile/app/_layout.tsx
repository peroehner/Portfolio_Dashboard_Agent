import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import { StarredSymbolsProvider } from "@/lib/StarredSymbolsContext";
import { colors } from "@/lib/theme";

export default function RootLayout() {
  return (
    <StarredSymbolsProvider>
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
      </Stack>
    </StarredSymbolsProvider>
  );
}
