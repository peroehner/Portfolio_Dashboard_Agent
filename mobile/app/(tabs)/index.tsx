import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
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
import {
  allocationSourceLabel,
  holdingsForAllocationSource,
  sourceBelongsToDirection,
  type AllocationMode,
  type AllocationSource,
  type ProgressDirection,
} from "@/lib/allocationChart";
import { api, getApiHostLabel, showApiHostInDev } from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";
import { formatEntryDate, formatMoney, formatPct, formatShortDateTime, pctColor } from "@/lib/format";
import { openSymbol } from "@/lib/symbolBrowseSession";
import { colors, radii, spacing } from "@/lib/theme";
import type { PastProgressWindow } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

const PRIVACY_MASK = "••••";

function privacyMoney(
  value: number | null | undefined,
  hide: boolean,
  compact = false,
): string {
  if (hide) return PRIVACY_MASK;
  return formatMoney(value, compact);
}

function pastWindowNote(window: PastProgressWindow): string {
  const parts: string[] = [];
  if (window.spyReturnPct != null) {
    parts.push(`S&P ${formatPct(window.spyReturnPct, 1)}`);
  }
  if (window.relativePct != null) {
    parts.push(`rel ${formatPct(window.relativePct, 1)} pp`);
  }
  const cov = window.coverage;
  if (
    cov?.heldTotal != null &&
    cov.heldWithPrices != null &&
    cov.heldWithPrices < cov.heldTotal
  ) {
    parts.push(`cov ${cov.heldWithPrices}/${cov.heldTotal}`);
  }
  return parts.join(" · ");
}

function performerHint(
  gainPct?: number | null,
  gain?: number | null,
  hideAmounts = false,
): string | undefined {
  if (gainPct == null && gain == null) return undefined;
  const parts: string[] = [];
  if (gainPct != null) parts.push(formatPct(gainPct));
  if (gain != null) parts.push(hideAmounts ? PRIVACY_MASK : formatMoney(gain, true));
  return parts.join(" · ");
}

