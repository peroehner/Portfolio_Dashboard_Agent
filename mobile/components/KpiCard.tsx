import { Ionicons } from "@expo/vector-icons";
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
  /** Optional control next to the label (e.g. privacy eye). */
  labelAction?: {
    icon: keyof typeof Ionicons.glyphMap;
    onPress: () => void;
    accessibilityLabel: string;
  };
}

export function KpiCard({
  label,
  value,
  hint,
  valueColor,
  onPress,
  compact = false,
  labelAction,
}: KpiCardProps) {
  const labelRow = (
    <View style={styles.labelRow}>
      <Text
        style={[styles.label, compact && styles.labelCompact, styles.labelFlex]}
        numberOfLines={compact ? 2 : 1}
      >
        {label}
      </Text>
      {labelAction ? (
        <Pressable
          onPress={labelAction.onPress}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel={labelAction.accessibilityLabel}
          style={({ pressed }) => [styles.labelActionBtn, pressed && styles.labelActionPressed]}
        >
          <Ionicons
            name={labelAction.icon}
            size={compact ? 14 : 16}
            color={colors.textMuted}
          />
        </Pressable>
      ) : null}
    </View>
  );

  const body = (
    <>
      {labelRow}
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
  labelRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 4,
    marginBottom: spacing.xs,
  },
  labelFlex: {
    flex: 1,
    marginBottom: 0,
  },
  labelActionBtn: {
    paddingTop: 1,
    paddingHorizontal: 2,
  },
  labelActionPressed: {
    opacity: 0.7,
  },
  label: {
    color: colors.textMuted,
    fontSize: 12,
  },
  labelCompact: {
    fontSize: 10,
    lineHeight: 12,
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
