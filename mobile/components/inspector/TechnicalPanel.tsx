import { StyleSheet, Text, View } from "react-native";

import { InspectorPerformanceChart } from "@/components/inspector/InspectorPerformanceChart";
import { formatMoney, formatPrice } from "@/lib/format";
import { confluenceBiasColor, voteChipStyle } from "@/lib/inspectorHelpers";
import { colors, radii, spacing } from "@/lib/theme";
import type { ChartPatternPayload, InspectorPayload } from "@/lib/types";

function voteArrow(direction?: string): string {
  if (direction === "bull") return "↑";
  if (direction === "bear") return "↓";
  return "·";
}

function formatVolumeShort(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return String(Math.round(value));
}

const VALIDATION_META: Record<
  string,
  { label: string; color: string; backgroundColor: string; borderColor: string }
> = {
  confirmed: {
    label: "VOLUME CONFIRMED",
    color: colors.buy,
    backgroundColor: "rgba(34,197,94,0.12)",
    borderColor: "rgba(34,197,94,0.4)",
  },
  weak: {
    label: "WEAK VOLUME",
    color: colors.warning,
    backgroundColor: "rgba(245,158,11,0.12)",
    borderColor: "rgba(245,158,11,0.4)",
  },
  veto: {
    label: "VOLUME VETO",
    color: colors.sell,
    backgroundColor: "rgba(239,68,68,0.12)",
    borderColor: "rgba(239,68,68,0.4)",
  },
  pending: {
    label: "CONFIRMATION PENDING",
    color: colors.link,
    backgroundColor: "rgba(147,197,253,0.1)",
    borderColor: "rgba(147,197,253,0.35)",
  },
  stale: {
    label: "PLAYED OUT / STALE",
    color: colors.textMuted,
    backgroundColor: "rgba(148,163,184,0.12)",
    borderColor: "rgba(148,163,184,0.4)",
  },
};

function patternTypeColor(type?: string): string {
  if (type === "bullish") return colors.buy;
  if (type === "bearish") return colors.sell;
  return colors.warning;
}

function MiniBadge({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.miniBadge}>
      <Text style={styles.miniLabel}>{label}</Text>
      <Text style={styles.miniValue} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

function PatternCompact({ pattern }: { pattern: ChartPatternPayload }) {
  const conf =
    typeof pattern.confidence === "number"
      ? `${Math.round(pattern.confidence * 100)}%`
      : null;
  const verdict = pattern.validation?.verdict;
  const verdictMeta = verdict ? VALIDATION_META[verdict] : null;
  const metaLine = [
    pattern.status,
    conf,
    pattern.keyLevel?.price != null
      ? `neckline ${formatPrice(pattern.keyLevel.price)}`
      : null,
    pattern.target != null ? `target ≈ ${formatMoney(pattern.target)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <View style={styles.patternBlock}>
      <View style={styles.patternHead}>
        <Text style={[styles.patternName, { color: patternTypeColor(pattern.type) }]}>
          {pattern.name}
        </Text>
        {verdictMeta ? (
          <Text
            style={[
              styles.verdictBadge,
              {
                color: verdictMeta.color,
                backgroundColor: verdictMeta.backgroundColor,
                borderColor: verdictMeta.borderColor,
              },
            ]}
          >
            {verdictMeta.label}
          </Text>
        ) : null}
      </View>
      {metaLine ? <Text style={styles.patternMeta}>{metaLine}</Text> : null}
    </View>
  );
}

interface TechnicalPanelProps {
  data?: InspectorPayload | null;
}

export function TechnicalPanel({ data }: TechnicalPanelProps) {
  const confluence = data?.confluence;
  const advisory = data?.technicalAdvisory;
  const volume = data?.volume;
  const pattern = data?.chartPatterns?.[0];
  const showMetrics = advisory?.stance || volume;

  return (
    <View style={styles.wrap}>
      <View style={styles.card}>
        <Text style={styles.title}>Technical Confluence</Text>

        {confluence?.bias ? (
          <>
            <View style={styles.headRow}>
              <Text style={[styles.bias, { color: confluenceBiasColor(confluence.bias) }]}>
                {confluence.bias}
              </Text>
              <Text style={styles.muted}>
                {[confluence.strength, `${confluence.agreeCount ?? 0}/${confluence.totalSignals ?? 0} agree`]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
            </View>
            <View style={styles.meter}>
              <View
                style={[
                  styles.meterFill,
                  {
                    width: `${confluence.score100 ?? 50}%`,
                    backgroundColor: confluenceBiasColor(confluence.bias),
                  },
                ]}
              />
            </View>
            <View style={styles.votes}>
              {(confluence.votes ?? []).map((vote, idx) => {
                const chip = voteChipStyle(vote.direction);
                return (
                  <Text
                    key={`${vote.agent}-${idx}`}
                    style={[
                      styles.voteChip,
                      {
                        color: chip.color,
                        borderColor: chip.borderColor,
                        backgroundColor: chip.backgroundColor,
                      },
                    ]}
                  >
                    {voteArrow(vote.direction)} {vote.agent}
                  </Text>
                );
              })}
            </View>
          </>
        ) : (
          <Text style={styles.muted}>Insufficient technical data for a fused verdict.</Text>
        )}

        {showMetrics ? (
          <View style={styles.metricsRow}>
            {advisory?.stance ? <MiniBadge label="Stance" value={advisory.stance} /> : null}
            {volume?.rvol != null ? (
              <MiniBadge label="Rel. vol" value={`${volume.rvol.toFixed(2)}×`} />
            ) : null}
            {volume ? (
              <MiniBadge
                label="OBV"
                value={
                  volume.obvLabel ??
                  (volume.obvSlopePct != null ? `${volume.obvSlopePct.toFixed(1)}%` : "—")
                }
              />
            ) : null}
            {volume?.state ? <MiniBadge label="State" value={volume.state} /> : null}
            {volume?.avgVolume20 != null ? (
              <MiniBadge label="Avg 20d" value={formatVolumeShort(volume.avgVolume20)} />
            ) : null}
          </View>
        ) : null}

        {pattern ? <PatternCompact pattern={pattern} /> : null}
      </View>

      <InspectorPerformanceChart data={data} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingBottom: spacing.md,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
  },
  headRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  bias: {
    fontSize: 16,
    fontWeight: "800",
  },
  muted: {
    color: colors.textMuted,
    fontSize: 12,
    flexShrink: 1,
    textAlign: "right",
  },
  meter: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceAlt,
    overflow: "hidden",
  },
  meterFill: {
    height: "100%",
    borderRadius: 3,
    opacity: 0.85,
  },
  votes: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  voteChip: {
    fontSize: 11,
    borderWidth: 1,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 999,
    overflow: "hidden",
    textTransform: "capitalize",
  },
  metricsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  miniBadge: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: radii.sm,
    paddingHorizontal: 8,
    paddingVertical: 5,
    minWidth: 58,
    gap: 1,
  },
  miniLabel: {
    color: colors.textMuted,
    fontSize: 8,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  miniValue: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "700",
  },
  patternBlock: {
    gap: 3,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  patternHead: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  patternName: {
    fontSize: 13,
    fontWeight: "700",
  },
  verdictBadge: {
    fontSize: 9,
    fontWeight: "700",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 6,
    paddingVertical: 2,
    overflow: "hidden",
  },
  patternMeta: {
    color: colors.textMuted,
    fontSize: 11,
    lineHeight: 15,
  },
});
