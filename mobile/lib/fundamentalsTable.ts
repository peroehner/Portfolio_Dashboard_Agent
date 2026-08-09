import {
  formatColoredRatioPercent,
  formatLargeMoney,
  formatPrice,
  formatRatio,
  formatRatioPercent,
} from "@/lib/format";
import {
  fundToneBeta,
  fundToneColor,
  fundToneCurrent,
  fundToneDebtEquity,
  fundTonePeg,
  fundToneQuick,
  fundToneSignedRatio,
} from "@/lib/fundamentalsTone";
import { colors } from "@/lib/theme";
import type { FundamentalsRow } from "@/lib/types";

export type FundamentalsTab = "val" | "health";

export type FundamentalsSortKey = string;

export type SortDirection = "asc" | "desc";

export interface FundamentalsSortState {
  key: FundamentalsSortKey | null;
  direction: SortDirection | null;
}

export type FundamentalsCellKind =
  | "text"
  | "money"
  | "largeMoney"
  | "ratio"
  | "ratioPct"
  | "ratioPctColored"
  | "range52"
  | "targetRange"
  | "rating"
  | "price"
  | "symbol";

export interface FundamentalsColumn {
  key: FundamentalsSortKey;
  label: string;
  width: number;
  align?: "left" | "right";
  sticky?: boolean;
  kind: FundamentalsCellKind;
}

export function fundVal(
  row: FundamentalsRow,
  group: string,
  key: string,
): unknown {
  const g = row.fundamentals?.[group as keyof NonNullable<FundamentalsRow["fundamentals"]>];
  if (!g || typeof g !== "object") return undefined;
  return (g as Record<string, unknown>)[key];
}

export function fundNum(value: unknown): number | null {
  if (value == null || value === "") return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : null;
}

export function fundRangeLevels(row: FundamentalsRow): {
  price: number | null;
  storedHigh: number | null;
  storedLow: number | null;
  high: number | null;
  low: number | null;
} {
  const price = fundNum(row.currentPrice);
  const storedHigh = fundNum(fundVal(row, "priceRange", "high52w"));
  const storedLow = fundNum(fundVal(row, "priceRange", "low52w"));
  if (price == null || storedHigh == null || storedLow == null) {
    return { price, storedHigh, storedLow, high: storedHigh, low: storedLow };
  }
  return {
    price,
    storedHigh,
    storedLow,
    high: Math.max(storedHigh, price),
    low: Math.min(storedLow, price),
  };
}

export function fundRangePosition(row: FundamentalsRow): number | null {
  const { price, high, low } = fundRangeLevels(row);
  if (price == null || high == null || low == null || high <= low) return null;
  const raw = ((price - low) / (high - low)) * 100;
  return Math.max(0, Math.min(100, raw));
}

