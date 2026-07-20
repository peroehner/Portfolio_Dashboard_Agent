import { useCallback } from "react";

import { symbolMatchesFilter } from "@/lib/filters";
import { useStarredSymbols } from "@/lib/StarredSymbolsContext";

export function useSymbolFilterMatch(filter: string) {
  const { starred } = useStarredSymbols();
  return useCallback(
    (symbol: string) => symbolMatchesFilter(symbol, filter, starred),
    [filter, starred],
  );
}
