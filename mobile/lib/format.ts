export function formatMoney(value: number | null | undefined, compact = false): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (compact && abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  }
  if (compact && abs >= 10_000) {
    return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  }
  return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatQty(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "—";
  return n % 1 === 0 ? String(n) : n.toFixed(2);
}

export function formatWeight(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(1)}%`;
}

export function pctColor(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "#94a3b8";
  if (value > 0) return "#4ade80";
  if (value < 0) return "#f87171";
  return "#94a3b8";
}

export function titleCaseAction(action?: string | null): string {
  if (!action) return "—";
  return action.charAt(0).toUpperCase() + action.slice(1).toLowerCase();
}

export function formatRelativeDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
