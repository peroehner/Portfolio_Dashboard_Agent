import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View, type PressableProps } from "react-native";

import { useStarredSymbols } from "@/lib/StarredSymbolsContext";
import { promptToggleStar } from "@/lib/symbolStarActions";
import { colors } from "@/lib/theme";

interface SymbolStarPressableProps extends Omit<PressableProps, "children"> {
  symbol: string;
  children?: React.ReactNode;
  /** Show a small star badge when starred. */
  showStarBadge?: boolean;
  textStyle?: object;
  compact?: boolean;
}

/** Tap navigates; long-press offers Star / Unstar. */
export function SymbolStarPressable({
  symbol,
  children,
  showStarBadge = true,
  textStyle,
  compact,
  onLongPress,
  delayLongPress = 400,
  ...rest
}: SymbolStarPressableProps) {
  const { isStarred, toggleStar } = useStarredSymbols();
  const sym = String(symbol || "").trim().toUpperCase();
  const starred = isStarred(sym);

  function handleLongPress(e: Parameters<NonNullable<PressableProps["onLongPress"]>>[0]) {
    promptToggleStar(sym, starred, () => toggleStar(sym));
    onLongPress?.(e);
  }

  return (
    <Pressable onLongPress={handleLongPress} delayLongPress={delayLongPress} {...rest}>
      {children ?? (
        <View style={styles.row}>
          {showStarBadge && starred ? (
            <Ionicons
              name="star"
              size={compact ? 11 : 12}
              color={colors.warning}
              style={styles.starIcon}
            />
          ) : null}
          <Text style={[styles.symbol, compact && styles.symbolCompact, textStyle]} numberOfLines={1}>
            {sym}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
  },
  starIcon: {
    flexShrink: 0,
  },
  symbol: {
    color: colors.link,
    fontSize: 16,
    fontWeight: "700",
  },
  symbolCompact: {
    fontSize: 13,
  },
});
