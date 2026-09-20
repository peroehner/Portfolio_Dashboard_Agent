/**
 * Planned-trade window geometry and signed distances for Trade / Trade Range.
 *
 * Window = Trade Below → Trade Above (extended if price is out of range).
 * Optional upper-ref mark: analyst 1Y mean (default) or Pers Target.
 */

export type TradeUpperRef = "analyst" | "pt";
export type TradeSortSide = "below" | "above";

export const TRADE_BAND_PAD = 4;
export const TRADE_BAND_FALLBACK_SPAN_PCT = 20;

export type TradeBandRow = {
  currentPrice?: number | null;
  tradeBelowPrice?: number | null;
  tradeAbovePrice?: number | null;
  analystTarget1y?: number | null;
  personalTarget?: number | null;
  targetPrice?: number | null;
};

/** Signed % from lower boundary: negative = left of Below (OOR). */
export function signedDistFromBelow(
  row: TradeBandRow,
): number | null {
  const price = row.currentPrice;
  const below = row.tradeBelowPrice;
  if (price == null || !(price > 0) || below == null) return null;
  return ((price - below) / price) * 100;
}

/** Signed % from upper boundary: positive = right of Above (OOR). */
export function signedDistFromAbove(
  row: TradeBandRow,
): number | null {
  const price = row.currentPrice;
  const above = row.tradeAbovePrice;
  if (price == null || !(price > 0) || above == null) return null;
  return ((price - above) / price) * 100;
}

export function isOutOfRangeBelow(row: TradeBandRow): boolean {
  const s = signedDistFromBelow(row);
  return s != null && s < 0;
}

export function isOutOfRangeAbove(row: TradeBandRow): boolean {
  const s = signedDistFromAbove(row);
  return s != null && s > 0;
}

export function isOutOfRange(row: TradeBandRow): boolean {
  return isOutOfRangeBelow(row) || isOutOfRangeAbove(row);
}

/** Abs % to a side; used for within-range heat length labels. */
export function absDistToSide(row: TradeBandRow, side: TradeSortSide): number | null {
  const signed =
    side === "below" ? signedDistFromBelow(row) : signedDistFromAbove(row);
  if (signed == null) return null;
  return Math.abs(signed);
}

/**
 * Format distance label for the heat readout.
 * Sign only when OOR on that side: − left of Below, + right of Above.
 */
export function formatTradeDistLabel(
  row: TradeBandRow,
  side: TradeSortSide,
): string | null {
  const signed =
    side === "below" ? signedDistFromBelow(row) : signedDistFromAbove(row);
  if (signed == null || !Number.isFinite(signed)) return null;
  const rounded = Math.round(Math.abs(signed));
  if (side === "below" && signed < 0) return `−${rounded}%`;
  if (side === "above" && signed > 0) return `+${rounded}%`;
  return `${rounded}%`;
}

export function resolveUpperRefPrice(
  row: TradeBandRow,
  upperRef: TradeUpperRef,
): number | null {
  if (upperRef === "pt") {
    const pt = row.personalTarget ?? row.targetPrice;
    return pt != null && Number.isFinite(Number(pt)) ? Number(pt) : null;
  }
  const mean = row.analystTarget1y;
  return mean != null && Number.isFinite(Number(mean)) ? Number(mean) : null;
}

export type TradeBandLayout = {
  price: number;
  low: number;
  high: number;
  span: number;
  below: number | null;
  above: number | null;
  hasBelow: boolean;
  hasAbove: boolean;
  pPrice: number;
  pBelow: number | null;
  pAbove: number | null;
  pUpperRef: number | null;
  upperRefPrice: number | null;
  /** Side of heat + % label (closest boundary, or breached side if OOR). */
  focusSide: TradeSortSide | null;
  pFocus: number | null;
  distLabel: string | null;
  outOfRange: boolean;
  outOfRangeBelow: boolean;
  outOfRangeAbove: boolean;
  heatColor: string;
};

function clamp01(v: number): number {
  return Math.max(0, Math.min(100, v));
}

function posOnTrack(value: number, low: number, high: number): number {
  const span = high - low;
  const raw = span > 0 ? ((value - low) / span) * 100 : 50;
  return TRADE_BAND_PAD + (clamp01(raw) * (100 - 2 * TRADE_BAND_PAD)) / 100;
}

/** Cool within-range distance color (farther → greener). */
export function inRangeHeatColor(absDistPct: number): string {
  const t = Math.max(0, Math.min(1, absDistPct / 15));
  return `hsl(${Math.round(t * 130)}, 70%, 48%)`;
}

/** Alarm color when price is outside the planned-trade window. */
export function outOfRangeHeatColor(side: TradeSortSide): string {
  return side === "below" ? "#f97316" : "#ef4444"; // orange left / red right
}

