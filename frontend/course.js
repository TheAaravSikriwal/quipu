/* Room: Search -- the curriculum, step by step, at the top of the page.
 *
 * "From Chart to Trade", run on this stock: find the candidate, decide
 * the direction, build the trade, size it. Every number arrives from
 * /api/course with its sum, the curriculum table it is read against,
 * and which way it points; this file only draws them, always the same
 * way, so a reader learns the shape once:
 *
 *    label ................ BIG NUMBER  [which way]  [score x weight]
 *    compared with: the table, its row lit, and the other figures
 *    what to do with it
 *
 * Wrapped, so nothing here lands in the page's shared scope except the
 * handful of hooks the search room calls (window.QUIPU_COURSE).
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
  if (state.active === tab.id && tab.status === "ready") render(true);
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

function metricCard(m) {
  if (!m) return "";
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
    <div class="cg-against">
      ${tableOf(m.against)}
      ${compareList(m.compare)}
    </div>
    <div class="cg-foot">${m.formula ? `<span class="cg-formula">${esc(m.formula)}</span>` : ""}${
      m.source ? `<span class="cg-src">${esc(m.source)}</span>` : ""}</div>
  </div>`;
}

const sectionOf = (sec) => `<div class="cg-section">
  <h5><span class="cg-lesson">${esc(sec.lesson)}</span> ${esc(sec.title)}</h5>
  ${sec.metrics.map(metricCard).join("")}</div>`;

function stepHead(n, title, s) {
  return `<header class="cg-head" id="cg-step${n}">
    <span class="cg-n">${n}</span>
    <div><h3>${esc(title)}</h3>${s?.question ? `<p>${esc(s.question)}</p>` : ""}</div>
  </header>`;
}

function waiting(tab) {
  if (tab.courseState === "error") return `<div class="cg-wait down">Could not run the four steps: ${esc(tab.courseError)}</div>`;
  const c = tab.course;
  if (c && !c.available) return `<div class="cg-wait">The four steps could not run on ${esc(tab.symbol)}: ${esc(c.why)}</div>`;
  return `<div class="cg-wait">Working through the four steps on <b>${esc(tab.symbol)}</b>&hellip;</div>`;
}

const ready = (tab) => tab.course?.available;
const step = (tab, n) => tab.course.steps[String(n)];

/* ---- the verdict, first -------------------------------------------- */

panel("guide", "verdict", "The answer first: direction, conviction, target, the trade, and the thesis", (tab) => {
  if (!ready(tab)) return `<div class="cg-block">${waiting(tab)}</div>`;
  const s2 = step(tab, 2), s3 = step(tab, 3), s4 = step(tab, 4);
  const v = s2.output, card = s2.scorecard;
  const pos = Math.max(-1, Math.min(1, card.total / card.max));
  const h = tab.course.iv_history || {};
  return `<div class="cg-block cg-verdict v-${v.direction}">
    <nav class="cg-steps">
      <a href="#cg-step1"><b>1</b> Find</a><a href="#cg-step2"><b>2</b> Direction</a>
      <a href="#cg-step3"><b>3</b> Build</a><a href="#cg-step4"><b>4</b> Size</a>
      <span class="grow"></span>
      <span class="cg-iv">IV history: ${h.status === "ready" ? `Alpaca, ${esc(h.from)} to ${esc(h.to)}`
        : h.status === "building" ? "rebuilding&hellip;" : esc(h.why || "off")}</span>
      <button class="cg-toggle" data-cg-alpaca="${h.status === "off" ? "on" : "off"}"
        title="Alpaca is optional. Off, nothing that needs a year of options history is shown, and nothing is guessed.">
        ${h.status === "off" ? "turn Alpaca on" : "turn Alpaca off"}</button>
    </nav>
    <div class="cg-call">
      <div class="cg-dir"><span class="cg-dir-arrow">${ARROW[v.direction]}</span>
        <div><b>${esc(v.direction)}</b><span>${esc(card.label)} conviction</span></div></div>
      <div class="cg-meter" title="Direction score, -15 to +15">
        <div class="cg-meter-bar"><i style="left:${50 + pos * 50}%"></i></div>
        <div class="cg-meter-lab"><span>bearish &minus;15</span>
          <b>${calc(signOf(card.total) + " / " + card.max, card.working)}</b><span>+15 bullish</span></div>
      </div>
      <dl class="cg-kv">
        ${v.target ? `<div><dt>target</dt><dd>${money(v.target)}</dd></div>` : `<div><dt>range</dt><dd>${money(v.support)} &ndash; ${money(v.resistance)}</dd></div>`}
        <div><dt>wrong on</dt><dd>${esc(v.invalidation_text)}</dd></div>
        ${v.timeframe ? `<div><dt>timeframe</dt><dd>${calc(`${v.timeframe.low}&ndash;${v.timeframe.high} days`, v.timeframe.working)}</dd></div>` : ""}
        <div><dt>the trade</dt><dd>${esc(s3.name)}${s3.expiry ? `, ${esc(s3.expiry)}` : ""}</dd></div>
      </dl>
      ${s3.legs?.length ? `<button class="cg-open" data-cg-open="1">Open this trade in the Workshop</button>` : ""}
    </div>
    ${card.tempered ? `<p class="cg-temper">Tempered from strong: ${esc(card.tempered)}, so defined risk.</p>` : ""}
    <p class="cg-thesis">${esc(s4.thesis || s3.summary || "")}</p>
    <p class="cg-disclaimer">An educational framework, not advice. The rules of thumb are
      practitioners' conventions, not laws; the model's odds assume no edge.</p>
  </div>`;
});

