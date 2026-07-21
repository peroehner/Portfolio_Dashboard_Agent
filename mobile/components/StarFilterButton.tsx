import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { toggleStarFilterToken } from "@/lib/filters";
import { colors, radii } from "@/lib/theme";

interface StarFilterButtonProps {
  filter: string;
  onChangeFilter: (next: string) => void;
}

/** Tap toggles `*` (OR). Long-press toggles `+*` (AND). */
export function StarFilterButton({ filter, onChangeFilter }: StarFilterButtonProps) {
  return (
    <Pressable
      style={({ pressed }) => [styles.btn, pressed && styles.btnPressed]}
      onPress={() => onChangeFilter(toggleStarFilterToken(filter, false))}
      onLongPress={() => onChangeFilter(toggleStarFilterToken(filter, true))}
      delayLongPress={350}
      hitSlop={6}
      accessibilityLabel="Toggle starred filter. Long press for AND starred."
    >
      <Ionicons name="star" size={16} color={colors.warning} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    flexShrink: 0,
    width: 32,
    height: 32,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  btnPressed: {
    borderColor: colors.warning,
    backgroundColor: colors.surfaceAlt,
  },
});
