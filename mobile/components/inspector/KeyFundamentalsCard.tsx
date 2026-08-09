import { ScrollView, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { formatPct, formatRatio, pctColor } from "@/lib/format";
import { fundToneColor, fundTonePeg } from "@/lib/fundamentalsTone";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface KeyFundamentalsCardProps {
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

export function KeyFundamentalsCard({ data, style }: KeyFundamentalsCardProps) {
  const v = data?.valuation;
  const peg = v?.pegRatio ?? null;
  const rev = v?.revenueGrowth ?? null;
  const earn = v?.earningsGrowth ?? null;
  const hasAny =
    v &&
    (v.trailingPe != null ||
      v.forwardPe != null ||
      peg != null ||
      rev != null ||
      earn != null ||
      v.operatingMargin != null);

  return (
    <View style={[styles.card, style]}>
      <Text style={styles.title}>Key Fundamentals</Text>
      <Text style={styles.subtitle}>Valuation / Growth</Text>
      <ScrollView
        nestedScrollEnabled
        style={styles.bodyScroll}
        contentContainerStyle={styles.bodyScrollContent}
        showsVerticalScrollIndicator={false}
      >
        {!hasAny ? (
          <Text style={styles.muted}>No valuation metrics yet.</Text>
        ) : (
          <View style={styles.grid}>
            <View style={styles.col}>
              <Metric label="Trail P/E" value={formatRatio(v?.trailingPe)} />
              <Metric label="Fwd P/E" value={formatRatio(v?.forwardPe)} />
              <Metric
                label="PEG"
                value={formatRatio(peg)}
                color={fundToneColor(fundTonePeg(peg))}
              />
            </View>
            <View style={styles.col}>
              <Metric label="Rev growth" value={formatPct(rev)} color={pctColor(rev)} />
              <Metric label="Earn growth" value={formatPct(earn)} color={pctColor(earn)} />
              <Metric
                label="Op. margin"
                value={formatPct(v?.operatingMargin)}
                color={pctColor(v?.operatingMargin)}
              />
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
  subtitle: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
    marginBottom: 2,
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
