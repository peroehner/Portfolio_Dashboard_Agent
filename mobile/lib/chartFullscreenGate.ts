/** Gate so symbol-browse swipes don't steal fullscreen chart H-scroll. */
let chartFullscreenActive = false;

export function setChartFullscreenActive(active: boolean) {
  chartFullscreenActive = Boolean(active);
}

export function isChartFullscreenActive(): boolean {
  return chartFullscreenActive;
}
