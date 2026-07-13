import { Link } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
import { formatPct, formatPrice, pctColor } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { PortfolioSymbol } from "@/lib/types";

interface SymbolRowProps {
  item: PortfolioSymbol;
  showWeight?: boolean;
  weightPct?: number | null;
}

export function SymbolRow({ item, showWeight, weightPct }: SymbolRowProps) {
  const assessment = item.latestAssessment;
  return (
    <Link href={`/symbol/${item.symbol}`} asChild>
      <Pressable style={styles.row}>
        <View style={styles.left}>
          <Text style={styles.symbol}>{item.symbol}</Text>
          {showWeight && weightPct != null ? (
            <Text style={styles.meta}>{weightPct.toFixed(1)}% wt</Text>
          ) : null}
        </View>
        <View style={styles.mid}>
          <SaiBadge action={assessment?.action} compact />
        </View>
        <View style={styles.right}>
          <Text style={styles.price}>{formatPrice(item.currentPrice)}</Text>
          <Text style={[styles.pct, { color: pctColor(item.dayChangePct) }]}>
            {formatPct(item.dayChangePct)}
          </Text>
        </View>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: spacing.sm,
  },
  left: {
    width: 72,
  },
  symbol: {
    color: colors.link,
    fontSize: 16,
    fontWeight: "700",
  },
  meta: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: 2,
  },
  mid: {
    flex: 1,
  },
  right: {
    alignItems: "flex-end",
    minWidth: 88,
  },
  price: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "600",
  },
  pct: {
    fontSize: 12,
    marginTop: 2,
  },
});
