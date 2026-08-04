import { StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";
import type { NoteSynthesis } from "@/lib/types";

export function noteHasSynthesis(note: { synthesis?: NoteSynthesis | null } | null | undefined): boolean {
  return Boolean(note?.synthesis?.summary);
}

interface NoteSynthesisViewProps {
  synthesis: NoteSynthesis;
  /** When false, show summary only (truncated). When true, show full structured body. */
  expanded?: boolean;
}

export function NoteSynthesisView({ synthesis, expanded = false }: NoteSynthesisViewProps) {
  const sentiment = String(synthesis.sentiment || "neutral").toLowerCase();
  const title = `Note Synthesis · ${sentiment}${synthesis.llmFallback ? " · rules fallback" : ""}`;
  const growth = synthesis.growthTrajectory || [];
  const projections = synthesis.revenueProjections || [];
  const catalysts = synthesis.catalystsToWatch || [];

  return (
    <View style={styles.box}>
      <Text style={styles.title}>{title}</Text>
      {synthesis.llmFallback && synthesis.llmError ? (
        <Text style={styles.fallback}>{String(synthesis.llmError)}</Text>
      ) : null}
      {synthesis.summary ? (
        <Text style={styles.summary} numberOfLines={expanded ? undefined : 4}>
          {synthesis.summary}
        </Text>
      ) : null}
      {expanded ? (
        <>
          {growth.length ? (
            <View style={styles.list}>
              {growth.map((g, idx) => (
                <Text key={`g-${idx}`} style={styles.listItem}>
                  · <Text style={styles.listStrong}>{g.metric || "Growth"}:</Text>{" "}
                  {[g.growth, g.period ? `(${g.period})` : ""].filter(Boolean).join(" ")}
                </Text>
              ))}
            </View>
          ) : null}
          {projections.length ? (
            <View style={styles.list}>
              {projections.map((p, idx) => (
                <Text key={`p-${idx}`} style={styles.listItem}>
                  · {[p.target, p.timeline ? `by ${p.timeline}` : ""].filter(Boolean).join(" ")}
                </Text>
              ))}
            </View>
          ) : null}
          {catalysts.length ? (
            <View style={styles.list}>
              {catalysts.map((c, idx) => (
                <Text key={`c-${idx}`} style={styles.listItem}>
                  · <Text style={styles.listStrong}>{c.period || "Upcoming"}:</Text>{" "}
                  {[c.metric, c.threshold ? `— watch for ${c.threshold}` : ""]
                    .filter(Boolean)
                    .join(" ")}
                </Text>
              ))}
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    backgroundColor: "rgba(167,139,250,0.08)",
    borderWidth: 1,
    borderColor: "rgba(167,139,250,0.28)",
    borderRadius: radii.sm,
    padding: spacing.sm,
    gap: 6,
  },
  title: {
    color: "#c4b5fd",
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  fallback: {
    color: colors.warning,
    fontSize: 12,
    lineHeight: 16,
  },
  summary: {
    color: colors.text,
    fontSize: 13,
    lineHeight: 19,
  },
  list: {
    gap: 3,
    marginTop: 2,
  },
  listItem: {
    color: colors.textMuted,
    fontSize: 12,
    lineHeight: 17,
  },
  listStrong: {
    color: colors.text,
    fontWeight: "700",
  },
});
