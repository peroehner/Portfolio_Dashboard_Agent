/** Canonical signal names + formula/meaning (Buy/Sell Plan, Tax & Trim, SAI). */

export type SignalKey =
  | "saiScore"
  | "saiConf"
  | "fitBand"
  | "proximity"
  | "planAttract"
  | "planSellRank"
  | "lossScore"
  | "trimScore";

export type SignalDef = {
  key: SignalKey;
  label: string;
  shortLabel: string;
  formula: string;
  meaning: string;
};

export const SIGNAL_GLOSSARY: Record<SignalKey, SignalDef> = {
  saiScore: {
    key: "saiScore",
    label: "SAI Score",
    shortLabel: "SAI",
    formula: "State + Trigger + Fit → 0–100",
    meaning: "Published agent setup quality. High = stronger buy lean.",
  },
  saiConf: {
    key: "saiConf",
    label: "SAI Conf",
    shortLabel: "Conf",
    formula: "High ≥75 · Medium ≥35 · else Low (may soften for gates/vetoes)",
    meaning: "Published conviction label from SAI Score.",
  },
  fitBand: {
    key: "fitBand",
    label: "Fit Band",
    shortLabel: "Fit",
    formula: "High ≥75 · Medium ≥35 · else Low (raw SAI Score; no soften)",
    meaning: "Same cuts/names as SAI Conf base — compare to Conf to see softening impact.",
  },
  proximity: {
    key: "proximity",
    label: "Proximity",
    shortLabel: "Prox",
    formula: "|price − threshold| / price × 100%",
    meaning: "Distance to this planned-trade threshold. Lower = closer to fire.",
  },
  planAttract: {
    key: "planAttract",
    label: "Plan Attract",
    shortLabel: "Attract",
    formula: "P(proximity) + T(triggered) + S(size) ≈ 0–80",
    meaning:
      "Planned-leg readiness (not SAI Score). Shown as P/T/S under Sell Rank. Sell Rank = 80 − Attract.",
  },
  planSellRank: {
    key: "planSellRank",
    label: "Plan Sell Rank",
    shortLabel: "Sell Rank",
    formula: "80 − Plan Attract (P+T+S)",
    meaning:
      "Sell-side planned-trade rank for Trade Above legs. Lower = closer/triggered/larger → stronger sell-to-fire. Not Trim Score.",
  },
  lossScore: {
    key: "lossScore",
    label: "Loss Score",
    shortLabel: "Loss",
    formula: "Residual loss vs cost after 1YT (0–50 curve)",
    meaning: "Tax-loss harvest rank among losers.",
  },
  trimScore: {
    key: "trimScore",
    label: "Trim Score",
    shortLabel: "Trim",
    formula: "Exhaustion + 52W peak + weight + Intent",
    meaning: "Winner-harvest rank (Tax & Trim), not planned Sell Rank.",
  },
};

export function signalTooltip(key: SignalKey): string {
  const def = SIGNAL_GLOSSARY[key];
  return `${def.label}\n${def.formula}\n${def.meaning}`;
}

export function signalHint(key: SignalKey): string {
  const def = SIGNAL_GLOSSARY[key];
  return `${def.formula}. ${def.meaning}`;
}
