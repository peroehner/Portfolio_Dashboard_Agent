import type { ChartPatternPayload, ImportedFibLevel, InspectorPayload, TrendWavePayload } from "@/lib/types";

export interface ChartPoint {
  x: number;
  y: number;
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

export interface InspectorChartModel {
  priceLine: ChartPoint[];
  trendSegments: ChartTrendSegment[];
  fibLines: ChartFibLine[];
  pattern?: ChartPatternOverlay;
  minPrice: number;
  maxPrice: number;
  minX: number;
  maxX: number;
  priceColor: string;
}

const TREND_UP = ["#22c55e", "#4ade80", "#86efac"];
const TREND_DOWN = ["#f87171", "#ef4444", "#fca5a5"];
const PRICE_COLOR = "#c4b5fd";
const DEFAULT_FIB_COLORS = ["#f59e0b", "#eab308", "#84cc16", "#22c55e", "#14b8a6", "#38bdf8", "#a78bfa"];

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

  if (!dates.length) {
    return {
      priceLine: [],
      trendSegments: [],
      fibLines: [],
      minPrice: 0,
      maxPrice: 1,
      minX: 0,
      maxX: 1,
      priceColor: PRICE_COLOR,
    };
  }

  const minX = dates[0];
  const maxX = dates[dates.length - 1] || minX + 1;
  const xSpan = Math.max(maxX - minX, 1);

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

  const minPrice = prices.length ? Math.min(...prices) : 0;
  const maxPrice = prices.length ? Math.max(...prices) : 1;
  const pricePad = (maxPrice - minPrice) * 0.06 || maxPrice * 0.02 || 1;
  const yMin = minPrice - pricePad;
  const yMax = maxPrice + pricePad;

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
    .map((p) => ({ x: toX(p.date), y: toY(p.price) }));

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
    trendSegments,
    fibLines,
    pattern: patternOverlay,
    minPrice: yMin,
    maxPrice: yMax,
    minX,
    maxX,
    priceColor: PRICE_COLOR,
  };
}

export function pointsToPolyline(points: ChartPoint[], width: number, height: number, pad: number): string {
  return points
    .map((p) => {
      const x = pad + p.x * (width - pad * 2);
      const y = pad + p.y * (height - pad * 2);
      return `${x},${y}`;
    })
    .join(" ");
}

export function chartCoord(
  point: ChartPoint,
  width: number,
  height: number,
  pad: number,
): { x: number; y: number } {
  return {
    x: pad + point.x * (width - pad * 2),
    y: pad + point.y * (height - pad * 2),
  };
}
