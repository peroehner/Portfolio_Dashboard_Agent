import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";
import type { Alert } from "@/lib/types";

interface AlertRowProps {
  alert: Alert;
  onDismiss?: (id: number) => void;
  dismissing?: boolean;
}

function alertTypeLabel(alert: Alert): string {
  const raw = alert.type || alert.alert_type || "alert";
  return raw.replace(/_/g, " ");
}

export function AlertRow({ alert, onDismiss, dismissing }: AlertRowProps) {
  return (
    <View style={styles.card}>
      <View style={styles.top}>
        <Link href={`/symbol/${alert.symbol}`} asChild>
          <Pressable>
            <Text style={styles.symbol}>{alert.symbol}</Text>
          </Pressable>
        </Link>
        <Text style={styles.type}>{alertTypeLabel(alert)}</Text>
      </View>
      {alert.message ? <Text style={styles.message}>{alert.message}</Text> : null}
      {onDismiss ? (
        <Pressable
          style={[styles.dismiss, dismissing && styles.dismissDisabled]}
          onPress={() => onDismiss(alert.id)}
          disabled={dismissing}
        >
          <Text style={styles.dismissText}>{dismissing ? "Dismissing…" : "Dismiss"}</Text>
        </Pressable>
      ) : null}
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
  symbol: {
    color: colors.link,
    fontSize: 16,
    fontWeight: "700",
  },
  type: {
    color: colors.warning,
    fontSize: 11,
    textTransform: "capitalize",
    flexShrink: 1,
    textAlign: "right",
  },
  message: {
    color: colors.text,
    fontSize: 14,
    lineHeight: 20,
  },
  dismiss: {
    alignSelf: "flex-start",
    paddingVertical: 4,
    paddingHorizontal: spacing.sm,
    borderRadius: radii.sm,
    backgroundColor: colors.surfaceAlt,
  },
  dismissDisabled: {
    opacity: 0.6,
  },
  dismissText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
  },
});
