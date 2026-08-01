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
  /** Pattern pivot role when this point is a pattern marker. */
  role?: string;
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
  direction?: string;
  legPattern?: string;
  priceStart?: number;
  priceEnd?: number;
}

export interface ChartPatternOverlay {
  name: string;
  color: string;
  status?: string;
  type?: string;
  points: ChartPoint[];
  keyLevelLine?: { y: number; x1: number; x2: number; label?: string; price?: number };
  targetLine?: { y: number; x1: number; x2: number; price?: number };
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
  volume?: number;
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
const PRICE_COLOR = "#e9d5ff";
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

/** Match web `resolveFibLevelMeta` so horizontals get the same palette. */
function resolveFibLevelMeta(label?: string, fallbackColor?: string): {
  key: string;
  shortLabel: string;
  color: string;
} {
  const lowered = String(label || "").toLowerCase();
  if (lowered.startsWith("0%") || (lowered.includes("0%") && lowered.includes("high"))) {
    return { key: "high", shortLabel: "0% High", color: "#c4b5fd" };
  }
  if (lowered.includes("38.2")) {
    return { key: "fib-0.382", shortLabel: "38.2% Fib", color: "#60a5fa" };
  }
  if (lowered.includes("50.0") || lowered.includes("center")) {
    return { key: "fib-0.5", shortLabel: "50.0% Center", color: "#fbbf24" };
  }
  if (lowered.includes("61.8") || lowered.includes("golden")) {
    return { key: "fib-0.618", shortLabel: "61.8% Golden", color: "#f87171" };
  }
  if (lowered.startsWith("100%") || (lowered.includes("low") && lowered.includes("base"))) {
    return { key: "base", shortLabel: "100% Base", color: "#cbd5e1" };
  }
  return {
    key: "fib-other",
    shortLabel: label || "Fib",
    color: fallbackColor || "#cbd5e1",
  };
}

function enrichFibLevels(levels: ImportedFibLevel[]): ImportedFibLevel[] {
  return levels
    .filter((level) => level.price != null && Number.isFinite(Number(level.price)))
    .map((level) => {
      const meta = resolveFibLevelMeta(level.shortLabel || level.label || level.key, level.color);
      return {
        ...level,
        key: level.key || meta.key,
        shortLabel: level.shortLabel || meta.shortLabel,
        label: level.label || meta.shortLabel,
        color: level.color || meta.color,
        price: Number(level.price),
      };
    });
}

function fibLevelsFromPayload(data?: InspectorPayload | null): ImportedFibLevel[] {
  const imported = enrichFibLevels(data?.importedFibLevels ?? []);
  if (imported.length) return imported;

  const blueprint = enrichFibLevels(
    (data?.fibBlueprint?.levels ?? []).map((level) => ({
      key: level.key,
      shortLabel: level.label,
      label: level.label,
      price: level.price,
      color: level.color,
    })),
  );
  if (blueprint.length) return blueprint;

  // Last resort: build the standard ladder from `fib` (parity with web client blueprint).
  const fib = data?.fib;
  if (!fib || (fib.swingHigh == null && fib.swingLow == null && !(fib.levels?.length))) {
    return [];
  }
  const palette: Record<string, string> = {
    "0% High": "#c4b5fd",
    "38.2% Fib": "#60a5fa",
    "50.0% Center": "#fbbf24",
    "61.8% Golden": "#f87171",
    "100% Base": "#cbd5e1",
  };
  const ratioMap: Record<number, [string, string]> = {
    0.382: ["fib-0.382", "38.2% Fib"],
    0.5: ["fib-0.5", "50.0% Center"],
    0.618: ["fib-0.618", "61.8% Golden"],
  };
  const built: ImportedFibLevel[] = [];
  if (fib.swingHigh != null) {
    built.push({
      key: "high",
      label: "0% High",
      shortLabel: "0% High",
      price: fib.swingHigh,
      color: palette["0% High"],
    });
  }
  for (const level of fib.levels ?? []) {
    const ratio = level.ratio;
    if (ratio == null || level.price == null) continue;
    const mapping = ratioMap[ratio];
    if (!mapping) continue;
    const [key, label] = mapping;
    built.push({
      key,
      label,
      shortLabel: label,
      price: level.price,
      color: palette[label],
    });
  }
  if (fib.swingLow != null) {
    built.push({
      key: "base",
      label: "100% Base",
      shortLabel: "100% Base",
      price: fib.swingLow,
      color: palette["100% Base"],
    });
  }
  return enrichFibLevels(built);
}

export function buildInspectorChartModel(data?: InspectorPayload | null): InspectorChartModel {
  const timeline = data?.chartTimeline?.points ?? [];
  const waves = data?.trendWaves ?? [];
  const fibSource = fibLevelsFromPayload(data);

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
  const volumeBars: ChartVolumeBar[] = [];
  if (hasVolume) {
    for (let i = 0; i < timeline.length; i++) {
      const p = timeline[i];
      const ts = parseDate(p.date);
      if (ts == null || p.volume == null) continue;
      const prev = i > 0 ? timeline[i - 1].price : p.price;
      volumeBars.push({
        x: toX(p.date),
        h: p.volume / maxVol,
        up: (p.price ?? 0) >= (prev ?? 0),
        volume: p.volume,
      });
    }
  }

  const trendSegments: ChartTrendSegment[] = waves
    .filter((w) => w.startDate && w.endDate && w.priceStart != null && w.priceEnd != null)
    .map((wave, index) => ({
      label: wave.label ?? "",
      x1: toX(wave.startDate),
      y1: toY(wave.priceStart),
      x2: toX(wave.endDate),
      y2: toY(wave.priceEnd),
      color: trendColor(wave, index),
      direction: wave.direction,
      legPattern: wave.legPattern ?? wave.type,
      priceStart: wave.priceStart ?? undefined,
      priceEnd: wave.priceEnd ?? undefined,
    }));

  const fibLines: ChartFibLine[] = fibSource.map((level, index) => ({
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
  if (pattern) {
    const pts = (pattern.points ?? [])
      .filter((p) => p.price != null && parseDate(p.date) != null)
      .map((p) => ({
        x: toX(p.date),
        y: toY(p.price),
        price: p.price ?? undefined,
        dateMs: parseDate(p.date) ?? undefined,
        role: p.role,
      }));
    const hasGeom =
      pts.length >= 2 || pattern.keyLevel?.price != null || pattern.target != null;
    if (hasGeom) {
      const firstX = pts[0]?.x ?? 0;
      const lastX = pts[pts.length - 1]?.x ?? 1;
      patternOverlay = {
        name: pattern.name ?? "Pattern",
        color: patternColor(pattern),
        status: pattern.status,
        type: pattern.type,
        points: pts,
        keyLevelLine:
          pattern.keyLevel?.price != null
            ? {
                y: toY(pattern.keyLevel.price),
                x1: Math.min(firstX, 0.02),
                x2: 1,
                label: pattern.keyLevel.label,
                price: pattern.keyLevel.price,
              }
            : undefined,
        targetLine:
          pattern.target != null
            ? { y: toY(pattern.target), x1: lastX, x2: 1, price: pattern.target }
            : undefined,
      };
    }
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

/** padLeft = left gutter (Y labels); padTop/padRight from pad; padBottom for X ticks. */
export function pointsToPolyline(
  points: ChartPoint[],
  width: number,
  height: number,
  padLeft: number,
  pad = padLeft,
  padBottom?: number,
): string {
  const bottom = padBottom ?? pad;
  const plotW = Math.max(1, width - padLeft - pad);
  const plotH = Math.max(1, height - pad - bottom);
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
  padBottom?: number,
): { x: number; y: number } {
  const bottom = padBottom ?? pad;
  const plotW = Math.max(1, width - padLeft - pad);
  const plotH = Math.max(1, height - pad - bottom);
  return {
    x: padLeft + point.x * plotW,
    y: pad + point.y * plotH,
  };
}

export function plotMetrics(
  width: number,
  height: number,
  padLeft: number,
  pad: number,
  padBottom?: number,
) {
  const bottom = padBottom ?? pad;
  return {
    plotW: Math.max(1, width - padLeft - pad),
    plotH: Math.max(1, height - pad - bottom),
    padLeft,
    pad,
    padBottom: bottom,
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

/** Evenly spaced date ticks across the model span (for bottom timeline). */
export function xDateTicks(model: InspectorChartModel, count = 8): { x: number; label: string }[] {
  if (!(model.maxX > model.minX)) {
    return [
      {
        x: 0,
        label: new Date(model.minX).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      },
    ];
  }
  const ticks: { x: number; label: string }[] = [];
  const n = Math.max(2, count);
  for (let i = 0; i < n; i++) {
    const t = model.minX + ((model.maxX - model.minX) * i) / (n - 1);
    ticks.push({
      x: i / (n - 1),
      label: new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    });
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

function formatVolumeShort(volume: number): string {
  if (volume >= 1e9) return `${(volume / 1e9).toFixed(2)}B`;
  if (volume >= 1e6) return `${(volume / 1e6).toFixed(2)}M`;
  if (volume >= 1e3) return `${(volume / 1e3).toFixed(1)}K`;
  return String(Math.round(volume));
}

/** Compact hover parts: date, price, volume, trends, nearby pattern/trade. */
export function buildChartHoverParts(model: InspectorChartModel, point: ChartPoint): string[] {
  const parts: string[] = [];
  const date =
    point.dateMs != null
      ? new Date(point.dateMs).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
        })
      : "";
  if (date) parts.push(date);
  if (point.price != null) parts.push(formatMoney(point.price));
  if (point.volume != null && point.volume > 0) {
    parts.push(`Vol ${formatVolumeShort(point.volume)}`);
  }

  for (const seg of model.trendSegments) {
    const lo = Math.min(seg.x1, seg.x2);
    const hi = Math.max(seg.x1, seg.x2);
    if (point.x < lo - 0.02 || point.x > hi + 0.02) continue;
    const arrow = seg.direction === "down" ? "↓" : "↑";
    const kind = seg.legPattern || (seg.direction === "down" ? "Bearish" : "Bullish");
    parts.push(`${seg.label || "T"} ${arrow} ${kind}`);
  }

  const pattern = model.pattern;
  if (pattern) {
    let nearestRole: string | undefined;
    let nearestDist = 0.045;
    for (const ppt of pattern.points) {
      const d = Math.abs(ppt.x - point.x);
      if (d < nearestDist) {
        nearestDist = d;
        nearestRole = ppt.role;
      }
    }
    if (nearestRole || nearestDist < 0.04) {
      const roleBit = nearestRole ? ` (${nearestRole})` : "";
      parts.push(`${pattern.name}${roleBit}`);
    }
    if (
      pattern.keyLevelLine?.price != null &&
      point.price != null &&
      Math.abs(point.price - pattern.keyLevelLine.price) / Math.max(point.price, 1) < 0.015
    ) {
      const kl = pattern.keyLevelLine.label || "Key level";
      parts.push(`${kl} ${formatMoney(pattern.keyLevelLine.price)}`);
    }
  }

  for (const level of model.tradeLevels) {
    if (level.edge !== "none") continue;
    if (point.price == null) continue;
    if (Math.abs(point.price - level.price) / Math.max(point.price, 1) < 0.012) {
      parts.push(`${level.label} ${formatMoney(level.price)}`);
    }
  }

  return parts;
}

/** Single-line hover summary (web-style tooltip text). */
export function buildChartHoverLine(model: InspectorChartModel, point: ChartPoint): string {
  return buildChartHoverParts(model, point).join(" · ");
}

/** @deprecated Prefer buildChartHoverParts / buildChartHoverLine. */
export function buildChartHoverLines(model: InspectorChartModel, point: ChartPoint): string[] {
  return buildChartHoverParts(model, point);
}

export function formatChartHover(point: ChartPoint): string {
  const date =
    point.dateMs != null
      ? new Date(point.dateMs).toLocaleDateString("en-US", { month: "short", day: "numeric" })
      : "";
  const price = point.price != null ? formatPrice(point.price) : "—";
  return [date, price ? `Price ${price}` : ""].filter(Boolean).join(" · ");
}

/** Short fib label for the sticky price axis (e.g. "38.2%", "High", "Base"). */
export function shortFibAxisLabel(label: string): string {
  const pct = label.match(/\d+\.?\d*\s*%/);
  if (pct) return pct[0].replace(/\s/g, "");
  if (/high/i.test(label)) return "High";
  if (/base|100/i.test(label)) return "Base";
  if (/center|50/i.test(label)) return "Ctr";
  if (/golden|61/i.test(label)) return "Gld";
  return label.length > 8 ? `${label.slice(0, 7)}…` : label;
}

export function formatTradeLevelHover(level: ChartTradeLevel): string {
  return `${level.label}: ${formatMoney(level.price)}`;
}

/** Days spanned by the model (for fullscreen px-per-day sizing). */
export function modelSpanDays(model: InspectorChartModel): number {
  return Math.max(1, (model.maxX - model.minX) / 86400000);
}
