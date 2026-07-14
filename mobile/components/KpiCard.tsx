import { StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";

interface KpiCardProps {
  label: string;
  value: string;
  hint?: string;
  valueColor?: string;
}

export function KpiCard({ label, value, hint, valueColor }: KpiCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, valueColor ? { color: valueColor } : null]}>{value}</Text>
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  label: {
    color: colors.textMuted,
    fontSize: 12,
    marginBottom: spacing.xs,
  },
  value: {
    color: colors.text,
    fontSize: 20,
    fontWeight: "700",
  },
  hint: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: spacing.xs,
  },
});
