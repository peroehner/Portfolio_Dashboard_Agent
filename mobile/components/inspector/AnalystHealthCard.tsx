import { ScrollView, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { formatLargeMoney, formatPrice, formatRatio } from "@/lib/format";
import {
  fundToneBeta,
  fundToneColor,
  fundToneDebtEquity,
} from "@/lib/fundamentalsTone";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface AnalystHealthCardProps {
  data?: InspectorPayload | null;
  style?: ViewStyle | ViewStyle[];
}

function Metric({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <View style={styles.cell}>
      <Text style={styles.cellLabel}>{label}</Text>
      <Text style={[styles.cellValue, color ? { color } : null]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

function formatRating(key?: string | null, count?: number | null): string {
  if (!key) return "—";
  const label = String(key).replace(/_/g, " ");
  if (count == null || Number.isNaN(count)) return label;
  return `${label} (${Math.round(count)})`;
}

function closestInfo(
  price: number | null | undefined,
  levels: { label: string; value: number | null | undefined }[],
): { text: string; color?: string } {
  if (price == null || Number.isNaN(price)) return { text: "—" };
  let best: { label: string; abs: number; deviation: number } | null = null;
  for (const lvl of levels) {
    if (lvl.value == null || lvl.value === 0 || Number.isNaN(lvl.value)) continue;
    const deviation = ((price - lvl.value) / lvl.value) * 100;
    const abs = Math.abs(deviation);
    if (!best || abs < best.abs) best = { label: lvl.label, abs, deviation };
  }
  if (!best) return { text: "—" };
  const sign = best.deviation > 0 ? "+" : "";
  return {
    text: `${best.label} ${sign}${best.deviation.toFixed(1)}%`,
    color: best.deviation >= 0 ? colors.buy : colors.sell,
  };
}

export function AnalystHealthCard({ data, style }: AnalystHealthCardProps) {
  const v = data?.valuation;
  const quote = data?.quote;
  const price = quote?.currentPrice;
  const targetMean = v?.targetMean ?? quote?.analystTarget1y ?? null;
  const hasAny =
    Boolean(v?.recommendationKey) ||
    targetMean != null ||
    v?.beta != null ||
    v?.debtToEquity != null ||
    v?.freeCashflow != null ||
    v?.ma50 != null ||
    v?.ma200 != null ||
    v?.high52w != null ||
    v?.low52w != null;

  const closest = closestInfo(price, [
    { label: "52W-Hi", value: v?.high52w },
    { label: "52W-Lo", value: v?.low52w },
    { label: "50-Avg", value: v?.ma50 },
    { label: "200-Avg", value: v?.ma200 },
  ]);

  const beta = v?.beta ?? null;
  const d2e = v?.debtToEquity ?? null;
  const fcf = v?.freeCashflow ?? null;

  return (
    <View style={[styles.card, style]}>
      <Text style={styles.title}>Analyst · Health</Text>
      <ScrollView
        nestedScrollEnabled
        style={styles.bodyScroll}
        contentContainerStyle={styles.bodyScrollContent}
        showsVerticalScrollIndicator={false}
      >
        {!hasAny ? (
          <Text style={styles.muted}>No analyst / health metrics yet.</Text>
        ) : (
          <View style={styles.grid}>
            <View style={styles.col}>
              <Metric label="Rating" value={formatRating(v?.recommendationKey, v?.analystCount)} />
              <Metric label="Target mean" value={formatPrice(targetMean)} />
              <Metric
                label="Beta"
                value={formatRatio(beta)}
                color={fundToneColor(fundToneBeta(beta))}
              />
              <Metric
                label="Debt / E"
                value={formatRatio(d2e, 1)}
                color={fundToneColor(fundToneDebtEquity(d2e))}
              />
            </View>
            <View style={styles.col}>
              <Metric
                label="FCF"
                value={formatLargeMoney(fcf)}
                color={fcf == null ? undefined : fcf >= 0 ? colors.buy : colors.sell}
              />
              <Metric label="50-Day" value={formatPrice(v?.ma50)} />
              <Metric label="200-Day" value={formatPrice(v?.ma200)} />
              <Metric label="Closest" value={closest.text} color={closest.color} />
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.xs,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
  },
  bodyScroll: {
    flexGrow: 1,
    flexShrink: 1,
  },
  bodyScrollContent: {
    flexGrow: 1,
  },
  muted: {
    color: colors.textMuted,
    fontSize: 12,
  },
  grid: {
    flexDirection: "row",
    gap: spacing.md,
  },
  col: {
    flex: 1,
    gap: spacing.sm,
    minWidth: 0,
  },
  cell: {
    gap: 1,
  },
  cellLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  cellValue: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "600",
    lineHeight: 15,
  },
});
