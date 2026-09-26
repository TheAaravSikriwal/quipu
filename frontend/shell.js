/* QUIPU -- the frame around the rooms.
 *
 * Tabs, the ring of room buttons, the per-tab trail, the launcher, and
 * render(), which hands the viewport to whichever room the tab is.
 */

/* ---- tabs and loading ------------------------------------------------ */

function newTab(symbol = null) {
  const tab = {
    id: ++state.seq, symbol,
    status: symbol ? "loading" : "blank",
    data: null, error: null, lastLive: null, liveMs: null, live: true,
    ui: { side: "call", expiryIdx: 0, strike: null, budget: 1000, zoom: null },
  };
  state.tabs.push(tab);
  state.active = tab.id;
  render();
  if (symbol) load(tab);
  return tab;
}

/* The four rooms this app has, and what each tab strip entry means.
 *
 * Colour here is the same argument the moving averages make: it says
 * WHICH ROOM THIS IS and nothing else. The hue on a tab is repeated on
 * the button that opens that room, so the mapping is shown rather than
 * memorised -- and the room is named in words on both, so the colour is
 * never carrying the fact alone.
 */
const ROOMS = {
  search:   { label: "Search",    what: "one company, everything on it" },
  finder:   { label: "Finder",    what: "rank the whole market and find one" },
  position: { label: "Workshop",  what: "build a position and price it" },
  log:      { label: "Trade log", what: "what you are holding now" },
  world:    { label: "World",     what: "the market as a whole, and why" },
};

/* What each room does, filled in by the room's own file.
 *
 * Everything the frame needs to know about a room -- how to open one,
 * how to draw it, what to wire once it is drawn, what is worth keeping
 * in the back/forward trail -- is one entry, registered at the bottom
 * of that room's file with room(). Adding a room or retiring one is
 * that entry plus a line in ROOMS, instead of a branch in each of the
 * five places that used to ask "which kind of tab is this".
 *
 *   open()               make a tab of this room and return it
 *   draw(tab)            the room's HTML
 *   wire(tab)            handlers, once that HTML is on the page
 *   show(tab, view, y)   optional: replaces draw+wire when a room needs
 *                        more than that (the search room packs a grid
 *                        and mounts charts)
 *   place(ui)            what the back/forward trail remembers
 *   resume(tab)          what to redo after stepping back to a place
 *   name(tab)            the words on its tab when there is no ticker
 *   badge(tab)           optional small text after the name
 */
const VIEWS = {};
function room(id, view) { VIEWS[id] = view; }
const roomOf = (tab) => tab?.kind || "search";

/* Going somewhere else, from anywhere.
 *
 * Every room used to be reachable only from the front page, so getting
 * from a company to the finder meant opening a blank tab first and
 * going back out to the launcher. That is what made the app feel like
 * it branched: each tab was a dead end you reversed out of.
 *
 * The same four buttons now sit in every room, so the shape is a ring
 * rather than a tree -- from any one of them you are one click from the
 * other three, and you never lose where you were, because going to a
 * different KIND of room opens a tab instead of replacing this one.
 *
 * Switching to the room you are already in is not navigation, so that
 * button is marked as where you are and does nothing.
 */
function roomNav(here) {
  return `<nav class="rooms">${Object.entries(ROOMS).map(([id, r]) =>
    `<button class="room r-${id}${id === here ? " here" : ""}"
       data-room="${id}" title="${esc(r.what)}"
       ${id === here ? 'aria-current="page"' : ""}>${esc(r.label)}</button>`
  ).join("")}</nav>`;
}

/* One way in to each room, so "open a new tab" is decided once. */
function openRoom(which) {
  return (VIEWS[which] || VIEWS.search).open();
}

function wireRooms() {
  document.querySelectorAll("[data-room]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      if (b.classList.contains("here")) return;
      openRoom(b.dataset.room);
    };
  });
}

function closeTab(id, event) {
  if (event) event.stopPropagation();
  const i = state.tabs.findIndex((t) => t.id === id);
  if (i < 0) return;
  state.tabs.splice(i, 1);
  if (state.active === id) state.active = state.tabs.length ? state.tabs[Math.max(0, i - 1)].id : null;
  if (!state.tabs.length) newTab();
  else render();
}

const current = () => state.tabs.find((t) => t.id === state.active);

/* ---- where you have been, per tab ----------------------------------
 *
 * Each tab keeps its own trail, because each tab is a separate line of
 * thought: stepping back in the position workspace should not undo a
 * zoom in the ticker beside it.
 *
 * A "place" is only the handful of fields that decide what is on
 * screen. Data, chains and analyses are deliberately left out -- going
 * back should return you to a view, not to a stale copy of the numbers
 * it was showing an hour ago. */
