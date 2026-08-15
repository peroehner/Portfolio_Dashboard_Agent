import { useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { FundamentalsTable } from "@/components/FundamentalsTable";
import { RecallFilterButton } from "@/components/RecallFilterButton";
import { Screen } from "@/components/Screen";
import { StarFilterButton } from "@/components/StarFilterButton";
import { api } from "@/lib/api";
import { FILTER_PLACEHOLDER } from "@/lib/filters";
import { usePersistedSymbolFilter } from "@/lib/usePersistedSymbolFilter";
import { useSymbolFilterMatch } from "@/lib/useSymbolFilterMatch";
import type { FundamentalsSortState, FundamentalsTab } from "@/lib/fundamentalsTable";
import { colors, radii, spacing } from "@/lib/theme";
import { useApiQuery } from "@/lib/useApiQuery";

function pillActiveStyle(active: boolean) {
  return active
    ? { backgroundColor: colors.surfaceAlt, borderColor: colors.accent, opacity: 1 }
    : { backgroundColor: colors.surface, borderColor: colors.border, opacity: 0.9 };
}

export default function FundamentalsScreen() {
  const { filter, setFilter, lastFilter, applyLast, canRecall } = usePersistedSymbolFilter();
  const [tab, setTab] = useState<FundamentalsTab>("val");
  const [sort, setSort] = useState<FundamentalsSortState>({
    key: "range52",
    direction: "desc",
  });
  const { data, loading, error, refresh } = useApiQuery(() => api.fundamentals(), []);
  const matchesSymbol = useSymbolFilterMatch(filter);

  const rows = useMemo(
    () => (data?.symbols ?? []).filter((row) => matchesSymbol(row.symbol)),
    [data?.symbols, matchesSymbol],
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Fundamentals"
        subtitle={`${rows.length} shown · tap headers to sort · swipe columns →`}
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
        contentStyle={styles.screenContent}
      >
        <View style={styles.toolbar}>
          <TextInput
            style={styles.filter}
            placeholder={FILTER_PLACEHOLDER}
            placeholderTextColor={colors.textMuted}
            value={filter}
            onChangeText={setFilter}
            autoCapitalize="characters"
            autoCorrect={false}
          />
          <RecallFilterButton
            visible={canRecall}
            onPress={applyLast}
            lastFilter={lastFilter}
          />
          <StarFilterButton filter={filter} onChangeFilter={setFilter} />
          <Pressable
            style={[styles.pill, pillActiveStyle(tab === "val")]}
            onPress={() => {
              setTab("val");
              setSort({ key: "range52", direction: "desc" });
            }}
          >
            <Text style={styles.pillText}>Val · Growth</Text>
          </Pressable>
          <Pressable
            style={[styles.pill, pillActiveStyle(tab === "health")]}
            onPress={() => {
              setTab("health");
              setSort({ key: null, direction: null });
            }}
          >
            <Text style={styles.pillText}>Analyst · Health</Text>
          </Pressable>
        </View>

        {rows.length === 0 && data ? (
          <Text style={styles.empty}>No symbols match the filter.</Text>
        ) : (
          <FundamentalsTable
            rows={rows}
            tab={tab}
            sort={sort}
            onSortChange={setSort}
            refreshControl={
              <RefreshControl
                refreshing={loading && !!data}
                onRefresh={() => void refresh()}
                tintColor={colors.accent}
              />
            }
          />
        )}
      </Screen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  screenContent: { flex: 1 },
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  filter: {
    flex: 1,
    minWidth: 72,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    color: colors.text,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    fontSize: 13,
  },
  pill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  pillText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "600",
  },
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
