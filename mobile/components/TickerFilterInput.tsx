import { useMemo, useState } from "react";
import {
  Pressable,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from "react-native";

import {
  FILTER_PLACEHOLDER,
  matchingSegmentNames,
  parseSegmentCommand,
  trailingAtToken,
} from "@/lib/filters";
import { useTickerSegments } from "@/lib/TickerSegmentsContext";
import { colors, radii, spacing } from "@/lib/theme";

interface TickerFilterInputProps extends Omit<TextInputProps, "value" | "onChangeText"> {
  value: string;
  onChangeFilter: (next: string) => void;
}

export function TickerFilterInput({
  value,
  onChangeFilter,
  style,
  ...rest
}: TickerFilterInputProps) {
  const { segments, applyCommand, exportText } = useTickerSegments();
  const [focused, setFocused] = useState(false);

  const atToken = useMemo(() => trailingAtToken(value), [value]);
  const suggestions = useMemo(() => {
    if (!atToken || !focused) return [];
    return matchingSegmentNames(atToken.prefix, segments);
  }, [atToken, segments, focused]);
  const showAtHints = Boolean(atToken && focused);

  async function commitCommand() {
    if (!parseSegmentCommand(value)) return;
    const next = await applyCommand(value);
    if (next != null) onChangeFilter(next);
  }

  function applySuggestion(name: string) {
    const token = trailingAtToken(value);
    if (!token) {
      onChangeFilter(`@${name}`);
      return;
    }
    onChangeFilter(`${value.slice(0, token.start)}@${name}`);
  }

  async function onExport() {
    const text = exportText();
    if (!text.trim()) return;
    try {
      await Share.share({ message: text, title: "Ticker segments" });
    } catch {
      /* cancelled */
    }
  }

  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <TextInput
          {...rest}
          style={[styles.input, style]}
          placeholder={FILTER_PLACEHOLDER}
          placeholderTextColor={colors.textMuted}
          value={value}
          autoCapitalize="characters"
          autoCorrect={false}
          returnKeyType="done"
          onChangeText={onChangeFilter}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            void commitCommand();
          }}
          onSubmitEditing={() => void commitCommand()}
        />
        <Pressable onPress={() => void onExport()} hitSlop={8} style={styles.exportBtn}>
          <Text style={styles.exportText}>⇪</Text>
        </Pressable>
      </View>
      {showAtHints ? (
        <View style={styles.suggestRow}>
          {suggestions.length ? (
            suggestions.map((name) => (
              <Pressable key={name} onPress={() => applySuggestion(name)} style={styles.chip}>
                <Text style={styles.chipText}>@{name}</Text>
              </Pressable>
            ))
          ) : (
            <Text style={styles.hint}>
              {Object.keys(segments || {}).length
                ? `No segment matches @${atToken?.prefix || ""}`
                : "No saved segments yet — type @NAME=tsm, mr then Done"}
            </Text>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 6 },
  input: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    color: colors.text,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    fontSize: 14,
  },
  exportBtn: {
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  exportText: { color: colors.link, fontSize: 16, fontWeight: "700" },
  suggestRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: colors.surface,
  },
  chipText: { color: colors.text, fontSize: 12, fontWeight: "600" },
  hint: { color: colors.textMuted, fontSize: 12 },
});
