import { useEffect, useState } from "react";
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { api } from "@/lib/api";
import { colors, radii, spacing } from "@/lib/theme";
import type { Note } from "@/lib/types";

function todayIso(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export interface NoteDraft {
  symbol: string;
  date: string;
  title: string;
  text: string;
}

interface NoteModalProps {
  visible: boolean;
  draft: NoteDraft | null;
  onClose: () => void;
  onSaved?: (note: Note, symbol: string) => void;
}

export function NoteModal({ visible, draft, onClose, onSaved }: NoteModalProps) {
  const [date, setDate] = useState(todayIso());
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!draft) return;
    setDate(draft.date || todayIso());
    setTitle(draft.title || "");
    setText(draft.text || "");
    setError(null);
  }, [draft]);

  async function save() {
    if (!draft?.symbol || !text.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Note = {
        date: date.trim() || todayIso(),
        source: title.trim() || undefined,
        text: text.trim(),
      };
      await api.addNote(draft.symbol, payload);
      onSaved?.(payload, draft.symbol);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setSaving(false);
    }
  }

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
            <Text style={styles.headerBtn}>Cancel</Text>
          </Pressable>
          <Text style={styles.headerTitle}>Add note · {draft?.symbol ?? ""}</Text>
          <Pressable onPress={() => void save()} disabled={saving || !text.trim()} hitSlop={8}>
            <Text style={[styles.headerBtn, (saving || !text.trim()) && styles.headerBtnDisabled]}>
              {saving ? "Saving…" : "Save"}
            </Text>
          </Pressable>
        </View>
        <View style={styles.body}>
          <View style={styles.row}>
            <TextInput
              style={[styles.input, styles.dateInput]}
              value={date}
              onChangeText={setDate}
              placeholder="YYYY-MM-DD"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <TextInput
              style={[styles.input, styles.titleInput]}
              value={title}
              onChangeText={setTitle}
              placeholder="Title"
              placeholderTextColor={colors.textMuted}
            />
          </View>
          <TextInput
            style={[styles.input, styles.textInput]}
            value={text}
            onChangeText={setText}
            placeholder="Note text…"
            placeholderTextColor={colors.textMuted}
            multiline
            textAlignVertical="top"
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
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
  headerBtnDisabled: {
    opacity: 0.5,
  },
  body: {
    padding: spacing.lg,
    gap: spacing.sm,
  },
  row: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    color: colors.text,
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    fontSize: 14,
  },
  dateInput: {
    width: 118,
  },
  titleInput: {
    flex: 1,
  },
  textInput: {
    minHeight: 140,
  },
  error: {
    color: colors.danger,
    fontSize: 13,
  },
});
