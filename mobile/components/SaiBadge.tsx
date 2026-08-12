import { StyleSheet, Text, View } from "react-native";

import {
  formatSaiActionLabel,
  resolveSaiAttention,
} from "@/lib/saiDisplay";
import { colors, radii, spacing } from "@/lib/theme";
import type { SaiAction, TradingProposal } from "@/lib/types";

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
  proposal?: TradingProposal | null;
  /** Force attention bang; otherwise derived from proposal vs action. */
  attention?: boolean;
  compact?: boolean;
  mini?: boolean;
  alignRight?: boolean;
}

export function SaiBadge({
  action,
  confidence,
  proposal,
  attention: attentionProp,
  compact,
  mini,
  alignRight,
}: SaiBadgeProps) {
  if (!action) return null;
  const key = String(action).toLowerCase();
  const color = ACTION_COLORS[key] ?? colors.textMuted;
  const attention =
    attentionProp ?? resolveSaiAttention(action, proposal).flag;
  const label = mini
    ? `${ACTION_SHORT[key] ?? key.slice(0, 3).toUpperCase()}${attention ? "!" : ""}`
    : formatSaiActionLabel(action, attention);
  return (
    <View
      style={[
        styles.badge,
        { borderColor: color },
        attention && styles.attention,
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
  attention: {
    borderWidth: 1.5,
  },
  compact: {
    paddingVertical: 2,
    paddingHorizontal: 6,
  },
  mini: {
    paddingVertical: 1,
    paddingHorizontal: 4,
    borderRadius: 4,
    alignSelf: "center",
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
