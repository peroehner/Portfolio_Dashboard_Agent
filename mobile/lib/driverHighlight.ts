/**
 * Wrap driver highlights in ``**…**`` so AlertMessageText can bold them
 * (prices, percents, multiples). Leaves existing markup alone.
 */
export function emphasizeDriverText(text: string): string {
  const raw = String(text || "").trim();
  if (!raw) return raw;
  if (/\*\*[^*]+\*\*/.test(raw)) return raw;

  return raw
    .replace(/(\$[\d,]+(?:\.\d+)?(?:\s*[MBmbKk])?)/g, "**$1**")
    .replace(/(\d+(?:\.\d+)?%)/g, "**$1**")
    .replace(/(\d+(?:\.\d+)?x)\b/gi, "**$1**");
}
