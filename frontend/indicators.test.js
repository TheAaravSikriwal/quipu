/* Indicators checked against something other than themselves.
 *
 * The same rule the Python suite follows: every figure is tested against
 * an independent source of truth -- a published worked example, or an
 * identity that has to hold however the thing is implemented.
 *
 * Run:  node frontend/indicators.test.js
 */

const fs = require("fs");
const path = require("path");

// chart.js is a browser file: it ends by assigning to `window`, and its
// draw code touches the DOM. Only the pure maths is wanted here, so a
// minimal window stands in and nothing else is called.
global.window = {};
global.document = { createElementNS: () => ({ setAttribute() {}, appendChild() {} }) };
global.setInterval = () => 0;
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

const src = fs.readFileSync(path.join(__dirname, "chart.js"), "utf8");
// Run it in its own scope. Evaluated inline, chart.js's top-level
// declarations collide with this file's imports of the same names.
new Function(src).call(global);
const { rsi, ema, macd, macdCrossBars, bollinger, sma, crossovers } =
  global.window.QUIPU_CHART;

let pass = 0, fail = 0;
const bars = (closes) => closes.map((c) => ({ t: "", o: c, h: c, l: c, c, v: 0 }));

function near(name, got, want, tol) {
  const ok = got != null && Math.abs(got - want) <= tol;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name.padEnd(52)} got ${
    got == null ? "null" : Number(got).toFixed(4)}  want ${want}`);
  ok ? pass++ : fail++;
}
function yes(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name.padEnd(52)} ${detail}`);
  cond ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

/* ------------------------------------------------------------------ RSI
 *
 * Wilder's own worked example from "New Concepts in Technical Trading
 * Systems", the series every implementation is checked against. The
 * expected values below are the published ones, not this code's output.
 */
section("RSI against Wilder's published example");

const WILDER = [
  44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
  45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
  46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
  43.42, 42.66, 43.13,
];
const EXPECTED = {
  14: 70.46, 15: 66.25, 16: 66.48, 17: 69.35, 18: 66.29, 19: 57.92,
  20: 62.88, 21: 63.21, 22: 56.01, 23: 62.34, 24: 54.68, 25: 50.39,
  26: 39.99, 27: 41.46, 28: 41.87, 29: 45.46, 30: 37.30, 31: 33.08,
  32: 37.77,
};

const R = rsi(bars(WILDER), 14);
for (const [i, want] of Object.entries(EXPECTED)) {
  near(`RSI at bar ${i}`, R[i], want, 0.05);
}

section("RSI cannot leave its own range");
yes("nothing before the first full window",
    R.slice(0, 14).every((v) => v === null), "first 14 are null");
yes("every value sits between 0 and 100",
    R.filter((v) => v != null).every((v) => v >= 0 && v <= 100),
    `${R.filter((v) => v != null).length} values`);

// A series that only rises has no losses at all. That is RSI 100 by
// definition and a division by zero in the arithmetic; it happens to a
// real stock on a two-week run.
const up = rsi(bars(Array.from({ length: 40 }, (_, i) => 100 + i)), 14);
near("a series that only rises reads 100", up[39], 100, 1e-9);
const down = rsi(bars(Array.from({ length: 40 }, (_, i) => 200 - i)), 14);
near("a series that only falls reads 0", down[39], 0, 1e-9);
// A flat line has neither, which is 100 under the same convention every
// platform uses -- but it must not be NaN.
const flat = rsi(bars(new Array(40).fill(50)), 14);
yes("a flat line is a number, not NaN", Number.isFinite(flat[39]), String(flat[39]));

/* ------------------------------------------------------------------ EMA */
section("EMA seeds where it should");

const seq = Array.from({ length: 30 }, (_, i) => i + 1);
const e10 = ema(seq, 10);
yes("nothing before the seeding window", e10.slice(0, 9).every((v) => v === null), "");
near("seeds on the simple average of the first window", e10[9], 5.5, 1e-9);
near("then carries forward at 2/(n+1)", e10[10], 11 * (2 / 11) + 5.5 * (9 / 11), 1e-9);

// The MACD signal line is an EMA of a series that begins with nulls. An
// index-based seed divided a single value by the period.
const gappy = [null, null, null, null, 10, 20, 30, 40, 50, 60, 70, 80];
const eg = ema(gappy, 3);
near("leading nulls do not corrupt the seed", eg[6], 20, 1e-9);
yes("and nothing is emitted before the window fills",
    eg.slice(0, 6).every((v) => v === null), "");

/* ----------------------------------------------------------------- MACD */
section("MACD holds its own identity");

const noise = Array.from({ length: 120 }, (_, i) =>
  100 + 10 * Math.sin(i / 7) + 3 * Math.cos(i / 3));
const m = macd(bars(noise));
const i = 119;
near("histogram is the line less its signal", m.hist[i], m.line[i] - m.signal[i], 1e-9);

// On a constant series the two averages are equal, so the gap is zero.
const mflat = macd(bars(new Array(80).fill(42)));
near("a flat series has no divergence", mflat.line[79], 0, 1e-9);
near("and no histogram", mflat.hist[79], 0, 1e-9);

/* ------------------------------------------------------------ Bollinger */
section("Bollinger bands are the average plus its own spread");

const b = bollinger(bars(noise), 20, 2);
yes("the middle band is the 20-day average",
    Math.abs(b.mid[119] - sma(bars(noise), 20)[119]) < 1e-9, "");
yes("upper is above middle is above lower",
    b.up[119] > b.mid[119] && b.mid[119] > b.dn[119],
    `${b.dn[119].toFixed(2)} < ${b.mid[119].toFixed(2)} < ${b.up[119].toFixed(2)}`);
