import type { Assessment, Holding, PortfolioRow, PortfolioSymbol, SaiAction } from "@/lib/types";

export type PortfolioSortKey =
  | "symbol"
  | "sai"
  | "currentPrice"
  | "dayChangePct"
  | "tradeBand"
  | "quantity"
  | "marketValue"
  | "weightPct"
  | "annualDividend"
  | "unrealizedGain"
  | "gainPct"
  | "analystTarget1y"
  | "analystUpsidePct"
  | "analystTargetValue"
  | "personalTarget"
  | "personalUpsidePct"
  | "personalTargetValue";

export type SortDirection = "asc" | "desc";

export interface PortfolioSortState {
  key: PortfolioSortKey | null;
  direction: SortDirection | null;
}

export interface PortfolioColumn {
  key: PortfolioSortKey;
  label: string;
  width: number;
  align?: "left" | "right";
  pct?: boolean;
  money?: boolean;
  price?: boolean;
  sticky?: boolean;
  tradeBand?: boolean;
}

export const STICKY_COLUMNS: PortfolioColumn[] = [
  { key: "symbol", label: "Symbol", width: 74, sticky: true },
  { key: "sai", label: "SAI", width: 54, sticky: true, align: "right" },
];

export const PORTFOLIO_SCROLL_COLUMNS: PortfolioColumn[] = [
  { key: "currentPrice", label: "Price", width: 78, align: "right", price: true },
  { key: "dayChangePct", label: "Day %", width: 64, align: "right", pct: true },
  { key: "tradeBand", label: "Trade", width: 150, tradeBand: true },
  { key: "quantity", label: "Qty", width: 56, align: "right" },
  { key: "marketValue", label: "Value", width: 72, align: "right", money: true },
  { key: "weightPct", label: "Wt %", width: 58, align: "right" },
  { key: "annualDividend", label: "Div", width: 68, align: "right", money: true },
  { key: "unrealizedGain", label: "Gain", width: 72, align: "right", money: true },
  { key: "gainPct", label: "Gain %", width: 72, align: "right", pct: true },
  { key: "analystTarget1y", label: "1YT", width: 78, align: "right", price: true },
  { key: "analystUpsidePct", label: "1YT %", width: 68, align: "right", pct: true },
  { key: "analystTargetValue", label: "1YT Val", width: 76, align: "right", money: true },
  { key: "personalTarget", label: "PT", width: 78, align: "right", price: true },
  { key: "personalUpsidePct", label: "PT %", width: 68, align: "right", pct: true },
  { key: "personalTargetValue", label: "PT Val", width: 76, align: "right", money: true },
];

const LANDSCAPE_WIDTH_SCALE = 0.78;

/** Keep header labels on one line when columns are scaled for landscape. */
const LANDSCAPE_MIN_WIDTHS: Partial<Record<PortfolioSortKey, number>> = {
  symbol: 62,
  gainPct: 58,
  analystTarget1y: 54,
  analystUpsidePct: 56,
  personalTarget: 52,
  personalUpsidePct: 54,
};

function landscapeColumnWidth(col: PortfolioColumn): number {
  const scaled = Math.round(col.width * LANDSCAPE_WIDTH_SCALE);
  const floor = LANDSCAPE_MIN_WIDTHS[col.key] ?? (col.sticky ? 48 : 50);
  return Math.max(floor, scaled);
}

export function portfolioTableColumns(landscape: boolean): {
  sticky: PortfolioColumn[];
  scroll: PortfolioColumn[];
} {
  if (!landscape) {
    return { sticky: STICKY_COLUMNS, scroll: PORTFOLIO_SCROLL_COLUMNS };
  }
  return {
    sticky: STICKY_COLUMNS.map((col) => ({
      ...col,
      width: landscapeColumnWidth(col),
    })),
    scroll: PORTFOLIO_SCROLL_COLUMNS.map((col) => ({
      ...col,
      width: landscapeColumnWidth(col),
    })),
  };
}

export function actionRank(action?: SaiAction | null): number {
  const key = String(action || "").toLowerCase();
  if (key === "sell") return 4;
  if (key === "watch") return 3;
  if (key === "hold") return 2;
  if (key === "buy") return 1;
  return 0;
}

