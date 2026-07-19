/** Proportionally widen fixed-width columns so tables use leftover viewport space. */
export function scaleColumnsToFillWidth<T extends { width: number }>(
  columns: T[],
  availableWidth: number,
): T[] {
  if (availableWidth <= 0 || columns.length === 0) return columns;
  const total = columns.reduce((sum, col) => sum + col.width, 0);
  if (total <= 0 || availableWidth <= total) return columns;

  const scaled = columns.map((col) => ({
    ...col,
    width: Math.floor((col.width / total) * availableWidth),
  }));
  const used = scaled.reduce((sum, col) => sum + col.width, 0);
  const remainder = availableWidth - used;
  if (remainder !== 0 && scaled.length) {
    const last = scaled[scaled.length - 1];
    scaled[scaled.length - 1] = { ...last, width: last.width + remainder };
  }
  return scaled;
}

export function fitStickyScrollColumns<T extends { width: number }>(
  sticky: T[],
  scroll: T[],
  availableWidth: number,
): { sticky: T[]; scroll: T[] } {
  const fitted = scaleColumnsToFillWidth([...sticky, ...scroll], availableWidth);
  return {
    sticky: fitted.slice(0, sticky.length),
    scroll: fitted.slice(sticky.length),
  };
}
