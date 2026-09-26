/* Room: Search -- the curriculum, as squares in the grid.
 *
 * "From Chart to Trade", run on this stock. Every number the four steps
 * produce is a tile in the same packed grid as the rest of the page, below
 * it, behind a thin bar. A tile's face says only what you need in passing:
 *
 *    the figure (hover it for the sum)   which way it points   score x weight
 *    the row of the curriculum's table it landed in
 *    one line on what it means
 *
 * Everything else -- the whole table, what it is compared with, the
 * formula, the sum laid out, the source -- is inside the tile: click it.
 *
 * "Create the path" on the bar numbers the squares in the order the
 * curriculum reads them and joins them with a faint line, so the grid can
 * keep its shape and still be read as one route from "is this tradeable"
 * to "how many contracts". Each number's badge is tinted by the way that
 * square points, so the run of the path shows the lean at a glance.
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

/* The whole of one number: what the tile opens into. */
function metricCard(m) {
  if (!m.available) {
    return `<div class="cg-metric off">
      <div class="cg-top"><span class="cg-lesson">${esc(m.lesson)}</span>
        <span class="cg-label">${esc(m.label)}</span><span class="grow"></span>
        <span class="cg-big">&ndash;</span>${scoreChip(m)}</div>
      <p class="cg-means">${esc(m.why)}</p>
      ${m.formula ? `<div class="cg-formula">${esc(m.formula)}</div>` : ""}
      ${compareList(m.compare)}
    </div>`;
  }
  return `<div class="cg-metric${m.reads ? " m-" + m.reads : ""}">
    <div class="cg-top"><span class="cg-lesson">${esc(m.lesson)}</span>
      <span class="cg-label">${esc(m.label)}</span><span class="grow"></span>
      <span class="cg-big">${calc(esc(m.show), m.working)}</span>
      ${readsChip(m.reads)}${stanceChip(m.stance)}${scoreChip(m)}</div>
    <p class="cg-means">${esc(m.means)}</p>
    <div class="cg-against">${tableOf(m.against)}${compareList(m.compare)}</div>
    ${m.working ? `<h5 class="cg-sumhead">the sum</h5>${wcalc(m.working)}` : ""}
    <div class="cg-foot">${m.formula ? `<span class="cg-formula">${esc(m.formula)}</span>` : ""}${
      m.source ? `<span class="cg-src">${esc(m.source)}</span>` : ""}</div>
  </div>`;
}

