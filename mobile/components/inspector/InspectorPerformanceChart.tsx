import { useEffect, useMemo, useState } from "react";
import {
  LayoutChangeEvent,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";

import { InspectorChartSvg } from "@/components/inspector/InspectorChartSvg";
import { buildInspectorChartModel } from "@/lib/chartHelpers";
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
  const [fullscreen, setFullscreen] = useState(false);
  const model = useMemo(() => buildInspectorChartModel(data), [data]);
  const isLandscape = windowWidth > windowHeight;

  useEffect(() => {
    setFullscreen(isLandscape);
  }, [isLandscape]);

  function onLayout(event: LayoutChangeEvent) {
    const next = event.nativeEvent.layout.width;
    if (next > 0 && Math.abs(next - cardWidth) > 1) setCardWidth(next);
  }

  if (!model.priceLine.length && !model.trendSegments.length) {
    return (
      <View style={styles.card}>
        <Text style={styles.title}>Performance & Fibonacci</Text>
        <Text style={styles.muted}>No chart timeline available for this symbol.</Text>
      </View>
    );
  }

  const chartBody = (
    <>
      <View style={styles.chartWrap}>
        <InspectorChartSvg model={model} width={cardWidth} height={CHART_HEIGHT} />
      </View>
      <View style={styles.legend}>
        <LegendDot color={model.priceColor} label="Price" />
        {model.trendSegments.slice(0, 4).map((seg) => (
          <LegendDot key={seg.label} color={seg.color} label={seg.label || "Trend"} />
        ))}
        {model.pattern ? (
          <LegendDot color={model.pattern.color} label={`◆ ${model.pattern.name}`} />
        ) : null}
      </View>
    </>
  );

  return (
    <>
      <View style={styles.card} onLayout={onLayout}>
        <Text style={styles.title}>Performance & Fibonacci</Text>
        {data?.chartTimeline?.windowStart && data?.chartTimeline?.windowEnd ? (
          <Text style={styles.window}>
            {data.chartTimeline.windowStart} → {data.chartTimeline.windowEnd}
          </Text>
        ) : null}
        {chartBody}
        <Text style={styles.hint}>Rotate device sideways for full-screen chart</Text>
      </View>

      <Modal
        visible={fullscreen}
        animationType="fade"
        supportedOrientations={["landscape-left", "landscape-right", "portrait"]}
        onRequestClose={() => setFullscreen(false)}
      >
        <View style={styles.fsRoot}>
          <View style={styles.fsHeader}>
            <Text style={styles.fsTitle}>
              {data?.symbol ?? ""} · Performance
              {data?.chartTimeline?.windowStart
                ? ` · ${data.chartTimeline.windowStart} → ${data.chartTimeline.windowEnd}`
                : ""}
            </Text>
            <Pressable onPress={() => setFullscreen(false)} hitSlop={12}>
              <Text style={styles.fsClose}>Done</Text>
            </Pressable>
          </View>
          <View
            style={styles.fsChart}
            onLayout={(e) => {
              const w = e.nativeEvent.layout.width;
              if (w > 0) setCardWidth(w);
            }}
          >
            <InspectorChartSvg
              model={model}
              width={Math.max(windowWidth - PAD * 2, 320)}
              height={Math.max(windowHeight - 72, 200)}
            />
          </View>
          <View style={styles.fsLegend}>
            <LegendDot color={model.priceColor} label="Price" />
            {model.trendSegments.slice(0, 4).map((seg) => (
              <LegendDot key={`fs-${seg.label}`} color={seg.color} label={seg.label || "Trend"} />
            ))}
            {model.pattern ? (
              <LegendDot color={model.pattern.color} label={`◆ ${model.pattern.name}`} />
            ) : null}
          </View>
        </View>
      </Modal>
    </>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendSwatch, { backgroundColor: color }]} />
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
    width: 10,
    height: 3,
    borderRadius: 2,
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
    marginBottom: spacing.sm,
  },
  fsTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
    flex: 1,
  },
  fsClose: {
    color: colors.link,
    fontSize: 15,
    fontWeight: "700",
  },
  fsChart: {
    flex: 1,
    borderRadius: radii.sm,
    overflow: "hidden",
    backgroundColor: colors.surface,
  },
  fsLegend: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    paddingTop: spacing.sm,
  },
});
