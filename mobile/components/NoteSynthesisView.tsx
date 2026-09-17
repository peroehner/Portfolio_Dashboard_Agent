import { StyleSheet, Text, View } from "react-native";

import { colors, radii, spacing } from "@/lib/theme";
import type { NoteSynthesis } from "@/lib/types";

export function noteHasSynthesis(note: { synthesis?: NoteSynthesis | null } | null | undefined): boolean {
  return Boolean(note?.synthesis?.summary);
}

/** Top-level sentiment is home-symbol stance; linked tickers use relevantSymbols[].sentiment. */
export function synthesisSentimentForViewer(
  synthesis: NoteSynthesis | null | undefined,
  viewSymbol?: string | null,
  homeSymbol?: string | null,
): string {
  if (!synthesis) return "neutral";
  const view = String(viewSymbol || "").trim().toUpperCase();
  const home = String(homeSymbol || "").trim().toUpperCase();
  const top = String(synthesis.sentiment || "neutral").trim().toLowerCase();
  const valid = new Set(["bullish", "neutral", "bearish"]);
  const safeTop = valid.has(top) ? top : "neutral";
  for (const item of synthesis.relevantSymbols || []) {
    if (!item || typeof item !== "object") continue;
    if (String(item.symbol || "").trim().toUpperCase() !== view) continue;
    const linkSent = String(item.sentiment || "").trim().toLowerCase();
    if (valid.has(linkSent)) return linkSent;
    break;
  }
  if (!home || !view || view === home) return safeTop;
  return "neutral";
}

interface NoteSynthesisViewProps {
  synthesis: NoteSynthesis;
  /** When false, show summary only (truncated). When true, show full structured body. */
  expanded?: boolean;
  /** Symbol whose Target/Notes tab is open (may differ from provisional home). */
  viewSymbol?: string;
  /** Provisional/home symbol on the note row. */
  homeSymbol?: string;
}

export function NoteSynthesisView({
  synthesis,
  expanded = false,
  viewSymbol,
  homeSymbol,
}: NoteSynthesisViewProps) {
  const sentiment = synthesisSentimentForViewer(synthesis, viewSymbol, homeSymbol);
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
