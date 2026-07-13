import { StyleSheet, Text, View } from "react-native";

import { titleCaseAction } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { SaiAction } from "@/lib/types";

const ACTION_COLORS: Record<string, string> = {
  buy: colors.buy,
  sell: colors.sell,
  hold: colors.hold,
  watch: colors.watch,
};

interface SaiBadgeProps {
  action?: SaiAction | null;
  confidence?: string | null;
  compact?: boolean;
}

export function SaiBadge({ action, confidence, compact }: SaiBadgeProps) {
  if (!action) return null;
  const key = String(action).toLowerCase();
  const color = ACTION_COLORS[key] ?? colors.textMuted;
  return (
    <View style={[styles.badge, { borderColor: color }, compact && styles.compact]}>
      <Text style={[styles.text, { color }]}>{titleCaseAction(key)}</Text>
      {confidence && !compact ? (
        <Text style={styles.confidence}>{confidence}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderWidth: 1,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    alignSelf: "flex-start",
    gap: 2,
  },
  compact: {
    paddingVertical: 2,
    paddingHorizontal: 6,
  },
  text: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  confidence: {
    color: colors.textMuted,
    fontSize: 10,
    textTransform: "capitalize",
  },
});
