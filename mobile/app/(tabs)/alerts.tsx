import { useCallback, useMemo, useState } from "react";
import {
  Pressable,
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

/** Canonical alert_type → short filter chip label. */
const ALERT_TYPE_LABELS: Record<string, string> = {
  screener_upside: "Screener Upside",
  fib_proximity: "Fib",
  trade_above: "Trade Above",
  trade_above_near: "Trade Above Near",
  trade_below: "Trade Below",
  trade_below_near: "Trade Below Near",
};

function alertTypeKey(alert: Alert): string {
  return String(alert.type || alert.alert_type || "alert").trim().toLowerCase();
}

function alertTypeLabel(key: string): string {
  if (ALERT_TYPE_LABELS[key]) return ALERT_TYPE_LABELS[key];
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function AlertsScreen() {
  const [filter, setFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [dismissingId, setDismissingId] = useState<number | null>(null);
  const { data, loading, error, refresh } = useApiQuery<{ alerts: Alert[] }>(
    () => api.alerts("active"),
    [],
  );

  const typeOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const alert of data?.alerts ?? []) {
      const key = alertTypeKey(alert);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([key, count]) => ({ key, count, label: alertTypeLabel(key) }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [data?.alerts]);

  const alerts = useMemo(
    () =>
      (data?.alerts ?? []).filter((alert) => {
        if (!symbolMatchesFilter(alert.symbol, filter)) return false;
        if (typeFilter && alertTypeKey(alert) !== typeFilter) return false;
        return true;
      }),
    [data?.alerts, filter, typeFilter],
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

  function toggleType(key: string) {
    setTypeFilter((prev) => (prev === key ? "" : key));
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Alerts"
        subtitle={`${alerts.length} shown${data?.alerts?.length != null && alerts.length !== data.alerts.length ? ` · ${data.alerts.length} active` : " active"}`}
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
        {typeOptions.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.typeRow}
            style={styles.typeScroll}
          >
            {typeOptions.map(({ key, count, label }) => {
              const active = typeFilter === key;
              return (
                <Pressable
                  key={key}
                  style={[styles.typeChip, active && styles.typeChipActive]}
                  onPress={() => toggleType(key)}
                >
                  <Text style={[styles.typeChipText, active && styles.typeChipTextActive]}>
                    {label} · {count}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        ) : null}
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
  typeScroll: {
    flexGrow: 0,
    marginBottom: spacing.sm,
  },
  typeRow: {
    paddingHorizontal: spacing.lg,
    gap: spacing.xs,
  },
  typeChip: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
  },
  typeChipActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
  },
  typeChipText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
  },
  typeChipTextActive: {
    color: colors.accent,
  },
  scroll: { paddingBottom: spacing.xl },
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
