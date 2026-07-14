import { Link } from "expo-router";
import { useRef } from "react";
import {
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type RefreshControlProps,
} from "react-native";

import { SaiBadge } from "@/components/SaiBadge";
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
      <Text style={[styles.headerText, col.align === "right" && styles.alignRight]}>
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
  const headerScrollRef = useRef<ScrollView>(null);
  const bodyScrollRef = useRef<ScrollView>(null);
  const syncing = useRef(false);

  function handleHeaderSort(key: PortfolioSortKey) {
    onSortChange(cyclePortfolioSort(sort, key));
  }

  function syncHorizontalScroll(source: "header" | "body") {
    return (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      if (syncing.current) return;
      syncing.current = true;
      const x = event.nativeEvent.contentOffset.x;
      const target = source === "header" ? bodyScrollRef.current : headerScrollRef.current;
      target?.scrollTo({ x, animated: false });
      syncing.current = false;
    };
  }

  return (
    <View style={styles.wrap}>
      <View style={styles.headerRow}>
        <View style={{ width: stickyWidth, flexShrink: 0, flexDirection: "row" }}>
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
        <ScrollView
          ref={headerScrollRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          scrollEventThrottle={16}
          onScroll={syncHorizontalScroll("header")}
          style={styles.scrollHeader}
          contentContainerStyle={{ width: tableWidth }}
        >
          <View style={[styles.scrollHeaderInner, { width: tableWidth }]}>
            {scrollColumns.map((col) => (
              <SortHeader
                key={col.key}
                col={col}
                sort={sort}
                width={col.width}
                onPress={() => handleHeaderSort(col.key)}
              />
            ))}
          </View>
        </ScrollView>
      </View>

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

          <ScrollView
            ref={bodyScrollRef}
            horizontal
            showsHorizontalScrollIndicator
            scrollEventThrottle={16}
            onScroll={syncHorizontalScroll("body")}
            style={styles.scrollBody}
            contentContainerStyle={{ width: tableWidth }}
          >
            <View style={{ width: tableWidth }}>
              {rows.map((row) => (
                <Link key={row.symbol} href={`/symbol/${row.symbol}`} asChild>
                  <Pressable style={styles.scrollDataRow}>
                    {scrollColumns.map((col) => (
                      <View key={col.key} style={[styles.dataCell, { width: col.width }]}>
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
                      </View>
                    ))}
                  </Pressable>
                </Link>
              ))}
            </View>
          </ScrollView>
        </View>
      </ScrollView>
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
  },
  headerCell: {
    flexShrink: 0,
    height: HEADER_HEIGHT,
    justifyContent: "center",
    paddingHorizontal: spacing.sm,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
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
  scrollHeader: {
    flex: 1,
  },
  scrollHeaderInner: {
    flexDirection: "row",
    height: HEADER_HEIGHT,
    alignItems: "center",
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
    minHeight: ROW_HEIGHT,
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
    paddingLeft: 0,
    paddingRight: spacing.sm,
    minHeight: ROW_HEIGHT,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    overflow: "hidden",
  },
  headerCellRight: {
    flexDirection: "row",
    justifyContent: "flex-end",
    alignItems: "center",
    paddingLeft: 0,
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
    minHeight: ROW_HEIGHT,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  dataCell: {
    justifyContent: "center",
    paddingHorizontal: spacing.xs,
  },
  cellText: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "500",
  },
  alignRight: {
    textAlign: "right",
  },
});
