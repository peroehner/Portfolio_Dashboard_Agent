import { StyleSheet, Text, View } from "react-native";

import { formatPct, formatPrice, pctColor } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface QuoteHeaderProps {
  companyName?: string | null;
  price?: number | null;
  dayChangePct?: number | null;
}

export function QuoteHeader({ companyName, price, dayChangePct }: QuoteHeaderProps) {
  return (
    <View style={styles.wrap}>
      <View style={styles.priceRow}>
        <Text style={styles.price}>{formatPrice(price)}</Text>
        <Text style={[styles.change, { color: pctColor(dayChangePct) }]}>
          {formatPct(dayChangePct)}
        </Text>
        {companyName ? (
          <Text style={styles.company} numberOfLines={2}>
            {companyName}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

interface TechnicalBadgesProps {
  data?: InspectorPayload | null;
}

export function TechnicalBadges({ data }: TechnicalBadgesProps) {
  const advisory = data?.technicalAdvisory;
  const volume = data?.volume;

  if (!advisory?.stance && !volume) return null;

  return (
    <View style={styles.card}>
      {advisory?.stance ? (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Technical stance</Text>
          <View style={styles.badgeRow}>
            <Badge label="Stance" value={advisory.stance} tone="stance" />
          </View>
        </View>
      ) : null}
      {volume ? (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Volume</Text>
          <View style={styles.badgeRow}>
            <Badge
              label="Rel. vol"
              value={volume.rvol != null ? `${volume.rvol.toFixed(2)}×` : "—"}
            />
            <Badge
              label="OBV"
              value={
                volume.obvLabel ??
                (volume.obvSlopePct != null ? `${volume.obvSlopePct.toFixed(1)}%` : "—")
              }
            />
            <Badge label="State" value={volume.state ?? "—"} />
            {volume.avgVolume20 != null ? (
              <Badge label="Avg 20d" value={formatVolumeShort(volume.avgVolume20)} />
            ) : null}
          </View>
        </View>
      ) : null}
    </View>
  );
}

function Badge({
  label,
  value,
  tone,
}: {
  label: string;
  value?: string;
  tone?: "stance";
}) {
  return (
    <View style={[styles.badge, tone === "stance" && styles.badgeStance]}>
      <Text style={styles.badgeLabel}>{label}</Text>
      {value != null ? <Text style={styles.badgeValue}>{value}</Text> : null}
    </View>
  );
}

function formatVolumeShort(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return String(Math.round(value));
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xs,
    paddingBottom: spacing.sm,
  },
  priceRow: {
    flexDirection: "row",
    alignItems: "baseline",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  price: {
    color: colors.text,
    fontSize: 24,
    fontWeight: "800",
  },
  change: {
    fontSize: 16,
    fontWeight: "700",
  },
  company: {
    flex: 1,
    minWidth: 120,
    color: colors.textMuted,
    fontSize: 14,
    fontWeight: "600",
    lineHeight: 18,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  section: {
    gap: spacing.xs,
  },
  sectionLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  badgeRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  badge: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    minWidth: 72,
    gap: 2,
  },
  badgeStance: {
    borderWidth: 1,
    borderColor: colors.border,
  },
  badgeLabel: {
    color: colors.textMuted,
    fontSize: 9,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  badgeValue: {
    color: colors.text,
    fontSize: 12,
    fontWeight: "700",
  },
});
