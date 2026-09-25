/* The payoff diagram, checked for the things that make it readable.
 *
 * Run:  node frontend/payoff.test.js
 *
 * This replaced a borrowed price-series chart that was handed
 * {date: "342.50", close: -199} -- share prices pretending to be
 * dates. It drew the line and could draw none of the rest, and the
 * rest is the diagram: where the strikes are, which side of zero you
 * are on, where the most you can make and lose actually happen.
 *
 * The failures worth catching here are the ones that make it lie:
 * drawing a range so wide the position is a spike, missing the
 * corners that define a piecewise-linear payoff, or putting the
 * winning tint on the losing side.
 */

const { payoffSvg, scales, zeroCrossings, strikeMarks } = require("./payoff.js");

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

/* An iron condor on a $341 share: 335/337.5 puts, 345/347.5 calls,
 * $54 credit. The exact position that prompted all of this. */
const LEGS = [
  { kind: "put", side: "long", strike: 335, qty: 1 },
  { kind: "put", side: "short", strike: 337.5, qty: 1 },
  { kind: "call", side: "short", strike: 345, qty: 1 },
  { kind: "call", side: "long", strike: 347.5, qty: 1 },
];
const pay = (s) => {
  const v = (k, call) => Math.max(call ? s - k : k - s, 0);
  return 100 * (v(335, 0) - v(337.5, 0) - v(345, 1) + v(347.5, 1)) + 54;
};
// The range the engine really produces: 40% of spot to nearly twice it.
const WIDE = [];
for (let i = 0; i <= 60; i++) {
  const s = 136 + (614 - 136) * i / 60;
  WIDE.push({ s, pl: pay(s) });
}
// Plus the corners, which the engine now adds.
const CURVE = WIDE.concat(
  [335, 337.5, 345, 347.5, 336.96, 345.54, 341.02].flatMap(
    (k) => [{ s: k, pl: pay(k) }])
).sort((a, b) => a.s - b.s);

const OPTS = {
  curve: CURVE, legs: LEGS, spot: 341.02, breakevens: [336.96, 345.54],
  maxProfit: 54, maxLoss: -196,
  bestAt: [{ lo: 337.5, hi: 345 }],
  worstAt: [{ lo: 136, hi: 335, to_zero: true }],
};

section("It draws the part of the price line with something in it");

const svg = payoffSvg(OPTS);
const drawnXs = (svg.match(/class="pfline" points="([^"]+)"/) || [])[1]
  .split(" ").map((p) => +p.split(",")[0]);
yes("the curve is drawn", drawnXs.length > 4, `${drawnXs.length} points`);

// Everything that matters has to be inside the window, or the reader
// is looking at a spike with two flat lines either side.
[335, 337.5, 345, 347.5].forEach((k) =>
  yes(`the ${k} strike is on the chart`, svg.includes(`>$${k}<`)));
yes("and both break-evens", svg.includes(">$336.96<") && svg.includes(">$345.54<"));
yes("and today's price", /now \$341\.02/.test(svg));

section("Both extremes are named where they happen");

yes("the most it can make", /most it can make \$54/.test(svg));
yes("the most it can lose", /most it can lose −\$196/.test(svg));

// An uncapped position must say so rather than naming a number that
// does not exist.
const call = payoffSvg({
  curve: [{ s: 300, pl: -500 }, { s: 350, pl: 0 }, { s: 400, pl: 4500 }],
  legs: [{ kind: "call", side: "long", strike: 345, qty: 1 }],
  spot: 341, breakevens: [350], maxProfit: null, maxLoss: -500,
  unboundedUp: true, worstAt: [{ lo: 300, hi: 345, to_zero: true }],
});
yes("no cap says no cap", /no cap/.test(call));
yes("and names no figure for it", !/most it can make \$/.test(call));

section("The winning side is tinted apart from the losing side");

yes("both tints are drawn",
    svg.includes("pfband win") && svg.includes("pfband lose"));
// The crossings the tints stop at must be the break-evens.
const cuts = zeroCrossings(CURVE).map((v) => Math.round(v * 100) / 100);
yes("the tints change hands at the break-evens",
    cuts.length === 2 && Math.abs(cuts[0] - 336.96) < 0.2
      && Math.abs(cuts[1] - 345.54) < 0.2, cuts.join(", "));

section("Every strike says which leg put it there");

const marks = strikeMarks(LEGS);
is("four strikes", marks.length, 4);
yes("the short put is labelled short", /−1 put/.test(svg));
yes("the long call is labelled long", /\+1 call/.test(svg));
yes("shares contribute no strike",
    strikeMarks([{ kind: "stock", side: "long", qty: 100, strike: null }]).length === 0);

section("Zero is always on the chart");

// A position that only ever wins still needs its zero line, or the
// shape means nothing.
const s2 = scales([{ s: 10, pl: 40 }, { s: 20, pl: 90 }], 600, 240);
yes("a payoff that never loses still shows zero", s2.y0 <= 0, `y0 ${s2.y0.toFixed(1)}`);
const s3 = scales([{ s: 10, pl: -40 }, { s: 20, pl: -90 }], 600, 240);
yes("and one that never wins", s3.y1 >= 0, `y1 ${s3.y1.toFixed(1)}`);

section("It refuses rather than drawing nonsense");

yes("no curve", /nothing to draw/.test(payoffSvg({ curve: [] })));
yes("one point", /nothing to draw/.test(payoffSvg({ curve: [{ s: 1, pl: 1 }] })));
yes("values that are not numbers",
    /nothing to draw/.test(payoffSvg({ curve: [{ s: NaN, pl: 1 }, { s: 2, pl: NaN }] })));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
