import { Ionicons } from "@expo/vector-icons";
import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";
import { alertTypeKey, alertTypeLabel } from "@/lib/alertTypes";
import type { Alert } from "@/lib/types";

interface AlertRowProps {
  alert: Alert;
  onDismiss?: (id: number) => void;
  dismissing?: boolean;
}

export function AlertRow({ alert, onDismiss, dismissing }: AlertRowProps) {
  const type = alertTypeLabel(alertTypeKey(alert.type || alert.alert_type));

  return (
    <View style={styles.card}>
      <View style={styles.top}>
        <Link href={`/symbol/${alert.symbol}`} asChild>
          <Pressable style={styles.symbolPress}>
            <Text style={styles.symbol}>{alert.symbol}</Text>
          </Pressable>
        </Link>
        <View style={styles.typeRow}>
          <Text style={styles.type}>{type}</Text>
          {onDismiss ? (
            <Pressable
              style={[styles.dismissBtn, dismissing && styles.dismissDisabled]}
              onPress={() => onDismiss(alert.id)}
              disabled={dismissing}
              hitSlop={8}
              accessibilityLabel="Dismiss alert"
            >
              <Ionicons
                name="trash-outline"
                size={16}
                color={dismissing ? colors.textMuted : colors.textMuted}
              />
            </Pressable>
          ) : null}
        </View>
      </View>
      {alert.message ? <Text style={styles.message}>{alert.message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    padding: spacing.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  top: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.sm,
  },
  symbolPress: {
    flexShrink: 0,
  },
  symbol: {
    color: colors.link,
    fontSize: 16,
    fontWeight: "700",
  },
  typeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    flexShrink: 1,
    justifyContent: "flex-end",
  },
  type: {
    color: colors.warning,
    fontSize: 11,
    fontWeight: "600",
    textTransform: "none",
    textAlign: "right",
    flexShrink: 1,
  },
  message: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  dismissBtn: {
    padding: 2,
    borderRadius: radii.sm,
  },
  dismissDisabled: {
    opacity: 0.5,
  },
});
