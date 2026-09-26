/* Room: Finder -- rank the whole market and find one. */

/* ---- the finder -------------------------------------------------------
 *
 * Search answers "tell me about NVDA". This answers the question you have
 * before that one: out of every listed US stock, which handful is even
 * worth opening a tab on today.
 *
 * It opens as its own tab rather than a panel because it is a place you go
 * and come back to, and because the tab strip already is the app's history
 * of what you were looking at.
 */
function newFinderTab() {
  const tab = {
    id: ++state.seq, symbol: null, kind: "finder", status: "finder",
    data: null, error: null, live: false, loading: true,
    ui: { rank: "tradeable", limit: 40, zoom: null },
  };
  state.tabs.push(tab);
  state.active = tab.id;
  render();
  loadScreen(tab);
  return tab;
}

async function loadScreen(tab) {
  tab.loading = true;
  try {
    const res = await fetch(
      `${API}/api/screen?rank=${encodeURIComponent(tab.ui.rank)}&limit=${tab.ui.limit}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    tab.data = await res.json();
    tab.error = null;
  } catch (err) {
    tab.error = String(err.message || err);
  }
  tab.loading = false;
  // Keep the scroll. While the first scan runs this function re-renders
  // every four seconds, and without this the list snapped back to the
  // top each time -- so scrolling during a scan looked like a scrollbar
  // that did not work, when it was working and then being undone a
  // moment later.
  if (state.active === tab.id) render(true);

  // The first scan of ten thousand stocks takes about three minutes. Rather
  // than block on it, the tab shows its progress and asks again.
  if (tab.data?.meta?.status === "scanning") {
    setTimeout(() => { if (state.tabs.includes(tab)) loadScreen(tab); }, 4000);
  }
}

/* ---- the finder, drawn ----------------------------------------------- */

/* The same five columns whatever the ranking, and deliberately NOT the
 * metrics the ranking is built from -- those are already spelled out in the
 * reasons beside them, and printing "155% volatility" as a sentence and
 * "155%" as a number on the same line says one thing twice.
 *
 * These are the constants you want in order to compare a name from one list
 * against a name from another: what it costs, whether you can get out, how
 * much it moves, and what it has done lately. */
// The fourth field says whether the number has a direction. Price and
// turnover do not -- a big number is not an up number -- and volatility
// has one but it is not good or bad, so only the two returns are tinted.
const FINDER_COLS = [
  ["price", "price", money, false],
  ["dollar_vol", "a day", big, false],
  ["vol20", "volatility", (v) => pct(v, 0), false],
  ["ret_1m", "1 month", (v) => signed(v, 0), true],
  ["ret_12m", "12 months", (v) => signed(v, 0), true],
];

function renderFinder(tab) {
  const d = tab.data || {};
  const meta = d.meta || {};
  const scanning = meta.status === "scanning";
  const cat = FINDER_RANKINGS;

  const bar = `<div class="livebar">
    <span class="lbsym">Finder</span>
    <span class="grow"></span>
    <span>${scanning
      ? `Measuring <b>${meta.done || 0}</b> of <b>${meta.total || "--"}</b>`
      : `<b>${big(meta.measured)}</b> stocks measured${
          meta.eligible ? `, <b>${big(meta.eligible)}</b> liquid enough` : ""}`}</span>
    <span>${meta.age_s != null ? `scanned <b>${meta.age_s < 90
      ? meta.age_s + "s" : Math.round(meta.age_s / 60) + " min"}</b> ago` : ""}</span>
    <button id="fn-refresh">Rescan</button>
    ${roomNav("finder")}
  </div>`;

  /* Each card carries what the ranking DID, not only what it is for. A
   * screener that cannot say whether its own lists went anywhere is asking
   * to be taken on faith, and the walk-forward is cheap to quote. */
  const picker = `<div class="fpick">${cat.map((r) => `
    <button data-frank="${r.id}" class="${r.id === tab.ui.rank ? "on" : ""}">
      <span class="l">${esc(r.label)}</span><span class="n">${esc(r.note)}</span>
      ${r.study ? `<span class="v">${esc(r.study.verdict)}</span>` : ""}
    </button>`).join("")}</div>`;

  if (tab.error) {
    return bar + picker + `<div class="empty"><div class="down">The screen failed</div>
      <div class="stage">${esc(tab.error)}</div></div>`;
  }

  const rows = d.rows || [];
  if (!rows.length) {
    return bar + picker + `<div class="loading">
      ${scanning ? `<div class="spinner"></div>
        <div>Measuring every listed US stock</div>
        <div class="stage">${meta.done || 0} of ${meta.total || "--"} &middot;
          this happens once, then every ranking is instant</div>`
        : `<div>Nothing passed the filters</div>`}</div>`;
  }

  return bar + picker + `
    <div class="finder">
      <div class="frow fhead">
        <span class="fn">#</span><span class="fsym">symbol</span>
        <span class="fwhy">why it is here</span>
        ${FINDER_COLS.map(([, label]) => `<span class="fv">${esc(label)}</span>`).join("")}
      </div>
      ${rows.map((r, i) => `
        <div class="frow" data-fsym="${esc(r.symbol)}">
          <span class="fn">${i + 1}</span>
          <span class="fsym"><b>${esc(r.symbol)}</b>
            <i>${esc((r.name || "").replace(/ (Common Stock|Class A Common Stock|Ordinary Shares).*$/i, ""))}</i></span>
          <span class="fwhy">${r.why.map((w) => `<em>${esc(w)}</em>`).join("")}</span>
          ${FINDER_COLS.map(([k, , fmt, signed_]) => `<span class="fv ${
            signed_ && r[k] != null ? sign(r[k]) : ""}">${
            r[k] == null ? "--" : fmt(r[k])}</span>`).join("")}
        </div>`).join("")}
    </div>
    ${FINDER_STUDY ? `<div class="fstudy prose">
      <b>Tested.</b> Every ranking above was replayed through
      ${FINDER_STUDY.windows} fortnightly windows of the past year: metrics
      computed from bars up to that date only, top ${FINDER_STUDY.top} taken,
      then measured against what the whole eligible universe did over the
      next ${(FINDER_STUDY.horizons || []).join(" and ")} sessions. Each is
      graded on what it claims &mdash; the three directional lists on return,
      the volatility lists on whether volatility moved the way they said.
      Overlapping windows, one market regime, no costs, and the panel only
      holds names liquid enough to be in it today, which flatters returns.
    </div>` : ""}
    <div class="fnote prose">
      ${esc(d.note || "")} Scored as
      ${(d.parts || []).map((p) => `${Math.round(p.weight * 100)}% ${esc(p.metric.replace(/_/g, " "))}${p.invert ? " (low)" : ""}`).join(", ")}.
      Percentiles are taken within the liquid universe, not against fixed
      thresholds. None of this predicts anything &mdash; it is a sort order over
      public measurements. Click any row to open it.
    </div>`;
}

let FINDER_RANKINGS = [];
let FINDER_STUDY = null;

async function loadRankings() {
  try {
    const res = await fetch(`${API}/api/screen/rankings`);
    const d = await res.json();
    FINDER_RANKINGS = d.rankings || [];
    FINDER_STUDY = d.study && d.study.windows ? d.study : null;
  } catch { FINDER_RANKINGS = []; FINDER_STUDY = null; }
}

function wireFinder(tab) {
  wireRooms();
  document.querySelectorAll("[data-frank]").forEach((b) => {
    b.onclick = () => {
      if (b.dataset.frank === tab.ui.rank) return;
      tab.ui.rank = b.dataset.frank;
      render(true);
      loadScreen(tab);
    };
  });
  document.querySelectorAll("[data-fsym]").forEach((el) => {
    el.onclick = () => newTab(el.dataset.fsym);
  });
  const rs = document.getElementById("fn-refresh");
  if (rs) rs.onclick = async () => {
    rs.textContent = "Rescanning";
    await fetch(`${API}/api/screen/refresh`, { method: "POST" });
    loadScreen(tab);
  };
}

/* ---- the room ------------------------------------------------------ */

room("finder", {
  // The rankings are the finder's menu; fetch them first so the tab
  // never opens onto an empty choice.
  open: () => (FINDER_RANKINGS.length ? Promise.resolve() : loadRankings())
    .then(() => newFinderTab()),
  draw: renderFinder,
  wire: wireFinder,
  place: (u) => ({ ranking: u.ranking, study: u.study }),
  name: () => "Finder",
});
