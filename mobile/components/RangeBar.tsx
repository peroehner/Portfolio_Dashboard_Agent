import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Defs, LinearGradient, Rect, Stop } from "react-native-svg";

import { formatPrice } from "@/lib/format";
import { fundNum, fundRangeLevels, fundRangePosition, fundVal } from "@/lib/fundamentalsTable";
import { colors, radii, spacing } from "@/lib/theme";
import type { FundamentalsRow } from "@/lib/types";

const TRACK_HEIGHT = 5;
const KNOB_R = 5;
const ROW_HEIGHT = 44;

interface RangeBarProps {
  row: FundamentalsRow;
  width?: number;
}

function rangeBarMeta(row: FundamentalsRow) {
  const { price, high: highNum, low: lowNum } = fundRangeLevels(row);
  if (lowNum == null || highNum == null || price == null) return null;
  const mid = (lowNum + highNum) / 2;
  const dev = mid !== 0 ? ((price - mid) / mid) * 100 : null;
  return { lowNum, highNum, price, mid, dev };
}

export function RangeBar({ row, width = 100 }: RangeBarProps) {
  const [active, setActive] = useState(false);
  const position = fundRangePosition(row);
  const meta = useMemo(() => rangeBarMeta(row), [row]);
  const gradId = `range-${row.symbol}`;

  if (position == null || !meta) {
    return <Text style={styles.empty}>—</Text>;
  }

  const pos = position;
  const label = `${position.toFixed(0)}%`;
  const knobX = (pos / 100) * width;
  const trackY = 18;
  const devSign = meta.dev != null && meta.dev < 0 ? "▼" : "▲";
  const devColor = meta.dev != null && meta.dev < 0 ? colors.sell : colors.buy;
  const labelLeft = pos > 55;

  return (
    <Pressable
      style={[styles.wrap, { width }]}
      onPressIn={() => setActive(true)}
      onPressOut={() => setActive(false)}
      accessibilityLabel={`52-week range ${label}`}
      accessibilityHint="Press and hold for mid price and deviation"
    >
      {active ? (
        <View style={styles.tooltip}>
          <Text style={styles.tooltipText}>
            {`Mid ${formatPrice(meta.mid)} · Price ${formatPrice(meta.price)}`}
            {meta.dev != null ? (
              <Text style={{ color: devColor }}>
                {` (${devSign}${Math.abs(meta.dev).toFixed(1)}%)`}
              </Text>
            ) : null}
          </Text>
        </View>
      ) : null}

      {active ? (
        <>
          <Text style={[styles.edge, styles.edgeLow]} numberOfLines={1}>
            {formatPrice(meta.lowNum)}
          </Text>
          <Text style={[styles.edge, styles.edgeHigh]} numberOfLines={1}>
            {formatPrice(meta.highNum)}
          </Text>
        </>
      ) : null}

      <Svg width={width} height={32}>
        <Defs>
          <LinearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0" stopColor="rgba(239,68,68,0.55)" />
            <Stop offset="0.5" stopColor="rgba(148,163,184,0.4)" />
            <Stop offset="1" stopColor="rgba(34,197,94,0.55)" />
          </LinearGradient>
        </Defs>
        <Rect
          x={0}
          y={trackY}
          width={width}
          height={TRACK_HEIGHT}
          rx={TRACK_HEIGHT / 2}
          fill={`url(#${gradId})`}
        />
        <Circle
          cx={knobX}
          cy={trackY + TRACK_HEIGHT / 2}
          r={KNOB_R}
          fill={colors.link}
          stroke={colors.bg}
          strokeWidth={2}
        />
      </Svg>

      <Text
        style={[
          styles.pct,
          labelLeft
            ? { right: `${100 - pos}%`, left: undefined, marginRight: 6 }
            : { left: `${pos}%`, marginLeft: 6 },
        ]}
        numberOfLines={1}
      >
        {label}
      </Text>
    </Pressable>
  );
}

