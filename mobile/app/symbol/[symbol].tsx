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

import { AlertRow } from "@/components/AlertRow";
import { HoldingsCompactCard } from "@/components/inspector/HoldingsCompactCard";
import { QuoteHeader } from "@/components/inspector/QuoteHeader";
import { TechnicalPanel } from "@/components/inspector/TechnicalPanel";
import { SaiSummaryCard } from "@/components/inspector/SaiSummaryCard";
import { SymbolTabBar, type SymbolTab } from "@/components/inspector/SymbolTabBar";
import { SaiBadge } from "@/components/SaiBadge";
import { Screen } from "@/components/Screen";
import { api, isTimeoutApiError } from "@/lib/api";
import { getRecommendationDrivers, headlineForAction } from "@/lib/inspectorHelpers";
import { formatPrice, formatQty } from "@/lib/format";
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
  const [sellAbove, setSellAbove] = useState("");
  const [sellAboveShares, setSellAboveShares] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [noteDate, setNoteDate] = useState(todayIso());
  const [noteTitle, setNoteTitle] = useState("");
  const [noteText, setNoteText] = useState("");
  const [composingNote, setComposingNote] = useState(false);
  const [expandedNoteKey, setExpandedNoteKey] = useState<string | null>(null);

  useEffect(() => {
    setFullData(null);
    setFullError(null);
    setNewsSentiment(null);
    setComposingNote(false);
    setExpandedNoteKey(null);
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
            setSellAbove(toInput(effectiveSellAbove));
            setSellAboveShares(toShareInput(quote?.tradeAboveShares));
            setTargetPrice(toInput(quote?.targetPrice));
            setEditOpen(true);
          }}
          hitSlop={8}
        >
          <Text style={styles.headerBtn}>Edit</Text>
        </Pressable>
      ),
    });
  }, [navigation, sym, effectiveBuyBelow, effectiveSellAbove, quote?.targetPrice]);

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
        tradeBelowShares: signedTradeShares(buyBelowShares, "buy"),
        sellAbove: sellAboveValue,
        tradeAbovePrice: sellAboveValue,
        tradeAboveShares: signedTradeShares(sellAboveShares, "sell"),
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
            <Text style={styles.modalHint}>Leave blank to clear a threshold.</Text>
            <Text style={styles.inputLabel}>Buy below</Text>
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
            <Text style={styles.inputLabel}>Sell above</Text>
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
                  <Text style={styles.statLabel}>Buy below</Text>
                  <Text style={styles.statValue}>
                    {thresholdValueText(effectiveBuyBelow, quote?.tradeBelowShares)}
                  </Text>
                </View>
                <View style={styles.thresholdCell}>
                  <Text style={styles.statLabel}>Sell above</Text>
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
                    const expanded = expandedNoteKey === noteKey;
                    return (
                      <Pressable
                        key={noteKey}
                        style={styles.noteItem}
                        onPress={() => setExpandedNoteKey(expanded ? null : noteKey)}
                      >
                        <View style={styles.noteMetaRow}>
                          <Text style={styles.noteMeta} numberOfLines={1}>
                            {(note.date || "—") + (note.source ? ` · ${note.source}` : "")}
                          </Text>
                          <Text style={styles.noteExpandHint}>{expanded ? "Less" : "More"}</Text>
                        </View>
                        {note.text ? (
                          <Text style={styles.noteBody} numberOfLines={expanded ? undefined : 4}>
                            {note.text}
                          </Text>
                        ) : null}
                      </Pressable>
                    );
                  })}
                </View>
              ) : (
                <Text style={styles.emptyInline}>No notes yet.</Text>
              )}
            </View>

            {drivers.length > 0 ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Drivers</Text>
                {drivers.map((reason, idx) => (
                  <Text key={idx} style={styles.reason}>
                    · {reason}
                  </Text>
                ))}
              </View>
            ) : null}

            {(data?.alerts?.length ?? 0) > 0 ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Active alerts</Text>
                {data?.alerts?.map((alert) => (
                  <AlertRow key={alert.id} alert={alert} />
                ))}
              </View>
            ) : null}

            {(data?.assessments?.length ?? 0) > 0 ? (
              <View style={styles.card}>
                <Text style={styles.cardTitle}>Recent assessments</Text>
                {data?.assessments?.slice(0, 3).map((item) => (
                  <View key={item.id ?? item.createdAt} style={styles.assessment}>
                    <View style={styles.assessmentHead}>
                      <SaiBadge action={item.action} confidence={item.confidence} compact />
                      <Text style={styles.assessmentDate}>{item.createdAt}</Text>
                    </View>
                    {item.rationale ? (
                      <Text style={styles.reason} numberOfLines={4}>
                        {item.rationale}
                      </Text>
                    ) : null}
                  </View>
                ))}
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
    minWidth: 72,
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
    padding: spacing.lg,
    gap: spacing.sm,
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
