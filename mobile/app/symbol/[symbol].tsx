import { useLocalSearchParams, useNavigation } from "expo-router";
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
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
import { api } from "@/lib/api";
import { getRecommendationDrivers, headlineForAction } from "@/lib/inspectorHelpers";
import { formatPrice } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload, Note, PortfolioSymbol } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

function toInput(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "";
  return String(value);
}

function parseNullableNumber(text: string): number | null {
  const raw = text.trim();
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
  return { ...lite, ...full, quote: full.quote ?? lite.quote, holding: full.holding ?? lite.holding };
}

export default function SymbolDetailScreen() {
  const navigation = useNavigation();
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  const sym = String(symbol || "").toUpperCase();
  const [tab, setTab] = useState<SymbolTab>("summary");
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

  useEffect(() => {
    setFullData(null);
    setFullError(null);
    setNewsSentiment(null);
    setTab("summary");
  }, [sym]);

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

  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [buyBelow, setBuyBelow] = useState("");
  const [sellAbove, setSellAbove] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [noteDate, setNoteDate] = useState(todayIso());
  const [noteTitle, setNoteTitle] = useState("");
  const [noteText, setNoteText] = useState("");

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
            setBuyBelow(toInput(quote?.buyBelow));
            setSellAbove(toInput(quote?.sellAbove));
            setTargetPrice(toInput(quote?.targetPrice));
            setEditOpen(true);
          }}
          hitSlop={8}
        >
          <Text style={styles.headerBtn}>Edit</Text>
        </Pressable>
      ),
    });
  }, [navigation, sym, quote?.buyBelow, quote?.sellAbove, quote?.targetPrice]);

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
      const payload: Partial<PortfolioSymbol> = {
        buyBelow: parseNullableNumber(buyBelow),
        sellAbove: parseNullableNumber(sellAbove),
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
    setSaving(true);
    setSaveError(null);
    try {
      const payload: Note = {
        date: noteDate.trim() || todayIso(),
        source: noteTitle.trim() || undefined,
        text: noteText.trim(),
      };
      await api.addNote(sym, payload);
      setNoteText("");
      await refreshAll();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setSaving(false);
    }
  }

  const technicalLoading = tab === "technical" && fullLoading && !fullData;

  return (
    <Screen loading={loading && !data} error={error} onRetry={() => void refreshAll()}>
      <SymbolTabBar active={tab} onChange={setTab} />

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
            <TextInput
              style={styles.input}
              value={buyBelow}
              onChangeText={setBuyBelow}
              keyboardType="decimal-pad"
              placeholder="$"
              placeholderTextColor={colors.textMuted}
            />
            <Text style={styles.inputLabel}>Sell above</Text>
            <TextInput
              style={styles.input}
              value={sellAbove}
              onChangeText={setSellAbove}
              keyboardType="decimal-pad"
              placeholder="$"
              placeholderTextColor={colors.textMuted}
            />
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
        refreshControl={
          <RefreshControl
            refreshing={(loading && !!data) || fullLoading}
            onRefresh={() => void refreshAll()}
            tintColor={colors.accent}
          />
        }
        contentContainerStyle={styles.scroll}
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
                  <Text style={styles.statValue}>{formatPrice(quote?.buyBelow)}</Text>
                </View>
                <View style={styles.thresholdCell}>
                  <Text style={styles.statLabel}>Sell above</Text>
                  <Text style={styles.statValue}>{formatPrice(quote?.sellAbove)}</Text>
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
              <Text style={styles.cardTitle}>Notes</Text>
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
                />
                <Pressable
                  style={[styles.primaryBtn, (!noteText.trim() || saving) && styles.primaryBtnDisabled]}
                  onPress={() => void addNote()}
                  disabled={!noteText.trim() || saving}
                >
                  <Text style={styles.primaryBtnText}>{saving ? "Saving…" : "Add note"}</Text>
                </Pressable>
                {saveError ? <Text style={styles.modalError}>{saveError}</Text> : null}
              </View>

              {notes.length ? (
                <View style={styles.notesList}>
                  {notes.slice(0, 10).map((note) => (
                    <View
                      key={note.id ?? `${note.date}-${note.source}-${note.text}`}
                      style={styles.noteItem}
                    >
                      <Text style={styles.noteMeta}>
                        {(note.date || "—") + (note.source ? ` · ${note.source}` : "")}
                      </Text>
                      {note.text ? (
                        <Text style={styles.noteBody} numberOfLines={5}>
                          {note.text}
                        </Text>
                      ) : null}
                    </View>
                  ))}
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
    </Screen>
  );
}

const styles = StyleSheet.create({
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
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    gap: 4,
  },
  noteMeta: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
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
