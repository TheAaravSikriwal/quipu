/* The layout names real things, once each, and every room can be
 * rearranged without breaking.
 *
 * layout.js is the one place that decides what is on screen. A typo
 * there would not throw -- the panel would quietly not appear -- so the
 * names are checked here against what the rooms actually registered.
 *
 *   node frontend/layout.test.js
 */

const { page } = require("./lift.js");

const P = page("LAYOUT", "LAYOUT_PARTS", "SEARCH_ORDER", "PANELS", "ROOMS", "VIEWS", "REGIONS",
               "layoutOf", "compose", "bookView");

let pass = 0, fail = 0;
function ok(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name.padEnd(56)} ${detail}`);
  cond ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

section("Every name in the layout is a panel that exists");

for (const room of Object.keys(P.LAYOUT)) {
  const names = P.layoutOf(room);
  const unknown = names.filter((n) => !P.PANELS[room]?.[n]);
  ok(`${room}: every name is registered`, !unknown.length,
     unknown.length ? unknown.join(", ") : `${names.length} panels`);

  const twice = names.filter((n, i) => names.indexOf(n) !== i);
  ok(`${room}: no panel is listed twice`, !twice.length, twice.join(", "));

  const owner = P.LAYOUT_PARTS[room] || room;
  ok(`${room}: is a room the app has${owner !== room ? ` (part of ${owner})` : ""}`,
     owner in P.ROOMS && owner in P.VIEWS);
}

section("Every panel says what it is");

const bare = [];
for (const [room, panels] of Object.entries(P.PANELS)) {
  for (const [id, p] of Object.entries(panels)) {
    if (!p.what || p.what.length < 8) bare.push(`${room}/${id}`);
    if (typeof p.draw !== "function") bare.push(`${room}/${id} (no draw)`);
  }
}
ok("each has a description and a draw", !bare.length, bare.join(", "));

// What exists but is switched off is not a failure -- that is what
// the layout is for -- but it should be visible when it happens.
const hidden = [];
for (const [room, panels] of Object.entries(P.PANELS)) {
  const on = P.layoutOf(room);
  Object.keys(panels).forEach((id) => { if (!on.includes(id)) hidden.push(`${room}/${id}`); });
}
console.log(`  (hidden, registered but not in the layout: ${hidden.length ? hidden.join(", ") : "none"})`);

section("The search page draws both halves, in the order given");

ok("SEARCH_ORDER names only the page's parts",
   P.SEARCH_ORDER.every((k) => ["tiles", "bar", "steps"].includes(k)), P.SEARCH_ORDER.join(", "));
ok("the steps come after the company's panels, with the bar between",
   P.SEARCH_ORDER.indexOf("tiles") < P.SEARCH_ORDER.indexOf("bar")
   && P.SEARCH_ORDER.indexOf("bar") < P.SEARCH_ORDER.indexOf("steps"), P.SEARCH_ORDER.join(" > "));

section("The search rail is the layout, not a second copy of it");

const bandsOf = [...P.LAYOUT.search, ...P.LAYOUT.steps];
const groups = bandsOf.map((g) => g.id);
ok("group ids are unique", new Set(groups).size === groups.length, groups.join(", "));
ok("the rail has exactly the layout's groups",
   JSON.stringify(P.REGIONS.map((r) => r.keys)) ===
   JSON.stringify(bandsOf.map((g) => g.panels)));

section("A room survives any panel being taken away");

// The log is the one room that can be drawn without the network, so
// it is drawn here for real: with every panel, then with each one
// removed in turn. A panel that quietly leaned on another being
// present would throw on one of these.
const now = new Date().toISOString();
const book = [
  { id: "a", symbol: "AAPL", legs: [{ kind: "call", side: "long", strike: 250, qty: 1, entry: 5, expiry: "2027-01-15" }],
    opened_at: now, opened: now.slice(0, 10) },
  { id: "b", symbol: "MSFT", legs: [{ kind: "put", side: "short", strike: 400, qty: 1, entry: 3, expiry: "2026-10-16" }],
    opened_at: now, opened: now.slice(0, 10), closed: now.slice(0, 10), closed_at: now,
    realised: 120, realised_pct: 40 },
];
const tab = { ui: { book, marks: {}, closing: null, bankedFrom: null } };

const full = P.compose("log", tab, P.bookView(tab));
ok("the log draws with everything", full.includes("AAPL") && full.includes("MSFT"),
   `${full.length} chars`);

const original = P.LAYOUT.log.slice();
const broke = [];
for (const id of original) {
  P.LAYOUT.log.splice(0, P.LAYOUT.log.length, ...original.filter((x) => x !== id));
  try {
    const html = P.compose("log", tab, P.bookView(tab));
    if (html === full) broke.push(`${id} (removing it changed nothing)`);
  } catch (e) {
    broke.push(`${id}: ${e.message}`);
  }
}
P.LAYOUT.log.splice(0, P.LAYOUT.log.length, ...original);
ok("and with each panel taken out in turn", !broke.length,
   broke.length ? broke.join("; ") : `${original.length} ways`);

section("A name that does not exist costs one panel, not the room");

P.LAYOUT.log.push("no-such-panel");
let html = "", threw = null;
try { html = P.compose("log", tab, P.bookView(tab)); } catch (e) { threw = e.message; }
P.LAYOUT.log.pop();
ok("the room still draws", !threw && html === full, threw || "");
ok("and says which name was wrong",
   P.warnings.some((w) => w.includes('"no-such-panel"')), P.warnings.slice(-1)[0] || "");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
