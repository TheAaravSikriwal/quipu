/* The trade log's arithmetic, checked against the definitions rather
 * than against itself.
 *
 * Run:  node frontend/ledger.test.js
 */

const { realised, bookTotals } = require("./ledger.js");

let pass = 0, fail = 0;

function near(name, got, want, tol = 1e-9) {
  const ok = got != null && Math.abs(got - want) <= tol;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name.padEnd(54)} got ${
    got == null ? "null" : got}  want ${want}`);
  ok ? pass++ : fail++;
}
function yes(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name.padEnd(54)} ${detail}`);
  cond ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

section("A closed trade's result is what came back less what went out");

// The live case, checked against the figures on screen: a bull call
// spread that cost $99 and was closed for $250.
near("paid 99, closed at 250", realised(250, 99, 99).pl, 151);
near("and that is 153% of the 99 at risk", realised(250, 99, 99).pct, (151 / 99) * 100, 1e-9);

// Losing the lot.
near("paid 99, expired worthless", realised(0, 99, 99).pl, -99);
near("which is minus everything at risk", realised(0, 99, 99).pct, -100);

/* A CREDIT trade. netCost is negative -- you were paid to open it --
 * and closing it for nothing means keeping the whole credit. This is
 * the case a naive "profit = received - cost" gets right and a naive
 * "percent = profit / cost" gets backwards, because the cost is
 * negative and dividing by it flips the sign. */
section("A credit trade keeps the credit, and its percentage is not inverted");
const credit = realised(0, -57, 193);
near("paid 57 to open, closed for nothing", credit.pl, 57);
yes("and the percentage is positive", credit.pct > 0, `${credit.pct.toFixed(1)}%`);
near("measured against what was at risk", credit.pct, (57 / 193) * 100);

/* Buying a credit trade back costs money, so the value received is
 * NEGATIVE. Took in 57, paid 150 to get out: down 93. The close form
 * asks for that as a positive cost and negates it, precisely so the
 * user never has to reason about this. */
const badCredit = realised(-150, -57, 193);
near("took in 57, bought back for 150", badCredit.pl, -93);
yes("and that shows as a loss", badCredit.pl < 0, String(badCredit.pl));
yes("as does its percentage", badCredit.pct < 0, badCredit.pct.toFixed(1) + "%");

// Nothing to work from is not a result of zero.
yes("no exit figure gives no result", realised(null, 99, 99).pl === null, "null");
yes("no cost figure gives no result", realised(250, null, 99).pl === null, "null");

section("Totals add up on screen");

/* Rounded before summing, not after. This is the exact case that was
 * wrong: -6.50 and +151.00 printed as -7 and +151 above a total of
 * +145, three numbers that did not add up. */
const t = bookTotals([-6.5], [151]);
near("the open figure rounds to -6", t.open, -6);
near("the banked figure is 151", t.banked, 151);
near("and the total is exactly their sum", t.all, t.open + t.banked);
near("which is 145", t.all, 145);

const many = bookTotals([10.4, -3.6, null, 8.5], [20.5, -4.4, 0]);
near("open sums the rounded parts", many.open, 10 + -4 + 9);
near("banked sums the rounded parts", many.banked, 21 + -4 + 0);
near("all is the two together", many.all, many.open + many.banked);
yes("unpriced trades are counted out", many.priced === 3, `${many.priced} of 4 priced`);
yes("closed count is the closed ones", many.closed === 3, String(many.closed));
yes("wins counts only the profitable", many.wins === 1, `${many.wins} of 3`);

const empty = bookTotals([], []);
yes("an empty log totals zero, not NaN",
    empty.all === 0 && empty.priced === 0, JSON.stringify(empty));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
