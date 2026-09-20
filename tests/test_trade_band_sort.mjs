/**
 * Smoke tests for Trade band signed distances / OOR labels (mirrors mobile/lib/tradeBand.ts).
 */
function signedBelow(price, below) {
  return ((price - below) / price) * 100;
}
function signedAbove(price, above) {
  return ((price - above) / price) * 100;
}
function label(side, signed) {
  const r = Math.round(Math.abs(signed));
  if (side === "below" && signed < 0) return `−${r}%`;
  if (side === "above" && signed > 0) return `+${r}%`;
  return `${r}%`;
}
function compareL(a, b) {
  return a - b;
}
function compareR(a, b) {
  return b - a;
}

const assert = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

// GH-like: price above below → positive signed from below
assert(Math.abs(signedBelow(179, 99.5) - 44.4) < 0.2, "below dist ~44%");
assert(label("below", signedBelow(179, 99.5)) === "44%", "in-range below unsigned");

// OOR left of below
assert(signedBelow(90, 100) < 0, "oor below negative");
assert(label("below", signedBelow(90, 100)) === "−11%", "oor below signed");

// OOR right of above
assert(signedAbove(120, 100) > 0, "oor above positive");
assert(label("above", signedAbove(120, 100)).startsWith("+"), "oor above signed");
assert(Math.round(Math.abs(signedAbove(120, 100))) === 17, "oor above ~17% of price");

// Sort L: −7, 3, 4, 12
const L = [-7, 12, 3, 4].sort(compareL);
assert(L.join(",") === "-7,3,4,12", `L sort got ${L}`);

// Sort R: +7, +5, −1, −3, −6, −11
const R = [-11, 5, -1, 7, -3, -6].sort(compareR);
assert(R.join(",") === "7,5,-1,-3,-6,-11", `R sort got ${R}`);

console.log("trade band smoke OK");
