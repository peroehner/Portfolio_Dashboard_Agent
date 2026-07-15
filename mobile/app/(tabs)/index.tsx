import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
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
import { AllocationChart } from "@/components/AllocationChart";
import { KpiCard } from "@/components/KpiCard";
import { Screen } from "@/components/Screen";
import type { AllocationMode } from "@/lib/allocationChart";
import { api, getApiHostLabel, showApiHostInDev } from "@/lib/api";
import { formatMoney, formatPct, formatShortDateTime, pctColor } from "@/lib/format";
import { colors, spacing } from "@/lib/theme";
import { useApiQuery } from "@/lib/useApiQuery";

export default function OverviewScreen() {
  const router = useRouter();
  const [allocationMode, setAllocationMode] = useState<AllocationMode>("top5");
  const { data, loading, error, refresh } = useApiQuery(() => api.overview(), []);

  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (data?.pricesAsOf) parts.push(`Prices ${formatShortDateTime(data.pricesAsOf)}`);
    if (showApiHostInDev()) parts.push(getApiHostLabel());
    return parts.join(" · ");
  }, [data?.pricesAsOf]);

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
            <View style={styles.kpiCol}>
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
            </View>
            <View style={styles.kpiCol}>
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
    gap: spacing.sm,
    padding: spacing.lg,
  },
  kpiCol: {
    flex: 1,
    gap: spacing.sm,
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