/* A tile's face: the figure and its lean, the rule that applied, one line. */
function face(m) {
  if (!m.available) {
    return `<div class="ct-face off"><div class="ct-big">&ndash;</div>
      <div class="ct-chips">${scoreChip(m)}</div>
      <p class="ct-means">${esc(m.why)}</p></div>`;
  }
  const hit = m.against?.rows?.[m.against.hit];
  return `<div class="ct-face${m.reads ? " m-" + m.reads : ""}">
    <div class="ct-big">${calc(esc(m.show), m.working)}</div>
    <div class="ct-chips">${readsChip(m.reads)}${stanceChip(m.stance)}${scoreChip(m)}</div>
    ${hit ? `<div class="ct-hit">&#9656; ${esc(hit.when)} &mdash; ${esc(hit.read)}</div>` : ""}
    <p class="ct-means">${esc(m.means)}</p>
  </div>`;
}

const ready = (tab) => tab.course?.available;
const step = (tab, n) => tab.course.steps[String(n)];
const allMetrics = (tab) => ["1", "2"].flatMap((k) => (step(tab, k).sections || []).flatMap((s) => s.metrics));
const metricOf = (tab, id) => (ready(tab) ? allMetrics(tab).find((m) => m.id === id) : null);

/* The step each square belongs to, for the title's number. */
const STEP_OF = {};
const title = (tab, id, n, text) => `<span class="ct-step">${n}</span> ${esc(text)}`;

/* ---- the tiles ------------------------------------------------------- *
 *
 * One registration per square. Sizes differ on purpose: the numbers that
 * decide the trade -- IV Rank, the expected move, trend, levels, the
 * scorecard, the payoff -- get the room, the confirmations stay small.
 */

const SIZES = {
  // Step 1, four rows of five at the usual five columns, in reading order.
  spread: "w1 h2", oi: "w1 h2", vol_oi: "w1 h2", iv_rank: "w2 h2",
  iv_pct: "w1 h2", hv20: "w1 h2", iv_hv: "w1 h2", em_model: "w2 h2",
  em_market: "w2 h2", daily_move: "w1 h2", earnings_date: "w2 h2",
  market_events: "w2 h2", unusual: "w1 h2", pc_screen: "w2 h2",
  // Step 2's signals, three rows; the news and the scorecard make the fourth.
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
    return m ? `<div class="cg-zoom">${stepNote(n)}${metricCard(m)}</div>` : "";
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

const QUESTION = {
  1: "Find: which stocks are worth analysing, and is this a place to buy or sell premium?",
  2: "Direction: which way, how confident, over what time, to what target -- and where am I wrong?",
  3: "Build: what exact structure, expiration and strikes express the view?",
  4: "Size: how much, when do I get out, and how will I know I was right?",
};
const stepNote = (n) => `<p class="cg-context"><b>Step ${n}.</b> ${esc(QUESTION[n])}</p>`;

["spread", "oi", "vol_oi", "iv_rank", "iv_pct", "hv20", "iv_hv", "em_model", "em_market",
 "daily_move", "earnings_date", "market_events", "unusual", "pc_screen"].forEach((id) => metricTile(id, 1));
["trend", "levels", "pattern", "catalyst", "fundamentals", "rs", "rsi", "pc", "skew"]
  .forEach((id) => metricTile(id, 2));

/* One square that is not a number from a table, built the same way. */
function square(id, n, what, span, name, faceOf, detailOf) {
  STEP_OF[id] = n;
  panel("steps", id, what, (d, tab) => {
    if (!ready(tab)) return waitingTile(tab, id);
    const body = faceOf(tab);
    return body ? tile(id, "e-derived ct", span, title(tab, id, n, name(tab)), body) : "";
  });
  DETAIL[id] = (d, tab) => (ready(tab) ? `<div class="cg-zoom">${stepNote(n)}${detailOf(tab)}</div>` : "");
}

/* ---- step 2: the news beside the scorecard, and the scorecard -------- */

const leaning = (tab) => (tab.data?.news?.articles || []).filter((a) => a.lean);

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
    const top = items.slice().sort((a, b) => (b.moving?.score || 0) - (a.moving?.score || 0)).slice(0, 3);
    return `<div class="ct-face">
      <div class="ct-big ct-split"><b class="t-bullish">${ARROW.bullish} ${n.bullish}</b>
        <b class="t-bearish">${ARROW.bearish} ${n.bearish}</b><b>${ARROW.neutral} ${n.neutral}</b></div>
      <div class="ct-chips"><span class="cg-stance">not scored</span></div>
      ${top.map((a) => `<div class="ct-line t-${a.lean.reads}">${ARROW[a.lean.reads]} ${esc(a.title || "")}</div>`).join("")}
    </div>`;
  },
  (tab) => {
    const items = leaning(tab);
    const n = newsCounts(items);
    const top = items.slice().sort((a, b) => (b.moving?.score || 0) - (a.moving?.score || 0));
    return `<p class="cg-means">${items.length} articles: <b class="t-bullish">${ARROW.bullish} ${n.bullish} bullish</b>,
      <b class="t-bearish">${ARROW.bearish} ${n.bearish} bearish</b>, ${n.neutral} neutral. Tagged from the words in
      the headline, which cannot read an article, so it adds no points &mdash; it is here to agree or disagree with the
      scorecard, and each tag says which words decided it.</p>${newsList(top)}`;
  });

function scorecardBlock(card) {
  return `<table class="cg-table cg-scores">
      <tr class="th"><td>signal</td><td>score</td><td>weight</td><td>points</td></tr>
      ${card.rows.map((r) => `<tr class="${r.points > 0 ? "t-bullish" : r.points < 0 ? "t-bearish" : ""}${r.available ? "" : " off"}">
        <td><span class="cg-lesson">${esc(r.lesson)}</span> ${esc(r.label)}${r.available ? "" : " <i>(not available)</i>"}</td>
        <td>${signOf(r.score)}</td><td>${r.weight}</td><td><b>${signOf(r.points)}</b></td></tr>`).join("")}
      <tr class="total"><td>direction score</td><td></td><td>${card.max}</td><td><b>${signOf(card.total)}</b></td></tr>
    </table>
    <p class="cg-means">Conviction ${calc(nf(card.conviction, 2), card.working)} of 1 &rarr;
      <b>${esc(card.label)}</b>: ${esc(card.feeds)}.
      ${card.missing ? `${card.missing} signal${card.missing > 1 ? "s" : ""} could not be read and score${card.missing > 1 ? "" : "s"} zero, which pulls conviction down rather than guessing.` : ""}
      ${card.tempered ? ` Tempered from strong: ${esc(card.tempered)}, so defined risk.` : ""}</p>
    ${tableOf({ rows: [{ when: "0.60 or more", read: "Strong -- can use more directional delta" },
                       { when: "0.30 to 0.59", read: "Moderate -- spreads, defined risk" },
                       { when: "under 0.30", read: "Weak -- no directional trade, or a neutral strategy" }],
                hit: card.conviction >= 0.6 ? 0 : card.conviction >= 0.3 ? 1 : 2 })}`;
}

const meter = (card) => {
  const pos = Math.max(-1, Math.min(1, card.total / card.max));
  return `<div class="cg-meter" title="Direction score, -15 to +15">
    <div class="cg-meter-bar"><i style="left:${50 + pos * 50}%"></i></div>
    <div class="cg-meter-lab"><span>&minus;15</span><span>+15</span></div></div>`;
};

square("c-scorecard", "2.10", "Step 2's verdict: the weighted scorecard, direction, target and where you are wrong", "w2 h3",
  () => "The scorecard, and the verdict",
  (tab) => {
    const s = step(tab, 2), c = s.scorecard, v = s.output;
    return `<div class="ct-face m-${v.direction}">
      <div class="ct-big">${calc(signOf(c.total) + " / " + c.max, c.working)}</div>
      <div class="ct-chips">${readsChip(v.direction)}<span class="cg-stance">${esc(c.label)} conviction</span></div>
      ${meter(c)}
      <dl class="cg-kv">
        ${v.target ? `<div><dt>target</dt><dd>${money(v.target)}</dd></div>`
          : `<div><dt>range</dt><dd>${money(v.support)} &ndash; ${money(v.resistance)}</dd></div>`}
        <div><dt>wrong on</dt><dd>${v.invalidation ? money(v.invalidation) : "leaving the range"}</dd></div>
        ${v.timeframe ? `<div><dt>timeframe</dt><dd>${v.timeframe.low}&ndash;${v.timeframe.high} days</dd></div>` : ""}
      </dl>
    </div>`;
  },
  (tab) => {
    const s = step(tab, 2);
    return `<h5 class="cg-sumhead">2.10 The direction scorecard</h5>${scorecardBlock(s.scorecard)}
      <div class="cg-output"><b>Step 2 gives Step 3:</b> ${esc(s.output.sentence)}</div>`;
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
  (tab) => `<div class="ct-face"><div class="ct-big">${esc(s3(tab).name)}</div>${matrixBlock(s3(tab).matrix, true)}</div>`,
  (tab) => `${matrixBlock(s3(tab).matrix)}<p class="cg-context">IV column chosen by ${esc(s3(tab).matrix.by || "IV Rank")}.</p>
    ${s3(tab).why ? `<p class="cg-means">${esc(s3(tab).why)}</p>` : ""}
    ${hasTrade(tab) ? "" : `<div class="cg-output">${esc(s3(tab).summary || "")}</div>`}`);

square("c-expiry", "3.3", "Step 3: the expiration, from the catalyst and the timeframe", "w2 h2",
  () => "Expiration",
  (tab) => (hasTrade(tab) ? `<div class="ct-face"><div class="ct-big">${esc(s3(tab).expiry)}</div>
      <div class="ct-chips"><span class="cg-stance">${s3(tab).dte} days</span></div>
      <p class="ct-means">Needs at least ${s3(tab).expiration.need} days: the longest of the rules below it.</p></div>` : ""),
  (tab) => {
    const ex = s3(tab).expiration;
    return `<dl class="cg-cmp">${ex.parts.map(([l, v]) => `<div><dt>${esc(l)}</dt><dd>${v} days</dd></div>`).join("")}
      <div class="t-bullish"><dt>needs at least</dt><dd><b>${ex.need} days</b> &rarr; first listed: ${esc(s3(tab).expiry)}</dd></div></dl>
      <p class="cg-means">${esc(ex.rule)}</p>`;
  });

function legsTable(tab) {
  return `<table class="cg-table cg-legs"><tr class="th"><td>leg</td><td>mid</td><td>bid / ask</td><td>delta</td><td>open int.</td></tr>
    ${s3(tab).legs.map((l) => `<tr class="${l.side === "long" ? "t-bullish" : "t-bearish"}"><td><b>${esc(l.side)}</b> $${nf(l.strike, 2)} ${esc(l.kind)}</td>
      <td>${money(l.entry)}</td><td>${money(l.bid)} / ${money(l.ask)}</td><td>${nf(l.delta, 2)}</td><td>${(l.oi || 0).toLocaleString()}</td></tr>`).join("")}
  </table>`;
}

square("c-strikes", "3.4", "Step 3: the strikes, from the Step 2 target and delta", "w2 h3",
  () => "Strikes",
  (tab) => (hasTrade(tab) ? `<div class="ct-face">
      ${s3(tab).legs.map((l) => `<div class="ct-line ${l.side === "long" ? "t-bullish" : "t-bearish"}"><b>${esc(l.side)}</b>
        $${nf(l.strike, 2)} ${esc(l.kind)} @ ${money(l.entry)} <i>&Delta; ${nf(l.delta, 2)}</i></div>`).join("")}
      <p class="ct-means">${esc((s3(tab).strike_why || [])[0] || "")}</p></div>` : ""),
  (tab) => `${legsTable(tab)}<ul class="cg-why">${(s3(tab).strike_why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`);

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

square("c-payoff", "3.2", "Step 3: the payoff -- what you pay, the most you can make and lose, the break-even", "w3 h3",
  (tab) => `Payoff: ${s3(tab).name}`,
  (tab) => (hasTrade(tab) ? `<div class="ct-face">${bigNumbers(s3(tab).payoff)}
      <div class="ct-payoff">${payoffDrawing(tab, 760, 250)}</div></div>` : ""),
  (tab) => {
    const f = s3(tab).formulas;
    return `${f ? `<h5 class="cg-sumhead">3.2 by the curriculum's equations</h5><dl class="cg-cmp cg-eq">${f.rows.map(([l, v, w]) => `<div><dt>${esc(l)}</dt><dd>${
      calc(l === "Reward/risk" ? nf(v, 2) : l === "Breakeven" ? money(v)
        : money(v) + (v === null || v === undefined ? "" : ` <i>(${money(v * 100, 0)} a contract)</i>`), w)}</dd></div>`).join("")}</dl>` : ""}
      ${bigNumbers(s3(tab).payoff)}<div class="cg-payoff">${payoffDrawing(tab, 900, 300)}</div>`;
  });

square("c-odds", "3.5", "Step 3: the odds -- probability of profit, touching the target, expected value", "w2 h2",
  () => "The odds",
  (tab) => {
    if (!hasTrade(tab)) return "";
    const pr = s3(tab).probability;
    const pop = pr.breakevens.find((b) => b.profit) || pr.breakevens[0];
    return `<div class="ct-face"><div class="ct-big">${pop ? calc(pct(pop.value, 1), pop.working) : "--"}</div>
      <div class="ct-chips"><span class="cg-stance">probability of profit</span></div>
      ${pr.touch ? `<div class="ct-line">touches ${money(pr.touch.target)}: ${pct(pr.touch.touch, 0)}</div>` : ""}
      ${pr.ev ? `<div class="ct-line">expected value, no edge: ${cash(pr.ev.ev)}</div>` : ""}</div>`;
  },
  (tab) => {
    const pr = s3(tab).probability, p = s3(tab).payoff;
    return `<dl class="cg-cmp">
      ${pr.breakevens.map((b) => `<div class="${b.profit ? "t-bullish" : ""}"><dt>${b.profit ? "<b>probability of profit</b>: " : ""}${esc(b.label)}</dt>
        <dd>${calc(pct(b.value, 1), b.working)}</dd></div>`).join("")}
      <div><dt>the engine's probability of profit</dt><dd>${calc(pct(p.chance, 1), p.chance_working)}</dd></div>
      ${pr.touch ? `<div><dt>touches ${money(pr.touch.target)} before expiry / finishes past it</dt>
        <dd>${calc(pct(pr.touch.touch, 0), pr.touch.working)} / ${pct(pr.touch.finish, 0)}</dd></div>` : ""}
      ${pr.ev ? `<div><dt>expected value, no edge assumed</dt><dd>${calc(cash(pr.ev.ev), pr.ev.working)}</dd></div>` : ""}
    </dl>
    <p class="cg-means">The model's odds are risk-neutral: they assume you know nothing the market does not. A probability
      near a coin flip with a 2:1 payoff is fair on no edge &mdash; Step 2 is what is supposed to tilt it.</p>`;
  });

square("c-greeks", "3.5", "Step 3: the position greeks, and what the second leg buys you", "w3 h2",
  () => "Greeks, net",
  (tab) => {
    if (!hasTrade(tab)) return "";
    const g = s3(tab).greeks;
    const sh = g.net.delta === null || g.net.delta === undefined ? "--" : nf(g.net.delta * 100, 0);
    return `<div class="ct-face"><div class="ct-big">${sh} <i class="ct-unit">shares</i></div>
      <div class="ct-chips">${readsChip(g.net.delta > 0 ? "bullish" : g.net.delta < 0 ? "bearish" : "neutral")}</div>
      <div class="ct-line">time ${cash(g.net.theta * 100, 2)} a day</div>
      <div class="ct-line">IV +1 point ${cash(g.net.vega * 100, 2)}</div></div>`;
  },
  (tab) => {
    const t = s3(tab), g = t.greeks;
    return `<table class="cg-table cg-greeks"><tr class="th"><td>per share</td><td>delta</td><td>theta / day</td><td>vega / IV pt</td></tr>
      ${g.legs.map((x) => `<tr><td>${esc(x.leg)}</td><td>${nf(x.delta, 3)}</td><td>${nf(x.theta, 3)}</td><td>${nf(x.vega, 3)}</td></tr>`).join("")}
      <tr class="total"><td>net</td><td><b>${nf(g.net.delta, 3)}</b></td><td><b>${nf(g.net.theta, 3)}</b></td><td><b>${nf(g.net.vega, 3)}</b></td></tr>
    </table>
    <p class="cg-means">Net delta ${nf(g.net.delta, 2)} is about ${nf(Math.abs(g.net.delta * 100), 0)} shares of
      ${g.net.delta >= 0 ? "bullish" : "bearish"} exposure a contract. Time ${g.net.theta >= 0 ? "pays you" : "costs you"}
      ${money(Math.abs(g.net.theta * 100))} a day; a one-point IV move is ${money(Math.abs(g.net.vega * 100))}.
      ${g.naked && t.legs.length > 1 ? `The ${esc(g.naked.leg)} alone would cost ${money(Math.abs(g.naked.theta * 100))}/day in time and
        ${money(Math.abs(g.naked.vega * 100))} per IV point &mdash; what the other leg buys you.` : ""}</p>`;
  });

/* ---- step 4 ---------------------------------------------------------- */

const s4 = (tab) => step(tab, 4);

square("c-size", "4.1", "Step 4: how many contracts, from your account and risk per trade", "w2 h2",
  () => "How many contracts",
  (tab) => {
    if (!s4(tab).available) return "";
    const z = s4(tab).sizing;
    return `<div class="ct-face${z.contracts === 0 ? " m-bearish" : ""}">
      <div class="ct-big">${z.contracts === undefined ? "--" : calc(String(z.contracts), z.working)} <i class="ct-unit">contracts</i></div>
      ${z.contracts !== undefined ? `<div class="ct-line">allowed at risk ${money(z.budget, 0)} &middot; one contract ${money(z.max_loss, 0)}</div>`
        : `<p class="ct-means">${esc(z.why || "")}</p>`}
      ${z.note ? `<p class="ct-means">${esc(z.note)}</p>` : `<p class="ct-means">Click to set your account and risk.</p>`}</div>`;
  },
  (tab) => {
    const s = s4(tab), z = s.sizing;
    return `<div class="cg-inputs">
        <label>account <input data-cg-account value="${z.account ?? ""}" placeholder="e.g. 25000" inputmode="decimal"></label>
        <label>risk per trade % <input data-cg-risk value="${z.risk_pct}" inputmode="decimal"></label>
        <span class="cg-context">Kept on this machine only; changing either reworks the steps.</span>
      </div>
      ${tableOf(z.table)}
      ${z.contracts !== undefined ? `<div class="cg-big3">
          <div><span>dollars at risk allowed</span><b>${money(z.budget, 0)}</b></div>
          <div><span>most one contract loses</span><b>${money(z.max_loss, 0)}</b></div>
          <div class="${z.contracts ? "pos" : "neg"}"><span>contracts</span><b>${calc(String(z.contracts), z.working)}</b></div>
          <div><span>actual risk</span><b>${z.contracts ? pct(z.actual_pct, 2) : "none placed"}</b></div></div>
        ${z.note ? `<p class="cg-means down">${esc(z.note)}</p>` : ""}` : `<p class="cg-means">${esc(z.why || "")}</p>`}
      <dl class="cg-cmp">${s.recovery.map((r) => `<div><dt>a ${r.loss}% drawdown needs</dt><dd>${pct(r.gain, 1)} to get back</dd></div>`).join("")}</dl>
      <p class="cg-means">Why small percentages: losses compound against you. Kelly sizing needs 50+ journaled trades
        to estimate, so it is not offered here.</p>`;
  });

square("c-exposure", "4.2", "Step 4: beta-weighted delta, the trade's share of market exposure", "w1 h2",
  () => "Market exposure",
  (tab) => {
    const b = s4(tab).available && s4(tab).beta_weighted;
    return b ? `<div class="ct-face"><div class="ct-big">${calc(nf(b.value, 1), b.working)} <i class="ct-unit">SPY shares</i></div>
      <p class="ct-means">Beta-weighted delta. Add it across every open trade.</p></div>` : "";
  },
  (tab) => `<dl class="cg-cmp"><div><dt>beta-weighted delta</dt><dd>${calc(nf(s4(tab).beta_weighted.value, 1) + " SPY shares", s4(tab).beta_weighted.working)}</dd></div></dl>
    ${wcalc(s4(tab).beta_weighted.working)}
    <p class="cg-means">Several bullish trades on high-beta stocks are one big bet on the market; this is how big a share of it this one is.</p>`);

square("c-exits", "4.3", "Step 4: the exits, written before entry -- price stop, premium stop, target, time", "w2 h2",
  () => "The exits",
  (tab) => {
    if (!s4(tab).available) return "";
    const s = s4(tab);
    return `<div class="ct-face"><ul class="ct-exits">
      ${s.stops.filter((x) => x.kind !== "reference").map((x) => `<li class="x-${x.kind}"><b>${esc(x.kind)} stop</b> ${esc(x.label)}</li>`).join("")}
      <li class="x-target"><b>target</b> ${esc(s.target.label)}</li>
      <li class="x-time"><b>time</b> ${esc(s.time_exit.label)}, by ${esc(s.time_exit.on)}</li></ul></div>`;
  },
  (tab) => {
    const s = s4(tab);
    return `<ul class="cg-exits">
      ${s.stops.map((x) => `<li class="x-${x.kind}"><b>${x.kind === "reference" ? "for reference" : x.kind + " stop"}</b>
        ${calc(esc(x.label), x.working)}<span>${esc(x.detail || "")}</span></li>`).join("")}
      <li class="x-target"><b>profit target</b> ${calc(esc(s.target.label), s.target.working)}<span>${esc(s.target.detail)}</span></li>
      <li class="x-time"><b>time exit</b> ${esc(s.time_exit.label)}, by <b>${esc(s.time_exit.on)}</b></li>
      ${s.assignment ? `<li class="x-assign"><b>assignment</b> ${esc(s.assignment)}</li>` : ""}
    </ul>`;
  });

square("c-thesis", "4", "Step 4: the one-sentence thesis, and the button that places it in the Workshop", "w5 h2",
  () => "The thesis",
  (tab) => {
    const text = s4(tab).available ? s4(tab).thesis : s3(tab).summary;
    return `<div class="ct-face"><p class="ct-thesis">${esc(text || "")}</p>
      ${hasTrade(tab) ? `<button class="cg-open" data-cg-open="1">Open this trade in the Workshop</button>` : ""}</div>`;
  },
  (tab) => `<div class="cg-output"><b>The one-sentence thesis:</b> ${esc(s4(tab).available ? s4(tab).thesis : s3(tab).summary)}
      <span class="cg-context">If you cannot write that sentence with real numbers, one of the four steps is incomplete.</span></div>
    ${hasTrade(tab) ? `<button class="cg-open" data-cg-open="1">Open this trade in the Workshop</button>` : ""}
    <p class="cg-disclaimer">An educational framework, not advice. The rules of thumb are practitioners' conventions,
      not laws; the model's odds assume no edge.</p>`);

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
    <button class="sb-alpaca" data-cg-alpaca="${h.status === "off" ? "on" : "off"}"
      title="Alpaca is optional: it rebuilds a year of this stock's options for IV Rank. Off, those numbers say why they are missing and nothing is guessed.">
      Alpaca ${h.status === "off" ? "off" : h.status === "ready" ? "on" : h.status === "building" ? "&hellip;" : "off"}</button>
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

function mount(tab) {
  const host = document.querySelector(".ct-payoff");
  if (host && ready(tab)) {
    const w = Math.round(host.clientWidth || 700), h = Math.round(host.clientHeight || 220);
    if (w > 200 && h > 120) host.innerHTML = payoffDrawing(tab, w, h);
  }
  drawPath(tab);
}

/* Every control, wherever it sits -- the bar, a square, or an opened
 * square -- is handled here once, so none of them depends on which of
 * those was drawn last. */
let typing = null;
document.addEventListener("click", async (e) => {
  const tab = current();
  if (!tab || tab.kind) return;
  const b = e.target.closest("[data-cg-path], [data-cg-step], [data-cg-open], [data-cg-alpaca]");
  if (!b) return;
  e.stopPropagation();
  if (b.dataset.cgPath) {
    tab.ui.path = !tab.ui.path;
    render(true);
  } else if (b.dataset.cgStep) {
    const first = layoutOf("steps").find((id) => String(STEP_OF[id] || "").startsWith(b.dataset.cgStep)
      && document.querySelector(`.tile[data-tile="${id}"]`));
    document.querySelector(`.tile[data-tile="${first}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
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

window.QUIPU_COURSE = { load, mount, bar, redraw: () => drawPath(current()) };
}());
