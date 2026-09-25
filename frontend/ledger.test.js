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


section("Closing is shown as the subtraction it is");

/* The form asked for a number and printed a result, with the step
 * between them left to the reader. That step is not obvious for
 * anything SOLD: "what you paid to open" is stored as a negative, and
 * on screen both figures look like income, so 26 and 20 could
 * plausibly come to 46 as easily as to 6.
 *
 * WK is lifted from working.js rather than stubbed, so the rows here
 * are built by the same code that builds every other sum on the page.
 */
const { lift } = require("./lift.js");

// app.js reaches the sum-building helpers through window.QUIPU_WORKING,
// the same as it does in the browser. Wired up here with the real
// object out of working.js rather than a stub, so these rows are built
// by the code that builds every other sum on the page.
const { WK: realWK } = lift("working.js:WK");
global.window = { QUIPU_WORKING: { WK: realWK } };

const { closingWorking, round2 } = lift("WK", "round2", "closingWorking");

/** Follow the rows the way a reader would, and see where they land. */
function walk(w) {
  let total = null;
  for (const ln of w.lines) {
    const v = ln.gives !== null && ln.gives !== undefined
      ? ln.gives
      : ln.terms.reduce((a, t) => a * t.value, 1);
    if (total === null) total = ln.op === "-" ? -v : v;
    else if (ln.op === "+") total += v;
    else if (ln.op === "-") total -= v;
    else if (ln.op === "x") total *= v;
  }
  return total;
}

// Bought for 99, sold back for 250.
const closeDebit = closingWorking(250, 99, false);
near("a debit trade comes to the difference", closeDebit.result, 151);
near("and the rows say so too", walk(closeDebit), 151);
yes("the first row is what you get back",
    /get back/.test(closeDebit.lines[0].terms[0].label), closeDebit.lines[0].terms[0].label);
yes("the second is subtracted",
    closeDebit.lines[1].op === "-", `op "${closeDebit.lines[1].op}"`);

// Paid 26 to open, cost 20 to buy back. Both look like income on
// screen; only one of them is.
const closeCredit = closingWorking(-20, -26, true);
near("a credit trade keeps the difference", closeCredit.result, 6);
near("and its rows say so too", walk(closeCredit), 6);
yes("it leads with what you were paid",
    /were paid to open/.test(closeCredit.lines[0].terms[0].label),
    closeCredit.lines[0].terms[0].label);
yes("and subtracts the cost of buying it back",
    closeCredit.lines[1].op === "-" && /costs you to close/.test(closeCredit.lines[1].terms[0].label),
    closeCredit.lines[1].terms[0].label);
yes("every printed value is a magnitude, never a bare negative",
    closeCredit.lines.every((l) => l.gives >= 0),
    closeCredit.lines.map((l) => l.gives).join(", "));

// The same credit trade going wrong: bought back for more than it paid.
const blown = closingWorking(-199, -26, true);
near("a credit closed for more than it paid is a loss", blown.result, -173);
near("and the rows land there", walk(blown), -173);

// Selling a long position for nothing is still a real answer.
const worthless = closingWorking(0, 99, false);
near("expiring worthless loses the whole debit", worthless.result, -99);
near("and the rows agree", walk(worthless), -99);

// It agrees with the number the log actually stores.
for (const [recv, cost] of [[250, 99], [-20, -26], [-199, -26], [0, 99], [45, -51]]) {
  const w = closingWorking(recv, cost, cost < 0);
  near(`working matches realised() for ${recv} against ${cost}`,
       w.result, realised(recv, cost, null).pl);
}

yes("it declines to invent a sum with nothing to work from",
    closingWorking(null, 99, false) === null
    && closingWorking(250, null, false) === null);


section("What it costs to place is counted, not just disclaimed");

/* "Commissions are not included" is true and useless: on a four-leg
 * condor taking in $51 a round turn is $5.20 -- ten percent of the
 * maximum profit, on the structure the app most often surfaces for
 * its odds. A disclaimer with no number cannot be weighed. */
const { commissionOf, FEE_PER_CONTRACT } = lift("FEE_PER_CONTRACT", "commissionOf");

const four = [
  { kind: "put",  side: "long",  qty: 1 }, { kind: "put",  side: "short", qty: 1 },
  { kind: "call", side: "short", qty: 1 }, { kind: "call", side: "long",  qty: 1 },
];
near("a four-leg condor is four contracts", commissionOf(four).contracts, 4, 1e-9);
near("opening it costs four times the rate",
     commissionOf(four).open, 4 * FEE_PER_CONTRACT, 1e-9);
near("and the round turn is twice that",
     commissionOf(four).round, 8 * FEE_PER_CONTRACT, 1e-9);

const ten = four.map((l) => ({ ...l, qty: 10 }));
near("ten lots cost ten times as much",
     commissionOf(ten).round, commissionOf(four).round * 10, 1e-9);

yes("a stock-only position is charged nothing",
    commissionOf([{ kind: "stock", side: "long", qty: 100 }]) === null);
yes("and an empty position too", commissionOf([]) === null);

near("shares alongside options are not counted",
     commissionOf([{ kind: "stock", side: "long", qty: 100 },
                   { kind: "call", side: "short", qty: 1 }]).contracts, 1, 1e-9);


section("Resetting the banked total draws a line, it does not delete");

/* A trade log whose history can be wiped by a button next to a total
 * is not a log. The marks come back from the market every time; the
 * record of what you actually did does not. So reset moves a line and
 * the closed trades stay listed, uncounted. */
const { countsAsBanked } = lift("countsAsBanked");

const LINE = "2026-09-25T16:00:00.000Z";
const before = { closed_at: "2026-09-24T18:00:00.000Z", closed: "2026-09-24" };
const after  = { closed_at: "2026-09-25T19:00:00.000Z", closed: "2026-09-25" };

yes("with no line everything counts", countsAsBanked(before, null));
yes("before the line it does not", !countsAsBanked(before, LINE));
yes("after the line it does", countsAsBanked(after, LINE));

// Trades logged before timestamps existed carry only a date. They
// must still fall on a defensible side rather than throwing.
yes("a date-only trade from before still falls before",
    !countsAsBanked({ closed: "2026-09-01" }, LINE));
yes("and one from after falls after",
    countsAsBanked({ closed: "2026-09-26" }, LINE));
yes("one with no closing record at all is not counted",
    !countsAsBanked({}, LINE));

// The exact moment of the line counts as on or after it, so a trade
// closed in the same second as a reset is not silently lost.
yes("closing on the line itself counts",
    countsAsBanked({ closed_at: LINE }, LINE));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
