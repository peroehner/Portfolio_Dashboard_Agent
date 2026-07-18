import { router } from "expo-router";

export type SymbolBrowseTab = "summary" | "technical";

export type SymbolBrowseSession = {
  symbols: string[];
  source?: string;
};

type BrowseUi = {
  tab: SymbolBrowseTab;
  scrollY: Record<SymbolBrowseTab, number>;
};

let session: SymbolBrowseSession | null = null;
let browseUi: BrowseUi = {
  tab: "summary",
  scrollY: { summary: 0, technical: 0 },
};

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

function resetBrowseUi() {
  browseUi = {
    tab: "summary",
    scrollY: { summary: 0, technical: 0 },
  };
}

/** Remember the ordered list the user opened a symbol from (Portfolio, Alerts, …). */
export function setSymbolBrowseSession(symbols: string[], source?: string) {
  const list = normalizeList(symbols);
  session = list.length ? { symbols: list, source } : null;
  // Fresh entry from a list starts at Summary / top.
  resetBrowseUi();
}

export function getSymbolBrowseSession(): SymbolBrowseSession | null {
  return session;
}

export function getBrowseUi(): BrowseUi {
  return browseUi;
}

export function setBrowseTab(tab: SymbolBrowseTab) {
  browseUi.tab = tab;
}

export function setBrowseScrollY(tab: SymbolBrowseTab, y: number) {
  browseUi.scrollY[tab] = Math.max(0, y);
}

export function getBrowseScrollY(tab: SymbolBrowseTab): number {
  return browseUi.scrollY[tab] ?? 0;
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
