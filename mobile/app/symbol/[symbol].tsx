import { useLocalSearchParams, useNavigation } from "expo-router";
import { useLayoutEffect } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { AlertRow } from "@/components/AlertRow";
import { SaiBadge } from "@/components/SaiBadge";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { formatMoney, formatPct, formatPrice, pctColor } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

export default function SymbolDetailScreen() {
  const navigation = useNavigation();
  const { symbol } = useLocalSearchParams<{ symbol: string }>();
  const sym = String(symbol || "").toUpperCase();

  const { data, loading, error, refresh } = useApiQuery<InspectorPayload>(
    () => api.inspector(sym),
    [sym],
  );

  useLayoutEffect(() => {
    navigation.setOptions({
      title: sym,
      headerBackTitle: "Back",
      headerLargeTitle: false,
    });
  }, [navigation, sym, data?.companyName]);

  const quote = data?.quote;
  const mechanics = data?.positionMechanics;
  const recommendation = data?.recommendation;
  const screening = data?.screening;

  return (
    <Screen
      loading={loading && !data}
      error={error}
      onRetry={() => void refresh()}
    >
        <ScrollView
          refreshControl={
            <RefreshControl
              refreshing={loading && !!data}
              onRefresh={() => void refresh()}
              tintColor={colors.accent}
            />
          }
          contentContainerStyle={styles.scroll}
        >
          <View style={styles.hero}>
            {data?.companyName ? (
              <Text style={styles.company}>{data.companyName}</Text>
            ) : null}
            <Text style={styles.price}>{formatPrice(quote?.currentPrice)}</Text>
            <Text style={[styles.day, { color: pctColor(quote?.dayChangePct) }]}>
              {formatPct(quote?.dayChangePct)} today
            </Text>
            <View style={styles.recoRow}>
              <SaiBadge
                action={recommendation?.action}
                confidence={recommendation?.confidence}
              />
              {screening?.pScore != null ? (
                <Text style={styles.pScore}>P-Score {screening.pScore}</Text>
              ) : null}
            </View>
            {recommendation?.headline ? (
              <Text style={styles.headline}>{recommendation.headline}</Text>
            ) : null}
          </View>

          {mechanics?.quantity ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Position</Text>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Shares</Text>
                <Text style={styles.statValue}>{mechanics.quantity}</Text>
              </View>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Market value</Text>
                <Text style={styles.statValue}>{formatMoney(mechanics.marketValue)}</Text>
              </View>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Unrealized gain</Text>
                <Text style={[styles.statValue, { color: pctColor(mechanics.gainPct) }]}>
                  {formatMoney(mechanics.unrealizedGain)} ({formatPct(mechanics.gainPct)})
                </Text>
              </View>
              {mechanics.weightPct != null ? (
                <View style={styles.statRow}>
                  <Text style={styles.statLabel}>Weight</Text>
                  <Text style={styles.statValue}>{mechanics.weightPct.toFixed(1)}%</Text>
                </View>
              ) : null}
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Thresholds</Text>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Buy below</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.buyBelow)}</Text>
            </View>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Sell above</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.sellAbove)}</Text>
            </View>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Personal target</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.targetPrice)}</Text>
            </View>
            <View style={styles.statRow}>
              <Text style={styles.statLabel}>Analyst 1Y</Text>
              <Text style={styles.statValue}>{formatPrice(quote?.analystTarget1y)}</Text>
            </View>
          </View>

          {(recommendation?.reasons?.length ?? 0) > 0 ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Recommendation reasons</Text>
              {recommendation?.reasons?.map((reason, idx) => (
                <Text key={idx} style={styles.reason}>
                  • {reason}
                </Text>
              ))}
            </View>
          ) : null}

          {(data?.alerts?.length ?? 0) > 0 ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Active alerts</Text>
              {data?.alerts?.map((alert) => (
                <AlertRow key={alert.id} alert={alert} />
              ))}
            </View>
          ) : null}

          {(data?.assessments?.length ?? 0) > 0 ? (
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Recent assessments</Text>
              {data?.assessments?.slice(0, 3).map((item) => (
                <View key={item.id ?? item.createdAt} style={styles.assessment}>
                  <View style={styles.assessmentHead}>
                    <SaiBadge action={item.action} confidence={item.confidence} compact />
                    <Text style={styles.assessmentDate}>{item.createdAt}</Text>
                  </View>
                  {item.rationale ? (
                    <Text style={styles.reason} numberOfLines={4}>
                      {item.rationale}
                    </Text>
                  ) : null}
                </View>
              ))}
            </View>
          ) : null}
        </ScrollView>
      </Screen>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingBottom: spacing.xl },
  hero: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.lg,
    gap: spacing.sm,
  },
  company: {
    color: colors.textMuted,
    fontSize: 14,
  },
  price: {
    color: colors.text,
    fontSize: 36,
    fontWeight: "700",
  },
  day: {
    fontSize: 16,
    fontWeight: "600",
  },
  recoRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    marginTop: spacing.sm,
  },
  pScore: {
    color: colors.textMuted,
    fontSize: 13,
  },
  headline: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 22,
    marginTop: spacing.xs,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  cardTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
    marginBottom: spacing.xs,
  },
  statRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  statLabel: {
    color: colors.textMuted,
    fontSize: 14,
  },
  statValue: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "600",
    flexShrink: 1,
    textAlign: "right",
  },
  section: {
    marginTop: spacing.sm,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  reason: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  assessment: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  assessmentHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  assessmentDate: {
    color: colors.textMuted,
    fontSize: 11,
  },
});
