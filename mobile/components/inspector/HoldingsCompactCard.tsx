import { StyleSheet, Text, View, type ViewStyle } from "react-native";

import { getPositionDisplay } from "@/lib/inspectorHelpers";
import { formatEntryDate, formatMoney, formatPct, pctColor } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface HoldingsCompactCardProps {
  data?: InspectorPayload | null;
  style?: ViewStyle | ViewStyle[];
}

function formatShares(value: number | null): string {
  if (value == null) return "—";
  return Number.isInteger(value)
    ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function ColCell({
  label,
  value,
  valueColor,
  singleLine,
}: {
  label: string;
  value: string;
  valueColor?: string;
  singleLine?: boolean;
}) {
  return (
    <View style={styles.cell}>
      <Text style={styles.cellLabel}>{label}</Text>
      <Text
        style={[styles.cellValue, valueColor ? { color: valueColor } : null]}
        numberOfLines={singleLine ? 1 : 2}
        adjustsFontSizeToFit={singleLine}
        minimumFontScale={0.85}
      >
        {value}
      </Text>
    </View>
  );
}

export function HoldingsCompactCard({ data, style }: HoldingsCompactCardProps) {
  const pos = getPositionDisplay(data, data?.quote, data?.holding);
  const gainTxt =
    pos.gain != null
      ? `${formatMoney(pos.gain)} (${formatPct(pos.gainPct, 0)})`
      : formatPct(pos.gainPct, 0);
  const tgtTxt =
    pos.personalTargetValue != null
      ? `${formatMoney(pos.personalTargetValue)}${
          pos.personalUpsidePct != null ? ` (${formatPct(pos.personalUpsidePct, 0)})` : ""
        }`
      : pos.personalUpsidePct != null
        ? formatPct(pos.personalUpsidePct, 0)
        : "—";

  return (
    <View style={[styles.card, style]}>
      <Text style={styles.title}>Holdings</Text>
      {!pos.hasPosition ? (
        <Text style={styles.muted}>No holding recorded.</Text>
      ) : (
        <View style={styles.grid}>
          <View style={styles.colLeft}>
            <ColCell label="Entry" value={pos.entryDate ? formatEntryDate(pos.entryDate) : "—"} />
            <ColCell label="Shares" value={formatShares(pos.shares)} />
            <ColCell label="Investment" value={formatMoney(pos.investment)} />
          </View>
          <View style={styles.colMid}>
            <ColCell label="Value" value={formatMoney(pos.currentValue)} singleLine />
            <ColCell label="Gain" value={gainTxt} valueColor={pctColor(pos.gainPct)} singleLine />
            <ColCell
              label="Target"
              value={tgtTxt}
              valueColor={pos.personalUpsidePct != null ? pctColor(pos.personalUpsidePct) : undefined}
              singleLine
            />
          </View>
          <View style={styles.colRight}>
            <ColCell
              label="Est. Div"
              value={pos.estDividend != null && pos.estDividend > 0 ? formatMoney(pos.estDividend) : "—"}
              valueColor={pos.estDividend != null && pos.estDividend > 0 ? colors.buy : undefined}
            />
          </View>
        </View>
      )}
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
    gap: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
  },
  muted: {
    color: colors.textMuted,
    fontSize: 12,
  },
  grid: {
    flexDirection: "row",
    gap: spacing.xs,
  },
  colLeft: {
    flex: 0.9,
    gap: spacing.sm,
    minWidth: 0,
  },
  colMid: {
    flex: 1.85,
    gap: spacing.sm,
    minWidth: 0,
  },
  colRight: {
    flex: 0.7,
    gap: spacing.sm,
    minWidth: 0,
  },
  cell: {
    gap: 1,
  },
  cellLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  cellValue: {
    color: colors.text,
    fontSize: 11,
    fontWeight: "600",
    lineHeight: 14,
  },
});