/* ---- step 1 --------------------------------------------------------- */

panel("guide", "step1", "Step 1, find: liquidity, the IV environment, expected move, catalysts", (tab) => {
  if (!ready(tab)) return "";
  const s = step(tab, 1);
  if (!s.available) return `<div class="cg-block">${stepHead(1, "Find the candidate", s)}<div class="cg-wait">${esc(s.why)}</div></div>`;
  const o = s.output;
  return `<div class="cg-block">
    ${stepHead(1, "Find the candidate", s)}
    <p class="cg-context">Read at the $${nf(s.atm, 2)} strike of the ${esc(s.expiry)} expiry
      (${s.dte} days) &mdash; the contract you would actually trade.</p>
    ${s.sections.map(sectionOf).join("")}
    <div class="cg-output"><b>Step 1 gives Step 2:</b>
      ${o.liquid ? "liquid" : "<span class=down>fails the liquidity gate</span>"}
      (spread ${pct(o.spread_pct, 1)}) &middot; ${esc(o.stance)} [by ${esc(o.iv_column.by)}]
      &middot; expected move &plusmn;${money(o.expected_move)} (${pct(o.expected_pct, 1)})
      ${o.earnings ? `&middot; earnings ${esc(o.earnings.date)}${o.earnings.inside ? " <b>inside the window</b>" : ""}` : ""}</div>
  </div>`;
});

/* ---- step 2 --------------------------------------------------------- */

function scorecardBlock(card) {
  return `<div class="cg-card">
    <h5><span class="cg-lesson">2.10</span> The direction scorecard</h5>
    <table class="cg-table cg-scores">
      <tr class="th"><td>signal</td><td>score</td><td>weight</td><td>points</td></tr>
      ${card.rows.map((r) => `<tr class="${r.points > 0 ? "t-bullish" : r.points < 0 ? "t-bearish" : ""}${r.available ? "" : " off"}">
        <td><span class="cg-lesson">${esc(r.lesson)}</span> ${esc(r.label)}${r.available ? "" : " <i>(not available)</i>"}</td>
        <td>${signOf(r.score)}</td><td>${r.weight}</td><td><b>${signOf(r.points)}</b></td></tr>`).join("")}
      <tr class="total"><td>direction score</td><td></td><td>${card.max}</td><td><b>${signOf(card.total)}</b></td></tr>
    </table>
    <p class="cg-means">Conviction ${calc(nf(card.conviction, 2), card.working)} of 1 &rarr;
      <b>${esc(card.label)}</b>: ${esc(card.feeds)}.
      ${card.missing ? `${card.missing} signal${card.missing > 1 ? "s" : ""} could not be read and score${card.missing > 1 ? "" : "s"} zero, which pulls conviction down rather than guessing.` : ""}</p>
    ${tableOf({ rows: [{ when: "0.60 or more", read: "Strong -- can use more directional delta" },
                       { when: "0.30 to 0.59", read: "Moderate -- spreads, defined risk" },
                       { when: "under 0.30", read: "Weak -- no directional trade, or a neutral strategy" }],
                hit: card.conviction >= 0.6 ? 0 : card.conviction >= 0.3 ? 1 : 2 })}
  </div>`;
}

