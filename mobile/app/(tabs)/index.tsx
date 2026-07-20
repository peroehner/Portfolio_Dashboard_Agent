import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AlertRow } from "@/components/AlertRow";
import { AllocationChart } from "@/components/AllocationChart";
import { KpiCard } from "@/components/KpiCard";
import { Screen } from "@/components/Screen";
import type { AllocationMode } from "@/lib/allocationChart";
import { api, getApiHostLabel, showApiHostInDev } from "@/lib/api";
import { formatMoney, formatPct, formatShortDateTime, pctColor } from "@/lib/format";
import { openSymbol } from "@/lib/symbolBrowseSession";
import { colors, spacing } from "@/lib/theme";
import { useApiQuery } from "@/lib/useApiQuery";

function performerHint(gainPct?: number | null, gain?: number | null): string | undefined {
  if (gainPct == null && gain == null) return undefined;
  const parts: string[] = [];
  if (gainPct != null) parts.push(formatPct(gainPct));
  if (gain != null) parts.push(formatMoney(gain, true));
  return parts.join(" · ");
}

export default function OverviewScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const [allocationMode, setAllocationMode] = useState<AllocationMode>("top5");
  const { data, loading, error, refresh } = useApiQuery(() => api.overview(), []);

  const cellWidth = useMemo(() => {
    const pad = spacing.lg * 2;
    const gaps = spacing.sm * 2;
    return Math.floor((width - pad - gaps) / 3);
  }, [width]);

  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (data?.pricesAsOf) parts.push(`Prices ${formatShortDateTime(data.pricesAsOf)}`);
    if (showApiHostInDev()) parts.push(getApiHostLabel());
    return parts.join(" · ");
  }, [data?.pricesAsOf]);

  const recentAlerts = (data?.alerts ?? []).slice(0, isWide ? 5 : 3);
  const hasAlerts = recentAlerts.length > 0;

  const alertsSection = hasAlerts ? (
    <View style={[styles.section, isWide && styles.sectionFlex]}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Recent alerts</Text>
        <Pressable onPress={() => router.push("/alerts")}>
          <Text style={styles.sectionLink}>See all</Text>
        </Pressable>
      </View>
      {recentAlerts.map((alert) => (
        <AlertRow
          key={alert.id}
          alert={alert}
          browseSymbols={recentAlerts.map((a) => a.symbol)}
        />
      ))}
    </View>
  ) : null;

  const allocationSection = (
    <View style={[styles.section, isWide && styles.sectionFlex]}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Portfolio allocation</Text>
        <Pressable onPress={() => router.push("/portfolio")}>
          <Text style={styles.sectionLink}>Portfolio</Text>
        </Pressable>
      </View>
      <AllocationChart
        holdings={data?.holdings}
        mode={allocationMode}
        onModeChange={setAllocationMode}
      />
    </View>
  );

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
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Market value"
                value={formatMoney(data?.totalMarketValue, true)}
                hint={
                  data?.totalDayChangePct != null
                    ? `${formatPct(data.totalDayChangePct)} today`
                    : undefined
                }
                valueColor={pctColor(data?.totalDayChangePct)}
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Best Performer"
                value={data?.bestPerformer?.symbol ?? "—"}
                hint={performerHint(data?.bestPerformer?.gainPct, data?.bestPerformer?.gain)}
                valueColor={pctColor(data?.bestPerformer?.gainPct)}
                onPress={
                  data?.bestPerformer?.symbol
                    ? () => openSymbol(data.bestPerformer!.symbol, undefined, "summary")
                    : undefined
                }
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Positions"
                value={String(data?.holdingCount ?? "—")}
                hint={`${data?.symbolCount ?? 0} tracked · ${data?.watchlistOnlyCount ?? 0} watch`}
                onPress={() => router.push("/portfolio")}
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Unrealized gain"
                value={formatMoney(data?.unrealizedGain, true)}
                hint={formatPct(data?.unrealizedGainPct)}
                valueColor={pctColor(data?.unrealizedGainPct)}
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Best Performer YTD"
                value={data?.bestYtdPerformer?.symbol ?? "—"}
                hint={performerHint(data?.bestYtdPerformer?.gainPct, data?.bestYtdPerformer?.gain)}
                valueColor={pctColor(data?.bestYtdPerformer?.gainPct)}
                onPress={
                  data?.bestYtdPerformer?.symbol
                    ? () => openSymbol(data.bestYtdPerformer!.symbol, undefined, "summary")
                    : undefined
                }
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Active alerts"
                value={String(data?.activeAlerts ?? 0)}
                onPress={() => router.push("/alerts")}
              />
            </View>
          </View>

          {isWide ? (
            <View style={styles.wideRow}>
              {allocationSection}
              {alertsSection}
            </View>
          ) : (
            <>
              {alertsSection}
              {allocationSection}
            </>
          )}
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
  kpiCell: {},
  wideRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    paddingHorizontal: spacing.sm,
  },
  section: {
    marginTop: spacing.md,
  },
  sectionFlex: {
    flex: 1,
    minWidth: 0,
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
