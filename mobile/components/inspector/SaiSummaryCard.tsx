import { StyleSheet, Text, View } from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
import {
  getRecommendationText,
  headlineForAction,
  sentimentStyle,
} from "@/lib/inspectorHelpers";
import { titleCaseAction } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface SaiSummaryCardProps {
  data?: InspectorPayload | null;
}

export function SaiSummaryCard({ data }: SaiSummaryCardProps) {
  const rec = data?.recommendation;
  const body = getRecommendationText(data);
  const sentiment = rec?.sentiment ?? "neutral";
  const headline = rec?.headline?.trim() || headlineForAction(rec?.action, sentiment);

  if (!rec?.action && !headline && !body) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>SAI</Text>
        <Text style={styles.empty}>No assessment yet.</Text>
      </View>
    );
  }

  const sentStyle = sentimentStyle(sentiment);

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <Text style={styles.title}>SAI</Text>
        <View style={styles.chips}>
          <SaiBadge action={rec?.action} compact />
          {rec?.confidence ? (
            <Text style={styles.confidence}>{rec.confidence}</Text>
          ) : null}
          <View
            style={[
              styles.sentimentChip,
              {
                backgroundColor: sentStyle.backgroundColor,
                borderColor: sentStyle.borderColor,
              },
            ]}
          >
            <Text style={[styles.sentimentText, { color: sentStyle.color }]}>
              {titleCaseAction(sentiment)}
            </Text>
          </View>
        </View>
      </View>
      {headline ? <Text style={styles.headline}>{headline}</Text> : null}
      {body ? <Text style={styles.body}>{body}</Text> : null}
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
    gap: spacing.xs,
  },
  headRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "800",
  },
  chips: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexShrink: 1,
    flexWrap: "wrap",
    justifyContent: "flex-end",
  },
  confidence: {
    color: colors.textMuted,
    fontSize: 11,
    textTransform: "capitalize",
  },
  sentimentChip: {
    borderWidth: 1,
    borderRadius: radii.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  sentimentText: {
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  headline: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "600",
    lineHeight: 19,
  },
  body: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  empty: {
    color: colors.textMuted,
    fontSize: 13,
  },
});
