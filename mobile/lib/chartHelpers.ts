import type { ChartPatternPayload, ImportedFibLevel, InspectorPayload, TrendWavePayload } from "@/lib/types";
import { formatMoney, formatPrice } from "@/lib/format";

export interface ChartPoint {
  x: number;
  y: number;
  /** Absolute price for hover labels. */
  price?: number;
  /** Absolute date ms for hover labels. */
  dateMs?: number;
  volume?: number | null;
}

export interface ChartFibLine {
  label: string;
  price: number;
  color: string;
}

export interface ChartTrendSegment {
  label: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
}

export interface ChartPatternOverlay {
  name: string;
  color: string;
  points: ChartPoint[];
  keyLevelLine?: { y: number; x1: number; x2: number };
  targetLine?: { y: number; x1: number; x2: number };
}

export interface ChartTradeLevel {
  side: "below" | "above";
  label: string;
  price: number;
  /** Normalized y in [0,1] when in scale; null when outside. */
  y: number | null;
  edge: "none" | "top" | "bottom";
  color: string;
}

export interface ChartVolumeBar {
  x: number;
  /** 0–1 bar height relative to max volume. */
  h: number;
  up: boolean;
}

export interface InspectorChartModel {
  priceLine: ChartPoint[];
  volumeBars: ChartVolumeBar[];
  trendSegments: ChartTrendSegment[];
  fibLines: ChartFibLine[];
  tradeLevels: ChartTradeLevel[];
  pattern?: ChartPatternOverlay;
  minPrice: number;
  maxPrice: number;
  minX: number;
  maxX: number;
  priceColor: string;
  hasVolume: boolean;
}

const TREND_UP = ["#22c55e", "#4ade80", "#86efac"];
const TREND_DOWN = ["#f87171", "#ef4444", "#fca5a5"];
const PRICE_COLOR = "#c4b5fd";
const DEFAULT_FIB_COLORS = ["#f59e0b", "#eab308", "#84cc16", "#22c55e", "#14b8a6", "#38bdf8", "#a78bfa"];
export const TRADE_BELOW = "#fb7185";
export const TRADE_ABOVE = "#34d399";

function parseDate(value?: string): number | null {
  if (!value) return null;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : null;
}

function trendColor(wave: TrendWavePayload, index: number): string {
  const palette = wave.direction === "down" ? TREND_DOWN : TREND_UP;
  return palette[index % palette.length];
}

function patternColor(pattern: ChartPatternPayload): string {
  if (pattern.validation?.verdict === "stale") return "#94a3b8";
  if (pattern.type === "bullish") return "#22c55e";
  if (pattern.type === "bearish") return "#f59e0b";
  return "#f59e0b";
}

function emptyModel(): InspectorChartModel {
  return {
    priceLine: [],
    volumeBars: [],
    trendSegments: [],
    fibLines: [],
    tradeLevels: [],
    minPrice: 0,
    maxPrice: 1,
    minX: 0,
    maxX: 1,
    priceColor: PRICE_COLOR,
    hasVolume: false,
  };
}

