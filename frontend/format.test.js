/* The formatters that name things, checked against the shipped source.
 *
 * Run:  node frontend/format.test.js
 *
 * These are not decorative. A strike is the NAME of a contract, and a
 * formatter that drops a digit renames it: `strikeOf` was written to
 * turn 337.50 into "337.5", and the trailing-zero strip it used for
 * that also ate the last digit of every round strike. $220 printed as
 * "$22", $100 as "$10", $1,200 as "$1,20" -- on the chips that say
 * which contract you are about to buy, and in the leg table, and in
 * the assignment warning. It shipped because nothing here tested it.
 *
 * The frontend is classic scripts rather than modules, so the definitions
 * are lifted out of the source and evaluated. That is deliberate: it
 * tests the code that actually runs, not a copy of it that can drift.
 */

const { lift } = require("./lift.js");

// nf is what strikeOf formats through, so it has to be the real one.
const { nf, strikeOf } = lift("nf", "strikeOf");

let pass = 0, fail = 0;

function is(name, got, want) {
  const ok = got === want;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name.padEnd(54)} got ${got}  want ${want}`);
  ok ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

section("A strike keeps every digit it has");

// The exact failures that shipped.
is("a round hundred", strikeOf(100), "$100");
is("two hundred and twenty", strikeOf(220), "$220");
is("two hundred and thirty", strikeOf(230), "$230");
is("two hundred and fifty", strikeOf(250), "$250");
is("past a thousand, with its separator", strikeOf(1200), "$1,200");

// The case the trailing-zero strip was written for.
is("a half strike loses the cents zero", strikeOf(337.5), "$337.5");
is("and the other half strike", strikeOf(342.5), "$342.5");
is("a low half strike", strikeOf(7.5), "$7.5");

// Real cents must survive.
is("a quarter strike keeps both digits", strikeOf(337.25), "$337.25");
is("a leading-zero cent keeps both", strikeOf(337.05), "$337.05");

section("And says nothing rather than something wrong");

is("null", strikeOf(null), "--");
is("undefined", strikeOf(undefined), "--");
is("empty string", strikeOf(""), "--");
is("not a number", strikeOf("abc"), "--");

section("Every listed strike round-trips");

// A formatter is only trustworthy if reading it back gives the strike
// you started with. Walked across the shapes a US equity board uses.
const ladder = [];
for (let k = 5; k <= 1000; k += 2.5) ladder.push(k);
const broken = ladder.filter((k) => {
  const back = Number(strikeOf(k).replace(/[$,]/g, ""));
  return back !== k;
});
is(`${ladder.length} strikes from $5 to $1,000 in 2.50 steps`,
   broken.length, 0);
if (broken.length) console.log("        first few:", broken.slice(0, 6).join(", "));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
