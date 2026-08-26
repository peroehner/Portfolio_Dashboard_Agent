import { useMemo, useState } from "react";
import {
  ActionSheetIOS,
  Alert,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { api } from "@/lib/api";
import { colors, spacing } from "@/lib/theme";
import type { Note } from "@/lib/types";

function linkedSymbols(note: Note, fallbackSymbol?: string): string[] {
  const list =
    Array.isArray(note.symbols) && note.symbols.length
      ? note.symbols
      : note.symbol
        ? [note.symbol]
        : fallbackSymbol
          ? [fallbackSymbol]
          : [];
  return [...new Set(list.map((s) => String(s || "").toUpperCase()).filter(Boolean))].sort();
}

interface NoteLinkChipsProps {
  note: Note;
  viewSymbol: string;
  portfolioSymbols: string[];
  onUpdated: () => void | Promise<void>;
}

export function NoteLinkChips({
  note,
  viewSymbol,
  portfolioSymbols,
  onUpdated,
}: NoteLinkChipsProps) {
  const [busy, setBusy] = useState(false);
  const linked = useMemo(() => linkedSymbols(note, viewSymbol), [note, viewSymbol]);
  const available = useMemo(
    () => portfolioSymbols.filter((sym) => !linked.includes(sym.toUpperCase())),
    [portfolioSymbols, linked],
  );

  async function patchSymbols(next: string[]) {
    if (note.id == null) return;
    if (!next.length) {
      Alert.alert("Keep one link", "A note must stay linked to at least one symbol.");
      return;
    }
    setBusy(true);
    try {
      await api.updateNote(viewSymbol, note.id, {
        date: note.date,
        source: note.source,
        text: note.text,
        symbols: next,
      });
      await onUpdated();
    } catch (error) {
      Alert.alert("Link update failed", error instanceof Error ? error.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  function unlink(sym: string) {
    if (linked.length <= 1) {
      Alert.alert("Keep one link", "A note must stay linked to at least one symbol.");
      return;
    }
    void patchSymbols(linked.filter((s) => s !== sym));
  }

  function promptAdd() {
    if (!available.length || busy) return;
    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: [...available, "Cancel"],
          cancelButtonIndex: available.length,
          title: "Link symbol",
        },
        (index) => {
          if (index == null || index >= available.length) return;
          void patchSymbols([...linked, available[index]]);
        },
      );
      return;
    }
    Alert.alert(
      "Link symbol",
      undefined,
      [
        ...available.slice(0, 8).map((sym) => ({
          text: sym,
          onPress: () => void patchSymbols([...linked, sym]),
        })),
        { text: "Cancel", style: "cancel" as const },
      ],
    );
  }

  return (
    <View style={styles.row}>
      <Text style={styles.label}>Linked</Text>
      {linked.map((sym) => (
        <View key={sym} style={styles.chip}>
          <Text style={styles.chipText}>{sym}</Text>
          {linked.length > 1 ? (
            <Pressable
              onPress={() => unlink(sym)}
              disabled={busy}
              hitSlop={6}
              accessibilityLabel={`Unlink ${sym}`}
            >
              <Text style={styles.chipX}>×</Text>
            </Pressable>
          ) : null}
        </View>
      ))}
      {available.length ? (
        <Pressable
          style={styles.addChip}
          onPress={promptAdd}
          disabled={busy}
          accessibilityLabel="Link another symbol"
        >
          <Text style={styles.addText}>+</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 6,
    marginBottom: spacing.xs,
  },
  label: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
    backgroundColor: colors.surface,
  },
  chipText: { color: colors.text, fontSize: 12, fontWeight: "600" },
  chipX: { color: colors.textMuted, fontSize: 14, fontWeight: "700" },
  addChip: {
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  addText: { color: colors.textMuted, fontSize: 14, fontWeight: "700" },
});
