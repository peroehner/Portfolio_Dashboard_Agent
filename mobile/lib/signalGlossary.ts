/** Canonical signal names + formula/meaning (Buy/Sell Plan, Tax & Trim, SAI). */

export type SignalKey =
  | "saiScore"
  | "saiConf"
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
    meaning:
      "Rule of thumb: HIGHER = stronger buy-to-fire. Score mode shows SAI Score minus a hidden conviction penalty (High 0 · Med 6 · Low 12 · Attention ! +5).",
  },
  saiConf: {
    key: "saiConf",
    label: "SAI Conf",
    shortLabel: "Conf",
    formula: "High ≥75 · Medium ≥35 · else Low (may soften for gates/vetoes)",
    meaning: "Published conviction. Score does not drop when Conf softens.",
  },
  proximity: {
    key: "proximity",
    label: "Proximity",
    shortLabel: "Prox",
    formula: "|price − threshold| / price × 100%",
    meaning: "Rule of thumb: LOWER % = closer to firing this planned-trade threshold.",
  },
  planAttract: {
    key: "planAttract",
    label: "Plan Attract",
    shortLabel: "Attract",
    formula: "P(proximity) + T(triggered) + S(size) ≈ 0–80",
    meaning: "Leg readiness (not SAI Score). Sell Rank = 80 − Attract, then Score mode adds a conviction penalty.",
  },
  planSellRank: {
    key: "planSellRank",
    label: "Plan Sell Rank",
    shortLabel: "Sell Rank",
    formula: "80 − Plan Attract (P+T+S)",
    meaning:
      "Rule of thumb: LOWER = stronger sell-to-fire. Score mode shows this rank plus a hidden conviction penalty. Not Trim Score.",
  },
  lossScore: {
    key: "lossScore",
    label: "Loss Score",
    shortLabel: "Loss",
    formula: "Residual loss vs cost after 1YT (0–50 curve)",
    meaning: "Rule of thumb: HIGHER = more attractive tax-loss sell. Harvest rank — not planned-trade Sell Rank.",
  },
  trimScore: {
    key: "trimScore",
    label: "Trim Score",
    shortLabel: "Trim",
    formula: "Exhaustion + 52W peak + weight + Intent",
    meaning: "Rule of thumb: HIGHER = better winner to harvest now. Harvest rank — not planned-trade Sell Rank.",
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
