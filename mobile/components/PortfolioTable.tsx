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
import AsyncStorage from "@react-native-async-storage/async-storage";

import { FlashRow } from "@/components/FlashRow";
import { SaiBadge } from "@/components/SaiBadge";
import { TechBiasBadge } from "@/components/TechBiasBadge";
import { SymbolStarPressable } from "@/components/SymbolStarPressable";
import { TradeBandBar, tradeBandTooltipText } from "@/components/TradeBandBar";
import {
  formatDividendWithYield,
  formatHorizonLabel,
  formatMoney,
  formatPct,
  formatPrice,
  formatQty,
  formatWeight,
  pctColor,
} from "@/lib/format";
import {
  computePortfolioTotals,
  cyclePortfolioSort,
  portfolioTableColumns,
  sortHeaderLabel,
  type PortfolioColumn,
  type PortfolioSortKey,
  type PortfolioSortState,
} from "@/lib/portfolioTable";
import { openSymbol } from "@/lib/symbolBrowseSession";
import { fitStickyScrollColumns } from "@/lib/tableLayout";
import type { TradeUpperRef } from "@/lib/tradeBand";
import { colors, spacing } from "@/lib/theme";
import type { PortfolioRow } from "@/lib/types";

const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 36;
const TRADE_TIP_KEYS: PortfolioSortKey[] = ["dayChangePct", "tradeBand", "quantity"];
const TRADE_UPPER_REF_KEY = "portfolio.tradeUpperRef";

// Subtle directional flash tints: green when the price rose, red when it fell,
// neutral blue for non-price updates (e.g. Tech Bias / SAI arriving).
const FLASH_UP = "rgba(34, 197, 94, 0.22)";
const FLASH_DOWN = "rgba(239, 68, 68, 0.22)";
const FLASH_NEUTRAL = "rgba(96, 165, 250, 0.16)";

/** Fingerprint of the displayed values that arrive via background/progressive
 *  updates. When it changes, the row flashes (only changed rows flash). */
function rowFlashKey(row: PortfolioRow): string {
  return [
    row.currentPrice ?? "",
    row.dayChangePct ?? "",
    row.marketValue ?? "",
    row.gainPct ?? "",
    JSON.stringify(row.techBias ?? null),
    row.saiAction ?? "",
  ].join("|");
}

function flashPrice(row: PortfolioRow): number | null {
  return typeof row.currentPrice === "number" ? row.currentPrice : null;
}

interface PortfolioTableProps {
  rows: PortfolioRow[];
  sort: PortfolioSortState;
  onSortChange: (sort: PortfolioSortState) => void;
  landscape?: boolean;
  refreshControl?: React.ReactElement<RefreshControlProps>;
}

