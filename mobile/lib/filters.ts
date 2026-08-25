/** Named ticker segments + comma filter matching (parity with web / Python). */

export interface ParsedSymbolFilter {
  /** Substring OR include terms; "*" means starred. */
  orTerms: string[];
  /** Substring excludes (win over includes). */
  excludes: string[];
  /** When true, symbol must be starred (AND). */
  requireStarred: boolean;
}

export type TickerSegmentsMap = Record<string, string>;

const NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,31}$/;
const REF_RE = /^@([A-Za-z][A-Za-z0-9_]{0,31})$/;
const DEFINE_RE = /^@([A-Za-z][A-Za-z0-9_]{0,31})=(.*)$/s;
const DELETE_RE = /^@([A-Za-z][A-Za-z0-9_]{0,31})!$/;
const MAX_EXPAND_DEPTH = 4;

export function normalizeSegmentName(name: string): string | null {
  const text = String(name || "").trim();
  if (!text || !NAME_RE.test(text)) return null;
  return text.toUpperCase();
}

export function parseSegmentCommand(
  raw: string,
):
  | { op: "define"; name: string; match: string }
  | { op: "delete"; name: string }
  | null {
  const text = String(raw || "").trim();
  if (!text) return null;
  const deleted = text.match(DELETE_RE);
  if (deleted) {
    const name = normalizeSegmentName(deleted[1]);
    return name ? { op: "delete", name } : null;
  }
  const defined = text.match(DEFINE_RE);
  if (defined) {
    const name = normalizeSegmentName(defined[1]);
    if (!name) return null;
    return { op: "define", name, match: (defined[2] || "").trim() };
  }
  return null;
}

export function splitFilterTerms(filter: string): string[] {
  return String(filter || "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

export function expandFilter(filter: string, segments?: TickerSegmentsMap | null, depth = 0, stack: Set<string> = new Set()): string {
  const segs: TickerSegmentsMap = {};
  for (const [key, value] of Object.entries(segments || {})) {
    const name = normalizeSegmentName(key);
    if (name && value != null && String(value).trim()) segs[name] = String(value).trim();
  }
  const out: string[] = [];
  for (const term of splitFilterTerms(filter)) {
    // Bare ``@`` / in-progress ``@Ai`` — skip until a known segment resolves.
    if (term === "@" || /^@[A-Za-z0-9_]*$/.test(term)) {
      const ref = term.match(REF_RE);
      if (!ref) continue;
      const name = ref[1].toUpperCase();
      if (stack.has(name) || depth >= MAX_EXPAND_DEPTH) continue;
      const body = segs[name];
      if (!body) continue;
      const next = new Set(stack);
      next.add(name);
      out.push(...splitFilterTerms(expandFilter(body, segs, depth + 1, next)));
      continue;
    }
    out.push(term);
  }
  return out.join(", ");
}

export function parseSymbolFilter(
  filter: string,
  segments?: TickerSegmentsMap | null,
): ParsedSymbolFilter {
  const orTerms: string[] = [];
  const excludes: string[] = [];
  let requireStarred = false;

  for (const term of splitFilterTerms(expandFilter(filter, segments))) {
    if (term.startsWith("@")) continue;
    const lower = term.toLowerCase();
    if (lower === "+*" || lower === "+star") {
      requireStarred = true;
    } else if (lower === "*" || lower === "star" || lower === "⭐") {
      orTerms.push("*");
    } else if (term.startsWith("-") && term.length > 1) {
      excludes.push(term.slice(1).toLowerCase());
    } else {
      orTerms.push(lower);
    }
  }

  return { orTerms, excludes, requireStarred };
}

export function symbolMatchesFilter(
  symbol: string,
  filter: string,
  starred?: ReadonlySet<string>,
  segments?: TickerSegmentsMap | null,
): boolean {
  const { orTerms, excludes, requireStarred } = parseSymbolFilter(filter, segments);
  const sym = String(symbol || "").toUpperCase();
  const symLower = sym.toLowerCase();
  const starredSet = starred ?? new Set<string>();
  const isStarred = starredSet.has(sym);

  if (requireStarred && !isStarred) return false;
  for (const ex of excludes) {
    if (ex && symLower.includes(ex)) return false;
  }
  if (!orTerms.length) return true;

  return orTerms.some((term) => {
    if (term === "*") return isStarred;
    return symLower.includes(term);
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

export function listSegmentNames(segments?: TickerSegmentsMap | null): string[] {
  return Object.keys(segments || {})
    .map((k) => normalizeSegmentName(k))
    .filter((n): n is string => Boolean(n))
    .sort();
}

/** Names matching a typed ``@prefix`` (without @). */
export function matchingSegmentNames(
  prefix: string,
  segments?: TickerSegmentsMap | null,
): string[] {
  const needle = String(prefix || "").trim().toUpperCase();
  return listSegmentNames(segments).filter((name) => !needle || name.startsWith(needle));
}

/** Trailing ``@NAME`` fragment at end of input (for Tab autocomplete). */
export function trailingAtToken(value: string): { start: number; prefix: string } | null {
  const text = String(value || "");
  const match = text.match(/(?:^|,\s*)@([A-Za-z][A-Za-z0-9_]{0,31})?$/);
  if (!match) return null;
  const at = text.lastIndexOf("@");
  if (at < 0) return null;
  return { start: at, prefix: match[1] || "" };
}

export function exportSegmentsText(segments?: TickerSegmentsMap | null): string {
  const lines = listSegmentNames(segments).map((name) => `@${name}=${(segments || {})[name] || ""}`);
  return lines.length ? `${lines.join("\n")}\n` : "";
}

export const FILTER_PLACEHOLDER =
  "Filter… @AI · -intc · * starred · @AI=… save · @AI! delete";
