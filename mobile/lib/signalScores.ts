/**
 * Shared score helpers for Tax & Trim / Buy·Sell Plan (and web Screening).
 * Mobile Portfolio does not surface these as table columns — keep that list clean.
 * See docs/SIGNAL_SCORES.md.
 */

const LOSS_SCORE_WEIGHT = 50;
const LOSS_SCORE_AT_GATE = 30;
const LOSS_SCORE_ANCHOR_PCT = 50;

const TRIM_HEADROOM_REF_PCT = 60;
const TRIM_WEIGHT_REF_PCT = 10;
const TRIM_PEAK_FLOOR_PCT = 80;
const PLAN_ATTRACT_CEILING = 80;

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

/** Expected residual %-loss vs cost after 1YT. Missing 1YT → U=0. */
export function residualLossPct(
  gainPct: number | null | undefined,
  analystUpsidePct: number | null | undefined,
): number | null {
  if (gainPct == null || !Number.isFinite(gainPct) || gainPct >= 0) return null;
  const lossPct = Math.abs(gainPct);
  if (!(lossPct > 0)) return null;
  const L = Math.min(1, lossPct / 100);
  const U =
    analystUpsidePct != null && Number.isFinite(analystUpsidePct)
      ? analystUpsidePct / 100
      : 0;
  return Math.max(0, 100 * (1 - (1 - L) * (1 + U)));
}

export function lossScoreFromResidual(residualPct: number | null | undefined): number {
  if (residualPct == null || !(residualPct > 0)) return 0;
  if (residualPct <= LOSS_SCORE_ANCHOR_PCT) {
    return (residualPct / LOSS_SCORE_ANCHOR_PCT) * LOSS_SCORE_AT_GATE;
  }
  const t = Math.min(1, (residualPct - LOSS_SCORE_ANCHOR_PCT) / (100 - LOSS_SCORE_ANCHOR_PCT));
  return LOSS_SCORE_AT_GATE + t * (LOSS_SCORE_WEIGHT - LOSS_SCORE_AT_GATE);
}

/** Tax & Trim Loss Score (0–50). Null when not a loser. */
export function lossScore(
  gainPct: number | null | undefined,
  analystUpsidePct: number | null | undefined,
): number | null {
  if (gainPct == null || !Number.isFinite(gainPct) || gainPct >= 0) return null;
  const score = lossScoreFromResidual(residualLossPct(gainPct, analystUpsidePct));
  return score > 0 ? score : 0;
}

function trimHeadroomPct(
  analystUpsidePct: number | null | undefined,
  personalUpsidePct: number | null | undefined,
): number {
  const u1yt =
    analystUpsidePct != null && Number.isFinite(analystUpsidePct)
      ? Math.max(0, analystUpsidePct)
      : 0;
  const uPt =
    personalUpsidePct != null && Number.isFinite(personalUpsidePct)
      ? Math.max(0, personalUpsidePct)
      : u1yt;
  return 0.4 * u1yt + 0.6 * uPt;
}

/**
 * Tax & Trim Trim Score (~0–65). Null when not a held winner (gainPct ≤ 0).
 * peakPct = price as % of 52W high; missing peak uses mid default (10 pts).
 */
