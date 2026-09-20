import { colors } from "@/lib/theme";

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

/** Annual dividend as % of market value (position / portfolio yield). */
export function dividendYieldPct(
  annualDividend: number | null | undefined,
  marketValue: number | null | undefined,
): number | null {
  const div = Number(annualDividend);
  const value = Number(marketValue);
  if (!Number.isFinite(div) || !Number.isFinite(value) || value <= 0 || div <= 0) {
    return null;
  }
  return (div / value) * 100;
}

/** "$15,840 (1.01%)" — Hold table / Est. Div surfaces. */
export function formatDividendWithYield(
  annualDividend: number | null | undefined,
  marketValue: number | null | undefined,
  compact = false,
): string {
  const money = formatMoney(annualDividend, compact);
  if (money === "—") return "—";
  const yld = dividendYieldPct(annualDividend, marketValue);
  if (yld == null) return money;
  return `${money} (${yld.toFixed(2)}%)`;
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

/** Pers Target horizon end date → `Q2-2027`, `2030`, or ISO. */
export function formatHorizonLabel(
  value?: string | null,
  label?: string | null,
): string | null {
  if (label && String(label).trim()) return String(label).trim();
  const iso = value ? String(value).slice(0, 10) : "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const [y, mo, d] = iso.split("-").map(Number);
  const md = `${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const qEnds: Record<string, number> = {
    "03-31": 1,
    "06-30": 2,
    "09-30": 3,
    "12-31": 4,
  };
  if (md === "12-31") return String(y);
  if (qEnds[md]) return `Q${qEnds[md]}-${y}`;
  return iso;
}

/** Years remaining until horizon end (1 decimal); null if unset/invalid. */
export function yearsRemainingHorizon(value?: string | null): number | null {
  const iso = value ? String(value).slice(0, 10) : "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const end = new Date(`${iso}T00:00:00Z`);
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const days = (end.getTime() - today) / 86400000;
  if (!(days > 0)) return 0;
  return Math.round((days / 365.25) * 10) / 10;
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
  if (value == null || Number.isNaN(value)) return colors.textMuted;
  if (value > 0) return colors.buy;
  if (value < 0) return colors.sell;
  return colors.textMuted;
}

export function titleCaseAction(action?: string | null): string {
  if (!action) return "—";
  return action.charAt(0).toUpperCase() + action.slice(1).toLowerCase();
}

export function formatLargeMoney(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}k`;
  return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function formatRatio(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Number(value).toFixed(digits);
}

/** yfinance-style fraction (0.166) → 16.6% */
export function formatRatioPercent(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  const amount = Number(value) * 100;
  if (!Number.isFinite(amount)) return "—";
  return `${amount.toFixed(digits)}%`;
}

export function formatColoredRatioPercent(value: number | null | undefined, digits = 1): {
  text: string;
  color: string;
} {
  if (value == null || Number.isNaN(value)) {
    return { text: "—", color: colors.textMuted };
  }
  const amount = Number(value) * 100;
  if (!Number.isFinite(amount)) {
    return { text: "—", color: colors.textMuted };
  }
  const sign = amount > 0 ? "+" : "";
  return {
    text: `${sign}${amount.toFixed(digits)}%`,
    color: amount >= 0 ? colors.buy : colors.sell,
  };
}

function isDateOnlyIso(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value.trim());
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** e.g. Aug-04 — short calendar dates without year. */
export function formatRelativeDate(value?: string | null): string {
  if (!value) return "";
  const date = parseDateInput(value);
  if (!date) return value;
  const month = date.toLocaleDateString("en-US", { month: "short" });
  return `${month}-${pad2(date.getDate())}`;
}

/**
 * Holdings purchase / note dates — include year (lifetime can exceed 12 months).
 * e.g. Aug-04 2024
 */
export function formatEntryDate(value?: string | null): string {
  if (!value) return "";
  const date = parseDateInput(value);
  if (!date) return value;
  const month = date.toLocaleDateString("en-US", { month: "short" });
  return `${month}-${pad2(date.getDate())} ${date.getFullYear()}`;
}

/** Alias for note dates (same year-aware rule as purchase/entry). */
export function formatNoteDate(value?: string | null): string {
  return formatEntryDate(value);
}

/**
 * e.g. Aug-04 11:37 — for event timestamps.
 * Date-only values (YYYY-MM-DD, e.g. quote session) never invent a clock time.
 */
export function formatShortDateTime(value?: string | null): string {
  if (!value) return "";
  const raw = String(value).trim();
  if (isDateOnlyIso(raw)) return formatRelativeDate(raw);
  const date = parseDateInput(raw);
  if (!date) return value;
  const datePart = formatRelativeDate(raw);
  return `${datePart} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function parseDateInput(value: string): Date | null {
  const raw = String(value || "").trim();
  if (!raw) return null;

  // Date-only ISO must be local calendar date — `new Date("YYYY-MM-DD")` is UTC
  // midnight and shows a misleading local clock (e.g. 02:00 in CEST).
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (dateOnly) {
    const [, y, mo, d] = dateOnly;
    const parsed = new Date(Number(y), Number(mo) - 1, Number(d));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  const date = new Date(raw);
  if (!Number.isNaN(date.getTime())) return date;

  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (!m) return null;
  const [, y, mo, d, h = "0", mi = "0"] = m;
  const parsed = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
