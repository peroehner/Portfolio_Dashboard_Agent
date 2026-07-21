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

function isOrStarToken(term: string): boolean {
  const lower = term.toLowerCase();
  return lower === "*" || lower === "star" || lower === "⭐";
}

function isAndStarToken(term: string): boolean {
  const lower = term.toLowerCase();
  return lower === "+*" || lower === "+star";
}

/** Toggle `*` (OR) or `+*` (AND) in a filter string. */
export function toggleStarFilterToken(filter: string, andMode: boolean): string {
  const token = andMode ? "+*" : "*";
  const matcher = andMode ? isAndStarToken : isOrStarToken;
  const parts = filter
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

  if (parts.some(matcher)) {
    return parts.filter((part) => !matcher(part)).join(",");
  }

  const trimmed = filter.trim();
  if (!trimmed) return token;
  if (trimmed.endsWith(",")) return `${trimmed}${token}`;
  return `${trimmed},${token}`;
}

export const FILTER_PLACEHOLDER = "Filter… * starred, +* AND star";
