import type { Holding, PastProgress } from "@/lib/types";

export type AllocationMode = "top5" | "top75";

export type AllocationSource =
  | "current"
  | "analyst"
  | "personal"
  | "simulation"
  | "1M"
  | "3M"
  | "ath";

export type ProgressDirection = "back" | "forward";

export interface AllocationSlice {
  label: string;
  value: number;
  color: string;
}

export const ALLOCATION_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#60a5fa",
  "#f97316",
  "#a78bfa",
  "#64748b",
];

const MAX_ROWS = 15;

function currentHoldingsTotal(holdings: Holding[] | undefined): number {
  return (holdings ?? []).reduce((sum, holding) => sum + (Number(holding.marketValue) || 0), 0);
}

function normalizeRows(
  rows: Array<{ symbol?: string; marketValue?: number | null; value?: number | null }> | null | undefined,
): Holding[] {
  return (rows ?? [])
    .map((row) => {
      const symbol = row?.symbol;
      const marketValue = Number(row?.marketValue ?? row?.value);
      if (!symbol || !Number.isFinite(marketValue) || marketValue <= 0) return null;
      return { symbol, marketValue } as Holding;
    })
    .filter(Boolean) as Holding[];
}

function scaledHoldingsRows(holdings: Holding[] | undefined, targetTotal: number | null | undefined): Holding[] {
  const currentTotal = currentHoldingsTotal(holdings);
  if (!targetTotal || !currentTotal) return [];
  const scale = Number(targetTotal) / currentTotal;
  return (holdings ?? [])
    .filter((holding) => Number(holding.marketValue) > 0)
    .map((holding) => ({
      symbol: holding.symbol,
      marketValue: Number(holding.marketValue) * scale,
    }));
}

function pastAllocationRows(
  holdings: Holding[] | undefined,
  past: PastProgress | null | undefined,
  source: "1M" | "3M",
): Holding[] {
  const window = past?.windows?.[source];
  let rows = normalizeRows(window?.holdings);
  if (!rows.length && window?.valueThen) {
    rows = scaledHoldingsRows(holdings, window.valueThen);
  }
  return rows;
}

function athAllocationRows(holdings: Holding[] | undefined, past: PastProgress | null | undefined): Holding[] {
  const ath = past?.ath;
  let rows = normalizeRows(ath?.holdings);
  if (!rows.length && ath?.value) {
    rows = scaledHoldingsRows(holdings, ath.value);
  }
  return rows;
}

export function allocationSourceLabel(source: AllocationSource): string {
  switch (source) {
    case "analyst":
      return "1Y mean targets";
    case "personal":
      return "Personal targets";
    case "simulation":
      return "Planned trades (current weights)";
    case "1M":
      return "1M ago holdings";
    case "3M":
      return "3M ago holdings";
    case "ath":
      return "Portfolio ATH";
    case "current":
    default:
      return "Current holdings";
  }
}

export function sourceBelongsToDirection(
  source: AllocationSource,
  direction: ProgressDirection,
): boolean {
  if (direction === "back") return source === "1M" || source === "3M" || source === "ath";
  return source === "current" || source === "analyst" || source === "personal" || source === "simulation";
}

export function holdingsForAllocationSource(
  holdings: Holding[] | undefined,
  past: PastProgress | null | undefined,
  source: AllocationSource,
): Holding[] {
  if (source === "current" || source === "simulation") {
    return normalizeRows(
      (holdings ?? []).map((holding) => ({
        symbol: holding.symbol,
        marketValue: holding.marketValue,
      })),
    );
  }
  if (source === "analyst") {
    return normalizeRows(
      (holdings ?? []).map((holding) => ({
        symbol: holding.symbol,
        marketValue: holding.analystTargetValue,
      })),
    );
  }
  if (source === "personal") {
    return normalizeRows(
      (holdings ?? []).map((holding) => ({
        symbol: holding.symbol,
        marketValue: holding.personalTargetValue,
      })),
    );
  }
  if (source === "1M" || source === "3M") {
    return pastAllocationRows(holdings, past, source);
  }
  if (source === "ath") {
    return athAllocationRows(holdings, past);
  }
  return [];
}

export function buildAllocationSlices(
  holdings: Holding[] | undefined,
  mode: AllocationMode = "top5",
): AllocationSlice[] | null {
  const valued = (holdings ?? []).filter(
    (holding) => holding.marketValue != null && holding.marketValue > 0,
  );
  if (!valued.length) return null;

  const sorted = [...valued].sort(
    (left, right) => (right.marketValue ?? 0) - (left.marketValue ?? 0),
  );

  let individual: Holding[];
  if (mode === "top75") {
    const grandTotal = sorted.reduce((sum, holding) => sum + (holding.marketValue ?? 0), 0);
    const target = grandTotal * 0.75;
    individual = [];
    let cumulative = 0;
    for (const holding of sorted) {
      individual.push(holding);
      cumulative += holding.marketValue ?? 0;
      if (cumulative >= target) break;
    }
  } else {
    individual = sorted.slice(0, 5);
  }

  const others = sorted.slice(individual.length);
  const slices: AllocationSlice[] = individual.map((holding, index) => ({
    label: holding.symbol,
    value: holding.marketValue ?? 0,
    color: ALLOCATION_COLORS[index % (ALLOCATION_COLORS.length - 1)],
  }));

  const othersValue = others.reduce((sum, holding) => sum + (holding.marketValue ?? 0), 0);
  if (othersValue > 0) {
    slices.push({
      label: `Others (${others.length})`,
      value: othersValue,
      color: ALLOCATION_COLORS[ALLOCATION_COLORS.length - 1],
    });
  }

  if (slices.length > MAX_ROWS) {
    const keep = MAX_ROWS - 1;
    const head = slices.slice(0, keep);
    const tail = slices.slice(keep);
    const tailValue = tail.reduce((sum, slice) => sum + slice.value, 0);
    return [
      ...head,
      {
        label: `Others (${tail.length})`,
        value: tailValue,
        color: ALLOCATION_COLORS[ALLOCATION_COLORS.length - 1],
      },
    ];
  }

  return slices;
}

export function allocationSubtitle(mode: AllocationMode): string {
  return mode === "top75"
    ? "Assets making up the top 75% of value"
    : "Top 5 assets shown individually";
}
