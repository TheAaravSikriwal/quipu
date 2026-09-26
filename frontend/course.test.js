/* The curriculum's squares draw everything the four steps give them.
 *
 * Reads the courses verify.py builds offline (backend/cache/
 * course_fixture.json -- XYZ, a seeded price history, Alpaca off) and draws
 * every square, face and opened detail, inside the real page scope. Two
 * courses: exactly as computed on that history, and with the curriculum's
 * own bullish XYZ call, so Steps 3 and 4 are drawn both with a trade and
 * with "no trade". A field the backend adds or renames shows up here the
 * same day, as a number that never reached the page.
 *
 * The face of a square is the figure, its lean and the rule that applied;
 * the detail -- the table, the comparisons, the sum, the formula -- must
 * be inside it. Both halves are checked.
 *
 *   python -m backend.verify     (writes the fixture, then runs this)
 *   node frontend/course.test.js
 */

const fs = require("fs");
const path = require("path");
const { page } = require("./lift.js");

const FX = path.join(__dirname, "..", "backend", "cache", "course_fixture.json");
if (!fs.existsSync(FX)) {
  console.log("  [SKIP] no fixture yet -- run python -m backend.verify first");
  console.log("\n0 passed, 0 failed");
  process.exit(0);
}
const FIXTURES = JSON.parse(fs.readFileSync(FX, "utf8"));
const P = page("LAYOUT", "compose", "layoutOf", "esc", "DETAIL", "QUIPU_COURSE");
const esc = P.esc;          // the page's own, so the test cannot drift from it