/** Compact analyst target deviation label (vs mean). */
export function TargetRangeBar({ row, width = 110 }: { row: FundamentalsRow; width?: number }) {
  const [active, setActive] = useState(false);
  const price = fundNum(row.currentPrice);
  const low = fundNum(fundVal(row, "analyst", "targetLow"));
  const mean = fundNum(fundVal(row, "analyst", "targetMean"));
  const high = fundNum(fundVal(row, "analyst", "targetHigh"));
  if (price == null || mean == null || mean === 0) {
    return <Text style={styles.empty}>—</Text>;
  }

  const dev = ((price - mean) / mean) * 100;
  const sign = dev < 0 ? "▼" : "▲";
  const color = dev >= 0 ? colors.buy : colors.sell;

  if (low == null || high == null || high <= low) {
    return (
      <View style={[styles.wrap, styles.wrapCompact, { width }]}>
        <Text style={[styles.targetPctOnly, { color }]} numberOfLines={1}>
          {sign}
          {Math.abs(dev).toFixed(1)}%
        </Text>
      </View>
    );
  }

  const span = high - low;
  const clamp = (v: number) => Math.max(0, Math.min(100, v));
  const pricePos = clamp(((price - low) / span) * 100);
  const meanPos = clamp(((mean - low) / span) * 100);
  const gradId = `target-${row.symbol}`;

  return (
    <Pressable
      style={[styles.wrap, { width }]}
      onPressIn={() => setActive(true)}
      onPressOut={() => setActive(false)}
    >
      {active ? (
        <View style={styles.tooltip}>
          <Text style={styles.tooltipText}>
            Mean {formatPrice(mean)}
            {" · "}
            Price {formatPrice(price)}
            {" ("}
            <Text style={{ color }}>{sign}{Math.abs(dev).toFixed(1)}%</Text>
            {")"}
          </Text>
        </View>
      ) : null}

      <Svg width={width} height={32}>
        <Defs>
          <LinearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0" stopColor="rgba(96,165,250,0.2)" />
            <Stop offset="0.5" stopColor="rgba(96,165,250,0.55)" />
            <Stop offset="1" stopColor="rgba(96,165,250,0.2)" />
          </LinearGradient>
        </Defs>
        <Rect
          x={0}
          y={18}
          width={width}
          height={TRACK_HEIGHT}
          rx={TRACK_HEIGHT / 2}
          fill={`url(#${gradId})`}
        />
        <Rect
          x={(meanPos / 100) * width - 1}
          y={12}
          width={2}
          height={14}
          rx={1}
          fill={colors.watch}
        />
        <Circle
          cx={(pricePos / 100) * width}
          cy={18 + TRACK_HEIGHT / 2}
          r={KNOB_R}
          fill={colors.link}
          stroke={colors.bg}
          strokeWidth={2}
        />
      </Svg>

      <Text style={[styles.targetPct, { color }]} numberOfLines={1}>
        {sign}
        {Math.abs(dev).toFixed(1)}%
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: {
    height: 36,
    justifyContent: "center",
    position: "relative",
    zIndex: 1,
  },
  wrapCompact: {
    height: ROW_HEIGHT,
    alignItems: "flex-end",
    paddingRight: 2,
  },
  tooltip: {
    position: "absolute",
    top: -2,
    left: 0,
    right: 0,
    zIndex: 5,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.xs,
    paddingVertical: 3,
    transform: [{ translateY: -22 }],
  },
  tooltipText: {
    color: colors.text,
    fontSize: 9,
    fontWeight: "600",
    textAlign: "center",
  },
  edge: {
    position: "absolute",
    top: 10,
    fontSize: 8,
    fontWeight: "700",
    color: colors.text,
    backgroundColor: colors.bg,
    paddingHorizontal: 2,
    borderRadius: 2,
    zIndex: 2,
  },
  edgeLow: { left: 0 },
  edgeHigh: { right: 0 },
  pct: {
    position: "absolute",
    top: 4,
    fontSize: 9,
    fontWeight: "700",
    color: colors.text,
  },
  targetPct: {
    position: "absolute",
    right: 0,
    top: 8,
    fontSize: 10,
    fontWeight: "700",
  },
  targetPctOnly: {
    fontSize: 11,
    fontWeight: "700",
  },
  empty: {
    color: colors.textMuted,
    fontSize: 12,
  },
});
