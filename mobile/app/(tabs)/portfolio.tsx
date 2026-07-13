import { useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Screen } from "@/components/Screen";
import { SymbolRow } from "@/components/SymbolRow";
import { api } from "@/lib/api";
import { symbolMatchesFilter } from "@/lib/filters";
import { colors, radii, spacing } from "@/lib/theme";
import type { Assessment, Holding, PortfolioSymbol, SaiAction } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

type PortfolioMode = "all" | "holdings" | "watch";
type SortKey = "symbol" | "value" | "gainPct" | "dayChangePct" | "sai";

function actionRank(action?: SaiAction | null): number {
  const key = String(action || "").toLowerCase();
  if (key === "sell") return 4;
  if (key === "watch") return 3;
  if (key === "hold") return 2;
  if (key === "buy") return 1;
  return 0;
}

function pillActiveStyle(active: boolean) {
  return active
    ? { backgroundColor: colors.surfaceAlt, borderColor: colors.accent, opacity: 1 }
    : { backgroundColor: colors.surface, borderColor: colors.border, opacity: 0.9 };
}

export default function PortfolioScreen() {
  const [filter, setFilter] = useState("");
  const [mode, setMode] = useState<PortfolioMode>("all");
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
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

  const symbols = useMemo(() => {
    const rows = [...(data?.portfolio?.symbols ?? [])];
    const filtered = rows
      .filter((row) => symbolMatchesFilter(row.symbol, filter))
      .filter((row) => {
        const holding = holdingBySymbol.get(row.symbol);
        const hasShares = (holding?.quantity || 0) > 0;
        if (mode === "holdings") return hasShares;
        if (mode === "watch") return !hasShares;
        return true;
      });

    filtered.sort((a, b) => {
      if (sortKey === "symbol") return a.symbol.localeCompare(b.symbol);
      const ha = holdingBySymbol.get(a.symbol);
      const hb = holdingBySymbol.get(b.symbol);
      const aa = assessmentBySymbol.get(a.symbol);
      const ab = assessmentBySymbol.get(b.symbol);
      if (sortKey === "value") return (hb?.marketValue || 0) - (ha?.marketValue || 0);
      if (sortKey === "gainPct") return (hb?.gainPct || 0) - (ha?.gainPct || 0);
      if (sortKey === "dayChangePct") return (hb?.dayChangePct || 0) - (ha?.dayChangePct || 0);
      if (sortKey === "sai") return actionRank(ab?.action) - actionRank(aa?.action);
      return 0;
    });
    return filtered;
  }, [data?.portfolio?.symbols, filter, mode, sortKey, holdingBySymbol, assessmentBySymbol]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Portfolio"
        subtitle={`${data?.portfolio?.symbols?.length ?? 0} symbols`}
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
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.controls}
        >
          <View style={styles.controlGroup}>
            <Text style={styles.controlLabel}>Show</Text>
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
          </View>
          <View style={styles.controlGroup}>
            <Text style={styles.controlLabel}>Sort</Text>
            <Pressable
              style={[styles.pill, pillActiveStyle(sortKey === "symbol")]}
              onPress={() => setSortKey("symbol")}
            >
              <Text style={styles.pillText}>Symbol</Text>
            </Pressable>
            <Pressable
              style={[styles.pill, pillActiveStyle(sortKey === "value")]}
              onPress={() => setSortKey("value")}
            >
              <Text style={styles.pillText}>Value</Text>
            </Pressable>
            <Pressable
              style={[styles.pill, pillActiveStyle(sortKey === "gainPct")]}
              onPress={() => setSortKey("gainPct")}
            >
              <Text style={styles.pillText}>Gain%</Text>
            </Pressable>
            <Pressable
              style={[styles.pill, pillActiveStyle(sortKey === "dayChangePct")]}
              onPress={() => setSortKey("dayChangePct")}
            >
              <Text style={styles.pillText}>Day%</Text>
            </Pressable>
            <Pressable
              style={[styles.pill, pillActiveStyle(sortKey === "sai")]}
              onPress={() => setSortKey("sai")}
            >
              <Text style={styles.pillText}>SAI</Text>
            </Pressable>
          </View>
        </ScrollView>
        <ScrollView
          refreshControl={
            <RefreshControl
              refreshing={loading && !!data}
              onRefresh={() => void refresh()}
              tintColor={colors.accent}
            />
          }
        >
          {symbols.length === 0 && data ? (
            <Text style={styles.empty}>No symbols match the filter.</Text>
          ) : (
            symbols.map((item: PortfolioSymbol) => {
              const assessment = assessmentBySymbol.get(item.symbol);
              const holding = holdingBySymbol.get(item.symbol);
              return (
                <SymbolRow
                  key={item.symbol}
                  item={{
                    ...item,
                    latestAssessment: assessment
                      ? { action: assessment.action, confidence: assessment.confidence }
                      : null,
                  }}
                  showWeight={mode !== "watch"}
                  weightPct={holding?.weightPct ?? null}
                />
              );
            })
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
  controls: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    gap: spacing.lg,
  },
  controlGroup: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  controlLabel: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "700",
    marginRight: 2,
  },
  pill: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
  },
  pillText: {
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
