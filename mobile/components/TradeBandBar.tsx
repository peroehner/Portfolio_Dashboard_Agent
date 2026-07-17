import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Rect } from "react-native-svg";

import { formatMoney, formatPrice } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { PortfolioRow } from "@/lib/types";

const MAX_SPAN = 20;
const HEAT_MAX = 15;
const MIN_GAP = 15;
const PAD = 4;
const TRACK_HEIGHT = 5;
const KNOB_R = 5;
const BAR_HEIGHT = 36;

function heatColor(distPct: number): string {
  const t = Math.max(0, Math.min(1, distPct / HEAT_MAX));
  return `hsl(${Math.round(t * 130)}, 75%, 48%)`;
}

function deltaText(price: number, threshold: number): string {
  const pct = ((threshold - price) / price) * 100;
  return `${pct < 0 ? "▼" : "▲"}${Math.abs(pct).toFixed(1)}%`;
}

function sharesText(shares: number | null | undefined): string {
  if (shares == null || Number(shares) === 0) return "";
  return Math.round(Math.abs(Number(shares))).toLocaleString("en-US");
}

/** Tooltip text for Trade column (also used by Day % / Qty long-press). */
export function tradeBandTooltipText(row: PortfolioRow): string | null {
  const price = row.currentPrice;
  if (price == null) return null;
  const lines: string[] = [];
  lines.push(`Price ${formatPrice(price)}`);
  if (row.tradeBelowPrice != null) {
    const sh = sharesText(row.tradeBelowShares);
    lines.push(
      `Below ${formatPrice(row.tradeBelowPrice)} (${deltaText(price, row.tradeBelowPrice)})${sh ? ` · Buy ${sh}` : ""}`,
    );
  }
  if (row.tradeAbovePrice != null) {
    const sh = sharesText(row.tradeAboveShares);
    lines.push(
      `Above ${formatPrice(row.tradeAbovePrice)} (${deltaText(price, row.tradeAbovePrice)})${sh ? ` · Sell ${sh}` : ""}`,
    );
  }
  return lines.length > 1 ? lines.join("\n") : null;
}

interface TradeBandBarProps {
  row: PortfolioRow;
  width?: number;
  /** When set, parent owns tooltip visibility (Portfolio long-press). */
  active?: boolean;
}

