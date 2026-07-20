export interface ParsedSymbolFilter {
  /** Substring OR terms; "*" means starred. */
  orTerms: string[];
  /** When true, symbol must be starred (AND). */
  requireStarred: boolean;
}

export function parseSymbolFilter(filter: string): ParsedSymbolFilter {
  const orTerms: string[] = [];
  let requireStarred = false;

  for (const raw of filter.split(",")) {
    const term = raw.trim();
    if (!term) continue;
    const lower = term.toLowerCase();
    if (lower === "+*" || lower === "+star") {
      requireStarred = true;
    } else if (lower === "*" || lower === "star" || lower === "⭐") {
      orTerms.push("*");
    } else {
      orTerms.push(lower);
    }
  }

  return { orTerms, requireStarred };
}

export function symbolMatchesFilter(
  symbol: string,
  filter: string,
  starred?: ReadonlySet<string>,
): boolean {
  const { orTerms, requireStarred } = parseSymbolFilter(filter);
  const sym = String(symbol || "").toUpperCase();
  const starredSet = starred ?? new Set<string>();
  const isStarred = starredSet.has(sym);

  if (requireStarred && !isStarred) return false;
  if (!orTerms.length) return true;

  return orTerms.some((term) => {
    if (term === "*") return isStarred;
    return sym.toLowerCase().includes(term);
  });
}

/** Append `*` (OR) or `+*` (AND) to a filter string. */
export function appendStarFilterToken(filter: string, andMode: boolean): string {
  const token = andMode ? "+*" : "*";
  const trimmed = filter.trim();
  if (!trimmed) return token;
  if (trimmed.endsWith(",")) return `${trimmed}${token}`;
  return `${trimmed},${token}`;
}

export const FILTER_PLACEHOLDER = "Filter… * starred, +* AND star";
