import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useNavigation } from "expo-router";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Dimensions,
  Modal,
  PanResponder,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { AlertMessageText, AlertRow } from "@/components/AlertRow";
import { HoldingsCompactCard } from "@/components/inspector/HoldingsCompactCard";
import { QuoteHeader } from "@/components/inspector/QuoteHeader";
import { TechnicalPanel } from "@/components/inspector/TechnicalPanel";
import { SaiSummaryCard } from "@/components/inspector/SaiSummaryCard";
import { SymbolTabBar, type SymbolTab } from "@/components/inspector/SymbolTabBar";
import { NoteSynthesisView, noteHasSynthesis } from "@/components/NoteSynthesisView";
import { SaiBadge } from "@/components/SaiBadge";
import { Screen } from "@/components/Screen";
import { api, isTimeoutApiError } from "@/lib/api";
import { dedupeActiveAlerts } from "@/lib/alertDedup";
import { emphasizeDriverText } from "@/lib/driverHighlight";
import { getRecommendationDrivers, headlineForAction } from "@/lib/inspectorHelpers";
import { formatNoteDate, formatPrice, formatQty, formatShortDateTime } from "@/lib/format";
import { proposeThresholds } from "@/lib/thresholdProposals";
import {
  getBrowseScrollY,
  getBrowseUi,
  getSymbolBrowseNeighbors,
  replaceBrowseSymbol,
  setBrowseScrollY,
  setBrowseTab,
  type BrowseDirection,
} from "@/lib/symbolBrowseSession";
import { isChartFullscreenActive } from "@/lib/chartFullscreenGate";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload, Note, PortfolioSymbol } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

function toInput(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "";
  return String(value);
}

function toShareInput(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value === 0) return "";
  return String(Math.abs(value));
}

function tradeDirFromShares(
  shares: number | null | undefined,
  fallback: "buy" | "sell",
): "buy" | "sell" {
  if (shares == null || shares === 0 || Number.isNaN(shares)) return fallback;
  return shares < 0 ? "sell" : "buy";
}

function parseNullableQuantity(text: string): number | null {
  const raw = text.trim().replace(/[,\s]/g, "");
  if (!raw) return null;
  const val = Number(raw);
  if (!Number.isFinite(val)) return null;
  return Math.round(Math.abs(val) * 10000) / 10000;
}

function signedTradeShares(qtyText: string, side: "buy" | "sell"): number | null {
  const qty = parseNullableQuantity(qtyText);
  if (qty == null || qty === 0) return null;
  return side === "sell" ? -qty : qty;
}

function thresholdValueText(
  price: number | null | undefined,
  shares: number | null | undefined,
): string {
  const priceText = formatPrice(price);
  if (shares == null || shares === 0) return priceText;
  const qty = formatQty(Math.abs(shares));
  return qty === "—" ? priceText : `${priceText} · ${qty}`;
}

function parseNullableNumber(text: string): number | null {
  const raw = text.trim().replace(",", ".");
  if (!raw) return null;
  const val = Number(raw);
  return Number.isFinite(val) ? val : null;
}