export function buildInspectorChartModel(data?: InspectorPayload | null): InspectorChartModel {
  const timeline = data?.chartTimeline?.points ?? [];
  const waves = data?.trendWaves ?? [];
  const fibSource: ImportedFibLevel[] =
    (data?.importedFibLevels?.length ? data.importedFibLevels : null) ??
    (data?.fibBlueprint?.levels ?? []).map((level) => ({
      key: level.key,
      shortLabel: level.label,
      label: level.label,
      price: level.price,
      color: level.color,
    }));

  const quote = data?.quote;
  const tradeBelow = quote?.tradeBelowPrice ?? quote?.buyBelow;
  const tradeAbove = quote?.tradeAbovePrice ?? quote?.sellAbove;

  const dates: number[] = [];
  for (const point of timeline) {
    const ts = parseDate(point.date);
    if (ts != null) dates.push(ts);
  }
  for (const wave of waves) {
    const start = parseDate(wave.startDate);
    const end = parseDate(wave.endDate);
    if (start != null) dates.push(start);
    if (end != null) dates.push(end);
  }

  const pattern = (data?.chartPatterns ?? [])[0];
  for (const pt of pattern?.points ?? []) {
    const ts = parseDate(pt.date);
    if (ts != null) dates.push(ts);
  }

  dates.sort((a, b) => a - b);
  if (!dates.length) return emptyModel();

  const minX = dates[0];
  const maxX = dates[dates.length - 1] || minX + 1;
  const xSpan = Math.max(maxX - minX, 1);

  // Scale from price action + fib/pattern — not trade thresholds (edge markers instead).
  const prices: number[] = [];
  for (const point of timeline) {
    if (point.price != null) prices.push(point.price);
  }
  for (const wave of waves) {
    if (wave.priceStart != null) prices.push(wave.priceStart);
    if (wave.priceEnd != null) prices.push(wave.priceEnd);
  }
  for (const fib of fibSource) {
    if (fib.price != null) prices.push(fib.price);
  }
  for (const pt of pattern?.points ?? []) {
    if (pt.price != null) prices.push(pt.price);
  }
  if (pattern?.keyLevel?.price != null) prices.push(pattern.keyLevel.price);
  if (pattern?.target != null) prices.push(pattern.target);

  const minPriceRaw = prices.length ? Math.min(...prices) : 0;
  const maxPriceRaw = prices.length ? Math.max(...prices) : 1;
  const pricePad = (maxPriceRaw - minPriceRaw) * 0.06 || maxPriceRaw * 0.02 || 1;
  const yMin = minPriceRaw - pricePad;
  const yMax = maxPriceRaw + pricePad;

  const toX = (date?: string) => {
    const ts = parseDate(date);
    if (ts == null) return 0;
    return (ts - minX) / xSpan;
  };
  const toY = (price?: number | null) => {
    if (price == null) return 0.5;
    return 1 - (price - yMin) / Math.max(yMax - yMin, 1);
  };

  const priceLine: ChartPoint[] = timeline
    .filter((p) => p.price != null && parseDate(p.date) != null)
    .map((p) => {
      const dateMs = parseDate(p.date)!;
      return {
        x: toX(p.date),
        y: toY(p.price),
        price: p.price ?? undefined,
        dateMs,
        volume: p.volume ?? null,
      };
    });

  let maxVol = 0;
  for (const p of timeline) {
    if (p.volume != null && p.volume > maxVol) maxVol = p.volume;
  }
  const hasVolume = maxVol > 0 && timeline.filter((p) => p.volume != null).length > 1;
  const volumeBars: ChartVolumeBar[] = hasVolume
    ? timeline
        .map((p, i) => {
          const ts = parseDate(p.date);
          if (ts == null || p.volume == null) return null;
          const prev = i > 0 ? timeline[i - 1].price : p.price;
          return {
            x: toX(p.date),
            h: p.volume / maxVol,
            up: (p.price ?? 0) >= (prev ?? 0),
          };
        })
        .filter((b): b is ChartVolumeBar => b != null)
    : [];

  const trendSegments: ChartTrendSegment[] = waves
    .filter((w) => w.startDate && w.endDate && w.priceStart != null && w.priceEnd != null)
    .map((wave, index) => ({
      label: wave.label ?? "",
      x1: toX(wave.startDate),
      y1: toY(wave.priceStart),
      x2: toX(wave.endDate),
      y2: toY(wave.priceEnd),
      color: trendColor(wave, index),
    }));

  const fibLines: ChartFibLine[] = fibSource
    .filter((level) => level.price != null)
    .map((level, index) => ({
      label: level.shortLabel ?? level.label ?? level.key ?? "Fib",
      price: Number(level.price),
      color: level.color ?? DEFAULT_FIB_COLORS[index % DEFAULT_FIB_COLORS.length],
    }));

  const tradeLevels: ChartTradeLevel[] = [];
  const pushTrade = (side: "below" | "above", price: unknown, label: string, color: string) => {
    if (price == null || !Number.isFinite(Number(price))) return;
    const p = Number(price);
    let edge: ChartTradeLevel["edge"] = "none";
    let y: number | null = toY(p);
    if (p > yMax) {
      edge = "top";
      y = null;
    } else if (p < yMin) {
      edge = "bottom";
      y = null;
    }
    tradeLevels.push({ side, label, price: p, y, edge, color });
  };
  pushTrade("below", tradeBelow, "Trade Below", TRADE_BELOW);
  pushTrade("above", tradeAbove, "Trade Above", TRADE_ABOVE);

  let patternOverlay: ChartPatternOverlay | undefined;
  if (pattern && (pattern.points?.length ?? 0) >= 2) {
    const pts = (pattern.points ?? [])
      .filter((p) => p.price != null && parseDate(p.date) != null)
      .map((p) => ({ x: toX(p.date), y: toY(p.price) }));
    const firstX = pts[0]?.x ?? 0;
    const lastX = pts[pts.length - 1]?.x ?? 1;
    patternOverlay = {
      name: pattern.name ?? "Pattern",
      color: patternColor(pattern),
      points: pts,
      keyLevelLine:
        pattern.keyLevel?.price != null
          ? { y: toY(pattern.keyLevel.price), x1: firstX, x2: 1 }
          : undefined,
      targetLine:
        pattern.target != null ? { y: toY(pattern.target), x1: lastX, x2: 1 } : undefined,
    };
  }

  return {
    priceLine,
    volumeBars,
    trendSegments,
    fibLines,
    tradeLevels,
    pattern: patternOverlay,
    minPrice: yMin,
    maxPrice: yMax,
    minX,
    maxX,
    priceColor: PRICE_COLOR,
    hasVolume,
  };
}

