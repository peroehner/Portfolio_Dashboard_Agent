import Slider from "@react-native-community/slider";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
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

import { api, ApiError } from "@/lib/api";
import { parseSymbolFilter } from "@/lib/filters";
import { formatMoney, formatPrice } from "@/lib/format";
import { openSymbol } from "@/lib/symbolBrowseSession";
import { buildPortfolioRows } from "@/lib/portfolioTable";
import { colors, radii, spacing } from "@/lib/theme";
import type { Holding, PortfolioRow, TaxTrimPricingMode } from "@/lib/types";
import { usePersistedSymbolFilter } from "@/lib/usePersistedSymbolFilter";
import { useSymbolFilterMatch } from "@/lib/useSymbolFilterMatch";

type PortfolioMode = "all" | "holdings" | "watch";
type ListMode = "sell" | "buy";
type Side = "buy" | "sell";
type QualificationMode = "proximity" | "score";
type SortMetric = "proximity" | "score";

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
  proximityScore: number;
  triggerScore: number;
  sizeScore: number;
  totalScore: number;
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

function candidateFromRow(
  row: PortfolioRow,
  holdingBySymbol: Map<string, Holding>,
  pricingMode: TaxTrimPricingMode,
): PlanCandidate[] {
  const currentPrice = Number(row.currentPrice) || 0;
  if (!(currentPrice > 0)) return [];
  const held = Number(holdingBySymbol.get(row.symbol)?.quantity) || 0;
  const costBasis = Number(holdingBySymbol.get(row.symbol)?.costBasis);
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
    // Attractiveness for this side's action (closer / triggered / larger).
    const proximityScore = Math.max(0, 50 - proximityAbsPct);
    const triggerScore =
      side === "sell" ? (proximitySignedPct >= 0 ? 15 : 0) : (proximitySignedPct <= 0 ? 15 : 0);
    const sizeScore = Math.min(15, (cash / 50_000) * 15);
    const attract = proximityScore + triggerScore + sizeScore;
    // Directional score: high = buy lean, low = sell lean (so Buy ≥ / Sell ≤ gates).
    const SCORE_CEILING = 80;
    const totalScore = side === "buy" ? attract : Math.max(0, SCORE_CEILING - attract);
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
      totalScore,
    };
  });
}

function proposedQtyFromThreshold(
  candidate: PlanCandidate,
  threshold: number,
  mode: QualificationMode,
  thresholdMax: number,
): number {
  const candidateValue = mode === "score" ? candidate.totalScore : candidate.proximityAbsPct;
  // Proximity: both sides ≤ limit. Score: Buy ≥ (high=buy), Sell ≤ (low=sell).
  const qualifies =
    mode === "score"
      ? candidate.side === "buy"
        ? candidateValue >= threshold
        : candidateValue <= threshold
      : candidateValue <= threshold;
  if (!qualifies) return 0;
  if (!(candidate.qty > 0)) return 0;
  if (!(thresholdMax > 0)) return Math.floor(candidate.qty);
  // Proposed allocation scales by margin inside qualification gate.
  const margin =
    mode === "score"
      ? candidate.side === "buy"
        ? Math.max(0, candidateValue - threshold)
        : Math.max(0, threshold - candidateValue)
      : Math.max(0, threshold - candidateValue);
  const ratio = Math.max(0.15, Math.min(1, margin / thresholdMax));
  return Math.max(1, Math.floor(candidate.qty * ratio));
}

