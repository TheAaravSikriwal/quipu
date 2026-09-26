/* QUIPU -- what every room shares.
 *
 * Formatting, the tab state, the trade log's storage, and the helpers
 * that attach arithmetic to a number. Nothing here draws a room.
 *
 * The frontend is classic scripts sharing one scope, loaded in the
 * order index.html lists them. A file may CALL anything from any
 * other at run time; only top-level initialisers are order-sensitive,
 * and those only ever reach backwards into this file.
 */

/* QUIPU -- browser-shaped shell over the aggregator API.
 *
 * One tab per company. Fast numbers refresh on a timer against /api/live; the
 * slow half (news, financials, filings) is fetched once and left alone.
 *
 * Every tile registers its rendered body under an id, so clicking one can
 * re-present it in the zoom panel -- either the same content a step larger, or
 * a richer DETAIL view where there is more worth showing than a tile can hold.
 */

const API = window.QUIPU_API || "";
const G = window.QUIPU_GREEKS;
/* Link the jargon to its definition wherever fresh HTML lands. */
const gloss = (el) => window.QUIPU_GLOSSARY?.annotate(el);
const LIVE_MS = 15000;
/* News is watched on its own, slower clock.
 *
 * Prices move every tick and a headline does not, so polling both at
 * fifteen seconds would be five RSS fetches a minute per open tab for
 * no benefit. Ninety seconds is faster than anybody reloads a page
 * and slow enough that no publisher notices.
 */
const NEWS_MS = 90000;

const state = { tabs: [], active: null, seq: 0, timer: null };

/** Filled during each render: tile id -> its body HTML, for the zoom panel. */
let BODIES = {};
let TITLES = {};

/* ---- formatting ------------------------------------------------------ */

const nf = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "--"
    : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

const money = (v, d = 2) => (v === null || v === undefined ? "--" : "$" + nf(v, d));
/* A strike, which is a NAME as much as a number.
 *
 * Rounded to whole dollars to keep leg lists tidy, the 337.5 call
 * printed as "$338" -- a contract that exists, trades separately, and
 * is not the one being bought. Half-dollar strikes are standard near
 * the money on anything liquid, so this was wrong on most of them.
 *
 * Whole strikes still print whole: "$340 call", not "$340.00 call".
 */
const strikeOf = (v) => {
  if (v === null || v === undefined || v === "") return "--";
  const n = Number(v);
  if (!Number.isFinite(n)) return "--";
  // The trailing zero to drop is the CENTS one -- 337.50 reads as
  // 337.5. Applied to a whole strike it ate a real digit instead:
  // $220 printed as "$22", $100 as "$10", $1,200 as "$1,20". Every
  // round strike on the board was wrong by a factor of ten, on the
  // chips that say which contract you are about to buy.
  return "$" + (n % 1 === 0 ? nf(n, 0) : nf(n, 2).replace(/0$/, ""));
};
/* A fraction shown as a percentage.
 *
 * Exists because `pct100(xNone)` is a trap: in JavaScript `null * 100`
 * is 0, not null, so a missing value arrives at the formatter already
 * converted into a real zero and prints as "0.0%". That is worse than
 * a dash -- it asserts the thing was measured and came out at nothing.
 * SPY was reporting a gross margin of 0.0%, which a fund does not have.
 *
 * Check first, multiply second.
 */
const pct100 = (v, d = 2) =>
  (v === null || v === undefined || Number.isNaN(v) ? "--" : nf(v * 100, d) + "%");

/* The same guard without the percent sign, for the places that put a
 * fraction into a sentence as a count. Both of its callers are already
 * protected by a filter further up, but the guard is a long way from
 * the use -- and a rule that has to be remembered at a distance is one
 * that gets broken by the next edit. */
const x100 = (v, d = 2) =>
  (v === null || v === undefined || Number.isNaN(v) ? "--" : nf(v * 100, d));

