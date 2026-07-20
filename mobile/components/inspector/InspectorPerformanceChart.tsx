import { useEffect, useMemo, useRef, useState } from "react";
import {
  GestureResponderEvent,
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
  CHART_PAD_BOTTOM,
  CHART_PAD_LEFT,
  InspectorChartSvg,
} from "@/components/inspector/InspectorChartSvg";
import {
  buildChartHoverLine,
  buildInspectorChartModel,
  fullscreenChartWidth,
  nearestPricePoint,
  shortFibAxisLabel,
  yTicks,
  type ChartPoint,
  type InspectorChartModel,
} from "@/lib/chartHelpers";
import { formatMoney } from "@/lib/format";
import { setChartFullscreenActive } from "@/lib/chartFullscreenGate";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

const CHART_HEIGHT = 280;
const PAD = 12;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 4;

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
  const [zoom, setZoom] = useState(1);
  const fsScrollRef = useRef<ScrollView>(null);
  const lastTapRef = useRef(0);
  const pinchRef = useRef<{ dist: number; zoom: number } | null>(null);
  const model = useMemo(() => buildInspectorChartModel(data), [data]);
  const isLandscape = windowWidth > windowHeight;
  const wasLandscapeRef = useRef(isLandscape);

  // Auto-enter fullscreen only when rotating into landscape — not when
  // browsing symbols while already landscape (or after the user exited FS).
  useEffect(() => {
    const wasLandscape = wasLandscapeRef.current;
    wasLandscapeRef.current = isLandscape;
    if (isLandscape && !wasLandscape) {
      setFullscreen(true);
      return;
    }
    if (!isLandscape && wasLandscape) {
      setFullscreen(false);
      setFsHoverPoint(null);
    }
  }, [isLandscape]);

  useEffect(() => {
    setChartFullscreenActive(fullscreen);
    return () => setChartFullscreenActive(false);
  }, [fullscreen]);

  useEffect(() => {
    if (!fullscreen) {
      setZoom(1);
      return;
    }
    const t = setTimeout(() => {
      fsScrollRef.current?.scrollToEnd({ animated: false });
    }, 80);
    return () => clearTimeout(t);
  }, [fullscreen, model, fsViewport]);

  function enterFullscreen() {
    setFullscreen(true);
    setHoverPoint(null);
  }

  function exitFullscreen() {
    setFullscreen(false);
    setFsHoverPoint(null);
  }

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

  function clampZoom(value: number) {
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(value * 20) / 20));
  }

  function onPinchTouches(e: GestureResponderEvent) {
    const touches = e.nativeEvent.touches;
    if (touches.length < 2) {
      pinchRef.current = null;
      return;
    }
    const a = touches[0];
    const b = touches[1];
    const dist = Math.hypot(b.pageX - a.pageX, b.pageY - a.pageY);
    if (!pinchRef.current) {
      pinchRef.current = { dist: Math.max(dist, 1), zoom };
      return;
    }
    const next = clampZoom(pinchRef.current.zoom * (dist / pinchRef.current.dist));
    if (Math.abs(next - zoom) >= 0.05) setZoom(next);
  }

  if (!model.priceLine.length && !model.trendSegments.length) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>Performance & Fibonacci</Text>
        <Text style={styles.muted}>No chart timeline available for this symbol.</Text>
      </View>
    );
  }

  const inlineHover = hoverPoint ? buildChartHoverLine(model, hoverPoint) : "";
  const fsHover = fsHoverPoint ? buildChartHoverLine(model, fsHoverPoint) : "";

  const baseFsW = fullscreenChartWidth(model, Math.max(fsViewport || windowWidth - PAD * 2, 320));
  const fsChartW = Math.round(baseFsW * zoom);
  const fsChartH = Math.max(windowHeight - 72, 200);

  function onInlinePress(locationX: number) {
    const now = Date.now();
    if (now - lastTapRef.current < 320) {
      lastTapRef.current = 0;
      enterFullscreen();
      return;
    }
    lastTapRef.current = now;
    hoverFromTouch(locationX, cardWidth, CHART_PAD_LEFT, setHoverPoint);
  }

  function onFsPress(locationX: number) {
    const now = Date.now();
    if (now - lastTapRef.current < 320) {
      lastTapRef.current = 0;
      exitFullscreen();
      return;
    }
    lastTapRef.current = now;
    hoverFromTouch(locationX, fsChartW, CHART_PAD_LEFT, setFsHoverPoint);
  }

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
          onPress={(e) => onInlinePress(e.nativeEvent.locationX)}
        >
          {!fullscreen ? (
            <InspectorChartSvg
              model={model}
              width={cardWidth}
              height={CHART_HEIGHT}
              hoverNormX={hoverPoint?.x ?? null}
              hoverPoint={hoverPoint}
            />
          ) : (
            <View style={{ width: cardWidth, height: CHART_HEIGHT }} />
          )}
          {inlineHover && hoverPoint && !fullscreen ? (
            <View
              style={[
                styles.hoverBubble,
                {
                  left: Math.min(
                    Math.max(
                      CHART_PAD_LEFT,
                      hoverPoint.x * (cardWidth - CHART_PAD_LEFT - CHART_PAD) + CHART_PAD_LEFT - 20,
                    ),
                    Math.max(CHART_PAD_LEFT, cardWidth - 220),
                  ),
                  top: Math.max(
                    8,
                    CHART_PAD +
                      hoverPoint.y * (CHART_HEIGHT - CHART_PAD - CHART_PAD_BOTTOM) -
                      36,
                  ),
                },
              ]}
              pointerEvents="none"
            >
              <Text style={styles.hoverText} numberOfLines={2}>
                {inlineHover}
              </Text>
            </View>
          ) : null}
        </Pressable>
        <Text style={styles.hint}>
          Double-tap to toggle full-screen · tap for details · pinch/± to zoom
        </Text>
      </View>

      <Modal
        visible={fullscreen}
        animationType="fade"
        supportedOrientations={["landscape-left", "landscape-right", "portrait"]}
        onRequestClose={exitFullscreen}
      >
        <View style={styles.fsRoot}>
          <View style={styles.fsHeader}>
            <Text style={styles.fsTitle} numberOfLines={1}>
              {data?.symbol ?? ""} · Timeline
              {data?.chartTimeline?.windowStart
                ? ` · ${data.chartTimeline.windowStart} → ${data.chartTimeline.windowEnd}`
                : ""}
            </Text>
            <View style={styles.zoomRow}>
              <Pressable
                onPress={() => setZoom((z) => clampZoom(z - 0.25))}
                hitSlop={8}
                style={styles.zoomBtn}
              >
                <Text style={styles.zoomBtnText}>−</Text>
              </Pressable>
              <Text style={styles.zoomLabel}>{Math.round(zoom * 100)}%</Text>
              <Pressable
                onPress={() => setZoom((z) => clampZoom(z + 0.25))}
                hitSlop={8}
                style={styles.zoomBtn}
              >
                <Text style={styles.zoomBtnText}>+</Text>
              </Pressable>
              <Pressable onPress={exitFullscreen} hitSlop={12}>
                <Text style={styles.fsClose}>Done</Text>
              </Pressable>
            </View>
          </View>
          {fsHover ? (
            <Text style={styles.fsHoverLine} numberOfLines={1}>
              {fsHover}
            </Text>
          ) : (
            <Text style={styles.fsHint}>
              Scroll · pinch or ± to zoom · hold for details · double-tap to exit
            </Text>
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
                onPress={(e) => onFsPress(e.nativeEvent.locationX)}
                onPressOut={() => {
                  pinchRef.current = null;
                }}
                delayLongPress={160}
                onTouchStart={onPinchTouches}
                onTouchMove={onPinchTouches}
                onTouchEnd={() => {
                  pinchRef.current = null;
                }}
                onTouchCancel={() => {
                  pinchRef.current = null;
                }}
              >
                <InspectorChartSvg
                  model={model}
                  width={fsChartW}
                  height={fsChartH}
                  padLeft={CHART_PAD_LEFT}
                  showYLabels={false}
                  showXLabels
                  hoverNormX={fsHoverPoint?.x ?? null}
                  hoverPoint={fsHoverPoint}
                />
              </Pressable>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  );
}