function PoolCard({
  title,
  helperText,
  totalNode,
  cashLine,
  tone,
  sliderLabel,
  sliderValue,
  sliderMax,
  valueSuffix = "",
  trackColor,
  onChange,
  cashFirst = false,
  wide = false,
}: {
  title: string;
  helperText: string;
  totalNode?: ReactNode;
  cashLine: string;
  tone: "sell" | "buy";
  sliderLabel: string;
  sliderValue: number;
  sliderMax: number;
  valueSuffix?: string;
  trackColor: string;
  onChange: (v: number) => void;
  cashFirst?: boolean;
  wide?: boolean;
}) {
  const cashNode = (
    <Text style={[styles.poolCash, tone === "sell" ? styles.sellText : styles.buyText]}>{cashLine}</Text>
  );
  return (
    <View style={[styles.poolCard, tone === "sell" ? styles.poolCardSell : styles.poolCardBuy]}>
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
      <View style={styles.sliderHead}>
        <Text style={styles.sliderLabel}>{sliderLabel}</Text>
        <Text style={[styles.sliderValue, { color: trackColor }]}>
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
  const [buyScoreThreshold, setBuyScoreThreshold] = useState(40);
  const [listMode, setListMode] = useState<ListMode>("sell");
  const [sellSortMetric, setSellSortMetric] = useState<SortMetric>("score");
  const [buySortMetric, setBuySortMetric] = useState<SortMetric>("score");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<PortfolioRow[]>([]);
  const [holdingBySymbol, setHoldingBySymbol] = useState<Map<string, Holding>>(new Map());
  const [scopeSymbols, setScopeSymbols] = useState<string[] | null>(null);
  const [scopeReady, setScopeReady] = useState(false);

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
    if (!scopeReady) return;
    void load(rows.length > 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeReady, scopeSymbols]);

  const allCandidates = useMemo(
    () => rows.flatMap((row) => candidateFromRow(row, holdingBySymbol, pricingMode)),
    [rows, holdingBySymbol, pricingMode],
  );
  const sellCandidates = useMemo(
    () =>
      allCandidates
        .filter((row) => row.side === "sell")
        .sort((a, b) => {
          if (sellSortMetric === "score") {
            return a.totalScore - b.totalScore || a.proximityAbsPct - b.proximityAbsPct;
          }
          return a.proximityAbsPct - b.proximityAbsPct || a.totalScore - b.totalScore;
        }),
    [allCandidates, sellSortMetric],
  );
  const buyCandidates = useMemo(
    () =>
      allCandidates
        .filter((row) => row.side === "buy")
        .sort((a, b) => {
          if (buySortMetric === "score") {
            return b.totalScore - a.totalScore || a.proximityAbsPct - b.proximityAbsPct;
          }
          return a.proximityAbsPct - b.proximityAbsPct || b.totalScore - a.totalScore;
        }),
    [allCandidates, buySortMetric],
  );

  function toggleSortFor(mode: ListMode) {
    if (mode === "sell") {
      setSellSortMetric((prev) => (prev === "score" ? "proximity" : "score"));
    } else {
      setBuySortMetric((prev) => (prev === "score" ? "proximity" : "score"));
    }
  }

  function listButtonLabel(mode: ListMode): string {
    const metric = mode === "sell" ? sellSortMetric : buySortMetric;
    const scoreArrow = mode === "sell" ? "↑" : "↓";
    const activeArrow = metric === "score" ? scoreArrow : "↑";
    const short = compactCards ? "S|P" : "Score|Prox";
    const base = mode === "sell" ? "Sell" : "Buy";
    return `${base} ${compactCards ? "" : "Candidates "}(${activeArrow} ${short})`;
  }

  const sellScoreMax = useMemo(
    () => Math.max(1, Math.round(sellCandidates.reduce((m, c) => Math.max(m, c.totalScore), 0))),
    [sellCandidates],
  );
  const buyScoreMax = useMemo(
    () => Math.max(1, Math.round(buyCandidates.reduce((m, c) => Math.max(m, c.totalScore), 0))),
    [buyCandidates],
  );
  const sellGate = qualificationMode === "score" ? sellScoreThreshold : sellProxThreshold;
  const buyGate = qualificationMode === "score" ? buyScoreThreshold : buyProxThreshold;
  const sellGateMax = qualificationMode === "score" ? Math.max(sellScoreMax, 80) : 50;
  const buyGateMax = qualificationMode === "score" ? Math.max(buyScoreMax, 80) : 30;

  const proposedSells = useMemo(
    () =>
      sellCandidates.map((row) => {
        const proposedQty = proposedQtyFromThreshold(row, sellGate, qualificationMode, sellGateMax);
        const ratio = row.qty > 0 ? proposedQty / row.qty : 0;
        return {
          ...row,
          proposedQty,
          proposedCash: row.cash * ratio,
          proposedPnl: row.pnl == null ? null : row.pnl * ratio,
        } as ProposedCandidate;
      }),
    [sellCandidates, sellGate, qualificationMode, sellGateMax],
  );
  const proposedBuys = useMemo(
    () =>
      buyCandidates.map((row) => {
        const proposedQty = proposedQtyFromThreshold(row, buyGate, qualificationMode, buyGateMax);
        const ratio = row.qty > 0 ? proposedQty / row.qty : 0;
        return {
          ...row,
          proposedQty,
          proposedCash: row.cash * ratio,
          proposedPnl: null,
        } as ProposedCandidate;
      }),
    [buyCandidates, buyGate, qualificationMode, buyGateMax],
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

  const renderSell = () => {
    if (!sellCandidates.length) return <Text style={styles.empty}>No sell candidates in scope.</Text>;
    const browseSymbols = proposedSells.map((cand) => cand.symbol);
    return proposedSells.map((row) => {
      const qualifies = row.proposedQty > 0;
      const maxTxt = row.pnl == null ? "—" : formatMoney(row.pnl, true);
      const propTxt = row.proposedPnl == null ? "—" : formatMoney(row.proposedPnl, true);
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
              <Text style={styles.compactLine}>
                <Text style={styles.metricLabel}>Proximity </Text>
                <Text style={styles.metricValue}>{`${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%`}</Text>
                <Text style={styles.metricLabel}>  · Score </Text>
                <Text style={styles.metricValue}>{Math.round(row.totalScore)}</Text>
              </Text>
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
                <Text style={styles.metricLabel}>Proximity</Text>
                <Text style={styles.metricValue}>{wideCards ? `${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%` : proximityDetailText(row)}</Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 1.0 : 0.85 }]}>
                <Text style={styles.metricLabel}>Score</Text>
                <Text style={styles.metricValue}>{Math.round(row.totalScore)}</Text>
                {wideCards ? null : (
                  <Text style={styles.metricSub}>
                    P{Math.round(row.proximityScore)} T{Math.round(row.triggerScore)} S{Math.round(row.sizeScore)}
                  </Text>
                )}
              </View>
            </View>
          )}
        </Pressable>
      );
    });
  };

  const renderBuy = () => {
    if (!buyCandidates.length) return <Text style={styles.empty}>No buy candidates in scope.</Text>;
    const browseSymbols = proposedBuys.map((cand) => cand.symbol);
    return proposedBuys.map((row) => {
      const qualifies = row.proposedQty > 0;
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
              <Text style={styles.compactLine}>
                <Text style={styles.metricLabel}>Proximity </Text>
                <Text style={styles.metricValue}>{`${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%`}</Text>
                <Text style={styles.metricLabel}>  · Score </Text>
                <Text style={styles.metricValue}>{Math.round(row.totalScore)}</Text>
              </Text>
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
                <Text style={styles.metricLabel}>Proximity</Text>
                <Text style={styles.metricValue}>{wideCards ? `${row.proximitySignedPct >= 0 ? "+" : ""}${row.proximitySignedPct.toFixed(1)}%` : proximityDetailText(row)}</Text>
              </View>
              <View style={[styles.metric, { flex: wideCards ? 1.0 : 0.85 }]}>
                <Text style={styles.metricLabel}>Score</Text>
                <Text style={styles.metricValue}>{Math.round(row.totalScore)}</Text>
                {wideCards ? null : (
                  <Text style={styles.metricSub}>
                    P{Math.round(row.proximityScore)} T{Math.round(row.triggerScore)} S{Math.round(row.sizeScore)}
                  </Text>
                )}
              </View>
            </View>
          )}
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
              style={[styles.qualModeBtn, qualificationMode === "proximity" ? styles.qualModeBtnActive : null]}
              onPress={() => setQualificationMode("proximity")}
            >
              <Text style={styles.qualModeText}>Proximity</Text>
            </Pressable>
            <Pressable
              style={[styles.qualModeBtn, qualificationMode === "score" ? styles.qualModeBtnActive : null]}
              onPress={() => setQualificationMode("score")}
            >
              <Text style={styles.qualModeText}>Score</Text>
            </Pressable>
          </View>
        </View>
        {scopeLabel ? <Text style={styles.scopeHint}>Scope: {scopeLabel}</Text> : null}
        <View style={styles.poolRow}>
          <PoolCard
            title="Sell Pool"
            tone="sell"
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
            sliderLabel={qualificationMode === "score" ? "Sell Score ≤" : "Sell Proximity ≤"}
            sliderValue={sellGate}
            sliderMax={sellGateMax}
            valueSuffix={qualificationMode === "score" ? "" : "%"}
            onChange={qualificationMode === "score" ? setSellScoreThreshold : setSellProxThreshold}
            trackColor="#60a5fa"
            cashFirst
            wide={wideCards}
          />
          <PoolCard
            title="Buy Pool"
            tone="buy"
            helperText={`${qualifiedBuys.length} of ${buyCandidates.length} qualified`}
            cashLine={`CASH ${formatMoney(buyCash, true)}`}
            sliderLabel={qualificationMode === "score" ? "Buy Score ≥" : "Buy Proximity ≤"}
            sliderValue={buyGate}
            sliderMax={buyGateMax}
            valueSuffix={qualificationMode === "score" ? "" : "%"}
            onChange={qualificationMode === "score" ? setBuyScoreThreshold : setBuyProxThreshold}
            trackColor="#fb923c"
            wide={wideCards}
          />
        </View>
        <View style={styles.segRow}>
          <Pressable
            style={[
              styles.pill,
              styles.flexPill,
              pillStyle(listMode === "sell"),
              styles.sellToggle,
              listMode === "sell" ? styles.sellToggleActive : null,
            ]}
            onPress={() => {
              if (listMode === "sell") toggleSortFor("sell");
              else setListMode("sell");
            }}
          >
            <Text style={styles.pillText}>{listButtonLabel("sell")}</Text>
          </Pressable>
          <Pressable
            style={[
              styles.pill,
              styles.flexPill,
              pillStyle(listMode === "buy"),
              styles.buyToggle,
              listMode === "buy" ? styles.buyToggleActive : null,
            ]}
            onPress={() => {
              if (listMode === "buy") toggleSortFor("buy");
              else setListMode("buy");
            }}
          >
            <Text style={styles.pillText}>{listButtonLabel("buy")}</Text>
          </Pressable>
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
  },
  qualModeBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    backgroundColor: colors.surface,
  },
  qualModeBtnActive: {
    backgroundColor: colors.surfaceAlt,
  },
  qualModeText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "700",
  },
  flexPill: { flex: 1, alignItems: "center" },
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
    backgroundColor: "rgba(59,130,246,0.09)",
    borderColor: "rgba(96,165,250,0.35)",
  },
  poolCardBuy: {
    backgroundColor: "rgba(251,146,60,0.09)",
    borderColor: "rgba(251,146,60,0.35)",
  },
  poolHead: { flexDirection: "row", justifyContent: "space-between", gap: spacing.xs, alignItems: "flex-start" },
  poolTitle: { color: colors.textMuted, fontSize: 11, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.4 },
  poolHelper: { flex: 1, textAlign: "right", color: colors.textMuted, fontSize: 10, fontWeight: "600" },
  poolTotal: { color: colors.text, fontSize: 12, fontWeight: "700", marginTop: 4 },
  poolCash: { color: colors.text, fontSize: 12, fontWeight: "700", marginTop: 2 },
  poolTopLine: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: spacing.sm },
  sliderHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginTop: 6 },
  sliderLabel: { color: colors.text, fontSize: 12, fontWeight: "600" },
  sliderValue: { fontSize: 14, fontWeight: "800" },
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
  execHintStrong: { color: colors.text, fontSize: 20, fontWeight: "800", lineHeight: 22 },
  metricsRow: { flexDirection: "row", gap: spacing.sm },
  metricsRowWide: { gap: spacing.xs },
  metric: { gap: 2, minWidth: 0, flex: 1 },
  compactMetrics: { gap: 3 },
  compactLine: { color: colors.text, fontSize: 13, fontWeight: "600" },
  metricLabel: { color: colors.textMuted, fontSize: 10, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.3 },
  metricValue: { color: colors.text, fontSize: 13, fontWeight: "700" },
  metricSub: { color: colors.textMuted, fontSize: 10, fontWeight: "600" },
  sellText: { color: "#93c5fd" },
  buyText: { color: "#fdba74" },
  gainText: { color: colors.buy },
  lossText: { color: colors.sell },
  neutralText: { color: colors.text },
  sellToggle: {
    borderColor: "rgba(96,165,250,0.4)",
    backgroundColor: "rgba(59,130,246,0.08)",
  },
  sellToggleActive: {
    borderColor: "rgba(147,197,253,0.85)",
    backgroundColor: "rgba(59,130,246,0.16)",
  },
  buyToggle: {
    borderColor: "rgba(251,146,60,0.4)",
    backgroundColor: "rgba(251,146,60,0.08)",
  },
  buyToggleActive: {
    borderColor: "rgba(253,186,116,0.85)",
    backgroundColor: "rgba(251,146,60,0.16)",
  },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.lg },
  error: { color: colors.danger, textAlign: "center" },
  retryBtn: { borderWidth: 1, borderColor: colors.border, borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: 8 },
  retryText: { color: colors.text, fontWeight: "600", fontSize: 13 },
  empty: { color: colors.textMuted, textAlign: "center", marginTop: spacing.xl },
});

