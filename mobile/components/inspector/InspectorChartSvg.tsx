import Svg, { Circle, G, Line, Polyline, Rect, Text as SvgText } from "react-native-svg";

import {
  chartCoord,
  pointsToPolyline,
  yTicks,
  type ChartPoint,
  type InspectorChartModel,
} from "@/lib/chartHelpers";
import { formatMoney, formatPrice } from "@/lib/format";

export const CHART_PAD = 10;
export const CHART_PAD_LEFT = 44;

interface InspectorChartSvgProps {
  model: InspectorChartModel;
  width: number;
  height: number;
  /** Left gutter for Y labels (0 when sticky Y is drawn outside). */
  padLeft?: number;
  /** Draw Y-axis labels inside the SVG. */
  showYLabels?: boolean;
  /** Highlight nearest price point (normalized x 0–1). */
  hoverNormX?: number | null;
  hoverPoint?: ChartPoint | null;
}

export function InspectorChartSvg({
  model,
  width,
  height,
  padLeft = CHART_PAD_LEFT,
  showYLabels = true,
  hoverNormX = null,
  hoverPoint = null,
}: InspectorChartSvgProps) {
  const pad = CHART_PAD;
  const plotW = Math.max(1, width - padLeft - pad);
  const plotH = Math.max(1, height - pad * 2);
  const volBand = Math.min(48, plotH * 0.22);

  const pricePoints = pointsToPolyline(model.priceLine, width, height, padLeft, pad);
  const yForNorm = (yNorm: number) => pad + yNorm * plotH;
  const yForPrice = (price: number) => {
    const yNorm = 1 - (price - model.minPrice) / Math.max(model.maxPrice - model.minPrice, 1);
    return yForNorm(yNorm);
  };
  const xForNorm = (xNorm: number) => padLeft + xNorm * plotW;

  const ticks = yTicks(model.minPrice, model.maxPrice, 5);
  const pattern = model.pattern;
  const barW = Math.max(1.5, (plotW / Math.max(model.volumeBars.length, 1)) * 0.7);

  return (
    <Svg width={width} height={height}>
      {showYLabels
        ? ticks.map((price) => {
            const y = yForPrice(price);
            return (
              <SvgText
                key={`yt-${price}`}
                x={padLeft - 4}
                y={y + 3}
                fill="#64748b"
                fontSize="9"
                fontWeight="600"
                textAnchor="end"
              >
                {formatMoney(price)}
              </SvgText>
            );
          })
        : null}

      {model.hasVolume
        ? model.volumeBars.map((bar, i) => {
            const h = Math.max(1, bar.h * volBand);
            const x = xForNorm(bar.x) - barW / 2;
            const y = pad + plotH - h;
            return (
              <Rect
                key={`vol-${i}`}
                x={x}
                y={y}
                width={barW}
                height={h}
                fill={bar.up ? "rgba(34, 197, 94, 0.32)" : "rgba(248, 113, 113, 0.32)"}
              />
            );
          })
        : null}

      {model.fibLines.map((fib) => {
        const y = yForPrice(fib.price);
        return (
          <Line
            key={`${fib.label}-${fib.price}`}
            x1={padLeft}
            y1={y}
            x2={width - pad}
            y2={y}
            stroke={fib.color}
            strokeWidth={1}
            strokeDasharray="4,3"
            opacity={0.75}
          />
        );
      })}

      {pattern?.keyLevelLine ? (
        <Line
          x1={xForNorm(pattern.keyLevelLine.x1)}
          y1={yForNorm(pattern.keyLevelLine.y)}
          x2={xForNorm(pattern.keyLevelLine.x2)}
          y2={yForNorm(pattern.keyLevelLine.y)}
          stroke={pattern.color}
          strokeWidth={1.5}
          strokeDasharray="8,4"
        />
      ) : null}

      {pattern?.targetLine ? (
        <Line
          x1={xForNorm(pattern.targetLine.x1)}
          y1={yForNorm(pattern.targetLine.y)}
          x2={xForNorm(pattern.targetLine.x2)}
          y2={yForNorm(pattern.targetLine.y)}
          stroke={pattern.color}
          strokeWidth={1.5}
          strokeDasharray="2,5"
        />
      ) : null}

      {model.tradeLevels.map((level) => {
        if (level.edge !== "none" || level.y == null) return null;
        const y = yForNorm(level.y);
        const short = level.side === "below" ? "Below" : "Above";
        return (
          <G key={`trade-${level.side}`}>
            <Line
              x1={padLeft}
              y1={y}
              x2={width - pad}
              y2={y}
              stroke={level.color}
              strokeWidth={3}
              strokeDasharray="10,5"
              opacity={0.95}
            />
            <Circle cx={padLeft + 2} cy={y} r={4} fill={level.color} stroke="#0b1220" strokeWidth={1.5} />
            <Circle cx={width - pad - 2} cy={y} r={4} fill={level.color} stroke="#0b1220" strokeWidth={1.5} />
            <Rect
              x={padLeft + 6}
              y={y - 10}
              width={short.length * 6.2 + 8}
              height={14}
              rx={3}
              fill={level.side === "below" ? "rgba(225, 29, 72, 0.92)" : "rgba(5, 150, 105, 0.92)"}
            />
            <SvgText
              x={padLeft + 10}
              y={y + 1}
              fill={level.side === "below" ? "#fff1f2" : "#ecfdf5"}
              fontSize="9"
              fontWeight="800"
            >
              {short}
            </SvgText>
          </G>
        );
      })}

      {model.trendSegments.map((seg) => {
        const x1 = xForNorm(seg.x1);
        const x2 = xForNorm(seg.x2);
        const y1 = yForNorm(seg.y1);
        const y2 = yForNorm(seg.y2);
        return (
          <Line
            key={`${seg.label}-${x1}-${x2}`}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke={seg.color}
            strokeWidth={seg.label === "T1" ? 3.5 : 2.5}
          />
        );
      })}

      {pricePoints ? (
        <Polyline points={pricePoints} fill="none" stroke={model.priceColor} strokeWidth={2.5} />
      ) : null}

      {pattern?.points && pattern.points.length >= 2 ? (
        <Polyline
          points={pointsToPolyline(pattern.points, width, height, padLeft, pad)}
          fill="none"
          stroke={pattern.color}
          strokeWidth={3}
        />
      ) : null}

      {model.trendSegments.map((seg) => {
        const x2 = xForNorm(seg.x2);
        const y2 = yForNorm(seg.y2);
        return <Circle key={`${seg.label}-dot`} cx={x2} cy={y2} r={4} fill={seg.color} />;
      })}

      {pattern?.points.map((pt, idx) => {
        const { x, y } = chartCoord(pt, width, height, padLeft, pad);
        return (
          <Circle
            key={`pattern-pt-${idx}`}
            cx={x}
            cy={y}
            r={6}
            fill={pattern.color}
            stroke="#0b1220"
            strokeWidth={2}
          />
        );
      })}

      {model.fibLines.slice(0, 6).map((fib) => {
        const y = yForPrice(fib.price);
        return (
          <SvgText
            key={`${fib.label}-lbl`}
            x={width - pad - 2}
            y={y - 3}
            fill={fib.color}
            fontSize="9"
            fontWeight="600"
            textAnchor="end"
          >
            {fib.label} {formatPrice(fib.price)}
          </SvgText>
        );
      })}

      {hoverNormX != null ? (
        <Line
          x1={xForNorm(hoverNormX)}
          y1={pad}
          x2={xForNorm(hoverNormX)}
          y2={pad + plotH}
          stroke="rgba(226, 232, 240, 0.45)"
          strokeWidth={1}
          strokeDasharray="3,3"
        />
      ) : null}

      {hoverPoint ? (
        <Circle
          cx={xForNorm(hoverPoint.x)}
          cy={yForNorm(hoverPoint.y)}
          r={5}
          fill={model.priceColor}
          stroke="#0b1220"
          strokeWidth={2}
        />
      ) : null}

      {model.tradeLevels.map((level, idx) => {
        if (level.edge === "none") return null;
        const label = `${level.edge === "top" ? "▲" : "▼"} ${level.label} ${formatMoney(level.price)}`;
        const y = level.edge === "top" ? pad + 12 + idx * 18 : pad + plotH - 8 - idx * 18;
        const tw = Math.min(plotW * 0.7, label.length * 6.5 + 16);
        return (
          <G key={`edge-${level.side}`}>
            <Rect
              x={padLeft + (plotW - tw) / 2}
              y={y - 10}
              width={tw}
              height={16}
              rx={8}
              fill={level.side === "below" ? "rgba(225, 29, 72, 0.92)" : "rgba(5, 150, 105, 0.92)"}
            />
            <SvgText
              x={padLeft + plotW / 2}
              y={y + 2}
              fill={level.side === "below" ? "#fff1f2" : "#ecfdf5"}
              fontSize="9"
              fontWeight="800"
              textAnchor="middle"
            >
              {label}
            </SvgText>
          </G>
        );
      })}
    </Svg>
  );
}