function renderCell(row: PortfolioRow, col: PortfolioColumn): string {
  if (col.key === "symbol" || col.key === "sai" || col.key === "techBias") return "";
  const value = row[col.key as keyof PortfolioRow];
  if (col.key === "quantity") return formatQty(value as number | null);
  if (col.key === "weightPct") return formatWeight(value as number | null);
  if (col.key === "annualDividend") {
    return formatDividendWithYield(row.annualDividend, row.marketValue, true);
  }
  if (col.key === "targetHorizonAt") {
    return formatHorizonLabel(row.targetHorizonAt, row.targetHorizonLabel) || "—";
  }
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
  onLongPress,
  width,
  upperRefPt,
}: {
  col: PortfolioColumn;
  sort: PortfolioSortState;
  onPress: () => void;
  onLongPress?: () => void;
  width: number;
  upperRefPt?: boolean;
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
      onLongPress={onLongPress}
      delayLongPress={380}
    >
      <Text
        style={[styles.headerText, col.align === "right" && styles.alignRight]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.75}
      >
        {sortHeaderLabel(col.label, col.key, sort, Boolean(upperRefPt))}
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
  const [viewportWidth, setViewportWidth] = useState(0);
  const { sticky: stickyColumns, scroll: scrollColumns } = useMemo(() => {
    const base = portfolioTableColumns(landscape);
    if (viewportWidth <= 0) return base;
    return fitStickyScrollColumns(base.sticky, base.scroll, viewportWidth);
  }, [landscape, viewportWidth]);
  const stickyWidth = stickyColumns.reduce((sum, col) => sum + col.width, 0);
  const stickyWidthByKey = Object.fromEntries(stickyColumns.map((col) => [col.key, col.width])) as Record<
    string,
    number
  >;
  const symbolWidth = stickyWidthByKey.symbol ?? stickyColumns[0]?.width ?? 74;
  const saiWidth = stickyWidthByKey.sai ?? 54;
  const tableWidth = scrollColumns.reduce((sum, col) => sum + col.width, 0);
  const scrollX = useRef(new Animated.Value(0)).current;
  const [tipSymbol, setTipSymbol] = useState<string | null>(null);
  const longPressedRef = useRef(false);
  const [upperRef, setUpperRef] = useState<TradeUpperRef>("analyst");
  const totals = useMemo(() => computePortfolioTotals(rows), [rows]);

  // Per-symbol flash key + directional tint. `flashKey` changes only when a
  // displayed value changes (so only changed rows flash); the tint compares the
  // new price to the last committed one (green up / red down / neutral).
  const prevPriceRef = useRef<Map<string, number | null>>(new Map());
  const flashBySymbol = useMemo(() => {
    const map = new Map<string, { key: string; color: string }>();
    for (const row of rows) {
      const price = flashPrice(row);
      const prev = prevPriceRef.current.get(row.symbol);
      let color = FLASH_NEUTRAL;
      if (prev != null && price != null && price !== prev) {
        color = price > prev ? FLASH_UP : FLASH_DOWN;
      }
      map.set(row.symbol, { key: rowFlashKey(row), color });
    }
    return map;
  }, [rows]);
  useEffect(() => {
    const next = new Map<string, number | null>();
    for (const row of rows) next.set(row.symbol, flashPrice(row));
    prevPriceRef.current = next;
  }, [rows]);

  useEffect(() => {
    let cancelled = false;
    void AsyncStorage.getItem(TRADE_UPPER_REF_KEY).then((raw) => {
      if (cancelled) return;
      if (raw === "pt" || raw === "analyst") setUpperRef(raw);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const browseSymbols = rows.map((row) => row.symbol);

  function handleHeaderSort(key: PortfolioSortKey) {
    onSortChange(cyclePortfolioSort(sort, key));
  }

  function toggleTradeUpperRef() {
    setUpperRef((prev) => {
      const next: TradeUpperRef = prev === "pt" ? "analyst" : "pt";
      void AsyncStorage.setItem(TRADE_UPPER_REF_KEY, next);
      return next;
    });
  }

  function openDetails(symbol: string) {
    if (longPressedRef.current) return;
    setTipSymbol(null);
    openSymbol(symbol, browseSymbols, "portfolio");
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
                onLongPress={col.key === "tradeBand" ? toggleTradeUpperRef : undefined}
                upperRefPt={col.key === "tradeBand" && upperRef === "pt"}
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
              {tradeBandTooltipText(rows.find((r) => r.symbol === tipSymbol) ?? { symbol: tipSymbol }, upperRef) ??
                ""}
            </Text>
          </View>
        ) : null}

        <ScrollView
          style={styles.bodyScroll}
          nestedScrollEnabled
          showsVerticalScrollIndicator
          contentInsetAdjustmentBehavior="never"
          refreshControl={refreshControl}
        >
        <View style={styles.bodyRow}>
          <View style={[styles.stickyBody, { width: stickyWidth }]}>
            {rows.map((row) => (
              <FlashRow
                key={row.symbol}
                flashKey={flashBySymbol.get(row.symbol)?.key ?? ""}
                color={flashBySymbol.get(row.symbol)?.color}
                style={[styles.stickyDataRow, { width: stickyWidth }]}
              >
                <View style={[styles.symbolCell, { width: symbolWidth }]}>
                  <SymbolStarPressable
                    style={styles.symbolPress}
                    symbol={row.symbol}
                    onPress={() => openDetails(row.symbol)}
                  />
                </View>
                <View style={[styles.saiCell, { width: saiWidth }]}>
                  <SaiBadge action={row.saiAction} proposal={row.saiProposal} mini />
                </View>
              </FlashRow>
            ))}
            {rows.length > 0 ? (
              <View style={[styles.stickyDataRow, styles.totalRow, { width: stickyWidth }]}>
                <View style={[styles.symbolCell, { width: symbolWidth }]}>
                  <Text style={styles.totalLabel}>{totals.symbol?.text ?? "TOTAL"}</Text>
                </View>
                <View style={[styles.saiCell, { width: saiWidth }]} />
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
              {rows.map((row) => {
                const tipActive = tipSymbol === row.symbol;
                return (
                  <FlashRow
                    key={row.symbol}
                    flashKey={flashBySymbol.get(row.symbol)?.key ?? ""}
                    color={flashBySymbol.get(row.symbol)?.color}
                    style={styles.scrollDataRow}
                  >
                    {scrollColumns.map((col) => {
                      const supportsTradeTip = TRADE_TIP_KEYS.includes(col.key);
                      const content =
                        col.key === "techBias" ? (
                          <TechBiasBadge bias={row.techBias} mini />
                        ) : col.tradeBand ? (
                          <TradeBandBar
                            row={row}
                            width={col.width - spacing.xs}
                            active={tipActive}
                            upperRef={upperRef}
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
                                  if (tradeBandTooltipText(row, upperRef)) setTipSymbol(row.symbol);
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
                  </FlashRow>
                );
              })}
              {rows.length > 0 ? (
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
    fontSize: 13,
    fontWeight: "700",
  },
});
