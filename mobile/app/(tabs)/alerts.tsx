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
import {
  alertFilterGroupKey,
  alertFilterGroupLabel,
  alertMatchesFilterGroup,
  alertTypeKey,
  compareAlertTypeChipOrder,
  sortAlertFilterGroupEntries,
} from "@/lib/alertTypes";
import { symbolMatchesFilter } from "@/lib/filters";
import { colors, radii, spacing } from "@/lib/theme";
import type { Alert } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

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
      const group = alertFilterGroupKey(alert.type || alert.alert_type);
      if (!group) continue;
      counts.set(group, (counts.get(group) ?? 0) + 1);
    }
    return sortAlertFilterGroupEntries(
      [...counts.entries()].map(([key, count]) => ({
        key,
        count,
        label: alertFilterGroupLabel(key),
      })),
    );
  }, [data?.alerts]);

  const alerts = useMemo(() => {
    const filtered = (data?.alerts ?? []).filter((alert) => {
      if (!symbolMatchesFilter(alert.symbol, filter)) return false;
      if (typeFilter && !alertMatchesFilterGroup(alert.type || alert.alert_type, typeFilter)) {
        return false;
      }
      return true;
    });
    if (!typeFilter) {
      return [...filtered].sort((a, b) => {
        const byType = compareAlertTypeChipOrder(
          alertTypeKey(a.type || a.alert_type),
          alertTypeKey(b.type || b.alert_type),
        );
        if (byType !== 0) return byType;
        return a.symbol.localeCompare(b.symbol);
      });
    }
    return filtered;
  }, [data?.alerts, filter, typeFilter]);

  const browseSymbols = useMemo(() => alerts.map((a) => a.symbol), [alerts]);

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
                browseSymbols={browseSymbols}
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
