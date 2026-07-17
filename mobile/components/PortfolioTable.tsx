import { Link, router } from "expo-router";
import { useRef, useState } from "react";
import {
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type RefreshControlProps,
} from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
import { TradeBandBar, tradeBandTooltipText } from "@/components/TradeBandBar";
import {
  formatMoney,
  formatPct,
  formatPrice,
  formatQty,
  formatWeight,
  pctColor,
} from "@/lib/format";
import {
  cyclePortfolioSort,
  portfolioTableColumns,
  sortHeaderLabel,
  type PortfolioColumn,
  type PortfolioSortKey,
  type PortfolioSortState,
} from "@/lib/portfolioTable";
import { colors, spacing } from "@/lib/theme";
import type { PortfolioRow } from "@/lib/types";

const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 36;
const TRADE_TIP_KEYS: PortfolioSortKey[] = ["dayChangePct", "tradeBand", "quantity"];

interface PortfolioTableProps {
  rows: PortfolioRow[];
  sort: PortfolioSortState;
  onSortChange: (sort: PortfolioSortState) => void;
  landscape?: boolean;
  refreshControl?: React.ReactElement<RefreshControlProps>;
}

function renderCell(row: PortfolioRow, col: PortfolioColumn): string {
  if (col.key === "symbol" || col.key === "sai") return "";
  const value = row[col.key as keyof PortfolioRow];
  if (col.key === "quantity") return formatQty(value as number | null);
  if (col.key === "weightPct") return formatWeight(value as number | null);
  if (col.pct) return formatPct(value as number | null);
  if (col.money) return formatMoney(value as number | null, true);
  if (col.price) return formatPrice(value as number | null);
  if (value == null || value === "") return "—";
  return String(value);
}

function cellColor(row: PortfolioRow, col: PortfolioColumn): string {
  if (!col.pct) return colors.text;
  const value = row[col.key as keyof PortfolioRow] as number | null | undefined;
  return pctColor(value);
}

function SortHeader({
  col,
  sort,
  onPress,
  width,
}: {
  col: PortfolioColumn;
  sort: PortfolioSortState;
  onPress: () => void;
  width: number;
}) {
  const active = sort.key === col.key;
  return (
    <Pressable
      style={[
        styles.headerCell,
        { width },
        active && styles.headerCellActive,
        col.align === "right" && styles.headerCellRight,
      ]}
      onPress={onPress}
    >
      <Text
        style={[styles.headerText, col.align === "right" && styles.alignRight]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.85}
      >
        {sortHeaderLabel(col.label, col.key, sort)}
      </Text>
    </Pressable>
  );
}