panel("guide", "step2", "Step 2, direction: nine weighted signals, the scorecard, target and invalidation", (tab) => {
  if (!ready(tab)) return "";
  const s = step(tab, 2);
  return `<div class="cg-block">
    ${stepHead(2, "Determine the direction", s)}
    ${s.sections.map(sectionOf).join("")}
    ${scorecardBlock(s.scorecard)}
    <div class="cg-output"><b>Step 2 gives Step 3:</b> ${esc(s.output.sentence)}</div>
  </div>`;
});

/* ---- the news, beside the scorecard, not in it ---------------------- */

panel("guide", "news", "The news, tagged bullish or bearish with the words why -- shown, never scored", (tab) => {
  if (!ready(tab)) return "";
  const items = (tab.data?.news?.articles || []).filter((a) => a.lean);
  if (!items.length) return "";
  const n = { bullish: 0, bearish: 0, neutral: 0 };
  items.forEach((a) => { n[a.lean.reads] += 1; });
  const top = items.slice().sort((a, b) => (b.moving?.score || 0) - (a.moving?.score || 0)).slice(0, 10);
  return `<div class="cg-block cg-news">
    <h5><span class="cg-lesson">2.4</span> The news, beside the scorecard &mdash; not in it</h5>
    <p class="cg-means">${items.length} articles: <b class="t-bullish">${ARROW.bullish} ${n.bullish} bullish</b>,
      <b class="t-bearish">${ARROW.bearish} ${n.bearish} bearish</b>, ${n.neutral} neutral.
      Tagged from the words in the headline, which cannot read an article, so it adds no points
      &mdash; it is here to agree or disagree with the scorecard, and each tag says which words decided it.</p>
    ${top.map((a) => `<div class="cg-art t-${a.lean.reads}">
      ${readsChip(a.lean.reads)}${a.lean.mixed ? `<span class="cg-mixed">mixed</span>` : ""}
      <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title || "untitled")}</a>
      <span class="cg-words">${(a.lean.words || []).map(esc).join(" &middot; ") || "no telling words"}</span>
      <span class="cg-src">${esc(a.publisher || "")} &middot; ${esc(ago(a.published) || "undated")}</span>
    </div>`).join("")}
  </div>`;
});

/* ---- step 3 --------------------------------------------------------- */

function matrixBlock(m) {
  const cols = [["low", "Low IV (IVR < 30)"], ["mid", "Mid IV (30-50)"], ["high", "High IV (IVR > 50)"]];
  return `<table class="cg-table cg-matrix">
    <tr class="th"><td>direction / conviction</td>${cols.map(([k, l]) =>
      `<td class="${k === m.column ? "col" : ""}">${l}</td>`).join("")}</tr>
    ${m.rows.map((r) => `<tr class="${r.key === m.row ? "row" : ""}"><td>${esc(r.label)}</td>${cols.map(([k]) =>
      `<td class="${r.key === m.row && k === m.column ? "hit" : k === m.column ? "col" : ""}">${esc(r.cells[k])}</td>`).join("")}</tr>`).join("")}
  </table><p class="cg-context">IV column chosen by ${esc(m.by || "IV Rank")}.</p>`;
}

