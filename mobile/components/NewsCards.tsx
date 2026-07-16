import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
import { formatRelativeDate, formatShortDateTime } from "@/lib/format";
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
  onOpenNews?: (item: NewsItem) => void;
}

interface SaiChangeCardProps extends CompactProps {
  change: RecommendationChange;
  onOpenPortfolio?: (symbol: string) => void;
}

function SymbolLink({
  symbol,
  compact,
}: {
  symbol: string;
  compact?: boolean;
}) {
  return (
    <Pressable
      style={styles.symbolPress}
      onPress={() => router.push(`/symbol/${symbol}`)}
      hitSlop={4}
    >
      <Text style={[styles.symbol, compact && styles.symbolCompact]} numberOfLines={1}>
        {symbol}
      </Text>
    </Pressable>
  );
}

export function NewsCard({ item, compact, onAddNote, onOpenNews }: NewsCardProps) {
  return (
    <Pressable
      style={[styles.card, compact && styles.cardCompact]}
      onPress={() => onOpenNews?.(item)}
      disabled={!onOpenNews}
    >
      <View style={styles.metaRow}>
        <SymbolLink symbol={item.symbol} compact={compact} />
        <View style={styles.metaRight}>
          {item.published ? (
            <Text style={styles.date}>{formatRelativeDate(item.published)}</Text>
          ) : null}
          {onAddNote ? (
            <Pressable
              onPress={(e) => {
                e.stopPropagation();
                onAddNote(item);
              }}
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
    </Pressable>
  );
}

export function SaiChangeCard({ change, compact, onOpenPortfolio }: SaiChangeCardProps) {
  const ts = changeTimestamp(change);
  const metaParts = [
    ts ? formatShortDateTime(ts) : "",
    change.newConfidence ? `${change.newConfidence} confidence` : "",
  ].filter(Boolean);
  const meta = metaParts.join(" · ");

  if (compact) {
    return (
      <Pressable
        style={[styles.card, styles.cardCompact]}
        onPress={() => onOpenPortfolio?.(change.symbol)}
        disabled={!onOpenPortfolio}
      >
        <View style={styles.metaRow}>
          <SymbolLink symbol={change.symbol} compact />
          {meta ? <Text style={styles.date}>{meta}</Text> : null}
        </View>
        <View style={styles.changeRow}>
          <SaiBadge action={change.oldAction} compact />
          <Text style={styles.arrow}>→</Text>
          <SaiBadge action={change.newAction} compact />
        </View>
      </Pressable>
    );
  }

  return (
    <Pressable
      style={styles.card}
      onPress={() => onOpenPortfolio?.(change.symbol)}
      disabled={!onOpenPortfolio}
    >
      <View style={styles.recoRow}>
        <View style={styles.recoLeft}>
          <View style={styles.recoLine}>
            <SymbolLink symbol={change.symbol} />
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
