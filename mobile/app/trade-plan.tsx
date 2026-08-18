import Slider from "@react-native-community/slider";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  type ReactNode,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { GlossaryHint } from "@/components/GlossaryHint";
import { api, ApiError } from "@/lib/api";
import { parseSymbolFilter } from "@/lib/filters";
import { formatMoney, formatPrice } from "@/lib/format";
import { openSymbol } from "@/lib/symbolBrowseSession";
import { buildPortfolioRows } from "@/lib/portfolioTable";
import { signalTooltip } from "@/lib/signalGlossary";
import { colors, radii, spacing } from "@/lib/theme";
import type { Holding, PortfolioRow, TaxTrimPricingMode } from "@/lib/types";
import { usePersistedSymbolFilter } from "@/lib/usePersistedSymbolFilter";
import { useSymbolFilterMatch } from "@/lib/useSymbolFilterMatch";

type PortfolioMode = "all" | "holdings" | "watch";
type ListMode = "sell" | "buy";
type Side = "buy" | "sell";
/** Proximity = distance to threshold. Score = SAI Score (buy) / Plan Sell Rank (sell). Also drives list sort. */
type QualificationMode = "proximity" | "score";

const PLAN_ATTRACT_CEILING = 80;
const SAI_SCORE_MAX = 100;

type PlanCandidate = {
  symbol: string;
  side: Side;
  thresholdPrice: number;
  currentPrice: number;
  execPrice: number;
  execSource: "current" | "threshold";
  qty: number;
  held: number;
  cash: number;
  pnl: number | null;
  proximitySignedPct: number;
  proximityAbsPct: number;
  /** Plan Attract pieces (sell-side rank only). */
  proximityScore: number;
  triggerScore: number;
  sizeScore: number;
  planAttract: number;
  /** Plan Sell Rank = 80 − attract (sell). Unused for buy ranking. */
  planSellRank: number;
  /** SAI Score = State+Trigger+Fit (buy Score mode). */
  saiScore: number | null;
  /** Published confidence (may be softened by Pass 2). */
  saiConfidence: string | null;
  /** Attention mismatch between stored Action and live Score band. */
  attentionFlag: boolean;
  /** Conviction model (0-100): score+confidence(+attention penalty). */
  convictionScore: number;
  /** Readiness model (0-100): normalized leg Attract. */
  readinessScore: number;
  /** Side-aware blend (0-100): Conviction + Readiness. */
  executionScore: number;
};

type ProposedCandidate = PlanCandidate & {
  proposedQty: number;
  proposedCash: number;
  proposedPnl: number | null;
};

function pillStyle(active: boolean) {
  return active
    ? { backgroundColor: colors.surfaceAlt, borderColor: colors.accent }
    : { backgroundColor: colors.surface, borderColor: colors.border };
}

