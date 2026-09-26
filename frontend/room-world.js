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
    ui: { zoom: null, group: "all" },
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
 * Three questions in the order you would ask them: where is the
 * market, what happened, and what is coming. */
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

  const d = tab.data || {};
  const group = tab.ui.group || "all";
  const heads = (d.headlines || []).filter(
    (h) => group === "all" || h.group === group);

  const counts = {};
  (d.headlines || []).forEach((h) => { counts[h.group] = (counts[h.group] || 0) + 1; });

  const GROUPS = {
    all: "everything",
    policy: "central banks and regulators",
    data: "the statistics agencies",
    markets: "the tape",
    wire: "the wires",
  };

  const baro = (d.barometer || []).map((b) => `
    <div class="wxcell">
      <span class="wxlab">${esc(b.label)}</span>
      <b class="${b.change_pct == null ? "" : b.change_pct >= 0 ? "up" : "down"}">${
        b.change_pct == null ? "&ndash;" : signed(b.change_pct, 2)}</b>
      <span class="wxpx">${b.price == null ? "" : money(b.price)}</span>
      <span class="wxwhat">${esc(b.what)}${b.note ? ` &mdash; ${esc(b.note)}` : ""}</span>
    </div>`).join("");

  const cal = ((d.calendar || {}).events || []).slice(0, 8).map((e) => `
    <div class="wcal">
      <span class="wcd">${esc(e.date)}</span>
      <span class="wct">${esc(e.title)}</span>
      <span class="wcw">${esc((e.why || "").slice(0, 110))}</span>
    </div>`).join("");

  return bar + `<div class="worldbody">
    <h4>Where the market is</h4>
    <div class="wxgrid">${baro}</div>
    <div class="fnote">Index funds rather than the indices themselves, because
      those are what actually trade. A day is not a trend and none of this is
      a forecast.</div>

    <h4>What happened</h4>
    <div class="expbar">
      <span class="explab">show</span>
      <div class="cseg">
        ${Object.entries(GROUPS).map(([k, label]) => `
          <button data-wgroup="${k}" class="${group === k ? "on" : ""}">${label}${
            k === "all" ? "" : counts[k] ? ` ${counts[k]}` : ""}</button>`).join("")}
      </div>
    </div>
    <div class="wnews">
      ${heads.length ? heads.map((h) => `
        <div class="wnrow${h.loud ? " loud" : ""}">
          <a class="wnhl" href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a>
          <div class="wnmeta">
            <span class="wnsrc">${esc(h.source)}</span>
            ${h.feeds > 1 ? `<span class="dot">&bull;</span><b>${h.feeds} places</b>` : ""}
            <span class="dot">&bull;</span>${esc(ago(h.published) || "undated")}
            ${h.loud ? `<span class="wnloud">moves everything</span>` : ""}
          </div>
          ${h.summary ? `<div class="wnsum">${esc(h.summary.slice(0, 220))}</div>` : ""}
        </div>`).join("")
      : `<div class="empty" style="height:100px"><div>Nothing in this group</div></div>`}
    </div>
    <div class="fnote">Ranked, never filtered. A story is pushed up by the
      weight of where it came from &mdash; a Federal Reserve release outranks a
      blog about one &mdash; by how many outlets ran it, and by whether the
      headline contains the kind of word that moves a whole market rather than
      one company. A story nobody else carried can still be the one that
      matters, so a low rank buries it rather than dropping it.</div>

    ${cal ? `<h4>What is coming</h4><div class="wcals">${cal}</div>` : ""}
  </div>`;
}

function wireWorld(tab) {
  wireRooms();
  const again = document.getElementById("world-again");
  if (again) again.onclick = () => loadWorld(tab);
  document.querySelectorAll("[data-wgroup]").forEach((b) => {
    b.onclick = () => { tab.ui.group = b.dataset.wgroup; render(true); };
  });
}
