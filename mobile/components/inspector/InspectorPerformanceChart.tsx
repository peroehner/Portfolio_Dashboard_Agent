import { useEffect, useMemo, useRef, useState } from "react";
import {
  LayoutChangeEvent,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";

import {
  CHART_PAD,
  CHART_PAD_LEFT,
  InspectorChartSvg,
} from "@/components/inspector/InspectorChartSvg";
import {
  buildInspectorChartModel,
  formatChartHover,
  formatTradeLevelHover,
  fullscreenChartWidth,
  nearestPricePoint,
  yTicks,
  type ChartPoint,
  type InspectorChartModel,
} from "@/lib/chartHelpers";
import { formatMoney } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

const CHART_HEIGHT = 260;
const PAD = 12;

interface InspectorPerformanceChartProps {
  data?: InspectorPayload | null;
}

export function InspectorPerformanceChart({ data }: InspectorPerformanceChartProps) {
  const { width: windowWidth, height: windowHeight } = useWindowDimensions();
  const [cardWidth, setCardWidth] = useState(320);
  const [fsViewport, setFsViewport] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [hoverPoint, setHoverPoint] = useState<ChartPoint | null>(null);
  const [fsHoverPoint, setFsHoverPoint] = useState<ChartPoint | null>(null);
  const fsScrollRef = useRef<ScrollView>(null);
  const model = useMemo(() => buildInspectorChartModel(data), [data]);
  const isLandscape = windowWidth > windowHeight;

  useEffect(() => {
    setFullscreen(isLandscape);
  }, [isLandscape]);

  useEffect(() => {
    if (!fullscreen) return;
    const t = setTimeout(() => {
      fsScrollRef.current?.scrollToEnd({ animated: false });
    }, 80);
    return () => clearTimeout(t);
  }, [fullscreen, model, fsViewport]);

  function onLayout(event: LayoutChangeEvent) {
    const next = event.nativeEvent.layout.width;
    if (next > 0 && Math.abs(next - cardWidth) > 1) setCardWidth(next);
  }

  function hoverFromTouch(
    locationX: number,
    chartWidth: number,
    padLeft: number,
    setPoint: (p: ChartPoint | null) => void,
  ) {
    const plotW = Math.max(1, chartWidth - padLeft - CHART_PAD);
    const normX = Math.max(0, Math.min(1, (locationX - padLeft) / plotW));
    setPoint(nearestPricePoint(model, normX));
  }

  if (!model.priceLine.length && !model.trendSegments.length) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>Performance & Fibonacci</Text>
        <Text style={styles.muted}>No chart timeline available for this symbol.</Text>
      </View>
    );
  }

  function renderLegend(keyPrefix = "") {
    return (
      <View style={styles.legend}>
        <LegendDot color={model.priceColor} label="Price" />
        {model.hasVolume ? <LegendDot color="rgba(34,197,94,0.7)" label="Volume" dashed /> : null}
        {model.trendSegments.slice(0, 4).map((seg) => (
          <LegendDot
            key={`${keyPrefix}${seg.label}`}
            color={seg.color}
            label={seg.label || "Trend"}
          />
        ))}
        {model.pattern ? (
          <LegendDot
            key={`${keyPrefix}pattern`}
            color={model.pattern.color}
            label={`◆ ${model.pattern.name}`}
          />
        ) : null}
        {model.tradeLevels.map((level) => (
          <LegendDot
            key={`${keyPrefix}${level.side}`}
            color={level.color}
            label={level.label}
            dashed
            thick
          />
        ))}
      </View>
    );
  }

  const hoverTrade = model.tradeLevels
    .filter((l) => l.edge === "none")
    .map(formatTradeLevelHover)
    .join(" · ");

  const inlineHover = hoverPoint ? formatChartHover(hoverPoint) : null;
  const fsHover = fsHoverPoint ? formatChartHover(fsHoverPoint) : null;

  const fsChartW = fullscreenChartWidth(model, Math.max(fsViewport || windowWidth - PAD * 2, 320));
  const fsChartH = Math.max(windowHeight - 96, 200);

  return (
    <>
      <View style={styles.card} onLayout={onLayout}>
        <Text style={styles.title}>Performance & Fibonacci</Text>
        {data?.chartTimeline?.windowStart && data?.chartTimeline?.windowEnd ? (
          <Text style={styles.window}>
            {data.chartTimeline.windowStart} → {data.chartTimeline.windowEnd}
          </Text>
        ) : null}
        <Pressable
          style={styles.chartWrap}
          onLongPress={(e) =>
            hoverFromTouch(e.nativeEvent.locationX, cardWidth, CHART_PAD_LEFT, setHoverPoint)
          }
          onPressOut={() => setHoverPoint(null)}
          delayLongPress={180}
          onPress={(e) =>
            hoverFromTouch(e.nativeEvent.locationX, cardWidth, CHART_PAD_LEFT, setHoverPoint)
          }
        >
          <InspectorChartSvg
            model={model}
            width={cardWidth}
            height={CHART_HEIGHT}
            hoverNormX={hoverPoint?.x ?? null}
            hoverPoint={hoverPoint}
          />
          {inlineHover ? (
            <View style={styles.hoverBubble} pointerEvents="none">
              <Text style={styles.hoverText}>{inlineHover}</Text>
              {hoverTrade ? <Text style={styles.hoverSub}>{hoverTrade}</Text> : null}
            </View>
          ) : null}
        </Pressable>
        {renderLegend()}
        <Text style={styles.hint}>Hold on chart for price · rotate for full-screen scroll</Text>
      </View>

      <Modal
        visible={fullscreen}
        animationType="fade"
        supportedOrientations={["landscape-left", "landscape-right", "portrait"]}
        onRequestClose={() => setFullscreen(false)}
      >
        <View style={styles.fsRoot}>
          <View style={styles.fsHeader}>
            <Text style={styles.fsTitle} numberOfLines={1}>
              {data?.symbol ?? ""} · Performance
              {data?.chartTimeline?.windowStart
                ? ` · ${data.chartTimeline.windowStart} → ${data.chartTimeline.windowEnd}`
                : ""}
            </Text>
            <Pressable onPress={() => setFullscreen(false)} hitSlop={12}>
              <Text style={styles.fsClose}>Done</Text>
            </Pressable>
          </View>
          {fsHover ? (
            <Text style={styles.fsHoverLine} numberOfLines={1}>
              {fsHover}
              {hoverTrade ? ` · ${hoverTrade}` : ""}
            </Text>
          ) : (
            <Text style={styles.fsHint}>Scroll horizontally · ~2-month view · hold for price</Text>
          )}
          <View
            style={styles.fsChart}
            onLayout={(e) => {
              const w = e.nativeEvent.layout.width;
              if (w > 0) setFsViewport(w);
            }}
          >
            <StickyYAxis model={model} height={fsChartH} />
            <ScrollView
              ref={fsScrollRef}
              horizontal
              showsHorizontalScrollIndicator
              style={styles.fsScroll}
              contentContainerStyle={{ width: fsChartW }}
            >
              <Pressable
                onLongPress={(e) =>
                  hoverFromTouch(e.nativeEvent.locationX, fsChartW, CHART_PAD_LEFT, setFsHoverPoint)
                }
                onPress={(e) =>
                  hoverFromTouch(e.nativeEvent.locationX, fsChartW, CHART_PAD_LEFT, setFsHoverPoint)
                }
                onPressOut={() => setFsHoverPoint(null)}
                delayLongPress={160}
              >
                <InspectorChartSvg
                  model={model}
                  width={fsChartW}
                  height={fsChartH}
                  padLeft={CHART_PAD_LEFT}
                  showYLabels={false}
                  hoverNormX={fsHoverPoint?.x ?? null}
                  hoverPoint={fsHoverPoint}
                />
              </Pressable>
            </ScrollView>
          </View>
          <View style={styles.fsLegend}>{renderLegend("fs-")}</View>
        </View>
      </Modal>
    </>
  );
}

