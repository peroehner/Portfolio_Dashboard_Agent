import { StyleSheet, Text, View } from "react-native";

import { InspectorPerformanceChart } from "@/components/inspector/InspectorPerformanceChart";
import { formatMoney, formatPrice } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { ChartPatternPayload, InspectorPayload } from "@/lib/types";

interface PerformancePanelProps {
  data?: InspectorPayload | null;
}

function patternColor(type?: string): string {
  if (type === "bullish") return colors.buy;
  if (type === "bearish") return colors.sell;
  return colors.textMuted;
}

export function PerformancePanel({ data }: PerformancePanelProps) {
  const nearest = data?.nearestFib;
  const patterns = data?.chartPatterns ?? [];

  const hasExtras = nearest?.level?.price != null || patterns.length > 0;

  return (
    <View style={styles.wrap}>
      <InspectorPerformanceChart data={data} />

      {nearest?.level?.price != null ? (
        <View style={styles.card}>
          <Text style={styles.title}>Nearest Fib</Text>
          <Text style={styles.body}>
            {nearest.fib ?? nearest.level.label} @ {formatPrice(nearest.level.price)}
          </Text>
        </View>
      ) : null}

      {patterns.length > 0 ? (
        <View style={styles.card}>
          <Text style={styles.title}>Chart patterns</Text>
          {patterns.map((pattern, idx) => (
            <PatternRow key={`${pattern.name}-${idx}`} pattern={pattern} />
          ))}
        </View>
      ) : null}

      {!hasExtras && !data?.chartTimeline?.points?.length ? (
        <View style={styles.card}>
          <Text style={styles.muted}>No performance data available for this symbol.</Text>
        </View>
      ) : null}
    </View>
  );
}

function PatternRow({ pattern }: { pattern: ChartPatternPayload }) {
  const color = patternColor(pattern.type);
  const conf =
    typeof pattern.confidence === "number"
      ? `${Math.round(pattern.confidence * 100)}%`
      : null;
  return (
    <View style={styles.pattern}>
      <Text style={[styles.patternName, { color }]}>
        {pattern.name}
        {conf ? ` · ${conf}` : ""}
      </Text>
      {pattern.keyLevel?.price != null ? (
        <Text style={styles.muted}>
          {pattern.keyLevel.label} {formatPrice(pattern.keyLevel.price)}
          {pattern.target != null ? ` · tgt ${formatMoney(pattern.target)}` : ""}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingBottom: spacing.md,
  },
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
  body: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  muted: {
    color: colors.textMuted,
    fontSize: 12,
    lineHeight: 17,
  },
  pattern: {
    gap: 2,
    paddingTop: spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  patternName: {
    fontSize: 13,
    fontWeight: "700",
  },
});
