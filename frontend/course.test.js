/* The step-by-step guide draws everything the four steps give it.
 *
 * Reads the courses verify.py builds offline (backend/cache/
 * course_fixture.json -- XYZ, a seeded price history, Alpaca off) and
 * draws every guide panel from each inside the real page scope. Two of
 * them: the four steps exactly as computed on that history, and the same
 * with the curriculum's own bullish XYZ call, so Steps 3 and 4 are drawn
 * both with a trade and with "no trade". A field the backend adds or
 * renames shows up here the same day, as a number that never reached
 * the page.
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
const P = page("LAYOUT", "compose", "layoutOf", "esc");
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

function only(id, tab) {
  const saved = P.LAYOUT.guide.slice();
  P.LAYOUT.guide.splice(0, P.LAYOUT.guide.length, id);
  try { return P.compose("guide", tab); }
  finally { P.LAYOUT.guide.splice(0, P.LAYOUT.guide.length, ...saved); }
}

for (const [which, course] of Object.entries(FIXTURES)) {
  const tab = { id: 1, symbol: "XYZ", status: "ready", courseState: "ready", course,
                data: { news: NEWS }, ui: {} };
  const html = P.compose("guide", tab);
  const text = html.replace(/<[^>]+>/g, " ");
  const s3 = course.steps["3"];

  section(`${which} (${s3.name}): every piece is drawn`);
  for (const id of P.layoutOf("guide")) {
    const h = only(id, tab);
    // Step 4 with no trade is one line saying so; everything else is a panel.
    const least = id === "step4" && s3.strategy === "none" ? 20 : 80;
    ok(`${id} draws something`, h.length > least, `${h.length} chars`);
  }

  section(`${which}: every number the steps produced reaches the page`);
  const metrics = ["1", "2"].flatMap((k) => course.steps[k].sections.flatMap((s) => s.metrics));
  const noLabel = metrics.filter((m) => !html.includes(esc(m.label)));
  ok("every metric's label is on the page", !noLabel.length,
     noLabel.map((m) => m.id).join(", ") || `${metrics.length} metrics`);
  const noShow = metrics.filter((m) => m.available && !html.includes(esc(m.show)));
  ok("and every available one shows its figure", !noShow.length, noShow.map((m) => m.id).join(", ") || "all");
  const quiet = metrics.filter((m) => !m.available && !html.includes(esc(m.why)));
  ok("every unavailable one says why", !quiet.length, quiet.map((m) => m.id).join(", ") || "all");
  const worked = metrics.filter((m) => m.available && m.working).length;
  const hovers = (html.match(/data-calc=/g) || []).length;
  ok("every worked number can be hovered for its sum", hovers >= worked, `${hovers} hovers for ${worked} worked`);

  const card = course.steps["2"].scorecard;
  ok("the scorecard shows every signal", card.rows.every((r) => html.includes(esc(r.label))), `${card.rows.length} signals`);
  ok("the strategy is named", html.includes(esc(s3.name)), s3.name);
  ok("the matrix lights exactly one cell", (html.match(/<td class="hit">/g) || []).length === 1);
  if (s3.legs?.length) {
    ok("every leg is listed", s3.legs.every((l) => text.includes(`$${Number(l.strike).toFixed(2)}`)), `${s3.legs.length} legs`);
    ok("there is a place for the payoff diagram", html.includes("cg-payoff"));
    ok("the thesis is on the page", html.includes(esc(course.steps["4"].thesis).slice(0, 40)));
  } else {
    ok("no trade is said, not left blank", html.includes(esc(s3.summary).slice(0, 40)), (s3.summary || "").slice(0, 50));
  }

  section(`${which}: nothing reaches the page half-formatted`);
  for (const [bad, why] of [["undefined", "a missing field"], ["NaN", "arithmetic on nothing"],
                            ["[object", "an object printed as text"], ["$-", "a minus after the dollar"],
                            ["null", "a null printed as text"]]) {
    const at = text.indexOf(bad);
    ok(`no "${bad}" (${why})`, at < 0, at < 0 ? "" : `...${text.slice(Math.max(0, at - 40), at + 20)}...`);
  }

  section(`${which}: the news sits beside the scorecard and adds nothing to it`);
  ok("both tagged headlines are shown with their words",
     html.includes("+beats estimates") && html.includes("-cuts price target"));
  ok("and the page says it is not scored", /not in it|adds no points/.test(text));
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