const pct = (v, d = 2) => (v === null || v === undefined ? "--" : nf(v, d) + "%");
const signed = (v, d = 1) => (v === null || v === undefined ? "--" : (v > 0 ? "+" : "") + nf(v, d) + "%");

function big(v) {
  if (v === null || v === undefined) return "--";
  const n = Math.abs(v);
  if (n >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (n >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return nf(v, 0);
}

function ago(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(+then)) return "";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + " min ago";
  if (mins < 1440) return Math.floor(mins / 60) + " hr ago";
  const d = Math.floor(mins / 1440);
  return d + (d === 1 ? " day ago" : " days ago");
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const sign = (v) => (v > 0 ? "up" : v < 0 ? "down" : "dim");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/* ---- positions --------------------------------------------------------
 *
 * A trade you have already put on. You enter legs, not a strategy name --
 * the app works out what you built and what that shape implies, which is
 * the thing the reference workbooks cannot do (theirs asks the user to
 * tick a box saying "is this a Collar?").
 *
 * Legs live in localStorage. This is a local instrument and a position is
 * the one piece of state that is genuinely yours rather than fetched.
 */
const POS_KEY = "quipu.positions";
/* Where the banked total starts counting.
 *
 * Reset draws a LINE rather than deleting anything. A trade log whose
 * history can be wiped by a button next to a total is not a log, and
 * the closed trades are the part you cannot reconstruct -- the marks
 * come back from the market every time, the record of what you
 * actually did does not.
 *
 * So the trades stay, the tile says what it is counting from, and the
 * line can be lifted again.
 */
const BANKED_FROM_KEY = "quipu.bankedFrom";
const loadBankedFrom = () => {
  try { return localStorage.getItem(BANKED_FROM_KEY) || null; } catch { return null; }
};
const saveBankedFrom = (iso) => {
  try {
    if (iso) localStorage.setItem(BANKED_FROM_KEY, iso);
    else localStorage.removeItem(BANKED_FROM_KEY);
  } catch { /* private mode: the line is a convenience, not a record */ }
};

/** Was this trade closed after the line? */
function countsAsBanked(t, from) {
  if (!from) return true;
  return (t.closed_at || t.closed || "") >= from;
}

/* ---- the logbook ----------------------------------------------------
 *
 * Trades are kept, not just the one you happen to have open. A position
 * is a thing you hold for weeks and check on; the app was storing
 * exactly one of them and overwriting it the moment you looked at
 * another, which made it a calculator rather than a record.
 *
 * Local storage, because this is a local tool and a trade log is
 * nobody's business but the person keeping it.
 */
function loadBook() {
  try {
    const raw = JSON.parse(localStorage.getItem(POS_KEY));
    if (Array.isArray(raw)) return raw;
    // The old single-position format, carried over rather than dropped.
    if (raw && raw.legs?.length) {
      return [{ id: "t" + Date.now(), symbol: raw.symbol, legs: raw.legs,
                opened: new Date().toISOString().slice(0, 10), closed: null }];
    }
  } catch { /* unreadable or absent -- an empty book is the right answer */ }
  return [];
}

function saveBook(book) {
  try { localStorage.setItem(POS_KEY, JSON.stringify(book)); }
  catch { /* private mode, or full -- not worth interrupting for */ }
}

const bookOpen = (book) => book.filter((t) => !t.closed);

const blankLeg = () => ({ kind: "call", side: "long", strike: "", qty: 1, entry: "", expiry: "" });

/* A number with its arithmetic attached, for the hover. Falls back to
 * the plain number when there is no working -- a figure that was read
 * off a quote has no derivation, and marking it would promise one. */
const calc = (formatted, working) =>
  (working ? window.QUIPU_WORKING.calc(formatted, working) : formatted);
/* The same sum, laid out on the page instead of inside a hover. */
const wcalc = (working) =>
  (working ? window.QUIPU_WORKING.renderWorking(working) : "");
const WK = () => window.QUIPU_WORKING.WK;

const kv = (label, value, cls = "") =>
  `<div class="kv"><span>${label}</span><span class="${cls}">${value}</span></div>`;
