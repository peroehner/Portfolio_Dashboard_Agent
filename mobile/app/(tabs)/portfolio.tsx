import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { PortfolioTable } from "@/components/PortfolioTable";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { symbolMatchesFilter } from "@/lib/filters";
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
  const { width, height } = useWindowDimensions();
  const { symbol: symbolParam } = useLocalSearchParams<{ symbol?: string }>();
  const isLandscape = width > height;
  const [filter, setFilter] = useState("");
  const [mode, setMode] = useState<PortfolioMode>("all");
  const [sort, setSort] = useState<PortfolioSortState>({ key: null, direction: null });
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
  }, [symbolParam]);

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

  const rows = useMemo(() => {
    const symbols = [...(data?.portfolio?.symbols ?? [])].filter((row) => {
      if (!symbolMatchesFilter(row.symbol, filter)) return false;
      const holding = holdingBySymbol.get(row.symbol);
      const hasShares = (holding?.quantity || 0) > 0;
      if (mode === "holdings") return hasShares;
      if (mode === "watch") return !hasShares;
      return true;
    });

    const built = buildPortfolioRows(symbols, holdingBySymbol, assessmentBySymbol);
    return sortPortfolioRows(built, sort);
  }, [data?.portfolio?.symbols, filter, mode, sort, holdingBySymbol, assessmentBySymbol]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Portfolio"
        subtitle={
          isLandscape ? undefined : `${rows.length} shown · tap headers to sort · swipe columns →`
        }
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
        contentStyle={styles.screenContent}
      >
        {!isLandscape ? (
          <View style={styles.toolbar}>
            <TextInput
              style={styles.filter}
              placeholder="Filter…"
              placeholderTextColor={colors.textMuted}
              value={filter}
              onChangeText={setFilter}
              autoCapitalize="characters"
              autoCorrect={false}
            />
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
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
