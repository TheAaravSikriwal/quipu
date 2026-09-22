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
const { rsi, ema, macd, bollinger, sma } = global.window.QUIPU_CHART;

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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