panel("guide", "step3", "Step 3, build: the matrix, expiry, strikes, payoff, odds, greeks", (tab) => {
  if (!ready(tab)) return "";
  const s = step(tab, 3);
  const head = stepHead(3, "Build the trade", s);
  const mx = `<div class="cg-section"><h5><span class="cg-lesson">3.1</span> Strategy from the matrix</h5>
    ${matrixBlock(s.matrix)}${s.why ? `<p class="cg-means">${esc(s.why)}</p>` : ""}</div>`;
  if (!s.legs?.length) {
    return `<div class="cg-block">${head}${mx}<div class="cg-output">${esc(s.summary || s.why || "No trade.")}</div></div>`;
  }
  const p = s.payoff, pr = s.probability, g = s.greeks, ex = s.expiration;
  const f = s.formulas;
  const dollars = (v) => (v === null || v === undefined ? "unlimited" : money(Math.abs(v), 0));
  return `<div class="cg-block">
    ${head}${mx}
    <div class="cg-section"><h5><span class="cg-lesson">3.3</span> Expiration: ${esc(s.expiry)} (${s.dte} days)</h5>
      <dl class="cg-cmp">${ex.parts.map(([l, v]) => `<div><dt>${esc(l)}</dt><dd>${v} days</dd></div>`).join("")}
        <div class="t-bullish"><dt>needs at least</dt><dd><b>${ex.need} days</b> &rarr; first listed: ${esc(s.expiry)}</dd></div></dl>
      <p class="cg-means">${esc(ex.rule)}</p></div>
    <div class="cg-section"><h5><span class="cg-lesson">3.4</span> Strikes, from the target and delta</h5>
      <table class="cg-table cg-legs"><tr class="th"><td>leg</td><td>price (mid)</td><td>bid / ask</td><td>delta</td><td>open interest</td></tr>
        ${s.legs.map((l) => `<tr class="${l.side === "long" ? "t-bullish" : "t-bearish"}"><td><b>${esc(l.side)}</b> $${nf(l.strike, 2)} ${esc(l.kind)}</td>
          <td>${money(l.entry)}</td><td>${money(l.bid)} / ${money(l.ask)}</td><td>${nf(l.delta, 2)}</td><td>${(l.oi || 0).toLocaleString()}</td></tr>`).join("")}
      </table>
      <ul class="cg-why">${(s.strike_why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>
    <div class="cg-section"><h5><span class="cg-lesson">3.2</span> The payoff, by the curriculum's equations</h5>
      ${f ? `<dl class="cg-cmp cg-eq">${f.rows.map(([l, v, w]) => `<div><dt>${esc(l)}</dt><dd>${
        calc(l === "Reward/risk" ? nf(v, 2) : l === "Breakeven" ? money(v) : money(v) + (v === null || v === undefined ? "" : ` <i>(${money(v * 100, 0)} a contract)</i>`), w)}</dd></div>`).join("")}</dl>` : ""}
      <div class="cg-big3">
        <div><span>${p.debit ? "you pay" : "you collect"}</span><b>${money(Math.abs(p.net_cost || 0), 0)}</b></div>
        <div class="pos"><span>most you can make</span><b>${p.max_profit_unbounded ? "unlimited" : dollars(p.max_profit)}</b></div>
        <div class="neg"><span>most you can lose</span><b>${p.max_loss_unbounded ? "unlimited" : dollars(p.max_loss)}</b></div>
        <div><span>break-even</span><b>${(p.breakevens || []).map((b) => money(b)).join(" / ") || "--"}</b></div>
        ${p.reward_risk ? `<div><span>reward / risk</span><b>${nf(p.reward_risk, 2)}</b></div>` : ""}
      </div>
      <div class="cg-payoff" style="height:260px"></div></div>
    <div class="cg-section"><h5><span class="cg-lesson">3.5</span> The odds, and what they mean</h5>
      <dl class="cg-cmp">
        ${pr.breakevens.map((b) => `<div class="${b.profit ? "t-bullish" : ""}"><dt>${b.profit ? "<b>probability of profit</b>: " : ""}${esc(b.label)}</dt>
          <dd>${calc(pct(b.value, 1), b.working)}</dd></div>`).join("")}
        <div><dt>engine's probability of profit</dt><dd>${calc(pct(p.chance, 1), p.chance_working)}</dd></div>
        ${pr.touch ? `<div><dt>touches ${money(pr.touch.target)} before expiry / finishes past it</dt>
          <dd>${calc(pct(pr.touch.touch, 0), pr.touch.working)} / ${pct(pr.touch.finish, 0)}</dd></div>` : ""}
        ${pr.ev ? `<div><dt>expected value, no edge assumed</dt><dd>${calc(cash(pr.ev.ev), pr.ev.working)}</dd></div>` : ""}
      </dl>
      <p class="cg-means">The model's odds are risk-neutral: they assume you know nothing the market does not.
        A probability near a coin flip with a 2:1 payoff is fair on no edge &mdash; Step 2 is what is supposed to tilt it.</p>
      <table class="cg-table cg-greeks"><tr class="th"><td>per share</td><td>delta</td><td>theta / day</td><td>vega / IV pt</td></tr>
        ${g.legs.map((x) => `<tr><td>${esc(x.leg)}</td><td>${nf(x.delta, 3)}</td><td>${nf(x.theta, 3)}</td><td>${nf(x.vega, 3)}</td></tr>`).join("")}
        <tr class="total"><td>net</td><td><b>${nf(g.net.delta, 3)}</b></td><td><b>${nf(g.net.theta, 3)}</b></td><td><b>${nf(g.net.vega, 3)}</b></td></tr>
      </table>
      <p class="cg-means">Net delta ${nf(g.net.delta, 2)} is about ${nf(Math.abs(g.net.delta * 100), 0)} shares of
        ${g.net.delta >= 0 ? "bullish" : "bearish"} exposure a contract. Time ${g.net.theta >= 0 ? "pays you" : "costs you"}
        ${money(Math.abs(g.net.theta * 100))} a day; a one-point IV move is ${money(Math.abs(g.net.vega * 100))}.
        ${g.naked && s.legs.length > 1 ? `The ${esc(g.naked.leg)} alone would cost ${money(Math.abs(g.naked.theta * 100))}/day in time and
          ${money(Math.abs(g.naked.vega * 100))} per IV point &mdash; what the other leg buys you.` : ""}</p>
    </div>
  </div>`;
});