export function cyclePortfolioSort(
  current: PortfolioSortState,
  key: PortfolioSortKey,
): PortfolioSortState {
  if (current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return { key: null, direction: null };
}

function upsidePct(target: number | null | undefined, price: number | null | undefined): number | null {
  if (target == null || price == null || !price) return null;
  return Math.round(((target - price) / price) * 10000) / 100;
}

export function tradeBandClosestDist(row: PortfolioRow): number {
  const price = row.currentPrice;
  if (price == null || price === 0) return Infinity;
  const dists: number[] = [];
  if (row.tradeBelowPrice != null) {
    dists.push((Math.abs(price - row.tradeBelowPrice) / price) * 100);
  }
  if (row.tradeAbovePrice != null) {
    dists.push((Math.abs(row.tradeAbovePrice - price) / price) * 100);
  }
  return dists.length ? Math.min(...dists) : Infinity;
}

function buildRow(
  symbol: PortfolioSymbol,
  holding: Holding | undefined,
  assessment: Assessment | undefined,
): PortfolioRow {
  const quantity = holding?.quantity ?? 0;
  const currentPrice = holding?.currentPrice ?? symbol.currentPrice ?? null;
  const personalTarget = holding?.personalTarget ?? symbol.targetPrice ?? null;
  const analystTarget1y = holding?.analystTarget1y ?? symbol.analystTarget1y ?? null;

  return {
    symbol: symbol.symbol,
    saiAction: assessment?.action,
    saiConfidence: assessment?.confidence,
    currentPrice,
    dayChangePct: holding?.dayChangePct ?? symbol.dayChangePct ?? null,
    quantity: quantity > 0 ? quantity : null,
    marketValue: holding?.marketValue ?? null,
    weightPct: holding?.weightPct ?? null,
    annualDividend: holding?.annualDividend ?? null,
    unrealizedGain: holding?.unrealizedGain ?? null,
    gainPct: holding?.gainPct ?? null,
    analystTarget1y,
    analystTargetLow: symbol.analystTargetLow ?? null,
    analystTargetHigh: symbol.analystTargetHigh ?? null,
    analystUpsidePct: holding?.analystUpsidePct ?? upsidePct(analystTarget1y, currentPrice),
    analystTargetValue: holding?.analystTargetValue ?? null,
    personalTarget,
    personalUpsidePct: holding?.personalUpsidePct ?? upsidePct(personalTarget, currentPrice),
    personalTargetValue: holding?.personalTargetValue ?? null,
    tradeBelowPrice: symbol.tradeBelowPrice ?? symbol.buyBelow ?? null,
    tradeBelowShares: symbol.tradeBelowShares ?? null,
    tradeAbovePrice: symbol.tradeAbovePrice ?? symbol.sellAbove ?? null,
    tradeAboveShares: symbol.tradeAboveShares ?? null,
  };
}

export function buildPortfolioRows(
  symbols: PortfolioSymbol[],
  holdingBySymbol: Map<string, Holding>,
  assessmentBySymbol: Map<string, Assessment>,
): PortfolioRow[] {
  const rows = symbols.map((symbol) =>
    buildRow(symbol, holdingBySymbol.get(symbol.symbol), assessmentBySymbol.get(symbol.symbol)),
  );

  const totalMarketValue = rows.reduce((sum, row) => sum + (row.marketValue || 0), 0);
  if (!totalMarketValue) return rows;

  return rows.map((row) => ({
    ...row,
    weightPct:
      row.marketValue != null
        ? Math.round((row.marketValue / totalMarketValue) * 1000) / 10
        : null,
  }));
}

function sortValue(row: PortfolioRow, key: PortfolioSortKey): string | number | null {
  if (key === "symbol") return row.symbol;
  if (key === "sai") return actionRank(row.saiAction);
  if (key === "tradeBand") {
    const dist = tradeBandClosestDist(row);
    return dist === Infinity ? null : dist;
  }
  return row[key as keyof PortfolioRow] as number | null;
}

function compareRows(a: PortfolioRow, b: PortfolioRow, key: PortfolioSortKey): number {
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

export function sortPortfolioRows(
  rows: PortfolioRow[],
  sort: PortfolioSortState,
): PortfolioRow[] {
  const sorted = [...rows];
  if (!sort.key || !sort.direction) {
    sorted.sort((a, b) => a.symbol.localeCompare(b.symbol));
    return sorted;
  }
  const mult = sort.direction === "asc" ? 1 : -1;
  sorted.sort((a, b) => {
    const cmp = compareRows(a, b, sort.key as PortfolioSortKey);
    return cmp === 0 ? a.symbol.localeCompare(b.symbol) : cmp * mult;
  });
  return sorted;
}

export function sortHeaderLabel(label: string, key: PortfolioSortKey, sort: PortfolioSortState): string {
  if (sort.key !== key || !sort.direction) return label;
  return sort.direction === "asc" ? `${label} ↑` : `${label} ↓`;
}
