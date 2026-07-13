import { useCallback, useMemo, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AlertRow } from "@/components/AlertRow";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { symbolMatchesFilter } from "@/lib/filters";
import { colors, radii, spacing } from "@/lib/theme";
import type { Alert } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

export default function AlertsScreen() {
  const [filter, setFilter] = useState("");
  const [dismissingId, setDismissingId] = useState<number | null>(null);
  const { data, loading, error, refresh } = useApiQuery<{ alerts: Alert[] }>(
    () => api.alerts("active"),
    [],
  );

  const alerts = useMemo(
    () =>
      (data?.alerts ?? []).filter((alert) => symbolMatchesFilter(alert.symbol, filter)),
    [data?.alerts, filter],
  );

  const handleDismiss = useCallback(
    async (id: number) => {
      setDismissingId(id);
      try {
        await api.dismissAlert(id);
        await refresh();
      } finally {
        setDismissingId(null);
      }
    },
    [refresh],
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Alerts"
        subtitle={`${data?.alerts?.length ?? 0} active`}
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
      >
        <TextInput
          style={styles.filter}
          placeholder="Filter tickers (comma-separated)…"
          placeholderTextColor={colors.textMuted}
          value={filter}
          onChangeText={setFilter}
          autoCapitalize="characters"
          autoCorrect={false}
        />
        <ScrollView
          refreshControl={
            <RefreshControl
              refreshing={loading && !!data}
              onRefresh={() => void refresh()}
              tintColor={colors.accent}
            />
          }
          contentContainerStyle={styles.scroll}
        >
          {alerts.length === 0 && data ? (
            <Text style={styles.empty}>No active alerts match the filter.</Text>
          ) : (
            alerts.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                onDismiss={handleDismiss}
                dismissing={dismissingId === alert.id}
              />
            ))
          )}
        </ScrollView>
      </Screen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  filter: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    color: colors.text,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 15,
  },
  scroll: { paddingBottom: spacing.xl },
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
