/**
 * Wrap each figure WITH the nearby words that state its meaning (label or unit)
 * so AlertMessageText can bold ``**unrealized gain of 460%**``,
 * ``**180x forward P/E**``, ``**1.1% of portfolio**``.
 *
 * Existing ``**…**`` spans are kept; if the model only bolded the number,
 * neighboring label/unit words are pulled in.
 */

const NUMBER_RE =
  /\$[\d,]+(?:\.\d+)?(?:\s*[KMBkmb])?|[+\-]?\d+(?:\.\d+)?%|\d+(?:\.\d+)?x\b|\b\d+(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b/g;

const WORD_RE = /^(?:P\/E|1YT|[A-Za-z][A-Za-z0-9/.-]*)/;

const STOP_LEFT = new Set([
  "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
  "and", "but", "or", "nor", "with", "from", "by", "as", "if", "than", "then",
  "that", "this", "these", "those", "it", "its", "their", "his", "her",
  "very", "extremely", "currently", "still", "also", "only", "just",
  "about", "nearly", "almost", "now", "already", "has", "have", "had",
  "holding", "approaching", "positioned", "trading", "sitting",
  "remains", "remaining", "stretched", "expensive", "cheap",
  "significant", "significantly", "while", "when", "where", "which",
  "who", "whose", "into", "onto", "for", "on", "in", "at", "so", "yet", "not",
  "valuation", "monitor", "consider", "maintain", "review",
]);

const LEFT_CONNECTOR = new Set([
  "of", "vs", "versus", "exceeding", "above", "below", "around", "to",
]);

const STOP_RIGHT = new Set([
  "and", "but", "or", "nor", "while", "which", "that", "with", "because",
  "although", "however", "when", "where", "if", "so", "yet", "as",
  "is", "are", "was", "were", "has", "have", "had", "not", "than", "then",
  "who", "whose", "whom", "also", "still", "already", "now",
  "consider", "maintain", "monitor", "in", "for", "on", "at",
]);

const RIGHT_CONNECTOR = new Set(["of", "to", "vs", "versus", "per", "above", "below", "around"]);
const RIGHT_ARTICLE = new Set(["the", "a", "an"]);

function isYearToken(token: string): boolean {
  return /^(?:19|20)\d{2}$/.test(token);
}

function isPureNumberToken(token: string): boolean {
  const t = String(token || "").trim();
  return (
    /^\$[\d,]+(?:\.\d+)?(?:\s*[KMBkmb])?$/i.test(t) ||
    /^[+\-]?\d+(?:\.\d+)?%$/.test(t) ||
    /^\d+(?:\.\d+)?x$/i.test(t) ||
    /^\d+(?:,\d{3})+(?:\.\d+)?$/.test(t) ||
    /^\d+(?:\.\d+)?$/.test(t)
  );
}

function hasUnitSuffix(token: string): boolean {
  const t = String(token || "").trim();
  return /^\$/.test(t) || /%$/.test(t) || /x$/i.test(t);
}

function lastWord(text: string, end: number): { word: string; start: number } | null {
  let i = end;
  while (i > 0 && /[ \t]/.test(text[i - 1])) i -= 1;
  if (i <= 0) return null;
  const slice = text.slice(0, i);
  const match = slice.match(/(P\/E|1YT|[A-Za-z][A-Za-z0-9/.-]*)$/);
  if (!match) return null;
  return { word: match[1], start: i - match[1].length };
}

function expandLeft(text: string, start: number): number {
  let pos = start;
  let content = 0;
  let lastGood = start;
  while (content < 4) {
    const word = lastWord(text, pos);
    if (!word) break;
    if (!/^[\s]*$/.test(text.slice(word.start + word.word.length, pos))) break;
    const key = word.word.toLowerCase();
    if (LEFT_CONNECTOR.has(key)) {
      pos = word.start;
      lastGood = pos;
      continue;
    }
    if (STOP_LEFT.has(key)) break;
    pos = word.start;
    lastGood = pos;
    content += 1;
  }
  return lastGood;
}

function expandRight(text: string, end: number): number {
  let i = end;
  let content = 0;
  let lastGood = end;
  let lastWasConnector = false;
  while (content < 5) {
    let j = i;
    while (j < text.length && /[ \t]/.test(text[j])) j += 1;
    if (j >= text.length) break;
    if (text[j] === "(") {
      const close = text.indexOf(")", j + 1);
      if (close > j && close - j <= 28) {
        i = close + 1;
        lastGood = i;
        lastWasConnector = false;
        content += 1;
        continue;
      }
      break;
    }
    if (/[.,;:!?—–]/.test(text[j])) break;
    const match = text.slice(j).match(WORD_RE);
    if (!match) break;
    const key = match[0].toLowerCase();
    if (STOP_RIGHT.has(key)) break;
    if (RIGHT_ARTICLE.has(key) && !lastWasConnector) break;
    i = j + match[0].length;
    if (RIGHT_CONNECTOR.has(key) || RIGHT_ARTICLE.has(key)) {
      lastWasConnector = true;
      continue;
    }
    lastWasConnector = false;
    lastGood = i;
    content += 1;
  }
  return lastGood;
}

function wrapMetricPhrases(segment: string): string {
  const spans: { start: number; end: number }[] = [];
  const re = new RegExp(NUMBER_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(segment)) !== null) {
    const token = match[0];
    if (isYearToken(token)) continue;
    const numStart = match.index;
    const numEnd = numStart + token.length;
    const start = expandLeft(segment, numStart);
    const end = expandRight(segment, numEnd);
    if (!hasUnitSuffix(token) && start === numStart && end === numEnd) continue;
    spans.push({ start, end });
  }
  if (!spans.length) return segment;

  spans.sort((a, b) => a.start - b.start);
  const merged: { start: number; end: number }[] = [];
  for (const span of spans) {
    const prev = merged[merged.length - 1];
    if (prev && span.start <= prev.end) {
      prev.end = Math.max(prev.end, span.end);
    } else {
      merged.push({ ...span });
    }
  }

  let out = segment;
  for (let i = merged.length - 1; i >= 0; i -= 1) {
    const { start, end } = merged[i];
    const slice = out.slice(start, end).trimEnd();
    if (!slice || slice.includes("**")) continue;
    out = `${out.slice(0, start)}**${slice}**${out.slice(start + slice.length)}`;
  }
  return out;
}

