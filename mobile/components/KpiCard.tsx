import { StyleSheet, Text, Pressable, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";

interface KpiCardProps {
  label: string;
  value: string;
  hint?: string;
  valueColor?: string;
  onPress?: () => void;
  /** Tighter padding/type for 3-column Summary grids. */
  compact?: boolean;
}

export function KpiCard({ label, value, hint, valueColor, onPress, compact = false }: KpiCardProps) {
  const body = (
    <>
      <Text style={[styles.label, compact && styles.labelCompact]} numberOfLines={compact ? 2 : 1}>
        {label}
      </Text>
      <Text
        style={[styles.value, compact && styles.valueCompact, valueColor ? { color: valueColor } : null]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.75}
      >
        {value}
      </Text>
      {hint ? (
        <Text style={[styles.hint, compact && styles.hintCompact]} numberOfLines={2}>
          {hint}
        </Text>
      ) : null}
    </>
  );

  if (onPress) {
    return (
      <Pressable
        style={({ pressed }) => [
          styles.card,
          compact && styles.cardCompact,
          pressed && styles.cardPressed,
        ]}
        onPress={onPress}
        accessibilityRole="button"
      >
        {body}
      </Pressable>
    );
  }

  return <View style={[styles.card, compact && styles.cardCompact]}>{body}</View>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardCompact: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    minHeight: 78,
    flexGrow: 1,
  },
  cardPressed: {
    opacity: 0.85,
    borderColor: colors.link,
  },
  label: {
    color: colors.textMuted,
    fontSize: 12,
    marginBottom: spacing.xs,
  },
  labelCompact: {
    fontSize: 10,
    lineHeight: 12,
    marginBottom: 2,
  },
  value: {
    color: colors.text,
    fontSize: 20,
    fontWeight: "700",
  },
  valueCompact: {
    fontSize: 15,
  },
  hint: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: spacing.xs,
  },
  hintCompact: {
    fontSize: 10,
    marginTop: 2,
  },
});
