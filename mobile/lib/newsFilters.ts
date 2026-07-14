import type { RecommendationChange } from "@/lib/types";

/** Web SAI_ACTION_RANK — higher rank = more bullish (upgrade = up). */
const SAI_ACTION_RANK: Record<string, number> = {
  buy: 4,
  watch: 3,
  hold: 2,
  sell: 1,
};

export type RecoChangeDirection = "up" | "down" | "flat";
export type RecoChangesDirFilter = "up" | "down" | "";

function saiFieldRank(action?: string | null): number {
  return SAI_ACTION_RANK[String(action || "hold").toLowerCase()] ?? 2;
}

export function recoChangeDirection(change: RecommendationChange): RecoChangeDirection {
  const oldRank = saiFieldRank(change.oldAction);
  const newRank = saiFieldRank(change.newAction);
  if (newRank > oldRank) return "up";
  if (newRank < oldRank) return "down";
  return "flat";
}

export function filterRecoChanges(
  changes: RecommendationChange[],
  dirFilter: RecoChangesDirFilter,
): RecommendationChange[] {
  if (!dirFilter) return changes;
  return changes.filter((change) => recoChangeDirection(change) === dirFilter);
}

export function recoChangesCounts(changes: RecommendationChange[]): {
  total: number;
  up: number;
  down: number;
} {
  let up = 0;
  let down = 0;
  for (const change of changes) {
    const dir = recoChangeDirection(change);
    if (dir === "up") up += 1;
    else if (dir === "down") down += 1;
  }
  return { total: changes.length, up, down };
}

export function changeTimestamp(change: RecommendationChange): string | undefined {
  return change.createdAt ?? change.changedAt;
}
