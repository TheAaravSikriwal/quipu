/* The two-setup comparison, checked for the things it must never say.
 *
 * Run:  node frontend/versus.test.js
 *
 * This panel exists to answer "is this one cheaper, and what do I give
 * up for it". Every row is a claim about two real structures, so the
 * ways it can be wrong are specific: calling an uncapped loss a good
 * one, printing a very small ratio as zero, declaring a winner on a
 * row where one side has no number, or -- worst -- naming the wrong
 * setup as the one that wins.
 */

const { lift } = require("./lift.js");

const { VS_ROWS, nf, money } = lift("nf", "money", "VS_ROWS");

let pass = 0, fail = 0;

function is(name, got, want) {
  const ok = got === want;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name.padEnd(52)} got ${got}  want ${want}`);
  ok ? pass++ : fail++;
}
function yes(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name.padEnd(52)} ${detail}`);
  cond ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

const row = (k) => VS_ROWS.find((r) => r.key === k);

/* Two real structures off an AAPL board, spot ~335. */
const spread = {
  name: "Bull call spread", net_cost: 176, chance: 39,
  max_profit: 324, max_loss: -176,
  max_profit_unbounded: false, max_loss_unbounded: false,
  breakevens: [336.78], spot_used: 335.08,
};
const csp = {
  name: "Cash-secured put", net_cost: -119, chance: 75,
  max_profit: 119, max_loss: -33131,
  max_profit_unbounded: false, max_loss_unbounded: false,
  breakevens: [331.12], spot_used: 335.08,
};
const longCall = {
  name: "Buy a call", net_cost: 200, chance: 27,
  max_profit: null, max_loss: -200,
  max_profit_unbounded: true, max_loss_unbounded: false,
  breakevens: [338.9], spot_used: 335.08,
};
const naked = {
  name: "Short strangle", net_cost: -260, chance: 73,
  max_profit: 260, max_loss: null,
  max_profit_unbounded: false, max_loss_unbounded: true,
  breakevens: [320, 350], spot_used: 335.08,
};

section("Cash says which direction it goes, not just how much");

is("a debit is money out", row("cash").show(row("cash").of(spread)), "you pay $176");
is("a credit is money in", row("cash").show(row("cash").of(csp)), "you receive $119");

section("No cap and no limit are said in words, never as a number");

is("an uncapped upside", row("best").show(row("best").of(longCall)), "no cap");
is("an unlimited downside", row("worst").show(row("worst").of(naked)), "no limit");
yes("an uncapped upside sorts as the best there is",
    row("best").of(longCall) === Infinity);
yes("an unlimited loss sorts as the worst there is",
    row("worst").of(naked) === Infinity);

section("A tiny ratio is not zero");

// $119 against $33,131 at risk. Two decimals prints "0.00x", which
// reads as nothing rather than as very little -- and very little is
// the entire point of the row.
const r = row("ratio");
is("a cash-secured put's reward per dollar", r.show(r.of(csp)), "0.004×");
is("a spread's", r.show(r.of(spread)), "1.84×");
is("no cap on the upside", r.show(r.of(longCall)), "uncapped");
is("no cap on the risk", r.show(r.of(naked)), "no cap on the risk");

section("The move needed is the nearest break-even, either side");

const m = row("move");
is("a spread needs half a percent", m.show(m.of(spread)), "0.5%");
// A two-sided position breaks even in both directions; the nearer one
// is what has to happen first.
is("a strangle takes the nearer of its two", m.show(m.of(naked)), "4.5%");
is("with no break-even there is nothing to say",
   m.show(m.of({ breakevens: [], spot_used: 335 })), "&ndash;");
is("and nothing without a price to measure from",
   m.show(m.of({ breakevens: [340], spot_used: null })), "&ndash;");

section("Every row knows which way is which");

const bad = VS_ROWS.filter((x) => !["low", "high"].includes(x.good));
yes("each row declares a direction", bad.length === 0,
    bad.map((x) => x.key).join(", ") || "all six");
const noNote = VS_ROWS.filter((x) => !x.note || !x.label);
yes("and each has a label and a reason", noNote.length === 0,
    noNote.map((x) => x.key).join(", ") || "all six");

section("The verdict names the setup that actually wins the row");

/* The panel decides with: good === "high" ? b > a : b < a. Re-stated
 * here so a change to that rule has to be made in two places, which is
 * the point -- naming the wrong structure is the one error a reader
 * cannot catch by looking. */
const winner = (key, A, B) => {
  const rr = row(key);
  const a = rr.of(A), b = rr.of(B);
  if (a == null || b == null || a === b) return null;
  return (rr.good === "high" ? b > a : b < a) ? B.name : A.name;
};

is("the credit trade costs less up front",
   winner("cash", spread, csp), "Cash-secured put");
is("the credit trade is right more often",
   winner("chance", spread, csp), "Cash-secured put");
is("but the spread makes more when it works",
   winner("best", spread, csp), "Bull call spread");
is("and loses far less when it does not",
   winner("worst", spread, csp), "Bull call spread");
is("an uncapped upside beats a capped one",
   winner("best", spread, longCall), "Buy a call");
is("a capped loss beats an unlimited one",
   winner("worst", naked, spread), "Bull call spread");
is("a row where both agree names nobody",
   winner("chance", spread, { ...csp, chance: 39 }), null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
