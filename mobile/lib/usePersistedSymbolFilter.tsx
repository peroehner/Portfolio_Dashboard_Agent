import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { loadLastSymbolFilter, saveLastSymbolFilter } from "@/lib/symbolFilterMemory";

interface SymbolFilterContextValue {
  filter: string;
  setFilter: (next: string) => void;
  lastFilter: string;
  applyLast: () => void;
  canRecall: boolean;
  hydrated: boolean;
}

const SymbolFilterContext = createContext<SymbolFilterContextValue | null>(null);

export function SymbolFilterProvider({ children }: { children: ReactNode }) {
  const [filter, setFilterState] = useState("");
  const [lastFilter, setLastFilter] = useState("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const saved = await loadLastSymbolFilter();
      if (cancelled) return;
      setLastFilter(saved);
      if (saved) setFilterState(saved);
      setHydrated(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setFilter = useCallback((next: string) => {
    setFilterState(next);
    const trimmed = next.trim();
    if (!trimmed) return;
    setLastFilter(trimmed);
    void saveLastSymbolFilter(trimmed);
  }, []);

  const applyLast = useCallback(() => {
    if (!lastFilter.trim()) return;
    setFilterState(lastFilter);
  }, [lastFilter]);

  const canRecall =
    Boolean(lastFilter.trim()) && filter.trim().toUpperCase() !== lastFilter.trim().toUpperCase();

  const value = useMemo(
    () => ({ filter, setFilter, lastFilter, applyLast, canRecall, hydrated }),
    [filter, setFilter, lastFilter, applyLast, canRecall, hydrated],
  );

  return (
    <SymbolFilterContext.Provider value={value}>{children}</SymbolFilterContext.Provider>
  );
}

export function usePersistedSymbolFilter(): SymbolFilterContextValue {
  const ctx = useContext(SymbolFilterContext);
  if (!ctx) {
    throw new Error("usePersistedSymbolFilter must be used within SymbolFilterProvider");
  }
  return ctx;
}