export function TradeBandBar({ row, width = 150, active: activeProp }: TradeBandBarProps) {
  const [internalActive, setInternalActive] = useState(false);
  const controlled = activeProp !== undefined;
  const active = controlled ? Boolean(activeProp) : internalActive;

  const layout = useMemo(() => {
    const price = row.currentPrice;
    if (price == null) return null;

    const aLow = row.analystTargetLow;
    const aHigh = row.analystTargetHigh;
    const pt =
      row.personalTarget != null && row.personalTarget > 0 ? row.personalTarget : null;
    const analystMode = aLow != null && aHigh != null && aHigh > aLow;

    let low = analystMode ? aLow : price * (1 - MAX_SPAN / 100);
    let high = analystMode ? aHigh : price * (1 + MAX_SPAN / 100);
    low = Math.min(low, price);
    high = Math.max(high, price);
    if (row.tradeBelowPrice != null) low = Math.min(low, row.tradeBelowPrice);
    if (row.tradeAbovePrice != null) high = Math.max(high, row.tradeAbovePrice);
    if (pt != null) high = Math.max(high, pt);
    const span = high - low;

    const clamp = (v: number) => Math.max(0, Math.min(100, v));
    const rawPos = (v: number) => (span > 0 ? ((v - low) / span) * 100 : 50);
    const pos = (v: number) => PAD + (clamp(rawPos(v)) * (100 - 2 * PAD)) / 100;

    const below = row.tradeBelowPrice;
    const above = row.tradeAbovePrice;
    const hasBelow = below != null;
    const hasAbove = above != null;
    const belowDist = hasBelow ? (Math.abs(price - below) / price) * 100 : Infinity;
    const aboveDist = hasAbove ? (Math.abs(above - price) / price) * 100 : Infinity;
    const closest =
      hasBelow || hasAbove ? (belowDist <= aboveDist ? "below" : "above") : null;

    let pPrice = pos(price);
    let pBelow = hasBelow ? pos(below) : null;
    let pAbove = hasAbove ? pos(above) : null;
    let pClose: number | null = null;
    if (closest) {
      pClose = closest === "below" ? (pBelow as number) : (pAbove as number);
      const dir = pClose >= pPrice ? 1 : -1;
      if (Math.abs(pClose - pPrice) < MIN_GAP) pClose = pPrice + dir * MIN_GAP;
      let lo = Math.min(pPrice, pClose);
      if (lo < PAD) {
        const d = PAD - lo;
        pPrice += d;
        pClose += d;
      }
      let hi = Math.max(pPrice, pClose);
      if (hi > 100 - PAD) {
        const d = hi - (100 - PAD);
        pPrice -= d;
        pClose -= d;
      }
      if (closest === "below") pBelow = pClose;
      else pAbove = pClose;
    }

    const dist = closest === "below" ? belowDist : aboveDist;
    const title = tradeBandTooltipText(row) ?? "";

    return {
      price,
      low,
      high,
      analystMode,
      pPrice,
      pBelow,
      pAbove,
      pClose,
      closest,
      dist,
      title,
    };
  }, [row]);

  if (!layout) {
    return <Text style={styles.empty}>—</Text>;
  }

  const trackY = 20;
  const px = (pct: number) => (pct / 100) * width;
  const heatLeft = layout.pClose != null ? Math.min(layout.pPrice, layout.pClose) : null;
  const heatWidth =
    layout.pClose != null ? Math.abs(layout.pClose - layout.pPrice) : null;

  const body = (
    <>
      {!controlled && active && layout.title ? (
        <View style={styles.tooltip} pointerEvents="none">
          <Text style={styles.tooltipText}>{layout.title}</Text>
        </View>
      ) : null}

      {/* Edge/price overlays only for uncontrolled hover — controlled tips use the table banner. */}
      {!controlled && active ? (
        <>
          <Text style={[styles.edge, styles.edgeLow]} numberOfLines={1}>
            {formatMoney(layout.low)}
          </Text>
          <Text style={[styles.edge, styles.edgeHigh]} numberOfLines={1}>
            {formatMoney(layout.high)}
          </Text>
        </>
      ) : null}

      <Svg width={width} height={BAR_HEIGHT}>
        <Rect
          x={0}
          y={trackY}
          width={width}
          height={TRACK_HEIGHT}
          rx={TRACK_HEIGHT / 2}
          fill={layout.analystMode ? "rgba(96,165,250,0.25)" : "rgba(148,163,184,0.2)"}
        />
        {heatLeft != null && heatWidth != null && layout.closest ? (
          <Rect
            x={px(heatLeft)}
            y={trackY}
            width={Math.max(2, px(heatWidth))}
            height={TRACK_HEIGHT}
            rx={2}
            fill={heatColor(layout.dist as number)}
          />
        ) : null}
        {layout.pBelow != null ? (
          <Rect
            x={px(layout.pBelow) - 1}
            y={trackY - 4}
            width={2}
            height={TRACK_HEIGHT + 8}
            rx={1}
            fill="#ef4444"
          />
        ) : null}
        {layout.pAbove != null ? (
          <Rect
            x={px(layout.pAbove) - 1}
            y={trackY - 4}
            width={2}
            height={TRACK_HEIGHT + 8}
            rx={1}
            fill="#22c55e"
          />
        ) : null}
        <Circle
          cx={px(layout.pPrice)}
          cy={trackY + TRACK_HEIGHT / 2}
          r={KNOB_R}
          fill="#60a5fa"
          stroke={colors.bg}
          strokeWidth={2}
        />
      </Svg>

      {layout.closest && layout.dist != null && Number.isFinite(layout.dist) ? (
        <Text
          style={[
            styles.pct,
            { left: px((layout.pPrice + (layout.pClose as number)) / 2), color: heatColor(layout.dist) },
          ]}
          numberOfLines={1}
        >
          {Math.round(layout.dist)}%
        </Text>
      ) : null}

      {!controlled && active ? (
        <Text style={[styles.priceLabel, { left: px(layout.pPrice) }]} numberOfLines={1}>
          {formatPrice(layout.price)}
        </Text>
      ) : null}
    </>
  );

  if (controlled) {
    return <View style={[styles.wrap, { width }]}>{body}</View>;
  }

  return (
    <Pressable
      style={[styles.wrap, { width }]}
      onLongPress={() => setInternalActive(true)}
      onPressOut={() => setInternalActive(false)}
      delayLongPress={280}
      accessibilityLabel="Trade range"
    >
      {body}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: {
    height: BAR_HEIGHT,
    justifyContent: "center",
    position: "relative",
    overflow: "visible",
  },
  tooltip: {
    position: "absolute",
    top: -2,
    left: 0,
    right: 0,
    zIndex: 20,
    elevation: 20,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.xs,
    paddingVertical: 3,
    transform: [{ translateY: -28 }],
  },
  tooltipText: {
    color: colors.text,
    fontSize: 9,
    fontWeight: "600",
    textAlign: "center",
  },
  edge: {
    position: "absolute",
    top: 8,
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
    transform: [{ translateX: -12 }],
  },
  priceLabel: {
    position: "absolute",
    bottom: 0,
    fontSize: 8,
    fontWeight: "700",
    color: colors.text,
    transform: [{ translateX: -16 }],
  },
  empty: {
    color: colors.textMuted,
    fontSize: 12,
  },
});
