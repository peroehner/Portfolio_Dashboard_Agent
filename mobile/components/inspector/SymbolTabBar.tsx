import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";

export type SymbolTab = "summary" | "technical";

const TABS: { key: SymbolTab; label: string }[] = [
  { key: "summary", label: "Summary" },
  { key: "technical", label: "Technical" },
];

interface SymbolTabBarProps {
  active: SymbolTab;
  onChange: (tab: SymbolTab) => void;
}

export function SymbolTabBar({ active, onChange }: SymbolTabBarProps) {
  return (
    <View style={styles.row}>
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <Pressable
            key={tab.key}
            style={[styles.pill, isActive && styles.pillActive]}
            onPress={() => onChange(tab.key)}
          >
            <Text style={[styles.pillText, isActive && styles.pillTextActive]}>
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
  },
  pill: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingVertical: 7,
    alignItems: "center",
    backgroundColor: colors.surface,
  },
  pillActive: {
    borderColor: colors.accent,
    backgroundColor: colors.surfaceAlt,
  },
  pillText: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: "600",
  },
  pillTextActive: {
    color: colors.text,
  },
});
