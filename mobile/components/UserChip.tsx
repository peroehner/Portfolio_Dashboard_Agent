import { Image, StyleSheet, Text, View } from "react-native";

import { colors } from "@/lib/theme";

/** Short tier labels aligned with web badge (CSS uppercase → FREE / STD / PRO). */
export function formatPlanLabel(plan?: string | null): string {
  const key = String(plan || "")
    .trim()
    .toLowerCase();
  if (key === "free") return "Free";
  if (key === "standard") return "Std";
  if (key === "pro") return "Pro";
  return plan?.trim() || "";
}

export function planBadgeTone(plan?: string | null): {
  borderColor: string;
  color: string;
  backgroundColor: string;
} {
  const key = String(plan || "")
    .trim()
    .toLowerCase();
  if (key === "pro") {
    return { borderColor: "#7c3aed", color: "#c4b5fd", backgroundColor: "#2e1065" };
  }
  if (key === "standard") {
    return { borderColor: "#2563eb", color: "#93c5fd", backgroundColor: "#172554" };
  }
  return { borderColor: "#475569", color: "#94a3b8", backgroundColor: "#1e293b" };
}

interface UserChipProps {
  picture?: string | null;
  plan?: string | null;
  name?: string | null;
}

/** Avatar + plan badge — mirrors web `#userChip`. */
export function UserChip({ picture, plan, name }: UserChipProps) {
  const label = formatPlanLabel(plan);
  const tone = planBadgeTone(plan);
  const showAvatar = Boolean(picture);
  const showBadge = Boolean(label);

  if (!showAvatar && !showBadge) return null;

  return (
    <View style={styles.row} accessibilityLabel={[name, label].filter(Boolean).join(", ") || "Account"}>
      {showAvatar ? (
        <Image source={{ uri: String(picture) }} style={styles.avatar} accessibilityIgnoresInvertColors />
      ) : null}
      {showBadge ? (
        <View style={[styles.badge, { borderColor: tone.borderColor, backgroundColor: tone.backgroundColor }]}>
          <Text style={[styles.badgeText, { color: tone.color }]}>{label.toUpperCase()}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  avatar: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.surfaceAlt,
  },
  badge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 7,
    paddingVertical: 2,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
});
