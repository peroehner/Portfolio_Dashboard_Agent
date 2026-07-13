export function symbolMatchesFilter(symbol: string, filter: string): boolean {
  const terms = filter
    .split(",")
    .map((term) => term.trim().toLowerCase())
    .filter(Boolean);
  if (!terms.length) return true;
  const sym = String(symbol || "").toLowerCase();
  return terms.some((term) => sym.includes(term));
}
