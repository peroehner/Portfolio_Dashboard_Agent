import { colors } from "@/lib/theme";
import type { Holding, InspectorPayload, PortfolioSymbol } from "@/lib/types";

export interface PositionDisplay {
  hasPosition: boolean;
  entryDate: string | null;
  shares: number | null;
  investment: number | null;
  currentValue: number | null;
  gain: number | null;
  gainPct: number | null;
  personalTargetValue: number | null;
  personalUpsidePct: number | null;
  estDividend: number | null;
}

export function getPScore(data?: InspectorPayload | null): number | null {
  if (!data) return null;
  const valuation = data.valuation as { pScore?: number } | undefined;
  const screening = data.screening as { score?: number; pScore?: number } | undefined;
  const score = valuation?.pScore ?? screening?.score ?? screening?.pScore;
  return score != null && Number.isFinite(score) ? score : null;
}

export function getRecommendationText(data?: InspectorPayload | null): string {
  const rec = data?.recommendation;
  if (!rec) return "";
  return (rec.rationale || rec.thesis || "").trim();
}

export function getRecommendationDrivers(data?: InspectorPayload | null): string[] {
  const rec = data?.recommendation as { drivers?: string[]; reasons?: string[] } | undefined;
  return rec?.drivers ?? rec?.reasons ?? [];
}

export function getPositionDisplay(
  data?: InspectorPayload | null,
  quote?: PortfolioSymbol,
  holding?: Holding | null,
): PositionDisplay {
  const pm = data?.positionMechanics as Record<string, unknown> | undefined;
  const sharesRaw = pm?.sharesOwned ?? pm?.quantity ?? holding?.quantity;
  const shares = sharesRaw != null ? Number(sharesRaw) : null;
  const hasPosition = (shares ?? 0) > 0;

  const entryDateRaw =
    pm?.entryDate ?? pm?.purchaseDate ?? holding?.purchaseDate ?? null;
  const entryDate = entryDateRaw ? String(entryDateRaw).slice(0, 10) : null;

  const investmentRaw = pm?.entryCapital ?? holding?.totalCost ?? holding?.costBasis;
  const currentValueRaw =
    pm?.currentValue ?? pm?.marketValue ?? holding?.marketValue ?? null;
  const gainRaw = pm?.totalGain ?? pm?.unrealizedGain ?? holding?.unrealizedGain;
  const gainPctRaw = pm?.totalGainPct ?? pm?.gainPct ?? holding?.gainPct;

  const personalTargetPrice =
    holding?.personalTarget ?? quote?.targetPrice ?? (pm?.personalTarget as number | undefined);
  const personalTargetValueRaw =
    holding?.personalTargetValue ??
    (pm?.personalTargetValue as number | undefined) ??
    (personalTargetPrice != null && shares != null
      ? Number(shares) * Number(personalTargetPrice)
      : null);

  const price = holding?.currentPrice ?? quote?.currentPrice;
  const personalUpsidePctRaw =
    holding?.personalUpsidePct ??
    (pm?.personalUpsidePct as number | undefined) ??
    (personalTargetPrice != null && price
      ? ((Number(personalTargetPrice) - Number(price)) / Number(price)) * 100
      : null);

  const valuation = data?.valuation as { estDividend?: number | null } | undefined;
  const estDividend =
    valuation?.estDividend ?? holding?.annualDividend ?? quote?.annualDividend ?? null;

  return {
    hasPosition,
    entryDate,
    shares,
    investment: investmentRaw != null ? Number(investmentRaw) : null,
    currentValue: currentValueRaw != null ? Number(currentValueRaw) : null,
    gain: gainRaw != null ? Number(gainRaw) : null,
    gainPct: gainPctRaw != null ? Number(gainPctRaw) : null,
    personalTargetValue:
      personalTargetValueRaw != null ? Number(personalTargetValueRaw) : null,
    personalUpsidePct:
      personalUpsidePctRaw != null ? Number(personalUpsidePctRaw) : null,
    estDividend: estDividend != null ? Number(estDividend) : null,
  };
}

export function headlineForAction(action?: string | null, sentiment?: string | null): string {
  const labels: Record<string, string> = {
    buy: "Consider adding on confirmed setup",
    sell: "Consider taking profits or reducing",
    watch: "Monitor — catalysts approaching",
    hold: "Maintain current positioning",
  };
  const key = String(action || "hold").toLowerCase();
  const base = labels[key] || "Review positioning";
  const sent = String(sentiment || "neutral").toLowerCase();
  if (sent === "bullish" && (key === "hold" || key === "watch")) {
    return `${base} · bullish growth thesis`;
  }
  if (sent === "bearish") return `${base} · bearish notes flagged`;
  return base;
}

export function sentimentStyle(sentiment?: string | null): {
  color: string;
  backgroundColor: string;
  borderColor: string;
} {
  const sent = String(sentiment || "neutral").toLowerCase();
  if (sent === "bullish") {
    return {
      color: colors.buy,
      backgroundColor: "rgba(34,197,94,0.18)",
      borderColor: "rgba(34,197,94,0.4)",
    };
  }
  if (sent === "bearish") {
    return {
      color: colors.sell,
      backgroundColor: "rgba(248,113,113,0.18)",
      borderColor: "rgba(248,113,113,0.4)",
    };
  }
  return {
    color: colors.textMuted,
    backgroundColor: "rgba(148,163,184,0.16)",
    borderColor: colors.border,
  };
}

export function voteChipStyle(direction?: string | null): {
  color: string;
  borderColor: string;
  backgroundColor: string;
} {
  if (direction === "bull") {
    return {
      color: colors.buy,
      borderColor: "rgba(34,197,94,0.4)",
      backgroundColor: "rgba(34,197,94,0.08)",
    };
  }
  if (direction === "bear") {
    return {
      color: colors.sell,
      borderColor: "rgba(248,113,113,0.4)",
      backgroundColor: "rgba(248,113,113,0.08)",
    };
  }
  return {
    color: colors.textMuted,
    borderColor: colors.border,
    backgroundColor: colors.surfaceAlt,
  };
}

export function confluenceBiasColor(bias?: string | null): string {
  const key = String(bias || "").toLowerCase();
  if (key.includes("bull")) return colors.buy;
  if (key.includes("bear")) return colors.sell;
  return colors.textMuted;
}
