import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Alert } from "react-native";

import { api } from "@/lib/api";
import {
  exportSegmentsText,
  normalizeSegmentName,
  parseSegmentCommand,
  type TickerSegmentsMap,
} from "@/lib/filters";

interface TickerSegmentsContextValue {
  segments: TickerSegmentsMap;
  hydrated: boolean;
  refresh: () => Promise<void>;
  /** Apply define/delete command if the whole field is a command; returns next filter text. */
  applyCommand: (raw: string) => Promise<string | null>;
  exportText: () => string;
}

const TickerSegmentsContext = createContext<TickerSegmentsContextValue | null>(null);

export function TickerSegmentsProvider({ children }: { children: ReactNode }) {
  const [segments, setSegments] = useState<TickerSegmentsMap>({});
  const [hydrated, setHydrated] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api.preferences();
      setSegments((data.tickerSegments as TickerSegmentsMap) || {});
    } catch {
      /* offline — keep last */
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const persist = useCallback(async (patch: TickerSegmentsMap) => {
    const data = await api.updatePreferences({ tickerSegments: patch });
    setSegments((data.tickerSegments as TickerSegmentsMap) || {});
  }, []);

  const applyCommand = useCallback(
    async (raw: string): Promise<string | null> => {
      const cmd = parseSegmentCommand(raw);
      if (!cmd) return null;

      if (cmd.op === "delete") {
        const existing = segments[cmd.name];
        if (!existing) {
          Alert.alert("Segment", `@${cmd.name} is not saved.`);
          return "";
        }
        const confirmed = await new Promise<boolean>((resolve) => {
          Alert.alert("Delete segment", `Delete @${cmd.name}?`, [
            { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
            { text: "Delete", style: "destructive", onPress: () => resolve(true) },
          ]);
        });
        if (!confirmed) return raw;
        await persist({ [cmd.name]: "" });
        return "";
      }

      const prev = segments[cmd.name];
      if (prev != null && prev !== cmd.match) {
        const confirmed = await new Promise<boolean>((resolve) => {
          Alert.alert(
            "Overwrite segment",
            `@${cmd.name} already exists.\n\nCurrent: ${prev}\nNew: ${cmd.match || "(empty)"}\n\nOverwrite?`,
            [
              { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
              { text: "Overwrite", onPress: () => resolve(true) },
            ],
          );
        });
        if (!confirmed) return raw;
      }

      // Empty match deletes (same as @Name!).
      await persist({ [cmd.name]: cmd.match });
      return cmd.match ? `@${cmd.name}` : "";
    },
    [persist, segments],
  );

  const exportText = useCallback(() => exportSegmentsText(segments), [segments]);

  const value = useMemo(
    () => ({ segments, hydrated, refresh, applyCommand, exportText }),
    [segments, hydrated, refresh, applyCommand, exportText],
  );

  return (
    <TickerSegmentsContext.Provider value={value}>{children}</TickerSegmentsContext.Provider>
  );
}

export function useTickerSegments(): TickerSegmentsContextValue {
  const ctx = useContext(TickerSegmentsContext);
  if (!ctx) {
    throw new Error("useTickerSegments must be used within TickerSegmentsProvider");
  }
  return ctx;
}

export function segmentExists(segments: TickerSegmentsMap, name: string): boolean {
  const n = normalizeSegmentName(name);
  return Boolean(n && segments[n] != null);
}
