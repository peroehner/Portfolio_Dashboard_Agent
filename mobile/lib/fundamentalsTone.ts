import { colors } from "@/lib/theme";

/** Good / neutral / caution — mirrors web Fundamentals Help thresholds. */
export type FundTone = "pos" | "neg" | "mid" | null;

export function fundToneColor(tone: FundTone): string | undefined {
  if (tone === "pos") return colors.buy;
  if (tone === "neg") return colors.sell;
  if (tone === "mid") return colors.warning;
  return undefined;
}

/** PEG: &lt;1 good · 1–2 neutral · &gt;2 caution */
export function fundTonePeg(value: number | null | undefined): FundTone {
  if (value == null || !Number.isFinite(value)) return null;
  if (value < 1) return "pos";
  if (value <= 2) return "mid";
  return "neg";
}

/** Current ratio: ≥1.5 good · 1.0–1.5 neutral · &lt;1.0 caution */
export function fundToneCurrent(value: number | null | undefined): FundTone {
  if (value == null || !Number.isFinite(value)) return null;
  if (value >= 1.5) return "pos";
  if (value >= 1.0) return "mid";
  return "neg";
}

/** Quick ratio: ≥1.0 good · 0.7–1.0 neutral · &lt;0.7 caution */
export function fundToneQuick(value: number | null | undefined): FundTone {
  if (value == null || !Number.isFinite(value)) return null;
  if (value >= 1.0) return "pos";
  if (value >= 0.7) return "mid";
  return "neg";
}

/** Debt/E on yfinance-style % scale: &lt;100 good · 100–200 neutral · &gt;200 caution */
export function fundToneDebtEquity(value: number | null | undefined): FundTone {
  if (value == null || !Number.isFinite(value)) return null;
  if (value < 100) return "pos";
  if (value <= 200) return "mid";
  return "neg";
}

/** Beta extremes = volatility extremes, not “bad company.” */
export function fundToneBeta(value: number | null | undefined): FundTone {
  if (value == null || !Number.isFinite(value)) return null;
  if (value >= 0.7 && value <= 1.2) return "pos";
  if ((value >= 0.5 && value < 0.7) || (value > 1.2 && value <= 1.5)) return "mid";
  return "neg";
}

/** Margins / ROE: &gt;0 good · &lt;0 caution · ~0 muted */
export function fundToneSignedRatio(value: number | null | undefined): FundTone {
  if (value == null || !Number.isFinite(value)) return null;
  if (Math.abs(value) < 1e-9) return null;
  return value > 0 ? "pos" : "neg";
}
