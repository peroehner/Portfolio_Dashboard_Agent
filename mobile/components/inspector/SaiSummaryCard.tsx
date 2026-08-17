import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import { AlertMessageText } from "@/components/AlertRow";
import { SaiBadge } from "@/components/SaiBadge";
import { emphasizeDriverText } from "@/lib/driverHighlight";
import {
  getRecommendationDrivers,
  getRecommendationText,
  getWatchItems,
  headlineForAction,
  sentimentStyle,
} from "@/lib/inspectorHelpers";
import { formatShortDateTime, titleCaseAction } from "@/lib/format";
import {
  resolveSaiAttention,
  saiConfidenceLabel,
  saiIntentCode,
  saiIntentLabel,
} from "@/lib/saiDisplay";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface SaiSummaryCardProps {
  data?: InspectorPayload | null;
}

export function SaiSummaryCard({ data }: SaiSummaryCardProps) {
  const rec = data?.recommendation;
  const proposal = rec?.proposal;
  const body = getRecommendationText(data);
  const drivers = getRecommendationDrivers(data);
  const watchItems = getWatchItems(data);
  const sentiment = rec?.sentiment ?? "neutral";
  const headline =
    rec?.headline?.trim() || headlineForAction(rec?.action, sentiment, watchItems);
  const assessedAt = rec?.assessedAt ? formatShortDateTime(rec.assessedAt) : "";
  const attention = resolveSaiAttention(rec?.action, proposal);
  const confLabel = saiConfidenceLabel(rec?.confidence, proposal);
  const intentCode = saiIntentCode(proposal);
  const intentLabel = saiIntentLabel(proposal);
  const intentKey = String(intentCode || "").toLowerCase();
  const intentTone = intentKey.startsWith("divest")
    ? { icon: "exit-outline" as const, color: colors.sell, bg: "rgba(248,113,113,0.16)", border: "rgba(248,113,113,0.45)" }
    : intentKey.startsWith("tactical")
      ? { icon: "construct-outline" as const, color: "#f59e0b", bg: "rgba(245,158,11,0.16)", border: "rgba(245,158,11,0.45)" }
      : intentKey.startsWith("accumulate")
        ? { icon: "trending-up-outline" as const, color: colors.buy, bg: "rgba(74,222,128,0.16)", border: "rgba(74,222,128,0.45)" }
        : intentKey.startsWith("core")
          ? { icon: "shield-checkmark-outline" as const, color: "#60a5fa", bg: "rgba(96,165,250,0.16)", border: "rgba(96,165,250,0.45)" }
          : { icon: "person-circle-outline" as const, color: colors.textMuted, bg: colors.surfaceAlt, border: colors.border };

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
        <View style={styles.headMain}>
          <Text style={styles.title}>SAI</Text>
          <View style={styles.chips}>
            <View style={styles.saiSignals}>
              <SaiBadge
                action={rec?.action}
                proposal={proposal}
                attention={attention.flag}
                compact
              />
              {confLabel ? (
                <Text
                  style={styles.confidence}
                  numberOfLines={1}
                  accessibilityLabel={`Confidence ${confLabel}`}
                >
                  {confLabel}
                </Text>
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
            {intentCode ? (
              <View
                style={[
                  styles.intentChip,
                  { backgroundColor: intentTone.bg, borderColor: intentTone.border },
                ]}
                accessibilityLabel={intentLabel || `Portfolio Intent ${intentCode}`}
              >
                <Ionicons name={intentTone.icon} size={13} color={intentTone.color} />
                <Text style={[styles.intentCodeText, { color: intentTone.color }]} numberOfLines={1}>
                  {intentLabel || intentCode}
                </Text>
              </View>
            ) : null}
          </View>
        </View>
        {assessedAt ? <Text style={styles.assessedAt}>{assessedAt}</Text> : null}
      </View>
      {attention.flag && attention.message ? (
        <Text style={styles.attentionNote}>{attention.message}</Text>
      ) : null}
      {headline ? <Text style={styles.headline}>{headline}</Text> : null}
      {body ? (
        <AlertMessageText
          message={emphasizeDriverText(body)}
          style={styles.body}
          boldStyle={styles.bodyBold}
        />
      ) : null}
      {drivers.length > 0 ? (
        <View style={styles.drivers}>
          {drivers.map((reason, idx) => (
            <View key={idx} style={styles.driverRow}>
              <Text style={styles.driverBullet}>·</Text>
              <View style={styles.driverTextWrap}>
                <AlertMessageText
                  message={emphasizeDriverText(reason)}
                  style={styles.driverText}
                  boldStyle={styles.bodyBold}
                />
              </View>
            </View>
          ))}
        </View>
      ) : null}
      {watchItems.length > 0 ? (
        <View style={styles.watch}>
          <Text style={styles.watchLabel}>What to watch</Text>
          {watchItems.map((item, idx) => (
            <View key={idx} style={styles.driverRow}>
              <Text style={styles.driverBullet}>·</Text>
              <View style={styles.driverTextWrap}>
                <AlertMessageText
                  message={emphasizeDriverText(item)}
                  style={styles.driverText}
                  boldStyle={styles.bodyBold}
                />
              </View>
            </View>
          ))}
        </View>
      ) : null}
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
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  headMain: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    flex: 1,
    minWidth: 0,
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
    gap: spacing.md,
    flexShrink: 1,
    flexWrap: "wrap",
    justifyContent: "flex-start",
  },
  saiSignals: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  assessedAt: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
    lineHeight: 15,
    marginTop: 1,
  },
  confidence: {
    color: colors.textMuted,
    fontSize: 11,
    textTransform: "capitalize",
  },
  intentChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderRadius: radii.sm,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  intentCodeText: {
    fontSize: 10,
    fontWeight: "700",
    maxWidth: 120,
  },
  attentionNote: {
    color: colors.watch,
    fontSize: 11,
    fontWeight: "600",
    lineHeight: 15,
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
    fontWeight: "700",
    lineHeight: 19,
  },
  body: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  bodyBold: {
    color: colors.text,
    fontWeight: "800",
  },
  drivers: {
    marginTop: spacing.xs,
    gap: 4,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  watch: {
    marginTop: spacing.xs,
    gap: 4,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  watchLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.6,
    textTransform: "uppercase",
    marginBottom: 2,
  },
  driverRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
  },
  driverBullet: {
    color: colors.link,
    fontSize: 13,
    fontWeight: "800",
    lineHeight: 18,
  },
  driverTextWrap: {
    flex: 1,
    minWidth: 0,
  },
  driverText: {
    color: colors.textMuted,
    fontSize: 12,
    lineHeight: 17,
  },
  empty: {
    color: colors.textMuted,
    fontSize: 13,
  },
});
