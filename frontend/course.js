/* Room: Search -- the curriculum, as squares in the grid.
 *
 * "From Chart to Trade", run on this stock. Every number the four steps
 * produce is a tile in the same packed grid as the rest of the page, below
 * it, behind a thin bar.
 *
 * A square is FILLED, not merely occupied. Its face is built from blocks
 * ranked by how much they matter -- the figure and its lean first, then
 * the rule that applied, what it means, what it is compared with, the
 * rest of the curriculum's table, the formula, and why the lesson exists
 * -- and once the grid is packed each square is fitted on its own: the
 * least important blocks are dropped until the rest fits at a readable
 * size, then the type is grown until the square is full. So every square
 * ends up with its own size of type, and a large square says more rather
 * than saying the same thing with more space around it.
 *
 * Clicking a square opens all of it: the whole table, every comparison,
 * the sum laid out, the formula, what the curriculum says the lesson is
 * for, the other numbers from the same lesson, and what the step hands to
 * the next one.
 *
 * "Create the path" on the bar numbers the squares in the order the
 * curriculum reads them and joins them with a faint line, each number
 * tinted by the way its square points.
 *
 * Wrapped, so nothing here lands in the page's shared scope except the
 * hooks the search room calls (window.QUIPU_COURSE).
 */
(function () {

const ARROW = { bullish: "&uarr;", bearish: "&darr;", neutral: "&ndash;" };
const STANCE = {
  buy: "buy premium", debit: "debit spreads", sell: "sell premium",
  credit: "credit strategies", pass: "passes", fail: "fails",
};
const ACCOUNT_KEY = "quipu.account", RISK_KEY = "quipu.riskPct";

const num = (v) => (v === null || v === undefined || v === "" ? null : Number(v));
const savedAccount = () => num(localStorage.getItem(ACCOUNT_KEY));
const savedRisk = () => num(localStorage.getItem(RISK_KEY)) || 2;

/* ---- what each lesson is for, in the curriculum's own terms ----------- */

const LESSONS = {
  "0.5": { what: "How far the share moves on an ordinary day, from its IV.",
           why: "It turns an annual percentage into a move you can picture: anything more than about twice this in a day is news.",
           when: "Any time you read an IV." },
  "1.1": { what: "How easily you can get in and out at a fair price.",
           why: "An illiquid option quietly costs you on every entry and every exit, even when the thesis is right.",
           when: "First, on every name. It is a pass/fail gate." },
  "1.2": { what: "Whether options are expensive or cheap against this stock's own past year.",
           why: "It decides whether to lean towards buying premium or selling it, before direction is even known.",
           when: "Right after liquidity passes." },
  "1.3": { what: "How big a move the market is pricing in, and what known events could cause it.",
           why: "Your Step 2 target is judged against this: expecting $5 when $11 is priced makes buying options a bad bet even if you are right.",
           when: "During screening, so every candidate carries its event dates forward." },
  "1.4": { what: "Volume far above normal at a strike -- possibly informed, possibly large positioning.",
           why: "A source of ideas to research, never trades to copy: you cannot see if it is a hedge or one leg of a spread.",
           when: "Optional, while screening." },
  "1.5": { what: "Put volume against call volume.",
           why: "Noted here only for extreme positioning; it is read properly against its own normal in Step 2.",
           when: "While screening." },
  "2.1": { what: "Whether the stock is trending up, down or sideways against its own averages.",
           why: "Trading with the trend has the better base odds; fighting it needs a specific catalyst.",
           when: "First thing in Step 2. It sets your default bias." },
  "2.2": { what: "The prices where the stock has repeatedly stalled or turned.",
           why: "They give the two numbers every later step needs: the target, and the price at which you are wrong.",
           when: "Right after trend, before any strike is chosen." },
  "2.3": { what: "Breakouts from a range, and whether volume was behind them.",
           why: "It times the entry and shows whether a move has real buying or selling behind it.",
           when: "After trend and levels, to refine the timing." },
  "2.4": { what: "Scheduled events that can move the stock sharply, and how it has reacted before.",
           why: "Often the actual reason a move happens now; it also sets the expiration and warns about IV crush.",
           when: "Early in Step 2 -- it feeds straight into the expiration in Step 3." },
  "2.5": { what: "Whether analysts are raising or cutting estimates, and whether it is cheap or dear against its peers.",
           why: "Tells you whether the business supports the chart. Rising estimates tend to support rising prices.",
           when: "After the technical read, as a sanity check before money goes in." },
  "2.6": { what: "Whether it leads or lags the market, and whether that is real or just leverage to it.",
           why: "Confirmation: leaders tend to keep leading. Beta also sizes your market exposure in Step 4.",
           when: "After you have a lean, as a cross-check." },
  "2.7": { what: "Momentum and stretch on a 0-100 scale, from the stock's own prices.",
           why: "Spots overextension, and divergence -- a new high on fading momentum -- is its most useful signal.",
           when: "Timing within an existing thesis, never the thesis." },
  "2.8": { what: "How other options traders are positioned, against their own normal.",
           why: "A crowd check -- contrarian at the extremes.",
           when: "Late, as a gut check. Never the thesis." },
  "2.9": { what: "Whether equally distant puts or calls carry the higher IV.",
           why: "The final 'does the options market agree with me?' check. The signal is the change from normal, not the level.",
           when: "Last in Step 2, right before building the trade." },
  "2.10": { what: "Every signal scored +1, 0 or -1, times its weight, added up.",
            why: "One number for direction, and one for how sure to be of it -- which decides how much delta the trade may carry.",
            when: "At the end of Step 2. Your trade journal is how the weights get adjusted over time." },
  "3.1": { what: "Direction and conviction against the IV environment.",
           why: "Buying when IV is high means paying for vega at a peak; a spread gives most of that back.",
           when: "The first choice in Step 3." },
  "3.2": { what: "The payoff equations for the structure: what you pay, the most you make and lose, the break-even.",
           why: "Known risk and reward before anything is placed.",
           when: "Once the strikes are chosen." },
  "3.3": { what: "An expiration after the catalyst and the timeframe, without paying for time you do not need.",
           why: "Theta accelerates in the last weeks; too short and a right thesis runs out of time.",
           when: "After the strategy, before the strikes." },
  "3.4": { what: "Strikes tied to the Step 2 target and to delta.",
           why: "Long strike near the price, short strike at the target: the market pays you for the part of the move you do not expect.",
           when: "Once the expiry is set." },
  "3.5": { what: "The chance of profit, and the net greeks of the whole position.",
           why: "The model assumes no edge; Step 2 is what is supposed to tilt the odds.",
           when: "Before placing it." },
  "4": { what: "The whole trade in one sentence, with real numbers.",
         why: "If you cannot write it, one of the four steps is incomplete.",
         when: "Before the order goes in." },
  "4.1": { what: "Contracts = account x risk % / the most one contract can lose, rounded down.",
           why: "Losses compound against you: a 50% drawdown needs 100% to recover.",
           when: "Every trade, every time -- never by feel." },
  "4.2": { what: "Delta converted into SPY shares, through beta.",
           why: "Several bullish trades on high-beta stocks are really one big bet on the market.",
           when: "Before adding a trade to what you already hold." },
  "4.3": { what: "The exits: a price stop, a premium stop, a profit target and a time exit.",
           why: "An exit decided afterwards is a hope. Winners turn into losers without one.",
           when: "Written before entry." },
};
LESSONS["1.4-1.5"] = LESSONS["1.4"];

/* ---- fetching ------------------------------------------------------- */

async function load(tab, attempt = 0) {
  if (!tab?.symbol) return;
  tab.courseState = "loading";
  const acct = savedAccount(), risk = savedRisk();
  const q = new URLSearchParams({ risk: String(risk) });
  if (acct) q.set("account", String(acct));
  try {
    const res = await fetch(`${API}/api/course/${encodeURIComponent(tab.symbol)}?${q}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    tab.course = await res.json();
    tab.courseState = "ready";
  } catch (err) {
    tab.courseState = "error";
    tab.courseError = String(err.message || err);
  }
  if (state.active === tab.id && tab.status === "ready") {
    render(true);
    // An open square is redrawn from the new numbers rather than left
    // showing the old ones -- this is how a changed account size lands.
    if (tab.ui.zoom && String(tab.ui.zoom).startsWith("c-")) openZoom(tab, tab.ui.zoom);
  }
  // The year of IV history is rebuilt in the background on first sight
  // of a stock; ask again once it has had time to land.
  const h = tab.course?.iv_history?.status;
  if (h === "building" && attempt < 3) setTimeout(() => {
    if (state.tabs.includes(tab)) load(tab, attempt + 1);
  }, 8000);
  // Yahoo refuses in bursts, and a refusal says nothing about the stock.
  // Try twice more before leaving the explanation on the page.
  const refused = tab.courseState === "error" || /declined|did not load/.test(tab.course?.why || "");
  if (refused && attempt < 2) setTimeout(() => {
    if (state.tabs.includes(tab)) load(tab, attempt + 1);
  }, 15000);
}

/* ---- the pieces every number is drawn with -------------------------- */

const readsChip = (r) => (r ? `<span class="cg-reads r-${r}">${ARROW[r] || ""} ${esc(r)}</span>` : "");
const stanceChip = (s) => (s ? `<span class="cg-stance s-${s}">${esc(STANCE[s] || s)}</span>` : "");
const signOf = (v) => (v > 0 ? "+" + v : v < 0 ? "&minus;" + Math.abs(v) : "0");
/* Money with the sign before the dollar: -$42, never $-42. */
const cash = (v, d = 0) => (v === null || v === undefined ? "--"
  : (v < 0 ? "&minus;" : "") + money(Math.abs(v), d));

function scoreChip(m) {
  if (!m.weight) return "";
  const s = m.score || 0;
  return `<span class="cg-score ${s > 0 ? "pos" : s < 0 ? "neg" : ""}"
    title="score &times; weight = points toward the direction">${signOf(s)} &times; ${m.weight}
    = <b>${signOf(s * m.weight)}</b></span>`;
}

function tableOf(t) {
  if (!t?.rows?.length) return "";
  return `<table class="cg-table">${t.rows.map((r, i) => `
    <tr class="${i === t.hit ? "hit" : ""}${r.reads ? " t-" + r.reads : ""}">
      <td class="cg-when">${i === t.hit ? "&#9656; " : ""}${esc(r.when)}</td>
      <td>${esc(r.read)}</td></tr>`).join("")}</table>`;
}

function compareList(list) {
  if (!list?.length) return "";
  return `<dl class="cg-cmp">${list.map((c) => `
    <div class="${c.reads ? "t-" + c.reads : ""}"><dt>${esc(c.label)}</dt>
      <dd>${c.reads ? `<i class="cg-arrow">${ARROW[c.reads]}</i>` : ""}${calc(esc(c.show), c.working)}</dd></div>`).join("")}</dl>`;
}

/* The same comparisons, compact, for a square's face. */
function compact(list, n = 8) {
  if (!list?.length) return "";
  return `<dl class="ct-cmp">${list.slice(0, n).map((c) => `
    <div class="${c.reads ? "t-" + c.reads : ""}"><dt>${esc(c.label)}</dt>
      <dd>${c.reads ? ARROW[c.reads] + " " : ""}${esc(c.show)}</dd></div>`).join("")}</dl>`;
}

/* One block of a square's face. 0 is always shown; the higher the number,
 * the sooner it is dropped when the square is too small for everything. */
const blk = (pri, html, cls = "") => (html ? `<div class="ct-b ${cls}" data-pri="${pri}">${html}</div>` : "");

function lessonBlock(code, pri) {
  const L = LESSONS[code];
  return L ? blk(pri, `<p class="ct-why"><b>why it matters</b> ${esc(L.why)}</p>`) : "";
}

/* A number's face: every block it has, for the fit to choose from. */
function face(m) {
  if (!m.available) {
    return `<div class="ct-face off">
      ${blk(0, `<div class="ct-big">&ndash;</div>`)}
      ${blk(0, `<div class="ct-chips">${scoreChip(m)}<span class="cg-stance">not available</span></div>`)}
      ${blk(1, `<p class="ct-means">${esc(m.why)}</p>`)}
      ${blk(3, compact(m.compare))}
      ${blk(4, m.formula ? `<div class="ct-formula">${esc(m.formula)}</div>` : "")}
      ${lessonBlock(m.lesson, 5)}
    </div>`;
  }
  const t = m.against;
  const hit = t?.rows?.[t.hit];
  const others = (t?.rows || []).filter((_, i) => i !== t.hit);
  return `<div class="ct-face${m.reads ? " m-" + m.reads : ""}">
    ${blk(0, `<div class="ct-big">${calc(esc(m.show), m.working)}</div>`)}
    ${blk(0, `<div class="ct-chips">${readsChip(m.reads)}${stanceChip(m.stance)}${scoreChip(m)}</div>`)}
    ${blk(1, hit ? `<div class="ct-hit">&#9656; ${esc(hit.when)} &mdash; ${esc(hit.read)}</div>` : "")}
    ${blk(2, `<p class="ct-means">${esc(m.means)}</p>`)}
    ${blk(3, compact(m.compare))}
    ${blk(4, others.length ? `<div class="ct-rows">${others.map((r) =>
      `<div>${esc(r.when)} &mdash; ${esc(r.read)}</div>`).join("")}</div>` : "")}
    ${blk(5, m.formula ? `<div class="ct-formula">${esc(m.formula)}</div>` : "")}
    ${lessonBlock(m.lesson, 6)}
  </div>`;
}

const ready = (tab) => tab.course?.available;
const step = (tab, n) => tab.course.steps[String(n)];
const allMetrics = (tab) => ["1", "2"].flatMap((k) => (step(tab, k).sections || []).flatMap((s) => s.metrics));
const metricOf = (tab, id) => (ready(tab) ? allMetrics(tab).find((m) => m.id === id) : null);
const sectionOf = (tab, id) => ["1", "2"].flatMap((k) => step(tab, k).sections || [])
  .find((s) => s.metrics.some((m) => m.id === id));

/* The step each square belongs to, for the title's number. */
const STEP_OF = {};
const title = (tab, id, n, text) => `<span class="ct-step">${n}</span> ${esc(text)}`;

/* ---- inside an opened square --------------------------------------- */

const QUESTION = {
  1: "Find: which stocks are worth analysing, and is this a place to buy or sell premium?",
  2: "Direction: which way, how confident, over what time, to what target -- and where am I wrong?",
  3: "Build: what exact structure, expiration and strikes express the view?",
  4: "Size: how much, when do I get out, and how will I know I was right?",
};

function guide(code) {
  const L = LESSONS[code];
  if (!L) return "";
  return `<div class="cz-guide">
    <div><span>what it is</span>${esc(L.what)}</div>
    <div><span>why use it</span>${esc(L.why)}</div>
    <div><span>when</span>${esc(L.when)}</div></div>`;
}

/* What this step hands to the next one -- the chain the curriculum is. */
function handsOn(tab, n) {
  const k = String(n)[0];
  if (k === "1") {
    const o = step(tab, 1).output;
    return `<b>Step 1 gives Step 2:</b> ${o.liquid ? "liquid" : "fails the liquidity gate"} (spread ${pct(o.spread_pct, 1)})
      &middot; ${esc(o.stance)} [by ${esc(o.iv_column.by)}] &middot; expected move &plusmn;${money(o.expected_move)}
      (${pct(o.expected_pct, 1)})${o.earnings ? ` &middot; earnings ${esc(o.earnings.date)}${o.earnings.inside ? " inside the window" : ""}` : ""}`;
  }
  if (k === "2") return `<b>Step 2 gives Step 3:</b> ${esc(step(tab, 2).output.sentence)}`;
  if (k === "3") return `<b>Step 3 gives Step 4:</b> ${esc(step(tab, 3).name)}${step(tab, 3).expiry
    ? `, ${esc(step(tab, 3).expiry)}, most it can lose ${cash(step(tab, 3).payoff?.max_loss)}` : ""}.`;
  return `<b>The thesis:</b> ${esc(step(tab, 4).thesis || step(tab, 3).summary || "")}`;
}

/* The other numbers from the same lesson, each a door into its own square. */
function siblings(tab, id) {
  const sec = sectionOf(tab, id);
  if (!sec) return "";
  const rest = sec.metrics.filter((m) => m.id !== id);
  if (!rest.length) return "";
  return `<h5 class="cg-sumhead">the rest of ${esc(sec.lesson)} &mdash; ${esc(sec.title)}</h5>
    <div class="cz-sibs">${rest.map((m) => `<button class="cz-sib${m.reads ? " t-" + m.reads : ""}" data-cg-zoom="c-${m.id}">
      <span>${esc(m.label)}</span><b>${m.available ? esc(m.show) : "&ndash;"}</b>
      ${m.reads ? `<i>${ARROW[m.reads]} ${esc(m.reads)}</i>` : m.stance ? `<i>${esc(STANCE[m.stance] || m.stance)}</i>` : ""}</button>`).join("")}</div>`;
}

function opened(tab, n, code, left, right, id) {
  return `<div class="cg-zoom">
    <p class="cg-context"><b>Step ${String(n)[0]}.</b> ${esc(QUESTION[String(n)[0]])}</p>
    <div class="cz-cols"><div class="cz-left">${left}${guide(code)}</div><div class="cz-right">${right}</div></div>
    ${id ? siblings(tab, id) : ""}
    <div class="cg-output">${handsOn(tab, n)}</div>
  </div>`;
}

function metricDetail(tab, m, n) {
  const left = `<div class="cz-top"><span class="cg-lesson">${esc(m.lesson)}</span>${readsChip(m.reads)}${stanceChip(m.stance)}${scoreChip(m)}</div>
    <div class="cz-big${m.reads ? " m-" + m.reads : ""}">${m.available ? calc(esc(m.show), m.working) : "&ndash;"}</div>
    <p class="cz-means">${esc(m.available ? m.means : m.why)}</p>
    ${m.formula ? `<div class="cz-formula">${esc(m.formula)}</div>` : ""}
    ${m.source ? `<div class="cg-src">${esc(m.source)}</div>` : ""}`;
  const right = `${m.against ? `<h5 class="cg-sumhead">the curriculum's table</h5>${tableOf(m.against)}` : ""}
    ${m.compare?.length ? `<h5 class="cg-sumhead">compared with</h5>${compareList(m.compare)}` : ""}
    ${m.working ? `<h5 class="cg-sumhead">the sum</h5>${wcalc(m.working)}` : ""}`;
  return opened(tab, n, m.lesson, left, right, m.id);
}

/* ---- the squares ----------------------------------------------------- *
 *
 * Sizes differ on purpose: the numbers that decide the trade -- IV Rank,
 * the expected move, trend, levels, the scorecard, the payoff -- get the
 * room. The spans are chosen so each step's rows fill at five columns in
 * reading order.
 */

const SIZES = {
  spread: "w1 h2", oi: "w1 h2", vol_oi: "w1 h2", iv_rank: "w2 h2",
  iv_pct: "w1 h2", hv20: "w1 h2", iv_hv: "w1 h2", em_model: "w2 h2",
  em_market: "w2 h2", daily_move: "w1 h2", earnings_date: "w2 h2",
  market_events: "w2 h2", unusual: "w1 h2", pc_screen: "w2 h2",
  trend: "w2 h2", levels: "w2 h2", pattern: "w1 h2",
  catalyst: "w2 h2", fundamentals: "w1 h2", rs: "w2 h2",
  rsi: "w2 h2", pc: "w1 h2", skew: "w2 h2",
};

function metricTile(id, n) {
  STEP_OF["c-" + id] = n;
  panel("steps", "c-" + id, `Step ${n}: one of the curriculum's numbers, "${id}"`, (d, tab) => {
    const m = metricOf(tab, id);
    if (!m) return waitingTile(tab, "c-" + id);
    return tile("c-" + id, "e-derived ct", SIZES[id] || "w1 h2", title(tab, id, m.lesson, m.label), face(m));
  });
  DETAIL["c-" + id] = (d, tab) => {
    const m = metricOf(tab, id);
    return m ? metricDetail(tab, m, n) : "";
  };
}

/* While the four steps are still being worked out, one wide square says
 * so, in the place the first of them will go. */
function waitingTile(tab, id) {
  const first = layoutOf("steps")[0];
  if (id !== first) return "";
  const c = tab.course;
  const msg = tab.courseState === "error" ? `Could not run the four steps: ${esc(tab.courseError)}`
    : c && !c.available ? `The four steps could not run on ${esc(tab.symbol)}: ${esc(c.why)}`
    : `Working through the four steps on <b>${esc(tab.symbol)}</b>&hellip;`;
  return tile(first, "e-derived ct", "w4 h1", "The four steps", `<div class="cg-wait">${msg}</div>`);
}

["spread", "oi", "vol_oi", "iv_rank", "iv_pct", "hv20", "iv_hv", "em_model", "em_market",
 "daily_move", "earnings_date", "market_events", "unusual", "pc_screen"].forEach((id) => metricTile(id, 1));
["trend", "levels", "pattern", "catalyst", "fundamentals", "rs", "rsi", "pc", "skew"]
  .forEach((id) => metricTile(id, 2));

/* A square that is not one number from a table, built the same way:
 * `faceOf` returns its blocks, `detailOf` returns [left, right]. */
function square(id, n, what, span, name, faceOf, detailOf) {
  STEP_OF[id] = n;
  panel("steps", id, what, (d, tab) => {
    if (!ready(tab)) return waitingTile(tab, id);
    const body = faceOf(tab);
    return body ? tile(id, "e-derived ct", span, title(tab, id, n, name(tab)),
      `<div class="ct-face">${body}${body.includes("ct-fixed") ? "" : lessonBlock(String(n), 9)}</div>`) : "";
  });
  DETAIL[id] = (d, tab) => {
    if (!ready(tab)) return "";
    const [left, right] = detailOf(tab);
    return opened(tab, n, String(n), left, right, null);
  };
}

/* ---- step 2: the news beside the scorecard, and the scorecard -------- */

const leaning = (tab) => (tab.data?.news?.articles || []).filter((a) => a.lean);
const byMoving = (items) => items.slice().sort((a, b) => (b.moving?.score || 0) - (a.moving?.score || 0));

function newsList(items) {
  return items.map((a) => `<div class="cg-art t-${a.lean.reads}">
    ${readsChip(a.lean.reads)}${a.lean.mixed ? `<span class="cg-mixed">mixed</span>` : ""}
    <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title || "untitled")}</a>
    <span class="cg-words">${(a.lean.words || []).map(esc).join(" &middot; ") || "no telling words"}</span>
    <span class="cg-src">${esc(a.publisher || "")} &middot; ${esc(ago(a.published) || "undated")}</span>
  </div>`).join("");
}

function newsCounts(items) {
  const n = { bullish: 0, bearish: 0, neutral: 0 };
  items.forEach((a) => { n[a.lean.reads] += 1; });
  return n;
}

square("c-news", "2", "Step 2: the news, tagged bullish or bearish with the words why -- shown, never scored", "w3 h3",
  () => "The news, beside the scorecard",
  (tab) => {
    const items = leaning(tab);
    if (!items.length) return "";
    const n = newsCounts(items);
    const top = byMoving(items);
    return blk(0, `<div class="ct-big ct-split"><b class="t-bullish">${ARROW.bullish} ${n.bullish}</b>
        <b class="t-bearish">${ARROW.bearish} ${n.bearish}</b><b>${ARROW.neutral} ${n.neutral}</b></div>`)
      + blk(0, `<div class="ct-chips"><span class="cg-stance">not scored</span></div>`)
      + top.slice(0, 12).map((a, i) => blk(i < 3 ? 1 : 2 + Math.floor(i / 3),
          `<div class="ct-line t-${a.lean.reads}">${ARROW[a.lean.reads]} ${esc(a.title || "")}
            <i>${(a.lean.words || []).map(esc).join(" &middot; ")}</i></div>`)).join("");
  },
  (tab) => {
    const items = leaning(tab);
    const n = newsCounts(items);
    return [`<div class="cz-big ct-split"><b class="t-bullish">${ARROW.bullish} ${n.bullish}</b>
        <b class="t-bearish">${ARROW.bearish} ${n.bearish}</b><b>${ARROW.neutral} ${n.neutral}</b></div>
      <p class="cz-means">${items.length} articles. Tagged from the words in the headline, which cannot read an
        article, so it adds no points &mdash; it is here to agree or disagree with the scorecard, and each tag says
        which words decided it.</p>`, newsList(byMoving(items))];
  });

function scorecardBlock(card) {
  return `<table class="cg-table cg-scores">
      <tr class="th"><td>signal</td><td>score</td><td>weight</td><td>points</td></tr>
      ${card.rows.map((r) => `<tr class="${r.points > 0 ? "t-bullish" : r.points < 0 ? "t-bearish" : ""}${r.available ? "" : " off"}">
        <td><span class="cg-lesson">${esc(r.lesson)}</span> ${esc(r.label)}${r.available ? "" : " <i>(not available)</i>"}</td>
        <td>${signOf(r.score)}</td><td>${r.weight}</td><td><b>${signOf(r.points)}</b></td></tr>`).join("")}
      <tr class="total"><td>direction score</td><td></td><td>${card.max}</td><td><b>${signOf(card.total)}</b></td></tr>
    </table>`;
}

const convictionTable = (card) => tableOf({ rows: [
  { when: "0.60 or more", read: "Strong -- can use more directional delta" },
  { when: "0.30 to 0.59", read: "Moderate -- spreads, defined risk" },
  { when: "under 0.30", read: "Weak -- no directional trade, or a neutral strategy" }],
  hit: card.conviction >= 0.6 ? 0 : card.conviction >= 0.3 ? 1 : 2 });

const meter = (card) => {
  const pos = Math.max(-1, Math.min(1, card.total / card.max));
  return `<div class="cg-meter" title="Direction score, -15 to +15">
    <div class="cg-meter-bar"><i style="left:${50 + pos * 50}%"></i></div>
    <div class="cg-meter-lab"><span>&minus;15 bearish</span><span>bullish +15</span></div></div>`;
};

const verdictKV = (v) => `<dl class="cg-kv">
    ${v.target ? `<div><dt>target</dt><dd>${money(v.target)}</dd></div>`
      : `<div><dt>range</dt><dd>${money(v.support)} &ndash; ${money(v.resistance)}</dd></div>`}
    <div><dt>wrong on</dt><dd>${v.invalidation ? money(v.invalidation) : "leaving the range"}</dd></div>
    ${v.timeframe ? `<div><dt>timeframe</dt><dd>${v.timeframe.low}&ndash;${v.timeframe.high} days</dd></div>` : ""}
  </dl>`;

square("c-scorecard", "2.10", "Step 2's verdict: the weighted scorecard, direction, target and where you are wrong", "w2 h3",
  () => "The scorecard, and the verdict",
  (tab) => {
    const s = step(tab, 2), c = s.scorecard, v = s.output;
    return blk(0, `<div class="ct-big m-${v.direction}">${calc(signOf(c.total) + " / " + c.max, c.working)}</div>`)
      + blk(0, `<div class="ct-chips">${readsChip(v.direction)}<span class="cg-stance">${esc(c.label)} conviction</span></div>`)
      + blk(1, meter(c)) + blk(1, verdictKV(v))
      + blk(2, `<div class="ct-rows">${c.rows.map((r) => `<div class="${r.points > 0 ? "t-bullish" : r.points < 0 ? "t-bearish" : ""}">
          ${esc(r.lesson)} ${esc(r.label.split(" (")[0])} <b>${signOf(r.points)}</b></div>`).join("")}</div>`)
      + blk(3, `<p class="ct-means">${esc(s.output.sentence)}</p>`);
  },
  (tab) => {
    const s = step(tab, 2), c = s.scorecard, v = s.output;
    return [`<div class="cz-top">${readsChip(v.direction)}<span class="cg-stance">${esc(c.label)} conviction</span></div>
        <div class="cz-big m-${v.direction}">${calc(signOf(c.total) + " / " + c.max, c.working)}</div>
        ${meter(c)}${verdictKV(v)}
        <p class="cz-means">Conviction ${calc(nf(c.conviction, 2), c.working)} of 1 &rarr; <b>${esc(c.label)}</b>: ${esc(c.feeds)}.
          ${c.missing ? `${c.missing} signal${c.missing > 1 ? "s" : ""} could not be read and score zero, which pulls conviction down rather than guessing.` : ""}
          ${c.tempered ? ` Tempered from strong: ${esc(c.tempered)}, so defined risk.` : ""}</p>`,
      `<h5 class="cg-sumhead">the scorecard</h5>${scorecardBlock(c)}<h5 class="cg-sumhead">conviction</h5>${convictionTable(c)}`];
  });

/* ---- step 3 ---------------------------------------------------------- */

const s3 = (tab) => step(tab, 3);
const hasTrade = (tab) => !!s3(tab).legs?.length;

function matrixBlock(m, small = false) {
  const cols = [["low", small ? "low IV" : "Low IV (IVR < 30)"], ["mid", small ? "mid" : "Mid IV (30-50)"],
                ["high", small ? "high" : "High IV (IVR > 50)"]];
  return `<table class="cg-table cg-matrix${small ? " small" : ""}">
    <tr class="th"><td></td>${cols.map(([k, l]) => `<td class="${k === m.column ? "col" : ""}">${l}</td>`).join("")}</tr>
    ${m.rows.map((r) => `<tr class="${r.key === m.row ? "row" : ""}"><td>${esc(r.label)}</td>${cols.map(([k]) =>
      `<td class="${r.key === m.row && k === m.column ? "hit" : k === m.column ? "col" : ""}">${esc(r.cells[k])}</td>`).join("")}</tr>`).join("")}
  </table>`;
}

square("c-matrix", "3.1", "Step 3: the strategy matrix, with the cell this stock lands in lit", "w3 h2",
  () => "Strategy, from the matrix",
  (tab) => {
    const m = s3(tab).matrix, row = m.rows.find((r) => r.key === m.row);
    const col = { low: "low IV", mid: "mid IV", high: "high IV" }[m.column];
    return blk(0, `<div class="ct-big">${esc(s3(tab).name)}</div>`)
      + blk(0, `<div class="ct-line"><b>${esc(row?.label || "")}</b> &times; <b>${col}</b> &rarr; ${esc(row?.cells?.[m.column] || "")}</div>`)
      + blk(1, matrixBlock(m, true))
      + blk(2, `<p class="ct-means">IV column by ${esc(m.by || "IV Rank")}. ${esc(s3(tab).why || "")}</p>`);
  },
  (tab) => [`<div class="cz-big">${esc(s3(tab).name)}</div>
      <p class="cz-means">IV column chosen by ${esc(s3(tab).matrix.by || "IV Rank")}. ${esc(s3(tab).why || "")}</p>
      ${hasTrade(tab) ? "" : `<p class="cz-means">${esc(s3(tab).summary || "")}</p>`}`,
    `<h5 class="cg-sumhead">direction &times; conviction &times; IV</h5>${matrixBlock(s3(tab).matrix)}`]);

square("c-expiry", "3.3", "Step 3: the expiration, from the catalyst and the timeframe", "w2 h2",
  () => "Expiration",
  (tab) => {
    if (!hasTrade(tab)) return "";
    const ex = s3(tab).expiration;
    return blk(0, `<div class="ct-big">${esc(s3(tab).expiry)}</div>`)
      + blk(0, `<div class="ct-chips"><span class="cg-stance">${s3(tab).dte} days</span><span class="cg-stance">needs ${ex.need}</span></div>`)
      + blk(1, compact(ex.parts.map(([l, v]) => ({ label: l, show: `${v} days` }))))
      + blk(3, `<p class="ct-means">${esc(ex.rule)}</p>`);
  },
  (tab) => {
    const ex = s3(tab).expiration;
    return [`<div class="cz-big">${esc(s3(tab).expiry)}</div><p class="cz-means">${s3(tab).dte} days out. ${esc(ex.rule)}</p>`,
      `<h5 class="cg-sumhead">the rules it has to satisfy</h5><dl class="cg-cmp">${ex.parts.map(([l, v]) =>
        `<div><dt>${esc(l)}</dt><dd>${v} days</dd></div>`).join("")}
        <div class="t-bullish"><dt>needs at least</dt><dd><b>${ex.need} days</b> &rarr; first listed: ${esc(s3(tab).expiry)}</dd></div></dl>`];
  });

function legsTable(tab) {
  return `<table class="cg-table cg-legs"><tr class="th"><td>leg</td><td>mid</td><td>bid / ask</td><td>delta</td><td>open int.</td></tr>
    ${s3(tab).legs.map((l) => `<tr class="${l.side === "long" ? "t-bullish" : "t-bearish"}"><td><b>${esc(l.side)}</b> $${nf(l.strike, 2)} ${esc(l.kind)}</td>
      <td>${money(l.entry)}</td><td>${money(l.bid)} / ${money(l.ask)}</td><td>${nf(l.delta, 2)}</td><td>${(l.oi || 0).toLocaleString()}</td></tr>`).join("")}
  </table>`;
}

square("c-strikes", "3.4", "Step 3: the strikes, from the Step 2 target and delta", "w2 h3",
  () => "Strikes",
  (tab) => (hasTrade(tab)
    ? s3(tab).legs.map((l) => blk(0, `<div class="ct-leg ${l.side === "long" ? "t-bullish" : "t-bearish"}"><b>${esc(l.side)}</b>
        $${nf(l.strike, 2)} ${esc(l.kind)} <span>@ ${money(l.entry)}</span> <i>&Delta; ${nf(l.delta, 2)} &middot; OI ${(l.oi || 0).toLocaleString()}</i></div>`)).join("")
      + (s3(tab).strike_why || []).map((w, i) => blk(1 + i, `<p class="ct-means">${esc(w)}</p>`)).join("")
    : ""),
  (tab) => [`<div class="cz-big">${s3(tab).legs.map((l) => `$${nf(l.strike, 2)}`).join(" / ")}</div>
      <ul class="cg-why">${(s3(tab).strike_why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`,
    `<h5 class="cg-sumhead">the legs, at today's quotes</h5>${legsTable(tab)}`]);

const dollars = (v) => (v === null || v === undefined ? "unlimited" : money(Math.abs(v), 0));

function bigNumbers(p) {
  return `<div class="cg-big3">
    <div><span>${p.debit ? "you pay" : "you collect"}</span><b>${money(Math.abs(p.net_cost || 0), 0)}</b></div>
    <div class="pos"><span>most you can make</span><b>${p.max_profit_unbounded ? "unlimited" : dollars(p.max_profit)}</b></div>
    <div class="neg"><span>most you can lose</span><b>${p.max_loss_unbounded ? "unlimited" : dollars(p.max_loss)}</b></div>
    <div><span>break-even</span><b>${(p.breakevens || []).map((b) => money(b)).join(" / ") || "--"}</b></div>
    ${p.reward_risk ? `<div><span>reward / risk</span><b>${nf(p.reward_risk, 2)}</b></div>` : ""}
  </div>`;
}

function payoffDrawing(tab, w, h) {
  const t = s3(tab), p = t.payoff;
  if (!p?.curve?.length || !window.QUIPU_PAYOFF) return "";
  return window.QUIPU_PAYOFF.payoffSvg({
    curve: p.curve, legs: t.legs, spot: t.spot, breakevens: p.breakevens,
    maxProfit: p.max_profit, maxLoss: p.max_loss, bestAt: p.best_at, worstAt: p.worst_at,
    unboundedUp: p.max_profit_unbounded, unboundedDown: p.max_loss_unbounded, width: w, height: h,
  });
}

function equations(tab) {
  const f = s3(tab).formulas;
  return f ? `<dl class="cg-cmp cg-eq">${f.rows.map(([l, v, w]) => `<div><dt>${esc(l)}</dt><dd>${
    calc(l === "Reward/risk" ? nf(v, 2) : l === "Breakeven" ? money(v)
      : money(v) + (v === null || v === undefined ? "" : ` <i>(${money(v * 100, 0)} a contract)</i>`), w)}</dd></div>`).join("")}</dl>` : "";
}

/* The payoff square is drawn, not fitted: the numbers across the top and
 * the diagram taking every pixel left beneath them. */
square("c-payoff", "3.2", "Step 3: the payoff -- what you pay, the most you can make and lose, the break-even", "w3 h3",
  (tab) => `Payoff: ${s3(tab).name}`,
  (tab) => (hasTrade(tab) ? `<div class="ct-fixed">${bigNumbers(s3(tab).payoff)}
      <div class="ct-payoff">${payoffDrawing(tab, 760, 250)}</div></div>` : ""),
  (tab) => [`${bigNumbers(s3(tab).payoff)}<h5 class="cg-sumhead">3.2, by the curriculum's equations</h5>${equations(tab)}`,
    `<div class="cg-payoff">${payoffDrawing(tab, 900, 360)}</div>`]);

square("c-odds", "3.5", "Step 3: the odds -- probability of profit, touching the target, expected value", "w2 h2",
  () => "The odds",
  (tab) => {
    if (!hasTrade(tab)) return "";
    const pr = s3(tab).probability, p = s3(tab).payoff;
    const pop = pr.breakevens.find((b) => b.profit) || pr.breakevens[0];
    return blk(0, `<div class="ct-big">${pop ? calc(pct(pop.value, 1), pop.working) : "--"}</div>`)
      + blk(0, `<div class="ct-chips"><span class="cg-stance">probability of profit</span></div>`)
      + blk(1, `<div class="ct-line">${esc(pop?.label || "")}</div>`)
      + blk(2, pr.touch ? `<div class="ct-line">touches ${money(pr.touch.target)}: ${pct(pr.touch.touch, 0)}, finishes past it: ${pct(pr.touch.finish, 0)}</div>` : "")
      + blk(2, pr.ev ? `<div class="ct-line">expected value, no edge: ${cash(pr.ev.ev)}</div>` : "")
      + blk(3, `<div class="ct-line">the engine's own figure: ${pct(p.chance, 1)}</div>`)
      + blk(4, `<p class="ct-means">Risk-neutral odds assume no edge; Step 2 is what is supposed to tilt them.</p>`);
  },
  (tab) => {
    const pr = s3(tab).probability, p = s3(tab).payoff;
    const pop = pr.breakevens.find((b) => b.profit) || pr.breakevens[0];
    return [`<div class="cz-big">${pop ? calc(pct(pop.value, 1), pop.working) : "--"}</div>
      <p class="cz-means">${esc(pop?.label || "")}. The model's odds are risk-neutral: they assume you know nothing the
        market does not. A probability near a coin flip with a 2:1 payoff is fair on no edge &mdash; Step 2 is what is
        supposed to tilt it.</p>`,
      `<h5 class="cg-sumhead">every probability</h5><dl class="cg-cmp">
      ${pr.breakevens.map((b) => `<div class="${b.profit ? "t-bullish" : ""}"><dt>${b.profit ? "<b>probability of profit</b>: " : ""}${esc(b.label)}</dt>
        <dd>${calc(pct(b.value, 1), b.working)}</dd></div>`).join("")}
      <div><dt>the engine's probability of profit</dt><dd>${calc(pct(p.chance, 1), p.chance_working)}</dd></div>
      ${pr.touch ? `<div><dt>touches ${money(pr.touch.target)} before expiry / finishes past it</dt>
        <dd>${calc(pct(pr.touch.touch, 0), pr.touch.working)} / ${pct(pr.touch.finish, 0)}</dd></div>` : ""}
      ${pr.ev ? `<div><dt>expected value, no edge assumed</dt><dd>${calc(cash(pr.ev.ev), pr.ev.working)}</dd></div>` : ""}
    </dl>${pr.ev ? `<h5 class="cg-sumhead">the expected value, worked</h5>${wcalc(pr.ev.working)}` : ""}`];
  });

function greeksTable(tab) {
  const g = s3(tab).greeks;
  return `<table class="cg-table cg-greeks"><tr class="th"><td>per share</td><td>delta</td><td>theta / day</td><td>vega / IV pt</td></tr>
    ${g.legs.map((x) => `<tr><td>${esc(x.leg)}</td><td>${nf(x.delta, 3)}</td><td>${nf(x.theta, 3)}</td><td>${nf(x.vega, 3)}</td></tr>`).join("")}
    <tr class="total"><td>net</td><td><b>${nf(g.net.delta, 3)}</b></td><td><b>${nf(g.net.theta, 3)}</b></td><td><b>${nf(g.net.vega, 3)}</b></td></tr>
  </table>`;
}

function greeksWords(tab) {
  const t = s3(tab), g = t.greeks;
  return `Net delta ${nf(g.net.delta, 2)} is about ${nf(Math.abs(g.net.delta * 100), 0)} shares of
    ${g.net.delta >= 0 ? "bullish" : "bearish"} exposure a contract. Time ${g.net.theta >= 0 ? "pays you" : "costs you"}
    ${money(Math.abs(g.net.theta * 100))} a day; a one-point IV move is ${money(Math.abs(g.net.vega * 100))}.
    ${g.naked && t.legs.length > 1 ? `The ${esc(g.naked.leg)} alone would cost ${money(Math.abs(g.naked.theta * 100))}/day in time and
      ${money(Math.abs(g.naked.vega * 100))} per IV point &mdash; what the other leg buys you.` : ""}`;
}

square("c-greeks", "3.5", "Step 3: the position greeks, and what the second leg buys you", "w3 h2",
  () => "Greeks, net",
  (tab) => {
    if (!hasTrade(tab)) return "";
    const g = s3(tab).greeks;
    const sh = g.net.delta === null || g.net.delta === undefined ? "--" : nf(g.net.delta * 100, 0);
    return blk(0, `<div class="ct-big">${sh} <i class="ct-unit">shares a contract</i></div>`)
      + blk(0, `<div class="ct-chips">${readsChip(g.net.delta > 0 ? "bullish" : g.net.delta < 0 ? "bearish" : "neutral")}</div>`)
      + blk(1, `<div class="ct-line">time ${cash(g.net.theta * 100, 2)} a day &middot; IV +1 point ${cash(g.net.vega * 100, 2)}</div>`)
      + blk(2, greeksTable(tab))
      + blk(3, `<p class="ct-means">${greeksWords(tab)}</p>`);
  },
  (tab) => {
    const g = s3(tab).greeks;
    const sh = g.net.delta === null || g.net.delta === undefined ? "--" : nf(g.net.delta * 100, 0);
    return [`<div class="cz-big">${sh} <i class="ct-unit">shares a contract</i></div><p class="cz-means">${greeksWords(tab)}</p>`,
      `<h5 class="cg-sumhead">per leg, and net</h5>${greeksTable(tab)}`];
  });

/* ---- step 4 ---------------------------------------------------------- */

const s4 = (tab) => step(tab, 4);

square("c-size", "4.1", "Step 4: how many contracts, from your account and risk per trade", "w2 h2",
  () => "How many contracts",
  (tab) => {
    if (!s4(tab).available) return "";
    const z = s4(tab).sizing;
    return blk(0, `<div class="ct-big${z.contracts === 0 ? " m-bearish" : ""}">${z.contracts === undefined ? "--"
        : calc(String(z.contracts), z.working)} <i class="ct-unit">contracts</i></div>`)
      + blk(1, z.contracts !== undefined ? `<div class="ct-line">allowed at risk ${money(z.budget, 0)} &middot; one contract ${money(z.max_loss, 0)}</div>`
        : `<p class="ct-means">${esc(z.why || "")}</p>`)
      + blk(1, z.note ? `<p class="ct-means">${esc(z.note)}</p>` : "")
      + blk(2, `<div class="ct-line">account ${z.account ? money(z.account, 0) : "not set"} &middot; risk ${pct(z.risk_pct, 1)} a trade</div>`)
      + blk(3, compact(s4(tab).recovery.map((r) => ({ label: `a ${r.loss}% drawdown needs`, show: pct(r.gain, 1) }))))
      + blk(2, `<p class="ct-means">Click to set your account and risk.</p>`);
  },
  (tab) => {
    const s = s4(tab), z = s.sizing;
    return [`<div class="cg-inputs">
        <label>account <input data-cg-account value="${z.account ?? ""}" placeholder="e.g. 25000" inputmode="decimal"></label>
        <label>risk per trade % <input data-cg-risk value="${z.risk_pct}" inputmode="decimal"></label></div>
      <p class="cg-context">Kept on this machine only; changing either reworks the steps.</p>
      ${z.contracts !== undefined ? `<div class="cg-big3">
          <div><span>dollars at risk allowed</span><b>${money(z.budget, 0)}</b></div>
          <div><span>most one contract loses</span><b>${money(z.max_loss, 0)}</b></div>
          <div class="${z.contracts ? "pos" : "neg"}"><span>contracts</span><b>${calc(String(z.contracts), z.working)}</b></div>
          <div><span>actual risk</span><b>${z.contracts ? pct(z.actual_pct, 2) : "none placed"}</b></div></div>
        ${z.note ? `<p class="cz-means down">${esc(z.note)}</p>` : ""}` : `<p class="cz-means">${esc(z.why || "")}</p>`}`,
      `<h5 class="cg-sumhead">how much of the account per trade</h5>${tableOf(z.table)}
      ${z.working ? `<h5 class="cg-sumhead">the sum</h5>${wcalc(z.working)}` : ""}
      <h5 class="cg-sumhead">why small percentages</h5>
      <dl class="cg-cmp">${s.recovery.map((r) => `<div><dt>a ${r.loss}% drawdown needs</dt><dd>${pct(r.gain, 1)} to get back</dd></div>`).join("")}</dl>
      <p class="cg-context">Kelly sizing needs 50+ journaled trades to estimate, so it is not offered here.</p>`];
  });

square("c-exposure", "4.2", "Step 4: beta-weighted delta, the trade's share of market exposure", "w1 h2",
  () => "Market exposure",
  (tab) => {
    const b = s4(tab).available && s4(tab).beta_weighted;
    return b ? blk(0, `<div class="ct-big">${calc(nf(b.value, 1), b.working)}</div>`)
      + blk(0, `<div class="ct-chips"><span class="cg-stance">SPY shares</span></div>`)
      + blk(1, `<p class="ct-means">Beta-weighted delta: add it across every open trade to see your real market exposure.</p>`) : "";
  },
  (tab) => [`<div class="cz-big">${calc(nf(s4(tab).beta_weighted.value, 1), s4(tab).beta_weighted.working)} <i class="ct-unit">SPY shares</i></div>
      <p class="cz-means">Several bullish trades on high-beta stocks are one big bet on the market; this is how big a share of it this one is.</p>`,
    `<h5 class="cg-sumhead">the sum</h5>${wcalc(s4(tab).beta_weighted.working)}`]);

square("c-exits", "4.3", "Step 4: the exits, written before entry -- price stop, premium stop, target, time", "w2 h2",
  () => "The exits",
  (tab) => {
    if (!s4(tab).available) return "";
    const s = s4(tab);
    return s.stops.map((x, i) => blk(x.kind === "reference" ? 3 : 0,
        `<div class="ct-exit x-${x.kind}"><b>${x.kind === "reference" ? "at the stop" : esc(x.kind) + " stop"}</b> ${esc(x.label)}</div>`)).join("")
      + blk(0, `<div class="ct-exit x-target"><b>target</b> ${esc(s.target.label)}</div>`)
      + blk(0, `<div class="ct-exit x-time"><b>time</b> ${esc(s.time_exit.label)}, by ${esc(s.time_exit.on)}</div>`)
      + blk(4, s.assignment ? `<div class="ct-exit x-assign"><b>assignment</b> ${esc(s.assignment)}</div>` : "");
  },
  (tab) => {
    const s = s4(tab);
    return [`<p class="cz-means">Every exit is written before entry, from numbers the earlier steps already produced &mdash;
        the invalidation from Step 2, the max loss from Step 3.</p>`,
      `<ul class="cg-exits">
      ${s.stops.map((x) => `<li class="x-${x.kind}"><b>${x.kind === "reference" ? "for reference" : x.kind + " stop"}</b>
        ${calc(esc(x.label), x.working)}<span>${esc(x.detail || "")}</span></li>`).join("")}
      <li class="x-target"><b>profit target</b> ${calc(esc(s.target.label), s.target.working)}<span>${esc(s.target.detail)}</span></li>
      <li class="x-time"><b>time exit</b> ${esc(s.time_exit.label)}, by <b>${esc(s.time_exit.on)}</b></li>
      ${s.assignment ? `<li class="x-assign"><b>assignment</b> ${esc(s.assignment)}</li>` : ""}
    </ul>`];
  });

square("c-thesis", "4", "Step 4: the one-sentence thesis, and the button that places it in the Workshop", "w5 h2",
  () => "The thesis",
  (tab) => {
    const text = s4(tab).available ? s4(tab).thesis : s3(tab).summary;
    return blk(0, `<p class="ct-thesis">${esc(text || "")}</p>`)
      + blk(0, hasTrade(tab) ? `<button class="cg-open" data-cg-open="1">Open this trade in the Workshop</button>` : "")
      + blk(3, `<p class="ct-means">An educational framework, not advice. The rules of thumb are practitioners' conventions,
          not laws; the model's odds assume no edge.</p>`);
  },
  (tab) => [`<div class="cg-output"><b>The one-sentence thesis:</b> ${esc(s4(tab).available ? s4(tab).thesis : s3(tab).summary)}</div>
      ${hasTrade(tab) ? `<button class="cg-open" data-cg-open="1">Open this trade in the Workshop</button>` : ""}`,
    `<p class="cz-means">If you cannot write that sentence with real numbers, one of the four steps is incomplete.</p>
      <p class="cg-disclaimer">An educational framework, not advice. The rules of thumb are practitioners' conventions,
        not laws; the model's odds assume no edge.</p>`]);

/* ---- filling each square ----------------------------------------------- */

const MIN_SCALE = 0.85, MAX_SCALE = 2.6;

/* Fit every square at once: drop what cannot fit at the smallest readable
 * size, least important first, then grow the type until each is full.
 *
 * Done for all squares together rather than one after another -- every
 * guess is written to all of them, then all of them are measured -- so
 * the page is laid out once per round (about fifteen) rather than once
 * per square per guess (about three hundred and fifty), which took three
 * seconds a search. */
function fitSquares(tiles) {
  const S = tiles.map((t) => {
    const body = t.querySelector(":scope > .body");
    const face = body?.querySelector(".ct-face");
    if (!face) return null;
    const blocks = [...face.querySelectorAll(":scope > .ct-b")];
    blocks.forEach((b) => { b.hidden = false; });
    const ranks = [...new Set(blocks.map((b) => Number(b.dataset.pri)))].filter((p) => p > 0).sort((a, b) => b - a);
    return { body, face, blocks, ranks, lo: MIN_SCALE, hi: MAX_SCALE, done: false };
  }).filter(Boolean);
  const set = (x, v) => x.face.style.setProperty("--s", v);
  const fits = (x) => x.face.scrollHeight <= x.body.clientHeight + 1 && x.face.scrollWidth <= x.body.clientWidth + 1;

  // Everything at the largest size: any square that holds it all is done.
  S.forEach((x) => set(x, MAX_SCALE));
  S.forEach((x) => { if (fits(x)) { x.done = true; x.lo = MAX_SCALE; } });

  // At the smallest size, drop a rank from every square still too full.
  let open = S.filter((x) => !x.done);
  for (let round = 0; round < 10 && open.length; round++) {
    open.forEach((x) => set(x, MIN_SCALE));
    open = open.filter((x) => !fits(x));
    open.forEach((x) => {
      const p = x.ranks.shift();
      if (p === undefined) { x.done = true; return; }          // nothing left to drop
      x.blocks.filter((b) => Number(b.dataset.pri) === p).forEach((b) => { b.hidden = true; });
    });
    open = open.filter((x) => !x.done);
  }

  // Dropping in rank order can throw away more than it had to: the matrix
  // had to lose its table, but the two short lines dropped on the way would
  // have fitted once the table was gone. So put back whatever now fits,
  // most important first.
  const back = S.map((x) => ({ x, q: x.blocks.filter((b) => b.hidden)
    .sort((a, b) => Number(a.dataset.pri) - Number(b.dataset.pri)) })).filter((r) => r.q.length);
  for (let round = 0; round < 16 && back.some((r) => r.q.length); round++) {
    const tried = back.filter((r) => r.q.length).map((r) => { const b = r.q.shift(); b.hidden = false; set(r.x, MIN_SCALE); return [r.x, b]; });
    tried.forEach(([x, b]) => { if (!fits(x)) b.hidden = true; else x.done = false; });
  }

  // Then grow each square's type as far as it goes.
  const grow = S.filter((x) => !x.done);
  for (let round = 0; round < 7; round++) {
    grow.forEach((x) => set(x, (x.lo + x.hi) / 2));
    grow.forEach((x) => { const m = (x.lo + x.hi) / 2; if (fits(x)) x.lo = m; else x.hi = m; });
  }
  S.forEach((x) => set(x, x.lo.toFixed(3)));
}

function fitAll() {
  fitSquares([...document.querySelectorAll(".grid.steps .tile.ct")].filter((t) => !t.querySelector(".ct-fixed")));
}

const fit = (tileEl) => fitSquares([tileEl]);

/* ---- the thin bar between the page and the steps ----------------------- */

function bar(tab) {
  const on = !!tab.ui.path;
  const c = ready(tab) ? step(tab, 2) : null;
  const h = tab.course?.iv_history || {};
  const jump = (n, label) => `<button class="sb-step" data-cg-step="${n}">${n} ${label}</button>`;
  return `<div class="stepbar" id="stepbar">
    <span class="sb-title">From chart to trade</span>
    <button class="sb-path${on ? " on" : ""}" data-cg-path="1"
      title="Number the squares below in the order the curriculum reads them">${on ? "Hide the path" : "Create the path"}</button>
    ${jump(1, "Find")}${jump(2, "Direction")}${jump(3, "Build")}${jump(4, "Size")}
    <span class="grow"></span>
    ${c ? `<span class="sb-verdict v-${c.output.direction}">${ARROW[c.output.direction]} <b>${esc(c.output.direction)}</b>
      ${esc(c.scorecard.label.toLowerCase())} &middot; ${signOf(c.scorecard.total)}/${c.scorecard.max}
      &middot; ${esc(s3(tab).name)}</span>` : `<span class="sb-verdict">${tab.courseState === "loading" ? "working&hellip;" : ""}</span>`}
    ${ready(tab) && hasTrade(tab) ? `<button class="sb-open" data-cg-open="1">Open in Workshop</button>` : ""}
    ${IS_OWNER ? `<button class="sb-alpaca" data-cg-alpaca="${h.status === "off" ? "on" : "off"}"
      title="Alpaca is optional: it rebuilds a year of this stock's options for IV Rank. Off, those numbers say why they are missing and nothing is guessed.">
      Alpaca ${h.status === "off" ? "off" : h.status === "ready" ? "on" : h.status === "building" ? "&hellip;" : "off"}</button>` : ""}
  </div>`;
}

/* ---- the path ------------------------------------------------------------ */

function drawPath(tab) {
  document.getElementById("pathlayer")?.remove();
  document.querySelectorAll(".ct-order").forEach((n) => n.remove());
  const grid = document.querySelector(".grid.steps");
  grid?.classList.toggle("pathing", !!(tab?.ui?.path && ready(tab)));
  if (!tab?.ui?.path || !ready(tab) || !grid) return;
  const stops = layoutOf("steps")
    .map((id) => ({ id, el: grid.querySelector(`.tile[data-tile="${id}"]`) }))
    .filter((s) => s.el);
  if (stops.length < 2) return;

  const gb = grid.getBoundingClientRect();
  // The line runs between the numbers in each square's corner, not
  // through the middle, so it never sits on the figure it leads to.
  const at = (el) => { const r = el.getBoundingClientRect(); return { x: r.left - gb.left + 18, y: r.top - gb.top + 17 }; };
  const svgNS = "http://www.w3.org/2000/svg";
  const layer = document.createElementNS(svgNS, "svg");
  layer.setAttribute("id", "pathlayer");
  layer.setAttribute("class", "pathlayer");
  layer.setAttribute("width", grid.scrollWidth);
  layer.setAttribute("height", grid.scrollHeight);
  layer.setAttribute("viewBox", `0 0 ${grid.scrollWidth} ${grid.scrollHeight}`);
  layer.innerHTML = `<defs><marker id="pathhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5"
    orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="pathhead"/></marker></defs>`;

  stops.forEach((s, i) => {
    const m = metricOf(tab, s.id.slice(2));
    const net = s3(tab).greeks?.net?.delta;
    const lean = m?.reads
      || (s.id === "c-scorecard" ? step(tab, 2).output.direction : "")
      || (s.id === "c-greeks" && net ? (net > 0 ? "bullish" : "bearish") : "");
    if (i < stops.length - 1) {
      const a = at(s.el), b = at(stops[i + 1].el);
      const path = document.createElementNS(svgNS, "path");
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const bend = (b.y !== a.y ? 0 : 14) * (i % 2 ? 1 : -1);
      path.setAttribute("d", `M${a.x} ${a.y} Q${mx} ${my + bend} ${b.x} ${b.y}`);
      path.setAttribute("class", "pathline");
      path.setAttribute("marker-end", "url(#pathhead)");
      layer.appendChild(path);
    }
    const n = document.createElement("span");
    n.className = `ct-order${lean ? " o-" + lean : ""}`;
    n.textContent = String(i + 1);
    n.title = `Read this ${i + 1}${["st", "nd", "rd"][((i + 1) % 100 - 20) % 10 - 1] || "th"}`;
    s.el.appendChild(n);
  });
  grid.appendChild(layer);
}

/* ---- after the page is drawn ------------------------------------------- */

function openInWorkshop(tab) {
  const t3 = s3(tab), t4 = s4(tab);
  if (!t3?.legs?.length) return;
  closeZoom(tab);
  const t = newPositionTab();
  const u = t.ui;
  u.symbol = tab.symbol;
  u.legs = t3.legs.map((l) => ({ kind: l.kind, side: l.side, strike: l.strike, qty: 1,
                                 entry: l.entry, expiry: l.expiry }));
  // The shape is one of each; how many is the size Step 4 worked out.
  u.size = Math.max(1, t4?.sizing?.contracts || 1);
  u.view = "work";
  u.route = "custom";
  u.chain = null;
  u.preset = null;
  render();
  loadChain(t);
  analysePosition(t);
}

function mountPayoff(tab) {
  const host = document.querySelector(".ct-payoff");
  if (host && ready(tab)) {
    const w = Math.round(host.clientWidth || 700), h = Math.round(host.clientHeight || 220);
    if (w > 200 && h > 120) host.innerHTML = payoffDrawing(tab, w, h);
  }
}

function mount(tab) {
  fitAll();
  mountPayoff(tab);
  drawPath(tab);
}

/* After a repack (the window changed width) the squares changed size, so
 * they are fitted again and the path redrawn. */
function redraw() {
  const tab = current();
  if (!tab || tab.kind) return;
  fitAll();
  mountPayoff(tab);
  drawPath(tab);
}

/* Every control, wherever it sits -- the bar, a square, or an opened
 * square -- is handled here once, so none of them depends on which of
 * those was drawn last. */
let typing = null;
document.addEventListener("click", async (e) => {
  const tab = current();
  if (!tab || tab.kind) return;
  const b = e.target.closest("[data-cg-path], [data-cg-step], [data-cg-open], [data-cg-alpaca], [data-cg-zoom]");
  if (!b) return;
  e.stopPropagation();
  if (b.dataset.cgPath) {
    tab.ui.path = !tab.ui.path;
    render(true);
  } else if (b.dataset.cgStep) {
    const first = layoutOf("steps").find((id) => String(STEP_OF[id] || "").startsWith(b.dataset.cgStep)
      && document.querySelector(`.tile[data-tile="${id}"]`));
    document.querySelector(`.tile[data-tile="${first}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (b.dataset.cgZoom) {
    openZoom(tab, b.dataset.cgZoom);
  } else if (b.dataset.cgOpen) {
    openInWorkshop(tab);
  } else if (b.dataset.cgAlpaca) {
    b.disabled = true;
    await fetch(`${API}/api/settings/alpaca`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: b.dataset.cgAlpaca === "on" }),
    }).catch(() => null);
    load(tab);
  }
}, true);

document.addEventListener("change", (e) => {
  const el = e.target.closest("[data-cg-account], [data-cg-risk]");
  if (!el) return;
  const key = el.hasAttribute("data-cg-account") ? ACCOUNT_KEY : RISK_KEY;
  const v = Number(String(el.value).replace(/[$,\s%]/g, ""));
  if (Number.isFinite(v) && v > 0) localStorage.setItem(key, String(v));
  else localStorage.removeItem(key);
  clearTimeout(typing);
  typing = setTimeout(() => load(current()), 150);
});

window.QUIPU_COURSE = { load, mount, bar, redraw, fit };
}());