function StickyYAxis({ model, height }: { model: InspectorChartModel; height: number }) {
  const ticks = yTicks(model.minPrice, model.maxPrice, 5);
  const plotH = Math.max(1, height - CHART_PAD * 2);
  return (
    <View style={styles.fsYaxis} pointerEvents="none">
      {ticks.map((price) => {
        const yNorm = 1 - (price - model.minPrice) / Math.max(model.maxPrice - model.minPrice, 1);
        const top = CHART_PAD + yNorm * plotH - 6;
        return (
          <Text key={`fs-y-${price}`} style={[styles.fsYTick, { top }]}>
            {formatMoney(price)}
          </Text>
        );
      })}
    </View>
  );
}

function LegendDot({
  color,
  label,
  dashed,
  thick,
}: {
  color: string;
  label: string;
  dashed?: boolean;
  thick?: boolean;
}) {
  return (
    <View style={styles.legendItem}>
      <View
        style={[
          styles.legendSwatch,
          { backgroundColor: dashed ? "transparent" : color, borderColor: color },
          dashed && styles.legendSwatchDashed,
          thick && styles.legendSwatchThick,
        ]}
      />
      <Text style={styles.legendText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.xs,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
  },
  window: {
    color: colors.textMuted,
    fontSize: 11,
  },
  chartWrap: {
    borderRadius: radii.sm,
    overflow: "hidden",
    backgroundColor: colors.bg,
    position: "relative",
  },
  hoverBubble: {
    position: "absolute",
    top: 8,
    left: CHART_PAD_LEFT,
    right: 8,
    backgroundColor: "rgba(15, 23, 42, 0.92)",
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  hoverText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "700",
  },
  hoverSub: {
    color: colors.textMuted,
    fontSize: 10,
    marginTop: 2,
  },
  legend: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  legendItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  legendSwatch: {
    width: 12,
    height: 3,
    borderRadius: 2,
    borderTopWidth: 0,
  },
  legendSwatchDashed: {
    height: 0,
    borderTopWidth: 2,
    borderStyle: "dashed",
    width: 14,
  },
  legendSwatchThick: {
    borderTopWidth: 3,
  },
  legendText: {
    color: colors.textMuted,
    fontSize: 10,
  },
  hint: {
    color: colors.textMuted,
    fontSize: 10,
    marginTop: 2,
  },
  muted: {
    color: colors.textMuted,
    fontSize: 12,
  },
  fsRoot: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: PAD,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
  },
  fsHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
  },
  fsTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
    flex: 1,
    marginRight: spacing.sm,
  },
  fsClose: {
    color: colors.link,
    fontSize: 15,
    fontWeight: "700",
  },
  fsHint: {
    color: colors.textMuted,
    fontSize: 11,
    marginBottom: spacing.xs,
  },
  fsHoverLine: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "600",
    marginBottom: spacing.xs,
  },
  fsChart: {
    flex: 1,
    borderRadius: radii.sm,
    overflow: "hidden",
    backgroundColor: colors.surface,
    position: "relative",
  },
  fsYaxis: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    width: CHART_PAD_LEFT,
    zIndex: 2,
    backgroundColor: "rgba(11, 18, 32, 0.92)",
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
  },
  fsYTick: {
    position: "absolute",
    right: 4,
    color: "#94a3b8",
    fontSize: 9,
    fontWeight: "600",
  },
  fsScroll: {
    flex: 1,
  },
  fsLegend: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    paddingTop: spacing.sm,
  },
});
