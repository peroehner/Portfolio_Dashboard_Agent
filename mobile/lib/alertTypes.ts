/** Full alert type label shown on each alert row. */
export const ALERT_TYPE_LABELS: Record<string, string> = {
  screener_upside: "Screener Upside",
  fib_proximity: "Fib",
  trade_above: "Trade Above",
  trade_above_near: "Trade Above Near",
  trade_below: "Trade Below",
  trade_below_near: "Trade Below Near",
};

/** Short chip label for the type filter bar. */
export const ALERT_TYPE_CHIP_LABELS: Record<string, string> = {
  screener_upside: "Upside",
  fib_proximity: "Fib",
  trade_above: "Above",
  trade_above_near: "Above Near",
  trade_below: "Below",
  trade_below_near: "Below Near",
};

/** Preferred chip order in filter bars. */
export const ALERT_TYPE_CHIP_ORDER = [
  "trade_above",
  "trade_above_near",
  "trade_below",
  "trade_below_near",
  "fib_proximity",
  "screener_upside",
] as const;

export function alertTypeKey(type?: string | null): string {
  return String(type || "alert").trim().toLowerCase();
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

export function sortAlertTypeChipEntries<T extends { key: string }>(entries: T[]): T[] {
  return [...entries].sort((a, b) => compareAlertTypeChipOrder(a.key, b.key));
}
