/** Absolute share quantity for a threshold input (blank when unset). */
export function toShareInput(shares: number | null | undefined): string {
  if (shares == null || Number.isNaN(shares) || shares === 0) return "";
  return String(Math.abs(shares));
}

/** Parse a positive share quantity; blank/invalid → null. */
export function parseShareQuantity(text: string): number | null {
  const raw = text.trim().replace(/[,\s]/g, "");
  if (!raw) return null;
  const amount = Number(raw);
  if (!Number.isFinite(amount)) return null;
  const magnitude = Math.abs(amount);
  if (!magnitude) return null;
  return Math.round(magnitude * 10000) / 10000;
}

/** Combine magnitude input with buy/sell direction into signed share qty. */
export function signedShareQuantity(
  text: string,
  direction: "buy" | "sell",
): number | null {
  const magnitude = parseShareQuantity(text);
  if (magnitude == null) return null;
  return direction === "sell" ? -magnitude : magnitude;
}

/** Compact label for summary rows, e.g. "10 sh". */
export function formatShareAmount(shares: number | null | undefined): string | null {
  if (shares == null || Number.isNaN(shares) || shares === 0) return null;
  const n = Math.abs(Number(shares));
  const text = n % 1 === 0 ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
  return `${text} sh`;
}
