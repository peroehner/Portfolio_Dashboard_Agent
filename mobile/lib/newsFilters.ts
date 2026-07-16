import type { NewsItem, RecommendationChange } from "@/lib/types";

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

function newsPublishedMs(item: NewsItem): number {
  const raw = item.published;
  if (!raw) return 0;
  const d = new Date(raw);
  if (!Number.isNaN(d.getTime())) return d.getTime();
  const m = String(raw).match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (!m) return 0;
  const [, y, mo, dDay, h = "0", mi = "0"] = m;
  return new Date(Number(y), Number(mo) - 1, Number(dDay), Number(h), Number(mi)).getTime();
}

export interface NewsSymbolGroup {
  symbol: string;
  items: NewsItem[];
}

/** Group by symbol; each group newest-first; groups ordered by latest article. */
export function groupNewsBySymbol(items: NewsItem[]): NewsSymbolGroup[] {
  const bySymbol = new Map<string, NewsItem[]>();
  for (const item of items) {
    const symbol = String(item.symbol || "").toUpperCase() || "—";
    const list = bySymbol.get(symbol);
    if (list) list.push(item);
    else bySymbol.set(symbol, [item]);
  }
  const groups: NewsSymbolGroup[] = [];
  for (const [symbol, groupItems] of bySymbol) {
    const sorted = [...groupItems].sort((a, b) => newsPublishedMs(b) - newsPublishedMs(a));
    groups.push({ symbol, items: sorted });
  }
  groups.sort((a, b) => newsPublishedMs(b.items[0]) - newsPublishedMs(a.items[0]));
  return groups;
}