function todayIso(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function mergeInspector(
  lite?: InspectorPayload | null,
  full?: InspectorPayload | null,
): InspectorPayload | null {
  if (!lite && !full) return null;
  if (!full) return lite ?? null;
  if (!lite) return full;
  return {
    ...lite,
    ...full,
    quote: full.quote ?? lite.quote,
    holding: full.holding ?? lite.holding,
    // Chart fields: never keep lite empties over a populated full payload.
    chartTimeline: full.chartTimeline ?? lite.chartTimeline,
    chartPatterns: full.chartPatterns?.length ? full.chartPatterns : lite.chartPatterns,
    trendWaves: full.trendWaves?.length ? full.trendWaves : lite.trendWaves,
    importedFibLevels:
      full.importedFibLevels != null ? full.importedFibLevels : lite.importedFibLevels,
    fibBlueprint: full.fibBlueprint !== undefined ? full.fibBlueprint : lite.fibBlueprint,
    fib: full.fib !== undefined ? full.fib : lite.fib,
  };
}

export default function SymbolDetailScreen() {
  const navigation = useNavigation();
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  const sym = String(symbol || "").toUpperCase();
  const [tab, setTab] = useState<SymbolTab>(() => getBrowseUi().tab);
  const scrollRef = useRef<ScrollView>(null);
  const restoredScrollSym = useRef<string | null>(null);
  const [fullData, setFullData] = useState<InspectorPayload | null>(null);
  const [fullLoading, setFullLoading] = useState(false);
  const [fullError, setFullError] = useState<string | null>(null);
  const [newsSentiment, setNewsSentiment] = useState<{
    sentiment?: string;
    detail?: string;
    count?: number;
  } | null>(null);

  const {
    data: liteData,
    loading,
    error,
    refresh: refreshLite,
  } = useApiQuery<InspectorPayload>(() => api.inspector(sym, { lite: true }), [sym]);

  const data = useMemo(() => {
    const base = mergeInspector(liteData, fullData);
    if (!base?.recommendation || !newsSentiment?.count) return base;
    const rec = { ...base.recommendation };
    rec.sentiment = newsSentiment.sentiment || rec.sentiment;
    rec.sentimentSource = "news";
    rec.sentimentDetail = newsSentiment.detail;
    rec.headline = headlineForAction(rec.action, rec.sentiment);
    return { ...base, recommendation: rec };
  }, [liteData, fullData, newsSentiment]);
  const quote = data?.quote;
  const effectiveBuyBelow = quote?.tradeBelowPrice ?? quote?.buyBelow;
  const effectiveSellAbove = quote?.tradeAbovePrice ?? quote?.sellAbove;
  const drivers = useMemo(() => getRecommendationDrivers(data), [data]);
  const activeAlerts = useMemo(() => dedupeActiveAlerts(data?.alerts), [data?.alerts]);
  const thresholdSuggestions = useMemo(
    () => proposeThresholds(quote, data),
    [quote, data],
  );

  const loadFull = useCallback(async () => {
    if (fullData || fullLoading) return;
    setFullLoading(true);
    setFullError(null);
    try {
      const payload = await api.inspector(sym, { lite: false });
      setFullData(payload);
    } catch (err) {
      setFullError(err instanceof Error ? err.message : "Failed to load technical data");
    } finally {
      setFullLoading(false);
    }
  }, [sym, fullData, fullLoading]);

  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [buyBelow, setBuyBelow] = useState("");
  const [buyBelowShares, setBuyBelowShares] = useState("");
  const [buyBelowDir, setBuyBelowDir] = useState<"buy" | "sell">("buy");
  const [sellAbove, setSellAbove] = useState("");
  const [sellAboveShares, setSellAboveShares] = useState("");
  const [sellAboveDir, setSellAboveDir] = useState<"buy" | "sell">("sell");
  const [targetPrice, setTargetPrice] = useState("");
  const [noteDate, setNoteDate] = useState(todayIso());
  const [noteTitle, setNoteTitle] = useState("");
  const [noteText, setNoteText] = useState("");
  const [composingNote, setComposingNote] = useState(false);
  const [expandedNoteKey, setExpandedNoteKey] = useState<string | null>(null);
  const [deletingNoteId, setDeletingNoteId] = useState<number | null>(null);
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [editNoteDate, setEditNoteDate] = useState(todayIso());
  const [editNoteTitle, setEditNoteTitle] = useState("");
  const [editNoteText, setEditNoteText] = useState("");
  const [expandedAssessmentKey, setExpandedAssessmentKey] = useState<string | null>(null);

  useEffect(() => {
    setFullData(null);
    setFullError(null);
    setNewsSentiment(null);
    setComposingNote(false);
    setExpandedNoteKey(null);
    setEditingNoteId(null);
    setExpandedAssessmentKey(null);
    setEditOpen(false);
    restoredScrollSym.current = null;
    // Restore persisted tab after replace remounts this screen.
    setTab(getBrowseUi().tab);
  }, [sym]);

  const neighbors = useMemo(() => getSymbolBrowseNeighbors(sym), [sym]);
  const symRef = useRef(sym);
  symRef.current = sym;
  const slideX = useRef(new Animated.Value(0)).current;
  const browsingRef = useRef(false);

  const goBrowse = useCallback(
    (target: string | null, direction: BrowseDirection) => {
      if (!target || browsingRef.current) return;
      browsingRef.current = true;
      const width = Dimensions.get("window").width;
      // Next: current exits left, new enters from right.
      // Prev: current exits right, new enters from left.
      const exitTo = direction === "next" ? -width : width;
      const enterFrom = direction === "next" ? width : -width;

      Animated.timing(slideX, {
        toValue: exitTo,
        duration: 170,
        useNativeDriver: true,
      }).start(() => {
        replaceBrowseSymbol(target);
        slideX.setValue(enterFrom);
        Animated.timing(slideX, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }).start(() => {
          browsingRef.current = false;
        });
      });
    },
    [slideX],
  );

  function handleTabChange(next: SymbolTab) {
    setTab(next);
    setBrowseTab(next);
    restoredScrollSym.current = null;
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ y: getBrowseScrollY(next), animated: false });
      restoredScrollSym.current = `${sym}:${next}`;
    });
  }

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_, gesture) => {
          if (isChartFullscreenActive() || browsingRef.current) return false;
          return Math.abs(gesture.dx) > 24 && Math.abs(gesture.dx) > Math.abs(gesture.dy) * 1.6;
        },
        onPanResponderRelease: (_, gesture) => {
          if (isChartFullscreenActive() || browsingRef.current) return;
          const { prev, next } = getSymbolBrowseNeighbors(symRef.current);
          if (gesture.dx <= -56) goBrowse(next, "next");
          else if (gesture.dx >= 56) goBrowse(prev, "prev");
        },
      }),
    [goBrowse],
  );

  // After content for the new symbol is ready, restore scroll for the active tab.
  useEffect(() => {
    if (!data) return;
    if (tab === "technical" && fullLoading && !fullData) return;
    const key = `${sym}:${tab}`;
    if (restoredScrollSym.current === key) return;
    const y = getBrowseScrollY(tab);
    const apply = () => scrollRef.current?.scrollTo({ y, animated: false });
    apply();
    const t1 = setTimeout(apply, 50);
    const t2 = setTimeout(() => {
      apply();
      restoredScrollSym.current = key;
    }, 180);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [sym, tab, data, fullLoading, fullData]);

  useEffect(() => {
    let cancelled = false;
    void api
      .newsSentiment(sym)
      .then((res) => {
        if (!cancelled && res.newsSentiment?.count) {
          setNewsSentiment(res.newsSentiment);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sym]);

  useEffect(() => {
    if (tab === "technical") {
      void loadFull();
    }
  }, [tab, loadFull]);

  const notes = useMemo(() => {
    const list = (quote?.notes ?? []).slice();
    list.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    return list;
  }, [quote?.notes]);

  useLayoutEffect(() => {
    navigation.setOptions({
      title: sym,
      headerBackTitle: "Back",
      headerLargeTitle: false,
      headerRight: () => (
        <Pressable
          onPress={() => {
            setSaveError(null);
            setBuyBelow(toInput(effectiveBuyBelow));
            setBuyBelowShares(toShareInput(quote?.tradeBelowShares));
            setBuyBelowDir(tradeDirFromShares(quote?.tradeBelowShares, "buy"));
            setSellAbove(toInput(effectiveSellAbove));
            setSellAboveShares(toShareInput(quote?.tradeAboveShares));
            setSellAboveDir(tradeDirFromShares(quote?.tradeAboveShares, "sell"));
            setTargetPrice(toInput(quote?.targetPrice));
            setEditOpen(true);
            void loadFull();
          }}
          hitSlop={8}
        >
          <Text style={styles.headerBtn}>Edit</Text>
        </Pressable>
      ),
    });
  }, [
    navigation,
    sym,
    effectiveBuyBelow,
    effectiveSellAbove,
    quote?.targetPrice,
    quote?.tradeBelowShares,
    quote?.tradeAboveShares,
    loadFull,
  ]);

  async function refreshAll() {
    setFullData(null);
    setNewsSentiment(null);
    await refreshLite();
    void api
      .newsSentiment(sym)
      .then((res) => {
        if (res.newsSentiment?.count) setNewsSentiment(res.newsSentiment);
      })
      .catch(() => {});
    if (tab !== "summary") {
      setFullLoading(true);
      try {
        const payload = await api.inspector(sym, { lite: false });
        setFullData(payload);
        setFullError(null);
      } catch (err) {
        setFullError(err instanceof Error ? err.message : "Failed to load technical data");
      } finally {
        setFullLoading(false);
      }
    }
  }

  async function saveThresholds() {
    setSaving(true);
    setSaveError(null);
    try {
      const buyBelowValue = parseNullableNumber(buyBelow);
      const sellAboveValue = parseNullableNumber(sellAbove);
      const payload: Partial<PortfolioSymbol> = {
        // Keep legacy and planned-trade threshold fields in sync.
        buyBelow: buyBelowValue,
        tradeBelowPrice: buyBelowValue,
        tradeBelowShares: signedTradeShares(buyBelowShares, buyBelowDir),
        sellAbove: sellAboveValue,
        tradeAbovePrice: sellAboveValue,
        tradeAboveShares: signedTradeShares(sellAboveShares, sellAboveDir),
        targetPrice: parseNullableNumber(targetPrice),
      };
      await api.updateSymbol(sym, payload);
      setEditOpen(false);
      await refreshAll();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save thresholds");
    } finally {
      setSaving(false);
    }
  }

  async function addNote() {
    if (!noteText.trim()) return;
    const payload: Note = {
      date: noteDate.trim() || todayIso(),
      source: noteTitle.trim() || undefined,
      text: noteText.trim(),
    };
    setSaving(true);
    setSaveError(null);
    try {
      await api.addNote(sym, payload);
      setNoteText("");
      setNoteTitle("");
      setNoteDate(todayIso());
      setComposingNote(false);
      await refreshAll();
    } catch (err) {
      if (isTimeoutApiError(err)) {
        try {
          const inspector = await api.inspector(sym, { lite: true });
          const saved = (inspector.quote?.notes ?? []).some((note) => {
            const noteTextValue = (note.text || "").trim();
            const payloadText = (payload.text || "").trim();
            if (!payloadText || noteTextValue !== payloadText) return false;
            const noteDateValue = (note.date || "").trim();
            const payloadDate = (payload.date || "").trim();
            if (payloadDate && noteDateValue && payloadDate !== noteDateValue) return false;
            const noteSourceValue = (note.source || "").trim().toLowerCase();
            const payloadSource = (payload.source || "").trim().toLowerCase();
            if (payloadSource && noteSourceValue && payloadSource !== noteSourceValue) return false;
            return true;
          });
          if (saved) {
            setNoteText("");
            setNoteTitle("");
            setNoteDate(todayIso());
            setComposingNote(false);
            await refreshAll();
            return;
          }
        } catch {
          // Keep original timeout error below when verification fails.
        }
      }
      setSaveError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setSaving(false);
    }
  }

  async function deleteNote(note: Note) {
    const noteId = Number(note.id);
    if (!Number.isFinite(noteId)) {
      setSaveError("This note cannot be deleted because it has no id.");
      return;
    }
    if (deletingNoteId != null) return;
    setDeletingNoteId(noteId);
    setSaveError(null);
    try {
      await api.deleteNote(sym, noteId);
      if (expandedNoteKey === String(note.id ?? "")) setExpandedNoteKey(null);
      if (editingNoteId === noteId) setEditingNoteId(null);
      await refreshAll();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to delete note");
    } finally {
      setDeletingNoteId(null);
    }
  }

  function startEditNote(note: Note) {
    const noteId = Number(note.id);
    if (!Number.isFinite(noteId)) {
      setSaveError("This note cannot be edited because it has no id.");
      return;
    }
    setComposingNote(false);
    setExpandedNoteKey(null);
    setEditingNoteId(noteId);
    setEditNoteDate((note.date || "").trim() || todayIso());
    setEditNoteTitle((note.source || "").trim());
    setEditNoteText(note.text || "");
    setSaveError(null);
  }

  function cancelEditNote() {
    setEditingNoteId(null);
    setSaveError(null);
  }

  async function saveEditedNote() {
    if (editingNoteId == null) return;
    const text = editNoteText.trim();
    if (!text) {
      setSaveError("Note text is required.");
      return;
    }
    const payload: Note = {
      date: editNoteDate.trim() || todayIso(),
      source: editNoteTitle.trim() || undefined,
      text,
    };
    setSaving(true);
    setSaveError(null);
    try {
      await api.updateNote(sym, editingNoteId, payload);
      setEditingNoteId(null);
      await refreshAll();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to update note");
    } finally {
      setSaving(false);
    }
  }

  const technicalLoading = tab === "technical" && fullLoading && !fullData;

  return (
    <Screen loading={loading && !data} error={error} onRetry={() => void refreshAll()}>
      <Animated.View
        style={[styles.browseRoot, { transform: [{ translateX: slideX }] }]}
        {...panResponder.panHandlers}
      >
      <SymbolTabBar active={tab} onChange={handleTabChange} />

      {neighbors.total > 1 ? (
        <View style={styles.browseBar}>
          <Pressable
            style={[styles.browseSide, !neighbors.prev && styles.browseSideDisabled]}
            onPress={() => goBrowse(neighbors.prev, "prev")}
            disabled={!neighbors.prev}
            hitSlop={8}
          >
            <Text style={styles.browseSideText} numberOfLines={1}>
              {neighbors.prev ? `‹ ${neighbors.prev}` : " "}
            </Text>
          </Pressable>
          <Text style={styles.browseCount}>
            {neighbors.index >= 0 ? `${neighbors.index + 1} / ${neighbors.total}` : ""}
          </Text>
          <Pressable
            style={[styles.browseSide, styles.browseSideRight, !neighbors.next && styles.browseSideDisabled]}
            onPress={() => goBrowse(neighbors.next, "next")}
            disabled={!neighbors.next}
            hitSlop={8}
          >
            <Text style={styles.browseSideText} numberOfLines={1}>
              {neighbors.next ? `${neighbors.next} ›` : " "}
            </Text>
          </Pressable>
        </View>
      ) : null}

      <Modal
        visible={editOpen}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setEditOpen(false)}
      >
        <View style={styles.modalRoot}>
          <View style={styles.modalHeader}>
            <Pressable onPress={() => setEditOpen(false)} hitSlop={8}>
              <Text style={styles.modalBtn}>Cancel</Text>
            </Pressable>
            <Text style={styles.modalTitle}>Edit thresholds</Text>
            <Pressable onPress={() => void saveThresholds()} disabled={saving} hitSlop={8}>
              <Text style={[styles.modalBtn, saving && styles.modalBtnDisabled]}>
                {saving ? "Saving…" : "Save"}
              </Text>
            </Pressable>
          </View>
          <View style={styles.modalBody}>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.modalScroll}>
            <Text style={styles.modalHint}>Leave blank to clear a threshold. Use suggestions from Fib / assessment when available.</Text>

            <Text style={styles.inputLabel}>Trade @ Below</Text>
            <View style={styles.thresholdInputRow}>
              <TextInput
                style={[styles.input, styles.thresholdPriceInput]}
                value={buyBelow}
                onChangeText={setBuyBelow}
                keyboardType="decimal-pad"
                placeholder="Price"
                placeholderTextColor={colors.textMuted}
              />
              <TextInput
                style={[styles.input, styles.thresholdShareInput]}
                value={buyBelowShares}
                onChangeText={setBuyBelowShares}
                keyboardType="decimal-pad"
                placeholder="Shares"
                placeholderTextColor={colors.textMuted}
              />
            </View>
            <View style={styles.dirRow}>
              <Pressable
                style={[styles.dirBtn, buyBelowDir === "buy" && styles.dirBtnBuy]}
                onPress={() => setBuyBelowDir("buy")}
              >
                <Text style={[styles.dirBtnText, buyBelowDir === "buy" && styles.dirBtnTextActive]}>Buy</Text>
              </Pressable>
              <Pressable
                style={[styles.dirBtn, buyBelowDir === "sell" && styles.dirBtnSell]}
                onPress={() => setBuyBelowDir("sell")}
              >
                <Text style={[styles.dirBtnText, buyBelowDir === "sell" && styles.dirBtnTextActive]}>Sell</Text>
              </Pressable>
            </View>
            {thresholdSuggestions.buy != null ? (
              <Pressable
                style={styles.suggestBtn}
                onPress={() => setBuyBelow(toInput(thresholdSuggestions.buy))}
              >
                <Text style={styles.suggestBtnText}>
                  Use {formatPrice(thresholdSuggestions.buy)}
                  {thresholdSuggestions.buyNote ? ` · ${thresholdSuggestions.buyNote}` : ""}
                </Text>
              </Pressable>
            ) : (
              <Text style={styles.suggestHint}>
                {fullLoading
                  ? "Loading Fib suggestions…"
                  : "No Fib/assessment proposal yet — open Technical or wait for levels."}
              </Text>
            )}

            <Text style={styles.inputLabel}>Trade @ Above</Text>
            <View style={styles.thresholdInputRow}>
              <TextInput
                style={[styles.input, styles.thresholdPriceInput]}
                value={sellAbove}
                onChangeText={setSellAbove}
                keyboardType="decimal-pad"
                placeholder="Price"
                placeholderTextColor={colors.textMuted}
              />
              <TextInput
                style={[styles.input, styles.thresholdShareInput]}
                value={sellAboveShares}
                onChangeText={setSellAboveShares}
                keyboardType="decimal-pad"
                placeholder="Shares"
                placeholderTextColor={colors.textMuted}
              />
            </View>
            <View style={styles.dirRow}>
              <Pressable
                style={[styles.dirBtn, sellAboveDir === "buy" && styles.dirBtnBuy]}
                onPress={() => setSellAboveDir("buy")}
              >
                <Text style={[styles.dirBtnText, sellAboveDir === "buy" && styles.dirBtnTextActive]}>Buy</Text>
              </Pressable>
              <Pressable
                style={[styles.dirBtn, sellAboveDir === "sell" && styles.dirBtnSell]}
                onPress={() => setSellAboveDir("sell")}
              >
                <Text style={[styles.dirBtnText, sellAboveDir === "sell" && styles.dirBtnTextActive]}>Sell</Text>
              </Pressable>
            </View>
            {thresholdSuggestions.sell != null ? (
              <Pressable
                style={styles.suggestBtn}
                onPress={() => setSellAbove(toInput(thresholdSuggestions.sell))}
              >
                <Text style={styles.suggestBtnText}>
                  Use {formatPrice(thresholdSuggestions.sell)}
                  {thresholdSuggestions.sellNote ? ` · ${thresholdSuggestions.sellNote}` : ""}
                </Text>
              </Pressable>
            ) : (
              <Text style={styles.suggestHint}>
                {fullLoading
                  ? "Loading Fib suggestions…"
                  : "No Fib/assessment proposal yet — open Technical or wait for levels."}
              </Text>
            )}

            <Text style={styles.inputLabel}>Personal target</Text>
            <TextInput
              style={styles.input}
              value={targetPrice}
              onChangeText={setTargetPrice}
              keyboardType="decimal-pad"
              placeholder="$"
              placeholderTextColor={colors.textMuted}
            />
            {saveError ? <Text style={styles.modalError}>{saveError}</Text> : null}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {technicalLoading ? (
        <View style={styles.techLoading}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.techLoadingText}>Loading technical data…</Text>
        </View>
      ) : null}

      {fullError && tab === "technical" ? (
        <Text style={styles.fullError}>{fullError}</Text>
      ) : null}

      <ScrollView
        ref={scrollRef}
        refreshControl={
          <RefreshControl
            refreshing={(loading && !!data) || fullLoading}
            onRefresh={() => void refreshAll()}
            tintColor={colors.accent}
          />
        }
        contentContainerStyle={styles.scroll}
        scrollEventThrottle={16}
        onScroll={(event) => {
          setBrowseScrollY(tab, event.nativeEvent.contentOffset.y);
        }}
      >
        {tab === "summary" ? (
          <>
            <QuoteHeader
              companyName={data?.companyName}
              price={quote?.currentPrice}
              dayChangePct={quote?.dayChangePct}
            />
            <SaiSummaryCard data={data} />
            <HoldingsCompactCard data={data} />

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Thresholds</Text>
              <View style={styles.thresholdGrid}>
                <View style={styles.thresholdCell}>
                  <Text style={styles.statLabel}>Trade @ Below</Text>
                  <Text style={styles.statValue}>
                    {thresholdValueText(effectiveBuyBelow, quote?.tradeBelowShares)}
                  </Text>
                </View>
                <View style={styles.thresholdCell}>
                  <Text style={styles.statLabel}>Trade @ Above</Text>
                  <Text style={styles.statValue}>
                    {thresholdValueText(effectiveSellAbove, quote?.tradeAboveShares)}
                  </Text>
                </View>
                <View style={styles.thresholdCell}>
                  <Text style={styles.statLabel}>Personal target</Text>
                  <Text style={styles.statValue}>{formatPrice(quote?.targetPrice)}</Text>
                </View>
                <View style={styles.thresholdCell}>
                  <Text style={styles.statLabel}>Analyst 1Y</Text>
                  <Text style={styles.statValue}>{formatPrice(quote?.analystTarget1y)}</Text>
                </View>
              </View>
            </View>

            <View style={styles.card}>
              <View style={styles.notesHead}>
                <Text style={styles.cardTitle}>Notes</Text>
                {!composingNote ? (
                  <Pressable
                    style={styles.newNoteBtn}
                    onPress={() => {
                      setSaveError(null);
                      setComposingNote(true);
                    }}
                    hitSlop={8}
                  >
                    <Text style={styles.newNoteBtnText}>＋ New note</Text>
                  </Pressable>
                ) : null}
              </View>

              {composingNote ? (
                <View style={styles.noteForm}>
                  <View style={styles.noteRow}>
                    <TextInput
                      style={[styles.input, styles.noteDateInput]}
                      value={noteDate}
                      onChangeText={setNoteDate}
                      placeholder="YYYY-MM-DD"
                      placeholderTextColor={colors.textMuted}
                      autoCapitalize="none"
                      autoCorrect={false}
                    />
                    <TextInput
                      style={[styles.input, styles.noteTitleInput]}
                      value={noteTitle}
                      onChangeText={setNoteTitle}
                      placeholder="Title"
                      placeholderTextColor={colors.textMuted}
                    />
                  </View>
                  <TextInput
                    style={[styles.input, styles.noteText]}
                    value={noteText}
                    onChangeText={setNoteText}
                    placeholder="Add a note…"
                    placeholderTextColor={colors.textMuted}
                    multiline
                    autoFocus
                  />
                  <View style={styles.noteFormActions}>
                    <Pressable
                      style={styles.secondaryBtn}
                      onPress={() => {
                        setComposingNote(false);
                        setSaveError(null);
                      }}
                    >
                      <Text style={styles.secondaryBtnText}>Cancel</Text>
                    </Pressable>
                    <Pressable
                      style={[
                        styles.primaryBtn,
                        styles.primaryBtnFlex,
                        (!noteText.trim() || saving) && styles.primaryBtnDisabled,
                      ]}
                      onPress={() => void addNote()}
                      disabled={!noteText.trim() || saving}
                    >
                      <Text style={styles.primaryBtnText}>{saving ? "Saving…" : "Add note"}</Text>
                    </Pressable>
                  </View>
                  {saveError ? <Text style={styles.modalError}>{saveError}</Text> : null}
                </View>
              ) : null}

              {notes.length ? (
                <View style={styles.notesList}>
                  {notes.slice(0, 10).map((note) => {
                    const noteKey = String(note.id ?? `${note.date}-${note.source}-${note.text}`);
                    const noteId = Number(note.id);
                    const isEditing = Number.isFinite(noteId) && editingNoteId === noteId;
                    const expanded = expandedNoteKey === noteKey;
                    const hasSynthesis = noteHasSynthesis(note);

                    if (isEditing) {
                      return (
                        <View key={noteKey} style={styles.noteItem}>
                          <View style={styles.noteForm}>
                            <View style={styles.noteRow}>
                              <TextInput
                                style={[styles.input, styles.noteDateInput]}
                                value={editNoteDate}
                                onChangeText={setEditNoteDate}
                                placeholder="YYYY-MM-DD"
                                placeholderTextColor={colors.textMuted}
                                autoCapitalize="none"
                                autoCorrect={false}
                              />
                              <TextInput
                                style={[styles.input, styles.noteTitleInput]}
                                value={editNoteTitle}
                                onChangeText={setEditNoteTitle}
                                placeholder="Title"
                                placeholderTextColor={colors.textMuted}
                              />
                            </View>
                            <TextInput
                              style={[styles.input, styles.noteText]}
                              value={editNoteText}
                              onChangeText={setEditNoteText}
                              placeholder="Note text…"
                              placeholderTextColor={colors.textMuted}
                              multiline
                              autoFocus
                            />
                            <View style={styles.noteFormActions}>
                              <Pressable style={styles.secondaryBtn} onPress={cancelEditNote}>
                                <Text style={styles.secondaryBtnText}>Cancel</Text>
                              </Pressable>
                              <Pressable
                                style={[
                                  styles.primaryBtn,
                                  styles.primaryBtnFlex,
                                  (!editNoteText.trim() || saving) && styles.primaryBtnDisabled,
                                ]}
                                onPress={() => void saveEditedNote()}
                                disabled={!editNoteText.trim() || saving}
                              >
                                <Text style={styles.primaryBtnText}>
                                  {saving ? "Saving…" : "Save"}
                                </Text>
                              </Pressable>
                            </View>
                            {saveError ? <Text style={styles.modalError}>{saveError}</Text> : null}
                          </View>
                        </View>
                      );
                    }

                    return (
                      <Pressable
                        key={noteKey}
                        style={styles.noteItem}
                        onPress={() => setExpandedNoteKey(expanded ? null : noteKey)}
                      >
                        <View style={styles.noteMetaRow}>
                          <Text style={styles.noteMeta} numberOfLines={1}>
                            {(note.date ? formatNoteDate(note.date) : "—")
                              + (note.source ? ` · ${note.source}` : "")}
                          </Text>
                          <View style={styles.noteMetaActions}>
                            <Text style={styles.noteExpandHint}>{expanded ? "Less" : "More"}</Text>
                            <Pressable
                              style={styles.noteEditBtn}
                              onPress={(event) => {
                                event.stopPropagation();
                                startEditNote(note);
                              }}
                              disabled={note.id == null}
                              hitSlop={8}
                              accessibilityLabel="Edit note"
                            >
                              <Text
                                style={[
                                  styles.noteEditText,
                                  note.id == null && styles.noteDeleteTextDisabled,
                                ]}
                              >
                                Edit
                              </Text>
                            </Pressable>
                            <Pressable
                              style={[
                                styles.noteDeleteBtn,
                                (note.id == null || deletingNoteId != null) && styles.noteDeleteBtnDisabled,
                              ]}
                              onPress={(event) => {
                                event.stopPropagation();
                                void deleteNote(note);
                              }}
                              disabled={note.id == null || deletingNoteId != null}
                              hitSlop={8}
                              accessibilityLabel={
                                note.id == null
                                  ? "Delete unavailable for this note"
                                  : `Delete note ${note.date || ""}`
                              }
                            >
                              <Ionicons
                                name="trash-outline"
                                size={14}
                                color={note.id == null ? colors.textMuted : "#fecaca"}
                              />
                              <Text
                                style={[
                                  styles.noteDeleteText,
                                  note.id == null && styles.noteDeleteTextDisabled,
                                ]}
                              >
                                Del
                              </Text>
                            </Pressable>
                          </View>
                        </View>
                        {hasSynthesis && note.synthesis ? (
                          <NoteSynthesisView synthesis={note.synthesis} expanded={expanded} />
                        ) : note.text ? (
                          <Text style={styles.noteBody} numberOfLines={expanded ? undefined : 4}>
                            {note.text}
                          </Text>
                        ) : (
                          <Text style={styles.emptyInline}>Not synthesized yet.</Text>
                        )}
                      </Pressable>
                    );
                  })}
                </View>
              ) : (
                <Text style={styles.emptyInline}>No notes yet.</Text>
              )}
            </View>

            {drivers.length > 0 ? (
              <View style={[styles.card, styles.driversCard]}>
                <Text style={styles.driversTitle}>Drivers</Text>
                {drivers.map((reason, idx) => (
                  <View key={idx} style={styles.driverRow}>
                    <Text style={styles.driverBullet}>·</Text>
                    <View style={styles.driverTextWrap}>
                      <AlertMessageText
                        message={emphasizeDriverText(reason)}
                        style={styles.driverText}
                        boldStyle={styles.driverBold}
                      />
                    </View>
                  </View>
                ))}
              </View>
            ) : null}

            {activeAlerts.length > 0 ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Active alerts</Text>
                {activeAlerts.map((alert) => (
                  <AlertRow key={alert.id} alert={alert} />
                ))}
              </View>
            ) : null}

            {(data?.assessments?.length ?? 0) > 0 ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Recent assessments</Text>
                {data?.assessments?.slice(0, 3).map((item, idx) => {
                  const key = String(item.id ?? item.createdAt ?? idx);
                  const isLatest = idx === 0;
                  const expanded = isLatest || expandedAssessmentKey === key;
                  return (
                    <Pressable
                      key={key}
                      style={styles.assessment}
                      onPress={() => {
                        if (isLatest) return;
                        setExpandedAssessmentKey(expanded ? null : key);
                      }}
                      disabled={isLatest}
                    >
                      <View style={styles.assessmentHead}>
                        <SaiBadge action={item.action} confidence={item.confidence} compact />
                        <Text style={styles.assessmentDate}>
                          {formatShortDateTime(item.createdAt) || item.createdAt}
                        </Text>
                      </View>
                      {item.rationale ? (
                        <Text style={styles.reason} numberOfLines={expanded ? undefined : 2}>
                          {item.rationale}
                        </Text>
                      ) : null}
                      {!isLatest ? (
                        <Text style={styles.assessmentMore}>
                          {expanded ? "Less" : "More (…)"}
                        </Text>
                      ) : null}
                    </Pressable>
                  );
                })}
              </View>
            ) : null}
          </>
        ) : null}

        {tab === "technical" && !technicalLoading ? <TechnicalPanel data={data} /> : null}
      </ScrollView>
      </Animated.View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  browseRoot: {
    flex: 1,
  },
  browseBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.xs,
    gap: spacing.sm,
  },
  browseSide: {
    flex: 1,
    minWidth: 0,
  },
  browseSideRight: {
    alignItems: "flex-end",
  },
  browseSideDisabled: {
    opacity: 0.35,
  },
  browseSideText: {
    color: colors.link,
    fontSize: 13,
    fontWeight: "700",
  },
  browseCount: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
  },
  scroll: { paddingBottom: spacing.xl },
  headerBtn: {
    color: colors.link,
    fontSize: 15,
    fontWeight: "700",
  },
  techLoading: {
    alignItems: "center",
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  techLoadingText: {
    color: colors.textMuted,
    fontSize: 13,
  },
  fullError: {
    color: colors.danger,
    fontSize: 13,
    textAlign: "center",
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  cardTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
    marginBottom: spacing.xs,
  },
  notesHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  newNoteBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.accent,
    backgroundColor: colors.accentMuted,
    marginBottom: spacing.xs,
  },
  newNoteBtnText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "700",
  },
  noteFormActions: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  secondaryBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingVertical: 10,
    paddingHorizontal: spacing.md,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryBtnText: {
    color: colors.textMuted,
    fontSize: 14,
    fontWeight: "600",
  },
  primaryBtnFlex: {
    flex: 1,
  },
  statLabel: {
    color: colors.textMuted,
    fontSize: 12,
  },
  statValue: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "600",
  },
  thresholdGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  thresholdCell: {
    width: "48%",
    gap: 2,
  },
  section: {
    marginTop: spacing.sm,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  reason: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  driversCard: {
    borderColor: "rgba(96,165,250,0.45)",
    backgroundColor: "rgba(30,58,138,0.22)",
  },
  driversTitle: {
    color: colors.text,
    fontSize: 17,
    fontWeight: "800",
    letterSpacing: 0.2,
    marginBottom: spacing.xs,
  },
  driverRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
  },
  driverBullet: {
    color: colors.link,
    fontSize: 14,
    fontWeight: "800",
    lineHeight: 20,
  },
  driverTextWrap: {
    flex: 1,
    minWidth: 0,
  },
  driverText: {
    color: colors.text,
    fontSize: 14,
    lineHeight: 20,
  },
  driverBold: {
    color: colors.text,
    fontWeight: "800",
  },
  noteForm: {
    gap: spacing.sm,
  },
  noteRow: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  noteDateInput: {
    width: 118,
  },
  noteTitleInput: {
    flex: 1,
  },
  inputLabel: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 4,
    marginTop: spacing.sm,
  },
  input: {
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    color: colors.text,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    fontSize: 14,
  },
  thresholdInputRow: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  thresholdPriceInput: {
    flex: 2,
  },
  thresholdShareInput: {
    flex: 1,
  },
  dirRow: {
    flexDirection: "row",
    gap: spacing.xs,
    marginTop: 6,
  },
  dirBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.surfaceAlt,
  },
  dirBtnBuy: {
    borderColor: colors.buy,
    backgroundColor: "rgba(34,197,94,0.16)",
  },
  dirBtnSell: {
    borderColor: colors.sell,
    backgroundColor: "rgba(248,113,113,0.16)",
  },
  dirBtnText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "700",
  },
  dirBtnTextActive: {
    color: colors.text,
  },
  suggestBtn: {
    marginTop: 6,
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: colors.link,
    backgroundColor: "rgba(147,197,253,0.12)",
    borderRadius: radii.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  suggestBtnText: {
    color: colors.link,
    fontSize: 12,
    fontWeight: "700",
  },
  suggestHint: {
    marginTop: 6,
    color: colors.textMuted,
    fontSize: 11,
    lineHeight: 15,
  },
  noteText: {
    minHeight: 72,
    textAlignVertical: "top",
  },
  primaryBtn: {
    backgroundColor: colors.accentMuted,
    borderWidth: 1,
    borderColor: colors.accent,
    borderRadius: radii.sm,
    paddingVertical: 10,
    alignItems: "center",
  },
  primaryBtnDisabled: {
    opacity: 0.5,
  },
  primaryBtnText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
  },
  emptyInline: {
    color: colors.textMuted,
    fontSize: 13,
  },
  notesList: {
    marginTop: spacing.sm,
    gap: spacing.sm,
  },
  noteItem: {
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    padding: spacing.sm,
    gap: 6,
  },
  noteMetaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  noteMetaActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
  },
  noteMeta: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
    flex: 1,
  },
  noteExpandHint: {
    color: colors.link,
    fontSize: 11,
    fontWeight: "700",
  },
  noteEditBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: 6,
    paddingVertical: 3,
    backgroundColor: colors.surfaceAlt,
  },
  noteEditText: {
    color: colors.link,
    fontSize: 11,
    fontWeight: "700",
  },
  noteDeleteBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: "#7f1d1d",
    borderRadius: radii.sm,
    paddingHorizontal: 6,
    paddingVertical: 3,
    backgroundColor: "#3f151b",
  },
  noteDeleteBtnDisabled: {
    opacity: 0.5,
  },
  noteDeleteText: {
    color: "#fecaca",
    fontSize: 11,
    fontWeight: "700",
  },
  noteDeleteTextDisabled: {
    color: colors.textMuted,
  },
  noteBody: {
    color: colors.text,
    fontSize: 14,
    lineHeight: 20,
  },
  assessment: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  assessmentHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  assessmentDate: {
    color: colors.textMuted,
    fontSize: 11,
  },
  assessmentMore: {
    color: colors.link,
    fontSize: 11,
    fontWeight: "700",
    marginTop: 2,
  },
  modalRoot: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  modalHeader: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  modalTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
  },
  modalBtn: {
    color: colors.link,
    fontSize: 15,
    fontWeight: "700",
  },
  modalBtnDisabled: {
    opacity: 0.6,
  },
  modalBody: {
    flex: 1,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
  },
  modalScroll: {
    gap: spacing.xs,
    paddingBottom: spacing.xl,
  },
  modalHint: {
    color: colors.textMuted,
    fontSize: 12,
    marginBottom: spacing.sm,
  },
  modalError: {
    color: colors.danger,
    fontSize: 13,
    marginTop: spacing.sm,
  },
});
