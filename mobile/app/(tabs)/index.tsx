import { useRouter } from "expo-router";
import { useMemo } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AlertRow } from "@/components/AlertRow";
import { KpiCard } from "@/components/KpiCard";
import { Screen } from "@/components/Screen";
import { SymbolRow } from "@/components/SymbolRow";
import { api, getApiHostLabel, showApiHostInDev } from "@/lib/api";
import { formatMoney, formatPct, pctColor } from "@/lib/format";
import { colors, spacing } from "@/lib/theme";
import { useApiQuery } from "@/lib/useApiQuery";

export default function OverviewScreen() {
  const router = useRouter();
  const { data, loading, error, refresh } = useApiQuery(() => api.overview(), []);

  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (data?.pricesAsOf) parts.push(`Prices ${data.pricesAsOf}`);
    if (showApiHostInDev()) parts.push(getApiHostLabel());
    return parts.join(" · ");
  }, [data?.pricesAsOf]);

  const topHoldings = useMemo(() => {
    const holdings = [...(data?.holdings ?? [])];
    holdings.sort((a, b) => (b.marketValue ?? 0) - (a.marketValue ?? 0));
    return holdings.slice(0, 8);
  }, [data?.holdings]);

  const assessmentBySymbol = useMemo(() => {
    const map = new Map<string, { action?: string; confidence?: string }>();
    for (const item of data?.latestAssessments ?? []) {
      map.set(item.symbol, { action: item.action, confidence: item.confidence });
    }
    return map;
  }, [data?.latestAssessments]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="Summary"
        subtitle={subtitle}
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
      >
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
          <View style={styles.kpiGrid}>
            <KpiCard
              label="Market value"
              value={formatMoney(data?.totalMarketValue, true)}
              hint={
                data?.totalDayChangePct != null
                  ? `${formatPct(data.totalDayChangePct)} today`
                  : undefined
              }
              valueColor={pctColor(data?.totalDayChangePct)}
            />
            <KpiCard
              label="Unrealized gain"
              value={formatMoney(data?.unrealizedGain, true)}
              hint={formatPct(data?.unrealizedGainPct)}
              valueColor={pctColor(data?.unrealizedGainPct)}
            />
            <KpiCard
              label="Positions"
              value={String(data?.holdingCount ?? "—")}
              hint={`${data?.symbolCount ?? 0} tracked · ${data?.watchlistOnlyCount ?? 0} watch`}
            />
            <KpiCard
              label="Active alerts"
              value={String(data?.activeAlerts ?? 0)}
              hint={
                data?.bestYtdPerformer
                  ? `YTD ${data.bestYtdPerformer.symbol} ${formatPct(data.bestYtdPerformer.gainPct)}`
                  : undefined
              }
            />
          </View>

          {(data?.alerts?.length ?? 0) > 0 ? (
            <View style={styles.section}>
              <View style={styles.sectionHead}>
                <Text style={styles.sectionTitle}>Recent alerts</Text>
                <Pressable onPress={() => router.push("/alerts")}>
                  <Text style={styles.sectionLink}>See all</Text>
                </Pressable>
              </View>
              {(data?.alerts ?? []).slice(0, 3).map((alert) => (
                <AlertRow key={alert.id} alert={alert} />
              ))}
            </View>
          ) : null}

          <View style={styles.section}>
            <View style={styles.sectionHead}>
              <Text style={styles.sectionTitle}>Top holdings</Text>
              <Pressable onPress={() => router.push("/portfolio")}>
                <Text style={styles.sectionLink}>Portfolio</Text>
              </Pressable>
            </View>
            {topHoldings.map((holding) => (
              <SymbolRow
                key={holding.symbol}
                item={{
                  symbol: holding.symbol,
                  currentPrice: holding.currentPrice,
                  dayChangePct: holding.dayChangePct,
                  latestAssessment: assessmentBySymbol.get(holding.symbol) ?? null,
                }}
                showWeight
                weightPct={holding.weightPct}
              />
            ))}
          </View>
        </ScrollView>
      </Screen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { paddingBottom: spacing.xl },
  kpiGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    padding: spacing.lg,
  },
  section: {
    marginTop: spacing.md,
  },
  sectionHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: "700",
  },
  sectionLink: {
    color: colors.link,
    fontSize: 14,
    fontWeight: "600",
  },
});
