import { Link } from "expo-router";
import { useMemo, useRef } from "react";
import {
  Animated,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type RefreshControlProps,
} from "react-native";

import { RangeBar, TargetRangeBar } from "@/components/RangeBar";
import {
  cycleFundamentalsSort,
  fundamentalsColumns,
  renderFundamentalsCell,
  sortFundamentalsRows,
  sortHeaderLabel,
  type FundamentalsColumn,
  type FundamentalsSortKey,
  type FundamentalsSortState,
  type FundamentalsTab,
} from "@/lib/fundamentalsTable";
import { colors, spacing } from "@/lib/theme";
import type { FundamentalsRow } from "@/lib/types";

const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 40;

interface FundamentalsTableProps {
  rows: FundamentalsRow[];
  tab: FundamentalsTab;
  sort: FundamentalsSortState;
  onSortChange: (sort: FundamentalsSortState) => void;
  refreshControl?: React.ReactElement<RefreshControlProps>;
}

function SortHeader({
  col,
  sort,
  onPress,
  width,
}: {
  col: FundamentalsColumn;
  sort: FundamentalsSortState;
  onPress: () => void;
  width: number;
}) {
  const active = sort.key === col.key;
  const isRange = col.kind === "range52";
  return (
    <Pressable
      style={[
        styles.headerCell,
        { width },
        active && styles.headerCellActive,
        col.align === "right" && styles.headerCellAlignRight,
      ]}
      onPress={onPress}
    >
      <Text
        style={[
          styles.headerText,
          col.align === "right" && styles.alignRight,
          isRange && styles.headerTextRange,
        ]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.8}
      >
        {sortHeaderLabel(col.label, col.key, sort)}
      </Text>
    </Pressable>
  );
}

function StickyCell({
  row,
  col,
  width,
}: {
  row: FundamentalsRow;
  col: FundamentalsColumn;
  width: number;
}) {
  if (col.kind === "symbol") {
    return (
      <View style={[styles.symbolCell, { width }]}>
        <Link href={`/symbol/${row.symbol}`} asChild>
          <Pressable style={styles.symbolPress}>
            <Text style={styles.symbol} numberOfLines={1}>
              {row.symbol}
            </Text>
          </Pressable>
        </Link>
      </View>
    );
  }

  if (col.kind === "price") {
    const cell = renderFundamentalsCell(row, col);
    if ("custom" in cell) return null;
    return (
      <View style={[styles.dataCellSticky, { width }, styles.alignRightCell]}>
        <Text style={styles.cellText} numberOfLines={1}>
          {cell.text}
        </Text>
      </View>
    );
  }

  return null;
}

function ScrollCell({ row, col, width }: { row: FundamentalsRow; col: FundamentalsColumn; width: number }) {
  const rendered = renderFundamentalsCell(row, col);
  if ("custom" in rendered) {
    if (rendered.custom === "range52") {
      return (
        <View style={[styles.dataCell, { width }, styles.alignRightCell]}>
          <RangeBar row={row} width={width - spacing.xs} />
        </View>
      );
    }
    if (rendered.custom === "targetRange") {
      return (
        <View style={[styles.dataCell, { width }]}>
          <TargetRangeBar row={row} width={width - spacing.xs} />
        </View>
      );
    }
    return (
      <View style={[styles.dataCell, { width }]}>
        <Text style={styles.cellText}>—</Text>
      </View>
    );
  }

  return (
    <View style={[styles.dataCell, { width }, col.align === "right" && styles.alignRightCell]}>
      <Text
        style={[styles.cellText, rendered.color ? { color: rendered.color } : null]}
        numberOfLines={1}
      >
        {rendered.text}
      </Text>
    </View>
  );
}

export function FundamentalsTable({
  rows,
  tab,
  sort,
  onSortChange,
  refreshControl,
}: FundamentalsTableProps) {
  const { sticky: stickyColumns, scroll: scrollColumns } = useMemo(
    () => fundamentalsColumns(tab),
    [tab],
  );
  const sortedRows = useMemo(() => sortFundamentalsRows(rows, sort), [rows, sort]);
  const stickyWidth = stickyColumns.reduce((sum, col) => sum + col.width, 0);
  const tableWidth = scrollColumns.reduce((sum, col) => sum + col.width, 0);
  const scrollX = useRef(new Animated.Value(0)).current;

  function handleHeaderSort(key: FundamentalsSortKey) {
    onSortChange(cycleFundamentalsSort(sort, key));
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

      <ScrollView
        style={styles.bodyScroll}
        nestedScrollEnabled
        showsVerticalScrollIndicator
        refreshControl={refreshControl}
      >
        <View style={styles.bodyRow}>
          <View style={[styles.stickyBody, { width: stickyWidth }]}>
            {sortedRows.map((row) => (
              <View key={row.symbol} style={[styles.stickyDataRow, { width: stickyWidth }]}>
                {stickyColumns.map((col) => (
                  <StickyCell key={col.key} row={row} col={col} width={col.width} />
                ))}
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
              {sortedRows.map((row) => (
                <Link key={row.symbol} href={`/symbol/${row.symbol}`} asChild>
                  <Pressable style={styles.scrollDataRow}>
                    {scrollColumns.map((col) => (
                      <ScrollCell key={col.key} row={row} col={col} width={col.width} />
                    ))}
                  </Pressable>
                </Link>
              ))}
            </View>
          </Animated.ScrollView>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1 },
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
  headerCellActive: { backgroundColor: colors.surfaceAlt },
  headerCellAlignRight: {
    alignItems: "flex-end",
  },
  headerText: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  headerTextRange: {
    color: colors.link,
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
  bodyScroll: { flex: 1 },
  bodyRow: { flexDirection: "row" },
  stickyBody: {
    flexShrink: 0,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    backgroundColor: colors.bg,
    zIndex: 1,
    elevation: 1,
  },
  stickyDataRow: {
    flexDirection: "row",
    height: ROW_HEIGHT,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    alignItems: "center",
    flexShrink: 0,
    overflow: "visible",
  },
  symbolCell: {
    flexShrink: 0,
    justifyContent: "center",
    paddingLeft: spacing.sm,
    paddingRight: spacing.xs,
    height: ROW_HEIGHT,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    overflow: "hidden",
  },
  symbolPress: { justifyContent: "center", flex: 1 },
  symbol: { color: colors.link, fontSize: 14, fontWeight: "700" },
  dataCellSticky: {
    justifyContent: "center",
    paddingHorizontal: spacing.xs,
    height: ROW_HEIGHT,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
  },
  rangeCell: {
    justifyContent: "center",
    alignItems: "flex-end",
    paddingHorizontal: spacing.xs,
    height: ROW_HEIGHT,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
    overflow: "visible",
    zIndex: 1,
  },
  scrollBody: { flex: 1 },
  scrollDataRow: {
    flexDirection: "row",
    alignItems: "center",
    height: ROW_HEIGHT,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  dataCell: {
    flexShrink: 0,
    justifyContent: "center",
    paddingHorizontal: spacing.xs,
    height: ROW_HEIGHT,
  },
  alignRightCell: { alignItems: "flex-end" },
  cellText: { color: colors.text, fontSize: 12, fontWeight: "500" },
  alignRight: { textAlign: "right" },
});
