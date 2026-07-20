import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { appendStarFilterToken } from "@/lib/filters";
import { colors, radii } from "@/lib/theme";

interface StarFilterButtonProps {
  filter: string;
  onChangeFilter: (next: string) => void;
}

/** Tap = `*` / `,*` (OR). Long-press = `+*` / `,+*` (AND). */
export function StarFilterButton({ filter, onChangeFilter }: StarFilterButtonProps) {
  return (
    <Pressable
      style={({ pressed }) => [styles.btn, pressed && styles.btnPressed]}
      onPress={() => onChangeFilter(appendStarFilterToken(filter, false))}
      onLongPress={() => onChangeFilter(appendStarFilterToken(filter, true))}
      delayLongPress={350}
      hitSlop={6}
      accessibilityLabel="Add starred filter. Long press for AND starred."
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
