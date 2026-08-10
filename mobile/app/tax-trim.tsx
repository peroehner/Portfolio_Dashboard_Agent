import AsyncStorage from "@react-native-async-storage/async-storage";
import Slider from "@react-native-community/slider";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Switch,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError, api } from "@/lib/api";
import { parseSymbolFilter } from "@/lib/filters";
import { formatMoney, formatPrice, formatQty } from "@/lib/format";
import { orderBookStamp, orderBookToCsv } from "@/lib/orderBookCsv";
import { colors, radii, spacing } from "@/lib/theme";
import type {
  TaxTrimLossCandidate,
  TaxTrimOrderBook,
  TaxTrimPricingMode,
  TaxTrimProposal,
  TaxTrimWinnerCandidate,
} from "@/lib/types";
import { usePersistedSymbolFilter } from "@/lib/usePersistedSymbolFilter";
import { useSymbolFilterMatch } from "@/lib/useSymbolFilterMatch";

const STORAGE_KEY = "pda.taxTrim.lastBook";
const LOSS_SCORE_MAX = 50;
const TRIM_SCORE_MAX = 65;

type ListMode = "tax_loss" | "winner_trim";

type SavedControls = {
  pricingMode: TaxTrimPricingMode;
  lossScoreThreshold: number;
  trimScoreThreshold: number;
  matchLossPool: boolean;
  listMode?: ListMode;
};

function pillStyle(active: boolean) {
  return active
    ? { backgroundColor: colors.surfaceAlt, borderColor: colors.accent }
    : { backgroundColor: colors.surface, borderColor: colors.border };
}

function qtyLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || !Number.isFinite(Number(value))) return "—";
  const n = Number(value);
  return n % 1 === 0 ? String(n) : n.toFixed(2);
}

/** proposal (of held) — or proposal (of planCap / held) when a sell-plan cap exists. */
function formatProposedQty(
  proposed: number | null | undefined,
  held: number | null | undefined,
  planCap: number | null | undefined,
): string {
  const p = qtyLabel(proposed ?? 0);
  const h = qtyLabel(held);
  if (planCap != null && Number.isFinite(Number(planCap)) && Number(planCap) > 0) {
    return `${p} (of ${qtyLabel(planCap)} / ${h})`;
  }
  return `${p} (of ${h})`;
}

function MetricCell({
  label,
  value,
  valueColor,
  flex = 1,
}: {
  label: string;
  value: string;
  valueColor?: string;
  flex?: number;
}) {
  return (
    <View style={[styles.metricCell, { flex }]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, valueColor ? { color: valueColor } : null]} numberOfLines={2}>
        {value}
      </Text>
    </View>
  );
}

function PoolSliderCard({
  title,
  primaryLabel,
  primaryAmount,
  primaryColor,
  cashAmount,
  helperText,
  scoreLabel,
  scoreValue,
  scoreMax,
  onScoreChange,
  trackColor,
}: {
  title: string;
  primaryLabel: string;
  primaryAmount: string;
  primaryColor: string;
  cashAmount: string;
  helperText?: string | null;
  scoreLabel: string;
  scoreValue: number;
  scoreMax: number;
  onScoreChange: (next: number) => void;
  trackColor: string;
}) {
  return (
    <View style={styles.poolCard}>
      <View style={styles.poolCardHead}>
        <Text style={styles.poolCardTitle}>{title}</Text>
        {helperText ? (
          <Text style={styles.poolCardHelper} numberOfLines={2}>
            {helperText}
          </Text>
        ) : null}
      </View>
      <View style={styles.poolTotalsRow}>
        <View style={styles.poolTotalCell}>
          <Text style={styles.poolTotalLabel}>{primaryLabel}</Text>
          <Text style={[styles.poolCardAmount, { color: primaryColor }]} numberOfLines={1}>
            {primaryAmount}
          </Text>
        </View>
        <View style={styles.poolTotalCell}>
          <Text style={styles.poolTotalLabel}>Cash</Text>
          <Text style={[styles.poolCardAmount, styles.poolCashAmount]} numberOfLines={1}>
            {cashAmount}
          </Text>
        </View>
      </View>
      <View style={styles.poolSliderHeader}>
        <Text style={styles.poolSliderLabel}>{scoreLabel}</Text>
        <Text style={[styles.poolSliderValue, { color: trackColor }]}>{Math.round(scoreValue)}</Text>
      </View>
      <Slider
        style={styles.slider}
        minimumValue={0}
        maximumValue={scoreMax}
        step={1}
        value={Math.max(0, Math.min(scoreMax, scoreValue))}
        onValueChange={(v) => onScoreChange(Math.round(v))}
        minimumTrackTintColor={trackColor}
        maximumTrackTintColor={colors.surfaceAlt}
        thumbTintColor={trackColor}
      />
    </View>
  );
}

