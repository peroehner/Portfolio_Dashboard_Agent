/** Full alert type label shown on each alert row. */
export const ALERT_TYPE_LABELS: Record<string, string> = {
  one_yt_chance: "1YT Chance",
  one_yt_lean: "1YT Lean",
  one_yt_stretch: "1YT Stretch",
  one_yt_watch: "1YT Watch",
  screener_upside: "1YT", // legacy until Check Alerts re-categorizes
  fib_proximity: "Fib",
  trade_above: "Trade Above",
  trade_above_near: "Trade Above Near",
  trade_below: "Trade Below",
  trade_below_near: "Trade Below Near",
};

/** Short chip label for fine-grained type keys (row badges / legacy). */
export const ALERT_TYPE_CHIP_LABELS: Record<string, string> = {
  one_yt_chance: "Chance",
  one_yt_lean: "Lean",
  one_yt_stretch: "Stretch",
  one_yt_watch: "Watch",
  screener_upside: "1YT",
  fib_proximity: "Fib",
  trade_above: "Above",
  trade_above_near: "Above Near",
  trade_below: "Below",
  trade_below_near: "Below Near",
};

/** Preferred chip order for fine-grained types (list sort). */
export const ALERT_TYPE_CHIP_ORDER = [
  "trade_above",
  "trade_above_near",
  "trade_below",
  "trade_below_near",
  "fib_proximity",
  "one_yt_chance",
  "one_yt_lean",
  "one_yt_watch",
  "one_yt_stretch",
  "screener_upside",
] as const;

/**
 * Mobile Alerts filter bar — fewer grouped chips.
 * Trade Below = below + near; Trade Above = above + near; 1YT = all categories.
 */
export const ALERT_FILTER_GROUPS = [
  {
    key: "trade_below",
    label: "Trade Below",
    types: ["trade_below", "trade_below_near"],
  },
  {
    key: "trade_above",
    label: "Trade Above",
    types: ["trade_above", "trade_above_near"],
  },
  {
    key: "fib",
    label: "Fib",
    types: ["fib_proximity"],
  },
  {
    key: "one_yt",
    label: "1YT↑",
    types: [
      "one_yt_chance",
      "one_yt_lean",
      "one_yt_watch",
      "one_yt_stretch",
      "screener_upside",
    ],
  },
] as const;

export type AlertFilterGroupKey = (typeof ALERT_FILTER_GROUPS)[number]["key"];

const TYPE_TO_FILTER_GROUP: Record<string, AlertFilterGroupKey> = {};
for (const group of ALERT_FILTER_GROUPS) {
  for (const type of group.types) {
    TYPE_TO_FILTER_GROUP[type] = group.key;
  }
}

export function alertTypeKey(type?: string | null): string {
  return String(type || "alert").trim().toLowerCase();
}

export function alertFilterGroupKey(type?: string | null): AlertFilterGroupKey | null {
  return TYPE_TO_FILTER_GROUP[alertTypeKey(type)] ?? null;
}

export function alertFilterGroupLabel(groupKey: string): string {
  const group = ALERT_FILTER_GROUPS.find((g) => g.key === groupKey);
  return group?.label ?? groupKey;
}

export function alertMatchesFilterGroup(type: string | null | undefined, groupKey: string): boolean {
  const group = ALERT_FILTER_GROUPS.find((g) => g.key === groupKey);
  if (!group) return false;
  return (group.types as readonly string[]).includes(alertTypeKey(type));
}

export function alertTypeLabel(key: string): string {
  if (ALERT_TYPE_LABELS[key]) return ALERT_TYPE_LABELS[key];
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function alertTypeChipLabel(key: string): string {
  if (ALERT_TYPE_CHIP_LABELS[key]) return ALERT_TYPE_CHIP_LABELS[key];
  return alertTypeLabel(key);
}

export function compareAlertTypeChipOrder(a: string, b: string): number {
  const ia = ALERT_TYPE_CHIP_ORDER.indexOf(a as (typeof ALERT_TYPE_CHIP_ORDER)[number]);
  const ib = ALERT_TYPE_CHIP_ORDER.indexOf(b as (typeof ALERT_TYPE_CHIP_ORDER)[number]);
  const ra = ia === -1 ? ALERT_TYPE_CHIP_ORDER.length : ia;
  const rb = ib === -1 ? ALERT_TYPE_CHIP_ORDER.length : ib;
  if (ra !== rb) return ra - rb;
  return alertTypeChipLabel(a).localeCompare(alertTypeChipLabel(b));
}

export function compareAlertFilterGroupOrder(a: string, b: string): number {
  const ia = ALERT_FILTER_GROUPS.findIndex((g) => g.key === a);
  const ib = ALERT_FILTER_GROUPS.findIndex((g) => g.key === b);
  const ra = ia === -1 ? ALERT_FILTER_GROUPS.length : ia;
  const rb = ib === -1 ? ALERT_FILTER_GROUPS.length : ib;
  if (ra !== rb) return ra - rb;
  return alertFilterGroupLabel(a).localeCompare(alertFilterGroupLabel(b));
}

export function sortAlertTypeChipEntries<T extends { key: string }>(entries: T[]): T[] {
  return [...entries].sort((a, b) => compareAlertTypeChipOrder(a.key, b.key));
}

export function sortAlertFilterGroupEntries<T extends { key: string }>(entries: T[]): T[] {
  return [...entries].sort((a, b) => compareAlertFilterGroupOrder(a.key, b.key));
}