export function PortfolioTable({
  rows,
  sort,
  onSortChange,
  landscape = false,
  refreshControl,
}: PortfolioTableProps) {
  const { sticky: stickyColumns, scroll: scrollColumns } = portfolioTableColumns(landscape);
  const stickyWidth = stickyColumns.reduce((sum, col) => sum + col.width, 0);
  const symbolWidth = stickyColumns[0].width;
  const saiWidth = stickyColumns[1].width;
  const tableWidth = scrollColumns.reduce((sum, col) => sum + col.width, 0);
  const scrollX = useRef(new Animated.Value(0)).current;
  const [tipSymbol, setTipSymbol] = useState<string | null>(null);
  const longPressedRef = useRef(false);

  function handleHeaderSort(key: PortfolioSortKey) {
    onSortChange(cyclePortfolioSort(sort, key));
  }

  function openDetails(symbol: string) {
    if (longPressedRef.current) return;
    setTipSymbol(null);
    router.push(`/symbol/${symbol}`);
  }

  return (
    <View style={styles.wrap}>
      <View style={styles.headerRow}>
        <View style={[styles.stickyHeader, { width: stickyWidth }]}>
          {stickyColumns.map((col) => (
            <SortHeader
              key={col.key}
              col={col}
              sort={sort}
              width={col.width}
              onPress={() => handleHeaderSort(col.key)}
            />
          ))}
        </View>
        <View style={styles.scrollHeaderClip}>
          <Animated.View
            style={[
              styles.scrollHeaderInner,
              { width: tableWidth, transform: [{ translateX: Animated.multiply(scrollX, -1) }] },
            ]}
          >
            {scrollColumns.map((col) => (
              <SortHeader
                key={col.key}
                col={col}
                sort={sort}
                width={col.width}
                onPress={() => handleHeaderSort(col.key)}
              />
            ))}
          </Animated.View>
        </View>
      </View>

      <View style={styles.bodyWrap}>
        {tipSymbol ? (
          <View style={styles.tipBanner} pointerEvents="none">
            <Text style={styles.tipBannerSymbol}>{tipSymbol}</Text>
            <Text style={styles.tipBannerText}>
              {tradeBandTooltipText(rows.find((r) => r.symbol === tipSymbol) ?? { symbol: tipSymbol }) ??
                ""}
            </Text>
          </View>
        ) : null}

        <ScrollView
          style={styles.bodyScroll}
          nestedScrollEnabled
          showsVerticalScrollIndicator
          refreshControl={refreshControl}
        >
        <View style={styles.bodyRow}>
          <View style={[styles.stickyBody, { width: stickyWidth }]}>
            {rows.map((row) => (
              <View key={row.symbol} style={[styles.stickyDataRow, { width: stickyWidth }]}>
                <View style={[styles.symbolCell, { width: symbolWidth }]}>
                  <Link href={`/symbol/${row.symbol}`} asChild>
                    <Pressable style={styles.symbolPress}>
                      <Text style={styles.symbol} numberOfLines={1}>
                        {row.symbol}
                      </Text>
                    </Pressable>
                  </Link>
                </View>
                <View style={[styles.saiCell, { width: saiWidth }]}>
                  <SaiBadge action={row.saiAction} mini />
                </View>
              </View>
            ))}
          </View>

          <Animated.ScrollView
            horizontal
            showsHorizontalScrollIndicator
            scrollEventThrottle={16}
            onScroll={Animated.event([{ nativeEvent: { contentOffset: { x: scrollX } } }], {
              useNativeDriver: true,
            })}
            style={styles.scrollBody}
            contentContainerStyle={{ width: tableWidth }}
          >
            <View style={{ width: tableWidth }}>
              {rows.map((row) => {
                const tipActive = tipSymbol === row.symbol;
                return (
                  <View key={row.symbol} style={styles.scrollDataRow}>
                    {scrollColumns.map((col) => {
                      const supportsTradeTip = TRADE_TIP_KEYS.includes(col.key);
                      const content = col.tradeBand ? (
                        <TradeBandBar
                          row={row}
                          width={col.width - spacing.xs}
                          active={tipActive}
                        />
                      ) : (
                        <Text
                          style={[
                            styles.cellText,
                            col.align === "right" && styles.alignRight,
                            { color: cellColor(row, col) },
                          ]}
                          numberOfLines={1}
                        >
                          {renderCell(row, col)}
                        </Text>
                      );

                      return (
                        <Pressable
                          key={col.key}
                          style={[
                            styles.dataCell,
                            { width: col.width },
                            col.align === "right" && styles.alignRightCell,
                            col.tradeBand && styles.tradeBandCell,
                            tipActive && supportsTradeTip && styles.dataCellTipActive,
                          ]}
                          onPress={() => openDetails(row.symbol)}
                          onLongPress={
                            supportsTradeTip
                              ? () => {
                                  longPressedRef.current = true;
                                  if (tradeBandTooltipText(row)) setTipSymbol(row.symbol);
                                }
                              : undefined
                          }
                          onPressOut={() => {
                            if (tipSymbol === row.symbol) setTipSymbol(null);
                            requestAnimationFrame(() => {
                              longPressedRef.current = false;
                            });
                          }}
                          delayLongPress={320}
                        >
                          {content}
                        </Pressable>
                      );
                    })}
                  </View>
                );
              })}
            </View>
          </Animated.ScrollView>
        </View>
      </ScrollView>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
  },
  headerRow: {
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    zIndex: 2,
    elevation: 2,
  },
  stickyHeader: {
    flexShrink: 0,
    flexDirection: "row",
    backgroundColor: colors.surface,
    zIndex: 3,
    overflow: "hidden",
    elevation: 3,
  },
  headerCell: {
    flexShrink: 0,
    height: HEADER_HEIGHT,
    justifyContent: "center",
    paddingHorizontal: spacing.xs,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    overflow: "hidden",
  },
  headerCellActive: {
    backgroundColor: colors.surfaceAlt,
  },
  headerText: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  scrollHeaderClip: {
    flex: 1,
    overflow: "hidden",
  },
  scrollHeaderInner: {
    flexDirection: "row",
    height: HEADER_HEIGHT,
    alignItems: "center",
  },
  bodyWrap: {
    flex: 1,
    position: "relative",
  },
  bodyScroll: {
    flex: 1,
  },
  bodyRow: {
    flexDirection: "row",
  },
  stickyBody: {
    flexShrink: 0,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    backgroundColor: colors.bg,
  },
  stickyDataRow: {
    flexDirection: "row",
    height: ROW_HEIGHT,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    alignItems: "center",
    flexShrink: 0,
  },
  symbolCell: {
    flexShrink: 0,
    justifyContent: "center",
    paddingLeft: spacing.sm,
    paddingRight: spacing.xs,
    minHeight: ROW_HEIGHT,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    overflow: "hidden",
  },
  symbolPress: {
    justifyContent: "center",
    minHeight: ROW_HEIGHT,
  },
  saiCell: {
    flexShrink: 0,
    flexDirection: "row",
    justifyContent: "flex-end",
    alignItems: "center",
    height: ROW_HEIGHT,
    paddingLeft: 0,
    paddingRight: spacing.sm,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    overflow: "hidden",
  },
  headerCellRight: {
    alignItems: "flex-end",
  },
  symbol: {
    color: colors.link,
    fontSize: 14,
    fontWeight: "700",
  },
  scrollBody: {
    flex: 1,
  },
  scrollDataRow: {
    flexDirection: "row",
    alignItems: "center",
    height: ROW_HEIGHT,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  tipBanner: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 20,
    elevation: 20,
    backgroundColor: "rgba(11, 18, 32, 0.82)",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "rgba(71, 85, 105, 0.7)",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 2,
  },
  tipBannerSymbol: {
    color: colors.link,
    fontSize: 12,
    fontWeight: "800",
  },
  tipBannerText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "600",
    lineHeight: 16,
  },
  dataCell: {
    flexShrink: 0,
    justifyContent: "center",
    paddingHorizontal: spacing.xs,
    height: ROW_HEIGHT,
  },
  dataCellTipActive: {
    backgroundColor: "rgba(148, 163, 184, 0.12)",
  },
  tradeBandCell: {
    overflow: "visible",
    zIndex: 1,
  },
  cellText: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "500",
  },
  alignRight: {
    textAlign: "right",
  },
  alignRightCell: {
    alignItems: "flex-end",
  },
});
