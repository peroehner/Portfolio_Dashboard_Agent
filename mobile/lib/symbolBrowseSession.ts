import { router } from "expo-router";

export type SymbolBrowseSession = {
  symbols: string[];
  source?: string;
};

let session: SymbolBrowseSession | null = null;

function normalizeList(symbols: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of symbols) {
    const sym = String(raw || "").trim().toUpperCase();
    if (!sym || seen.has(sym)) continue;
    seen.add(sym);
    out.push(sym);
  }
  return out;
}

/** Remember the ordered list the user opened a symbol from (Portfolio, Alerts, …). */
export function setSymbolBrowseSession(symbols: string[], source?: string) {
  const list = normalizeList(symbols);
  session = list.length ? { symbols: list, source } : null;
}

export function getSymbolBrowseSession(): SymbolBrowseSession | null {
  return session;
}

export function getSymbolBrowseNeighbors(current: string): {
  prev: string | null;
  next: string | null;
  index: number;
  total: number;
  source?: string;
} {
  const sym = String(current || "").toUpperCase();
  if (!session?.symbols.length) {
    return { prev: null, next: null, index: -1, total: 0 };
  }
  const index = session.symbols.indexOf(sym);
  if (index < 0) {
    return { prev: null, next: null, index: -1, total: session.symbols.length, source: session.source };
  }
  return {
    prev: index > 0 ? session.symbols[index - 1] : null,
    next: index < session.symbols.length - 1 ? session.symbols[index + 1] : null,
    index,
    total: session.symbols.length,
    source: session.source,
  };
}

/** Open symbol detail; optionally set browse order for swipe prev/next. */
export function openSymbol(symbol: string, list?: string[], source?: string) {
  if (list?.length) setSymbolBrowseSession(list, source);
  router.push(`/symbol/${String(symbol).toUpperCase()}`);
}

/** Switch symbol in-place so Back still returns to the originating list. */
export function replaceBrowseSymbol(symbol: string) {
  router.replace(`/symbol/${String(symbol).toUpperCase()}`);
}
