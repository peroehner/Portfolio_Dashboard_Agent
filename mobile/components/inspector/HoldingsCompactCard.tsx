import { StyleSheet, Text, View } from "react-native";

import { getPositionDisplay } from "@/lib/inspectorHelpers";
import { formatMoney, formatPct, formatRelativeDate, pctColor } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { InspectorPayload } from "@/lib/types";

interface HoldingsCompactCardProps {
  data?: InspectorPayload | null;
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
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <View style={styles.cell}>
      <Text style={styles.cellLabel}>{label}</Text>
      <Text style={[styles.cellValue, valueColor ? { color: valueColor } : null]} numberOfLines={2}>
        {value}
      </Text>
    </View>
  );
}

export function HoldingsCompactCard({ data }: HoldingsCompactCardProps) {
  const pos = getPositionDisplay(data, data?.quote, data?.holding);
  const gainTxt =
    pos.gain != null
      ? `${formatMoney(pos.gain)} (${formatPct(pos.gainPct)})`
      : formatPct(pos.gainPct);

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Holdings</Text>
      {!pos.hasPosition ? (
        <Text style={styles.muted}>No holding recorded.</Text>
      ) : (
        <View style={styles.grid}>
          <View style={styles.col}>
            <ColCell label="Entry" value={pos.entryDate ? formatRelativeDate(pos.entryDate) : "—"} />
            <ColCell label="Sh" value={formatShares(pos.shares)} />
            <ColCell label="Inv" value={formatMoney(pos.investment)} />
          </View>
          <View style={styles.col}>
            <ColCell label="Value" value={formatMoney(pos.currentValue)} />
            <ColCell label="Gain" value={gainTxt} valueColor={pctColor(pos.gainPct)} />
            <ColCell label="Tgt" value={formatMoney(pos.personalTargetValue)} />
          </View>
          <View style={styles.col}>
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
  col: {
    flex: 1,
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
