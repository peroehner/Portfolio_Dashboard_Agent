import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { loadStarredSymbols, saveStarredSymbols } from "@/lib/starredSymbols";

interface StarredSymbolsContextValue {
  ready: boolean;
  starred: ReadonlySet<string>;
  isStarred: (symbol: string) => boolean;
  toggleStar: (symbol: string) => void;
  setStarred: (symbol: string, starred: boolean) => void;
}

const StarredSymbolsContext = createContext<StarredSymbolsContextValue | null>(null);

export function StarredSymbolsProvider({ children }: { children: ReactNode }) {
  const [starred, setStarredState] = useState<Set<string>>(() => new Set());
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void loadStarredSymbols().then((loaded) => {
      setStarredState(loaded);
      setReady(true);
    });
  }, []);

  const commit = useCallback((next: Set<string>) => {
    setStarredState(next);
    void saveStarredSymbols(next);
  }, []);

  const isStarred = useCallback((symbol: string) => starred.has(String(symbol || "").toUpperCase()), [starred]);

  const toggleStar = useCallback(
    (symbol: string) => {
      const sym = String(symbol || "").trim().toUpperCase();
      if (!sym) return;
      const next = new Set(starred);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      commit(next);
    },
    [starred, commit],
  );

  const setStarred = useCallback(
    (symbol: string, value: boolean) => {
      const sym = String(symbol || "").trim().toUpperCase();
      if (!sym) return;
      const next = new Set(starred);
      if (value) next.add(sym);
      else next.delete(sym);
      if (next.size === starred.size && [...next].every((s) => starred.has(s))) return;
      commit(next);
    },
    [starred, commit],
  );

  const value = useMemo(
    () => ({ ready, starred, isStarred, toggleStar, setStarred }),
    [ready, starred, isStarred, toggleStar, setStarred],
  );

  return <StarredSymbolsContext.Provider value={value}>{children}</StarredSymbolsContext.Provider>;
}

export function useStarredSymbols(): StarredSymbolsContextValue {
  const ctx = useContext(StarredSymbolsContext);
  if (!ctx) throw new Error("useStarredSymbols must be used within StarredSymbolsProvider");
  return ctx;
}