export function recommendationRank(key: unknown): number | null {
  const normalized = String(key || "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "_");
  switch (normalized) {
    case "strong_buy":
      return 6;
    case "buy":
    case "outperform":
    case "overweight":
      return 5;
    case "hold":
    case "neutral":
    case "equal_weight":
    case "market_perform":
      return 4;
    case "underperform":
    case "underweight":
      return 3;
    case "sell":
      return 2;
    case "strong_sell":
      return 1;
    default:
      return null;
  }
}

/** Upside from price → mean target: (mean − price) / price. */
export function targetMeanDeviation(row: FundamentalsRow): number | null {
  const price = fundNum(row.currentPrice);
  const mean = fundNum(fundVal(row, "analyst", "targetMean"));
  if (price == null || mean == null || price === 0) return null;
  return ((mean - price) / price) * 100;
}

const VAL_STICKY: FundamentalsColumn[] = [
  { key: "symbol", label: "Symbol", width: 68, kind: "symbol" },
  { key: "price", label: "Price", width: 76, align: "right", kind: "price" },
];

const VAL_SCROLL: FundamentalsColumn[] = [
  { key: "range52", label: "52W Range %", width: 112, align: "right", kind: "range52" },
  { key: "sector", label: "Sector", width: 88, kind: "text" },
  { key: "mktCap", label: "Mkt Cap", width: 72, align: "right", kind: "largeMoney" },
  { key: "ttmPe", label: "P/E", width: 56, align: "right", kind: "ratio" },
  { key: "fwdPe", label: "Fwd P/E", width: 64, align: "right", kind: "ratio" },
  { key: "pb", label: "P/B", width: 52, align: "right", kind: "ratio" },
  { key: "ps", label: "P/S", width: 52, align: "right", kind: "ratio" },
  { key: "peg", label: "PEG", width: 52, align: "right", kind: "ratio" },
  { key: "ev", label: "EV/EBITDA", width: 72, align: "right", kind: "ratio" },
  { key: "revG", label: "Rev Gr", width: 64, align: "right", kind: "ratioPctColored" },
  { key: "earnG", label: "Earn Gr", width: 64, align: "right", kind: "ratioPctColored" },
  { key: "gm", label: "Gross", width: 58, align: "right", kind: "ratioPct" },
  { key: "om", label: "Op", width: 52, align: "right", kind: "ratioPct" },
  { key: "pm", label: "Profit", width: 58, align: "right", kind: "ratioPct" },
  { key: "roe", label: "ROE", width: 52, align: "right", kind: "ratioPct" },
];

function toneRatio(
  value: number | null,
  tone: ReturnType<typeof fundTonePeg>,
): FundamentalsCellText {
  return { text: formatRatio(value), color: fundToneColor(tone) };
}

function toneRatioPercent(
  value: number | null,
  tone: ReturnType<typeof fundToneSignedRatio>,
): FundamentalsCellText {
  return { text: formatRatioPercent(value), color: fundToneColor(tone) };
}

const HEALTH_STICKY: FundamentalsColumn[] = [
  { key: "symbol", label: "Symbol", width: 64, kind: "symbol" },
];

const HEALTH_SCROLL: FundamentalsColumn[] = [
  { key: "rec", label: "Rating", width: 96, kind: "rating" },
  { key: "tgtRange", label: "Target", width: 120, kind: "targetRange" },
  { key: "price", label: "Price", width: 72, align: "right", kind: "price" },
  { key: "beta", label: "Beta", width: 52, align: "right", kind: "ratio" },
  { key: "current", label: "Current", width: 64, align: "right", kind: "ratio" },
  { key: "quick", label: "Quick", width: 56, align: "right", kind: "ratio" },
  { key: "d2e", label: "Debt / E", width: 64, align: "right", kind: "ratio" },
  { key: "fcf", label: "FCF", width: 68, align: "right", kind: "largeMoney" },
  { key: "ma50", label: "50-Day Avg", width: 84, align: "right", kind: "money" },
  { key: "ma200", label: "200-Day Avg", width: 92, align: "right", kind: "money" },
  { key: "closest", label: "Closest", width: 118, align: "right", kind: "text" },
];

/** Short Closest labels (web-aligned levels). */
const FUND_LEVELS: { key: string; label: string; field: string }[] = [
  { key: "high52", label: "52W-Hi", field: "high52w" },
  { key: "low52", label: "52W-Lo", field: "low52w" },
  { key: "ma50", label: "50-Avg", field: "ma50" },
  { key: "ma200", label: "200-Avg", field: "ma200" },
];

export function fundLevelDeviations(row: FundamentalsRow): {
  key: string;
  label: string;
  field: string;
  level: number;
  deviation: number;
  absDev: number;
}[] {
  const { price, high, low } = fundRangeLevels(row);
  if (price == null) return [];
  const effective: Record<string, number | null> = {
    high52w: high,
    low52w: low,
    ma50: fundNum(fundVal(row, "priceRange", "ma50")),
    ma200: fundNum(fundVal(row, "priceRange", "ma200")),
  };
  const out: {
    key: string;
    label: string;
    field: string;
    level: number;
    deviation: number;
    absDev: number;
  }[] = [];
  for (const lvl of FUND_LEVELS) {
    const level = effective[lvl.field];
    if (level == null || level === 0) continue;
    const deviation = ((price - level) / level) * 100;
    out.push({ ...lvl, level, deviation, absDev: Math.abs(deviation) });
  }
  return out;
}

export function fundClosestLevel(row: FundamentalsRow) {
  const devs = fundLevelDeviations(row);
  if (!devs.length) return null;
  return devs.reduce((best, d) => (d.absDev < best.absDev ? d : best));
}

export function fundLevelAbsDev(row: FundamentalsRow, field: string): number | null {
  const price = fundNum(row.currentPrice);
  let level = fundNum(fundVal(row, "priceRange", field));
  if (field === "high52w" || field === "low52w") {
    const range = fundRangeLevels(row);
    level = field === "high52w" ? range.high : range.low;
  }
  if (price == null || level == null || level === 0) return null;
  return Math.abs(((price - level) / level) * 100);
}

export function fundamentalsColumns(tab: FundamentalsTab): {
  sticky: FundamentalsColumn[];
  scroll: FundamentalsColumn[];
} {
  return tab === "health"
    ? { sticky: HEALTH_STICKY, scroll: HEALTH_SCROLL }
    : { sticky: VAL_STICKY, scroll: VAL_SCROLL };
}

export function cycleFundamentalsSort(
  current: FundamentalsSortState,
  key: FundamentalsSortKey,
): FundamentalsSortState {
  if (current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return { key: null, direction: null };
}

export function sortHeaderLabel(
  label: string,
  key: FundamentalsSortKey,
  sort: FundamentalsSortState,
): string {
  if (sort.key !== key || !sort.direction) return label;
  return sort.direction === "asc" ? `${label} ↑` : `${label} ↓`;
}

function sortValue(row: FundamentalsRow, key: FundamentalsSortKey): string | number | null {
  switch (key) {
    case "symbol":
      return row.symbol;
    case "price":
      return fundNum(row.currentPrice);
    case "range52":
      return fundRangePosition(row);
    case "sector":
      return String(fundVal(row, "profile", "sector") || "");
    case "mktCap":
      return fundNum(fundVal(row, "profile", "marketCap"));
    case "ttmPe":
      return fundNum(fundVal(row, "valuation", "trailingPe"));
    case "fwdPe":
      return fundNum(fundVal(row, "valuation", "forwardPe"));
    case "pb":
      return fundNum(fundVal(row, "valuation", "priceToBook"));
    case "ps":
      return fundNum(fundVal(row, "valuation", "priceToSales"));
    case "peg":
      return fundNum(fundVal(row, "valuation", "pegRatio"));
    case "ev":
      return fundNum(fundVal(row, "valuation", "evToEbitda"));
    case "revG":
      return fundNum(fundVal(row, "growthProfitability", "revenueGrowth"));
    case "earnG":
      return fundNum(fundVal(row, "growthProfitability", "earningsGrowth"));
    case "gm":
      return fundNum(fundVal(row, "growthProfitability", "grossMargin"));
    case "om":
      return fundNum(fundVal(row, "growthProfitability", "operatingMargin"));
    case "pm":
      return fundNum(fundVal(row, "growthProfitability", "profitMargin"));
    case "roe":
      return fundNum(fundVal(row, "growthProfitability", "returnOnEquity"));
    case "beta":
      return fundNum(fundVal(row, "profile", "beta"));
    case "current":
      return fundNum(fundVal(row, "financialHealth", "currentRatio"));
    case "quick":
      return fundNum(fundVal(row, "financialHealth", "quickRatio"));
    case "d2e":
      return fundNum(fundVal(row, "financialHealth", "debtToEquity"));
    case "fcf":
      return fundNum(fundVal(row, "financialHealth", "freeCashflow"));
    case "ma50":
      return fundLevelAbsDev(row, "ma50");
    case "ma200":
      return fundLevelAbsDev(row, "ma200");
    case "closest": {
      const c = fundClosestLevel(row);
      return c ? c.absDev : null;
    }
    case "rec":
      return recommendationRank(fundVal(row, "analyst", "recommendationKey"));
    case "tgtRange":
      return targetMeanDeviation(row);
    default:
      return null;
  }
}

function compareRows(
  a: FundamentalsRow,
  b: FundamentalsRow,
  key: FundamentalsSortKey,
  direction: SortDirection,
): number {
  const av = sortValue(a, key);
  const bv = sortValue(b, key);
  const aNull = av == null || av === "";
  const bNull = bv == null || bv === "";
  if (aNull && bNull) return a.symbol.localeCompare(b.symbol);
  if (aNull) return 1;
  if (bNull) return -1;
  let cmp = 0;
  if (typeof av === "string" && typeof bv === "string") cmp = av.localeCompare(bv);
  else cmp = Number(av) - Number(bv);
  if (cmp === 0) return a.symbol.localeCompare(b.symbol);
  const mult = direction === "asc" ? 1 : -1;
  return cmp * mult;
}

export function sortFundamentalsRows(
  rows: FundamentalsRow[],
  sort: FundamentalsSortState,
): FundamentalsRow[] {
  const sorted = [...rows];
  if (!sort.key || !sort.direction) {
    sorted.sort((a, b) => a.symbol.localeCompare(b.symbol));
    return sorted;
  }
  sorted.sort((a, b) =>
    compareRows(a, b, sort.key as FundamentalsSortKey, sort.direction as SortDirection),
  );
  return sorted;
}

export interface FundamentalsCellText {
  text: string;
  color?: string;
}

export function renderFundamentalsCell(
  row: FundamentalsRow,
  col: FundamentalsColumn,
): FundamentalsCellText | { custom: FundamentalsCellKind } {
  if (col.kind === "symbol" || col.kind === "range52" || col.kind === "targetRange") {
    return { custom: col.kind };
  }

  const val = (() => {
    switch (col.key) {
      case "price":
        return { text: formatPrice(fundNum(row.currentPrice)) };
      case "sector":
        return { text: String(fundVal(row, "profile", "sector") || "—") };
      case "mktCap":
        return { text: formatLargeMoney(fundNum(fundVal(row, "profile", "marketCap"))) };
      case "ttmPe":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "trailingPe"))) };
      case "fwdPe":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "forwardPe"))) };
      case "pb":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "priceToBook"))) };
      case "ps":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "priceToSales"))) };
      case "peg": {
        const n = fundNum(fundVal(row, "valuation", "pegRatio"));
        return toneRatio(n, fundTonePeg(n));
      }
      case "ev":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "evToEbitda"))) };
      case "revG":
        return formatColoredRatioPercent(fundNum(fundVal(row, "growthProfitability", "revenueGrowth")));
      case "earnG":
        return formatColoredRatioPercent(fundNum(fundVal(row, "growthProfitability", "earningsGrowth")));
      case "gm": {
        const n = fundNum(fundVal(row, "growthProfitability", "grossMargin"));
        return toneRatioPercent(n, fundToneSignedRatio(n));
      }
      case "om": {
        const n = fundNum(fundVal(row, "growthProfitability", "operatingMargin"));
        return toneRatioPercent(n, fundToneSignedRatio(n));
      }
      case "pm": {
        const n = fundNum(fundVal(row, "growthProfitability", "profitMargin"));
        return toneRatioPercent(n, fundToneSignedRatio(n));
      }
      case "roe": {
        const n = fundNum(fundVal(row, "growthProfitability", "returnOnEquity"));
        return toneRatioPercent(n, fundToneSignedRatio(n));
      }
      case "beta": {
        const n = fundNum(fundVal(row, "profile", "beta"));
        return toneRatio(n, fundToneBeta(n));
      }
      case "current": {
        const n = fundNum(fundVal(row, "financialHealth", "currentRatio"));
        return toneRatio(n, fundToneCurrent(n));
      }
      case "quick": {
        const n = fundNum(fundVal(row, "financialHealth", "quickRatio"));
        return toneRatio(n, fundToneQuick(n));
      }
      case "d2e": {
        const n = fundNum(fundVal(row, "financialHealth", "debtToEquity"));
        return toneRatio(n, fundToneDebtEquity(n));
      }
      case "fcf": {
        const n = fundNum(fundVal(row, "financialHealth", "freeCashflow"));
        return {
          text: formatLargeMoney(n),
          color: n == null ? undefined : n >= 0 ? colors.buy : colors.sell,
        };
      }
      case "ma50":
        return { text: formatPrice(fundNum(fundVal(row, "priceRange", "ma50"))) };
      case "ma200":
        return { text: formatPrice(fundNum(fundVal(row, "priceRange", "ma200"))) };
      case "closest": {
        const c = fundClosestLevel(row);
        if (!c) return { text: "—" };
        const sign = c.deviation > 0 ? "+" : "";
        return {
          text: `${c.label} ${sign}${c.deviation.toFixed(1)}%`,
          color: c.deviation >= 0 ? colors.buy : colors.sell,
        };
      }
      case "rec": {
        const k = fundVal(row, "analyst", "recommendationKey");
        const rating = k ? String(k).replace(/_/g, " ") : "—";
        const n = fundNum(fundVal(row, "analyst", "analystCount"));
        if (rating === "—" || n == null) return { text: rating };
        return { text: `${rating} (${Math.round(n)})` };
      }
      default:
        return { text: "—" };
    }
  })();

  return val;
}

/** Sum large-money fundamentals for displayed rows; ratios/ratings stay blank. */
export function computeFundamentalsTotals(
  rows: FundamentalsRow[],
): Record<string, FundamentalsCellText> {
  if (!rows.length) return {};

  const sumFund = (group: string, key: string) =>
    rows.reduce((acc, row) => acc + (fundNum(fundVal(row, group, key)) || 0), 0);

  const mktCap = sumFund("profile", "marketCap");
  const fcf = sumFund("financialHealth", "freeCashflow");

  return {
    symbol: { text: "TOTAL" },
    mktCap: { text: formatLargeMoney(mktCap || null) },
    fcf: {
      text: formatLargeMoney(fcf || null),
      color: fcf < 0 ? colors.sell : undefined,
    },
  };
}

