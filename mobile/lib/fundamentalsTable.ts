import {
  formatColoredRatioPercent,
  formatLargeMoney,
  formatPrice,
  formatRatio,
  formatRatioPercent,
} from "@/lib/format";
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

export function fundRangePosition(row: FundamentalsRow): number | null {
  const price = fundNum(row.currentPrice);
  const high = fundNum(fundVal(row, "priceRange", "high52w"));
  const low = fundNum(fundVal(row, "priceRange", "low52w"));
  if (price == null || high == null || low == null || high <= low) return null;
  return ((price - low) / (high - low)) * 100;
}

export function targetMeanDeviation(row: FundamentalsRow): number | null {
  const price = fundNum(row.currentPrice);
  const mean = fundNum(fundVal(row, "analyst", "targetMean"));
  if (price == null || mean == null || mean === 0) return null;
  return ((price - mean) / mean) * 100;
}

const VAL_STICKY: FundamentalsColumn[] = [
  { key: "symbol", label: "Symbol", width: 68, kind: "symbol" },
  { key: "price", label: "Price", width: 76, align: "right", kind: "price" },
  { key: "range52", label: "52W Range %", width: 112, align: "right", kind: "range52" },
];

const VAL_SCROLL: FundamentalsColumn[] = [
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

const HEALTH_STICKY: FundamentalsColumn[] = [
  { key: "symbol", label: "Symbol", width: 64, kind: "symbol" },
  { key: "price", label: "Price", width: 72, align: "right", kind: "price" },
];

const HEALTH_SCROLL: FundamentalsColumn[] = [
  { key: "beta", label: "Beta", width: 52, align: "right", kind: "ratio" },
  { key: "d2e", label: "D/E", width: 52, align: "right", kind: "ratio" },
  { key: "current", label: "Current", width: 60, align: "right", kind: "ratio" },
  { key: "quick", label: "Quick", width: 56, align: "right", kind: "ratio" },
  { key: "fcf", label: "FCF", width: 68, align: "right", kind: "largeMoney" },
  { key: "cash", label: "Cash", width: 68, align: "right", kind: "largeMoney" },
  { key: "debt", label: "Debt", width: 68, align: "right", kind: "largeMoney" },
  { key: "rec", label: "Rating", width: 72, kind: "rating" },
  { key: "tgtRange", label: "Target", width: 120, kind: "targetRange" },
  { key: "analysts", label: "#", width: 40, align: "right", kind: "ratio" },
];

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
    case "d2e":
      return fundNum(fundVal(row, "financialHealth", "debtToEquity"));
    case "current":
      return fundNum(fundVal(row, "financialHealth", "currentRatio"));
    case "quick":
      return fundNum(fundVal(row, "financialHealth", "quickRatio"));
    case "fcf":
      return fundNum(fundVal(row, "financialHealth", "freeCashflow"));
    case "cash":
      return fundNum(fundVal(row, "financialHealth", "totalCash"));
    case "debt":
      return fundNum(fundVal(row, "financialHealth", "totalDebt"));
    case "rec":
      return String(fundVal(row, "analyst", "recommendationKey") || "");
    case "tgtRange":
      return targetMeanDeviation(row);
    case "analysts":
      return fundNum(fundVal(row, "analyst", "analystCount"));
    default:
      return null;
  }
}

function compareRows(
  a: FundamentalsRow,
  b: FundamentalsRow,
  key: FundamentalsSortKey,
): number {
  const av = sortValue(a, key);
  const bv = sortValue(b, key);
  const aNull = av == null || av === "";
  const bNull = bv == null || bv === "";
  if (aNull && bNull) return a.symbol.localeCompare(b.symbol);
  if (aNull) return 1;
  if (bNull) return -1;
  if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv);
  return Number(av) - Number(bv);
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
  const mult = sort.direction === "asc" ? 1 : -1;
  sorted.sort((a, b) => {
    const cmp = compareRows(a, b, sort.key as FundamentalsSortKey);
    return cmp === 0 ? a.symbol.localeCompare(b.symbol) : cmp * mult;
  });
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
      case "peg":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "pegRatio"))) };
      case "ev":
        return { text: formatRatio(fundNum(fundVal(row, "valuation", "evToEbitda"))) };
      case "revG":
        return formatColoredRatioPercent(fundNum(fundVal(row, "growthProfitability", "revenueGrowth")));
      case "earnG":
        return formatColoredRatioPercent(fundNum(fundVal(row, "growthProfitability", "earningsGrowth")));
      case "gm":
        return { text: formatRatioPercent(fundNum(fundVal(row, "growthProfitability", "grossMargin"))) };
      case "om":
        return { text: formatRatioPercent(fundNum(fundVal(row, "growthProfitability", "operatingMargin"))) };
      case "pm":
        return { text: formatRatioPercent(fundNum(fundVal(row, "growthProfitability", "profitMargin"))) };
      case "roe":
        return { text: formatRatioPercent(fundNum(fundVal(row, "growthProfitability", "returnOnEquity"))) };
      case "beta":
        return { text: formatRatio(fundNum(fundVal(row, "profile", "beta"))) };
      case "d2e":
        return { text: formatRatio(fundNum(fundVal(row, "financialHealth", "debtToEquity"))) };
      case "current":
        return { text: formatRatio(fundNum(fundVal(row, "financialHealth", "currentRatio"))) };
      case "quick":
        return { text: formatRatio(fundNum(fundVal(row, "financialHealth", "quickRatio"))) };
      case "fcf": {
        const n = fundNum(fundVal(row, "financialHealth", "freeCashflow"));
        return { text: formatLargeMoney(n), color: n != null && n < 0 ? "#f87171" : undefined };
      }
      case "cash":
        return { text: formatLargeMoney(fundNum(fundVal(row, "financialHealth", "totalCash"))) };
      case "debt":
        return { text: formatLargeMoney(fundNum(fundVal(row, "financialHealth", "totalDebt"))) };
      case "rec": {
        const k = fundVal(row, "analyst", "recommendationKey");
        return { text: k ? String(k).replace(/_/g, " ") : "—" };
      }
      case "analysts": {
        const n = fundNum(fundVal(row, "analyst", "analystCount"));
        return { text: n != null ? String(Math.round(n)) : "—" };
      }
      default:
        return { text: "—" };
    }
  })();

  return val;
}
