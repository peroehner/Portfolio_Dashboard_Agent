import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
import { formatRelativeDate } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { NewsItem, RecommendationChange } from "@/lib/types";

export function NewsCard({ item }: { item: NewsItem }) {
  return (
    <View style={styles.card}>
      <View style={styles.metaRow}>
        <Link href={`/symbol/${item.symbol}`} asChild>
          <Pressable>
            <Text style={styles.symbol}>{item.symbol}</Text>
          </Pressable>
        </Link>
        {item.published ? (
          <Text style={styles.date}>{formatRelativeDate(item.published)}</Text>
        ) : null}
      </View>
      <Text style={styles.title}>{item.title || "Untitled"}</Text>
      {item.publisher ? <Text style={styles.publisher}>{item.publisher}</Text> : null}
      {item.summary ? (
        <Text style={styles.summary} numberOfLines={3}>
          {item.summary}
        </Text>
      ) : null}
    </View>
  );
}

export function SaiChangeCard({ change }: { change: RecommendationChange }) {
  return (
    <View style={styles.card}>
      <View style={styles.metaRow}>
        <Link href={`/symbol/${change.symbol}`} asChild>
          <Pressable>
            <Text style={styles.symbol}>{change.symbol}</Text>
          </Pressable>
        </Link>
        {change.changedAt ? (
          <Text style={styles.date}>{formatRelativeDate(change.changedAt)}</Text>
        ) : null}
      </View>
      <View style={styles.changeRow}>
        <SaiBadge action={change.oldAction} compact />
        <Text style={styles.arrow}>→</Text>
        <SaiBadge action={change.newAction} compact />
      </View>
      {change.rationale ? (
        <Text style={styles.summary} numberOfLines={4}>
          {change.rationale}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    padding: spacing.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.xs,
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  symbol: {
    color: colors.link,
    fontWeight: "700",
    fontSize: 14,
  },
  date: {
    color: colors.textMuted,
    fontSize: 11,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "600",
    lineHeight: 20,
  },
  publisher: {
    color: colors.textMuted,
    fontSize: 12,
  },
  summary: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginTop: spacing.xs,
  },
  changeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  arrow: {
    color: colors.textMuted,
    fontSize: 14,
  },
});
