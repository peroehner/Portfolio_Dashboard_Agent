import { StyleSheet, Text, View } from "react-native";

import { confluenceBiasColor } from "@/lib/inspectorHelpers";
import { colors, radii, spacing } from "@/lib/theme";
import type { ConfluencePayload } from "@/lib/types";

interface ConfluencePanelProps {
  confluence?: ConfluencePayload | null;
}

function voteArrow(direction?: string): string {
  if (direction === "bull") return "↑";
  if (direction === "bear") return "↓";
  return "·";
}

export function ConfluencePanel({ confluence }: ConfluencePanelProps) {
  if (!confluence?.bias) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>Technical Confluence</Text>
        <Text style={styles.muted}>Insufficient technical data for a fused verdict.</Text>
      </View>
    );
  }

  const score100 = confluence.score100 ?? 50;
  const biasColor = confluenceBiasColor(confluence.bias);
  const strengthTxt = [
    confluence.strength,
    `${confluence.agreeCount ?? 0}/${confluence.totalSignals ?? 0} agree`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Technical Confluence</Text>
      <View style={styles.headRow}>
        <Text style={[styles.bias, { color: biasColor }]}>{confluence.bias}</Text>
        <Text style={styles.muted}>{strengthTxt}</Text>
      </View>
      <View style={styles.meter}>
        <View style={[styles.meterFill, { width: `${score100}%`, backgroundColor: biasColor }]} />
      </View>
      <View style={styles.votes}>
        {(confluence.votes ?? []).map((vote, idx) => (
          <Text key={`${vote.agent}-${idx}`} style={styles.voteChip}>
            {voteArrow(vote.direction)} {vote.agent}
          </Text>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
  },
  headRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  bias: {
    fontSize: 16,
    fontWeight: "800",
  },
  muted: {
    color: colors.textMuted,
    fontSize: 12,
    flexShrink: 1,
    textAlign: "right",
  },
  meter: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceAlt,
    overflow: "hidden",
  },
  meterFill: {
    height: "100%",
    borderRadius: 3,
    opacity: 0.85,
  },
  votes: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  voteChip: {
    color: colors.textMuted,
    fontSize: 11,
    backgroundColor: colors.surfaceAlt,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 4,
    overflow: "hidden",
  },
});
