import { Ionicons } from "@expo/vector-icons";
import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
import { formatRelativeDate } from "@/lib/format";
import { headlineForAction } from "@/lib/inspectorHelpers";
import { changeTimestamp } from "@/lib/newsFilters";
import { colors, radii, spacing } from "@/lib/theme";
import type { NewsItem, RecommendationChange } from "@/lib/types";

interface CompactProps {
  compact?: boolean;
}

interface NewsCardProps extends CompactProps {
  item: NewsItem;
  onAddNote?: (item: NewsItem) => void;
}

export function NewsCard({ item, compact, onAddNote }: NewsCardProps) {
  return (
    <View style={[styles.card, compact && styles.cardCompact]}>
      <View style={styles.metaRow}>
        <Link href={`/symbol/${item.symbol}`} asChild>
          <Pressable style={styles.symbolPress}>
            <Text style={[styles.symbol, compact && styles.symbolCompact]} numberOfLines={1}>
              {item.symbol}
            </Text>
          </Pressable>
        </Link>
        <View style={styles.metaRight}>
          {item.published ? (
            <Text style={styles.date}>{formatRelativeDate(item.published)}</Text>
          ) : null}
          {onAddNote ? (
            <Pressable
              onPress={() => onAddNote(item)}
              hitSlop={8}
              accessibilityLabel="Add note from news"
            >
              <Ionicons name="create-outline" size={compact ? 16 : 18} color={colors.link} />
            </Pressable>
          ) : null}
        </View>
      </View>
      <Text style={[styles.title, compact && styles.titleCompact]} numberOfLines={compact ? 3 : undefined}>
        {item.title || "Untitled"}
      </Text>
      {!compact && item.publisher ? <Text style={styles.publisher}>{item.publisher}</Text> : null}
      {item.summary ? (
        <Text style={styles.summary} numberOfLines={compact ? 2 : 3}>
          {item.summary}
        </Text>
      ) : null}
    </View>
  );
}

export function SaiChangeCard({ change, compact }: { change: RecommendationChange } & CompactProps) {
  const ts = changeTimestamp(change);
  const metaParts = [
    ts ? formatRelativeDate(ts) : "",
    change.newConfidence ? `${change.newConfidence} confidence` : "",
  ].filter(Boolean);
  const meta = metaParts.join(" · ");

  if (compact) {
    return (
      <View style={[styles.card, styles.cardCompact]}>
        <View style={styles.metaRow}>
          <Link href={`/symbol/${change.symbol}`} asChild>
            <Pressable style={styles.symbolPress}>
              <Text style={[styles.symbol, styles.symbolCompact]} numberOfLines={1}>
                {change.symbol}
              </Text>
            </Pressable>
          </Link>
          {meta ? <Text style={styles.date}>{meta}</Text> : null}
        </View>
        <View style={styles.changeRow}>
          <SaiBadge action={change.oldAction} compact />
          <Text style={styles.arrow}>→</Text>
          <SaiBadge action={change.newAction} compact />
        </View>
      </View>
    );
  }

  return (
    <Link href={`/symbol/${change.symbol}`} asChild>
      <Pressable style={styles.card}>
        <View style={styles.recoRow}>
          <View style={styles.recoLeft}>
            <View style={styles.recoLine}>
              <Text style={styles.symbol}>{change.symbol}</Text>
              <SaiBadge action={change.oldAction} compact />
              <Text style={styles.arrow}>→</Text>
              <SaiBadge action={change.newAction} compact />
            </View>
            {meta ? <Text style={styles.recoMeta}>{meta}</Text> : null}
          </View>
          <Text style={styles.recoHeadline} numberOfLines={3} ellipsizeMode="tail">
            {headlineForAction(change.newAction)}
          </Text>
        </View>
      </Pressable>
    </Link>
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
  cardCompact: {
    padding: spacing.sm,
    marginHorizontal: spacing.xs,
    marginBottom: spacing.xs,
    borderRadius: radii.sm,
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.xs,
  },
  metaRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
  },
  symbolPress: {
    flexShrink: 1,
    minWidth: 0,
  },
  symbol: {
    color: colors.link,
    fontWeight: "700",
    fontSize: 14,
  },
  symbolCompact: {
    fontSize: 12,
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
  titleCompact: {
    fontSize: 13,
    lineHeight: 17,
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
    gap: spacing.xs,
    marginTop: 2,
  },
  recoLine: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  recoRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
  },
  recoLeft: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  recoHeadline: {
    flex: 1,
    minWidth: 0,
    color: colors.text,
    fontSize: 12,
    fontWeight: "600",
    lineHeight: 16,
    textAlign: "right",
  },
  recoMeta: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: 2,
  },
  arrow: {
    color: colors.textMuted,
    fontSize: 12,
  },
});
