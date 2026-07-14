import Svg, { Circle, Line, Polyline, Text as SvgText } from "react-native-svg";

import {
  chartCoord,
  pointsToPolyline,
  type InspectorChartModel,
} from "@/lib/chartHelpers";
import { formatPrice } from "@/lib/format";

const PAD = 12;

interface InspectorChartSvgProps {
  model: InspectorChartModel;
  width: number;
  height: number;
}

export function InspectorChartSvg({ model, width, height }: InspectorChartSvgProps) {
  const pricePoints = pointsToPolyline(model.priceLine, width, height, PAD);
  const yForPrice = (price: number) => {
    const yNorm = 1 - (price - model.minPrice) / Math.max(model.maxPrice - model.minPrice, 1);
    return PAD + yNorm * (height - PAD * 2);
  };

  const pattern = model.pattern;

  return (
    <Svg width={width} height={height}>
      {model.fibLines.map((fib) => {
        const y = yForPrice(fib.price);
        return (
          <Line
            key={`${fib.label}-${fib.price}`}
            x1={PAD}
            y1={y}
            x2={width - PAD}
            y2={y}
            stroke={fib.color}
            strokeWidth={1}
            strokeDasharray="5,4"
            opacity={0.85}
          />
        );
      })}

      {pattern?.keyLevelLine ? (
        <Line
          x1={PAD + pattern.keyLevelLine.x1 * (width - PAD * 2)}
          y1={PAD + pattern.keyLevelLine.y * (height - PAD * 2)}
          x2={PAD + pattern.keyLevelLine.x2 * (width - PAD * 2)}
          y2={PAD + pattern.keyLevelLine.y * (height - PAD * 2)}
          stroke={pattern.color}
          strokeWidth={1.5}
          strokeDasharray="8,4"
        />
      ) : null}

      {pattern?.targetLine ? (
        <Line
          x1={PAD + pattern.targetLine.x1 * (width - PAD * 2)}
          y1={PAD + pattern.targetLine.y * (height - PAD * 2)}
          x2={PAD + pattern.targetLine.x2 * (width - PAD * 2)}
          y2={PAD + pattern.targetLine.y * (height - PAD * 2)}
          stroke={pattern.color}
          strokeWidth={1.5}
          strokeDasharray="2,5"
        />
      ) : null}

      {model.trendSegments.map((seg) => {
        const x1 = PAD + seg.x1 * (width - PAD * 2);
        const x2 = PAD + seg.x2 * (width - PAD * 2);
        const y1 = PAD + seg.y1 * (height - PAD * 2);
        const y2 = PAD + seg.y2 * (height - PAD * 2);
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
          points={pointsToPolyline(pattern.points, width, height, PAD)}
          fill="none"
          stroke={pattern.color}
          strokeWidth={3}
        />
      ) : null}

      {model.trendSegments.map((seg) => {
        const x2 = PAD + seg.x2 * (width - PAD * 2);
        const y2 = PAD + seg.y2 * (height - PAD * 2);
        return <Circle key={`${seg.label}-dot`} cx={x2} cy={y2} r={4} fill={seg.color} />;
      })}

      {pattern?.points.map((pt, idx) => {
        const { x, y } = chartCoord(pt, width, height, PAD);
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
            x={width - PAD - 2}
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
    </Svg>
  );
}
