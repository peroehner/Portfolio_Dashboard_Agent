import { useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import {
  allocationSubtitle,
  buildAllocationSlices,
  type AllocationMode,
} from "@/lib/allocationChart";
import { formatMoney } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { Holding } from "@/lib/types";

const CHART_SIZE = 220;
const OUTER_R = CHART_SIZE / 2 - 8;
const INNER_R = OUTER_R * 0.58;

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function donutPath(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
  startAngle: number,
  endAngle: number,
): string {
  const large = endAngle - startAngle > 180 ? 1 : 0;
  const outerStart = polar(cx, cy, outerR, startAngle);
  const outerEnd = polar(cx, cy, outerR, endAngle);
  const innerEnd = polar(cx, cy, innerR, endAngle);
  const innerStart = polar(cx, cy, innerR, startAngle);
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerR} ${outerR} 0 ${large} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerR} ${innerR} 0 ${large} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

interface AllocationChartProps {
  holdings?: Holding[];
  mode: AllocationMode;
  onModeChange: (mode: AllocationMode) => void;
}

export function AllocationChart({ holdings, mode, onModeChange }: AllocationChartProps) {
  const slices = useMemo(() => buildAllocationSlices(holdings, mode), [holdings, mode]);
  const total = useMemo(
    () => (slices ?? []).reduce((sum, slice) => sum + slice.value, 0),
    [slices],
  );

  const arcs = useMemo(() => {
    if (!slices?.length || !total) return [];
    const cx = CHART_SIZE / 2;
    const cy = CHART_SIZE / 2;
    let angle = 0;
    return slices.map((slice) => {
      const sweep = (slice.value / total) * 360;
      const path = donutPath(cx, cy, OUTER_R, INNER_R, angle, angle + sweep);
      angle += sweep;
      return { ...slice, path, pct: (slice.value / total) * 100 };
    });
  }, [slices, total]);

  if (!slices?.length) {
    return <Text style={styles.empty}>No holdings with market value yet.</Text>;
  }

  return (
    <View style={styles.wrap}>
      <View style={styles.modeRow}>
        <Pressable
          style={[styles.modeBtn, mode === "top5" && styles.modeBtnActive]}
          onPress={() => onModeChange("top5")}
        >
          <Text style={[styles.modeText, mode === "top5" && styles.modeTextActive]}>Top 5</Text>
        </Pressable>
        <Pressable
          style={[styles.modeBtn, mode === "top75" && styles.modeBtnActive]}
          onPress={() => onModeChange("top75")}
        >
          <Text style={[styles.modeText, mode === "top75" && styles.modeTextActive]}>Top 75%</Text>
        </Pressable>
      </View>
      <Text style={styles.subtitle}>{allocationSubtitle(mode)}</Text>

      <View style={styles.chartRow}>
        <Svg width={CHART_SIZE} height={CHART_SIZE}>
          {arcs.map((arc) => (
            <Path
              key={arc.label}
              d={arc.path}
              fill={arc.color}
              stroke={colors.bg}
              strokeWidth={2}
            />
          ))}
        </Svg>
        <View style={styles.legend}>
          {arcs.map((arc) => (
            <View key={arc.label} style={styles.legendRow}>
              <View style={[styles.swatch, { backgroundColor: arc.color }]} />
              <View style={styles.legendTextWrap}>
                <Text style={styles.legendLabel} numberOfLines={1}>
                  {arc.label}
                </Text>
                <Text style={styles.legendValue}>
                  {formatMoney(arc.value, true)} · {arc.pct.toFixed(1)}%
                </Text>
              </View>
            </View>
          ))}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.lg,
  },
  modeRow: {
    flexDirection: "row",
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  modeBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    backgroundColor: colors.surface,
  },
  modeBtnActive: {
    borderColor: colors.accent,
    backgroundColor: colors.surfaceAlt,
  },
  modeText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
  },
  modeTextActive: {
    color: colors.text,
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: 12,
    marginBottom: spacing.sm,
  },
  chartRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  legend: {
    flex: 1,
    minWidth: 0,
    gap: spacing.xs,
  },
  legendRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
  },
  swatch: {
    width: 10,
    height: 10,
    borderRadius: 2,
  },
  legendTextWrap: {
    flex: 1,
    minWidth: 0,
  },
  legendLabel: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "600",
  },
  legendValue: {
    color: colors.textMuted,
    fontSize: 10,
  },
  empty: {
    color: colors.textMuted,
    fontSize: 13,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
});
