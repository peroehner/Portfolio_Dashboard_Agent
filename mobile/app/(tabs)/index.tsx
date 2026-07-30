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

function signedMoney(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatMoney(Math.abs(value))}`;
}

function dayChangeHint(dayValue?: number | null, dayPct?: number | null): string | undefined {
  if (dayValue == null && dayPct == null) return undefined;
  const valueText = dayValue != null ? signedMoney(dayValue) : "";
  const pctText = dayPct != null ? `(${formatPct(dayPct, 2)})` : "";
  const combined = [valueText, pctText].filter(Boolean).join(" ");
  return combined ? `${combined} Day` : undefined;
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

  const projectedRows = [
    {
      key: "analyst",
      label: "Projected 1Y mean target valuation",
      value: data?.totalAnalystTargetValue,
      pct: data?.totalAnalystUpsidePct,
      color: colors.buy,
    },
    {
      key: "personal",
      label: "Projected personal target valuation",
      value: data?.totalPersonalTargetValue,
      pct: data?.totalPersonalUpsidePct,
      color: "#a78bfa",
    },
    {
      key: "roc",
      label: "Projected annual return on capital (ROC)",
      value: data?.totalProjectedRoc,
      pct: data?.totalProjectedRocPct,
      color: colors.warning,
    },
    {
      key: "planned",
      label: "Projected valuation if planned trades execute",
      value: data?.simulation?.projectedValuation,
      pct: data?.simulation?.projectedUpsidePct,
      color: colors.link,
    },
  ].filter((row) => row.value != null);

  const projectionMax = Math.max(
    data?.totalMarketValue ?? 0,
    ...projectedRows.map((row) => row.value ?? 0),
    1,
  );
  const plannedMeta =
    data?.simulation && data.simulation.projectedValuation != null
      ? [
          data.simulation.savedAt ? formatShortDateTime(data.simulation.savedAt) : null,
          `${data.simulation.scopeCount ?? 0} symbols`,
          `${data.simulation.buyLegs ?? 0} buys`,
          `${data.simulation.sellLegs ?? 0} sells`,
          data.simulation.netCashFlow != null
            ? `Net cash flow ${signedMoney(data.simulation.netCashFlow)}`
            : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  const progressSection = (
    <View style={[styles.section, isWide && styles.sectionFlex]}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Portfolio progress</Text>
        <Pressable onPress={() => router.push("/portfolio")}>
          <Text style={styles.sectionLink}>Portfolio</Text>
        </Pressable>
      </View>
      <View style={styles.progressCard}>
        <Text style={styles.progressSubhead}>
          Current portfolio value vs projected valuations at analyst 1Y mean targets and your
          personal targets.
        </Text>
        <View style={styles.progressRow}>
          <View style={styles.progressLabelLine}>
            <Text style={styles.progressLabel}>Current aggregated valuation</Text>
            <Text style={styles.progressValue}>{formatMoney(data?.totalMarketValue)}</Text>
          </View>
          <View style={styles.progressTrack}>
            <View
              style={[
                styles.progressFill,
                {
                  width: `${Math.max(4, ((data?.totalMarketValue ?? 0) / projectionMax) * 100)}%`,
                  backgroundColor: colors.hold,
                },
              ]}
            />
          </View>
        </View>
        {projectedRows.map((row) => (
          <View style={styles.progressRow} key={row.key}>
            <View style={styles.progressLabelLine}>
              <Text style={styles.progressLabel}>{row.label}</Text>
              <Text style={[styles.progressValue, { color: pctColor(row.pct) }]}>
                {formatMoney(row.value)} {row.pct != null ? `(${formatPct(row.pct, 1)})` : ""}
              </Text>
            </View>
            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: `${Math.max(4, (((row.value ?? 0) / projectionMax) * 100))}%`,
                    backgroundColor: row.color,
                  },
                ]}
              />
            </View>
          </View>
        ))}
        {plannedMeta ? <Text style={styles.progressMeta}>{plannedMeta}</Text> : null}
      </View>
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
                  dayChangeHint(data?.totalDayChange, data?.totalDayChangePct)
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
          {progressSection}

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
  progressCard: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.xs,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  progressSubhead: {
    color: colors.textMuted,
    fontSize: 12,
    lineHeight: 16,
  },
  progressRow: {
    gap: 6,
  },
  progressLabelLine: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.sm,
  },
  progressLabel: {
    flex: 1,
    color: colors.textMuted,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  progressValue: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "700",
  },
  progressTrack: {
    height: 10,
    borderRadius: 99,
    backgroundColor: "rgba(148,163,184,0.20)",
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    borderRadius: 99,
  },
  progressMeta: {
    marginTop: 2,
    color: colors.textMuted,
    fontSize: 11,
    lineHeight: 15,
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