function signedMoney(value?: number | null, hideAmounts = false): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (hideAmounts) return PRIVACY_MASK;
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatMoney(Math.abs(value))}`;
}

function dayChangeHint(
  dayValue?: number | null,
  dayPct?: number | null,
  hideAmounts = false,
): string | undefined {
  if (dayValue == null && dayPct == null) return undefined;
  const valueText = dayValue != null ? signedMoney(dayValue, hideAmounts) : "";
  const pctText = dayPct != null ? `(${formatPct(dayPct, 2)})` : "";
  const combined = [valueText, pctText].filter(Boolean).join(" ");
  return combined ? `${combined} Day` : undefined;
}

export default function OverviewScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const [allocationMode, setAllocationMode] = useState<AllocationMode>("top5");
  const [allocationSource, setAllocationSource] = useState<AllocationSource>("current");
  const [progressDirection, setProgressDirection] = useState<ProgressDirection>("forward");
  const [hideAmounts, setHideAmounts] = useState(false);
  const { data, loading, error, refresh } = useApiQuery(() => api.overview(), []);
  const { user, authEnabled, signOut } = useAuth();
  const [refreshedAt, setRefreshedAt] = useState("");
  const pastProgressSoftRetry = useRef(false);

  useEffect(() => {
    if (loading || !data) return;
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");
    setRefreshedAt(`${hh}:${mm}:${ss}`);
  }, [loading, data]);

  // Overview returns KPIs immediately while pastProgress warms in the background.
  // One delayed refetch picks up 1M/3M/ATH once Yahoo history is cached.
  useEffect(() => {
    if (loading || !data || data.pastProgress || pastProgressSoftRetry.current) return;
    pastProgressSoftRetry.current = true;
    const t = setTimeout(() => void refresh(), 2800);
    return () => clearTimeout(t);
  }, [loading, data, refresh]);

  const cellWidth = useMemo(() => {
    const pad = spacing.lg * 2;
    const gaps = spacing.sm * 2;
    return Math.floor((width - pad - gaps) / 3);
  }, [width]);

  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (user?.email) parts.push(user.email);
    // pricesAsOf is a market session date (YYYY-MM-DD), not a clock time.
    if (data?.pricesAsOf) parts.push(`Data session ${formatShortDateTime(data.pricesAsOf)}`);
    if (refreshedAt) parts.push(`Refreshed ${refreshedAt}`);
    if (showApiHostInDev()) parts.push(getApiHostLabel());
    return parts.join(" · ");
  }, [data?.pricesAsOf, refreshedAt, user?.email]);

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

  const allocationHoldings = useMemo(
    () => holdingsForAllocationSource(data?.holdings, data?.pastProgress, allocationSource),
    [data?.holdings, data?.pastProgress, allocationSource],
  );
  const allocationLabel = useMemo(() => {
    const label = allocationSourceLabel(allocationSource);
    return allocationSource === "simulation" ? `${label}` : label;
  }, [allocationSource]);

  const selectAllocation = (source: AllocationSource) => {
    setAllocationSource(source);
  };

  const setDirection = (direction: ProgressDirection) => {
    setProgressDirection(direction);
    if (!sourceBelongsToDirection(allocationSource, direction) && direction === "forward") {
      setAllocationSource("current");
    }
  };

  const allocationSection = (
    <View style={[styles.section, isWide && styles.sectionFlex]}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Portfolio allocation</Text>
        <View style={styles.sectionSourcePill}>
          <Text style={styles.sectionSource} numberOfLines={1}>
            {allocationLabel}
          </Text>
        </View>
      </View>
      <AllocationChart
        holdings={allocationHoldings}
        mode={allocationMode}
        onModeChange={setAllocationMode}
        hideAmounts={hideAmounts}
      />
    </View>
  );

  const projectedRows = [
    {
      key: "current" as const,
      label: "Current aggregated valuation",
      value: data?.totalMarketValue,
      pct: data?.unrealizedGainPct,
      color: colors.hold,
      allocKey: "current" as AllocationSource,
    },
    {
      key: "analyst" as const,
      label: "Projected 1Y mean target valuation",
      value: data?.totalAnalystTargetValue,
      pct: data?.totalAnalystUpsidePct,
      color: colors.buy,
      allocKey: "analyst" as AllocationSource,
    },
    {
      key: "personal" as const,
      label: "Projected personal target valuation",
      value: data?.totalPersonalTargetValue,
      pct: data?.totalPersonalUpsidePct,
      color: "#a78bfa",
      allocKey: "personal" as AllocationSource,
    },
    {
      key: "roc" as const,
      label: "Projected annual return on capital (ROC)",
      value: data?.totalProjectedRoc,
      pct: data?.totalProjectedRocPct,
      color: colors.warning,
      allocKey: null as AllocationSource | null,
    },
    {
      key: "planned" as const,
      label: "Projected valuation if planned trades execute",
      value: data?.simulation?.projectedValuation,
      pct: data?.simulation?.projectedUpsidePct,
      color: colors.link,
      allocKey: "simulation" as AllocationSource,
    },
  ].filter((row) => row.value != null);

  const projectionMax = Math.max(
    data?.totalMarketValue ?? 0,
    ...projectedRows.map((row) => row.value ?? 0),
    1,
  );
  const past = data?.pastProgress;
  const pastWindows = (["1M", "3M"] as const)
    .map((key) => {
      const w = past?.windows?.[key];
      if (!w || w.valueThen == null) return null;
      return { key, window: w };
    })
    .filter(Boolean) as Array<{ key: "1M" | "3M"; window: PastProgressWindow }>;
  const ath = past?.ath;
  const pastMax = Math.max(
    data?.totalMarketValue ?? 0,
    ath?.value ?? 0,
    ...pastWindows.map((row) => row.window.valueThen ?? 0),
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
            ? `Net cash flow ${signedMoney(data.simulation.netCashFlow, hideAmounts)}`
            : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  const athAtPeak =
    ath?.deltaPct != null && Math.abs(Number(ath.deltaPct)) < 0.05;

  const progressSection = (
    <View style={[styles.section, isWide && styles.sectionFlex]}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>Portfolio progress</Text>
        <Pressable onPress={() => router.push("/portfolio")}>
          <Text style={styles.sectionLink}>Portfolio</Text>
        </Pressable>
      </View>
      <View style={styles.progressCard}>
        <View style={styles.directionRow}>
          <Pressable
            style={[
              styles.directionBtn,
              progressDirection === "back" && styles.directionBtnActive,
            ]}
            onPress={() => setDirection("back")}
          >
            <Text
              style={[
                styles.directionText,
                progressDirection === "back" && styles.directionTextActive,
              ]}
            >
              Looking back
            </Text>
          </Pressable>
          <Pressable
            style={[
              styles.directionBtn,
              progressDirection === "forward" && styles.directionBtnActive,
            ]}
            onPress={() => setDirection("forward")}
          >
            <Text
              style={[
                styles.directionText,
                progressDirection === "forward" && styles.directionTextActive,
              ]}
            >
              Looking forward
            </Text>
          </Pressable>
        </View>
        <Text style={styles.progressHint}>
          Tap a row to show that portfolio in the allocation pie
        </Text>

        {progressDirection === "back" ? (
          <>
            <Text style={styles.progressBand}>Current holdings buy & hold vs S&P</Text>
            {pastWindows.length === 0 && !ath ? (
              <Text style={styles.progressMeta}>
                Past progress unavailable yet — populates after price history loads.
              </Text>
            ) : null}
            {pastWindows.map(({ key, window }) => {
              const active = allocationSource === key;
              return (
                <Pressable
                  key={key}
                  style={[styles.progressRow, active && styles.progressRowActive]}
                  onPress={() => selectAllocation(key)}
                >
                  <View style={styles.progressLabelLine}>
                    <Text style={styles.progressLabel}>
                      <Text style={styles.progressLabelStrong}>{key}</Text> ago
                    </Text>
                    <Text style={[styles.progressValue, { color: pctColor(window.returnPct) }]}>
                      {privacyMoney(window.valueThen, hideAmounts)}{" "}
                      {window.returnPct != null ? `(${formatPct(window.returnPct, 1)})` : ""}
                    </Text>
                  </View>
                  <View style={styles.progressTrack}>
                    <View
                      style={[
                        styles.progressFill,
                        {
                          width: `${Math.max(4, ((window.valueThen ?? 0) / pastMax) * 100)}%`,
                          backgroundColor: colors.textMuted,
                        },
                      ]}
                    />
                  </View>
                  {pastWindowNote(window) ? (
                    <Text style={styles.progressMeta}>{pastWindowNote(window)}</Text>
                  ) : null}
                </Pressable>
              );
            })}
            {ath?.value != null ? (
              <Pressable
                style={[styles.progressRow, allocationSource === "ath" && styles.progressRowActive]}
                onPress={() => selectAllocation("ath")}
              >
                <View style={styles.progressLabelLine}>
                  <Text style={[styles.progressLabel, styles.progressLabelAth]}>
                    ATH · {formatEntryDate(ath.date) || ath.date || "—"}
                  </Text>
                  <Text
                    style={[
                      styles.progressValue,
                      { color: athAtPeak ? colors.buy : pctColor(ath.deltaPct) },
                    ]}
                  >
                    {privacyMoney(ath.value, hideAmounts)}
                    {athAtPeak
                      ? " · at ATH"
                      : ath.deltaPct != null
                        ? ` (${formatPct(ath.deltaPct, 1)})${ath.deltaValue != null ? ` ${signedMoney(ath.deltaValue, hideAmounts)}` : ""}`
                        : ""}
                  </Text>
                </View>
                <View style={styles.progressTrack}>
                  <View
                    style={[
                      styles.progressFill,
                      {
                        width: `${Math.max(4, ((ath.value ?? 0) / pastMax) * 100)}%`,
                        backgroundColor: colors.warning,
                      },
                    ]}
                  />
                </View>
              </Pressable>
            ) : null}
          </>
        ) : (
          <>
            <Text style={styles.progressBand}>Targets & planned-trade projection</Text>
            {projectedRows.map((row) => {
              const interactive = row.allocKey != null;
              const active = row.allocKey != null && allocationSource === row.allocKey;
              const body = (
                <>
                  <View style={styles.progressLabelLine}>
                    <Text style={styles.progressLabel}>{row.label}</Text>
                    <Text style={[styles.progressValue, { color: pctColor(row.pct) }]}>
                      {privacyMoney(row.value, hideAmounts)}{" "}
                      {row.pct != null ? `(${formatPct(row.pct, 1)})` : ""}
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
                  {row.key === "planned" && plannedMeta ? (
                    <Text style={styles.progressMeta}>{plannedMeta}</Text>
                  ) : null}
                </>
              );
              if (!interactive || !row.allocKey) {
                return (
                  <View style={styles.progressRow} key={row.key}>
                    {body}
                  </View>
                );
              }
              return (
                <Pressable
                  key={row.key}
                  style={[styles.progressRow, active && styles.progressRowActive]}
                  onPress={() => selectAllocation(row.allocKey!)}
                >
                  {body}
                </Pressable>
              );
            })}
          </>
        )}
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
        rightAction={
          authEnabled ? (
            <Pressable onPress={() => void signOut()} accessibilityRole="button">
              <Text style={styles.signOut}>Sign out</Text>
            </Pressable>
          ) : undefined
        }
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
                value={privacyMoney(data?.totalMarketValue, hideAmounts, true)}
                hint={dayChangeHint(
                  data?.totalDayChange,
                  data?.totalDayChangePct,
                  hideAmounts,
                )}
                valueColor={pctColor(data?.totalDayChangePct)}
                labelAction={{
                  icon: hideAmounts ? "eye-off-outline" : "eye-outline",
                  onPress: () => setHideAmounts((prev) => !prev),
                  accessibilityLabel: hideAmounts
                    ? "Show sensitive dollar amounts"
                    : "Hide sensitive dollar amounts",
                }}
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Best Performer"
                value={data?.bestPerformer?.symbol ?? "—"}
                hint={performerHint(
                  data?.bestPerformer?.gainPct,
                  data?.bestPerformer?.gain,
                  hideAmounts,
                )}
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
                value={privacyMoney(data?.unrealizedGain, hideAmounts, true)}
                hint={formatPct(data?.unrealizedGainPct)}
                valueColor={pctColor(data?.unrealizedGainPct)}
              />
            </View>
            <View style={[styles.kpiCell, { width: cellWidth }]}>
              <KpiCard
                compact
                label="Best Performer YTD"
                value={data?.bestYtdPerformer?.symbol ?? "—"}
                hint={performerHint(
                  data?.bestYtdPerformer?.gainPct,
                  data?.bestYtdPerformer?.gain,
                  hideAmounts,
                )}
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
              {allocationSection}
              {alertsSection}
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
  directionRow: {
    flexDirection: "row",
    gap: spacing.xs,
  },
  directionBtn: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingVertical: 8,
    alignItems: "center",
    backgroundColor: colors.bg,
  },
  directionBtnActive: {
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
  },
  directionText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "700",
  },
  directionTextActive: {
    color: colors.text,
  },
  progressHint: {
    color: colors.textMuted,
    fontSize: 11,
    marginBottom: 2,
  },
  progressBand: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  progressRow: {
    gap: 6,
    padding: spacing.sm,
    marginHorizontal: -spacing.sm / 2,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: "transparent",
  },
  progressRowActive: {
    borderColor: "rgba(59,130,246,0.55)",
    backgroundColor: "rgba(59,130,246,0.08)",
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
  progressLabelStrong: {
    color: colors.text,
    fontWeight: "800",
  },
  progressLabelAth: {
    color: colors.warning,
    fontWeight: "700",
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
  sectionSourcePill: {
    flexShrink: 1,
    marginLeft: spacing.md,
    maxWidth: "58%",
    backgroundColor: "rgba(147,197,253,0.18)",
    borderWidth: 1,
    borderColor: colors.link,
    borderRadius: radii.md,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  sectionSource: {
    color: colors.link,
    fontSize: 13,
    fontWeight: "700",
    textAlign: "right",
  },
  signOut: {
    color: colors.link,
    fontSize: 14,
    fontWeight: "600",
    marginTop: 6,
  },
});