export function buildTradeBandLayout(
  row: TradeBandRow,
  upperRef: TradeUpperRef = "analyst",
): TradeBandLayout | null {
  const price = row.currentPrice;
  if (price == null || !Number.isFinite(Number(price))) return null;
  const p = Number(price);

  const below = row.tradeBelowPrice != null ? Number(row.tradeBelowPrice) : null;
  const above = row.tradeAbovePrice != null ? Number(row.tradeAbovePrice) : null;
  const hasBelow = below != null && Number.isFinite(below);
  const hasAbove = above != null && Number.isFinite(above);

  let low: number;
  let high: number;
  if (hasBelow && hasAbove && (above as number) > (below as number)) {
    low = below as number;
    high = above as number;
  } else if (hasBelow && hasAbove) {
    // Mis-ordered thresholds — still span them.
    low = Math.min(below as number, above as number);
    high = Math.max(below as number, above as number);
  } else if (hasBelow) {
    low = below as number;
    high = Math.max(p, p * (1 + TRADE_BAND_FALLBACK_SPAN_PCT / 100));
  } else if (hasAbove) {
    high = above as number;
    low = Math.min(p, p * (1 - TRADE_BAND_FALLBACK_SPAN_PCT / 100));
  } else {
    low = p * (1 - TRADE_BAND_FALLBACK_SPAN_PCT / 100);
    high = p * (1 + TRADE_BAND_FALLBACK_SPAN_PCT / 100);
  }

  // Keep the knob on-scale when price breaches the window.
  low = Math.min(low, p);
  high = Math.max(high, p);

  const upperRefPrice = resolveUpperRefPrice(row, upperRef);
  if (upperRefPrice != null) {
    low = Math.min(low, upperRefPrice);
    high = Math.max(high, upperRefPrice);
  }

  const oorBelow = hasBelow && p < (below as number);
  const oorAbove = hasAbove && p > (above as number);
  const outOfRange = oorBelow || oorAbove;

  let focusSide: TradeSortSide | null = null;
  if (oorBelow) focusSide = "below";
  else if (oorAbove) focusSide = "above";
  else if (hasBelow || hasAbove) {
    const dBelow = hasBelow ? Math.abs(p - (below as number)) : Infinity;
    const dAbove = hasAbove ? Math.abs((above as number) - p) : Infinity;
    focusSide = dBelow <= dAbove ? "below" : "above";
  }

  const pPrice = posOnTrack(p, low, high);
  const pBelow = hasBelow ? posOnTrack(below as number, low, high) : null;
  const pAbove = hasAbove ? posOnTrack(above as number, low, high) : null;
  const pUpperRef =
    upperRefPrice != null ? posOnTrack(upperRefPrice, low, high) : null;
  const pFocus =
    focusSide === "below"
      ? pBelow
      : focusSide === "above"
        ? pAbove
        : null;

  const distLabel = focusSide ? formatTradeDistLabel(row, focusSide) : null;
  const absFocus =
    focusSide === "below"
      ? Math.abs(signedDistFromBelow(row) ?? 0)
      : focusSide === "above"
        ? Math.abs(signedDistFromAbove(row) ?? 0)
        : 0;

  const heatColor = outOfRange
    ? outOfRangeHeatColor(focusSide === "above" ? "above" : "below")
    : inRangeHeatColor(absFocus);

  return {
    price: p,
    low,
    high,
    span: high - low,
    below: hasBelow ? (below as number) : null,
    above: hasAbove ? (above as number) : null,
    hasBelow,
    hasAbove,
    pPrice,
    pBelow,
    pAbove,
    pUpperRef,
    upperRefPrice,
    focusSide,
    pFocus,
    distLabel,
    outOfRange,
    outOfRangeBelow: oorBelow,
    outOfRangeAbove: oorAbove,
    heatColor,
  };
}

/** Sort key for Trade L (ascending signed-from-below). */
export function tradeBandSortSigned(
  row: TradeBandRow,
  side: TradeSortSide,
): number | null {
  return side === "above" ? signedDistFromAbove(row) : signedDistFromBelow(row);
}

/** Compare for Trade sort: L asc (−…+), R desc (+…−). Nulls last. */
export function compareTradeBandSort(
  a: TradeBandRow,
  b: TradeBandRow,
  side: TradeSortSide,
): number {
  const av = tradeBandSortSigned(a, side);
  const bv = tradeBandSortSigned(b, side);
  const aMissing = av == null || !Number.isFinite(av);
  const bMissing = bv == null || !Number.isFinite(bv);
  if (aMissing && bMissing) return 0;
  if (aMissing) return 1;
  if (bMissing) return -1;
  if (side === "above") return (bv as number) - (av as number);
  return (av as number) - (bv as number);
}