function LossCard({
  row,
  qualifies,
  onPress,
}: {
  row: TaxTrimLossCandidate;
  qualifies: boolean;
  onPress: () => void;
}) {
  const proposed = qualifies ? (row.sellQtyMax ?? 0) : 0;
  return (
    <Pressable
      style={[styles.card, qualifies ? styles.cardLossQualified : styles.cardMuted]}
      onPress={onPress}
    >
      <View style={styles.cardTop}>
        <View style={styles.symbolCol}>
          <Text style={styles.symbol}>{row.symbol}</Text>
          {qualifies ? <Text style={styles.badgeLoss}>QUALIFIED</Text> : null}
        </View>
        <Text style={styles.execHint}>
          @ {row.execSource === "threshold" ? "Thr" : "Cur"} {formatPrice(row.execPrice)}
        </Text>
      </View>
      <View style={styles.metricsRow}>
        <MetricCell
          label="Proposed Sell"
          value={formatProposedQty(
            proposed,
            row.held,
            row.hasSellPlan ? row.sellPlanCap : null,
          )}
          flex={1.4}
        />
        <MetricCell
          label={qualifies ? "Real Loss" : "Max Loss"}
          value={formatMoney(row.netLossMax, true)}
          valueColor={colors.sell}
        />
        <MetricCell label="Cash" value={formatMoney(row.cashGenerated, true)} />
        <MetricCell
          label="Score"
          value={String(Math.round(row.lossScore ?? 0))}
          valueColor={qualifies ? colors.sell : colors.textMuted}
          flex={0.7}
        />
      </View>
    </Pressable>
  );
}

function TrimCard({
  row,
  qualifies,
  pick,
  onPress,
}: {
  row: TaxTrimWinnerCandidate;
  qualifies: boolean;
  pick?: TaxTrimWinnerCandidate;
  onPress: () => void;
}) {
  const proposedShares =
    pick != null && (pick.suggestShares ?? 0) > 0 ? (pick.suggestShares ?? 0) : 0;
  const proposed = proposedShares > 0;
  const maxGainTxt = formatMoney(row.netGainsMax, true);
  const gainLabel = proposed ? "Prop Gain (Max)" : "Max Gain";
  const gainValue = proposed
    ? `${formatMoney(pick?.suggestGain, true)} (${maxGainTxt})`
    : maxGainTxt;
  const cashTxt = proposed
    ? formatMoney(pick?.suggestCash, true)
    : formatMoney(row.cashGenerated, true);
  return (
    <Pressable
      style={[styles.card, qualifies ? styles.cardTrimQualified : styles.cardMuted]}
      onPress={onPress}
    >
      <View style={styles.cardTop}>
        <View style={styles.symbolCol}>
          <Text style={styles.symbol}>{row.symbol}</Text>
          {proposed ? (
            <Text style={styles.badgeProposed}>PROPOSED</Text>
          ) : qualifies ? (
            <Text style={styles.badgeTrim}>QUALIFIED</Text>
          ) : null}
        </View>
        <Text style={styles.execHint}>
          @ {row.execSource === "threshold" ? "Thr" : "Cur"} {formatPrice(row.execPrice)}
        </Text>
      </View>
      <View style={styles.metricsRow}>
        <MetricCell
          label="Proposed Trim"
          value={formatProposedQty(
            proposedShares,
            row.held,
            row.hasSellPlan ? row.sellPlanCap : null,
          )}
          flex={1.35}
        />
        <MetricCell
          label={gainLabel}
          value={gainValue}
          valueColor={colors.buy}
          flex={1.35}
        />
        <MetricCell label="Cash" value={cashTxt} />
        <MetricCell
          label="Score"
          value={String(Math.round(row.trimScore ?? 0))}
          valueColor={qualifies ? colors.buy : colors.textMuted}
          flex={0.65}
        />
      </View>
    </Pressable>
  );
}

