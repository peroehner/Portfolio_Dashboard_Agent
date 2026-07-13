import { useMemo, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Screen } from "@/components/Screen";
import { SymbolRow } from "@/components/SymbolRow";
import { api } from "@/lib/api";
import { symbolMatchesFilter } from "@/lib/filters";
import { colors, radii, spacing } from "@/lib/theme";
import type { Assessment, PortfolioSymbol } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

export default function PortfolioScreen() {
  const [filter, setFilter] = useState("");
  const { data, loading, error, refresh } = useApiQuery(
    async () => {
      const [portfolio, assessments] = await Promise.all([
        api.portfolio(),
        api.assessmentsOverview(),
      ]);
      return { portfolio, assessments };
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

  const symbols = useMemo(() => {
    const rows = [...(data?.portfolio?.symbols ?? [])];
    rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
    return rows.filter((row) => symbolMatchesFilter(row.symbol, filter));
  }, [data?.portfolio?.symbols, filter]);

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
              return (
                <SymbolRow
                  key={item.symbol}
                  item={{
                    ...item,
                    latestAssessment: assessment
                      ? { action: assessment.action, confidence: assessment.confidence }
                      : null,
                  }}
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
  empty: {
    color: colors.textMuted,
    textAlign: "center",
    padding: spacing.xl,
  },
});
