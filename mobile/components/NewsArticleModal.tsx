import { Linking, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { formatRelativeDate } from "@/lib/format";
import { colors, radii, spacing } from "@/lib/theme";
import type { NewsItem } from "@/lib/types";

interface NewsArticleModalProps {
  visible: boolean;
  item: NewsItem | null;
  onClose: () => void;
}

export function NewsArticleModal({ visible, item, onClose }: NewsArticleModalProps) {
  const meta = [item?.publisher, item?.published ? formatRelativeDate(item.published) : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.root}>
        <View style={styles.header}>
          <Pressable onPress={onClose} hitSlop={8}>
            <Text style={styles.headerBtn}>Close</Text>
          </Pressable>
          <Text style={styles.headerTitle} numberOfLines={1}>
            {item?.symbol ?? "News"}
          </Text>
          <View style={styles.headerSpacer} />
        </View>
        <ScrollView contentContainerStyle={styles.body}>
          {meta ? <Text style={styles.meta}>{meta}</Text> : null}
          <Text style={styles.title}>{item?.title || "Untitled"}</Text>
          {item?.summary ? <Text style={styles.summary}>{item.summary}</Text> : null}
          {item?.link ? (
            <Pressable onPress={() => void Linking.openURL(item.link!)} style={styles.linkBtn}>
              <Text style={styles.linkText}>Open article</Text>
            </Pressable>
          ) : null}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
  },
  headerTitle: {
    color: colors.text,
    fontSize: 15,
    fontWeight: "700",
    flex: 1,
    textAlign: "center",
  },
  headerBtn: {
    color: colors.link,
    fontSize: 15,
    fontWeight: "700",
    minWidth: 56,
  },
  headerSpacer: {
    minWidth: 56,
  },
  body: {
    padding: spacing.lg,
    gap: spacing.md,
    paddingBottom: spacing.xl,
  },
  meta: {
    color: colors.textMuted,
    fontSize: 13,
  },
  title: {
    color: colors.text,
    fontSize: 20,
    fontWeight: "700",
    lineHeight: 26,
  },
  summary: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 22,
  },
  linkBtn: {
    alignSelf: "flex-start",
    marginTop: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radii.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  linkText: {
    color: colors.link,
    fontSize: 14,
    fontWeight: "600",
  },
});
