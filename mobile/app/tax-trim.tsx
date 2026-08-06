import AsyncStorage from "@react-native-async-storage/async-storage";
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
import { formatMoney, formatPct, formatPrice, formatQty } from "@/lib/format";
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

function ScoreStepper({
  label,
  value,
  max,
  onChange,
  summary,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (next: number) => void;
  summary: string;
}) {
  return (
    <View style={styles.stepperBlock}>
      <View style={styles.stepperHeader}>
        <Text style={styles.stepperLabel}>{label}</Text>
        <Text style={styles.stepperValue}>{Math.round(value)}</Text>
      </View>
      <View style={styles.stepperRow}>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onChange(Math.max(0, value - 5))}
          hitSlop={6}
        >
          <Text style={styles.stepBtnText}>−5</Text>
        </Pressable>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onChange(Math.max(0, value - 1))}
          hitSlop={6}
        >
          <Text style={styles.stepBtnText}>−</Text>
        </Pressable>
        <View style={styles.stepTrack}>
          <View
            style={[
              styles.stepFill,
              { width: `${Math.max(0, Math.min(100, (value / max) * 100))}%` },
            ]}
          />
        </View>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onChange(Math.min(max, value + 1))}
          hitSlop={6}
        >
          <Text style={styles.stepBtnText}>+</Text>
        </Pressable>
        <Pressable
          style={styles.stepBtn}
          onPress={() => onChange(Math.min(max, value + 5))}
          hitSlop={6}
        >
          <Text style={styles.stepBtnText}>+5</Text>
        </Pressable>
      </View>
      <Text style={styles.stepperSummary}>{summary}</Text>
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
      style={[styles.card, !qualifies && styles.cardMuted]}
      onPress={onPress}
    >
      <View style={styles.cardTop}>
        <Text style={styles.symbol}>{row.symbol}</Text>
        <Text style={styles.scoreChip}>L {Math.round(row.lossScore ?? 0)}</Text>
      </View>
      <Text style={styles.meta}>
        {(row.saiAction || "—").toUpperCase()}
        {row.saiConfidence && row.saiConfidence !== "—"
          ? ` · ${String(row.saiConfidence).toUpperCase()}`
          : ""}
        {" · "}
        @ {row.execSource === "threshold" ? "Threshold" : "Current"}{" "}
        {formatPrice(row.execPrice)}
      </Text>
      <Text style={styles.meta}>
        Sell {formatQty(row.sellQtyMax)} · Loss {formatMoney(row.netLossMax, true)} · Cash{" "}
        {formatMoney(row.cashGenerated, true)}
      </Text>
      <Text style={styles.meta}>
        Residual {formatPct(row.residualLossPct)} · 1YT {formatPct(row.analystUpsidePct)}
      </Text>
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
  return (
    <Pressable
      style={[styles.card, !qualifies && styles.cardMuted]}
      onPress={onPress}
    >
      <View style={styles.cardTop}>
        <Text style={styles.symbol}>{row.symbol}</Text>
        <Text style={styles.scoreChip}>T {Math.round(row.trimScore ?? 0)}</Text>
      </View>
      <Text style={styles.meta}>
        {(row.saiAction || "—").toUpperCase()}
        {row.saiConfidence && row.saiConfidence !== "—"
          ? ` · ${String(row.saiConfidence).toUpperCase()}`
          : ""}
        {" · "}
        @ {row.execSource === "threshold" ? "Threshold" : "Current"}{" "}
        {formatPrice(row.execPrice)}
      </Text>
      <Text style={styles.meta}>
        {pick
          ? `Propose ${formatQty(pick.suggestShares)} · Gain ${formatMoney(pick.suggestGain, true)}`
          : `Max trim ${formatQty(row.sellQtyMax)} · Gain ${formatMoney(row.netGainsMax, true)}`}
        {" · "}Cash {formatMoney(pick?.suggestCash ?? row.cashGenerated, true)}
      </Text>
      <Text style={styles.meta}>
        Headroom {formatPct(row.headroomPct)} · Wt {formatPct(row.weightPct)}
      </Text>
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
  const hasProposal = useRef(false);

  useEffect(() => {
    void (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw) as { settings?: SavedControls } & SavedControls;
          const settings = parsed.settings ?? parsed;
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
          if (settings.listMode === "tax_loss" || settings.listMode === "winner_trim") {
            setListMode(settings.listMode);
          }
          setCanRestore(true);
        }
      } catch {
        /* ignore corrupt restore */
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

  const pickBySymbol = useMemo(() => {
    const map = new Map<string, TaxTrimWinnerCandidate>();
    for (const pick of proposal?.picks ?? []) {
      map.set(pick.symbol, pick);
    }
    return map;
  }, [proposal?.picks]);

  const lossCandidates = proposal?.lossSells?.candidates ?? [];
  const trimCandidates = proposal?.winnerTrims?.candidates ?? [];

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

        <Text style={styles.poolReadout}>
          Loss {formatMoney(proposal?.lossPool, true)}
          {" · "}Trim {formatMoney(proposal?.selectedTrimPool, true)}
          {matchLossPool
            ? ` · Matched ${formatMoney(proposal?.offsetGain, true)}`
            : ` · Offset ${formatMoney(proposal?.offsetGain, true)}`}
        </Text>

        <ScoreStepper
          label="Loss-score ≥"
          value={lossScoreThreshold}
          max={LOSS_SCORE_MAX}
          onChange={setLossScoreThreshold}
          summary={`${proposal?.lossSells?.selectedCount ?? 0} selected / ${proposal?.lossSells?.candidateCount ?? 0} candidates`}
        />
        <ScoreStepper
          label="Trim-score ≥"
          value={trimScoreThreshold}
          max={TRIM_SCORE_MAX}
          onChange={setTrimScoreThreshold}
          summary={`${proposal?.winnerTrims?.selectedCount ?? 0} selected / ${proposal?.winnerTrims?.candidateCount ?? 0} candidates`}
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
  poolReadout: { color: colors.textMuted, fontSize: 12 },
  stepperBlock: { gap: 4 },
  stepperHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
  },
  stepperLabel: { color: colors.text, fontSize: 13, fontWeight: "600" },
  stepperValue: { color: colors.accent, fontSize: 14, fontWeight: "700" },
  stepperRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  stepBtn: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: 8,
    paddingVertical: 4,
    minWidth: 36,
    alignItems: "center",
  },
  stepBtnText: { color: colors.text, fontWeight: "700", fontSize: 12 },
  stepTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceAlt,
    overflow: "hidden",
  },
  stepFill: { height: "100%", backgroundColor: colors.accent },
  stepperSummary: { color: colors.textMuted, fontSize: 11 },
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
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    padding: spacing.md,
    gap: 4,
  },
  cardMuted: { opacity: 0.45 },
  cardTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  symbol: { color: colors.text, fontSize: 16, fontWeight: "700" },
  scoreChip: {
    color: colors.accent,
    fontWeight: "700",
    fontSize: 13,
    backgroundColor: colors.accentMuted,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radii.sm,
    overflow: "hidden",
  },
  meta: { color: colors.textMuted, fontSize: 12, lineHeight: 16 },
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
