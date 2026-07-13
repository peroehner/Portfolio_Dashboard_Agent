import { useMemo, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { NewsCard, SaiChangeCard } from "@/components/NewsCards";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import { symbolMatchesFilter } from "@/lib/filters";
import { colors, radii, spacing } from "@/lib/theme";
import type { NewsFeed } from "@/lib/types";
import { useApiQuery } from "@/lib/useApiQuery";

export default function NewsScreen() {
  const [filter, setFilter] = useState("");
  const { data, loading, error, refresh } = useApiQuery<NewsFeed>(
    () => api.newsFeed(),
    [],
  );

  const changes = useMemo(
    () =>
      (data?.recommendationChanges ?? []).filter((item) =>
        symbolMatchesFilter(item.symbol, filter),
      ),
    [data?.recommendationChanges, filter],
  );

  const news = useMemo(
    () =>
      (data?.topNews ?? []).filter((item) => symbolMatchesFilter(item.symbol, filter)),
    [data?.topNews, filter],
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Screen
        title="News & Changes"
        subtitle={data?.newsCheckedAt ? `Checked ${data.newsCheckedAt}` : undefined}
        loading={loading && !data}
        error={error}
        onRetry={() => void refresh()}
      >
        <TextInput
          style={styles.filter}
          placeholder="Filter tickers (comma-separated)…"
          placeholderTextColor={colors.textMuted}
          value={filter}
          onChangeText={setFilter}
          autoCapitalize="characters"
          autoCorrect={false}
        />
        <ScrollView
          refreshControl={
            <RefreshControl
              refreshing={loading && !!data}
              onRefresh={() => void refresh()}
              tintColor={colors.accent}
            />
          }
          contentContainerStyle={styles.scroll}
        >
          <Text style={styles.sectionTitle}>SAI changes</Text>
          {changes.length === 0 ? (
            <Text style={styles.empty}>No SAI changes match the filter.</Text>
          ) : (
            changes.map((change, idx) => (
              <SaiChangeCard key={`${change.symbol}-${change.changedAt}-${idx}`} change={change} />
            ))
          )}

          <Text style={[styles.sectionTitle, styles.sectionGap]}>Latest news</Text>
          {news.length === 0 ? (
            <Text style={styles.empty}>No news matches the filter.</Text>
          ) : (
            news.map((item, idx) => (
              <NewsCard key={`${item.symbol}-${item.title}-${idx}`} item={item} />
            ))
          )}
        </ScrollView>
      </Screen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
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
    fontSize: 15,
  },
  scroll: { paddingBottom: spacing.xl },
  sectionTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  sectionGap: {
    marginTop: spacing.lg,
  },
  empty: {
    color: colors.textMuted,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.md,
  },
});
