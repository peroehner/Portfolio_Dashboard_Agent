import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AddTickerModal } from "@/components/AddTickerModal";
import { PortfolioTable } from "@/components/PortfolioTable";
import { RecallFilterButton } from "@/components/RecallFilterButton";
import { Screen } from "@/components/Screen";
import { StarFilterButton } from "@/components/StarFilterButton";
import { TickerFilterInput } from "@/components/TickerFilterInput";
import { api } from "@/lib/api";
import { usePersistedSymbolFilter } from "@/lib/usePersistedSymbolFilter";
import { useSymbolFilterMatch } from "@/lib/useSymbolFilterMatch";
import {
  buildPortfolioRows,
  sortPortfolioRows,
  type PortfolioSortState,
} from "@/lib/portfolioTable";
import { colors, radii, spacing } from "@/lib/theme";
import type { Assessment, Holding } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

type PortfolioMode = "all" | "holdings" | "watch";

function pillActiveStyle(active: boolean) {
  return active
    ? { backgroundColor: colors.surfaceAlt, borderColor: colors.accent, opacity: 1 }
    : { backgroundColor: colors.surface, borderColor: colors.border, opacity: 0.9 };
}

export default function PortfolioScreen() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const { symbol: symbolParam } = useLocalSearchParams<{ symbol?: string }>();
  const isLandscape = width > height;
  const { filter, setFilter, lastFilter, applyLast, canRecall } = usePersistedSymbolFilter();
  const [mode, setMode] = useState<PortfolioMode>("all");
  const [sort, setSort] = useState<PortfolioSortState>({ key: null, direction: null });
  const [addOpen, setAddOpen] = useState(false);
  const [addHint, setAddHint] = useState<string | null>(null);
  const [addedSymbol, setAddedSymbol] = useState<string | null>(null);
  const [pullRefreshing, setPullRefreshing] = useState(false);
  const { data, loading, error, refresh } = useApiQuery(
    async () => {
      const [portfolio, assessments, holdings] = await Promise.all([
        api.portfolio(),
        api.assessmentsOverview(),
        api.holdings(),
      ]);
      return { portfolio, assessments, holdings };
    },
    [],
  );

  useEffect(() => {
    const sym = typeof symbolParam === "string" ? symbolParam.trim().toUpperCase() : "";
    if (sym) setFilter(sym);
  }, [symbolParam, setFilter]);

  // Returning from Symbol details should reflect freshly saved thresholds.
  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const assessmentBySymbol = useMemo(() => {
    const map = new Map<string, Assessment>();
    for (const item of data?.assessments?.assessments ?? []) {
      map.set(item.symbol, item);
    }
    return map;
  }, [data?.assessments]);

  const holdingBySymbol = useMemo(() => {
    const map = new Map<string, Holding>();
    for (const item of data?.holdings?.holdings ?? []) {
      map.set(item.symbol, item);
    }
    return map;
  }, [data?.holdings]);

  const matchesSymbol = useSymbolFilterMatch(filter);

  const rows = useMemo(() => {
    const symbols = [...(data?.portfolio?.symbols ?? [])].filter((row) => {
      if (!matchesSymbol(row.symbol)) return false;
      const holding = holdingBySymbol.get(row.symbol);
      const hasShares = (holding?.quantity || 0) > 0;
      if (mode === "holdings") return hasShares;
      if (mode === "watch") return !hasShares;
      return true;
    });

    const built = buildPortfolioRows(symbols, holdingBySymbol, assessmentBySymbol);
    return sortPortfolioRows(built, sort);
  }, [data?.portfolio?.symbols, filter, mode, sort, holdingBySymbol, assessmentBySymbol, matchesSymbol]);

  function handleAdded(symbol: string) {
    setMode("watch");
    setFilter(symbol);
    setAddedSymbol(symbol);
    setAddHint(`Added ${symbol} — set Target thresholds to get the most out of PDA.`);
    void refresh();
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Portfolio"
        subtitle={`${rows.length} shown · tap headers to sort · swipe columns →`}
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
        contentStyle={styles.screenContent}
        rightAction={
          <View style={styles.rightActions}>
            <Pressable
              style={styles.planBtn}
              onPress={() =>
                router.push({
                  pathname: "/trade-plan",
                  params: { mode },
                })
              }
              hitSlop={8}
            >
              <Text style={styles.planBtnText}>Buy/Sell Plan</Text>
            </Pressable>
            <Pressable
              style={styles.taxTrimBtn}
              onPress={() =>
                router.push({
                  pathname: "/tax-trim",
                  params: { mode },
                })
              }
              hitSlop={8}
            >
              <Text style={styles.taxTrimBtnText}>Tax & Trim</Text>
            </Pressable>
          </View>
        }
      >
        <View style={styles.toolbar}>
          <TickerFilterInput value={filter} onChangeFilter={setFilter} style={styles.filter} />
          <RecallFilterButton
            visible={canRecall}
            onPress={applyLast}
            lastFilter={lastFilter}
          />
          <StarFilterButton filter={filter} onChangeFilter={setFilter} />
          <Pressable
            style={[styles.pill, pillActiveStyle(mode === "all")]}
            onPress={() => setMode("all")}
          >
            <Text style={styles.pillText}>All</Text>
          </Pressable>
          <Pressable
            style={[styles.pill, pillActiveStyle(mode === "holdings")]}
            onPress={() => setMode("holdings")}
          >
            <Text style={styles.pillText}>Holdings</Text>
          </Pressable>
          <Pressable
            style={[styles.pill, pillActiveStyle(mode === "watch")]}
            onPress={() => setMode("watch")}
          >
            <Text style={styles.pillText}>Watch</Text>
          </Pressable>
          <Pressable style={styles.addBtn} onPress={() => setAddOpen(true)} hitSlop={6}>
            <Text style={styles.addBtnText}>Add</Text>
          </Pressable>
        </View>

        {addHint && addedSymbol ? (
          <View style={styles.hintBar}>
            <Text style={styles.hintText}>{addHint}</Text>
            <Pressable
              onPress={() => {
                setAddHint(null);
                router.push(`/symbol/${encodeURIComponent(addedSymbol)}`);
              }}
              hitSlop={8}
            >
              <Text style={styles.hintAction}>Open Target</Text>
            </Pressable>
            <Pressable onPress={() => setAddHint(null)} hitSlop={8}>
              <Text style={styles.hintDismiss}>Dismiss</Text>
            </Pressable>
          </View>
        ) : null}

        {rows.length === 0 && data ? (
          <Text style={styles.empty}>No symbols match the filter.</Text>
        ) : (
          <PortfolioTable
            rows={rows}
            sort={sort}
            onSortChange={setSort}
            landscape={isLandscape}
            refreshControl={
              <RefreshControl
                refreshing={pullRefreshing}
                onRefresh={() => {
                  setPullRefreshing(true);
                  void refresh().finally(() => setPullRefreshing(false));
                }}
                tintColor={colors.accent}
              />
            }
          />
        )}
      </Screen>

      <AddTickerModal
        visible={addOpen}
        onClose={() => setAddOpen(false)}
        onAdded={handleAdded}
      />
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
    paddingVertical: 6,
    fontSize: 13,
  },
  pill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  pillText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "600",
  },
  addBtn: {
    borderWidth: 1,
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  addBtnText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "700",
  },
  taxTrimBtn: {
    borderWidth: 1,
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
    borderRadius: radii.md,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  rightActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
  },
  planBtn: {
    borderWidth: 1,
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
    borderRadius: radii.md,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  planBtnText: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: "700",
  },
  taxTrimBtnText: {
    color: colors.accent,
    fontSize: 12,
    fontWeight: "700",
  },
  hintBar: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    padding: spacing.sm,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: "rgba(34,197,94,0.35)",
    backgroundColor: "rgba(34,197,94,0.1)",
    gap: 6,
  },
  hintText: {
    color: colors.text,
    fontSize: 12,
    lineHeight: 16,
  },
  hintAction: {
    color: colors.link,
    fontSize: 12,
    fontWeight: "700",
  },
  hintDismiss: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
  },
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
