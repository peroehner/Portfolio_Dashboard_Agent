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

const ACTION_SHORT: Record<string, string> = {
  buy: "BUY",
  sell: "SEL",
  hold: "HLD",
  watch: "WCH",
};

interface SaiBadgeProps {
  action?: SaiAction | null;
  confidence?: string | null;
  compact?: boolean;
  mini?: boolean;
  alignRight?: boolean;
}

export function SaiBadge({ action, confidence, compact, mini, alignRight }: SaiBadgeProps) {
  if (!action) return null;
  const key = String(action).toLowerCase();
  const color = ACTION_COLORS[key] ?? colors.textMuted;
  const label = mini ? (ACTION_SHORT[key] ?? titleCaseAction(key).slice(0, 3).toUpperCase()) : titleCaseAction(key);
  return (
    <View
      style={[
        styles.badge,
        { borderColor: color },
        compact && styles.compact,
        mini && styles.mini,
        alignRight && styles.alignRight,
      ]}
    >
      <Text style={[styles.text, mini && styles.miniText, { color }]} numberOfLines={1}>
        {label}
      </Text>
      {confidence && !compact && !mini ? (
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
  mini: {
    paddingVertical: 1,
    paddingHorizontal: 4,
    borderRadius: 4,
  },
  alignRight: {
    alignSelf: "flex-end",
  },
  text: {
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  miniText: {
    fontSize: 9,
    lineHeight: 11,
    letterSpacing: -0.2,
  },
  confidence: {
    color: colors.textMuted,
    fontSize: 10,
    textTransform: "capitalize",
  },
});
