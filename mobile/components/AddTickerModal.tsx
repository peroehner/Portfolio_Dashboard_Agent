import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { api } from "@/lib/api";
import { colors, radii, spacing } from "@/lib/theme";
import type { TickerSearchHit } from "@/lib/types";

interface AddTickerModalProps {
  visible: boolean;
  onClose: () => void;
  onAdded: (symbol: string) => void;
}

export function AddTickerModal({ visible, onClose, onAdded }: AddTickerModalProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TickerSearchHit[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState(false);
  const [hint, setHint] = useState("Type a name or ticker to search.");
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef(0);

  useEffect(() => {
    if (!visible) return;
    setQuery("");
    setResults([]);
    setSelected(null);
    setSearching(false);
    setAdding(false);
    setError(null);
    setHint("Type a name or ticker to search. Exact tickers work without hits.");
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      setSelected(null);
      setHint("Type a name or ticker to search. Exact tickers work without hits.");
      return;
    }
    setSelected(q.toUpperCase());
    const seq = ++seqRef.current;
    const timer = setTimeout(() => {
      void (async () => {
        setSearching(true);
        try {
          const data = await api.searchSymbols(q, 12);
          if (seq !== seqRef.current) return;
          if (data.providerUnavailable) {
            setResults([]);
            setHint("Search unavailable. Enter an exact ticker (e.g. AAPL) and tap Add.");
          } else if (!(data.results || []).length) {
            setResults([]);
            setHint(`No matches for “${q}”. You can still Add the exact ticker.`);
          } else {
            setResults(data.results || []);
            setHint("");
            const exact = (data.results || []).find(
              (r) => r.symbol.toUpperCase() === q.toUpperCase(),
            );
            if (exact) setSelected(exact.symbol.toUpperCase());
          }
        } catch {
          if (seq !== seqRef.current) return;
          setResults([]);
          setHint(`Search failed — you can still Add exact ticker “${q.toUpperCase()}”.`);
        } finally {
          if (seq === seqRef.current) setSearching(false);
        }
      })();
    }, 280);
    return () => clearTimeout(timer);
  }, [query, visible]);

  async function confirmAdd() {
    const symbol = (selected || query).trim().toUpperCase();
    if (!symbol || adding) return;
    setAdding(true);
    setError(null);
    try {
      const created = await api.addSymbol(symbol);
      onAdded(String(created.symbol || symbol).toUpperCase());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add ticker");
    } finally {
      setAdding(false);
    }
  }

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.root}>
        <View style={styles.header}>
          <Pressable onPress={onClose} hitSlop={8}>
            <Text style={styles.headerBtn}>Cancel</Text>
          </Pressable>
          <View style={styles.headerCenter}>
            <Text style={styles.headerTitle}>Select ticker to add</Text>
            <Text style={styles.headerSub}>Adding to Portfolio</Text>
          </View>
          <Pressable
            onPress={() => void confirmAdd()}
            disabled={adding || !(selected || query).trim()}
            hitSlop={8}
          >
            <Text
              style={[
                styles.headerBtn,
                (adding || !(selected || query).trim()) && styles.headerBtnDisabled,
              ]}
            >
              {adding ? "Adding…" : "Add"}
            </Text>
          </Pressable>
        </View>

        <View style={styles.body}>
          <TextInput
            style={styles.input}
            value={query}
            onChangeText={setQuery}
            placeholder="Search by name or ticker…"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="characters"
            autoCorrect={false}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={() => void confirmAdd()}
          />
          {searching ? <ActivityIndicator color={colors.accent} style={styles.spinner} /> : null}
          {hint ? <Text style={styles.hint}>{hint}</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <FlatList
            data={results}
            keyExtractor={(item) => item.symbol}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => {
              const active = selected === item.symbol.toUpperCase();
              const meta = [item.description, item.type].filter(Boolean).join(" · ");
              return (
                <Pressable
                  style={[styles.row, active && styles.rowActive]}
                  onPress={() => {
                    setSelected(item.symbol.toUpperCase());
                    setQuery(item.symbol.toUpperCase());
                  }}
                >
                  <Text style={styles.sym}>{item.displaySymbol || item.symbol}</Text>
                  {meta ? <Text style={styles.meta}>{meta}</Text> : null}
                </Pressable>
              );
            }}
          />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
    gap: spacing.sm,
  },
  headerCenter: { flex: 1, alignItems: "center" },
  headerTitle: { color: colors.text, fontSize: 15, fontWeight: "700" },
  headerSub: { color: colors.textMuted, fontSize: 11, marginTop: 2 },
  headerBtn: { color: colors.link, fontSize: 15, fontWeight: "700", minWidth: 56 },
  headerBtnDisabled: { opacity: 0.45 },
  body: { flex: 1, paddingHorizontal: spacing.lg, gap: spacing.sm },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    color: colors.text,
    paddingHorizontal: spacing.sm,
    paddingVertical: 10,
    fontSize: 15,
  },
  spinner: { marginVertical: spacing.xs },
  hint: { color: colors.textMuted, fontSize: 12, lineHeight: 16 },
  error: { color: colors.danger, fontSize: 13 },
  row: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: 2,
  },
  rowActive: { backgroundColor: "rgba(96,165,250,0.14)", borderRadius: radii.sm },
  sym: { color: colors.text, fontSize: 15, fontWeight: "700" },
  meta: { color: colors.textMuted, fontSize: 12 },
});