near("the band is symmetric about the average",
    b.up[119] - b.mid[119], b.mid[119] - b.dn[119], 1e-9);

// Two standard deviations of nothing is nothing.
const bflat = bollinger(bars(new Array(40).fill(7)), 20, 2);
near("a flat series has no width", bflat.up[39] - bflat.dn[39], 0, 1e-9);

/* ------------------------------------------------------- 50/200 cross */
section("Golden and death crosses are not the same event");

// A series that falls for a year then rises for a year: the 50 has to
// cross UP through the 200 exactly once, and that is the golden cross.
const vshape = [];
for (let k = 0; k < 400; k++) vshape.push(300 - k * 0.5);
for (let k = 0; k < 400; k++) vshape.push(100 + k * 0.5);
const cv = crossovers(bars(vshape), 50, 200);
yes("a V-shape crosses exactly once", cv.length === 1, `${cv.length} crossing(s)`);
yes("and rising through is the GOLDEN cross",
    cv[0] && cv[0].kind === "golden", cv[0] ? cv[0].kind : "none");

// The mirror image. Falling through is the DEATH cross. This is the
// pair most often held the wrong way round, so it is asserted in both
// directions rather than assumed from one.
const peak = [];
for (let k = 0; k < 400; k++) peak.push(100 + k * 0.5);
for (let k = 0; k < 400; k++) peak.push(300 - k * 0.5);
const cp = crossovers(bars(peak), 50, 200);
yes("an inverted V also crosses once", cp.length === 1, `${cp.length} crossing(s)`);
yes("and falling through is the DEATH cross",
    cp[0] && cp[0].kind === "death", cp[0] ? cp[0].kind : "none");

if (cv[0]) {
  yes("the averages meet where the cross is marked",
      Math.abs(cv[0].fast - cv[0].slow) < 1,
      `50 at ${cv[0].fast.toFixed(2)}, 200 at ${cv[0].slow.toFixed(2)}`);
}

const steady = crossovers(
  bars(Array.from({ length: 600 }, (_, k) => 50 + k * 0.2)), 50, 200);
yes("a one-way trend never crosses", steady.length === 0, `${steady.length} crossings`);

yes("no crossings without enough history",
    crossovers(bars(Array.from({ length: 150 }, (_, k) => 100 + k)), 50, 200).length === 0,
    "150 bars, no 200-day average");

// Crossings must alternate. Two goldens in a row would mean one was
// counted on the way through without the pair ever returning.
const wobble = [];
for (let c = 0; c < 3; c++) {
  for (let k = 0; k < 300; k++) wobble.push(200 + 60 * Math.sin(k / 48 + c));
}
const cw = crossovers(bars(wobble), 50, 200);
yes("crossings alternate direction",
    cw.length > 1 && cw.every((c, idx) => idx === 0 || c.kind !== cw[idx - 1].kind),
    `${cw.length}: ` + cw.map((c) => c.kind[0]).join(""));


/* Exact equality, including null -- near() cannot express "no crossing",
 * and a null that quietly compared equal to 0 would hide the one case
 * this function most needs to get right. */
function same(name, got, want) {
  const ok = got === want;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name.padEnd(52)} got ${got}  want ${want}`);
  ok ? pass++ : fail++;
}

section("How long the MACD has been on this side of its signal");

/* A crossing that happened this morning and one that happened in March
 * are the same fact stated with very different confidence, and the
 * readout used to say neither. Counted from the histogram, which is
 * the MACD line less its signal -- so a change of sign in the
 * histogram IS the crossing.
 */

// Hand-built histograms, so the expected answer is countable by eye.
same("crossed on the last bar", macdCrossBars([-1, -1, -1, 2], 3), 1);
same("crossed three bars back", macdCrossBars([-1, 2, 2, 2], 3), 3);
same("crossed the other way", macdCrossBars([1, 1, -2], 2), 1);

// Zero counts as the positive side, the same way the readout's
// "above or below" does -- the two must agree or the sentence and the
// number contradict each other.
same("exactly zero is treated as above", macdCrossBars([-1, -1, 0], 2), 1);

// No crossing inside the data is NOT "a long time ago". It is the
// absence of a measurement, and saying "200 sessions" would be
// inventing one.
same("no crossing in the data at all", macdCrossBars([1, 2, 3, 4], 3), null);
same("nothing to measure from", macdCrossBars([null, null], 1), null);
same("an empty histogram", macdCrossBars([], 0), null);

// Against the real generator rather than a hand-built array: whatever
// it returns must point at an actual change of sign.
const hist = macd(bars(noise)).hist;
const last = hist.length - 1;
const back = macdCrossBars(hist, last);
if (back == null) {
  yes("the sample never crosses, and it says so", true, "null");
} else {
  const here = hist[last] >= 0;
  const there = hist[last - back] >= 0;
  const between = hist.slice(last - back + 1, last + 1).every((v) => (v >= 0) === here);
  yes("it points at a real change of sign",
      there !== here, `${hist[last - back].toFixed(3)} then ${hist[last].toFixed(3)}`);
  yes("and nothing in between crossed back", between, `${back} bars held`);
}

section("MACD carries the units of the share");

/* This is the whole reason the readout now prints a percentage. The
 * indicator is a difference of two averages of PRICE, so doubling the
 * price doubles the reading without anything about the trend changing.
 */
const cheap = bars(noise);
const dear = bars(noise.map((v) => v * 10));
const mc = macd(cheap), md = macd(dear);
const j = mc.line.length - 1;
near("ten times the price is ten times the MACD",
     md.line[j], mc.line[j] * 10, 1e-6);
near("but the same fraction of the share price",
     md.line[j] / dear[j].c, mc.line[j] / cheap[j].c, 1e-9);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