function StickyYAxis({ model, height }: { model: InspectorChartModel; height: number }) {
  const ticks = yTicks(model.minPrice, model.maxPrice, 5);
  const plotH = Math.max(1, height - CHART_PAD - CHART_PAD_BOTTOM);
  const span = Math.max(model.maxPrice - model.minPrice, 1);
  return (
    <View style={styles.fsYaxis} pointerEvents="none">
      {model.fibLines.slice(0, 8).map((fib) => {
        const yNorm = 1 - (fib.price - model.minPrice) / span;
        const top = CHART_PAD + yNorm * plotH - 5;
        return (
          <Text
            key={`fs-fib-${fib.label}-${fib.price}`}
            style={[styles.fsFibTick, { top, color: fib.color }]}
            numberOfLines={1}
          >
            {shortFibAxisLabel(fib.label)}
          </Text>
        );
      })}
      {ticks.map((price) => {
        const yNorm = 1 - (price - model.minPrice) / span;
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
    maxWidth: 220,
    backgroundColor: "rgba(15, 23, 42, 0.94)",
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
  },
  hoverText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "600",
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
    gap: spacing.sm,
  },
  fsTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
    flex: 1,
    marginRight: spacing.sm,
  },
  zoomRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  zoomBtn: {
    width: 28,
    height: 28,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  zoomBtnText: {
    color: colors.text,
    fontSize: 18,
    fontWeight: "700",
    lineHeight: 20,
  },
  zoomLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
    minWidth: 36,
    textAlign: "center",
  },
  fsClose: {
    color: colors.link,
    fontSize: 15,
    fontWeight: "700",
    marginLeft: 4,
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
    backgroundColor: "rgba(244, 246, 248, 0.96)",
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: colors.border,
  },
  fsYTick: {
    position: "absolute",
    right: 4,
    color: colors.textMuted,
    fontSize: 9,
    fontWeight: "600",
  },
  fsFibTick: {
    position: "absolute",
    left: 3,
    fontSize: 8,
    fontWeight: "700",
    maxWidth: 36,
  },
  fsScroll: {
    flex: 1,
  },
});
