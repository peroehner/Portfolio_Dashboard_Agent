import { useStarredSymbols } from "@/lib/StarredSymbolsContext";
import { promptToggleStar } from "@/lib/symbolStarActions";

/** Long-press handler for a whole row/card tied to a symbol. */
export function useSymbolRowStar(symbol: string) {
  const { isStarred, toggleStar } = useStarredSymbols();
  const sym = String(symbol || "").trim().toUpperCase();

  return {
    onLongPress: () => {
      if (!sym) return;
      promptToggleStar(sym, isStarred(sym), () => toggleStar(sym));
    },
    delayLongPress: 400 as const,
  };
}
