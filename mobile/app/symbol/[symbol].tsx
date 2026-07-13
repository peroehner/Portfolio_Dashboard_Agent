import { useLocalSearchParams, useNavigation } from "expo-router";
import { useLayoutEffect, useMemo, useState } from "react";
import {
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
import { SaiBadge } from "@/components/SaiBadge";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { formatMoney, formatPct, formatPrice, pctColor } from "@/lib/format";
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

export default function SymbolDetailScreen() {
  const navigation = useNavigation();
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  const sym = String(symbol || "").toUpperCase();

  const { data, loading, error, refresh } = useApiQuery<InspectorPayload>(
    () => api.inspector(sym),
    [sym],
  );

  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [buyBelow, setBuyBelow] = useState("");
  const [sellAbove, setSellAbove] = useState("");
  const [targetPrice, setTargetPrice] = useState("");

  const [noteDate, setNoteDate] = useState(todayIso());
  const [noteSource, setNoteSource] = useState("Mobile");
  const [noteText, setNoteText] = useState("");

  const quote = data?.quote;

  const notes = useMemo(() => {
    const list = (quote?.notes ?? []).slice();
    // Most recent first (lexicographic works for YYYY-MM-DD and YYYY-Qn; best-effort)
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

  const mechanics = data?.positionMechanics;
  const recommendation = data?.recommendation;
  const screening = data?.screening;

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
      await refresh();
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
        source: noteSource.trim() || "Mobile",
        text: noteText.trim(),
      };
      await api.addNote(sym, payload);
      setNoteText("");
      await refresh();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen
      loading={loading && !data}
      error={error}
      onRetry={() => void refresh()}
    >
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

        <ScrollView
          refreshControl={
            <RefreshControl
              refreshing={loading && !!data}
              onRefresh={() => void refresh()}
              tintColor={colors.accent}
            />
          }
          contentContainerStyle={styles.scroll}
        >
          <View style={styles.hero}>
            {data?.companyName ? (
              <Text style={styles.company}>{data.companyName}</Text>
            ) : null}
            <Text style={styles.price}>{formatPrice(quote?.currentPrice)}</Text>
            <Text style={[styles.day, { color: pctColor(quote?.dayChangePct) }]}>
              {formatPct(quote?.dayChangePct)} today
            </Text>
            <View style={styles.recoRow}>
              <SaiBadge
                action={recommendation?.action}
                confidence={recommendation?.confidence}
              />
              {screening?.pScore != null ? (
                <Text style={styles.pScore}>P-Score {screening.pScore}</Text>
              ) : null}
            </View>
            {recommendation?.headline ? (
              <Text style={styles.headline}>{recommendation.headline}</Text>
            ) : null}
          </View>

          {mechanics?.quantity ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Position</Text>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Shares</Text>
                <Text style={styles.statValue}>{mechanics.quantity}</Text>
              </View>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Market value</Text>
                <Text style={styles.statValue}>{formatMoney(mechanics.marketValue)}</Text>
              </View>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Unrealized gain</Text>
                <Text style={[styles.statValue, { color: pctColor(mechanics.gainPct) }]}>
                  {formatMoney(mechanics.unrealizedGain)} ({formatPct(mechanics.gainPct)})
                </Text>
              </View>
              {mechanics.weightPct != null ? (
                <View style={styles.statRow}>
                  <Text style={styles.statLabel}>Weight</Text>
                  <Text style={styles.statValue}>{mechanics.weightPct.toFixed(1)}%</Text>
                </View>
              ) : null}
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Thresholds</Text>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Buy below</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.buyBelow)}</Text>
            </View>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Sell above</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.sellAbove)}</Text>
            </View>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Personal target</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.targetPrice)}</Text>
            </View>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Analyst 1Y</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.analystTarget1y)}</Text>
            </View>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Notes</Text>
            <View style={styles.noteForm}>
              <View style={styles.noteRow}>
                <View style={styles.noteCol}>
                  <Text style={styles.inputLabel}>Date</Text>
                  <TextInput
                    style={styles.input}
                    value={noteDate}
                    onChangeText={setNoteDate}
                    placeholder="YYYY-MM-DD"
                    placeholderTextColor={colors.textMuted}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                </View>
                <View style={styles.noteCol}>
                  <Text style={styles.inputLabel}>Source</Text>
                  <TextInput
                    style={styles.input}
                    value={noteSource}
                    onChangeText={setNoteSource}
                    placeholder="Mobile"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>
              <Text style={styles.inputLabel}>Text</Text>
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
                  <View key={note.id ?? `${note.date}-${note.source}-${note.text}`} style={styles.noteItem}>
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

          {(recommendation?.reasons?.length ?? 0) > 0 ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Recommendation reasons</Text>
              {recommendation?.reasons?.map((reason, idx) => (
                <Text key={idx} style={styles.reason}>
                  • {reason}
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
  hero: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.lg,
    gap: spacing.sm,
  },
  company: {
    color: colors.textMuted,
    fontSize: 14,
  },
  price: {
    color: colors.text,
    fontSize: 36,
    fontWeight: "700",
  },
  day: {
    fontSize: 16,
    fontWeight: "600",
  },
  recoRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    marginTop: spacing.sm,
  },
  pScore: {
    color: colors.textMuted,
    fontSize: 13,
  },
  headline: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.xs,
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
  statRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  statLabel: {
    color: colors.textMuted,
    fontSize: 14,
  },
  statValue: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "right",
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
  noteCol: {
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
    minHeight: 90,
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
