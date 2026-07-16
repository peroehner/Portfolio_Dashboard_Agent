import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { NewsSymbolGroupCard, SaiChangeCard } from "@/components/NewsCards";
import { NewsArticleModal } from "@/components/NewsArticleModal";
import { NoteModal, type NoteDraft } from "@/components/NoteModal";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { symbolMatchesFilter } from "@/lib/filters";
import {
  changeTimestamp,
  filterRecoChanges,
  groupNewsBySymbol,
  recoChangesCounts,
  type RecoChangesDirFilter,
} from "@/lib/newsFilters";
import { formatShortDateTime } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { NewsFeed, NewsItem } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

type Pane = "changes" | "news";

function todayIso(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function buildNoteDraftFromNews(item: NewsItem): NoteDraft {
  const parts: string[] = [];
  if (item.summary) parts.push(item.summary);
  if (item.link) parts.push(item.link);
  return {
    symbol: item.symbol,
    date: todayIso(),
    title: item.title || item.publisher || "",
    text: parts.join("\n\n"),
  };
}

function dirBtnStyle(active: boolean, kind: "up" | "down") {
  if (!active) {
    return kind === "up"
      ? { borderColor: "#22c55e", backgroundColor: colors.surface }
      : { borderColor: "#ef4444", backgroundColor: colors.surface };
  }
  return kind === "up"
    ? { borderColor: "#22c55e", backgroundColor: "#22c55e" }
    : { borderColor: "#ef4444", backgroundColor: "#ef4444" };
}

function dirBtnTextStyle(active: boolean, kind: "up" | "down") {
  if (active) return { color: kind === "up" ? "#0a1a0f" : "#1a0a0a" };
  return { color: kind === "up" ? "#22c55e" : "#ef4444" };
}

function PaneHeader({
  title,
  count,
  expanded,
  onExpand,
  onSplit,
}: {
  title: string;
  count?: string;
  expanded: boolean;
  onExpand: () => void;
  onSplit: () => void;
}) {
  return (
    <View style={styles.paneHead}>
      <View style={styles.paneHeadLeft}>
        <Text style={styles.paneTitle}>{title}</Text>
        {count ? <Text style={styles.paneCount}>{count}</Text> : null}
      </View>
      {expanded ? (
        <Pressable
          style={styles.paneAction}
          onPress={onSplit}
          accessibilityLabel="Show both columns"
          hitSlop={8}
        >
          <Ionicons name="contract-outline" size={16} color={colors.link} />
          <Text style={styles.paneActionText}>Split</Text>
        </Pressable>
      ) : (
        <Pressable
          style={styles.paneAction}
          onPress={onExpand}
          accessibilityLabel={`Expand ${title}`}
          hitSlop={8}
        >
          <Ionicons name="expand-outline" size={16} color={colors.link} />
        </Pressable>
      )}
    </View>
  );
}

export default function NewsScreen() {
  const [filter, setFilter] = useState("");
  const [dirFilter, setDirFilter] = useState<RecoChangesDirFilter>("");
  const [expanded, setExpanded] = useState<Pane | null>(null);
  const [noteDraft, setNoteDraft] = useState<NoteDraft | null>(null);
  const [newsArticle, setNewsArticle] = useState<NewsItem | null>(null);
  const [expandedNewsSymbols, setExpandedNewsSymbols] = useState<Set<string>>(
    () => new Set(),
  );
  const { data, loading, error, refresh } = useApiQuery<NewsFeed>(
    () => api.newsFeed(),
    [],
  );

  const tickerFilteredChanges = useMemo(
    () =>
      (data?.recommendationChanges ?? []).filter((item) =>
        symbolMatchesFilter(item.symbol, filter),
      ),
    [data?.recommendationChanges, filter],
  );

  const changes = useMemo(
    () => filterRecoChanges(tickerFilteredChanges, dirFilter),
    [tickerFilteredChanges, dirFilter],
  );

  const changeCounts = useMemo(() => recoChangesCounts(changes), [changes]);

  const news = useMemo(
    () =>
      (data?.topNews ?? []).filter((item) => symbolMatchesFilter(item.symbol, filter)),
    [data?.topNews, filter],
  );

  const newsGroups = useMemo(() => groupNewsBySymbol(news), [news]);

  const showChanges = expanded !== "news";
  const showNews = expanded !== "changes";
  const split = expanded === null;
  const changesFullscreen = expanded === "changes";

  function toggleDirFilter(dir: "up" | "down") {
    setDirFilter((prev) => (prev === dir ? "" : dir));
  }

  function toggleNewsGroup(symbol: string) {
    setExpandedNewsSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }

  function openPortfolioSymbol(symbol: string) {
    router.push({ pathname: "/portfolio", params: { symbol: symbol.toUpperCase() } });
  }

  const subtitle = data?.newsCheckedAt
    ? `Checked ${formatShortDateTime(data.newsCheckedAt)}${split ? " · tap ⤢ to expand a column" : " · tap Split to show both"}`
    : split
      ? "Tap ⤢ on a column header to expand"
      : "Tap Split to show both columns";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="News & Changes"
        subtitle={subtitle}
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
        contentStyle={styles.screenContent}
      >
        <TextInput
          style={styles.filter}
          placeholder="Filter…"
          placeholderTextColor={colors.textMuted}
          value={filter}
          onChangeText={setFilter}
          autoCapitalize="characters"
          autoCorrect={false}
        />

        <View style={[styles.split, split && styles.splitColumns]}>
          {showChanges ? (
            <View style={[styles.pane, split && styles.paneColumn]}>
              <PaneHeader
                title="Changes"
                count={
                  changesFullscreen && changeCounts.total > 0
                    ? `${changeCounts.total} · ▲${changeCounts.up} · ▼${changeCounts.down}`
                    : split
                      ? String(changes.length)
                      : undefined
                }
                expanded={changesFullscreen}
                onExpand={() => setExpanded("changes")}
                onSplit={() => setExpanded(null)}
              />
              {changesFullscreen ? (
                <View style={styles.dirControls}>
                  <Text style={styles.dirLabel}>Direction</Text>
                  <View style={styles.dirBtns}>
                    <Pressable
                      style={[styles.dirBtn, dirBtnStyle(dirFilter === "up", "up")]}
                      onPress={() => toggleDirFilter("up")}
                    >
                      <Text style={[styles.dirBtnText, dirBtnTextStyle(dirFilter === "up", "up")]}>
                        ▲ Up
                      </Text>
                    </Pressable>
                    <Pressable
                      style={[styles.dirBtn, dirBtnStyle(dirFilter === "down", "down")]}
                      onPress={() => toggleDirFilter("down")}
                    >
                      <Text
                        style={[styles.dirBtnText, dirBtnTextStyle(dirFilter === "down", "down")]}
                      >
                        ▼ Down
                      </Text>
                    </Pressable>
                  </View>
                </View>
              ) : null}
              <ScrollView
                nestedScrollEnabled
                showsVerticalScrollIndicator
                refreshControl={
                  expanded === "changes" ? (
                    <RefreshControl
                      refreshing={loading && !!data}
                      onRefresh={() => void refresh()}
                      tintColor={colors.accent}
                    />
                  ) : undefined
                }
                contentContainerStyle={styles.paneScroll}
              >
                {changes.length === 0 ? (
                  <Text style={styles.empty}>
                    {tickerFilteredChanges.length && (filter.trim() || dirFilter)
                      ? "No changes match the current filter."
                      : "No changes"}
                  </Text>
                ) : (
                  changes.map((change, idx) => (
                    <SaiChangeCard
                      key={`${change.symbol}-${changeTimestamp(change) ?? idx}-${idx}`}
                      change={change}
                      compact={split}
                      onOpenPortfolio={openPortfolioSymbol}
                    />
                  ))
                )}
              </ScrollView>
            </View>
          ) : null}

          {showNews ? (
            <View style={[styles.pane, split && styles.paneColumn, split && styles.paneColumnRight]}>
              <PaneHeader
                title="News"
                count={
                  split
                    ? `${newsGroups.length}${news.length !== newsGroups.length ? ` · ${news.length}` : ""}`
                    : expanded === "news"
                      ? `${newsGroups.length} symbols · ${news.length} news`
                      : undefined
                }
                expanded={expanded === "news"}
                onExpand={() => setExpanded("news")}
                onSplit={() => setExpanded(null)}
              />
              <ScrollView
                nestedScrollEnabled
                showsVerticalScrollIndicator
                refreshControl={
                  expanded === "news" ? (
                    <RefreshControl
                      refreshing={loading && !!data}
                      onRefresh={() => void refresh()}
                      tintColor={colors.accent}
                    />
                  ) : undefined
                }
                contentContainerStyle={styles.paneScroll}
              >
                {newsGroups.length === 0 ? (
                  <Text style={styles.empty}>No news</Text>
                ) : (
                  newsGroups.map((group) => (
                    <NewsSymbolGroupCard
                      key={group.symbol}
                      symbol={group.symbol}
                      items={group.items}
                      compact={split}
                      expanded={expandedNewsSymbols.has(group.symbol)}
                      onToggleExpand={() => toggleNewsGroup(group.symbol)}
                      onAddNote={(newsItem) => setNoteDraft(buildNoteDraftFromNews(newsItem))}
                      onOpenNews={setNewsArticle}
                    />
                  ))
                )}
              </ScrollView>
            </View>
          ) : null}
        </View>

        <NoteModal
          visible={!!noteDraft}
          draft={noteDraft}
          onClose={() => setNoteDraft(null)}
        />
        <NewsArticleModal
          visible={!!newsArticle}
          item={newsArticle}
          onClose={() => setNewsArticle(null)}
        />
      </Screen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  screenContent: { flex: 1 },
  filter: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    color: colors.text,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 14,
  },
  split: {
    flex: 1,
    flexDirection: "row",
  },
  splitColumns: {
    gap: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingBottom: spacing.sm,
  },
  pane: {
    flex: 1,
    minWidth: 0,
  },
  paneColumn: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    overflow: "hidden",
  },
  paneColumnRight: {
    borderLeftWidth: 1,
  },
  paneHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.surfaceAlt,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  paneHeadLeft: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minWidth: 0,
  },
  paneTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "700",
    flexShrink: 0,
  },
  paneCount: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: "600",
    flexShrink: 1,
  },
  paneAction: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.xs,
    paddingVertical: 4,
    borderRadius: radii.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  paneActionText: {
    color: colors.link,
    fontSize: 12,
    fontWeight: "600",
  },
  dirControls: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  dirLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  dirBtns: {
    flexDirection: "row",
    gap: spacing.xs,
  },
  dirBtn: {
    borderWidth: 1,
    borderRadius: radii.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
  },
  dirBtnText: {
    fontSize: 12,
    fontWeight: "700",
  },
  paneScroll: {
    paddingVertical: spacing.xs,
    paddingBottom: spacing.lg,
  },
  empty: {
    color: colors.textMuted,
    fontSize: 12,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.md,
  },
});
