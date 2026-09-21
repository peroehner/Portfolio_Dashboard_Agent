import { useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
  type RefreshControlProps,
} from "react-native";

import { FlashRow } from "@/components/FlashRow";
import { RangeBar, TargetRangeBar } from "@/components/RangeBar";
import { SymbolStarPressable } from "@/components/SymbolStarPressable";
import {
  computeFundamentalsTotals,
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
import { openSymbol } from "@/lib/symbolBrowseSession";
import { fitStickyScrollColumns } from "@/lib/tableLayout";
import { useSymbolRowStar } from "@/lib/useSymbolRowStar";
import { colors, spacing } from "@/lib/theme";
import type { FundamentalsRow } from "@/lib/types";

const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 40;

// Subtle directional flash tints (green up / red down / neutral for non-price
// updates), matching the Portfolio table.
const FLASH_UP = "rgba(34, 197, 94, 0.22)";
const FLASH_DOWN = "rgba(239, 68, 68, 0.22)";
const FLASH_NEUTRAL = "rgba(96, 165, 250, 0.16)";

function fundFlashPrice(row: FundamentalsRow): number | null {
  return typeof row.currentPrice === "number" ? row.currentPrice : null;
}

/** Fingerprint of displayed fundamentals values; changes trigger a row flash. */
function fundFlashKey(row: FundamentalsRow): string {
  return [
    row.currentPrice ?? "",
    row.dayChangePct ?? "",
    JSON.stringify(row.fundamentals ?? null),
  ].join("|");
}

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
  browseSymbols,
}: {
  row: FundamentalsRow;
  col: FundamentalsColumn;
  width: number;
  browseSymbols: string[];
}) {
  if (col.kind === "symbol") {
    return (
      <View style={[styles.symbolCell, { width }]}>
        <SymbolStarPressable
          style={styles.symbolPress}
          symbol={row.symbol}
          onPress={() => openSymbol(row.symbol, browseSymbols, "fundamentals")}
        />
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

function FundamentalsScrollRow({
  row,
  scrollColumns,
  browseSymbols,
  flashKey,
  flashColor,
}: {
  row: FundamentalsRow;
  scrollColumns: FundamentalsColumn[];
  browseSymbols: string[];
  flashKey: string;
  flashColor: string;
}) {
  const rowStar = useSymbolRowStar(row.symbol);
  return (
    <FlashRow flashKey={flashKey} color={flashColor}>
      <Pressable
        style={styles.scrollDataRow}
        onPress={() => openSymbol(row.symbol, browseSymbols, "fundamentals")}
        {...rowStar}
      >
        {scrollColumns.map((col) => (
          <ScrollCell key={col.key} row={row} col={col} width={col.width} />
        ))}
      </Pressable>
    </FlashRow>
  );
}

export function FundamentalsTable({
  rows,
  tab,
  sort,
  onSortChange,
  refreshControl,
}: FundamentalsTableProps) {
  const [viewportWidth, setViewportWidth] = useState(0);
  const { sticky: stickyColumns, scroll: scrollColumns } = useMemo(() => {
    const base = fundamentalsColumns(tab);
    if (viewportWidth <= 0) return base;
    return fitStickyScrollColumns(base.sticky, base.scroll, viewportWidth);
  }, [tab, viewportWidth]);
  const sortedRows = useMemo(() => sortFundamentalsRows(rows, sort), [rows, sort]);
  const browseSymbols = useMemo(() => sortedRows.map((row) => row.symbol), [sortedRows]);
  const totals = useMemo(() => computeFundamentalsTotals(sortedRows), [sortedRows]);

  // Per-symbol flash key + directional tint (green up / red down / neutral),
  // compared against the last committed price so both row panes flash alike.
  const prevPriceRef = useRef<Map<string, number | null>>(new Map());
  const flashBySymbol = useMemo(() => {
    const map = new Map<string, { key: string; color: string }>();
    for (const row of sortedRows) {
      const price = fundFlashPrice(row);
      const prev = prevPriceRef.current.get(row.symbol);
      let color = FLASH_NEUTRAL;
      if (prev != null && price != null && price !== prev) {
        color = price > prev ? FLASH_UP : FLASH_DOWN;
      }
      map.set(row.symbol, { key: fundFlashKey(row), color });
    }
    return map;
  }, [sortedRows]);
  useEffect(() => {
    const next = new Map<string, number | null>();
    for (const row of sortedRows) next.set(row.symbol, fundFlashPrice(row));
    prevPriceRef.current = next;
  }, [sortedRows]);
  const stickyWidth = stickyColumns.reduce((sum, col) => sum + col.width, 0);
  const tableWidth = scrollColumns.reduce((sum, col) => sum + col.width, 0);
  const scrollX = useRef(new Animated.Value(0)).current;

  function handleHeaderSort(key: FundamentalsSortKey) {
    onSortChange(cycleFundamentalsSort(sort, key));
  }

  function onWrapLayout(event: LayoutChangeEvent) {
    const next = Math.floor(event.nativeEvent.layout.width);
    if (next > 0 && next !== viewportWidth) setViewportWidth(next);
  }

  return (
    <View style={styles.wrap} onLayout={onWrapLayout}>
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
              <FlashRow
                key={row.symbol}
                flashKey={flashBySymbol.get(row.symbol)?.key ?? ""}
                color={flashBySymbol.get(row.symbol)?.color}
                style={[styles.stickyDataRow, { width: stickyWidth }]}
              >
                {stickyColumns.map((col) => (
                  <StickyCell
                    key={col.key}
                    row={row}
                    col={col}
                    width={col.width}
                    browseSymbols={browseSymbols}
                  />
                ))}
              </FlashRow>
            ))}
            {sortedRows.length > 0 ? (
              <View style={[styles.stickyDataRow, styles.totalRow, { width: stickyWidth }]}>
                {stickyColumns.map((col) => {
                  if (col.kind === "symbol") {
                    return (
                      <View key={col.key} style={[styles.symbolCell, { width: col.width }]}>
                        <Text style={styles.totalLabel}>{totals.symbol?.text ?? "TOTAL"}</Text>
                      </View>
                    );
                  }
                  return (
                    <View
                      key={col.key}
                      style={[styles.dataCellSticky, { width: col.width }, styles.alignRightCell]}
                    >
                      <Text style={styles.totalCellText}> </Text>
                    </View>
                  );
                })}
              </View>
            ) : null}
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
                <FundamentalsScrollRow
                  key={row.symbol}
                  row={row}
                  scrollColumns={scrollColumns}
                  browseSymbols={browseSymbols}
                  flashKey={flashBySymbol.get(row.symbol)?.key ?? ""}
                  flashColor={flashBySymbol.get(row.symbol)?.color ?? FLASH_NEUTRAL}
                />
              ))}
              {sortedRows.length > 0 ? (
                <View style={[styles.scrollDataRow, styles.totalRow]}>
                  {scrollColumns.map((col) => {
                    const cell = totals[col.key];
                    return (
                      <View
                        key={col.key}
                        style={[
                          styles.dataCell,
                          { width: col.width },
                          col.align === "right" && styles.alignRightCell,
                        ]}
                      >
                        <Text
                          style={[
                            styles.totalCellText,
                            col.align === "right" && styles.alignRight,
                            cell?.color ? { color: cell.color } : null,
                          ]}
                          numberOfLines={1}
                        >
                          {cell?.text ?? ""}
                        </Text>
                      </View>
                    );
                  })}
                </View>
              ) : null}
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
  totalRow: {
    backgroundColor: colors.surfaceAlt,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  totalLabel: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "800",
  },
  totalCellText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "700",
  },
});