let pass = 0, fail = 0;
function ok(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name.padEnd(58)} ${detail}`);
  cond ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

const NEWS = { articles: [
  { title: "XYZ beats estimates, raises guidance", url: "#", publisher: "Wire", published: null,
    moving: { score: 5 }, lean: { reads: "bullish", words: ["+beats estimates", "+raises guidance"], mixed: false } },
  { title: "Analyst cuts price target on XYZ", url: "#", publisher: "Wire", published: null,
    moving: { score: 3 }, lean: { reads: "bearish", words: ["-cuts price target"], mixed: false } },
] };

const plain = (h) => h.replace(/<[^>]+>/g, " ");
const HALF_FORMED = [["undefined", "a missing field"], ["NaN", "arithmetic on nothing"],
                     ["[object", "an object printed as text"], ["$-", "a minus after the dollar"],
                     ["null", "a null printed as text"]];

for (const [which, course] of Object.entries(FIXTURES)) {
  const tab = { id: 1, symbol: "XYZ", status: "ready", courseState: "ready", course,
                data: { news: NEWS }, ui: {} };
  const d = tab.data;
  const s3 = course.steps["3"];
  const trade = !!s3.legs?.length;
  const faces = P.compose("steps", d, tab);
  const ids = P.layoutOf("steps");
  const drawn = ids.filter((id) => faces.includes(`data-tile="${id}"`));
  const details = Object.fromEntries(drawn.map((id) => [id, P.DETAIL[id] ? P.DETAIL[id](d, tab) : ""]));

  section(`${which} (${s3.name}): the squares`);
  // Without a trade, the squares that describe one have nothing to show
  // and are left out rather than drawn empty.
  const tradeOnly = ["c-expiry", "c-strikes", "c-payoff", "c-odds", "c-greeks", "c-size", "c-exposure", "c-exits"];
  const want = ids.filter((id) => trade || !tradeOnly.includes(id));
  const missing = want.filter((id) => !drawn.includes(id));
  ok("every square that has something to say is drawn", !missing.length,
     missing.join(", ") || `${drawn.length} squares`);
  ok("each is a tile the grid can pack", (faces.match(/class="tile /g) || []).length === drawn.length);
  const empty = drawn.filter((id) => (details[id] || "").length < 60);
  ok("and each opens into its detail", !empty.length, empty.join(", ") || "all");

  section(`${which}: every number reaches the page, in brief and in full`);
  const metrics = ["1", "2"].flatMap((k) => course.steps[k].sections.flatMap((s) => s.metrics));
  const onFace = metrics.filter((m) => !faces.includes(esc(m.label)));
  ok("every metric's square carries its name", !onFace.length, onFace.map((m) => m.id).join(", ") || `${metrics.length}`);
  const noFig = metrics.filter((m) => m.available && !faces.includes(esc(m.show)));
  ok("and its figure on the face", !noFig.length, noFig.map((m) => m.id).join(", ") || "all");
  const quiet = metrics.filter((m) => !m.available && !faces.includes(esc(m.why)));
  ok("an unavailable one says why, on the face", !quiet.length, quiet.map((m) => m.id).join(", ") || "all");

  const inside = (m) => details["c-" + m.id] || "";
  const noTable = metrics.filter((m) => m.available && m.against && !inside(m).includes("cg-table"));
  ok("opened, each has the curriculum's table", !noTable.length, noTable.map((m) => m.id).join(", ") || "all");
  const noCmp = metrics.filter((m) => m.available && m.compare?.length
    && !m.compare.every((c) => inside(m).includes(esc(c.label))));
  ok("every comparison", !noCmp.length, noCmp.map((m) => m.id).join(", ") || "all");
  const noSum = metrics.filter((m) => m.available && m.working && !inside(m).includes("wcalc"));
  ok("the sum laid out", !noSum.length, noSum.map((m) => m.id).join(", ") || "all");
  const noFormula = metrics.filter((m) => m.formula && !inside(m).includes(esc(m.formula)));
  ok("and the formula", !noFormula.length, noFormula.map((m) => m.id).join(", ") || "all");
  const worked = metrics.filter((m) => m.available && m.working).length;
  const hovers = (faces.match(/data-calc=/g) || []).length;
  ok("every worked figure can be hovered on the face", hovers >= worked, `${hovers} for ${worked}`);

  const card = course.steps["2"].scorecard;
  ok("the scorecard opens to every signal", card.rows.every((r) => details["c-scorecard"].includes(esc(r.label))),
     `${card.rows.length} signals`);
  ok("the matrix lights exactly one cell, face and detail",
     (faces.match(/<td class="hit">/g) || []).length === 1
     && (details["c-matrix"].match(/<td class="hit">/g) || []).length === 1);
  if (trade) {
    ok("every leg is on the strikes square", s3.legs.every((l) => plain(faces).includes(`$${Number(l.strike).toFixed(2)}`)));
    ok("the payoff is drawn, on the face and inside",
       faces.includes("ct-payoff") && details["c-payoff"].includes("pfsvg"));
    ok("its equations are written out", !s3.formulas || s3.formulas.rows.every(([l]) => details["c-payoff"].includes(esc(l))));
    ok("the thesis is on its square", faces.includes(esc(course.steps["4"].thesis).slice(0, 40)));
    ok("and the account can be set from inside Step 4", /data-cg-account/.test(details["c-size"]));
  } else {
    ok("no trade is said on the thesis square", faces.includes(esc(s3.summary).slice(0, 40)), (s3.summary || "").slice(0, 50));
  }
  ok("the news opens to the tagged headlines and their words",
     details["c-news"].includes("+beats estimates") && details["c-news"].includes("-cuts price target"));
  ok("and says it adds no points", /adds no points/.test(plain(details["c-news"])));

  section(`${which}: nothing reaches the page half-formatted`);
  const all = plain(faces + Object.values(details).join(" "));
  for (const [bad, why] of HALF_FORMED) {
    const at = all.indexOf(bad);
    ok(`no "${bad}" (${why})`, at < 0, at < 0 ? "" : `...${all.slice(Math.max(0, at - 40), at + 20)}...`);
  }

  section(`${which}: the bar`);
  const bar = P.QUIPU_COURSE.bar(tab);
  ok("offers Create the path", /Create the path/.test(bar));
  ok("jumps to each step", [1, 2, 3, 4].every((n) => bar.includes(`data-cg-step="${n}"`)));
  ok("carries the verdict", bar.includes(esc(course.steps["2"].output.direction)));
  ok("and Open in Workshop only when there is a trade", /data-cg-open/.test(bar) === trade);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