// What each room remembers is its own business: see `place` in VIEWS.
const placeOf = (tab) => (VIEWS[roomOf(tab)]?.place || (() => ({})))(tab.ui || {});
const samePlace = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Record where the tab is now, if it has moved. */
function markPlace(tab) {
  if (!tab) return;
  const here = placeOf(tab);
  tab.hist ||= { stack: [here], at: 0 };
  if (samePlace(tab.hist.stack[tab.hist.at], here)) return;
  // Stepping back and then somewhere new abandons the forward trail,
  // which is what every back button in the world does.
  tab.hist.stack = tab.hist.stack.slice(0, tab.hist.at + 1);
  tab.hist.stack.push(here);
  if (tab.hist.stack.length > 40) tab.hist.stack.shift();
  tab.hist.at = tab.hist.stack.length - 1;
}

function step(tab, delta) {
  if (!tab?.hist) return;
  const to = tab.hist.at + delta;
  if (to < 0 || to >= tab.hist.stack.length) return;
  tab.hist.at = to;
  const place = tab.hist.stack[to];
  Object.entries(place).forEach(([k, v]) => {
    tab.ui[k] = k === "legs" ? JSON.parse(v) : v;
  });
  // Restoring a position means re-pricing it: the legs came back, the
  // analysis of them did not, and showing the old one would be showing
  // numbers for a different trade.
  render(true);
  VIEWS[roomOf(tab)]?.resume?.(tab);
}

const canStep = (tab, d) => {
  const h = tab?.hist;
  return !!h && h.at + d >= 0 && h.at + d < h.stack.length;
};

/* ---- search ---------------------------------------------------------- */

let suggestTimer = null, suggestions = [], suggestOn = -1;

function search(value) {
  const q = (value || "").trim();
  if (!q) return;
  const tab = current();
  tab.symbol = q.toUpperCase();
  load(tab);
}

function pick(symbol) {
  const tab = current();
  tab.symbol = symbol;
  suggestions = [];
  load(tab);
}

async function fetchSuggestions(q) {
  if (q.trim().length < 2) { suggestions = []; paintSuggestions(); return; }
  try {
    const res = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
    suggestions = (await res.json()).results || [];
  } catch { suggestions = []; }
  suggestOn = -1;
  paintSuggestions();
}

function paintSuggestions() {
  const box = document.getElementById("suggest");
  if (!box) return;
  if (!suggestions.length) { box.innerHTML = ""; box.style.display = "none"; return; }
  box.style.display = "block";
  box.innerHTML = suggestions
    .map((r, i) => `<div data-sym="${esc(r.symbol)}" class="${i === suggestOn ? "on" : ""}">
        <span class="s">${esc(r.symbol)}</span><span class="n">${esc(r.name)}</span>
        <span class="e">${esc(r.exchange || "")} ${r.type !== "Equity" ? esc(r.type) : ""}</span></div>`)
    .join("");
  box.querySelectorAll("div").forEach((el) => { el.onclick = () => pick(el.dataset.sym); });
}

/* ---- chrome ---------------------------------------------------------- */

/* The price, pinned.
 *
 * It lives in the sticky bar so scrolling cannot lose it, in the tab chip so
 * switching away cannot lose it, and in the window title so the price is
 * readable even when the window is behind something else. Every other number
 * on this page is quoted relative to this one, so it is never off screen.
 */
function priceNow(tab) {
  const q = tab.data?.quote;
  if (!q?.price) return "";
  return `<b>${money(q.price)}</b><span class="${sign(q.change)}">${signed(q.change_pct, 2)}</span>`;
}

function setTitle(tab) {
  const q = tab?.data?.quote;
  document.title = q?.price
    ? `${tab.symbol} ${money(q.price)} ${signed(q.change_pct, 2)} · QUIPU`
    : "QUIPU";
}

function renderTabs() {
  const strip = document.getElementById("tabstrip");
  strip.querySelectorAll(".tab, .navpair").forEach((el) => el.remove());
  const plus = document.getElementById("newtab");

  // One pair of arrows, acting on whichever tab is in front. The trail
  // itself belongs to the tab, so switching tabs switches history with
  // it -- which is the behaviour of every browser and needs no
  // explaining.
  const tab = current();
  const nav = document.createElement("div");
  nav.className = "navpair";
  nav.innerHTML = `
    <button class="navb" data-step="-1" title="Back"${canStep(tab, -1) ? "" : " disabled"}>&#8249;</button>
    <button class="navb" data-step="1" title="Forward"${canStep(tab, 1) ? "" : " disabled"}>&#8250;</button>`;
  nav.querySelectorAll("[data-step]").forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); step(current(), Number(b.dataset.step)); };
  });
  strip.insertBefore(nav, strip.firstChild);

  state.tabs.forEach((tab) => {
    const el = document.createElement("div");
    // One class per room, so a glance at the strip says what kind of
    // thing each tab is before you read the name on it.
    const room = roomOf(tab);
    const v = VIEWS[room] || {};
    el.className = `tab t-${room}` + (tab.id === state.active ? " active" : "");
    const q = tab.data?.quote;
    const chg = q?.change_pct;
    el.innerHTML =
      (tab.status === "ready" ? `<span class="livedot ${tab.live ? "" : "off"}"></span>` : "") +
      `<span class="sym">${esc(tab.symbol || v.name?.(tab) || ROOMS[room]?.label || "")}</span>` +
      (v.badge?.(tab) ? `<span class="chg dim">${esc(v.badge(tab))}</span>` : "") +
      (tab.status === "loading" ? `<span class="chg dim">...</span>` : "") +
      (q?.price ? `<span class="px">${money(q.price)}</span>` : "") +
      (chg !== undefined && chg !== null ? `<span class="chg ${sign(chg)}">${signed(chg, 2)}</span>` : "") +
      `<span class="x" title="Close">&times;</span>`;
    el.onclick = () => { state.active = tab.id; render(); };
    el.querySelector(".x").onclick = (e) => closeTab(tab.id, e);
    strip.insertBefore(el, plus);
  });

  setTitle(current());
}