/** padLeft = left gutter (Y labels); pad = top/right/bottom gutter. */
export function pointsToPolyline(
  points: ChartPoint[],
  width: number,
  height: number,
  padLeft: number,
  pad = padLeft,
): string {
  const plotW = Math.max(1, width - padLeft - pad);
  const plotH = Math.max(1, height - pad * 2);
  return points
    .map((p) => {
      const x = padLeft + p.x * plotW;
      const y = pad + p.y * plotH;
      return `${x},${y}`;
    })
    .join(" ");
}

export function chartCoord(
  point: ChartPoint,
  width: number,
  height: number,
  padLeft: number,
  pad = padLeft,
): { x: number; y: number } {
  const plotW = Math.max(1, width - padLeft - pad);
  const plotH = Math.max(1, height - pad * 2);
  return {
    x: padLeft + point.x * plotW,
    y: pad + point.y * plotH,
  };
}

export function plotMetrics(width: number, height: number, padLeft: number, pad: number) {
  return {
    plotW: Math.max(1, width - padLeft - pad),
    plotH: Math.max(1, height - pad * 2),
    padLeft,
    pad,
  };
}

/** Fullscreen chart content width so ~60 calendar days fill the viewport. */
export function fullscreenChartWidth(model: InspectorChartModel, viewportWidth: number): number {
  const daysPerView = 60;
  const totalDays = modelSpanDays(model);
  const pxPerDay = viewportWidth / daysPerView;
  return Math.max(viewportWidth, Math.round(totalDays * pxPerDay));
}

export function yTicks(minPrice: number, maxPrice: number, count = 5): number[] {
  if (!(maxPrice > minPrice)) return [minPrice];
  const ticks: number[] = [];
  for (let i = 0; i < count; i++) {
    ticks.push(minPrice + ((maxPrice - minPrice) * i) / (count - 1));
  }
  return ticks;
}

export function nearestPricePoint(model: InspectorChartModel, normX: number): ChartPoint | null {
  if (!model.priceLine.length) return null;
  let best = model.priceLine[0];
  let bestDist = Math.abs(best.x - normX);
  for (const pt of model.priceLine) {
    const d = Math.abs(pt.x - normX);
    if (d < bestDist) {
      best = pt;
      bestDist = d;
    }
  }
  return best;
}

export function formatChartHover(point: ChartPoint): string {
  const date =
    point.dateMs != null
      ? new Date(point.dateMs).toLocaleDateString("en-US", { month: "short", day: "numeric" })
      : "";
  const price = point.price != null ? formatPrice(point.price) : "—";
  return [date, price ? `Price ${price}` : ""].filter(Boolean).join(" · ");
}

export function formatTradeLevelHover(level: ChartTradeLevel): string {
  return `${level.label}: ${formatMoney(level.price)}`;
}

/** Days spanned by the model (for fullscreen px-per-day sizing). */
export function modelSpanDays(model: InspectorChartModel): number {
  return Math.max(1, (model.maxX - model.minX) / 86400000);
}
