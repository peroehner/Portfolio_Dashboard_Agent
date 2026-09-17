/**
 * Unit checks for dividendRetentionBonus / underIncomeTarget (yield %-based).
 * Run: node --experimental-strip-types tests/test_div_retention_bonus.mjs
 */
import assert from "node:assert/strict";
import {
  dividendRetentionBonus,
  underIncomeTarget,
  DIV_RETENTION_MAX_UNDER,
  DIV_RETENTION_MAX_AT_TARGET,
} from "../mobile/lib/signalScores.ts";

assert.equal(dividendRetentionBonus({ dividendYieldPct: null }), 0);
assert.equal(dividendRetentionBonus({ dividendYieldPct: 0.1 }), 0);
assert.equal(
  dividendRetentionBonus({ dividendYieldPct: 3, underIncomeTarget: true }),
  DIV_RETENTION_MAX_UNDER,
);
assert.equal(
  dividendRetentionBonus({ dividendYieldPct: 3, underIncomeTarget: false }),
  DIV_RETENTION_MAX_AT_TARGET,
);
assert.equal(
  dividendRetentionBonus({ dividendYieldPct: 1.5, underIncomeTarget: true }),
  Math.round(DIV_RETENTION_MAX_UNDER * 0.5),
);
// NET / GH style zero yield
assert.equal(dividendRetentionBonus({ dividendYieldPct: 0, underIncomeTarget: true }), 0);
// GILD-like ~3% under target → full keep pressure
assert.equal(
  dividendRetentionBonus({ dividendYieldPct: 2.9, underIncomeTarget: true }),
  Math.round(DIV_RETENTION_MAX_UNDER * Math.min(1, 2.9 / 3)),
);

assert.equal(underIncomeTarget({ targetAnnualDividend: null, portfolioAnnualDividend: 1000 }), false);
assert.equal(underIncomeTarget({ targetAnnualDividend: 5000, portfolioAnnualDividend: 4000 }), true);
assert.equal(underIncomeTarget({ targetAnnualDividend: 5000, portfolioAnnualDividend: 5000 }), false);
assert.equal(underIncomeTarget({ targetAnnualDividend: 5000, portfolioAnnualDividend: null }), true);

console.log("test_div_retention_bonus: ok");
