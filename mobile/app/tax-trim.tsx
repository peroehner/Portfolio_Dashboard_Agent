import AsyncStorage from "@react-native-async-storage/async-storage";
import Slider from "@react-native-community/slider";
import { useRouter } from "expo-router";
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
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError, api } from "@/lib/api";
import { formatMoney, formatPrice, formatQty } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type {
  TaxTrimLossCandidate,
  TaxTrimOrderBook,
  TaxTrimPricingMode,
  TaxTrimProposal,
  TaxTrimWinnerCandidate,
} from "@/lib/types";

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

function MetricCell({
  label,
  value,
  valueColor,
  align = "left",
}: {
  label: string;
  value: string;
  valueColor?: string;
  align?: "left" | "right" | "center";
}) {
  return (
    <View style={[styles.metricCell, align === "right" && styles.metricRight, align === "center" && styles.metricCenter]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, valueColor ? { color: valueColor } : null]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

function ScoreSlider({
  label,
  value,
  max,
  onChange,
  poolLabel,
  countLabel,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (next: number) => void;
  poolLabel: string;
  countLabel: string;
}) {
  return (
    <View style={styles.sliderBlock}>
      <View style={styles.sliderHeader}>
        <Text style={styles.sliderLabel}>{label}</Text>
        <Text style={styles.sliderValue}>{Math.round(value)}</Text>
      </View>
      <Slider
        style={styles.slider}
        minimumValue={0}
        maximumValue={max}
        step={1}
        value={Math.max(0, Math.min(max, value))}
        onValueChange={(v) => onChange(Math.round(v))}
        minimumTrackTintColor={colors.accent}
        maximumTrackTintColor={colors.surfaceAlt}
        thumbTintColor={colors.accent}
      />
      <Text style={styles.sliderPool}>{poolLabel}</Text>
      <Text style={styles.sliderCount}>{countLabel}</Text>
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
        <MetricCell label="Max Sell" value={formatQty(row.sellQtyMax)} />
        <MetricCell
          label="Max Loss"
          value={formatMoney(row.netLossMax, true)}
          valueColor={colors.sell}
        />
        <MetricCell label="Cash" value={formatMoney(row.cashGenerated, true)} />
        <MetricCell
          label="Score"
          value={String(Math.round(row.lossScore ?? 0))}
          valueColor={qualifies ? colors.sell : colors.textMuted}
          align="right"
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
  const proposed = pick != null && (pick.suggestShares ?? 0) > 0;
  const gain = proposed ? pick.suggestGain : row.netGainsMax;
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
          label="Max Trim"
          value={
            proposed
              ? `${formatQty(pick.suggestShares)} / ${formatQty(row.sellQtyMax)}`
              : formatQty(row.sellQtyMax)
          }
        />
        <MetricCell
          label={proposed ? "Proposed Gain" : "Max Gain"}
          value={formatMoney(gain, true)}
          valueColor={colors.buy}
        />
        <MetricCell
          label="Score"
          value={String(Math.round(row.trimScore ?? 0))}
          valueColor={qualifies ? colors.buy : colors.textMuted}
          align="right"
        />
      </View>
    </Pressable>
  );
}

export default function TaxTrimScreen() {
  const router = useRouter();
  const [pricingMode, setPricingMode] = useState<TaxTrimPricingMode>("current");
  const [lossScoreThreshold, setLossScoreThreshold] = useState(0);
  const [trimScoreThreshold, setTrimScoreThreshold] = useState(0);
  const [matchLossPool, setMatchLossPool] = useState(true);
  const [listMode, setListMode] = useState<ListMode>("tax_loss");
  const [proposal, setProposal] = useState<TaxTrimProposal | null>(null);
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
        /* defaults remain — web prefs unavailable */
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
    [pricingMode, lossScoreThreshold, trimScoreThreshold, matchLossPool],
  );

  useEffect(() => {
    if (!ready) return;
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
  }, [ready, load]);

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
          /* keep working offline */
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
      });
      await persistBook(book);
      const lines = [
        `Tax & Trim Order Book · ${book.capturedAt}`,
        `Pricing: ${book.settings.pricingMode} · Match Loss: ${book.settings.matchLossPool ? "on" : "off"}`,
        `Loss ≥ ${book.settings.lossScoreThreshold} · Trim ≥ ${book.settings.trimScoreThreshold}`,
        `Orders: ${book.summary.orderCount} · Loss pool ${formatMoney(book.summary.lossPool)} · Offset ${formatMoney(book.summary.offsetGain)}`,
        "",
        ...book.orders.map((o) => {
          const impact =
            o.kind === "tax_loss"
              ? `loss ${formatMoney(o.estLoss)}`
              : `gain ${formatMoney(o.estGain)}`;
          return `${o.side.toUpperCase()} ${o.symbol} ${formatQty(o.shares)} @ ${formatPrice(o.limit)} (${o.kind}) · ${impact}`;
        }),
        "",
        "JSON:",
        JSON.stringify(book, null, 2),
      ];
      await Share.share({
        message: lines.join("\n"),
        title: "Tax & Trim Order Book",
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
            <Text style={styles.matchLabel}>Match Loss</Text>
            <Switch
              value={matchLossPool}
              onValueChange={setMatchLossPool}
              trackColor={{ false: colors.surfaceAlt, true: colors.accentMuted }}
              thumbColor={matchLossPool ? colors.accent : colors.textMuted}
            />
          </View>
        </View>

        <View style={styles.poolTotals}>
          <View style={styles.poolBox}>
            <Text style={styles.poolBoxLabel}>Loss pool</Text>
            <Text style={[styles.poolBoxValue, { color: colors.sell }]}>
              {formatMoney(proposal?.lossPool, true)}
            </Text>
            <Text style={styles.poolBoxSub}>
              {lossSelected} of {lossTotal} qualified
            </Text>
          </View>
          <View style={styles.poolBox}>
            <Text style={styles.poolBoxLabel}>Trim pool</Text>
            <Text style={[styles.poolBoxValue, { color: colors.buy }]}>
              {formatMoney(proposal?.selectedTrimPool, true)}
            </Text>
            <Text style={styles.poolBoxSub}>
              {trimSelected} of {trimTotal} qualified
              {matchLossPool
                ? ` · matched ${formatMoney(proposal?.offsetGain, true)}`
                : ` · offset ${formatMoney(proposal?.offsetGain, true)}`}
            </Text>
          </View>
        </View>

        <ScoreSlider
          label="Loss-score ≥"
          value={lossScoreThreshold}
          max={LOSS_SCORE_MAX}
          onChange={setLossScoreThreshold}
          poolLabel={`Loss pool ${formatMoney(proposal?.lossPool, true)}`}
          countLabel={`${lossSelected} of ${lossTotal} qualified`}
        />
        <ScoreSlider
          label="Trim-score ≥"
          value={trimScoreThreshold}
          max={TRIM_SCORE_MAX}
          onChange={setTrimScoreThreshold}
          poolLabel={`Trim pool ${formatMoney(proposal?.selectedTrimPool, true)}`}
          countLabel={`${trimSelected} of ${trimTotal} qualified`}
        />

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

        <View style={styles.actionRow}>
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
      ) : (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => void load({ soft: true })}
              tintColor={colors.accent}
            />
          }
        >
          {listMode === "tax_loss"
            ? lossCandidates.map((row) => {
                const qualifies = (row.lossScore ?? 0) >= lossScoreThreshold;
                return (
                  <LossCard
                    key={row.symbol}
                    row={row}
                    qualifies={qualifies}
                    onPress={() =>
                      router.push(`/symbol/${encodeURIComponent(row.symbol)}`)
                    }
                  />
                );
              })
            : trimCandidates.map((row) => {
                const qualifies = (row.trimScore ?? 0) >= trimScoreThreshold;
                return (
                  <TrimCard
                    key={row.symbol}
                    row={row}
                    qualifies={qualifies}
                    pick={pickBySymbol.get(row.symbol)}
                    onPress={() =>
                      router.push(`/symbol/${encodeURIComponent(row.symbol)}`)
                    }
                  />
                );
              })}
          {(listMode === "tax_loss" ? lossCandidates : trimCandidates).length === 0 ? (
            <Text style={styles.empty}>No candidates for this pricing mode.</Text>
          ) : null}
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
    marginLeft: "auto",
  },
  matchLabel: { color: colors.textMuted, fontSize: 12, fontWeight: "600" },
  poolTotals: { flexDirection: "row", gap: spacing.sm },
  poolBox: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 2,
  },
  poolBoxLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  poolBoxValue: { color: colors.text, fontSize: 18, fontWeight: "700" },
  poolBoxSub: { color: colors.textMuted, fontSize: 11 },
  sliderBlock: { gap: 2 },
  sliderHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
  },
  sliderLabel: { color: colors.text, fontSize: 13, fontWeight: "600" },
  sliderValue: { color: colors.accent, fontSize: 15, fontWeight: "700" },
  slider: { width: "100%", height: 36 },
  sliderPool: { color: colors.text, fontSize: 12, fontWeight: "600" },
  sliderCount: { color: colors.textMuted, fontSize: 11 },
  actionRow: { flexDirection: "row", gap: spacing.sm },
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
    flex: 1,
    alignItems: "center",
  },
  actionDisabled: { opacity: 0.45 },
  actionText: { color: colors.text, fontWeight: "600", fontSize: 13 },
  actionPrimaryText: { color: colors.accent, fontWeight: "700", fontSize: 13 },
  status: { color: colors.textMuted, fontSize: 12 },
  list: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing.xl * 2 },
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
  metricCell: { flex: 1, gap: 2 },
  metricRight: { alignItems: "flex-end" },
  metricCenter: { alignItems: "center" },
  metricLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  metricValue: { color: colors.text, fontSize: 14, fontWeight: "700" },
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
