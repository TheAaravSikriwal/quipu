/* Room: World -- the market as a whole, and why. */

/* What is happening, rather than what is happening to one company.
 *
 * Every other room starts from a ticker. This one is the question you
 * have BEFORE you pick one: whether the tape is risk-on, whether the
 * Fed spoke this morning, whether the selling is in one name or in
 * all of them. Opening a company page to work that out means reading
 * a single stock and generalising from it, which is the wrong way
 * round.
 */
function newWorldTab() {
  const tab = {
    id: ++state.seq, symbol: null, kind: "world", status: "world",
    data: null, error: null, live: true, loading: true,
    ui: { zoom: null },
  };
  state.tabs.push(tab);
  state.active = tab.id;
  render();
  loadWorld(tab);
  return tab;
}

async function loadWorld(tab) {
  tab.loading = true;
  if (state.active === tab.id) render(true);
  try {
    const res = await fetch(`${API}/api/world`);
    if (!res.ok) throw new Error(res.statusText);
    tab.data = await res.json();
    tab.error = null;
  } catch (err) {
    tab.error = String(err.message || err);
  }
  tab.loading = false;
  if (state.active === tab.id) render(true);
}

/* The world, drawn.
 *
 * The same grid of squares as a company's page, packed by the same
 * packer and opened by the same click: every instrument, every kind of
 * source and every release coming up is a square of its own. Three
 * bands, in the order you would ask them: where is the market, what
 * happened, and what is coming. */
function renderWorld(tab) {
  const bar = `<div class="livebar">
      <span class="lbsym">World</span>
      ${tab.data ? `<span>${tab.data.feeds_reached?.length || 0} of
        ${tab.data.feeds_total} feeds &middot;
        <b>${tab.data.found}</b> stories</span>
      <span>read ${esc(tab.data.at || "")}</span>` : ""}
      <span class="grow"></span>
      <button id="world-again">Read again</button>
      ${roomNav("world")}
    </div>`;

  if (tab.loading && !tab.data) {
    return bar + `<div class="loading"><div class="spinner"></div>
      <div>Reading the market</div>
      <div class="stage">central banks &middot; statistics agencies &middot;
        wires &middot; the tape</div></div>`;
  }
  if (tab.error && !tab.data) {
    return bar + `<div class="empty" style="height:150px">
      <div class="down">Could not read the market</div>
      <div class="stage">${esc(tab.error)}</div></div>`;
  }

  // A square's body and title are what a click opens, so they are
  // written afresh with every drawing, as the company page does.
  BODIES = {};
  TITLES = {};
  SPANS = {};
  BADGES = {};
  // Which parts, and in what order, is layout.js's call.
  return bar + `<div class="grid world">${compose("world", tab)}</div>`;
}

/* ---- the squares ---------------------------------------------------- */

/* The band each panel's squares sit in, read off the layout. The packer
 * keeps a band in one run down the page; numbered past the company
 * page's bands so the two can never be confused. */
const WORLD_BAND = {};
(LAYOUT.world || []).forEach((g, i) =>
  (typeof g === "string" ? [g] : g.panels).forEach((id) => { WORLD_BAND[id] = 100 + i; }));

function worldTile(panelId, id, cls, span, title, body, badge = "") {
  REGION_OF[id] = WORLD_BAND[panelId] ?? 99;
  return tile(id, cls, span, title, body, badge);
}

const WORLD_GROUPS = {
  policy: "Central banks and regulators",
  data: "The statistics agencies",
  markets: "The tape",
  wire: "The wires",
};

const LEAN = { bullish: "&uarr;", bearish: "&darr;" };

function headMeta(h) {
  return `<div class="wnmeta">
      <span class="wnsrc">${esc(h.source)}</span>
      ${h.feeds > 1 ? `<span class="dot">&bull;</span><b>${h.feeds} places</b>` : ""}
      <span class="dot">&bull;</span>${esc(ago(h.published) || "undated")}
      ${h.loud ? `<span class="wnloud">moves everything</span>` : ""}
    </div>`;
}

function headRow(h, full) {
  const reads = h.lean?.reads;
  return `<div class="wnrow${h.loud ? " loud" : ""}">
      <a class="wnhl" href="${safeUrl(h.url)}" target="_blank" rel="noopener">${
        LEAN[reads] ? `<span class="t-${reads}">${LEAN[reads]}</span> ` : ""}${esc(h.title)}</a>
      ${headMeta(h)}
      ${full && h.summary ? `<div class="wnsum">${esc(h.summary.slice(0, 400))}</div>` : ""}
    </div>`;
}

