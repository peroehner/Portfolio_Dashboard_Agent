import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { colors, radii } from "@/lib/theme";

interface RecallFilterButtonProps {
  visible: boolean;
  onPress: () => void;
  /** Last remembered filter (for accessibility). */
  lastFilter?: string;
}

/** Re-applies the last remembered symbol filter sequence. */
export function RecallFilterButton({ visible, onPress, lastFilter }: RecallFilterButtonProps) {
  if (!visible) return null;
  return (
    <Pressable
      style={({ pressed }) => [styles.btn, pressed && styles.btnPressed]}
      onPress={onPress}
      hitSlop={6}
      accessibilityLabel={
        lastFilter
          ? `Re-apply last filter: ${lastFilter}`
          : "Re-apply last symbol filter"
      }
    >
      <Ionicons name="refresh" size={15} color={colors.link} />
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
    borderColor: colors.link,
    backgroundColor: colors.surfaceAlt,
  },
});