function pullContextIntoBold(text: string): string {
  const parts = text.split(/(\*\*[^*]+\*\*)/);
  const out: string[] = [];
  for (let i = 0; i < parts.length; i += 1) {
    const part = parts[i];
    const bold = /^\*\*([^*]+)\*\*$/.exec(part);
    if (!bold) {
      out.push(part);
      continue;
    }
    let inner = bold[1];
    if (!isPureNumberToken(inner)) {
      out.push(part);
      continue;
    }
    const prev = out.length ? out[out.length - 1] : "";
    let next = parts[i + 1] || "";
    if (next.startsWith("**")) next = "";
    const fake = `${prev}${inner}${next}`;
    const numStart = prev.length;
    const numEnd = numStart + inner.length;
    const left = expandLeft(fake, numStart);
    const right = expandRight(fake, numEnd);
    if (out.length) out[out.length - 1] = prev.slice(0, left);
    if (parts[i + 1] != null && !String(parts[i + 1]).startsWith("**")) {
      parts[i + 1] = next.slice(right - numEnd);
    }
    inner = fake.slice(left, right);
    out.push(`**${inner}**`);
  }
  return out.join("");
}

export function emphasizeDriverText(text: string): string {
  const raw = String(text || "").trim();
  if (!raw) return raw;
  const wrapped = raw
    .split(/(\*\*[^*]+\*\*)/)
    .map((part) => (/^\*\*[^*]+\*\*$/.test(part) ? part : wrapMetricPhrases(part)))
    .join("");
  return pullContextIntoBold(wrapped);
}