export default function TaxTrimScreen() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const landscape = width > height;
  const { mode: modeParam } = useLocalSearchParams<{ mode?: string }>();
  const portfolioMode =
    modeParam === "holdings" || modeParam === "watch" || modeParam === "all"
      ? modeParam
      : "all";
  const { filter, hydrated: filterHydrated } = usePersistedSymbolFilter();
  const matchesSymbol = useSymbolFilterMatch(filter);
  const [pricingMode, setPricingMode] = useState<TaxTrimPricingMode>("current");
  const [lossScoreThreshold, setLossScoreThreshold] = useState(0);
  const [trimScoreThreshold, setTrimScoreThreshold] = useState(0);
  const [matchLossPool, setMatchLossPool] = useState(true);
  const [listMode, setListMode] = useState<ListMode>("tax_loss");
  const [proposal, setProposal] = useState<TaxTrimProposal | null>(null);
  const [scopeSymbols, setScopeSymbols] = useState<string[] | null>(null);
  const [scopeReady, setScopeReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [canRestore, setCanRestore] = useState(false);
  const [ready, setReady] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prefsSyncRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasProposal = useRef(false);
  const skipNextPrefsSync = useRef(true);

  const filterActive = Boolean(filter.trim());
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
        const holdingBySymbol = new Map(
          (holdings.holdings ?? []).map((h) => [h.symbol.toUpperCase(), h]),
        );
        const symbols = (portfolio.symbols ?? [])
          .map((row) => row.symbol.toUpperCase())
          .filter((symbol) => {
            if (!matchesSymbol(symbol)) return false;
            const qty = holdingBySymbol.get(symbol)?.quantity ?? 0;
            if (portfolioMode === "holdings") return qty > 0;
            if (portfolioMode === "watch") return !(qty > 0);
            return true;
          });
        // No filter + All → unscoped (full portfolio holdings on server).
        if (!filterActive && portfolioMode === "all") {
          setScopeSymbols(null);
        } else {
          setScopeSymbols(symbols);
        }
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

  useEffect(() => {
    void (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) setCanRestore(true);
      } catch {
        /* ignore */
      }
      try {
        const prefs = await api.preferences();
        const tt = prefs.taxTrim;
        if (tt) {
          if (tt.pricingMode === "threshold" || tt.pricingMode === "current") {
            setPricingMode(tt.pricingMode);
          }
          if (typeof tt.lossScoreThreshold === "number" && Number.isFinite(tt.lossScoreThreshold)) {
            setLossScoreThreshold(Math.max(0, tt.lossScoreThreshold));
          }
          if (typeof tt.trimScoreThreshold === "number" && Number.isFinite(tt.trimScoreThreshold)) {
            setTrimScoreThreshold(Math.max(0, tt.trimScoreThreshold));
          }
          if (typeof tt.matchLossPool === "boolean") {
            setMatchLossPool(tt.matchLossPool);
          }
        }
      } catch {
        /* defaults remain */
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const load = useCallback(
    async (opts?: { soft?: boolean }) => {
      if (!opts?.soft) setLoading(true);
      else setRefreshing(true);
      setError(null);
      try {
        const next = await api.taxTrimProposal({
          pricingMode,
          lossScoreThreshold,
          trimScoreThreshold,
          matchLossPool,
          ...(scopeSymbols != null ? { selectedSymbols: scopeSymbols } : {}),
        });
        setProposal(next);
        hasProposal.current = true;
      } catch (err) {
        const message =
          err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed to load";
        setError(message);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [pricingMode, lossScoreThreshold, trimScoreThreshold, matchLossPool, scopeSymbols],
  );

  useEffect(() => {
    if (!ready || !scopeReady) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(
      () => {
        void load({ soft: hasProposal.current });
      },
      hasProposal.current ? 220 : 0,
    );
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [ready, scopeReady, load]);

  useEffect(() => {
    if (!ready) return;
    if (skipNextPrefsSync.current) {
      skipNextPrefsSync.current = false;
      return;
    }
    if (prefsSyncRef.current) clearTimeout(prefsSyncRef.current);
    prefsSyncRef.current = setTimeout(() => {
      void api
        .updatePreferences({
          taxTrim: {
            pricingMode,
            lossScoreThreshold,
            trimScoreThreshold,
            matchLossPool,
          },
        })
        .catch(() => {
          /* offline ok */
        });
    }, 500);
    return () => {
      if (prefsSyncRef.current) clearTimeout(prefsSyncRef.current);
    };
  }, [ready, pricingMode, lossScoreThreshold, trimScoreThreshold, matchLossPool]);

  const pickBySymbol = useMemo(() => {
    const map = new Map<string, TaxTrimWinnerCandidate>();
    for (const pick of proposal?.picks ?? []) {
      map.set(pick.symbol, pick);
    }
    return map;
  }, [proposal?.picks]);

  const lossCandidates = useMemo(() => {
    const rows = [...(proposal?.lossSells?.candidates ?? [])];
    rows.sort((a, b) => {
      const aq = (a.lossScore ?? 0) >= lossScoreThreshold ? 1 : 0;
      const bq = (b.lossScore ?? 0) >= lossScoreThreshold ? 1 : 0;
      if (aq !== bq) return bq - aq;
      return (b.lossScore ?? 0) - (a.lossScore ?? 0);
    });
    return rows;
  }, [proposal?.lossSells?.candidates, lossScoreThreshold]);

  const trimCandidates = useMemo(() => {
    const rows = [...(proposal?.winnerTrims?.candidates ?? [])];
    rows.sort((a, b) => {
      const aq = (a.trimScore ?? 0) >= trimScoreThreshold ? 1 : 0;
      const bq = (b.trimScore ?? 0) >= trimScoreThreshold ? 1 : 0;
      if (aq !== bq) return bq - aq;
      return (b.trimScore ?? 0) - (a.trimScore ?? 0);
    });
    return rows;
  }, [proposal?.winnerTrims?.candidates, trimScoreThreshold]);

  async function persistBook(book: TaxTrimOrderBook) {
    const payload = {
      ...book,
      settings: {
        ...book.settings,
        listMode,
      },
    };
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    setCanRestore(true);
  }

  async function onCapture() {
    setCapturing(true);
    setStatus(null);
    try {
      const book = await api.taxTrimOrderBook({
        pricingMode,
        lossScoreThreshold,
        trimScoreThreshold,
        matchLossPool,
        ...(scopeSymbols != null ? { selectedSymbols: scopeSymbols } : {}),
      });
      await persistBook(book);
      const stamp = orderBookStamp(book.capturedAt);
      const csv = orderBookToCsv(book);
      await Share.share({
        message: csv,
        title: `PDA-OrderBook-${stamp}.csv`,
      });
      setStatus(`Captured ${book.summary.orderCount} orders`);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Capture failed";
      setStatus(message);
    } finally {
      setCapturing(false);
    }
  }

  async function onRestore() {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_KEY);
      if (!raw) {
        setStatus("No saved order book");
        return;
      }
      const parsed = JSON.parse(raw) as TaxTrimOrderBook & { settings?: SavedControls };
      const settings = parsed.settings;
      if (!settings) {
        setStatus("Saved book has no settings");
        return;
      }
      if (settings.pricingMode === "threshold" || settings.pricingMode === "current") {
        setPricingMode(settings.pricingMode);
      }
      if (typeof settings.lossScoreThreshold === "number") {
        setLossScoreThreshold(settings.lossScoreThreshold);
      }
      if (typeof settings.trimScoreThreshold === "number") {
        setTrimScoreThreshold(settings.trimScoreThreshold);
      }
      if (typeof settings.matchLossPool === "boolean") {
        setMatchLossPool(settings.matchLossPool);
      }
      const savedList = (settings as SavedControls).listMode;
      if (savedList === "tax_loss" || savedList === "winner_trim") {
        setListMode(savedList);
      }
      setStatus(`Restored settings from ${parsed.capturedAt ?? "last capture"}`);
    } catch {
      setStatus("Could not restore last book");
    }
  }

  const lossSelected = proposal?.lossSells?.selectedCount ?? 0;
  const lossTotal = proposal?.lossSells?.candidateCount ?? 0;
  const trimSelected = proposal?.winnerTrims?.selectedCount ?? 0;
  const trimTotal = proposal?.winnerTrims?.candidateCount ?? 0;

  const lossPoolCash = useMemo(() => {
    return (proposal?.lossSells?.candidates ?? [])
      .filter((row) => (row.lossScore ?? 0) >= lossScoreThreshold)
      .reduce((sum, row) => sum + Math.max(0, Number(row.cashGenerated) || 0), 0);
  }, [proposal?.lossSells?.candidates, lossScoreThreshold]);

  const trimPoolCash = useMemo(() => {
    return (proposal?.picks ?? []).reduce(
      (sum, row) => sum + Math.max(0, Number(row.suggestCash) || 0),
      0,
    );
  }, [proposal?.picks]);

  const refreshControl = (
    <RefreshControl
      refreshing={refreshing}
      onRefresh={() => void load({ soft: true })}
      tintColor={colors.accent}
    />
  );

  function renderLossList() {
    if (!lossCandidates.length) {
      return <Text style={styles.empty}>No tax-loss candidates.</Text>;
    }
    return lossCandidates.map((row) => {
      const qualifies = (row.lossScore ?? 0) >= lossScoreThreshold;
      return (
        <LossCard
          key={row.symbol}
          row={row}
          qualifies={qualifies}
          onPress={() => router.push(`/symbol/${encodeURIComponent(row.symbol)}`)}
        />
      );
    });
  }

  function renderTrimList() {
    if (!trimCandidates.length) {
      return <Text style={styles.empty}>No winner-trim candidates.</Text>;
    }
    return trimCandidates.map((row) => {
      const qualifies = (row.trimScore ?? 0) >= trimScoreThreshold;
      return (
        <TrimCard
          key={row.symbol}
          row={row}
          qualifies={qualifies}
          pick={pickBySymbol.get(row.symbol)}
          onPress={() => router.push(`/symbol/${encodeURIComponent(row.symbol)}`)}
        />
      );
    });
  }

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.controls}>
        <View style={styles.segRow}>
          <Pressable
            style={[styles.pill, pillStyle(pricingMode === "current")]}
            onPress={() => setPricingMode("current")}
          >
            <Text style={styles.pillText}>Current</Text>
          </Pressable>
          <Pressable
            style={[styles.pill, pillStyle(pricingMode === "threshold")]}
            onPress={() => setPricingMode("threshold")}
          >
            <Text style={styles.pillText}>Threshold</Text>
          </Pressable>
          <View style={styles.matchRow}>
            <Text style={styles.matchLabel}>Match Losses</Text>
            <Switch
              value={matchLossPool}
              onValueChange={setMatchLossPool}
              trackColor={{ false: colors.surfaceAlt, true: colors.accentMuted }}
              thumbColor={matchLossPool ? colors.accent : colors.textMuted}
            />
          </View>
          <View style={styles.topActions}>
            <Pressable
              style={[styles.actionBtn, styles.actionPrimary, capturing && styles.actionDisabled]}
              onPress={() => void onCapture()}
              disabled={capturing}
            >
              <Text style={styles.actionPrimaryText}>
                {capturing ? "Capturing…" : "Capture"}
              </Text>
            </Pressable>
            <Pressable
              style={[styles.actionBtn, !canRestore && styles.actionDisabled]}
              onPress={() => void onRestore()}
              disabled={!canRestore}
            >
              <Text style={styles.actionText}>Restore</Text>
            </Pressable>
          </View>
        </View>

        {scopeLabel ? <Text style={styles.scopeHint}>Scope: {scopeLabel}</Text> : null}

        <View style={styles.poolRow}>
          <PoolSliderCard
            title="Loss pool"
            primaryLabel="Loss"
            primaryAmount={formatMoney(proposal?.lossPool, true)}
            primaryColor={colors.sell}
            cashAmount={formatMoney(lossPoolCash, true)}
            helperText={`${lossSelected} of ${lossTotal} qualified`}
            scoreLabel="Loss-score ≥"
            scoreValue={lossScoreThreshold}
            scoreMax={LOSS_SCORE_MAX}
            onScoreChange={setLossScoreThreshold}
            trackColor={colors.sell}
          />
          <PoolSliderCard
            title="Trim pool"
            primaryLabel="Gains"
            primaryAmount={formatMoney(proposal?.offsetGain, true)}
            primaryColor={colors.buy}
            cashAmount={formatMoney(trimPoolCash, true)}
            helperText={`${trimSelected} of ${trimTotal} qualified${
              matchLossPool ? " · Match Losses" : " · Full trim capacity"
            }`}
            scoreLabel="Trim-score ≥"
            scoreValue={trimScoreThreshold}
            scoreMax={TRIM_SCORE_MAX}
            onScoreChange={setTrimScoreThreshold}
            trackColor={colors.buy}
          />
        </View>

        {!landscape ? (
          <View style={styles.segRow}>
            <Pressable
              style={[styles.pill, styles.flexPill, pillStyle(listMode === "tax_loss")]}
              onPress={() => setListMode("tax_loss")}
            >
              <Text style={styles.pillText}>Tax-loss</Text>
            </Pressable>
            <Pressable
              style={[styles.pill, styles.flexPill, pillStyle(listMode === "winner_trim")]}
              onPress={() => setListMode("winner_trim")}
            >
              <Text style={styles.pillText}>Winner-trim</Text>
            </Pressable>
          </View>
        ) : null}

        {status ? <Text style={styles.status}>{status}</Text> : null}
      </View>

      {loading && !proposal ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.accent} size="large" />
        </View>
      ) : error && !proposal ? (
        <View style={styles.centered}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.actionBtn} onPress={() => void load()}>
            <Text style={styles.actionText}>Retry</Text>
          </Pressable>
        </View>
      ) : landscape ? (
        <View style={styles.dualLists}>
          <View style={styles.dualCol}>
            <Text style={styles.dualColTitle}>Tax-loss</Text>
            <ScrollView contentContainerStyle={styles.list} refreshControl={refreshControl}>
              {renderLossList()}
            </ScrollView>
          </View>
          <View style={styles.dualCol}>
            <Text style={styles.dualColTitle}>Winner-trim</Text>
            <ScrollView contentContainerStyle={styles.list} refreshControl={refreshControl}>
              {renderTrimList()}
            </ScrollView>
          </View>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.list} refreshControl={refreshControl}>
          {listMode === "tax_loss" ? renderLossList() : renderTrimList()}
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
  segRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  pill: {
    borderWidth: 1,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
  },
  flexPill: { flex: 1, alignItems: "center" },
  pillText: { color: colors.text, fontWeight: "600", fontSize: 13 },
  matchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  matchLabel: { color: colors.textMuted, fontSize: 12, fontWeight: "600" },
  topActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginLeft: "auto",
  },
  scopeHint: { color: colors.textMuted, fontSize: 12, fontWeight: "600" },
  poolRow: { flexDirection: "row", gap: spacing.sm },
  poolCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    paddingHorizontal: spacing.sm,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xs,
    gap: 2,
  },
  poolCardTitle: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  poolCardHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  poolCardHelper: {
    flex: 1,
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "600",
    textAlign: "right",
    lineHeight: 13,
  },
  poolTotalsRow: { flexDirection: "row", gap: spacing.sm, marginTop: 2 },
  poolTotalCell: { flex: 1, minWidth: 0, gap: 1 },
  poolTotalLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  poolCardAmount: { fontSize: 16, fontWeight: "800" },
  poolCashAmount: { color: colors.text },
  poolSliderHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    marginTop: 4,
  },
  poolSliderLabel: { color: colors.text, fontSize: 12, fontWeight: "600" },
  poolSliderValue: { fontSize: 14, fontWeight: "800" },
  slider: { width: "100%", height: 32 },
  actionBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
  },
  actionPrimary: {
    backgroundColor: colors.accentMuted,
    borderColor: colors.accent,
    alignItems: "center",
  },
  actionDisabled: { opacity: 0.45 },
  actionText: { color: colors.text, fontWeight: "600", fontSize: 13 },
  actionPrimaryText: { color: colors.accent, fontWeight: "700", fontSize: 13 },
  status: { color: colors.textMuted, fontSize: 12 },
  dualLists: { flex: 1, flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.sm },
  dualCol: { flex: 1, minWidth: 0 },
  dualColTitle: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.4,
    paddingHorizontal: spacing.sm,
    paddingTop: spacing.sm,
    paddingBottom: 4,
  },
  list: { padding: spacing.md, gap: spacing.sm, paddingBottom: spacing.xl * 2 },
  card: {
    borderWidth: 1,
    borderRadius: radii.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  cardLossQualified: {
    backgroundColor: "rgba(248,113,113,0.12)",
    borderColor: "rgba(248,113,113,0.45)",
  },
  cardTrimQualified: {
    backgroundColor: "rgba(74,222,128,0.12)",
    borderColor: "rgba(74,222,128,0.45)",
  },
  cardMuted: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    opacity: 0.55,
  },
  cardTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: spacing.sm,
  },
  symbolCol: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
  symbol: { color: colors.text, fontSize: 16, fontWeight: "700" },
  badgeLoss: {
    color: colors.sell,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
    backgroundColor: "rgba(248,113,113,0.2)",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  badgeTrim: {
    color: colors.buy,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
    backgroundColor: "rgba(74,222,128,0.2)",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  badgeProposed: {
    color: "#052e16",
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
    backgroundColor: colors.buy,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  execHint: { color: colors.textMuted, fontSize: 11 },
  metricsRow: { flexDirection: "row", gap: spacing.sm },
  metricCell: { gap: 2, minWidth: 0 },
  metricLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  metricValue: { color: colors.text, fontSize: 13, fontWeight: "700" },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    padding: spacing.lg,
  },
  errorText: { color: colors.danger, textAlign: "center" },
  empty: { color: colors.textMuted, textAlign: "center", marginTop: spacing.xl },
});