/* ---- step 4 --------------------------------------------------------- */

panel("guide", "step4", "Step 4, size and manage: contracts, exposure, stops, target, time exit, thesis", (tab) => {
  if (!ready(tab)) return "";
  const s = step(tab, 4);
  const head = stepHead(4, "Size, manage, and review", s);
  if (!s.available) return `<div class="cg-block">${head}<div class="cg-wait">${esc(s.why)}</div></div>`;
  const z = s.sizing;
  return `<div class="cg-block">
    ${head}
    <div class="cg-section"><h5><span class="cg-lesson">4.1</span> How many contracts</h5>
      <div class="cg-inputs">
        <label>account <input data-cg-account value="${z.account ?? ""}" placeholder="e.g. 25000" inputmode="decimal"></label>
        <label>risk per trade % <input data-cg-risk value="${z.risk_pct}" inputmode="decimal"></label>
        <span class="cg-context">Kept on this machine only.</span>
      </div>
      ${tableOf(z.table)}
      ${z.contracts !== undefined ? `<div class="cg-big3">
          <div><span>dollars at risk allowed</span><b>${money(z.budget, 0)}</b></div>
          <div><span>most one contract loses</span><b>${money(z.max_loss, 0)}</b></div>
          <div class="${z.contracts ? "pos" : "neg"}"><span>contracts</span><b>${calc(String(z.contracts), z.working)}</b></div>
          <div><span>actual risk</span><b>${z.contracts ? pct(z.actual_pct, 2) : "none placed"}</b></div></div>
        ${z.note ? `<p class="cg-means down">${esc(z.note)}</p>` : ""}`
      : `<p class="cg-means">${esc(z.why || "")}</p>`}
      <dl class="cg-cmp">${s.recovery.map((r) => `<div><dt>a ${r.loss}% drawdown needs</dt><dd>${pct(r.gain, 1)} to get back</dd></div>`).join("")}</dl>
      <p class="cg-means">Why small percentages: losses compound against you. Kelly sizing needs 50+ journaled trades
        to estimate, so it is not offered here.</p></div>
    ${s.beta_weighted ? `<div class="cg-section"><h5><span class="cg-lesson">4.2</span> Market exposure</h5>
      <dl class="cg-cmp"><div><dt>beta-weighted delta</dt><dd>${calc(nf(s.beta_weighted.value, 1) + " SPY shares", s.beta_weighted.working)}</dd></div></dl>
      <p class="cg-means">Add this across every open trade: several bullish trades on high-beta stocks are one big bet on the market.</p></div>` : ""}
    <div class="cg-section"><h5><span class="cg-lesson">4.3-4.5</span> The exits, written before entry</h5>
      <ul class="cg-exits">
        ${s.stops.map((x) => `<li class="x-${x.kind}"><b>${x.kind === "reference" ? "for reference" : x.kind + " stop"}</b>
          ${calc(esc(x.label), x.working)}<span>${esc(x.detail || "")}</span></li>`).join("")}
        <li class="x-target"><b>profit target</b> ${calc(esc(s.target.label), s.target.working)}<span>${esc(s.target.detail)}</span></li>
        <li class="x-time"><b>time exit</b> ${esc(s.time_exit.label)}, by <b>${esc(s.time_exit.on)}</b></li>
        ${s.assignment ? `<li class="x-assign"><b>assignment</b> ${esc(s.assignment)}</li>` : ""}
      </ul></div>
    <div class="cg-output"><b>The one-sentence thesis:</b> ${esc(s.thesis)}
      <span class="cg-context">If you cannot write that sentence with real numbers, one of the four steps is incomplete.</span></div>
  </div>`;
});

