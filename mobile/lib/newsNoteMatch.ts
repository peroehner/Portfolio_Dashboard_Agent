import type { NewsItem, Note, PortfolioSymbol } from "./types";

function normalizeNewsUrl(url: string): string {
  return String(url || "")
    .trim()
    .toLowerCase()
    .replace(/\/+$/, "");
}

function stripNoteDatePrefix(line: string): string {
  return String(line || "")
    .replace(/^\[\d{4}-\d{2}-\d{2}\]\s*/, "")
    .trim()
    .toLowerCase();
}

/** Stable key for a news article — prefer URL, fall back to symbol+title. */
export function newsArticleKey(item: Pick<NewsItem, "symbol" | "title" | "link">): string {
  const url = normalizeNewsUrl(item.link || "");
  if (url) return `u:${url}`;
  const sym = String(item.symbol || "").toUpperCase();
  const title = stripNoteDatePrefix(item.title || "");
  return title ? `t:${sym}:${title}` : "";
}

const NOTE_URL_RE = /https?:\/\/[^\s<>"')]+/gi;

function keysFromNoteText(text: string, symbol?: string, source?: string): string[] {
  const keys: string[] = [];
  const raw = String(text || "");
  NOTE_URL_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = NOTE_URL_RE.exec(raw)) !== null) {
    const cleaned = normalizeNewsUrl(match[0].replace(/[.,;:!?)]+$/, ""));
    if (cleaned) keys.push(`u:${cleaned}`);
  }
  const firstLine = stripNoteDatePrefix(raw.split(/\r?\n/)[0] || "");
  const sym = String(symbol || "").toUpperCase();
  if (firstLine && sym) keys.push(`t:${sym}:${firstLine}`);
  const src = stripNoteDatePrefix(source || "");
  if (src && sym) keys.push(`t:${sym}:${src}`);
  return keys;
}

export function buildNotedNewsKeySet(
  symbols: Array<Pick<PortfolioSymbol, "symbol" | "notes">> | null | undefined,
): Set<string> {
  const keys = new Set<string>();
  for (const s of symbols || []) {
    for (const note of s.notes || []) {
      for (const k of keysFromNoteText(note.text || "", s.symbol, note.source)) {
        keys.add(k);
      }
    }
  }
  return keys;
}

export function newsArticleIsNoted(
  item: Pick<NewsItem, "symbol" | "title" | "link">,
  notedKeys: Set<string>,
): boolean {
  const key = newsArticleKey(item);
  return Boolean(key && notedKeys.has(key));
}

/** Merge keys from a just-saved note into an existing set (immutable). */
export function notedKeysAfterSave(
  notedKeys: Set<string>,
  note: Pick<Note, "text" | "source">,
  symbol: string,
): Set<string> {
  const next = new Set(notedKeys);
  for (const k of keysFromNoteText(note.text || "", symbol, note.source)) {
    next.add(k);
  }
  return next;
}