export function trimScore(args: {
  gainPct?: number | null;
  analystUpsidePct?: number | null;
  personalUpsidePct?: number | null;
  peakPct?: number | null;
  weightPct?: number | null;
  buyQty?: number | null;
  sellQty?: number | null;
  held?: number | null;
}): number | null {
  const gainPct = args.gainPct;
  if (gainPct == null || !Number.isFinite(gainPct) || gainPct <= 0) return null;
  const held = Math.max(0, Number(args.held) || 0);
  if (!(held > 0)) return null;

  const headroom = trimHeadroomPct(args.analystUpsidePct, args.personalUpsidePct);
  const exhaustPts = 30 * clamp01(1 - headroom / TRIM_HEADROOM_REF_PCT);
  const peakPct = args.peakPct;
  const peakPts =
    peakPct == null || !Number.isFinite(peakPct)
      ? 10
      : 20 * clamp01((peakPct - TRIM_PEAK_FLOOR_PCT) / (100 - TRIM_PEAK_FLOOR_PCT));
  const weightPct = args.weightPct;
  const weightPts =
    weightPct == null || !Number.isFinite(weightPct) || weightPct <= 0
      ? 0
      : 15 * clamp01(weightPct / TRIM_WEIGHT_REF_PCT);

  const buy = Math.max(0, Number(args.buyQty) || 0);
  const sell = Math.max(0, Number(args.sellQty) || 0);
  const net = buy - sell;
  const denom = Math.max(held, buy + sell, 1);
  let intentPts = 0;
  if (net > 0) intentPts = -10 * clamp01(net / denom);
  else if (net < 0) intentPts = 10 * clamp01(Math.abs(net) / denom);
  else if (sell > 0) intentPts = 5;

  return Math.max(0, exhaustPts + peakPts + weightPts + intentPts);
}

export type BuyPlanQualificationMode = "proximity" | "score";

/**
 * Buy Plan SAI Action hard-filter.
 * - Score mode: only Action = BUY
 * - Prox mode: allow WATCH (and BUY / HOLD / unknown)
 * - Always exclude SELL
 */
export function buyPlanActionAllowed(
  action: string | null | undefined,
  mode: BuyPlanQualificationMode,
): boolean {
  const a = String(action || "").trim().toLowerCase();
  if (a === "sell") return false;
  if (mode === "score") return a === "buy";
  return true;
}

/** Plan Sell Rank for a sell leg (lower = stronger). Null when no sell threshold. */
export function planSellRankForRow(args: {
  currentPrice?: number | null;
  tradeAbovePrice?: number | null;
  tradeAboveShares?: number | null;
  tradeBelowPrice?: number | null;
  tradeBelowShares?: number | null;
}): number | null {
  const price = Number(args.currentPrice) || 0;
  if (!(price > 0)) return null;

  const legs: { thr: number; qty: number; buy: boolean }[] = [];
  const pushLeg = (
    thr: number | null | undefined,
    shares: number | null | undefined,
    side: "below" | "above",
  ) => {
    if (thr == null || !Number.isFinite(Number(thr))) return;
    const sh = Number(shares) || 0;
    let buy: boolean;
    if (sh > 0) buy = true;
    else if (sh < 0) buy = false;
    else buy = side === "below";
    legs.push({ thr: Number(thr), qty: Math.abs(sh), buy });
  };
  pushLeg(args.tradeBelowPrice, args.tradeBelowShares, "below");
  pushLeg(args.tradeAbovePrice, args.tradeAboveShares, "above");

  const sellLegs = legs.filter((leg) => !leg.buy);
  if (!sellLegs.length) return null;

  let best: number | null = null;
  for (const leg of sellLegs) {
    const proximitySignedPct = ((price - leg.thr) / price) * 100;
    const proximityAbsPct = Math.abs(proximitySignedPct);
    const proximityScore = Math.max(0, 50 - proximityAbsPct);
    const triggerScore = proximitySignedPct >= 0 ? 15 : 0;
    const cash = leg.thr * leg.qty;
    const sizeScore = Math.min(15, (cash / 50000) * 15);
    const planAttract = proximityScore + triggerScore + sizeScore;
    const rank = Math.max(0, PLAN_ATTRACT_CEILING - planAttract);
    if (best == null || rank < best) best = rank;
  }
  return best;
}

export function tradeBandSideDist(
  row: {
    currentPrice?: number | null;
    tradeBelowPrice?: number | null;
    tradeAbovePrice?: number | null;
  },
  side: "below" | "above",
): number | null {
  const price = row.currentPrice;
  if (price == null || !(price > 0)) return null;
  if (side === "below") {
    if (row.tradeBelowPrice == null) return null;
    return (Math.abs(price - row.tradeBelowPrice) / price) * 100;
  }
  if (row.tradeAbovePrice == null) return null;
  return (Math.abs(row.tradeAbovePrice - price) / price) * 100;
}