const RANKED = `<div class="fnote">Ranked, never filtered. A story is pushed up by the
  weight of where it came from &mdash; a Federal Reserve release outranks a
  blog about one &mdash; by how many outlets ran it, and by whether the
  headline contains the kind of word that moves a whole market rather than
  one company. A story nobody else carried can still be the one that
  matters, so a low rank buries it rather than dropping it. The arrows are
  read from the headline's words, not from the article, and are not a
  forecast.</div>`;

/* Where the market is: a square per instrument. */
panel("world", "barometer", "Index funds, VIX, Treasuries, gold and oil: a square each", (tab) =>
  (tab.data?.barometer || []).map((b) => worldTile("barometer", "wx-" + b.symbol, "e-priced", "w1 h1",
    esc(b.label), `
      <b class="wxbig ${b.change_pct == null ? "" : b.change_pct >= 0 ? "up" : "down"}">${
        b.change_pct == null ? "&ndash;" : signed(b.change_pct, 2)}</b>
      <span class="wxpx">${esc(b.symbol)}${b.price == null ? "" : " &middot; " + money(b.price)}</span>
      <span class="wxwhat">${esc(b.what)}${b.note ? ` &mdash; ${esc(b.note)}` : ""}</span>`,
  )).join(""));

/* The one story most worth reading first. */
panel("world", "lead", "The highest-ranked story, on a square of its own", (tab) => {
  const top = (tab.data?.headlines || [])[0];
  if (!top) return "";
  return worldTile("lead", "wn-lead", "", "w2 h2", "The story at the top", `
    <a class="wnlead" href="${safeUrl(top.url)}" target="_blank" rel="noopener">${esc(top.title)}</a>
    ${headMeta(top)}
    ${top.summary ? `<div class="wnsum">${esc(top.summary.slice(0, 300))}</div>` : ""}`);
});

/* What happened: a square per kind of source, each ranked within itself.
 * Opened, a square shows every story in it, with summaries. */
panel("world", "headlines", "What happened, a square per kind of source, ranked", (tab) => {
  const all = tab.data?.headlines || [];
  return Object.entries(WORLD_GROUPS).map(([g, label]) => {
    const heads = all.filter((h) => h.group === g);
    if (!heads.length) return "";
    const id = "wn-" + g;
    DETAIL[id] = () => `<div class="wnews">${heads.map((h) => headRow(h, true)).join("")}</div>${RANKED}`;
    const loud = heads.filter((h) => h.loud).length;
    return worldTile("headlines", id, "elastic", heads.length > 6 ? "w2 h3" : "w2 h2", label,
      `<div class="wnews">${heads.slice(0, 10).map((h) => headRow(h, false)).join("")}</div>`,
      `${heads.length}${loud ? ` &middot; ${loud} loud` : ""}`);
  }).join("");
});

/* What is coming: a square per scheduled release. */
panel("world", "calendar", "What is coming: a square per scheduled release", (tab) =>
  ((tab.data?.calendar || {}).events || []).slice(0, 8).map((e, i) => {
    const id = "wc-" + i;
    const when = e.days == null ? "" : e.days === 0 ? "today" : e.days === 1 ? "tomorrow" : `in ${e.days} days`;
    const date = `${esc(e.date)}${e.time ? " &middot; " + esc(e.time) : ""}`;
    DETAIL[id] = () => `<div class="wcz">
        <div class="wcd">${date}${when ? " &middot; " + when : ""}</div>
        <h4 class="wct">${esc(e.title)}</h4>
        ${e.detail ? `<div class="wcdet">${esc(e.detail)}</div>` : ""}
        <p class="wcw">${esc(e.why || "")}</p>
        <div class="wnmeta"><span class="wnsrc">${esc(e.source || "")}</span>
          ${e.confirmed === false || e.approx ? `<span class="dot">&bull;</span>date not yet confirmed` : ""}
          ${e.url ? `<span class="dot">&bull;</span><a href="${safeUrl(e.url)}" target="_blank" rel="noopener">the schedule</a>` : ""}</div>
      </div>`;
    return worldTile("calendar", id, "", "w1 h1", esc(when || e.date), `
      <div class="wcd">${date}</div>
      <div class="wct">${esc(e.title)}</div>
      <div class="wcw">${esc((e.why || "").slice(0, 110))}</div>`);
  }).join(""));

function wireWorld(tab) {
  wireRooms();
  const again = document.getElementById("world-again");
  if (again) again.onclick = () => loadWorld(tab);
  if (!document.querySelector(".grid.world")) return;
  packGrid();
  watchGrid();
  document.querySelectorAll(".grid.world .tile[data-tile]").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest("a, select, input, button")) return;
      openZoom(tab, el.dataset.tile);
    };
  });
  if (tab.ui.zoom) openZoom(tab, tab.ui.zoom);
}

/* ---- the room ------------------------------------------------------ */

room("world", {
  open: newWorldTab,
  draw: renderWorld,
  wire: wireWorld,
  place: () => ({}),
  name: () => "World",
});