function formatQty(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

function proximityDetailText(row: PlanCandidate): string {
  const pct = `${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%`;
  const absDist = Math.abs(row.thresholdPrice - row.currentPrice);
  // Match Trade Band / Close %: ▼ when price is above threshold, ▲ when below.
  const arrow = row.currentPrice > row.thresholdPrice ? "▼" : "▲";
  return `${pct} (@ ${formatPrice(row.thresholdPrice)}, ${arrow} ${formatMoney(absDist, false)})`;
}

function evalTradeLeg(price: number | null | undefined, shares: number | null | undefined, side: "below" | "above") {
  if (!Number.isFinite(Number(price))) return null;
  const n = Number(shares) || 0;
  let buy: boolean;
  if (n > 0) buy = true;
  else if (n < 0) buy = false;
  else buy = side === "below";
  const qty = Math.abs(n);
  if (!(qty > 0)) return null;
  return { price: Number(price), qty, buy };
}

function clamp01to100(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function confidenceBaseScore(confidence: string | null | undefined): number {
  const conf = String(confidence || "").toLowerCase();
  if (conf.startsWith("high")) return 85;
  if (conf.startsWith("med")) return 60;
  if (conf.startsWith("low")) return 35;
  return 55;
}

function computeConvictionScore(
  saiScore: number | null,
  saiConfidence: string | null,
  attentionFlag: boolean,
): number {
  const scorePart = saiScore == null ? 30 : saiScore;
  const confPart = confidenceBaseScore(saiConfidence);
  const attentionPenalty = attentionFlag ? 8 : 0;
  return Math.round(clamp01to100(scorePart * 0.6 + confPart * 0.4 - attentionPenalty));
}

function computeReadinessScore(planAttract: number): number {
  return Math.round(clamp01to100((planAttract / PLAN_ATTRACT_CEILING) * 100));
}

function computeExecutionScore(side: Side, convictionScore: number, readinessScore: number): number {
  const blended =
    side === "buy"
      ? convictionScore * 0.55 + readinessScore * 0.45
      : convictionScore * 0.45 + readinessScore * 0.55;
  return Math.round(clamp01to100(blended));
}

function candidateFromRow(
  row: PortfolioRow,
  holdingBySymbol: Map<string, Holding>,
  pricingMode: TaxTrimPricingMode,
): PlanCandidate[] {
  const currentPrice = Number(row.currentPrice) || 0;
  if (!(currentPrice > 0)) return [];
  const held = Number(holdingBySymbol.get(row.symbol)?.quantity) || 0;
  const costBasis = Number(holdingBySymbol.get(row.symbol)?.costBasis);
  const saiTotal = Number(row.saiProposal?.scores?.total);
  const saiScore = Number.isFinite(saiTotal) ? Math.max(0, Math.min(SAI_SCORE_MAX, saiTotal)) : null;
  const saiConfidence = row.saiConfidence == null ? null : String(row.saiConfidence);
  const attentionFlag = Boolean(row.saiProposal?.attention?.flag);
  const below = evalTradeLeg(row.tradeBelowPrice ?? null, row.tradeBelowShares ?? null, "below");
  const above = evalTradeLeg(row.tradeAbovePrice ?? null, row.tradeAboveShares ?? null, "above");
  const legs = [below, above].filter((x) => !!x) as Array<{ price: number; qty: number; buy: boolean }>;
  return legs.map((leg) => {
    const execPrice = pricingMode === "current" ? currentPrice : leg.price;
    const side: Side = leg.buy ? "buy" : "sell";
    const cash = execPrice * leg.qty;
    const pnl = side === "sell" && Number.isFinite(costBasis) ? (execPrice - costBasis) * leg.qty : null;
    const proximitySignedPct = ((currentPrice - leg.price) / currentPrice) * 100;
    const proximityAbsPct = Math.abs(proximitySignedPct);
    // Plan Attract: planned-leg readiness (used for Sell Rank only).
    const proximityScore = Math.max(0, 50 - proximityAbsPct);
    const triggerScore =
      side === "sell" ? (proximitySignedPct >= 0 ? 15 : 0) : (proximitySignedPct <= 0 ? 15 : 0);
    const sizeScore = Math.min(15, (cash / 50_000) * 15);
    const planAttract = proximityScore + triggerScore + sizeScore;
    const planSellRank = Math.max(0, PLAN_ATTRACT_CEILING - planAttract);
    const convictionScore = computeConvictionScore(saiScore, saiConfidence, attentionFlag);
    const readinessScore = computeReadinessScore(planAttract);
    const executionScore = computeExecutionScore(side, convictionScore, readinessScore);
    return {
      symbol: row.symbol,
      side,
      thresholdPrice: leg.price,
      currentPrice,
      execPrice,
      execSource: pricingMode === "current" ? "current" : "threshold",
      qty: leg.qty,
      held,
      cash,
      pnl,
      proximitySignedPct,
      proximityAbsPct,
      proximityScore,
      triggerScore,
      sizeScore,
      planAttract,
      planSellRank,
      saiScore,
      saiConfidence,
      attentionFlag,
      convictionScore,
      readinessScore,
      executionScore,
    };
  });
}

/** Value used for Score-mode gate/sort: Buy → SAI Score, Sell → Plan Sell Rank. */
function scoreModeValue(candidate: PlanCandidate): number {
  if (candidate.side === "buy") {
    if (candidate.saiScore == null) return -1;
    return Math.max(0, candidate.saiScore - scoreThresholdPenalty(candidate));
  }
  return candidate.planSellRank + scoreThresholdPenalty(candidate);
}

/** Hidden strictness penalty in Score mode (Option A): lower conviction raises the bar. */
function scoreThresholdPenalty(candidate: PlanCandidate): number {
  const conf = String(candidate.saiConfidence || "").toLowerCase();
  let penalty = 6; // default medium-like strictness for unknown confidence
  if (conf.startsWith("high")) penalty = 0;
  else if (conf.startsWith("med")) penalty = 6;
  else if (conf.startsWith("low")) penalty = 12;
  if (candidate.attentionFlag) penalty += 5;
  return penalty;
}

function passesQualificationGate(
  candidate: PlanCandidate,
  threshold: number,
  mode: QualificationMode,
): boolean {
  if (mode === "proximity") {
    return candidate.proximityAbsPct <= threshold;
  }
  const value = scoreModeValue(candidate);
  if (candidate.side === "buy") {
    return value >= 0 && value >= threshold;
  }
  return value <= threshold;
}

function scoreGateReason(candidate: PlanCandidate, threshold: number): string | null {
  const value = scoreModeValue(candidate);
  const penalty = scoreThresholdPenalty(candidate);
  if (candidate.side === "buy") {
    if (value < 0) return "No SAI Score yet";
    if (value >= threshold) return null;
    return `Needs Buy Score ${Math.round(threshold)} (effective ${Math.round(value)}, penalty ${penalty})`;
  }
  if (value <= threshold) return null;
  return `Needs Sell Rank ${Math.round(threshold)} (effective ${Math.round(value)}, penalty ${penalty})`;
}

function maxLegQty(candidate: PlanCandidate): number {
  if (!(candidate.qty > 0)) return 0;
  if (candidate.side === "sell" && candidate.held > 0) {
    return Math.max(0, Math.floor(Math.min(candidate.qty, candidate.held)));
  }
  return Math.max(0, Math.floor(candidate.qty));
}

/** Readiness weight for soft budget split (deeper in gate → higher weight; min 15%). */
function readinessWeight(
  candidate: PlanCandidate,
  threshold: number,
  mode: QualificationMode,
  gateMax: number,
): number {
  if (mode === "proximity") {
    const margin = Math.max(0, threshold - candidate.proximityAbsPct);
    return Math.max(0.15, Math.min(1, margin / Math.max(gateMax, 1)));
  }
  if (candidate.side === "buy") {
    const value = scoreModeValue(candidate);
    const margin = Math.max(0, value - threshold);
    return Math.max(0.15, Math.min(1, margin / Math.max(gateMax - threshold, 1)));
  }
  // Sell Rank: lower is stronger.
  const margin = Math.max(0, threshold - scoreModeValue(candidate));
  return Math.max(0.15, Math.min(1, margin / Math.max(threshold, 1)));
}

function candidateKey(candidate: PlanCandidate): string {
  return `${candidate.symbol}:${candidate.side}:${candidate.thresholdPrice}`;
}

/**
 * Gate → max leg qty. If budget ≤ 0: full planned (held-capped on sells).
 * If budget > 0: soft-split cash like Tax & Trim (weight by readiness, then remainder).
 */
function proposeCandidates(
  candidates: PlanCandidate[],
  threshold: number,
  mode: QualificationMode,
  gateMax: number,
  budgetCash: number,
): ProposedCandidate[] {
  const prepared = candidates.map((c) => {
    const passes = passesQualificationGate(c, threshold, mode);
    const maxQty = passes ? maxLegQty(c) : 0;
    const weight = maxQty > 0 ? readinessWeight(c, threshold, mode, gateMax) : 0;
    return { c, maxQty, weight };
  });

  const qtyByKey = new Map<string, number>();
  const useBudget = budgetCash > 0;
  const pool = prepared.filter((x) => x.maxQty > 0 && x.weight > 0);

  if (!useBudget) {
    prepared.forEach(({ c, maxQty }) => qtyByKey.set(candidateKey(c), maxQty));
  } else if (pool.length) {
    const sumW = pool.reduce((sum, x) => sum + x.weight, 0) || 1;
    pool.forEach((item) => {
      const wantCash = (budgetCash * item.weight) / sumW;
      let shares = Math.floor(wantCash / Math.max(item.c.execPrice, 1e-9));
      if (shares <= 0 && wantCash >= item.c.execPrice * 0.5) shares = 1;
      shares = Math.max(0, Math.min(item.maxQty, shares));
      qtyByKey.set(candidateKey(item.c), shares);
    });

    const totalCash = () =>
      pool.reduce((sum, item) => {
        const sh = qtyByKey.get(candidateKey(item.c)) || 0;
        return sum + sh * item.c.execPrice;
      }, 0);

    let spent = totalCash();
    if (spent > budgetCash + 1e-6) {
      const scale = budgetCash / spent;
      pool.forEach((item) => {
        const sh = qtyByKey.get(candidateKey(item.c)) || 0;
        qtyByKey.set(candidateKey(item.c), Math.max(0, Math.floor(sh * scale)));
      });
      spent = totalCash();
    }

    let remaining = Math.max(0, budgetCash - spent);
    const byWeight = [...pool].sort(
      (a, b) =>
        b.weight - a.weight ||
        (a.c.side === "buy"
          ? scoreModeValue(b.c) - scoreModeValue(a.c)
          : scoreModeValue(a.c) - scoreModeValue(b.c)) ||
        a.c.proximityAbsPct - b.c.proximityAbsPct,
    );
    for (const item of byWeight) {
      if (!(remaining > 0)) break;
      const used = qtyByKey.get(candidateKey(item.c)) || 0;
      const room = item.maxQty - used;
      if (room <= 0 || !(item.c.execPrice > 0)) continue;
      let add = Math.floor(remaining / item.c.execPrice);
      add = Math.max(0, Math.min(room, add));
      if (add <= 0) continue;
      qtyByKey.set(candidateKey(item.c), used + add);
      remaining = Math.max(0, remaining - add * item.c.execPrice);
    }
  }

  return prepared.map(({ c }) => {
    const proposedQty = qtyByKey.get(candidateKey(c)) || 0;
    const proposedCash = c.execPrice * proposedQty;
    const proposedPnl =
      c.pnl == null || !(c.qty > 0) ? null : c.pnl * (proposedQty / c.qty);
    return {
      ...c,
      proposedQty,
      proposedCash,
      proposedPnl,
    } as ProposedCandidate;
  });
}

function PoolCard({
  title,
  helperText,
  totalNode,
  cashLine,
  tone,
  selected = false,
  onSelectPool,
  sliderLabel,
  sliderHint,
  sliderComparator = "≤",
  sliderValue,
  sliderMax,
  valueSuffix = "",
  trackColor,
  onChange,
  cashFirst = false,
  wide = false,
  budgetLabel,
  budgetValue,
  budgetMax,
  onBudgetChange,
}: {
  title: string;
  helperText: string;
  totalNode?: ReactNode;
  cashLine: string;
  tone: "sell" | "buy";
  selected?: boolean;
  onSelectPool?: () => void;
  sliderLabel: string;
  sliderHint?: "proximity" | "saiScore" | "planSellRank";
  /** Shown glued to the numeric value (≤ / ≥). */
  sliderComparator?: "≤" | "≥";
  sliderValue: number;
  sliderMax: number;
  valueSuffix?: string;
  trackColor: string;
  onChange: (v: number) => void;
  cashFirst?: boolean;
  wide?: boolean;
  /** Optional cash budget (0 = off → full planned qty). */
  budgetLabel?: string;
  budgetValue?: number;
  budgetMax?: number;
  onBudgetChange?: (v: number) => void;
}) {
  const cashNode = (
    <Text style={[styles.poolCash, tone === "sell" ? styles.sellText : styles.buyText]}>{cashLine}</Text>
  );
  const budgetOn = typeof budgetValue === "number" && typeof budgetMax === "number" && !!onBudgetChange;
  const budgetAmt = budgetValue ?? 0;
  const budgetCap = Math.max(budgetMax ?? 0, 0);
  const setBudget = onBudgetChange;
  const defaultBudgetLabel = tone === "buy" ? "Buy Budget" : "Sell Budget";
  const budgetHelp =
    tone === "buy"
      ? {
          title: "Buy Budget",
          body: "Off (0) = full planned qty for each qualified buy.\n\nSet a cash budget to soft-split among qualified legs by readiness (closer / higher SAI gets more), like Tax & Trim.",
        }
      : {
          title: "Sell Budget",
          body: "Off (0) = full planned qty for each qualified sell.\n\nSet a cash budget to soft-split among qualified legs by readiness (closer / stronger Sell Rank gets more). Low-conviction legs face a stricter hidden rank bar.",
        };
  return (
    <View
      style={[
        styles.poolCard,
        tone === "sell" ? styles.poolCardSell : styles.poolCardBuy,
        selected ? (tone === "sell" ? styles.poolCardSellActive : styles.poolCardBuyActive) : null,
      ]}
    >
      <Pressable
        onPress={onSelectPool}
        accessibilityRole="button"
        accessibilityState={{ selected }}
        accessibilityLabel={`Show ${title} list`}
      >
        <View style={styles.poolHead}>
          <Text style={[styles.poolTitle, tone === "sell" ? styles.sellText : styles.buyText]}>{title}</Text>
          <Text style={styles.poolHelper}>{helperText}</Text>
        </View>
        {wide && totalNode ? (
          <View style={styles.poolTopLine}>
            {cashFirst ? cashNode : <Text style={styles.poolTotal}>{totalNode}</Text>}
            {cashFirst ? <Text style={styles.poolTotal}>{totalNode}</Text> : cashNode}
          </View>
        ) : (
          <>
            {cashFirst ? cashNode : null}
            {totalNode ? <Text style={styles.poolTotal}>{totalNode}</Text> : null}
            {cashFirst ? null : cashNode}
          </>
        )}
      </Pressable>
      <View style={styles.sliderHead}>
        {sliderHint ? (
          <GlossaryHint signal={sliderHint} label={sliderLabel} style={styles.sliderLabel} />
        ) : (
          <Text style={styles.sliderLabel}>{sliderLabel}</Text>
        )}
        <Text style={[styles.sliderValue, { color: trackColor }]}>
          <Text style={styles.sliderComparator}>{sliderComparator}</Text>
          {Math.round(sliderValue)}
          {valueSuffix}
        </Text>
      </View>
      <Slider
        style={styles.slider}
        minimumValue={0}
        maximumValue={sliderMax}
        step={1}
        value={Math.max(0, Math.min(sliderMax, sliderValue))}
        onValueChange={(v) => onChange(Math.round(v))}
        minimumTrackTintColor={trackColor}
        maximumTrackTintColor={colors.surfaceAlt}
        thumbTintColor={trackColor}
      />
      {budgetOn && setBudget ? (
        <>
          <View style={styles.sliderHead}>
            <Pressable
              onLongPress={() => Alert.alert(budgetHelp.title, budgetHelp.body)}
              delayLongPress={280}
              hitSlop={6}
            >
              <Text style={styles.sliderLabel}>{budgetLabel ?? defaultBudgetLabel}</Text>
            </Pressable>
            <Text style={[styles.sliderValue, { color: trackColor }]}>
              {budgetAmt > 0 ? formatMoney(budgetAmt, true) : "Off"}
            </Text>
          </View>
          <Slider
            style={styles.slider}
            minimumValue={0}
            maximumValue={Math.max(budgetCap, 1)}
            step={Math.max(100, Math.round(Math.max(budgetCap, 1) / 100))}
            value={Math.max(0, Math.min(budgetCap || 0, budgetAmt))}
            onValueChange={(v) => {
              if (!(budgetCap > 0)) {
                setBudget(0);
                return;
              }
              setBudget(Math.max(0, Math.min(budgetCap, Math.round(v))));
            }}
            minimumTrackTintColor={trackColor}
            maximumTrackTintColor={colors.surfaceAlt}
            thumbTintColor={trackColor}
          />
        </>
      ) : null}
    </View>
  );
}

export default function TradePlanScreen() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const { mode: modeParam } = useLocalSearchParams<{ mode?: string }>();
  const portfolioMode: PortfolioMode =
    modeParam === "holdings" || modeParam === "watch" || modeParam === "all" ? modeParam : "all";
  const { filter, hydrated: filterHydrated } = usePersistedSymbolFilter();
  const matchesSymbol = useSymbolFilterMatch(filter);

  const [pricingMode, setPricingMode] = useState<TaxTrimPricingMode>("current");
  const [qualificationMode, setQualificationMode] = useState<QualificationMode>("proximity");
  const [sellProxThreshold, setSellProxThreshold] = useState(10);
  const [buyProxThreshold, setBuyProxThreshold] = useState(10);
  const [sellScoreThreshold, setSellScoreThreshold] = useState(40);
  const [buyScoreThreshold, setBuyScoreThreshold] = useState(45);
  /** 0 = Off (full planned qty); >0 soft-split cash among qualified sells. */
  const [sellBudget, setSellBudget] = useState(0);
  /** 0 = Off (full planned qty); >0 soft-split cash among qualified buys. */
  const [buyBudget, setBuyBudget] = useState(0);
  const [listMode, setListMode] = useState<ListMode>("sell");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<PortfolioRow[]>([]);
  const [holdingBySymbol, setHoldingBySymbol] = useState<Map<string, Holding>>(new Map());
  const [scopeSymbols, setScopeSymbols] = useState<string[] | null>(null);
  const [scopeReady, setScopeReady] = useState(false);
  const [prefsReady, setPrefsReady] = useState(false);
  const prefsSyncRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const skipNextPrefsSync = useRef(true);

  const filterActive = Boolean(filter.trim());
  const landscape = width > height;
  const compactCards = width <= 420 && !landscape;
  const wideCards = landscape || width >= 760;
  const scopeLabel = useMemo(() => {
    if (!filterActive && portfolioMode === "all") return null;
    const bits: string[] = [];
    if (portfolioMode === "holdings") bits.push("Holdings");
    if (portfolioMode === "watch") bits.push("Watch");
    if (filterActive) {
      const parsed = parseSymbolFilter(filter);
      if (parsed.orTerms.includes("*") || parsed.requireStarred) bits.push("Starred");
      else bits.push(`Filter “${filter.trim()}”`);
    }
    const n = scopeSymbols?.length ?? 0;
    bits.push(`${n} symbol${n === 1 ? "" : "s"}`);
    return bits.join(" · ");
  }, [filter, filterActive, portfolioMode, scopeSymbols]);

  useEffect(() => {
    void (async () => {
      try {
        const prefs = await api.preferences();
        const tp = prefs.tradePlan;
        if (tp) {
          if (tp.pricingMode === "threshold" || tp.pricingMode === "current") {
            setPricingMode(tp.pricingMode);
          }
          if (tp.qualificationMode === "proximity" || tp.qualificationMode === "score") {
            setQualificationMode(tp.qualificationMode);
          }
          if (typeof tp.sellProxThreshold === "number" && Number.isFinite(tp.sellProxThreshold)) {
            setSellProxThreshold(Math.max(0, tp.sellProxThreshold));
          }
          if (typeof tp.buyProxThreshold === "number" && Number.isFinite(tp.buyProxThreshold)) {
            setBuyProxThreshold(Math.max(0, tp.buyProxThreshold));
          }
          if (typeof tp.sellScoreThreshold === "number" && Number.isFinite(tp.sellScoreThreshold)) {
            setSellScoreThreshold(Math.max(0, tp.sellScoreThreshold));
          }
          if (typeof tp.buyScoreThreshold === "number" && Number.isFinite(tp.buyScoreThreshold)) {
            setBuyScoreThreshold(Math.max(0, tp.buyScoreThreshold));
          }
          if (typeof tp.sellBudget === "number" && Number.isFinite(tp.sellBudget)) {
            setSellBudget(Math.max(0, Math.round(tp.sellBudget)));
          }
          if (typeof tp.buyBudget === "number" && Number.isFinite(tp.buyBudget)) {
            setBuyBudget(Math.max(0, Math.round(tp.buyBudget)));
          }
          if (tp.listMode === "sell" || tp.listMode === "buy") {
            setListMode(tp.listMode);
          }
        }
      } catch {
        /* defaults remain */
      } finally {
        setPrefsReady(true);
      }
    })();
  }, []);

  useEffect(() => {
    if (!filterHydrated) return;
    let cancelled = false;
    void (async () => {
      try {
        const [portfolio, holdings] = await Promise.all([api.portfolio(), api.holdings()]);
        if (cancelled) return;
        const holdingMap = new Map((holdings.holdings ?? []).map((h) => [h.symbol.toUpperCase(), h]));
        const symbols = (portfolio.symbols ?? [])
          .map((row) => row.symbol.toUpperCase())
          .filter((symbol) => {
            if (!matchesSymbol(symbol)) return false;
            const qty = holdingMap.get(symbol)?.quantity ?? 0;
            if (portfolioMode === "holdings") return qty > 0;
            if (portfolioMode === "watch") return !(qty > 0);
            return true;
          });
        if (!filterActive && portfolioMode === "all") setScopeSymbols(null);
        else setScopeSymbols(symbols);
      } catch {
        if (!cancelled) setScopeSymbols(filterActive || portfolioMode !== "all" ? [] : null);
      } finally {
        if (!cancelled) setScopeReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filter, filterActive, filterHydrated, matchesSymbol, portfolioMode]);

  const load = async (soft = false) => {
    if (!soft) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const [portfolio, holdings, assessments] = await Promise.all([
        api.portfolio(),
        api.holdings(),
        api.assessmentsOverview(),
      ]);
      const holdingMap = new Map((holdings.holdings ?? []).map((h) => [h.symbol, h]));
      setHoldingBySymbol(holdingMap);
      const assessmentMap = new Map((assessments.assessments ?? []).map((a) => [a.symbol, a]));
      const built = buildPortfolioRows(portfolio.symbols ?? [], holdingMap, assessmentMap);
      const filtered = built.filter((row) => {
        if (scopeSymbols && !scopeSymbols.includes(row.symbol.toUpperCase())) return false;
        return true;
      });
      setRows(filtered);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed to load";
      setError(msg);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (!prefsReady || !scopeReady) return;
    void load(rows.length > 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefsReady, scopeReady, scopeSymbols]);

  useEffect(() => {
    if (!prefsReady) return;
    if (skipNextPrefsSync.current) {
      skipNextPrefsSync.current = false;
      return;
    }
    if (prefsSyncRef.current) clearTimeout(prefsSyncRef.current);
    prefsSyncRef.current = setTimeout(() => {
      void api
        .updatePreferences({
          tradePlan: {
            pricingMode,
            qualificationMode,
            sellProxThreshold,
            buyProxThreshold,
            sellScoreThreshold,
            buyScoreThreshold,
            sellBudget,
            buyBudget,
            listMode,
          },
        })
        .catch(() => {
          /* offline ok */
        });
    }, 500);
    return () => {
      if (prefsSyncRef.current) clearTimeout(prefsSyncRef.current);
    };
  }, [
    prefsReady,
    pricingMode,
    qualificationMode,
    sellProxThreshold,
    buyProxThreshold,
    sellScoreThreshold,
    buyScoreThreshold,
    sellBudget,
    buyBudget,
    listMode,
  ]);

  const allCandidates = useMemo(
    () => rows.flatMap((row) => candidateFromRow(row, holdingBySymbol, pricingMode)),
    [rows, holdingBySymbol, pricingMode],
  );
  const sellCandidates = useMemo(
    () =>
      allCandidates
        // Watch-only (no shares held) cannot sell — exclude from Sell Plan.
        .filter((row) => row.side === "sell" && row.held > 0)
        .sort((a, b) => {
          // Sort follows Proximity / SAI·Rank switch.
          if (qualificationMode === "score") {
            return scoreModeValue(a) - scoreModeValue(b) || a.proximityAbsPct - b.proximityAbsPct;
          }
          return a.proximityAbsPct - b.proximityAbsPct || a.planSellRank - b.planSellRank;
        }),
    [allCandidates, qualificationMode],
  );
  const buyCandidates = useMemo(
    () =>
      allCandidates
        .filter((row) => row.side === "buy")
        .sort((a, b) => {
          if (qualificationMode === "score") {
            return scoreModeValue(b) - scoreModeValue(a) || a.proximityAbsPct - b.proximityAbsPct;
          }
          return a.proximityAbsPct - b.proximityAbsPct || (b.saiScore ?? -1) - (a.saiScore ?? -1);
        }),
    [allCandidates, qualificationMode],
  );

  const sellScoreMax = useMemo(
    () => Math.max(1, Math.round(sellCandidates.reduce((m, c) => Math.max(m, c.planSellRank), 0))),
    [sellCandidates],
  );
  const sellGate = qualificationMode === "score" ? sellScoreThreshold : sellProxThreshold;
  const buyGate = qualificationMode === "score" ? buyScoreThreshold : buyProxThreshold;
  const sellGateMax = qualificationMode === "score" ? Math.max(sellScoreMax, PLAN_ATTRACT_CEILING) : 50;
  const buyGateMax = qualificationMode === "score" ? SAI_SCORE_MAX : 30;

  /** Full planned cash of gate-passers — upper bound for budget sliders. */
  const sellFullGateCash = useMemo(
    () =>
      sellCandidates.reduce((sum, c) => {
        if (!passesQualificationGate(c, sellGate, qualificationMode)) return sum;
        return sum + maxLegQty(c) * c.execPrice;
      }, 0),
    [sellCandidates, sellGate, qualificationMode],
  );
  const buyFullGateCash = useMemo(
    () =>
      buyCandidates.reduce((sum, c) => {
        if (!passesQualificationGate(c, buyGate, qualificationMode)) return sum;
        return sum + maxLegQty(c) * c.execPrice;
      }, 0),
    [buyCandidates, buyGate, qualificationMode],
  );

  useEffect(() => {
    // Only clamp once gate cash is known — avoid wiping a restored budget at cash=0.
    if (sellFullGateCash > 0 && sellBudget > sellFullGateCash) {
      setSellBudget(Math.round(sellFullGateCash));
    }
  }, [sellFullGateCash, sellBudget]);

  useEffect(() => {
    if (buyFullGateCash > 0 && buyBudget > buyFullGateCash) {
      setBuyBudget(Math.round(buyFullGateCash));
    }
  }, [buyFullGateCash, buyBudget]);

  const proposedSells = useMemo(
    () => proposeCandidates(sellCandidates, sellGate, qualificationMode, sellGateMax, sellBudget),
    [sellCandidates, sellGate, qualificationMode, sellGateMax, sellBudget],
  );
  const proposedBuys = useMemo(
    () => proposeCandidates(buyCandidates, buyGate, qualificationMode, buyGateMax, buyBudget),
    [buyCandidates, buyGate, qualificationMode, buyGateMax, buyBudget],
  );

  const qualifiedSells = useMemo(() => proposedSells.filter((row) => row.proposedQty > 0), [proposedSells]);
  const qualifiedBuys = useMemo(() => proposedBuys.filter((row) => row.proposedQty > 0), [proposedBuys]);

  const sellCash = qualifiedSells.reduce((sum, row) => sum + row.proposedCash, 0);
  const sellGain = qualifiedSells.reduce((sum, row) => sum + Math.max(0, Number(row.proposedPnl) || 0), 0);
  const sellLoss = qualifiedSells.reduce((sum, row) => sum + Math.max(0, -(Number(row.proposedPnl) || 0)), 0);
  const sellNet = sellGain - sellLoss;
  const buyCash = qualifiedBuys.reduce((sum, row) => sum + row.proposedCash, 0);

  const refreshControl = (
    <RefreshControl
      refreshing={refreshing}
      onRefresh={() => void load(true)}
      tintColor={colors.accent}
    />
  );

  function sortArrowFor(mode: ListMode, metric: QualificationMode): string {
    if (qualificationMode !== metric) return "";
    // Sell Rank asc (↑), Buy SAI desc (↓), Prox closest-first (↑).
    if (metric === "score" && mode === "buy") return "↓ ";
    return "↑ ";
  }

  const renderSell = () => {
    if (!sellCandidates.length) return <Text style={styles.empty}>No sell candidates in scope.</Text>;
    const browseSymbols = proposedSells.map((cand) => cand.symbol);
    return proposedSells.map((row) => {
      const gatePasses = passesQualificationGate(row, sellGate, qualificationMode);
      const qualifies = row.proposedQty > 0;
      const scoreReason =
        qualificationMode === "score" && !gatePasses ? scoreGateReason(row, sellGate) : null;
      const budgetReason =
        qualificationMode === "score" && gatePasses && !qualifies && sellBudget > 0
          ? "Qualified, but budget allocated to stronger legs"
          : null;
      const maxTxt = row.pnl == null ? "—" : formatMoney(row.pnl, true);
      const propTxt = row.proposedPnl == null ? "—" : formatMoney(row.proposedPnl, true);
      const proxSortLabel = `${sortArrowFor("sell", "proximity")}Prox`;
      const rankSortLabel = `${sortArrowFor("sell", "score")}Sell Rank`;
      return (
        <Pressable
          key={`${row.symbol}-sell-${row.thresholdPrice}`}
          style={[
            styles.card,
            styles.sellBase,
            qualifies ? styles.sellQualified : styles.sellUnqualified,
            row.pnl != null && row.pnl > 0 ? styles.sellGainTint : null,
            row.pnl != null && row.pnl < 0 ? styles.sellLossTint : null,
          ]}
          onPress={() => openSymbol(row.symbol, browseSymbols, "trade-plan")}
        >
          <View style={styles.cardHead}>
            <Text style={styles.symbol}>{row.symbol}</Text>
            <Text style={[styles.execHint, styles.execHintStrong]}>
              @ {row.execSource === "threshold" ? "The" : "Cur"} {formatPrice(row.execPrice)}
            </Text>
          </View>
          {compactCards ? (
            <View style={styles.compactMetrics}>
              <Text style={styles.compactLine}>
                <Text style={styles.metricLabel}>Prop Sell </Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatQty(row.proposedQty) : "0"} (of {formatQty(row.qty)})
                </Text>
              </Text>
              <Text style={styles.compactLine}>
                <Text style={styles.metricLabel}>Cash </Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatMoney(row.proposedCash, true) : formatMoney(row.cash, true)}
                </Text>
              </Text>
              <View style={styles.compactHintRow}>
                <GlossaryHint signal="proximity" label={proxSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>{` ${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%`}</Text>
                <Text style={styles.metricLabel}>  · </Text>
                <GlossaryHint signal="planSellRank" label={rankSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>{` ${Math.round(scoreModeValue(row))}`}</Text>
              </View>
              {qualificationMode === "score" ? (
                <Text style={styles.metricSub}>
                  C{row.convictionScore} · R{row.readinessScore} · E{row.executionScore}
                </Text>
              ) : null}
              {scoreReason || budgetReason ? (
                <Text style={styles.metricSub}>{scoreReason || budgetReason}</Text>
              ) : null}
            </View>
          ) : (
            <View style={[styles.metricsRow, wideCards && styles.metricsRowWide]}>
              <View style={[styles.metric, { flex: wideCards ? 1.1 : 1.2 }]}>
                <Text style={styles.metricLabel}>Prop Sell</Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatQty(row.proposedQty) : "0"} (of {formatQty(row.qty)} / {formatQty(row.held)})
                </Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 0.9 : 1.15 }]}>
                <Text style={styles.metricLabel}>{qualifies ? "Prop Gain (Max)" : "Max Gain"}</Text>
                <Text style={[styles.metricValue, { color: row.pnl != null && row.pnl >= 0 ? colors.buy : colors.sell }]}>
                  {qualifies ? `${propTxt} (${maxTxt})` : maxTxt}
                </Text>
              </View>
              <View style={[styles.metric, { flex: 0.8 }]}>
                <Text style={styles.metricLabel}>Cash</Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatMoney(row.proposedCash, true) : formatMoney(row.cash, true)}
                </Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 1.15 : 1.35 }]}>
                <GlossaryHint signal="proximity" label={proxSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>{wideCards ? `${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%` : proximityDetailText(row)}</Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 1.0 : 0.85 }]}>
                <GlossaryHint signal="planSellRank" label={rankSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>{Math.round(scoreModeValue(row))}</Text>
                {wideCards ? null : (
                  <Pressable
                    onLongPress={() => Alert.alert("Plan Attract", signalTooltip("planAttract"))}
                    delayLongPress={280}
                    hitSlop={6}
                  >
                    <Text style={styles.metricSub}>
                      P{Math.round(row.proximityScore)} T{Math.round(row.triggerScore)} S{Math.round(row.sizeScore)}
                    </Text>
                  </Pressable>
                )}
              </View>
            </View>
          )}
          {qualificationMode === "score" ? (
            <Text style={styles.metricSub}>
              Conviction {row.convictionScore} · Readiness {row.readinessScore} · Execution {row.executionScore}
            </Text>
          ) : null}
          {scoreReason || budgetReason ? (
            <Text style={styles.metricSub}>{scoreReason || budgetReason}</Text>
          ) : null}
        </Pressable>
      );
    });
  };

  const renderBuy = () => {
    if (!buyCandidates.length) return <Text style={styles.empty}>No buy candidates in scope.</Text>;
    const browseSymbols = proposedBuys.map((cand) => cand.symbol);
    return proposedBuys.map((row) => {
      const gatePasses = passesQualificationGate(row, buyGate, qualificationMode);
      const qualifies = row.proposedQty > 0;
      const scoreReason =
        qualificationMode === "score" && !gatePasses ? scoreGateReason(row, buyGate) : null;
      const budgetReason =
        qualificationMode === "score" && gatePasses && !qualifies && buyBudget > 0
          ? "Qualified, but budget allocated to stronger legs"
          : null;
      const proxSortLabel = `${sortArrowFor("buy", "proximity")}Prox`;
      const saiSortLabel = `${sortArrowFor("buy", "score")}SAI`;
      return (
        <Pressable
          key={`${row.symbol}-buy-${row.thresholdPrice}`}
          style={[
            styles.card,
            styles.buyBase,
            qualifies ? styles.buyQualified : styles.buyUnqualified,
          ]}
          onPress={() => openSymbol(row.symbol, browseSymbols, "trade-plan")}
        >
          <View style={styles.cardHead}>
            <Text style={styles.symbol}>{row.symbol}</Text>
            <Text style={[styles.execHint, styles.execHintStrong]}>
              @ {row.execSource === "threshold" ? "The" : "Cur"} {formatPrice(row.execPrice)}
            </Text>
          </View>
          {compactCards ? (
            <View style={styles.compactMetrics}>
              <Text style={styles.compactLine}>
                <Text style={styles.metricLabel}>Prop Buy </Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatQty(row.proposedQty) : "0"} (of {formatQty(row.qty)})
                </Text>
              </Text>
              <Text style={styles.compactLine}>
                <Text style={styles.metricLabel}>Cash </Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatMoney(row.proposedCash, true) : formatMoney(row.cash, true)}
                </Text>
              </Text>
              <View style={styles.compactHintRow}>
                <GlossaryHint signal="proximity" label={proxSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>{` ${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%`}</Text>
                <Text style={styles.metricLabel}>  · </Text>
                <GlossaryHint signal="saiScore" label={saiSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>
                  {` ${row.saiScore == null ? "—" : Math.round(scoreModeValue(row))}`}
                </Text>
              </View>
              {qualificationMode === "score" ? (
                <Text style={styles.metricSub}>
                  C{row.convictionScore} · R{row.readinessScore} · E{row.executionScore}
                </Text>
              ) : null}
              {scoreReason || budgetReason ? (
                <Text style={styles.metricSub}>{scoreReason || budgetReason}</Text>
              ) : null}
            </View>
          ) : (
            <View style={[styles.metricsRow, wideCards && styles.metricsRowWide]}>
              <View style={[styles.metric, { flex: wideCards ? 1.1 : 1.25 }]}>
                <Text style={styles.metricLabel}>Prop Buy</Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatQty(row.proposedQty) : "0"} (of {formatQty(row.qty)})
                </Text>
              </View>
              <View style={[styles.metric, { flex: 0.8 }]}>
                <Text style={styles.metricLabel}>Cash</Text>
                <Text style={styles.metricValue}>
                  {qualifies ? formatMoney(row.proposedCash, true) : formatMoney(row.cash, true)}
                </Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 1.15 : 1.45 }]}>
                <GlossaryHint signal="proximity" label={proxSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>{wideCards ? `${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%` : proximityDetailText(row)}</Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 1.0 : 0.85 }]}>
                <GlossaryHint signal="saiScore" label={saiSortLabel} style={styles.metricLabel} />
                <Text style={styles.metricValue}>
                  {row.saiScore == null ? "—" : Math.round(scoreModeValue(row))}
                </Text>
              </View>
            </View>
          )}
          {qualificationMode === "score" ? (
            <Text style={styles.metricSub}>
              Conviction {row.convictionScore} · Readiness {row.readinessScore} · Execution {row.executionScore}
            </Text>
          ) : null}
          {scoreReason || budgetReason ? (
            <Text style={styles.metricSub}>{scoreReason || budgetReason}</Text>
          ) : null}
        </Pressable>
      );
    });
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.controls}>
        <View style={styles.segRow}>
          <Pressable style={[styles.pill, pillStyle(pricingMode === "current")]} onPress={() => setPricingMode("current")}>
            <Text style={styles.pillText}>Current</Text>
          </Pressable>
          <Pressable style={[styles.pill, pillStyle(pricingMode === "threshold")]} onPress={() => setPricingMode("threshold")}>
            <Text style={styles.pillText}>Threshold</Text>
          </Pressable>
          <View style={styles.qualModeWrap}>
            <Pressable
              style={[styles.qualModeBtn, qualificationMode === "proximity" ? styles.qualModeBtnActive : styles.qualModeBtnIdle]}
              onPress={() => setQualificationMode("proximity")}
              onLongPress={() => Alert.alert("Proximity", signalTooltip("proximity"))}
              delayLongPress={280}
              accessibilityState={{ selected: qualificationMode === "proximity" }}
              accessibilityHint={signalTooltip("proximity")}
            >
              <Text
                style={[
                  styles.qualModeText,
                  qualificationMode === "proximity" ? styles.qualModeTextActive : styles.qualModeTextIdle,
                ]}
              >
                Proximity
              </Text>
            </Pressable>
            <Pressable
              style={[styles.qualModeBtn, qualificationMode === "score" ? styles.qualModeBtnActive : styles.qualModeBtnIdle]}
              onPress={() => setQualificationMode("score")}
              onLongPress={() =>
                Alert.alert(
                  "Score mode",
                  "Rule of thumb:\n• Buy Score — HIGHER = stronger buy-to-fire\n• Sell Rank — LOWER = stronger sell-to-fire\n\nNumbers shown are effective (conviction penalty already applied).\n\n" +
                    `${signalTooltip("saiScore")}\n\n${signalTooltip("planSellRank")}`,
                )
              }
              delayLongPress={280}
              accessibilityState={{ selected: qualificationMode === "score" }}
              accessibilityHint="Buy Score: higher is stronger. Sell Rank: lower is stronger. Low conviction tightens automatically."
            >
              <Text
                style={[
                  styles.qualModeText,
                  qualificationMode === "score" ? styles.qualModeTextActive : styles.qualModeTextIdle,
                ]}
              >
                SAI / Rank*
              </Text>
            </Pressable>
          </View>
        </View>
        {scopeLabel ? <Text style={styles.scopeHint}>Scope: {scopeLabel}</Text> : null}
        {qualificationMode === "score" ? (
          <Text style={styles.scopeHint}>* Effective scores/ranks include an automatic conviction penalty.</Text>
        ) : null}
        <View style={styles.poolRow}>
          <PoolCard
            title="Sell Pool"
            tone="sell"
            selected={listMode === "sell"}
            onSelectPool={() => setListMode("sell")}
            helperText={`${qualifiedSells.length} of ${sellCandidates.length} qualified`}
            totalNode={
              <>
                TOTAL{" "}
                <Text
                  style={
                    sellNet > 0 ? styles.gainText : sellNet < 0 ? styles.lossText : styles.neutralText
                  }
                >
                  {formatMoney(sellNet, true)}
                </Text>{" "}
                (
                <Text style={sellGain > 0 ? styles.gainText : styles.neutralText}>
                  {formatMoney(sellGain, true)}
                </Text>
                ,{" "}
                <Text style={sellLoss > 0 ? styles.lossText : styles.neutralText}>
                  {formatMoney(-sellLoss, true)}
                </Text>
                )
              </>
            }
            cashLine={`CASH ${formatMoney(sellCash, true)}`}
            sliderLabel={qualificationMode === "score" ? "Sell Rank" : "Sell Proximity"}
            sliderHint={qualificationMode === "score" ? "planSellRank" : "proximity"}
            sliderComparator="≤"
            sliderValue={sellGate}
            sliderMax={sellGateMax}
            valueSuffix={qualificationMode === "score" ? "" : "%"}
            onChange={qualificationMode === "score" ? setSellScoreThreshold : setSellProxThreshold}
            trackColor="#60a5fa"
            cashFirst
            wide={wideCards}
            budgetLabel="Sell Budget"
            budgetValue={sellBudget}
            budgetMax={Math.max(sellFullGateCash, 0)}
            onBudgetChange={setSellBudget}
          />
          <PoolCard
            title="Buy Pool"
            tone="buy"
            selected={listMode === "buy"}
            onSelectPool={() => setListMode("buy")}
            helperText={`${qualifiedBuys.length} of ${buyCandidates.length} qualified`}
            cashLine={`CASH ${formatMoney(buyCash, true)}`}
            sliderLabel={qualificationMode === "score" ? "SAI Score" : "Buy Proximity"}
            sliderHint={qualificationMode === "score" ? "saiScore" : "proximity"}
            sliderComparator={qualificationMode === "score" ? "≥" : "≤"}
            sliderValue={buyGate}
            sliderMax={buyGateMax}
            valueSuffix={qualificationMode === "score" ? "" : "%"}
            onChange={qualificationMode === "score" ? setBuyScoreThreshold : setBuyProxThreshold}
            trackColor="#fb923c"
            wide={wideCards}
            budgetLabel="Buy Budget"
            budgetValue={buyBudget}
            budgetMax={Math.max(buyFullGateCash, 0)}
            onBudgetChange={setBuyBudget}
          />
        </View>
      </View>

      {loading ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : error ? (
        <View style={styles.centered}>
          <Text style={styles.error}>{error}</Text>
          <Pressable style={styles.retryBtn} onPress={() => void load()}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.list} refreshControl={refreshControl}>
          {listMode === "sell" ? renderSell() : renderBuy()}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  controls: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: spacing.sm,
  },
  segRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  pill: {
    borderWidth: 1,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
  },
  qualModeWrap: {
    marginLeft: "auto",
    flexDirection: "row",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    overflow: "hidden",
    backgroundColor: colors.surface,
  },
  qualModeBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
  },
  qualModeBtnIdle: {
    backgroundColor: "transparent",
  },
  qualModeBtnActive: {
    backgroundColor: colors.accent,
  },
  qualModeText: {
    fontSize: 12,
    fontWeight: "800",
  },
  qualModeTextIdle: {
    color: colors.textMuted,
  },
  qualModeTextActive: {
    color: "#0b1220",
  },
  pillText: { color: colors.text, fontWeight: "600", fontSize: 13 },
  scopeHint: { color: colors.textMuted, fontSize: 12, fontWeight: "600" },
  poolRow: { flexDirection: "row", gap: spacing.sm },
  poolCard: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radii.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
  },
  poolCardSell: {
    backgroundColor: "rgba(59,130,246,0.08)",
    borderColor: "rgba(96,165,250,0.4)",
  },
  poolCardBuy: {
    backgroundColor: "rgba(251,146,60,0.08)",
    borderColor: "rgba(251,146,60,0.4)",
  },
  poolCardSellActive: {
    borderColor: "rgba(147,197,253,0.85)",
    backgroundColor: "rgba(59,130,246,0.16)",
  },
  poolCardBuyActive: {
    borderColor: "rgba(253,186,116,0.85)",
    backgroundColor: "rgba(251,146,60,0.16)",
  },
  poolHead: { flexDirection: "row", justifyContent: "space-between", gap: spacing.xs, alignItems: "flex-start" },
  poolTitle: { color: colors.textMuted, fontSize: 11, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.4 },
  poolHelper: { flex: 1, textAlign: "right", color: colors.textMuted, fontSize: 10, fontWeight: "600" },
  poolTotal: { color: colors.text, fontSize: 12, fontWeight: "700", marginTop: 4 },
  poolCash: { color: colors.text, fontSize: 12, fontWeight: "700", marginTop: 2 },
  poolTopLine: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: spacing.sm },
  sliderHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginTop: 6, gap: spacing.sm },
  sliderLabel: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
    flexShrink: 1,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  sliderValue: { fontSize: 14, fontWeight: "800", fontVariant: ["tabular-nums"] },
  sliderComparator: { fontSize: 14, fontWeight: "800" },
  slider: { width: "100%", height: 32 },
  list: { padding: spacing.md, gap: spacing.sm, paddingBottom: spacing.xl * 2 },
  card: { borderWidth: 1, borderRadius: radii.md, padding: spacing.md, gap: spacing.sm },
  sellBase: { backgroundColor: "rgba(59,130,246,0.08)", borderColor: "rgba(96,165,250,0.35)" },
  buyBase: { backgroundColor: "rgba(251,146,60,0.08)", borderColor: "rgba(251,146,60,0.35)" },
  sellQualified: { borderColor: "rgba(147,197,253,0.85)", backgroundColor: "rgba(59,130,246,0.16)" },
  sellUnqualified: { opacity: 0.7 },
  buyQualified: { borderColor: "rgba(253,186,116,0.85)", backgroundColor: "rgba(251,146,60,0.16)" },
  buyUnqualified: { opacity: 0.7 },
  sellGainTint: { borderLeftWidth: 3, borderLeftColor: colors.buy },
  sellLossTint: { borderLeftWidth: 3, borderLeftColor: colors.sell },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: spacing.sm },
  symbol: { color: colors.text, fontSize: 16, fontWeight: "700" },
  execHint: { color: colors.textMuted, fontSize: 11 },
  execHintStrong: { color: colors.text, fontSize: 16, fontWeight: "700", lineHeight: 20 },
  metricsRow: { flexDirection: "row", gap: spacing.sm },
  metricsRowWide: { gap: spacing.xs },
  metric: { gap: 2, minWidth: 0, flex: 1 },
  compactMetrics: { gap: 3 },
  compactLine: { color: colors.text, fontSize: 13, fontWeight: "600" },
  compactHintRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
  },
  metricLabel: { color: colors.textMuted, fontSize: 10, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.3 },
  metricValue: { color: colors.text, fontSize: 13, fontWeight: "700" },
  metricSub: { color: colors.textMuted, fontSize: 10, fontWeight: "600" },
  sellText: { color: "#93c5fd" },
  buyText: { color: "#fdba74" },
  gainText: { color: colors.buy },
  lossText: { color: colors.sell },
  neutralText: { color: colors.text },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.lg },
  error: { color: colors.danger, textAlign: "center" },
  retryBtn: { borderWidth: 1, borderColor: colors.border, borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: 8 },
  retryText: { color: colors.text, fontWeight: "600", fontSize: 13 },
  empty: { color: colors.textMuted, textAlign: "center", marginTop: spacing.xl },
});

