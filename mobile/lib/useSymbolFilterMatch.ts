import { useCallback } from "react";

import { symbolMatchesFilter } from "@/lib/filters";
import { useStarredSymbols } from "@/lib/StarredSymbolsContext";
import { useTickerSegments } from "@/lib/TickerSegmentsContext";

export function useSymbolFilterMatch(filter: string) {
  const { starred } = useStarredSymbols();
  const { segments } = useTickerSegments();
  return useCallback(
    (symbol: string) => symbolMatchesFilter(symbol, filter, starred, segments),
    [filter, starred, segments],
  );
}