/* The three other rooms.
 *
 * The front page was a search field and two sentences, and the
 * sentences were doing too much work: "I am already in a trade" is a
 * mood, not a destination, and it was the only way to reach either the
 * workshop or the log. Naming the three places plainly is shorter and
 * says where each one goes.
 *
 * Kept quiet on purpose. The search field is still the point of this
 * page -- these sit under it at label size, with the log carrying a
 * count only when there is something in it, which is the one piece of
 * information a door can usefully show before you walk through it. */
function renderDoors() {
  const open = bookOpen(loadBook()).length;
  // The same three rooms, the same names and the same hues as the nav
  // that sits in every other tab -- the front page is one more place
  // on the ring, not a different menu with its own vocabulary.
  return `<div class="doors">
    ${["finder", "position", "log", "world"].map((id) => `
      <button class="door d-${id}" data-room="${id}">
        <span class="dn">${esc(ROOMS[id].label)}${
          id === "log" && open ? `<i class="dcount">${open}</i>` : ""}</span>
        <span class="dw">${esc(ROOMS[id].what)}</span>
      </button>`).join("")}
  </div>`;
}

/** The front page is the logo and the search field. Nothing else. */
function renderLauncher() {
  return `<div class="launcher">
      <h1>QUIPU</h1>
      <div class="searchwrap">
        <div class="searchbox">
          <input id="q" placeholder="Company name or ticker" autocomplete="off" spellcheck="false">
          <button id="go">Search</button>
        </div>
        <div class="suggest" id="suggest" style="display:none"></div>
      </div>
      <div class="quick">
        ${["NVDA", "AAPL", "TSLA", "AMD", "SPY", "MSFT"].map((s) => `<span data-s="${s}">${s}</span>`).join("")}
      </div>
      ${renderDoors()}
    </div>`;
}

function render(keepScroll = false) {
  // Note where we are before drawing it, so the trail is written by the
  // act of arriving rather than by every control having to remember.
  markPlace(current());
  renderTabs();
  const view = document.getElementById("viewport");
  const scroll = keepScroll ? view.scrollTop : 0;
  const tab = current();

  if (!tab || tab.status === "blank") { view.innerHTML = renderLauncher(); wireLauncher(); return; }

  const v = VIEWS[roomOf(tab)];
  if (v.show) { v.show(tab, view, scroll); return; }
  view.innerHTML = v.draw(tab);
  gloss(view);
  v.wire(tab);
  view.scrollTop = scroll;
  // Whatever squares this room drew are filled to their edges.
  window.QUIPU_FILL?.all();
}

/* ---- wiring ---------------------------------------------------------- */

function wireLauncher() {
  const input = document.getElementById("q");
  if (!input) return;
  input.focus();
  const submit = () => {
    if (suggestOn >= 0 && suggestions[suggestOn]) pick(suggestions[suggestOn].symbol);
    else if (suggestions.length && !/^[A-Za-z.\-]{1,5}$/.test(input.value.trim())) pick(suggestions[0].symbol);
    else search(input.value);
  };
  document.getElementById("go").onclick = submit;
  input.oninput = () => {
    clearTimeout(suggestTimer);
    const q = input.value;
    suggestTimer = setTimeout(() => fetchSuggestions(q), 220);
  };
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); suggestOn = Math.min(suggestOn + 1, suggestions.length - 1); paintSuggestions(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); suggestOn = Math.max(suggestOn - 1, -1); paintSuggestions(); }
    else if (e.key === "Enter") submit();
    else if (e.key === "Escape") { suggestions = []; paintSuggestions(); }
  };
  document.querySelectorAll(".quick span").forEach((el) => { el.onclick = () => pick(el.dataset.s); });
  wireRooms();
}
