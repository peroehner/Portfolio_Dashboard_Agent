import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Circle, Line, Rect } from "react-native-svg";

import { formatMoney, formatPrice } from "@/lib/format";
import { buildTradeBandLayout, type TradeUpperRef } from "@/lib/tradeBand";
import { colors, radii, spacing } from "@/lib/theme";
import type { PortfolioRow } from "@/lib/types";

const TRACK_HEIGHT = 5;
const KNOB_R = 5;
const BAR_HEIGHT = 26;
const TRACK_Y = 16;
const MIN_HEAT_PX = 2;

function sharesText(shares: number | null | undefined): string {
  if (shares == null || Number(shares) === 0) return "";
  return Math.round(Math.abs(Number(shares))).toLocaleString("en-US");
}

function deltaText(price: number, threshold: number): string {
  const pct = ((threshold - price) / price) * 100;
  return `${pct < 0 ? "▼" : "▲"}${Math.abs(pct).toFixed(1)}%`;
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
  /** Upper-ref mark: analyst 1Y mean (solid, default) or Pers Target (dashed). */
  upperRef?: TradeUpperRef;
}

export function TradeBandBar({
  row,
  width = 150,
  active: activeProp,
  upperRef = "analyst",
}: TradeBandBarProps) {
  const [internalActive, setInternalActive] = useState(false);
  const controlled = activeProp !== undefined;
  const active = controlled ? Boolean(activeProp) : internalActive;

  const layout = useMemo(
    () =>
      buildTradeBandLayout(
        {
          currentPrice: row.currentPrice,
          tradeBelowPrice: row.tradeBelowPrice,
          tradeAbovePrice: row.tradeAbovePrice,
          analystTarget1y: row.analystTarget1y,
          personalTarget: row.personalTarget,
          targetPrice: row.personalTarget,
        },
        upperRef,
      ),
    [row, upperRef],
  );

  if (!layout) {
    return <Text style={styles.empty}>—</Text>;
  }

  const trackY = TRACK_Y;
  const px = (pct: number) => (pct / 100) * width;
  const heatLeft = layout.pFocus != null ? Math.min(layout.pPrice, layout.pFocus) : null;
  const heatWidthPct =
    layout.pFocus != null ? Math.abs(layout.pFocus - layout.pPrice) : null;

  const pricePosStyle =
    layout.focusSide === "above"
      ? { right: width - px(layout.pPrice) + 7 }
      : layout.focusSide === "below"
        ? { left: px(layout.pPrice) + 7 }
        : { left: px(layout.pPrice), transform: [{ translateX: -20 }] as const };

  const title = tradeBandTooltipText(row) ?? "";

  const body = (
    <>
      {!controlled && active && title ? (
        <View style={styles.tooltip} pointerEvents="none">
          <Text style={styles.tooltipText}>{title}</Text>
        </View>
      ) : null}

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
          fill={
            layout.outOfRange
              ? "rgba(249,115,22,0.18)"
              : "rgba(148,163,184,0.22)"
          }
        />
        {heatLeft != null && heatWidthPct != null ? (
          <Rect
            x={px(heatLeft)}
            y={trackY}
            width={Math.max(MIN_HEAT_PX, px(heatWidthPct))}
            height={TRACK_HEIGHT}
            rx={2}
            fill={layout.heatColor}
          />
        ) : null}
        {layout.pBelow != null ? (
          <Rect
            x={px(layout.pBelow) - 1}
            y={trackY - 4}
            width={2}
            height={TRACK_HEIGHT + 8}
            rx={1}
            fill={colors.sell}
          />
        ) : null}
        {layout.pAbove != null ? (
          <Rect
            x={px(layout.pAbove) - 1}
            y={trackY - 4}
            width={2}
            height={TRACK_HEIGHT + 8}
            rx={1}
            fill={colors.buy}
          />
        ) : null}
        {layout.pUpperRef != null ? (
          // 1YT = solid, PT = dashed (matches web); thicker so it reads as
          // clearly as the red/green threshold marks.
          <Line
            x1={px(layout.pUpperRef)}
            y1={trackY - 5}
            x2={px(layout.pUpperRef)}
            y2={trackY + TRACK_HEIGHT + 5}
            stroke={upperRef === "pt" ? "#a78bfa" : "#38bdf8"}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeDasharray={upperRef === "pt" ? "2 2" : undefined}
          />
        ) : null}
        <Circle
          cx={px(layout.pPrice)}
          cy={trackY + TRACK_HEIGHT / 2}
          r={KNOB_R}
          fill={layout.outOfRange ? layout.heatColor : colors.link}
          stroke={colors.bg}
          strokeWidth={2}
        />
      </Svg>

      {layout.distLabel ? (
        <Text
          style={[
            styles.pct,
            {
              left: px((layout.pPrice + (layout.pFocus as number)) / 2),
              color: layout.heatColor,
            },
          ]}
          numberOfLines={1}
        >
          {layout.distLabel}
        </Text>
      ) : null}

      <Text style={[styles.priceLabel, pricePosStyle]} numberOfLines={1}>
        {formatMoney(layout.price)}
      </Text>
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
    top: TRACK_Y + 6,
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
    top: 1,
    fontSize: 9,
    fontWeight: "700",
    transform: [{ translateX: -12 }],
  },
  priceLabel: {
    position: "absolute",
    top: 1,
    fontSize: 9,
    fontWeight: "700",
    color: "#93c5fd",
  },
  empty: {
    color: colors.textMuted,
    fontSize: 12,
  },
});