/* ---- after the page is drawn ---------------------------------------- */

function openInWorkshop(tab) {
  const s3 = step(tab, 3), s4 = step(tab, 4);
  if (!s3?.legs?.length) return;
  const t = newPositionTab();
  const u = t.ui;
  u.symbol = tab.symbol;
  u.legs = s3.legs.map((l) => ({ kind: l.kind, side: l.side, strike: l.strike, qty: 1,
                                 entry: l.entry, expiry: l.expiry }));
  // The shape is one of each; how many is the size Step 4 worked out.
  u.size = Math.max(1, s4?.sizing?.contracts || 1);
  u.view = "work";
  u.route = "custom";
  u.chain = null;
  u.preset = null;
  render();
  loadChain(t);
  analysePosition(t);
}

let typing = null;

function mount(tab) {
  if (!ready(tab)) return;
  const s3 = step(tab, 3);
  const host = document.querySelector(".cg-payoff");
  if (host && s3?.payoff?.curve?.length && window.QUIPU_PAYOFF) {
    const p = s3.payoff;
    host.innerHTML = window.QUIPU_PAYOFF.payoffSvg({
      curve: p.curve, legs: s3.legs, spot: s3.spot, breakevens: p.breakevens,
      maxProfit: p.max_profit, maxLoss: p.max_loss, bestAt: p.best_at, worstAt: p.worst_at,
      unboundedUp: p.max_profit_unbounded, unboundedDown: p.max_loss_unbounded,
      width: Math.max(560, Math.round(host.clientWidth || 860)),
      height: Math.max(240, Math.round(host.clientHeight || 260)),
    });
  }
  document.querySelectorAll("[data-cg-open]").forEach((b) => { b.onclick = () => openInWorkshop(tab); });
  document.querySelectorAll("[data-cg-alpaca]").forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      await fetch(`${API}/api/settings/alpaca`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: b.dataset.cgAlpaca === "on" }),
      }).catch(() => null);
      load(tab);
    };
  });
  const again = (key, el) => {
    el.onchange = () => {
      const v = Number(String(el.value).replace(/[$,\s%]/g, ""));
      if (Number.isFinite(v) && v > 0) localStorage.setItem(key, String(v));
      else localStorage.removeItem(key);
      clearTimeout(typing);
      typing = setTimeout(() => load(tab), 150);
    };
  };
  const a = document.querySelector("[data-cg-account]");
  const r = document.querySelector("[data-cg-risk]");
  if (a) again(ACCOUNT_KEY, a);
  if (r) again(RISK_KEY, r);
  document.querySelectorAll(".cg-steps a").forEach((l) => {
    l.onclick = (e) => {
      e.preventDefault();
      document.querySelector(l.getAttribute("href"))?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
}

window.QUIPU_COURSE = { load, mount };
}());
