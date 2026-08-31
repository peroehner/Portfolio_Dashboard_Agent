import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import {
  allocationFocusSummary,
  allocationSubtitle,
  buildAllocationSlices,
  type AllocationMode,
  type AllocationSlice,
} from "@/lib/allocationChart";
import { formatMoney } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { Holding } from "@/lib/types";

const CHART_SIZE = 220;
const OUTER_R = CHART_SIZE / 2 - 8;
const INNER_R = OUTER_R * 0.58;
/** Match Chart.js doughnut feel (~1s grow / morph). */
const ANIM_MS = 750;

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
  const sweep = endAngle - startAngle;
  if (sweep < 0.05) return "";
  // Full circle needs two arcs (SVG can't close a 360° arc on itself).
  if (sweep >= 359.95) {
    const mid = startAngle + 180;
    return [
      donutPath(cx, cy, outerR, innerR, startAngle, mid),
      donutPath(cx, cy, outerR, innerR, mid, startAngle + 360),
    ]
      .filter(Boolean)
      .join(" ");
  }
  const large = sweep > 180 ? 1 : 0;
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

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3;
}

interface ArcFrame {
  label: string;
  color: string;
  value: number;
  start: number;
  end: number;
}

function targetArcs(slices: AllocationSlice[], total: number): ArcFrame[] {
  let angle = 0;
  return slices.map((slice) => {
    const sweep = total > 0 ? (slice.value / total) * 360 : 0;
    const start = angle;
    const end = angle + sweep;
    angle = end;
    return {
      label: slice.label,
      color: slice.color,
      value: slice.value,
      start,
      end,
    };
  });
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function interpolateArcs(from: ArcFrame[], to: ArcFrame[], t: number): ArcFrame[] {
  const fromBy = new Map(from.map((a) => [a.label, a]));
  const toBy = new Map(to.map((a) => [a.label, a]));
  const labels = [...new Set([...from.map((a) => a.label), ...to.map((a) => a.label)])];

  return labels
    .map((label) => {
      const next = toBy.get(label);
      const prev = fromBy.get(label);
      if (next && prev) {
        return {
          label,
          color: next.color,
          value: lerp(prev.value, next.value, t),
          start: lerp(prev.start, next.start, t),
          end: lerp(prev.end, next.end, t),
        };
      }
      if (next) {
        // Grow from a zero-width wedge at the target start.
        const mid = next.start;
        return {
          label,
          color: next.color,
          value: lerp(0, next.value, t),
          start: lerp(mid, next.start, t),
          end: lerp(mid, next.end, t),
        };
      }
      if (prev) {
        const mid = (prev.start + prev.end) / 2;
        return {
          label,
          color: prev.color,
          value: lerp(prev.value, 0, t),
          start: lerp(prev.start, mid, t),
          end: lerp(prev.end, mid, t),
        };
      }
      return null;
    })
    .filter(Boolean) as ArcFrame[];
}

function slicesSignature(slices: AllocationSlice[] | null | undefined, total: number): string {
  if (!slices?.length) return "empty";
  return `${total.toFixed(2)}|` + slices.map((s) => `${s.label}:${s.value.toFixed(2)}:${s.color}`).join("|");
}

interface AllocationChartProps {
  holdings?: Holding[];
  mode: AllocationMode;
  onModeChange: (mode: AllocationMode) => void;
  /** Mask legend dollar amounts for Summary privacy demos. */
  hideAmounts?: boolean;
}

export function AllocationChart({
  holdings,
  mode,
  onModeChange,
  hideAmounts = false,
}: AllocationChartProps) {
  const slices = useMemo(() => buildAllocationSlices(holdings, mode), [holdings, mode]);
  const focus = useMemo(() => allocationFocusSummary(holdings, mode), [holdings, mode]);
  const total = useMemo(
    () => focus?.total ?? (slices ?? []).reduce((sum, slice) => sum + slice.value, 0),
    [focus, slices],
  );
  const target = useMemo(
    () => (slices?.length && total ? targetArcs(slices, total) : []),
    [slices, total],
  );
  const signature = slicesSignature(slices, total);

  const [displayArcs, setDisplayArcs] = useState<ArcFrame[]>([]);
  const displayRef = useRef<ArcFrame[]>([]);
  const animRef = useRef<number | null>(null);
  const signatureRef = useRef("");
  const targetRef = useRef(target);
  targetRef.current = target;

  useEffect(() => {
    if (signature === signatureRef.current) return;
    signatureRef.current = signature;
    const to = targetRef.current;
    if (animRef.current != null) cancelAnimationFrame(animRef.current);

    if (!to.length) {
      displayRef.current = [];
      setDisplayArcs([]);
      return;
    }

    const from = displayRef.current;
    const origin =
      from.length === 0
        ? to.map((a) => ({ ...a, value: 0, end: a.start }))
        : from;

    const started = Date.now();
    const tick = () => {
      const u = Math.min(1, (Date.now() - started) / ANIM_MS);
      const eased = easeOutCubic(u);
      const next = interpolateArcs(origin, to, eased);
      displayRef.current = next;
      setDisplayArcs(next);
      if (u < 1) {
        animRef.current = requestAnimationFrame(tick);
      } else {
        animRef.current = null;
        displayRef.current = to;
        setDisplayArcs(to);
      }
    };
    animRef.current = requestAnimationFrame(tick);
    return () => {
      if (animRef.current != null) cancelAnimationFrame(animRef.current);
    };
  }, [signature]);

  const arcs = useMemo(() => {
    const cx = CHART_SIZE / 2;
    const cy = CHART_SIZE / 2;
    const liveTotal = displayArcs.reduce((sum, a) => sum + a.value, 0);
    return displayArcs
      .map((arc) => {
        const path = donutPath(cx, cy, OUTER_R, INNER_R, arc.start, arc.end);
        if (!path) return null;
        const pct = liveTotal > 0 ? (arc.value / liveTotal) * 100 : 0;
        return { ...arc, path, pct };
      })
      .filter(Boolean) as Array<ArcFrame & { path: string; pct: number }>;
  }, [displayArcs]);

  if (!slices?.length && !displayArcs.length) {
    return (
      <View style={styles.wrap}>
        <Text style={styles.empty}>No allocation data for this selection.</Text>
      </View>
    );
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
        <View style={styles.chartWrap}>
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
          {focus ? (
            <View style={styles.centerHole} pointerEvents="none">
              <Text style={styles.centerLabel}>Total</Text>
              <Text style={styles.centerTotal}>
                {hideAmounts ? "••••" : formatMoney(focus.total, true)}
              </Text>
              <Text style={styles.centerFocusLabel}>{focus.focusLabel}</Text>
              <Text style={styles.centerFocusValue}>
                {hideAmounts
                  ? "••••"
                  : `${formatMoney(focus.focusValue, true)} (${focus.focusPct.toFixed(1)}%)`}
              </Text>
            </View>
          ) : null}
        </View>
        <View style={styles.legend}>
          {arcs
            .filter((arc) => arc.value > 0.5 || arc.pct > 0.05)
            .map((arc) => (
              <View key={arc.label} style={styles.legendRow}>
                <View style={[styles.swatch, { backgroundColor: arc.color }]} />
                <View style={styles.legendTextWrap}>
                  <Text style={styles.legendLabel} numberOfLines={1}>
                    {arc.label}
                  </Text>
                  <Text style={styles.legendValue}>
                    {hideAmounts ? "••••" : formatMoney(arc.value, true)} · {arc.pct.toFixed(1)}%
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
  chartWrap: {
    width: CHART_SIZE,
    height: CHART_SIZE,
    position: "relative",
    alignItems: "center",
    justifyContent: "center",
  },
  centerHole: {
    position: "absolute",
    alignItems: "center",
    justifyContent: "center",
    maxWidth: INNER_R * 2 - 12,
    paddingHorizontal: 4,
  },
  centerLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "600",
  },
  centerTotal: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
    marginBottom: 4,
  },
  centerFocusLabel: {
    color: colors.textMuted,
    fontSize: 9,
    fontWeight: "600",
    textAlign: "center",
  },
  centerFocusValue: {
    color: "#cbd5e1",
    fontSize: 11,
    fontWeight: "600",
    textAlign: "center",
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
    paddingVertical: spacing.md,
  },
});
