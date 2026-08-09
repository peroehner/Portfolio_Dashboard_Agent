import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { Pressable, StyleSheet, Text } from "react-native";

import { colors, spacing } from "@/lib/theme";

/** Back to Symbol Summary when Alerts/News were opened from a symbol detail. */
export function BackToSymbolButton({ symbol }: { symbol: string }) {
  const sym = symbol.trim().toUpperCase();
  if (!sym) return null;
  return (
    <Pressable
      style={styles.btn}
      onPress={() => router.push(`/symbol/${encodeURIComponent(sym)}`)}
      hitSlop={10}
      accessibilityRole="button"
      accessibilityLabel={`Back to ${sym} Summary`}
    >
      <Ionicons name="chevron-back" size={18} color={colors.link} />
      <Text style={styles.text} numberOfLines={1}>
        {sym}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    maxWidth: 88,
    paddingVertical: 2,
  },
  text: {
    color: colors.link,
    fontSize: 14,
    fontWeight: "700",
  },
});
