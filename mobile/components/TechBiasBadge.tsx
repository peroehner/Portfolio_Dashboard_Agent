import { StyleSheet, Text, View } from "react-native";

import { confluenceBiasColor } from "@/lib/inspectorHelpers";
import { colors, radii, spacing } from "@/lib/theme";

/** Compact Tech Bias (web Tech Stance) chip for Portfolio list. */
const SHORT_LABELS: Record<string, string> = {
  bullish: "Bull",
  "lean bullish": "LBull",
  "lean-bullish": "LBull",
  mixed: "Mix",
  "lean bearish": "LBear",
  "lean-bearish": "LBear",
  bearish: "Bear",
  // Fib-advisory fallbacks when confluence cannot fuse
  strong: "Str",
  alert: "Alrt",
  cautious: "Caut",
  neutral: "Neu",
  unknown: "—",
};

interface TechBiasBadgeProps {
  bias?: string | null;
  mini?: boolean;
}

export function shortTechBiasLabel(bias?: string | null): string | null {
  if (!bias) return null;
  const key = String(bias).trim().toLowerCase();
  if (!key) return null;
  if (SHORT_LABELS[key]) return SHORT_LABELS[key];
  if (key.includes("lean") && key.includes("bull")) return "LBull";
  if (key.includes("lean") && key.includes("bear")) return "LBear";
  if (key.includes("bull")) return "Bull";
  if (key.includes("bear")) return "Bear";
  if (key.includes("mix")) return "Mix";
  return bias.slice(0, 4);
}

export function TechBiasBadge({ bias, mini }: TechBiasBadgeProps) {
  const label = shortTechBiasLabel(bias);
  if (!label || label === "—") {
    return mini ? (
      <Text style={styles.empty} numberOfLines={1}>
        —
      </Text>
    ) : null;
  }
  const color = confluenceBiasColor(bias);
  return (
    <View
      style={[
        styles.badge,
        { borderColor: color },
        mini && styles.mini,
      ]}
    >
      <Text style={[styles.text, mini && styles.miniText, { color }]} numberOfLines={1}>
        {label}
      </Text>
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
  },
  mini: {
    paddingVertical: 1,
    paddingHorizontal: 4,
    borderRadius: 4,
    alignSelf: "center",
  },
  text: {
    fontSize: 12,
    fontWeight: "700",
  },
  miniText: {
    fontSize: 9,
    lineHeight: 11,
    letterSpacing: -0.2,
  },
  empty: {
    color: colors.textMuted,
    fontSize: 9,
    textAlign: "center",
  },
});
