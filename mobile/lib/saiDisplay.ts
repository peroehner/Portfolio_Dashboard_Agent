/** SAI Attention + Conf · Score helpers (aligned with web dashboard). */

import { colors } from "@/lib/theme";
import type { SaiAction, TradingProposal } from "@/lib/types";

export function saiNormAction(action?: string | null): string {
  const a = String(action || "hold").toLowerCase();
  return a === "hold" ? "watch" : a;
}

export function saiBandActionFromProposal(proposal?: TradingProposal | null): string | null {
  const code = String(proposal?.bandBias?.code || "").toLowerCase();
  if (code === "strong_buy" || code === "buy") return "buy";
  if (code === "watch_hold" || code === "hold_trim") return "watch";
  if (code === "sell_avoid") return "sell";
  const total = Number(proposal?.scores?.total);
  if (!Number.isFinite(total)) return null;
  if (total >= 60) return "buy";
  if (total >= 30) return "watch";
  return "sell";
}

export interface SaiAttention {
  flag: boolean;
  level: "warn" | "info" | null;
  message: string | null;
  bandAction: string | null;
  saiAction: string;
}

/** Pay attention when Action chip (last Assess) ≠ what Live Score maps to. */
export function resolveSaiAttention(
  action?: string | null,
  proposal?: TradingProposal | null,
): SaiAttention {
  const saiAction = String(action || "hold").toLowerCase();
  const bandAction = saiBandActionFromProposal(proposal);
  const stored = proposal?.attention;
  if (!bandAction) {
    if (stored && typeof stored === "object") {
      return {
        flag: Boolean(stored.flag),
        level: (stored.level as "warn" | "info" | null) ?? null,
        message: stored.message ?? null,
        bandAction: stored.bandAction ?? null,
        saiAction: stored.saiAction ?? saiAction,
      };
    }
    return { flag: false, level: null, message: null, bandAction: null, saiAction };
  }
  if (saiNormAction(bandAction) === saiNormAction(saiAction)) {
    return { flag: false, level: null, message: null, bandAction, saiAction };
  }
  const nb = saiNormAction(bandAction);
  const ns = saiNormAction(saiAction);
  const opposite = (nb === "buy" && ns === "sell") || (nb === "sell" && ns === "buy");
  return {
    flag: true,
    level: opposite ? "warn" : "info",
    message: `Pay attention: SAI Action is ${saiAction.toUpperCase()} (last Assess), while Live Score shows a ${bandAction.toUpperCase()}`,
    bandAction,
    saiAction,
  };
}

export function saiConfidenceLabel(
  actionConfidence?: string | null,
  proposal?: TradingProposal | null,
): string | null {
  const confidence = String(proposal?.confidence || actionConfidence || "").toLowerCase();
  if (!confidence) return null;
  const total = Number(proposal?.scores?.total);
  if (Number.isFinite(total)) {
    return `${confidence} · ${Math.round(total)}`;
  }
  return confidence;
}

export function saiIntentCode(proposal?: TradingProposal | null): string | null {
  const code = proposal?.intent?.code;
  return code ? String(code) : null;
}

export function saiIntentLabel(proposal?: TradingProposal | null): string | null {
  const label = proposal?.intent?.label;
  if (label) return String(label);
  const code = saiIntentCode(proposal);
  return code;
}

export function saiFitBandLabel(proposal?: TradingProposal | null): string | null {
  const total = Number(proposal?.scores?.total);
  if (!Number.isFinite(total)) return null;
  // Same cuts as Conf base: ≥75 high · ≥35 medium · else low (raw; no soften).
  if (total >= 75) return "high";
  if (total >= 35) return "medium";
  return "low";
}

export function saiFitBandStyle(band?: string | null): {
  color: string;
  bg: string;
  border: string;
} {
  const key = String(band || "unknown").toLowerCase();
  if (key === "high" || key === "strong") {
    return { color: "#86efac", bg: "rgba(34,197,94,0.2)", border: "rgba(34,197,94,0.45)" };
  }
  if (key === "medium" || key === "mid") {
    return { color: "#fbbf24", bg: "rgba(245,158,11,0.22)", border: "rgba(245,158,11,0.45)" };
  }
  if (key === "low" || key === "weak") {
    return { color: "#fca5a5", bg: "rgba(239,68,68,0.2)", border: "rgba(248,113,113,0.45)" };
  }
  return { color: colors.textMuted, bg: colors.surfaceAlt, border: colors.border };
}

export function formatSaiActionLabel(
  action?: SaiAction | string | null,
  attention?: boolean,
): string {
  const key = String(action || "").toLowerCase();
  const base =
    key === "buy"
      ? "Buy"
      : key === "sell"
        ? "Sell"
        : key === "watch"
          ? "Watch"
          : key === "hold"
            ? "Hold"
            : key
              ? key[0].toUpperCase() + key.slice(1)
              : "";
  if (!base) return "";
  return attention ? `${base} !` : base;
}
