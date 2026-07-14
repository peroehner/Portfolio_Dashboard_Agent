import type { Holding } from "@/lib/types";

export type AllocationMode = "top5" | "top75";

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

  return slices;
}

export function allocationSubtitle(mode: AllocationMode): string {
  return mode === "top75"
    ? "Assets making up the top 75% of value"
    : "Top 5 assets shown individually";
}
