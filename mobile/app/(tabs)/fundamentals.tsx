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
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { FILTER_PLACEHOLDER } from "@/lib/filters";
import { useSymbolFilterMatch } from "@/lib/useSymbolFilterMatch";
import type { FundamentalsSortState, FundamentalsTab } from "@/lib/fundamentalsTable";
import { colors, radii, spacing } from "@/lib/theme";
import { useApiQuery } from "@/lib/useApiQuery";

function tabStyle(active: boolean) {
  return active
    ? { backgroundColor: colors.surfaceAlt, borderColor: colors.accent }
    : { backgroundColor: colors.surface, borderColor: colors.border };
}

export default function FundamentalsScreen() {
  const [filter, setFilter] = useState("");
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
        </View>

        <View style={styles.tabRow}>
          <Pressable
            style={[styles.tabBtn, tabStyle(tab === "val")]}
            onPress={() => {
              setTab("val");
              setSort({ key: "range52", direction: "desc" });
            }}
          >
            <Text style={styles.tabText}>Val · Growth</Text>
          </Pressable>
          <Pressable
            style={[styles.tabBtn, tabStyle(tab === "health")]}
            onPress={() => {
              setTab("health");
              setSort({ key: null, direction: null });
            }}
          >
            <Text style={styles.tabText}>Health · Analyst</Text>
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
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  filter: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    color: colors.text,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    fontSize: 13,
  },
  tabRow: {
    flexDirection: "row",
    gap: spacing.xs,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  tabBtn: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radii.md,
    paddingVertical: 8,
    alignItems: "center",
  },
  tabText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "600",
  },
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
