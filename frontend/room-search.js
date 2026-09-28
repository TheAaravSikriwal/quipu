/* Room: Search -- one company, everything on it.
 *
 * Loading and live-refreshing a ticker, every dashboard tile, the
 * zoomed panel, the packer, the rail, and the price chart.
 */

async function load(tab) {
  tab.status = "loading";
  tab.error = null;
  render();
  // The four steps are their own request, started alongside rather than
  // after: they need none of the news and filings the page waits for.
  tab.course = null;
  window.QUIPU_COURSE?.load(tab);
  try {
    const res = await fetch(`${API}/api/ticker/${encodeURIComponent(tab.symbol)}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    tab.data = await res.json();
    tab.status = "ready";
    tab.lastLive = new Date();
    tab.ui.strike = null;
    tab.ui.introDone = false;
  } catch (err) {
    tab.error = err.message;
    tab.status = "error";
  }
  render();
  if (tab.status === "ready") {
    tripSetup(tab);
    refreshWire(tab);
    refreshInstant(tab);
  }
}

async function refreshLive(tab, manual = false) {
  if (!tab || tab.status !== "ready" || tab.refreshing) return;
  if (!manual && !tab.live) return;
  tab.refreshing = true;
  try {
    const res = await fetch(`${API}/api/live/${encodeURIComponent(tab.symbol)}`);
    if (!res.ok) throw new Error(res.status);
    const live = await res.json();
    if (live.quote?.price) tab.data.quote = live.quote;
    if (live.intraday?.points?.length) tab.data.intraday = live.intraday;
    if (live.series_1d?.points?.length) {
      tab.data.series_1d = live.series_1d;
      if (tab.data.series) tab.data.series["1D"] = live.series_1d;
    }
    if (live.options?.available) {
      const fresh = live.options.expiries || [];
      const kept = tab.data.options?.expiries || [];
      tab.data.options = {
        ...live.options,
        expiries: fresh.concat(kept.slice(fresh.length)),
        all_expiries: tab.data.options?.all_expiries || live.options.all_expiries,
      };
    }
    tab.lastLive = new Date();
    tab.liveMs = live.ms;
    tab.liveError = null;
    tripwires(tab);
  } catch (err) {
    tab.liveError = String(err.message || err);
  }
  tab.refreshing = false;
  if (state.active === tab.id) patchLive(tab);
  refreshWire(tab);
}

/* ---- the lights: which sources answered -------------------------------
 *
 * One light per data source along the bottom of the page, green if it
 * answered and red if it did not, read from the engine's own record of
 * every request it made (wire.py). A source this search had no reason
 * to ask is checked by the engine instead, so every light is a real
 * answer rather than a guess. Hover one for when, and what came back. */

async function refreshWire(tab) {
  if (tab.wireBusy) return;
  tab.wireBusy = true;
  try {
    const res = await fetch(`${API}/api/sources`);
    if (!res.ok) throw new Error(res.status);
    tab.wire = await res.json();
  } catch {
    return;                  // keep the last reading; the next tick tries again
  } finally {
    tab.wireBusy = false;
  }
  if (state.active !== tab.id) return;
  const el = document.querySelector(".wirebar");
  if (el) el.outerHTML = wireBar(tab);
}

function wireAgo(s) {
  if (s == null) return "";
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
}

function wireNote(r) {
  if (r.ok) {
    return `${r.name}: answered${r.code ? ` (HTTP ${r.code})` : ""} ${wireAgo(r.ago)}`
      + (r.via === "check" ? ", on a status check" : ", fetching for this page");
  }
  return `${r.name}: ${r.error || "no answer"}${r.ago != null ? `, ${wireAgo(r.ago)}` : ""}`;
}

function wireBar(tab) {
  const rows = tab.wire?.sources;
  const up = rows ? rows.filter((r) => r.ok).length : 0;
  return `<div class="wirebar" role="status" aria-label="Data sources reached">
    <span class="wb-head">Sources ${rows ? `<b>${up}/${rows.length}</b>` : ""}</span>
    ${rows
      ? rows.map((r) => `<span class="wb-src ${r.ok ? "ok" : "bad"}" title="${esc(wireNote(r))}">
          <i class="led" aria-label="${r.ok ? "reached" : "not reached"}"></i>${esc(r.name)}</span>`).join("")
      : `<span class="wb-wait">checking each source&hellip;</span>`}
  </div>`;
}

/* ---- Instant: what lands first ------------------------------------------
 *
 * The Wire reads aggregators every ninety seconds, and an aggregator runs
 * a story after the wire does -- usually after the price has moved on it.
 * This panel asks the engine every four seconds what the feeds that
 * publish FIRST have turned up (instant.py: Alpaca's news stream, SEC
 * filings, the press wires, the last hour of Google News), and shows how
 * many seconds after publication each one got here.
 *
 * It also raises its own alarms, because no free feed reliably beats the
 * tape: the price or the volume moving before any headline explains it,
 * and a contract suddenly trading far past its open interest. Those are
 * worked out here, from numbers the live refresh already brings. */

const INSTANT_MS = 4000;
const IN_KIND = { news: "Wire", filing: "Filing", release: "Press release", web: "News", move: "Move" };
let IN_ALERTS = localStorage.getItem("quipu.instantAlerts") === "on";
let IN_AUDIO = null;

function instantState(tab) {
  return (tab.instant ||= { seq: 0, events: [], feeds: [], stream: null, loaded: false });
}

function instantSort(st) {
  st.events.sort((a, b) => (b.published || b.received) - (a.published || a.received));
  if (st.events.length > 150) st.events.length = 150;
}

async function refreshInstant(tab) {
  if (!tab?.symbol || tab.status !== "ready" || tab.instantBusy) return;
  const st = instantState(tab);
  tab.instantBusy = true;
  try {
    const company = tab.data?.quote?.name || "";
    const res = await fetch(`${API}/api/instant/${encodeURIComponent(tab.symbol)}`
      + `?after=${st.seq}&company=${encodeURIComponent(company)}`);
    if (!res.ok) throw new Error(res.status);
    const body = await res.json();
    // The first answer can hold things another tab saw arrive; only what
    // lands while this one is watching is worth a sound.
    const quiet = !st.loaded;
    for (const ev of body.events || []) {
      const i = st.events.findIndex((e) => e.id === ev.id);
      if (i >= 0) st.events[i] = { ...st.events[i], ...ev };
      else {
        st.events.push(ev);
        // A passing mention is listed, never rung: a market roundup that
        // names the company once is not a reason to look up.
        if (ev.fresh && !quiet && ev.about !== false) instantAlert(tab, ev);
      }
    }
    st.seq = body.seq;
    st.feeds = body.feeds || [];
    st.stream = body.stream;
    st.name = body.name;
    st.loaded = true;
    instantSort(st);
  } catch {
    return;                  // the next poll is four seconds away
  } finally {
    tab.instantBusy = false;
  }
  paintInstant(tab);
}

function paintInstant(tab) {
  if (state.active !== tab.id || !tab.data) return;
  if (document.querySelector('.tile[data-tile="instant"]')) {
    instantTile(tab.data, tab);
    setTileBody("instant");
  }
  if (tab.ui.zoom === "instant") {
    const inner = document.querySelector(".zoom .inner");
    if (inner) inner.innerHTML = DETAIL.instant(tab.data, tab);
  }
}

const inLag = (s) => (s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`);

function instantRow(ev, full = false) {
  const t = new Date((ev.published || ev.received) * 1000);
  const clock = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", ...(ev.fresh ? { second: "2-digit" } : {}) });
  const stamp = t.toDateString() === new Date().toDateString()
    ? clock : `${t.toLocaleDateString([], { month: "short", day: "numeric" })} ${clock}`;
  const lag = ev.lag != null
    ? `<span class="in-lag" title="Time between the source publishing it and QUIPU having it">+${inLag(ev.lag)}</span>` : "";
  const kind = ev.kind === "filing" && ev.form ? ev.form : IN_KIND[ev.kind] || ev.kind;
  const src = ev.via ? `${ev.source} via ${ev.via}` : ev.source;
  const link = safeUrl(ev.url);
  return `<div class="in-row k-${esc(ev.kind)}${ev.fresh ? " fresh" : ""}${ev.important ? " hot" : ""}">
    <div class="in-meta"><span class="in-kind">${esc(kind)}</span><span class="in-src">${esc(src)}</span>
      <span class="in-when">${esc(stamp)}${lag}</span></div>
    ${link !== "#" ? `<a class="in-title" href="${link}" target="_blank" rel="noopener">${esc(ev.title)}</a>`
                   : `<div class="in-title">${esc(ev.title)}</div>`}
    ${full && ev.summary ? `<div class="in-sum">${esc(ev.summary)}</div>` : ""}
    ${ev.also?.length ? `<div class="in-also">also ${ev.also.map((a) =>
      esc(a.source) + (a.lag != null ? ` +${inLag(a.lag)}` : "")).join(", ")}</div>` : ""}
  </div>`;
}

function instantHead(st) {
  return `<div class="in-head"><span class="in-feeds">${st.feeds.map((f) =>
      `<span class="in-feed ${f.ok ? "ok" : "bad"}" title="${esc(f.name)}: ${esc(f.note || "")}"><i class="led"></i>${esc(f.name)}</span>`).join("")}
      <span class="in-feed ok" title="The price, volume and options flow, checked on every refresh"><i class="led"></i>Tripwires</span></span>
    <button class="in-alert${IN_ALERTS ? " on" : ""}" data-in-alert
      title="A sound and a desktop notification when something new lands">${IN_ALERTS ? "Alerts on" : "Alerts off"}</button>
  </div>`;
}

/* Two lists, never one filter. "About" is the company in the headline,
 * its own filing, a story tagged to its ticker or a release with its
 * listing; "mentions" is everything that names it only in the text --
 * a roundup, a sponsorship story, a customer's news. The second can
 * matter as much as the first (the Oracle force majeure headline never
 * said Bloom), so it is shown, just below and without alerts. */
function instantLists(tab, cap = Infinity) {
  const st = instantState(tab);
  const about = st.events.filter((e) => e.about !== false);
  const mentions = st.events.filter((e) => e.about === false);
  const name = st.name || tab.symbol;
  const empty = (what) => `<div class="dim in-empty">${st.loaded ? what : "Connecting to the feeds&hellip;"}</div>`;
  return (about.length ? about.slice(0, cap).map((e) => instantRow(e, cap === Infinity)).join("")
      : empty("Nothing about it in the last three days yet &mdash; anything new appears here the moment it lands."))
    + (mentions.length ? `<div class="in-sub">Mentions ${esc(name)} <span>${mentions.length}</span>
        <em>named in the article, not the headline &mdash; roundups, partners, customers</em></div>
        <div class="in-mentions">${mentions.slice(0, cap).map((e) => instantRow(e, cap === Infinity)).join("")}</div>` : "");
}

function instantTile(d, tab) {
  const st = instantState(tab);
  const live = st.feeds.filter((f) => f.ok).length + 1;
  return tile(
    "instant", "elastic e-claimed t-small", "w2 h3", "Instant",
    instantHead(st) + instantLists(tab, 30),
    `${live} feeds live`);
}

/* ---- alarms ---- */

function instantAlert(tab, ev) {
  if (state.active === tab.id) {
    const el = document.querySelector('.tile[data-tile="instant"]');
    if (el) { el.classList.remove("ping"); void el.offsetWidth; el.classList.add("ping"); }
  }
  if (!IN_ALERTS) return;
  inBeep(ev.important || ev.kind === "move");
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(`${tab.symbol} · ${IN_KIND[ev.kind] || "New"}`,
        { body: ev.title, tag: `quipu-${tab.symbol}-${ev.id}` });
    } catch { /* some browsers only allow these from a service worker */ }
  }
}

function inBeep(urgent) {
  if (!IN_AUDIO) return;
  const now = IN_AUDIO.currentTime;
  (urgent ? [0, 0.17] : [0]).forEach((off) => {
    const o = IN_AUDIO.createOscillator(), g = IN_AUDIO.createGain();
    o.type = "sine";
    o.frequency.value = urgent ? 880 : 660;
    g.gain.setValueAtTime(0.0001, now + off);
    g.gain.exponentialRampToValueAtTime(0.16, now + off + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, now + off + 0.14);
    o.connect(g).connect(IN_AUDIO.destination);
    o.start(now + off);
    o.stop(now + off + 0.15);
  });
}

// A browser only lets a page make sound after the person has clicked on
// it, so the audio is set up on the first click rather than on load.
document.addEventListener("pointerdown", () => {
  if (IN_ALERTS && !IN_AUDIO) IN_AUDIO = new (window.AudioContext || window.webkitAudioContext)();
});

document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-in-alert]")) return;
  IN_ALERTS = !IN_ALERTS;
  localStorage.setItem("quipu.instantAlerts", IN_ALERTS ? "on" : "off");
  if (IN_ALERTS) {
    IN_AUDIO ||= new (window.AudioContext || window.webkitAudioContext)();
    IN_AUDIO.resume?.();
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    inBeep(false);
  }
  document.querySelectorAll("[data-in-alert]").forEach((b) => {
    b.classList.toggle("on", IN_ALERTS);
    b.textContent = IN_ALERTS ? "Alerts on" : "Alerts off";
  });
});

/* ---- tripwires: the move before the story ---- */

const inMedian = (xs) => {
  const s = xs.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
};
const inUnusual = (o) => (o?.expiries || [])
  .flatMap((e) => (e.unusual_activity || []).map((r) => r.contract)).filter(Boolean);

function tripSetup(tab) {
  // What was already unusual when the page opened is on the page; only
  // a contract that turns unusual while it is being watched is news.
  tab.trips = { unusual: new Set(inUnusual(tab.data?.options)), fired: {} };
}

function tripwires(tab) {
  const d = tab.data, trips = tab.trips;
  if (!d || !trips) return;
  const now = Date.now() / 1000;
  const fire = (key, coolS, title) => {
    if (trips.fired[key] && now - trips.fired[key] < coolS) return;
    trips.fired[key] = now;
    const ev = { id: `move:${key}:${Math.round(now)}`, seq: 0, kind: "move", source: "QUIPU tripwire",
      title, url: null, published: now, received: now, lag: null, fresh: true, important: true, also: [] };
    const st = instantState(tab);
    st.events.push(ev);
    instantSort(st);
    instantAlert(tab, ev);
  };

  // Five-minute bars. The last one is still forming, so its close is
  // simply the price now; two bars back is roughly ten minutes ago.
  const pts = d.series_1d?.points || [];
  const price = d.quote?.price;
  if (pts.length >= 5 && price) {
    const move = (price / pts[pts.length - 3].c - 1) * 100;
    const swings = [];
    for (let i = 2; i < pts.length - 1; i++) swings.push(Math.abs(pts[i].c / pts[i - 2].c - 1) * 100);
    // Measured against this stock's own day: 1% in ten minutes is a
    // shock for a utility and a quiet stretch for a small-cap.
    const typical = inMedian(swings) || 0.3;
    if (Math.abs(move) >= Math.max(1.0, typical * 3)) {
      fire(`px${move > 0 ? "up" : "down"}`, 900,
        `${tab.symbol} ${move > 0 ? "up" : "down"} ${Math.abs(move).toFixed(1)}% in about ten minutes, to ${money(price)}. `
        + `A normal ten-minute swing today is ${typical.toFixed(2)}%.`);
    }

    // The opening bar is always heavy and the last is not finished.
    const done = pts.slice(1, -1);
    const last = done[done.length - 1];
    const med = inMedian(done.slice(0, -1).map((p) => p.v).filter((v) => v > 0));
    if (last && med && done.length >= 4 && last.v >= med * 3) {
      fire(`vol:${last.t}`, 1e9,
        `${tab.symbol} volume spike: ${big(last.v)} shares in the ${last.t} bar, ${(last.v / med).toFixed(1)}× a typical five minutes today.`);
    }
  }

  for (const e of d.options?.expiries || []) {
    for (const r of e.unusual_activity || []) {
      if (!r.contract || trips.unusual.has(r.contract)) continue;
      trips.unusual.add(r.contract);
      // The panel lists anything past twice its open interest; an alarm
      // wants more than that, or a busy chain would ring all afternoon.
      if ((r.vol_oi_ratio || 0) < 3 || (r.volume || 0) < 500) continue;
      fire(`opt:${r.contract}`, 1e9,
        `Unusual options: the ${e.expiry} $${r.strike} ${r.type} has traded ${big(r.volume)} against `
        + `${big(r.open_interest)} open (${r.vol_oi_ratio}×), so new positions rather than old ones closing.`);
    }
  }
}

/* Update only what the live endpoint actually changed.
 *
 * This used to call render(), which rebuilt all 25 tiles, re-packed the grid
 * and re-created every chart -- every fifteen seconds. In place is both
 * calmer to look at and keeps chart zoom, scroll position and the open panel
 * exactly where they were. */
function patchLive(tab) {
  const d = tab.data;
  if (!d) return;
  readSources(d);

  ["quote", "instant", "options", "optionstory", "unusual", "vol", "greeks", "chain",
   "pipeline"].forEach((id) => {
    if (!document.querySelector(`.tile[data-tile="${id}"]`)) return;
    switch (id) {
      case "quote": quoteTile(d.quote, tab); break;
      case "instant": instantTile(d, tab); break;
      case "options": optionsTile(d.options); break;
      // The story is written from the chain, so it goes stale with it.
      case "optionstory": optionStoryTile(d, tab); break;
      case "unusual": unusualTile(d.options); break;
      case "vol": volatilityTile(d); break;
      case "greeks": greeksTile(d, tab); break;
      case "chain": chainTile(d, tab); break;
      case "pipeline": pipelineTile(d, tab); break;
    }
    setTileBody(id);
  });

  reWireGreeksTile(tab);
  wireTileControls(tab);
  renderTabs();

  // Today's bars grow through the session. Only the 1D frame can have
  // changed, so only a chart currently showing 1D is worth touching.
  if (PRICE_SERIES && d.series_1d?.points?.length) {
    PRICE_SERIES["1D"] = d.series_1d;
    if (tab.ui.priceRange === "1D") {
      liveCharts.filter((c) => c?.key?.endsWith(":price"))
        .forEach((c) => c.setPoints(d.series_1d.points));
    }
  }

  const bar = document.querySelector(".livebar");
  if (bar) bar.outerHTML = liveBar(tab);
  wireLiveBar(tab);

  // the price in the open panel's header ticks with everything else
  const zp = document.getElementById("zoom-price");
  if (zp) zp.outerHTML = zoomPrice(tab);

  // keep an open panel current without closing it
  if (tab.ui.zoom && DETAIL[tab.ui.zoom]) {
    const inner = document.querySelector(".zoom .inner");
    if (inner) {
      ZOOM_MOUNTS = [];
      inner.innerHTML = DETAIL[tab.ui.zoom](d, tab);
      gloss(inner);
      mountZoomCharts(tab);
      wireZoom(tab);
    }
  }
}

function startClock() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (document.hidden) return;
    const tab = current();
    if (tab && tab.live) refreshLive(tab);
  }, LIVE_MS);

  // Every open company, and even while the window is hidden: an alarm is
  // most use exactly when the page is behind something else.
  if (state.instantTimer) clearInterval(state.instantTimer);
  state.instantTimer = setInterval(() => {
    state.tabs.forEach((t) => {
      if (roomOf(t) === "search" && t.live && t.status === "ready") refreshInstant(t);
    });
  }, INSTANT_MS);

  if (state.newsTimer) clearInterval(state.newsTimer);
  state.newsTimer = setInterval(() => {
    if (document.hidden) return;
    const tab = current();
    if (tab && tab.live && tab.symbol && tab.status === "ready") refreshNews(tab);
  }, NEWS_MS);
}

/* Look for stories that were not there a minute ago.
 *
 * Merged rather than replaced: the list already on the page has
 * extracted bodies attached to some of its entries, and throwing that
 * away every ninety seconds to re-fetch it would be both slower and
 * worse. Anything already present keeps what it has; anything new is
 * added and marked as new until the reader has seen the page settle.
 */
async function refreshNews(tab) {
  if (tab.newsBusy) return;
  tab.newsBusy = true;
  try {
    const company = tab.data?.quote?.name || "";
    const res = await fetch(
      `${API}/api/news/${encodeURIComponent(tab.symbol)}`
      + `?company=${encodeURIComponent(company)}`);
    if (!res.ok) return;
    const body = await res.json();

    const have = tab.data?.news?.articles || [];
    const seen = new Set(have.map((a) => (a.url || "").split("?")[0]));
    const fresh = (body.articles || []).filter(
      (a) => !seen.has((a.url || "").split("?")[0]));

    if (fresh.length) {
      fresh.forEach((a) => { a.is_new = true; });
      tab.data.news = {
        ...(tab.data.news || {}),
        articles: fresh.concat(have),
        discovered: (tab.data.news?.discovered || have.length) + fresh.length,
      };
      tab.newsNew = (tab.newsNew || 0) + fresh.length;
    }
    tab.newsAt = body.at;
    if (state.active === tab.id) render(true);
  } catch {
    /* a missed poll is not an error worth showing: the next one is
       ninety seconds away and the page is still readable */
  } finally {
    tab.newsBusy = false;
  }
}

/* ---- tile helper ----------------------------------------------------- */

/** Footprint of each tile, so the layout can place big ones first. */
let SPANS = {};
let BADGES = {};

const SOURCES = {
  quote: "Yahoo Finance &middot; live",
  price: "Yahoo Finance &middot; 5-minute to daily bars",
  optionstory: "Derived from the chain, the greeks and realised volatility",
  returns: "Yahoo Finance &middot; weekly, 5 years",
  volume: "Yahoo Finance &middot; 90-day tape",
  vol: "Implied: option prices &middot; Realised: computed here",
  options: "Yahoo chains &middot; IV solved locally",
  chain: "Yahoo chains &middot; greeks computed here",
  unusual: "Yahoo chains &middot; volume against open interest",
  greeks: "Black-Scholes, computed here from live quotes",
  profile: "Company filings via Yahoo Finance",
  holdings: "The issuer's own daily file where there is one, Yahoo otherwise",
  financials: "Annual reports via Yahoo Finance",
  secfin: "SEC EDGAR &middot; XBRL, exactly as filed",
  secmargins: "Computed here from the filed figures",
  valuation: "Yahoo Finance &middot; trailing and forward",
  earnings: "Reported results and consensus estimates",
  analysts: "Sell-side consensus via Yahoo Finance",
  ownership: "13F filings via Yahoo Finance",
  short: "Exchange short-interest reports",
  filings: "SEC EDGAR &middot; official, unedited",
  calendar: "SEC filings, company announcements, Federal Reserve and BEA",
  news: "Yahoo, Google News and Finnhub, deduplicated",
  unique: "Cross-referenced across every article read",
  corroborated: "Claims matched across two or more outlets",
  stories: "Articles clustered by event",
  social: "StockTwits &middot; tagged retail posts",
  pipeline: "This run"
};

/* When Yahoo refuses, the quote and the chain come from a backup, and
 * the source line under the masthead has to say which -- it is the one
 * place the page is honest about where a number came from. */
let SOURCE_NOW = {};
const SOURCE_SAYS = {
  "Yahoo Finance chart": "Yahoo Finance chart &middot; live",
  "Nasdaq": "Nasdaq &middot; live",
  "Cboe": "Cboe &middot; 15-minute delayed",
};

function readSources(d) {
  SOURCE_NOW = {};
  const q = d?.quote?.source, o = d?.options?.source;
  if (q && q !== "Yahoo Finance") {
    SOURCE_NOW.quote = `${SOURCE_SAYS[q] || esc(q)} &middot; Yahoo's quote refused`;
  }
  if (o && o !== "Yahoo Finance") {
    SOURCE_NOW.options = `${esc(o)} chains &middot; IV solved locally`;
    SOURCE_NOW.chain = `${esc(o)} chains &middot; greeks computed here`;
    SOURCE_NOW.unusual = `${esc(o)} chains &middot; volume against open interest`;
  }
}

function tile(id, cls, span, title, body, badge = "") {
  const ev = GROUPS.find((g) => cls.includes(g.cls));
  const said = SOURCE_NOW[id] || SOURCES[id];
  const src = said ? `<div class="source">${said}</div>` : "";
  body = src + body;
  BODIES[id] = body;
  TITLES[id] = title;
  const w = Number((span.match(/\bw(\d)\b/) || [, 1])[1]);
  const h = Number((span.match(/\bh(\d)\b/) || [, 1])[1]);
  SPANS[id] = { w, h, area: w * h };
  BADGES[id] = badge;
  return `<div class="tile ${cls} ${span}" data-tile="${id}">
     <h3><span>${title}</span>
       ${ev ? `<span class="cls" title="${CLASS_NOTE[ev.cls]}">${ev.label}</span>` : ""}
       ${badge ? `<span class="badge">${badge}</span>` : ""}</h3>
     <div class="body">${body}</div></div>`;
}

/* How far a panel's contents can be leaned on. Shown as a word in the panel
 * masthead and as line weight on its top rule -- the two say the same thing,
 * once for readers and once for people skimming. The accent colours these
 * carried were dropped with the compass; nothing on this page encodes
 * meaning in hue any more. */
const GROUPS = [
  { cls: "e-filed",   label: "FILED" },
  { cls: "e-priced",  label: "PRICED" },
  { cls: "e-derived", label: "DERIVED" },
  { cls: "e-claimed", label: "CLAIMED" },
];

/* What each class means, shown in the panel masthead and on hover. The label
 * is the design system made legible: the reader should never have to guess
 * how much weight a number deserves. */
const CLASS_NOTE = {
  "e-filed":   "Filed with a regulator. Legally binding and unedited.",
  "e-priced":  "What money actually did. Not an opinion.",
  "e-derived": "Computed by Quipu from the data above. Method stated inside.",
  "e-claimed": "An interested party talking. Read with suspicion.",
};

/* ---- the region rail -------------------------------------------------
 *
 * This replaces a compass rose. The compass indexed evidence class -- FILED,
 * PRICED, DERIVED, CLAIMED -- which is a property of a panel, not a place on
 * the page, so "north" pointed at panels scattered the whole way down it.
 * Pointing somewhere you cannot walk to is not navigation.
 *
 * What a reader actually wants to move between is the four REGIONS the page
 * is already written in, in the order it is meant to be read. The rail names
 * them, marks the one you are in, and jumps to any other -- and because the
 * grid lays tiles out in reading order, every region is one contiguous run.
 */
// Read off the layout, so the rail's regions and the order the tiles
// are drawn in are one list rather than two that have to agree.
// The curriculum's four steps are regions too, after the page's own, so
// the rail and the packer treat them as the four bands they are.
const REGIONS = [...LAYOUT.search, ...(LAYOUT.steps || [])]
  .map((g) => ({ id: g.id, label: g.label, keys: g.panels }));

/* Which region a panel belongs to, by reading order. The packer uses this to
 * keep a region in one run down the page; the rail is useless if "Business"
 * means four places. */
const REGION_OF = {};
REGIONS.forEach((r, i) => r.keys.forEach((k) => { REGION_OF[k] = i; }));

function renderRail() {
  const present = REGIONS
    .map((r) => ({ ...r, n: r.keys.filter((k) => SPANS[k]).length }))
    .filter((r) => r.n);
  if (present.length < 2) return "";
  return `<nav class="rail" id="rail">
    ${present.map((r, i) => `<button data-region="${r.id}">
        <span class="k">${i + 1}</span><span class="l">${r.label}</span>
      </button>`).join("")}
  </nav>`;
}

/* ---- charts ---------------------------------------------------------- */

/* ---- volatility: implied against realised ---------------------------- */

/** The comparison, written out. This is the question every option trade asks. */
function volatilityProse(iv, hv20, hv60, spot, expectedMovePct, expiry, terms) {
  if (iv == null || hv60 == null) {
    return `<div class="prose">Not enough data to compare implied with realised volatility.</div>`;
  }

  const spread = iv - hv60;
  const ratio = iv / hv60;
  const dailyImplied = iv / Math.sqrt(252);
  const dailyRealised = hv60 / Math.sqrt(252);

  let judgement;
  if (spread > 8) {
    judgement = `<b>Options here are expensive.</b> The market is charging
      <b>${nf(spread, 1)} points</b> more than the share price has actually delivered
      &mdash; a ratio of <b>${nf(ratio, 2)}&times;</b>. If the stock keeps behaving the way it
      has, option buyers lose that premium to time decay and sellers collect it. Something is
      expected: earnings, a ruling, a product launch. Worth finding out what before buying.`;
  } else if (spread < -5) {
    judgement = `<b>Options here are cheap.</b> The market is pricing
      <b>${nf(Math.abs(spread), 1)} points less</b> movement than the stock has actually been
      delivering. If recent behaviour continues, buyers are getting the move for less than it
      has been worth &mdash; the rarer and more interesting side of this comparison.`;
  } else {
    judgement = `<b>Options are priced about right.</b> Implied and realised are within
      <b>${nf(Math.abs(spread), 1)} points</b> of each other, so the market is charging roughly
      what the stock has been delivering. No edge either way from volatility alone.`;
  }

  let trend = "";
  if (hv20 != null) {
    const d = hv20 - hv60;
    if (d > 6) {
      trend = `The stock is <b>getting choppier</b>: <b>${nf(hv20, 1)}%</b> over the last month
        against <b>${nf(hv60, 1)}%</b> over three. Implied volatility may be catching up to
        reality rather than overcharging for it.`;
    } else if (d < -6) {
      trend = `The stock is <b>calming down</b>: <b>${nf(hv20, 1)}%</b> over the last month
        against <b>${nf(hv60, 1)}%</b> over three. That makes the implied premium look wider
        still, and favours sellers of premium.`;
    } else {
      trend = `Recent behaviour is steady &mdash; <b>${nf(hv20, 1)}%</b> over a month against
        <b>${nf(hv60, 1)}%</b> over three.`;
    }
  }

  let structure = "";
  if (terms && terms.length > 1) {
    const near = terms[0], far = terms[terms.length - 1];
    if (near.iv != null && far.iv != null) {
      if (near.iv - far.iv > 4) {
        structure = `Near-dated options cost more than later ones
          (<b>${nf(near.iv, 1)}%</b> for ${near.days}d against <b>${nf(far.iv, 1)}%</b> for
          ${far.days}d). That inversion almost always means a dated event inside the near
          window &mdash; the market is paying up to be covered for one specific day.`;
      } else if (far.iv - near.iv > 4) {
        structure = `Volatility rises with time (<b>${nf(near.iv, 1)}%</b> at ${near.days}d
          to <b>${nf(far.iv, 1)}%</b> at ${far.days}d), which is the normal, calm shape: more
          time, more that can go wrong, no single event dominating.`;
      } else {
        structure = `The term structure is flat, so the market is not singling out any
          particular date.`;
      }
    }
  }

  return `<div class="prose">
    <p>Implied volatility is the market's forecast: at <b>${nf(iv, 1)}%</b> a year, it expects
    this share price to swing about <b>${nf(dailyImplied, 2)}% a day</b>. Realised volatility is
    what actually happened: <b>${nf(hv60, 1)}%</b> a year over the last three months, or about
    <b>${nf(dailyRealised, 2)}% a day</b>.</p>
    <p>${judgement}</p>
    ${trend ? `<p>${trend}</p>` : ""}
    ${structure ? `<p>${structure}</p>` : ""}
    ${expectedMovePct != null && spot
      ? `<p>For the <b>${esc(expiry)}</b> expiry the options market is pricing a move of
         <b>&plusmn;${nf(expectedMovePct, 2)}%</b> &mdash; about
         <b>${money(spot * expectedMovePct / 100)}</b> either way from ${money(spot)}. That is
         the break-even a straddle buyer needs just to cover the premium.</p>` : ""}
  </div>`;
}

function volTerms(o) {
  return (o?.expiries || []).map((e) => ({ expiry: e.expiry, days: e.days_to_expiry, iv: e.stats.atm_iv }));
}

/* ---- the options story -----------------------------------------------
 *
 * A chain hands you forty numbers and no order to read them in, so most of
 * them get skipped. This is the order: one question per step, the number
 * that answers it, and what that number does to a position. Read it top to
 * bottom and you finish with a view; read step five alone and you finish
 * with a statistic.
 *
 * Every step carries two versions of the prose -- one line for the panel,
 * the full argument for the close-up -- because the same sentence cannot do
 * both jobs well.
 */
function buildOptionStory(d, tab) {
  const o = d.options;
  if (!o?.available || !o.expiries?.length) return null;
  const exp = o.expiries[Math.min(tab.ui.expiryIdx || 0, o.expiries.length - 1)];
  if (!exp) return null;

  const st = exp.stats || {};
  const pr = exp.probability || {};
  const vp = d.volume || {};
  const spot = o.spot || d.quote?.price;
  const steps = [];
  const push = (head, figure, short, long) => steps.push({ head, figure, short, long });

  /* 1 -- the clock, because every other number on this panel is measured
   * against it and means nothing without it. */
  push(
    "One date",
    `${exp.days_to_expiry}d`,
    `Everything below is about <b>${esc(exp.expiry)}</b> &mdash;
     ${plural(exp.days_to_expiry, "calendar day")}, ${plural(exp.trading_days, "trading day")}.`,
    `Everything below is about a single date: <b>${esc(exp.expiry)}</b>. That is
     <b>${plural(exp.days_to_expiry, "calendar day")}</b> away but only
     <b>${plural(exp.trading_days, "trading day")}</b>, and trading days are the ones that price
     an option. A weekend takes no premium out of
     it, which is why a Friday-to-Monday hold feels free and a five-session week does not.`
  );

  /* 2 -- what the market has already agreed the move will be. Any trade is
   * a disagreement with this number, so it comes before any opinion. */
  if (st.expected_move_pct && spot) {
    const lo = spot * (1 - st.expected_move_pct / 100);
    const hi = spot * (1 + st.expected_move_pct / 100);
    push(
      "The move already priced in",
      `&plusmn;${nf(st.expected_move_pct, 2)}%`,
      `The at-the-money straddle costs <b>${money(st.straddle_price)}</b> &rarr;
       <b>${money(lo)} to ${money(hi)}</b> by expiry.`,
      `The at-the-money call and put together cost <b>${money(st.straddle_price)}</b>. Owning both
       is a bet on movement in either direction, so their combined price is what the market charges
       for the move itself: <b>&plusmn;${nf(st.expected_move_pct, 2)}%</b>, or roughly
       <b>${money(lo)} to ${money(hi)}</b> by ${esc(exp.expiry)}. Every trade below is a
       disagreement with that range &mdash; you are saying it is too wide, too narrow, or
       mis-centred. If you have no disagreement with it, there is no trade here.`
    );
  }

  /* 3 -- the price of that move, which is the only question that decides
   * whether you want to be the buyer or the seller. */
  const iv = st.atm_iv;
  const hv = vp.realised_vol_20d ?? vp.realised_vol_60d ?? vp.realised_vol_annual;
  if (iv != null && hv != null) {
    const gap = iv - hv;
    const dear = gap > 4, cheap = gap < -4;
    push(
      "Is that move cheap or dear",
      `${gap > 0 ? "+" : ""}${nf(gap, 1)} pts`,
      `Implied <b>${pct(iv, 1)}</b> against a realised <b>${pct(hv, 1)}</b> &mdash;
       options are <b>${dear ? "expensive" : cheap ? "cheap" : "fairly priced"}</b>.`,
      `Options are implying <b>${pct(iv, 1)}</b> annualised volatility. Over the last twenty
       sessions the stock actually delivered <b>${pct(hv, 1)}</b>. The
       <b>${nf(Math.abs(gap), 1)}-point</b> gap is the whole trade.
       ${dear
        ? `You would be <b>paying</b> for more movement than this stock has been producing, so
           buying needs it to break its recent habit. Selling is being paid for that habit
           continuing.`
        : cheap
        ? `You would be <b>paying less</b> than the stock has recently delivered &mdash; the
           rarer and more interesting side. Buying only needs the recent past to repeat.`
        : `Neither side is being obviously overpaid; this is close to a fair fight, which means
           the edge has to come from direction or timing rather than from the price of
           volatility.`}
       ${vp.avg_daily_move_pct ? `For scale, an average day here moves
        <b>${pct(vp.avg_daily_move_pct, 2)}</b>.` : ""}`
    );
  }

  /* 4 -- the odds, stated as a distribution rather than a target price. */
  if (pr.available && pr.one_sigma) {
    push(
      "Where it probably lands",
      `${nf(pr.p_above_spot, 1)}%`,
      `Two in three outcomes fall between <b>${money(pr.one_sigma.low)}</b> and
       <b>${money(pr.one_sigma.high)}</b>. Median <b>${money(pr.median)}</b>.`,
      `On the model's own terms there is a <b>${nf(pr.p_above_spot, 1)}%</b> chance of finishing
       above today's ${money(spot)}. About two outcomes in three land between
       <b>${money(pr.one_sigma.low)}</b> and <b>${money(pr.one_sigma.high)}</b>; nineteen in
       twenty between <b>${money(pr.two_sigma.low)}</b> and <b>${money(pr.two_sigma.high)}</b>.
       The median outcome is <b>${money(pr.median)}</b>. That is not a forecast &mdash; it is
       what a lognormal distribution with this volatility and this drift does, and it is the
       honest baseline any opinion of yours has to beat.`
    );
  }

  /* 5 -- touch against finish. The single most common way a directional
   * option buyer is right and loses anyway. */
  /* Pick the rung that actually demonstrates the point rather than a fixed
   * +5%. On a one-day expiry a 5% move is a 0.0% / 0.0% row -- true, and
   * useless as an illustration. The widest gap between touching and
   * finishing is the rung this step exists to show. Upside rungs only:
   * above a lower strike, "finishes above" is not "finishes past it". */
  const rung = (pr.ladder || [])
    .filter((r) => r.move_pct > 0 && r.p_touch != null && r.p_touch >= 2
                   && r.p_finish_above != null)
    .sort((a, b) => (b.p_touch - b.p_finish_above) - (a.p_touch - a.p_finish_above))[0];
  if (rung) {
    push(
      "Touching it is not closing there",
      `${nf(rung.p_touch, 0)}% vs ${nf(rung.p_finish_above, 0)}%`,
      `<b>${nf(rung.p_touch, 0)}%</b> chance it ever trades ${money(rung.price)};
       only <b>${nf(rung.p_finish_above, 0)}%</b> that it closes above it.`,
      `There is a <b>${nf(rung.p_touch, 0)}%</b> chance the price touches
       <b>${money(rung.price)}</b> (${signed(rung.move_pct, 1)}) at some point before expiry, but
       only a <b>${nf(rung.p_finish_above, 0)}%</b> chance it is still above that line at the
       close on ${esc(exp.expiry)}. A path can cross a level and come back, which is why the
       first number is close to double the second. This gap is the difference between a trade you
       manage and a trade you hold: if you intend to sell into strength, the touch number is
       yours. If you intend to hold to expiry, only the finish number counts, and most people
       quietly use the first to justify a position they then hold under the second.`
    );
  }

  /* 6 -- positioning. Flow against inventory, which is a different question
   * from either one alone. */
  if (st.put_call_volume_ratio != null) {
    const flow = st.put_call_volume_ratio;
    const book = st.put_call_oi_ratio;
    const busier = book != null && flow > book * 1.2;
    const quieter = book != null && flow < book * 0.8;
    push(
      "Who is positioned where",
      `${nf(flow, 2)} P/C`,
      `<b>${big(st.call_volume)}</b> calls against <b>${big(st.put_volume)}</b> puts today
       ${book != null ? `&mdash; open interest sits at <b>${nf(book, 2)}</b>` : ""}.`,
      `Today's flow is <b>${nf(flow, 2)}</b> puts for every call:
       <b>${big(st.call_volume)}</b> call contracts against <b>${big(st.put_volume)}</b> puts.
       ${book != null
        ? `The positions already on the books run at <b>${nf(book, 2)}</b>.
           ${busier
            ? `Today is <b>more put-heavy than the standing book</b> &mdash; new defensive
               opinion arriving, not just existing hedges being rolled.`
            : quieter
            ? `Today is <b>more call-heavy than the standing book</b> &mdash; new upside
               opinion arriving against a more cautious existing position.`
            : `Today looks like the book it is trading against, so this is maintenance rather
               than a change of mind.`}`
        : `Open interest is not being reported for this expiry, so there is no standing book to
           compare today's flow against.`}
       Read volume as opinion arriving and open interest as opinion already held; the interesting
       signal is when they disagree.`
    );
  }

  /* 7 -- max pain, stated for what it is rather than as a prophecy. */
  if (st.max_pain && spot) {
    const away = ((st.max_pain / spot) - 1) * 100;
    push(
      "Where the sellers would like it to finish",
      money(st.max_pain),
      `Most contract value expires worthless at <b>${money(st.max_pain)}</b>,
       <b>${signed(away, 1)}</b> from here.`,
      `<b>${money(st.max_pain)}</b> is the strike at which the largest amount of option value
       expires worthless &mdash; <b>${signed(away, 1)}</b> from today's price. It is not a magnet
       and there is no mechanism that drags price toward it, whatever the folklore says. What it
       genuinely tells you is where the people who <i>sold</i> these contracts are collectively
       most comfortable, which is useful context for how hard a move past it might be defended.`
    );
  }

  /* 8 -- the loudest single line, because one outsized trade often explains
   * everything above it. */
  const loud = (exp.unusual_activity || [])[0];
  if (loud) {
    push(
      "The loudest line today",
      `${loud.type === "put" ? "Put" : "Call"} ${nf(loud.strike, 1)}`,
      `<b>${big(loud.volume)}</b> traded against <b>${big(loud.open_interest)}</b> open
       &mdash; <b>${nf(loud.vol_oi_ratio, 1)}&times;</b> the existing position.`,
      `The busiest contract relative to what already existed is the
       <b>${money(loud.strike)} ${esc(loud.type || "")}</b>: <b>${big(loud.volume)}</b> contracts
       traded today against <b>${big(loud.open_interest)}</b> held going in, a ratio of
       <b>${nf(loud.vol_oi_ratio, 1)}&times;</b>. Volume far above open interest means the
       position was <b>opened today</b> rather than closed &mdash; someone put on a new view in
       size. It does not tell you which way they lean (a bought call and a sold call print
       identically), but it tells you where the argument is happening.`
    );
  }

  /* 9 -- the bill, in dollars, on a position you could actually place. This
   * is the step that turns every greek above into money. */
  const atm = (exp.calls || [])
    .filter((c) => c.delta != null && (c.mark || c.last))
    .sort((a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot))[0];
  if (atm) {
    const prem = atm.mark || atm.last;
    const cost = prem * 100;
    const daily = Math.abs(atm.theta || 0) * 100;
    /* Quote decay over a horizon the option actually has. "A week" on a
     * contract expiring tomorrow is a bigger number than the contract
     * costs, which reads as nonsense rather than as urgency. */
    const hz = Math.max(1, Math.min(7, exp.trading_days || 7));
    const hzWord = hz >= 7 ? "a week" : hz === 1 ? "its last day" : `its last ${hz} days`;
    const overHz = daily * hz;
    // How far the stock must travel just to pay for that decay.
    const need = atm.delta ? overHz / (atm.delta * 100) : null;
    push(
      "What one contract actually costs you",
      G.usd0(cost),
      `One ${money(atm.strike)} call costs <b>${G.usd0(cost)}</b> and bleeds
       <b>${G.usd0(daily)}</b> a day.`,
      `Buying one <b>${money(atm.strike)}</b> call costs <b>${G.usd0(cost)}</b>
       (${money(prem)} &times; 100 shares). Time alone takes about <b>${G.usd0(daily)}</b> out of
       it per trading day${hz > 1 ? `, or <b>${G.usd0(overHz)}</b> over ${hzWord}` : ""}
       &mdash; whether or not anything happens.
       Its delta of <b>${nf(atm.delta, 3)}</b> means the contract behaves like
       <b>${nf(Math.abs(atm.delta) * 100, 0)} shares</b>, so it gains roughly
       <b>${G.usd0(Math.abs(atm.delta) * 100)}</b> on the first dollar the stock rises. Its gamma
       of <b>${nf(atm.gamma, 4)}</b> is how fast that changes: every dollar higher adds about
       <b>${x100(atm.gamma, 1)} more shares</b> of exposure, and every dollar lower takes the
       same away. The position speeds up as it works and stalls as it fails.
       ${need ? `Put together: the stock has to travel about <b>${money(need)}</b>
        (${pct((need / spot) * 100, 1)}) in your favour over ${hzWord} just to break even against
        decay. That is the number to hold against the
        &plusmn;${nf(st.expected_move_pct || 0, 2)}% the market is already pricing &mdash; if the
        break-even move is larger than the expected one, you are paying for an outcome the chain
        itself says is unlikely.` : ""}`
    );
  }

  return { exp, steps, spot };
}

const storyStep = (n, s, full) => `
  <div class="sstep">
    <span class="sn">${n}</span>
    <div class="sbody">
      <h5>${s.head}</h5>
      ${s.figure ? `<div class="sfig">${s.figure}</div>` : ""}
      <p>${full ? s.long : s.short}</p>
    </div>
  </div>`;

function optionStoryTile(d, tab) {
  const story = buildOptionStory(d, tab);
  if (!story || story.steps.length < 3) return "";
  return tile(
    "optionstory", "elastic e-derived t-small", "w2 h5", "Read the options in this order",
    `<div class="story-steps">
      ${story.steps.map((s, i) => storyStep(i + 1, s, false)).join("")}
     </div>
     <div class="dim" style="font-size:11.5px;margin-top:8px">Click for the full reasoning</div>`,
    esc(story.exp.expiry)
  );
}

function volatilityTile(d) {
  const o = d.options, v = d.volume;
  const iv = o?.expiries?.[0]?.stats?.atm_iv ?? null;
  const hv60 = v?.realised_vol_60d ?? v?.realised_vol_annual ?? null;
  const hv20 = v?.realised_vol_20d ?? null;

  if (iv == null && hv60 == null) return "";

  // Which realised window the verdict is measured against.
  //
  // This tile used to compare implied against the SIXTY-day figure
  // while the option board compared it against the TWENTY-day one, and
  // neither said so. On Apple that put "options cheap, -5.7" directly
  // above a board calling the same contracts +1.5 dear: one comparison,
  // two windows, opposite answers, no way for a reader to tell why.
  //
  // Twenty sessions wins because it is the nearer description of what
  // the share is doing now, and because a board a few days from expiry
  // has no business being judged against a quarter of history. Sixty
  // stays on screen underneath -- on Apple it reads 28.9% against 21.8%,
  // which is not noise, it is an old shock still inside the window, and
  // that is worth seeing rather than hiding.
  const hv = hv20 ?? hv60;
  const hvWin = hv20 != null ? "20" : "60";

  const spread = iv != null && hv != null ? iv - hv : null;
  const scale = Math.max(iv || 0, hv60 || 0, hv20 || 0, 40) * 1.35;

  const bar = (label, value, cls) => `
    <div class="volbar">
      <div class="track"><div class="fill ${cls}" style="width:${Math.min((value / scale) * 100, 100).toFixed(1)}%;
        ${cls === "hv" ? "background:var(--rule2)" : ""}"></div></div>
      <div class="lab"><span>${label}</span><span>${pct(value, 1)}</span></div>
    </div>`;

  return tile(
    "vol", "elastic e-derived m-heavy t-hero", "w2 h3", "Implied vs realised",
    `<div class="figure ${spread > 0 ? "down" : "up"}">${spread == null ? "--" : (spread > 0 ? "+" : "") + nf(spread, 1)}</div>
     <div class="unitline">points of premium in the options${
       hv == null ? "" : `, against ${hvWin} sessions of realised`}</div>
     ${iv != null ? bar("Implied &mdash; what options charge", iv, "iv") : ""}
     ${hv != null ? bar(`Realised &mdash; what the stock did, ${hvWin} sessions`, hv, "hv") : ""}
     ${kv("implied, at the money", pct(iv, 1))}
     ${kv(`realised, 20 days${hvWin === "20" ? " &mdash; the one compared" : ""}`, pct(hv20, 1))}
     ${kv("realised, 60 days", pct(hv60, 1))}
     ${kv("ratio", spread == null ? "--" : nf(iv / hv, 2) + "×", spread > 8 ? "down" : spread < -5 ? "up" : "")}
     ${kv("average day", pct(v?.avg_daily_move_pct, 2))}
     ${kv("biggest day, 90d", `${signed(v?.biggest_up_day_pct, 1)} / ${signed(v?.biggest_down_day_pct, 1)}`)}
     <div class="dim" style="font-size:11.5px;margin-top:6px">Click for what this means</div>`,
    spread == null ? "" : spread > 8 ? "options expensive" : spread < -5 ? "options cheap" : "fairly priced"
  );
}

/* ---- tiles ----------------------------------------------------------- */

function quoteTile(q, tab) {
  if (!q?.price) return tile(
    "quote", "e-priced", "w2", "Quote", `<div class="dim">unavailable</div>`);
  return tile(
    "quote", "e-priced t-hero", "w2 h2", "Quote",
    `<div class="coname">${esc(q.name)}</div>
     <div class="exch">${esc(q.symbol)} &middot; ${esc(q.exchange || "")}</div>
     <div class="price">${money(q.price)}</div>
     <div class="pricechg ${sign(q.change)}">${signed(q.change_pct, 2)}
       <span class="unit">${q.change > 0 ? "+" : ""}${nf(q.change)}</span></div>
     ${kv("day", `${money(q.day_low)} &ndash; ${money(q.day_high)}`)}
     ${kv("52 week", `${money(q.year_low)} &ndash; ${money(q.year_high)}`)}
     ${kv("market cap", big(q.market_cap))}
     ${kv("volume", `${big(q.volume)} of ${big(q.avg_volume)} avg`)}`,
    tab.lastLive ? tab.lastLive.toLocaleTimeString() : ""
  );
}

/* ---- the price chart ------------------------------------------------
 *
 * This was three panels -- today, six months, five years -- which is one
 * series shown at three zoom levels, answering the same question three
 * times. A range switch says all of it, and the two panels that buys back
 * go into making this one large enough to actually interrogate.
 *
 * Every range is already in memory from the first load, so switching costs
 * no network at all; only today's bars are refreshed live, because a daily
 * bar from March is settled and cannot change.
 */

let PRICE_SERIES = null;

function priceChartTile(d, tab) {
  const series = d.series;
  if (!series) return "";
  const ranges = (series.ranges || []).filter((r) => (series[r]?.points || []).length > 1);
  if (!ranges.length) return "";
  PRICE_SERIES = series;

  const sel = ranges.includes(tab.ui.priceRange) ? tab.ui.priceRange
    : ranges.includes(series.default) ? series.default : ranges[ranges.length - 1];
  tab.ui.priceRange = sel;
  const ui = (tab.ui.priceOpts ||= {
    candles: true, log: false, mas: { 20: false, 50: false, 200: false },
    bands: false, osc: null, crosses: false,
  });

  const btn = (label, on, attr) => `<button ${attr} class="${on ? "on" : ""}">${label}</button>`;
  const frame = series[sel] || {};

  // An oscillator needs its own pane, and a pane needs room. At the
  // tile's usual height the chart host is 90px, which after axes leaves
  // 60 -- a fifth of that is 13px of RSI, which is a smear rather than a
  // reading. So turning one on makes the panel taller rather than
  // quietly drawing nothing, which is what it did.
  return tile(
    "price", "elastic e-priced", ui.osc ? "w4 h4" : "w4 h3", "Price",
    `<div class="cbar">
       <div class="cseg">${ranges.map((r) => btn(r, r === sel, `data-prange="${r}"`)).join("")}</div>
       <span class="grow"></span>
       <div class="cseg">
         ${btn("candles", ui.candles, `data-ptool="candles"`)}
         ${btn("log", ui.log, `data-ptool="log"`)}
         ${[20, 50, 200].map((p) => `<button data-pma="${p}" class="${ui.mas[p] ? "on" : ""}"><i class="swatch" style="background:var(--ma${p})"></i>${p}</button>`).join("")}
       </div>
       <div class="cseg">
         ${btn("bands", ui.bands, `data-ptool="bands"`)}
         ${btn("50/200 cross", ui.crosses, `data-ptool="crosses"`)}
         ${btn("RSI", ui.osc === "rsi", `data-posc="rsi"`)}
         ${btn("MACD", ui.osc === "macd", `data-posc="macd"`)}
       </div>
     </div>
     <div class="qchart-host" data-chart="price"></div>
     <div class="indnote" data-pind></div>
     <div class="cstats" data-pstats></div>
     <div class="qchart-hint">drag to zoom &middot; shift-drag to pan &middot; scroll to scale &middot; double-click to reset</div>`,
    signed(frame.change_pct, 2)
  );
}

/* The numbers under the chart describe the VISIBLE window, not the whole
 * range. Zoom into March and the header should be about March, otherwise it
 * is describing a chart you are no longer looking at. */
function paintChartStats(s, label, selector = "[data-pstats]") {
  const host = document.querySelector(selector);
  if (!host) return;
  if (!s) { host.innerHTML = ""; return; }
  host.innerHTML =
    `<span class="k">${esc(label)}${s.zoomed ? " &middot; zoomed" : ""}</span>` +
    `<span>${esc(String(s.from))} &ndash; ${esc(String(s.to))}</span>` +
    `<span>${s.bars} bars</span>` +
    `<span class="${sign(s.changePct)}">${signed(s.changePct, 2)}</span>` +
    `<span>low ${money(s.low)}</span>` +
    `<span>high ${money(s.high)}</span>` +
    (s.avgVol ? `<span>avg vol ${big(s.avgVol)}</span>` : "");
}

function returnsTile(lh) {
  if (!lh?.returns || !Object.keys(lh.returns).length) return "";
  return tile(
    "returns", "elastic e-derived t-small", "w1 h2", "History",
    Object.entries(lh.returns).map(([k, v]) => kv(k, signed(v), sign(v))).join("") +
      `<div style="margin-top:5px;border-top:1px solid var(--rule);padding-top:4px">
        ${kv("all-time high", money(lh.all_time_high))}
        ${kv("off high", signed(lh.off_high_pct), sign(lh.off_high_pct))}</div>`
  );
}

function greeksTile(d, tab) {
  const o = d.options;
  if (!o?.available || !o.expiries?.length) {
    return tile(
    "greeks", "elastic e-derived m-heavy", "w3 h2", "The greeks, in plain English",
      `<div class="prose">${esc(o?.reason
        || "No option chain came back, so there are no greeks to explain.")}</div>`);
  }
  const ui = tab.ui;
  const exp = o.expiries[Math.min(ui.expiryIdx, o.expiries.length - 1)];
  const isCall = ui.side === "call";
  const book = isCall ? exp.calls : exp.puts;
  const spot = o.spot || d.quote?.price;
  const tradable = book.filter((c) => (c.mark || c.last) > 0 && c.delta !== null);

  if (!tradable.length) {
    return tile(
    "greeks", "elastic e-derived m-heavy", "w3 h2", "The greeks, in plain English",
      `<div class="prose">No priced contracts with usable greeks for this expiry &mdash; the vendor
       returned an empty book. Try a different expiry.</div>`);
  }

  const chosen = tradable.find((c) => c.strike === ui.strike) ||
    tradable.reduce((a, b) => (Math.abs(a.strike - spot) <= Math.abs(b.strike - spot) ? a : b));

  const out = G.explainContract(chosen, {
    spot, isCall, days: exp.days_to_expiry, tradingDays: exp.trading_days,
    budget: ui.budget,
    rate: o.risk_free_rate, divYield: o.dividend_yield,
    atmIv: exp.stats.atm_iv, expectedMovePct: exp.stats.expected_move_pct,
  });
  if (!out) return "";

  const expiryOpts = o.expiries.map((e, i) =>
    `<option value="${i}" ${i === ui.expiryIdx ? "selected" : ""}>${e.expiry} (${e.days_to_expiry}d)</option>`).join("");
  const strikeOpts = tradable.map((c) =>
    `<option value="${c.strike}" ${c.strike === chosen.strike ? "selected" : ""}>${nf(c.strike, 1)}${c.itm ? " (ITM)" : ""}</option>`).join("");

  const scen = out.scenarios.map((s) => `<div class="row scen">
      <span>${s.pctMove > 0 ? "+" : ""}${s.pctMove}%</span><span>${money(s.price, 2)}</span>
      <span class="${sign(s.pl)}">${G.usd0(s.pl)}</span>
      <span class="${sign(s.pl)}">${s.plPct > 0 ? "+" : ""}${s.plPct.toFixed(0)}%</span></div>`).join("");

  // The same contract priced two ways. Two models agreeing is information;
  // two models disagreeing is more of it -- the gap is what the right to
  // exercise early is worth, and only the tree can see it.
  const model = tab.ui.model === "tree" ? "tree" : "bs";
  const bin = G.explainBinomial(chosen, out.pos, {
    spot, isCall, tradingDays: exp.trading_days, rate: o.risk_free_rate,
    divYield: o.dividend_yield, atmIv: exp.stats.atm_iv,
  });

  const controls = `<div class="gk-pick">
       <label>expiry</label><select id="gk-exp">${expiryOpts}</select>
       <label>side</label><select id="gk-side">
         <option value="call" ${isCall ? "selected" : ""}>call</option>
         <option value="put" ${!isCall ? "selected" : ""}>put</option></select>
       <label>strike</label><select id="gk-strike">${strikeOpts}</select>
       <label>budget $</label><input id="gk-budget" type="number" min="100" step="100" value="${ui.budget}">
     </div>`;

  const tabs = `<div class="mtabs">
      <button data-model="bs" class="${model === "bs" ? "on" : ""}">Black-Scholes</button>
      <button data-model="tree" class="${model === "tree" ? "on" : ""}">Binomial tree</button>
      <span class="spacer"></span>
      ${bin ? `<span class="note">tree ${G.usd(bin.tree.price)} &middot; market ${G.usd(bin.market)}</span>` : ""}
    </div>`;

  const bsBody = `<div class="gk-head">
       <span class="pos">Buy ${out.pos.contracts} &times; ${nf(chosen.strike, 1)} ${isCall ? "call" : "put"}${out.pos.contracts === 1 ? "" : "s"}</span>
       <span class="cost">${G.usd(out.pos.premium)} &times; 100 &times; ${out.pos.contracts} = <b>${G.usd(out.pos.cost)}</b></span>
     </div>
     ${out.greeks.map((g) => `<div class="gk">
         <div><span class="name">${g.name}</span><span class="val">${g.value}</span></div>
         <div class="say">${g.say}</div></div>`).join("")}
     <div class="verdict">${out.verdict}</div>
     <div style="margin-top:10px">
       <div class="row scen head"><span>move</span><span>price</span><span>profit/loss</span><span>return</span></div>
       ${scen}</div>`;

  const treeBody = !bin
    ? `<div class="prose">Not enough data to build a tree for this contract.</div>`
    : `<div class="gk-head">
         <span class="pos">Tree says ${G.usd(bin.tree.price)}</span>
         <span class="cost">market ${G.usd(bin.market)} &middot; ${bin.tree.steps} steps</span>
       </div>
       <div class="prose">
         <p>Black-Scholes assumes you hold to expiry. A tree does not. It chops the
         <b>${exp.trading_days} trading day${exp.trading_days === 1 ? "" : "s"}</b> that are left
         into <b>${bin.tree.steps} steps</b> of roughly <b>${bin.hours} market hours</b> each. At
         every step the price either rises <b>${nf(bin.tree.upPct, 2)}%</b> or falls
         <b>${nf(bin.tree.downPct, 2)}%</b>, with a <b>${x100(bin.tree.p, 1)}%</b> chance of
         rising. Those numbers are not a forecast &mdash; they are chosen so the tree drifts at
         the risk-free rate, which is what makes the pricing fair rather than opinionated.</p>
         <p>It then walks <b>backwards from expiry</b>. At the last step every branch is worth
         its intrinsic value. At each earlier node it asks the one question the formula cannot:
         <i>is exercising right now worth more than holding on?</i> The node takes whichever is
         bigger, and that answer ripples back down the tree to today.</p>
         <p>${bin.tree.early > 0.005
           ? `Here the right to exercise early is worth <b>${G.usd(bin.tree.early)}</b> a share
              &mdash; <b>${G.usd(bin.earlyTotal)}</b> across your ${out.pos.contracts}
              contract${out.pos.contracts === 1 ? "" : "s"}. The tree prices this at
              ${G.usd(bin.tree.price)} against ${G.usd(bin.tree.euro)} if early exercise were
              forbidden. Black-Scholes would quote you the lower number and miss the difference.`
           : `Here that right is worth <b>nothing</b>: the tree and the European value agree to
              the cent. That is the expected answer for a call on a stock paying little or no
              dividend &mdash; there is never a reason to exercise early, so the American and
              European prices are provably identical. The tree confirming it is a good sign the
              inputs are sane.`}</p>
         <p>${bin.gapVsMarket === null ? ""
           : Math.abs(bin.gapVsMarket) < 0.02
             ? `The tree lands within a cent of the market price, so the implied volatility this
                page solved for is internally consistent.`
             : `The tree says ${G.usd(bin.tree.price)} where the market charges
                ${G.usd(bin.market)} &mdash; a gap of <b>${G.usd(Math.abs(bin.gapVsMarket))}</b>.
                The volatility fed in was solved from that same market price, so a gap this size
                points at a stale quote rather than a mispricing.`}</p>
       </div>
       <div class="row head" style="grid-template-columns:1fr 100px;margin-top:10px">
         <span>tree parameter</span><span>value</span></div>
       ${kv("up move per step", "&times;" + nf(bin.tree.u, 5))}
       ${kv("down move per step", "&times;" + nf(bin.tree.d, 5))}
       ${kv("chance of an up step", pct100(bin.tree.p, 2))}
       ${kv("american price", G.usd(bin.tree.price))}
       ${kv("european price", G.usd(bin.tree.euro))}
       ${kv("value of exercising early", G.usd(bin.tree.early))}`;

  return tile(
    "greeks", "elastic e-derived m-heavy", "w3 h3", "The greeks, in plain English",
    controls + tabs + (model === "tree" ? treeBody : bsBody),
    `${exp.expiry} &middot; ${exp.days_to_expiry}d &middot; IV ${pct(chosen.iv, 1)}`
  );
}

function optionsTile(o) {
  if (!o?.available) return tile(
    "options", "e-priced", "w2", "Options", `<div class="dim">${esc(o?.reason || "unavailable")}</div>`);
  const near = o.expiries[0], s = near.stats, dq = near.data_quality;
  const stale = !dq.quotes_live || !dq.open_interest_present;
  return tile(
    "options", "e-priced t-mid", "w2 h2", "Options",
    `<div class="figure">${pct(s.atm_iv, 1)}</div>
     <div class="unitline">implied volatility, at the money</div>
     ${kv("expiry", `${esc(near.expiry)} (${near.days_to_expiry}d)`)}
     ${kv("expected move", "&plusmn;" + pct(s.expected_move_pct, 2))}
     ${kv("straddle", money(s.straddle_price))}
     ${kv("put/call volume", nf(s.put_call_volume_ratio, 2), s.put_call_volume_ratio > 1 ? "down" : "up")}
     ${kv("max pain", s.max_pain ? money(s.max_pain, 0) : "no open interest")}
     ${kv("quotes", stale ? "stale" : "live", stale ? "stale" : "up")}`,
    `IV solved ${pct(dq.iv_solved_pct, 0)}`
  );
}

/* Probability -- the strike-picking tool.
 *
 * Taken from the reference option dashboards, where the same block sits next
 * to the greeks. Two odds per level, and the gap between them is the point:
 * FINISH is the chance of ending past a price at expiry, TOUCH is the chance
 * of trading through it at any point before. Touch is roughly double, and it
 * is the number that matters if the plan is to sell into strength rather
 * than hold to expiry. */
function probabilityTile(d, tab) {
  const o = d.options;
  if (!o?.available) return "";
  const exp = o.expiries[Math.min(tab.ui.expiryIdx, o.expiries.length - 1)];
  const pr = exp?.probability;
  if (!pr?.available) return "";

  return tile(
    "probability", "e-derived elastic t-small", "w2 h3", "Odds by price",
    `${kv("median outcome", money(pr.median))}
     ${kv("68% of the time", `${money(pr.one_sigma.low)} – ${money(pr.one_sigma.high)}`)}
     ${kv("95% of the time", `${money(pr.two_sigma.low)} – ${money(pr.two_sigma.high)}`)}
     <div class="row head" style="grid-template-columns:48px 62px 1fr 1fr;margin-top:7px">
       <span>move</span><span>price</span><span>finish</span><span>touch</span></div>
     ${pr.ladder.map((r) => `<div class="row" style="grid-template-columns:48px 62px 1fr 1fr">
        <span>${r.move_pct > 0 ? "+" : ""}${r.move_pct}%</span>
        <span>${nf(r.price, 2)}</span>
        <span>${nf(r.p_finish_above, 1)}%</span>
        <span>${r.p_touch === null ? "--" : nf(r.p_touch, 1) + "%"}</span></div>`).join("")}`,
    `${esc(exp.expiry)} · ${exp.trading_days}td`
  );
}

function chainTile(d, tab) {
  const o = d.options;
  if (!o?.available) return "";
  const ui = tab.ui;
  const exp = o.expiries[Math.min(ui.expiryIdx, o.expiries.length - 1)];
  const spot = o.spot || d.quote?.price;
  const book = ui.side === "call" ? exp.calls : exp.puts;
  const rows = book.slice().sort((a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot))
    .slice(0, 15).sort((a, b) => a.strike - b.strike);
  const chosenStrike = ui.strike ?? (rows.length
    ? rows.reduce((a, b) => (Math.abs(a.strike - spot) <= Math.abs(b.strike - spot) ? a : b)).strike : null);

  return tile(
    "chain", "elastic e-priced t-small", "w2 h3", ui.side === "call" ? "Calls" : "Puts",
    `<div class="row chain head"><span>strike</span><span>mark</span><span>iv</span><span>delta</span><span>gamma</span><span>theta</span></div>` +
      rows.map((r) => `<div class="row chain ${r.strike === chosenStrike ? "sel" : ""}" data-strike="${r.strike}">
          <span>${nf(r.strike, 1)}${r.itm ? "*" : ""}</span><span>${nf(r.mark ?? r.last, 2)}</span>
          <span>${r.iv ? nf(r.iv, 0) : "--"}</span><span>${nf(r.delta, 3)}</span>
          <span>${nf(r.gamma, 4)}</span><span>${nf(r.theta, 2)}</span></div>`).join(""),
    esc(exp.expiry)
  );
}

function unusualTile(o) {
  const rows = o?.expiries?.flatMap((e) => e.unusual_activity || []) || [];
  if (!rows.length) return tile(
    "unusual", "elastic e-priced t-small", "w2", "Unusual flow",
    `<div class="dim">Nothing trading above twice its open interest.</div>`);
  return tile(
    "unusual", "elastic e-priced t-small", "w2 h2", "Unusual flow",
    `<div class="prose" style="font-size:12px;margin-bottom:5px">Volume far above open interest means today's trading is new positioning, not existing holders swapping.</div>` +
      rows.slice(0, 7).map((r) => kv(esc(r.contract || ""),
        `${nf(r.vol_oi_ratio, 1)}&times; <span class="unit">${big(r.volume)}v/${big(r.open_interest)}oi</span>`, "warn")).join("")
  );
}

/* ---- what is already on the calendar --------------------------------
 *
 * Every other panel here is about what has already happened. This one is
 * the only one about what is scheduled to, and it exists to answer one
 * question before you pick an expiry: is something known coming first?
 *
 * Which is why the list is split at your expiry date rather than simply
 * running in date order. "There is a Fed meeting on the 28th" is trivia.
 * "There is a Fed meeting eight days before your option expires" is the
 * trade. The split does that comparison for you, so the panel is read
 * once and acted on rather than read and then worked out.
 */
const EV_DATE = (iso) => {
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("en-GB",
    { weekday: "short", day: "numeric", month: "short" });
};

const EV_WHEN = (n) => (n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`);

/* The list past your expiry is cut short -- it is context, not the point
 * of the panel. But the company's own dates are never cut: an earnings
 * report or an ex-dividend is the reason someone opened this, and losing
 * one off the bottom of a list of trade figures would be the worst
 * possible thing to drop. */
function evTrim(list, n) {
  const mine = list.filter((e) => e.scope === "company");
  const market = list.filter((e) => e.scope !== "company").slice(0, n);
  return mine.concat(market).sort((a, b) => (a.date < b.date ? -1 : 1));
}

/* The rows. Shared by both calendars, because a date is a date and the
 * only thing that differs is whose it is. */
function evRow(e) {
  return `<div class="evrow ${e.confirmed ? "" : "est"} ${e.scope}">
      <span class="evd">${EV_DATE(e.date)}</span>
      <span class="evn">${esc(e.title)}${e.confirmed ? ""
        : `<em>${e.approx ? "estimated" : "usual timing"}</em>`}</span>
      <span class="evx">${EV_WHEN(e.days)}</span>
      ${e.weight === 3 || e.scope === "company"
        ? `<span class="evy">${esc(e.why)}</span>` : ""}
      <span class="evc">${e.url
        ? `<a href="${safeUrl(e.url)}" target="_blank" rel="noopener">${esc(e.source)}</a>`
        : esc(e.source)}${e.time ? ` &middot; ${esc(e.time)}` : ""}</span>
    </div>`;
}

function evExpiry(d, tab) {
  const o = d.options;
  const exp = o?.available
    ? o.expiries[Math.min(tab.ui.expiryIdx, o.expiries.length - 1)] : null;
  return exp?.expiry || null;
}

/* ---- the calendar -----------------------------------------------
 *
 * One panel, two sides of the same question, switched between rather
 * than stacked: what this company has coming, and what the market
 * does. They were separate panels and that was wrong in the other
 * direction -- the packer could land them on opposite sides of the
 * page, and comparing "earnings on the 29th" against "Fed on the 28th"
 * meant holding one in your head while you found the other.
 *
 * The company side opens by default. Someone who has typed a ticker
 * into this app is asking about a company.
 */
function eventsTile(d, tab) {
  const all = d.events?.events || [];
  if (!all.length && !(d.events?.filed || []).length) return "";

  const side = tab.ui.calSide === "market" ? "market" : "company";
  const expiry = evExpiry(d, tab);
  const mine = all.filter((e) => e.scope === "company");
  const macro = all.filter((e) => e.scope !== "company");
  const bigBefore = expiry
    ? macro.filter((e) => e.date <= expiry && e.weight === 3).length : 0;

  const tabs = `<div class="calseg">
    <button data-calside="company" class="${side === "company" ? "on" : ""}">
      ${esc(tab.ui.symbol || d.quote?.symbol || "This company")}</button>
    <button data-calside="market" class="${side === "market" ? "on" : ""}">
      The market${bigBefore ? ` &middot; ${bigBefore}` : ""}</button>
  </div>`;

  return tile(
    "calendar", "elastic e-filed", "w3 h3", "What is coming",
    tabs + (side === "company" ? calCompany(d, tab, expiry, mine)
                               : calMarket(d, tab, expiry, macro)),
    side === "company"
      ? (mine.find((e) => e.kind === "earnings") && expiry
          ? (mine.find((e) => e.kind === "earnings").date <= expiry
             ? "earnings before expiry" : "earnings after expiry") : "")
      : (bigBefore ? `${bigBefore} before expiry` : "")
  );
}

function calCompany(d, tab, expiry, mine) {
  const filed = d.events?.filed || [];
  const filer = d.events?.filer;
  const earn = mine.find((e) => e.kind === "earnings");
  const name = d.profile?.name || tab.ui.symbol || "This company";

  let lead;
  if (!earn) {
    lead = `No earnings date has been published for ${esc(name)} yet.`;
  } else if (!expiry) {
    lead = `${esc(name)} reports on <b>${EV_DATE(earn.date)}</b>, ${EV_WHEN(earn.days)}.`;
  } else if (earn.date <= expiry) {
    lead = `${esc(name)} reports <b>${EV_WHEN(earn.days)}</b> &mdash; <b>before</b> your
      ${esc(expiry)} options expire. Options are priced up for the report and lose
      that extra value the morning after, so being right about the direction can
      still lose money.`;
  } else {
    lead = `${esc(name)} reports on <b>${EV_DATE(earn.date)}</b>, <b>after</b> your
      ${esc(expiry)} options expire. If the report is what you are trading, this
      expiry ends before it happens and a later one is the one you want.`;
  }

  return `<div class="prose">${lead}</div>
    ${mine.length ? `<div class="evhead">coming up</div>${mine.map(evRow).join("")}`
      : `<div class="dim">Nothing scheduled that we can see.</div>`}

    ${filed.length ? `<div class="evhead">already filed</div>
      ${filed.map((f) => `<div class="evrow filed w${f.weight}">
        <span class="evd">${EV_DATE(f.date)}</span>
        <span class="evn"><b class="evform">${esc(f.form)}</b> ${esc(f.headline)}</span>
        <span class="evx">${f.days_ago === 0 ? "today" : `${f.days_ago}d ago`}</span>
        ${f.items.length > 1 ? `<span class="evy">${f.items.map((i) =>
          `<i class="evitem">${esc(i.code)}</i> ${esc(i.means)}`).join(" &middot; ")}</span>` : ""}
        <span class="evc">${f.url
          ? `<a href="${safeUrl(f.url)}" target="_blank" rel="noopener">read the filing</a>`
          : "SEC EDGAR"}</span>
      </div>`).join("")}` : ""}

    <div class="evfoot">${filer?.category
      ? `A <b>${esc(String(filer.category).toLowerCase())}</b>, so the 10-Q is due 40 days
         after each quarter and the 10-K 60 days after the year ends. `
      : ""}An 8-K is how a company tells the market something happened between
      reports, and the item number says what: <b>2.02</b> is the results,
      <b>5.02</b> a director coming or going, <b>4.02</b> the company saying its
      own past accounts cannot be relied on. Earnings dates come from the data
      provider and do move; a projected ex-dividend date is marked.</div>`;
}

function calMarket(d, tab, expiry, ev) {
  if (!ev.length) return `<div class="dim">Nothing on the macro calendar.</div>`;

  const before = expiry ? ev.filter((e) => e.date <= expiry) : ev;
  const after = expiry ? ev.filter((e) => e.date > expiry) : [];
  const big = before.filter((e) => e.weight === 3);

  let verdict;
  if (!expiry) {
    verdict = `Next up is <b>${esc(ev[0].title)}</b>, ${EV_WHEN(ev[0].days)}.`;
  } else if (!big.length) {
    const next = after.find((e) => e.weight === 3);
    verdict = `No major economic release lands before your <b>${esc(expiry)}</b>
      options expire.`
      + (next ? ` The next is <b>${esc(next.title)}</b>, ${EV_WHEN(next.days)}
          &mdash; an expiry after <b>${EV_DATE(next.date)}</b> would cover it.` : "");
  } else {
    const names = big.map((e) => e.title);
    const list = names.length === 1 ? names[0]
      : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
    verdict = `Your <b>${esc(expiry)}</b> options have to get through
      <b>${big.length}</b> scheduled release${big.length > 1 ? "s" : ""} first &mdash;
      ${esc(list)}. Each can move the whole market on the day.`;
  }

  return `<div class="prose">${verdict}</div>
    ${before.length ? `<div class="evhead">${expiry
      ? `before your ${esc(expiry)} expiry` : "next up"}</div>
      ${before.map(evRow).join("")}` : ""}
    ${after.length ? `<div class="evhead">${!expiry ? "later"
      : before.length ? "after it" : `all after your ${esc(expiry)} expiry`}</div>
      ${after.slice(0, before.length ? 5 : 8).map(evRow).join("")}` : ""}
    <div class="evsrc">
      <div class="evhead">where these dates come from</div>
      ${(d.events.sources || []).map((x) => `<div class="evsrow">
        <a href="${safeUrl(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a>
        <span>${x.what}</span></div>`).join("")}
      <div class="evfoot">Anything marked <b>estimated</b> is Quipu&rsquo;s arithmetic,
        not a published date. Inflation and jobs come from the BLS, which refuses
        automated requests, so those two sit at their usual timing.</div>
    </div>`;
}

/* The handful most likely to have moved the price.
 *
 * Sixty-odd articles is a good haul and a bad list. Chronological
 * order puts a syndicated opinion piece from this morning above an
 * earnings miss from last night, and the reader is left doing the
 * ranking the app should have done.
 *
 * So the top few are lifted out. Scored on the server from three
 * things that need no reading -- how many outlets ran it, what kind
 * of words are in the headline, how old it is -- and every one shows
 * the reason it was picked, because a ranking that cannot say why is
 * just a different order.
 */
function moversStrip(items) {
  const scored = items
    .filter((a) => (a.moving?.score || 0) >= 3)
    .sort((a, b) => (b.moving.score - a.moving.score))
    .slice(0, 4);
  if (!scored.length) return "";

  return `<div class="movers">
    <div class="mvhead">most likely to have moved the price</div>
    ${scored.map((a) => `<div class="mvrow">
      <a class="mvhl" href="${safeUrl(a.url)}" target="_blank" rel="noopener">${
        esc(a.title || "untitled")}</a>
      <span class="mvwhy">${(a.moving.why || []).map(esc).join(" &middot; ")
        || "recent"}</span>
      <span class="mvage">${esc(ago(a.published) || "undated")}</span>
    </div>`).join("")}
    <div class="mvnote">Ranked by how many outlets carried it, the kind of
      words in the headline, and how recent it is &mdash; none of which
      requires reading the article, and none of which is a claim that the
      price actually moved. Everything found is still listed below.</div>
  </div>`;
}

function newsTile(news) {
  const items = news?.articles || [];
  if (!items.length) return tile(
    "news", "elastic e-claimed", "w3 h2", "The Wire", `<div class="dim">nothing found</div>`);
  return tile(
    "news", "elastic e-claimed cols2", "w3 h3", "The Wire",
    moversStrip(items) +
    items.map((a) => `<div class="article${a.is_new ? " fresh" : ""}${
        (a.moving?.score || 0) >= 3 ? " mover" : ""}">
        <a class="hl" href="${safeUrl(a.url)}" target="_blank" rel="noopener">${
          a.is_new ? `<i class="newflag">new</i>` : ""}${esc(a.title || "untitled")}</a>
        <div class="meta">${esc(a.publisher || "unknown")}<span class="dot">&bull;</span>${esc(ago(a.published) || "undated")}${
          a.also_via?.length ? `<span class="dot">&bull;</span>${a.also_via.length + 1} feeds` : ""}</div>
        <div class="stand">${esc((a.excerpt || "").slice(0, 250))}${a.full_text ? "" : ` <span class="nofull">(headline only)</span>`}</div>
      </div>`).join(""),
    `${items.length} articles &middot; ${news.extracted} read in full`
  );
}

function uniqueTile(xr) {
  const claims = xr?.unique_claims || [];
  if (!claims.length) return tile(
    "unique", "elastic e-derived m-side", "w2 h2", "Only one outlet said this", `<div class="dim">nothing extracted</div>`);
  return tile(
    "unique", "elastic e-derived m-side", "w2 h3", "Only one outlet said this",
    claims.slice(0, 28).map((c) => `<div class="claim"><span class="src">${esc(c.publisher)}</span>
        <span class="sc">${nf(c.score, 1)}</span><div>${esc(c.claim)}</div></div>`).join(""),
    `${claims.length} ranked`
  );
}

function corroboratedTile(xr) {
  const claims = xr?.corroborated_claims || [];
  if (!claims.length) return tile(
    "corroborated", "elastic e-derived", "w2 h2", "Corroborated",
    `<div class="prose" style="font-size:13px">No claim appeared in two or more outlets. Every story in this batch is standalone coverage, so there is nothing to cross-check against.</div>`);
  return tile(
    "corroborated", "elastic e-derived", "w2 h2", "Several outlets agree",
    claims.slice(0, 14).map((c) => `<div class="claim" style="border-left-color:var(--up)">
        <span class="src up">${c.source_count} sources</span>
        <span class="sc">${esc(c.publishers.slice(0, 2).join(", "))}</span>
        <div>${esc(c.claim)}</div></div>`).join("")
  );
}

function storiesTile(xr) {
  const stories = xr?.stories || [];
  if (!stories.length) return "";
  return tile(
    "stories", "elastic e-derived cols2 t-small", "w2 h3", "Stories",
    stories.slice(0, 18).map((s) => `<div class="article">
        <div class="meta">${s.size} article${s.size > 1 ? "s" : ""}<span class="dot">&bull;</span>${esc(s.first_seen.publisher || "?")}</div>
        <div class="hl" style="font-size:13px">${esc((s.headline || "untitled").slice(0, 110))}</div></div>`).join(""),
    `${stories.length} events`
  );
}

/* ---- what is inside a fund ------------------------------------------
 *
 * Searching an ETF and being shown a price is close to useless. The
 * basket IS the thing you are buying, and the two questions are always
 * what is in it and how much of it is one name.
 *
 * Every row is a way into that company: clicking one opens it in its
 * own tab, because "what is SPY" nearly always becomes "what is the
 * 8% of SPY that is NVIDIA".
 */
function holdingsTile(d) {
  const h = d.holdings;
  if (!h?.is_fund) return "";

  if (!h.available) {
    return tile("holdings", "e-filed", "w2 h1", "What is inside it",
      `<div class="dim">${esc(h.reason || "No holdings published.")}</div>`);
  }

  const rows = h.holdings || [];
  const top = rows.slice(0, 60);
  const most = rows[0];

  /* How much of the fund one name is. A reader looking at a sector
   * fund should find out in the first sentence that a quarter of it is
   * a single company, because that is the difference between a basket
   * and a proxy for one stock. */
  const lead = h.complete
    ? `All <b>${h.count}</b> holdings, from the issuer&rsquo;s own file${
        h.as_of ? ` dated ${esc(h.as_of)}` : ""}.`
    : `The largest <b>${h.count}</b>, which is
       <b>${nf(h.covered, 0)}%</b> of the fund. The issuer does not publish a
       full list anywhere we can read, so the rest is not shown.`;
  const concentration = most && most.weight
    ? ` The biggest single holding is <b>${esc(most.symbol)}</b> at
        <b>${nf(most.weight, 1)}%</b>${most.weight > 15
          ? " &mdash; a large enough share that this fund will track that one company closely."
          : "."}`
    : "";

  return tile(
    "holdings", "elastic e-filed", "w2 h3", "What is inside it",
    `<div class="prose">${lead}${concentration}</div>
     ${h.sectors?.length ? `<div class="hsect">
       ${h.sectors.slice(0, 5).map((x) => `<div class="hsrow">
          <span class="hsn">${esc(x.sector)}</span>
          <span class="hsbar"><i style="width:${Math.min(x.weight, 100)}%"></i></span>
          <span class="hsv">${nf(x.weight, 1)}%</span>
        </div>`).join("")}
     </div>` : ""}
     <div class="hlist">
       ${top.map((x) => `<button class="hrow" data-hold="${esc(x.symbol)}"
           title="Open ${esc(x.symbol)} in its own tab">
          <span class="hsym">${esc(x.symbol)}</span>
          <span class="hname">${esc(x.name)}</span>
          <span class="hw">${x.weight == null ? "&ndash;" : nf(x.weight, 2) + "%"}</span>
        </button>`).join("")}
     </div>
     ${rows.length > top.length
        ? `<div class="hmore">and ${rows.length - top.length} smaller holdings</div>` : ""}
     <div class="fnote">Click any of them to open that company in its own tab.
       ${h.source ? `List from ${esc(h.source)}.` : ""}</div>`,
    h.complete ? `${h.count} holdings` : `top ${h.count}`
  );
}

function profileTile(p) {
  if (!p?.summary) return "";
  const boss = (p.officers || [])[0];
  return tile(
    "profile", "elastic e-claimed", "w2 h3", "The business",
    `<div class="prose" style="text-align:justify">${esc(p.summary.slice(0, 760))}</div>
     <div style="margin-top:8px;border-top:1px solid var(--rule);padding-top:6px">
       ${kv("sector", esc(p.sector || "--"))}${kv("industry", esc(p.industry || "--"))}
       ${kv("employees", big(p.employees))}
       ${kv("headquarters", esc([p.city, p.state, p.country].filter(Boolean).join(", ")))}
       ${boss ? kv("chief executive", esc(boss.name || "--")) : ""}</div>`
  );
}

function financialsTile(f) {
  if (!f?.available || !f.annual?.length) return "";
  return tile(
    "financials", "elastic e-filed t-small", "w3 h3", "The economics",
    `<div class="row fin head"><span>year</span><span>revenue</span><span>growth</span><span>gross</span><span>net</span></div>` +
      f.annual.map((r) => `<div class="row fin"><span>${esc(r.year)}</span>
          <span>${r.revenue ? "$" + big(r.revenue) : "--"}</span>
          <span class="${sign(r.revenue_growth)}">${r.revenue_growth !== null ? signed(r.revenue_growth) : "--"}</span>
          <span>${r.gross_margin !== null ? nf(r.gross_margin, 1) + "%" : "--"}</span>
          <span>${r.net_margin !== null ? nf(r.net_margin, 1) + "%" : "--"}</span></div>`).join("") +
      `<div style="margin-top:7px">
        ${kv("operating margin", f.annual[0].operating_margin !== null ? pct(f.annual[0].operating_margin, 1) : "--")}
        ${kv("research &amp; development", f.annual[0].rnd ? "$" + big(f.annual[0].rnd) : "--")}</div>`,
    "annual, from filings"
  );
}

function earningsTile(e) {
  if (!e || (!e.history?.length && !e.next_date)) return "";
  return tile(
    "earnings", "elastic e-filed t-small", "w2 h2", "Earnings record",
    (e.next_date ? kv("next report", esc(e.next_date), "warn") : "") +
      (e.beat_rate !== null ? kv("beat rate", `${e.beat_rate}% of ${e.total}`, e.beat_rate >= 75 ? "up" : "") : "") +
      `<div class="row head" style="grid-template-columns:76px 1fr 1fr 54px;margin-top:5px">
        <span>quarter</span><span>est</span><span>actual</span><span>vs</span></div>` +
      (e.history || []).slice(0, 6).map((h) => `<div class="row" style="grid-template-columns:76px 1fr 1fr 54px">
          <span>${esc(h.date)}</span><span>${nf(h.eps_estimate)}</span><span>${nf(h.eps_reported)}</span>
          <span class="${sign(h.surprise_pct)}">${h.surprise_pct !== null ? signed(h.surprise_pct) : "--"}</span></div>`).join("")
  );
}

function volumeTile(v) {
  if (!v?.available) return "";
  return tile(
    "volume", "e-priced t-mid", "w2 h2", "Volume",
    `<div class="figure ${v.relative > 1.5 ? "warn" : ""}">${nf(v.relative, 2)}&times;</div>
     <div class="unitline">today against its 30-day average</div>
     ${kv("today", big(v.today))}${kv("30-day average", big(v.avg_30d))}
     ${kv("busiest day, 90d", big(v.max_volume_90d))}
     ${kv("up days, 90d", `${v.up_day_pct}%`, v.up_day_pct >= 50 ? "up" : "down")}`
  );
}

/* ---- the accounts, as filed -----------------------------------------
 *
 * Every other business panel here is Yahoo's version of the accounts.
 * Yahoo is a convenience layer over exactly this data, and convenience
 * layers normalise -- somebody decides what counts as revenue for a
 * company that reports three kinds, picks one, and hands you a number
 * with no way to ask which.
 *
 * These come from the filing. Each row says which form it is from and
 * when it was filed, and links to that filing on EDGAR. That is the
 * whole argument for the panel: not that the numbers are better, but
 * that you can go and check them.
 */
const BIG = (v) => {
  if (v == null) return "&ndash;";
  const a = Math.abs(v);
  const s = v < 0 ? "&minus;" : "";
  if (a >= 1e12) return `${s}$${nf(a / 1e12, 2)}T`;
  if (a >= 1e9) return `${s}$${nf(a / 1e9, 1)}B`;
  if (a >= 1e6) return `${s}$${nf(a / 1e6, 1)}M`;
  return `${s}$${nf(a, 0)}`;
};
const PCT1 = (v) => (v == null ? "&ndash;" : `${nf(v * 100, 1)}%`);
const FYLAB = (end) => {
  const d = new Date(end + "T12:00:00");
  // A September year end is FY25, not FY26. Anything from the second
  // half of the calendar year belongs to the year it started in only
  // for the handful of filers with a January close, so the label just
  // follows the year the period ENDED, which is what the cover of the
  // 10-K says.
  return `FY${String(d.getFullYear()).slice(2)}`;
};

function secFinTile(d) {
  const x = d.sec;
  if (!x?.available) {
    return x?.reason || x?.note
      ? tile("secfin", "e-filed", "w2 h1", "The accounts, as filed",
             `<div class="dim">${esc(x.note || x.reason)}</div>`)
      : "";
  }
  const rows = (x.annual || []).slice(-5);
  const qs = (x.quarterly || []).slice(-4);
  if (!rows.length && !qs.length) return "";

  const line = (label, key, fmt = BIG) => `<div class="fr">
      <span class="fl">${label}</span>
      ${rows.map((r) => `<span class="fv">${fmt(r[key])}</span>`).join("")}
    </div>`;

  return tile(
    "secfin", "elastic e-filed", "w3 h3", "The accounts, as filed",
    `${x.note ? `<div class="dim" style="margin-bottom:8px">${esc(x.note)}</div>` : ""}
     ${rows.length ? `
     <div class="ftab">
       <div class="fr fhead">
         <span class="fl">year to</span>
         ${rows.map((r) => `<span class="fv">${FYLAB(r.end)}</span>`).join("")}
       </div>
       ${line("revenue", "revenue")}
       ${line("gross profit", "gross_profit")}
       ${line("operating income", "operating_income")}
       ${line("net income", "net_income")}
       ${line("earnings per share", "eps_diluted", (v) => v == null ? "&ndash;" : `$${nf(v, 2)}`)}
       ${line("cash from operations", "operating_cash_flow")}
       ${line("capital spending", "capex")}
       <div class="fr">
         <span class="fl">free cash flow</span>
         ${rows.map((r) => `<span class="fv">${
           (r.operating_cash_flow != null && r.capex != null)
             ? calc(BIG(r.free_cash_flow), WK().sum(r.free_cash_flow, [
                 WK().line("", [WK().term("cash from operations", r.operating_cash_flow, 0)]),
                 WK().line("-", [WK().term("spent on plant and equipment", r.capex, 0)]),
               ], "$", "What is left after keeping the business running -- the "
                     + "money dividends and buybacks are actually paid from."))
             : BIG(r.free_cash_flow)}</span>`).join("")}
       </div>
       <div class="fr fgap"></div>
       ${line("cash on hand", "cash")}
       ${line("total assets", "assets")}
       <div class="fr">
         <span class="fl">total liabilities${rows.some((r) => r.liabilities_derived)
           ? `<i class="fdrv" title="Not tagged separately in the filing. Assets less equity, which is what the balance sheet says it must be.">worked out</i>` : ""}</span>
         ${rows.map((r) => `<span class="fv">${BIG(r.liabilities)}</span>`).join("")}
       </div>
       ${line("shareholders equity", "equity")}
     </div>` : ""}

     ${qs.length ? `<h4 class="fsub">the last four quarters</h4>
     <div class="ftab">
       <div class="fr fhead">
         <span class="fl">quarter to</span>
         ${qs.map((r) => `<span class="fv">${esc(r.end.slice(2))}${
           r.derived_q4 ? "*" : ""}</span>`).join("")}
       </div>
       <div class="fr"><span class="fl">revenue</span>
         ${qs.map((r) => `<span class="fv">${BIG(r.revenue)}</span>`).join("")}</div>
       <div class="fr"><span class="fl">against a year earlier</span>
         ${qs.map((r) => `<span class="fv">${r.revenue_growth == null ? "&ndash;"
            : signed(r.revenue_growth * 100, 1)}</span>`).join("")}</div>
       <div class="fr"><span class="fl">net income</span>
         ${qs.map((r) => `<span class="fv">${BIG(r.net_income)}</span>`).join("")}</div>
     </div>` : ""}

     <div class="fcite">
       ${rows.slice(-3).reverse().map((r) => r.cite ? `<a href="${safeUrl(r.cite.url || x.source_url)}"
          target="_blank" rel="noopener">${FYLAB(r.end)} figures &middot; from the
          ${esc(r.cite.form || "filing")} of ${esc(r.cite.filed || "")}</a>` : "").join("")}
     </div>
     ${qs.some((r) => r.derived_q4) ? `<div class="fnote">*&thinsp;No company files a
       fourth-quarter report &mdash; it only ever appears inside the annual figure.
       That column is the year less the three quarters inside it.</div>` : ""}
     <div class="fnote">Figures are taken from the company&rsquo;s own XBRL filings.
       Where a year has been restated in a later report, the later version is
       shown. Revenue is read from
       <b>${esc((x.tags || {}).revenue || "the filed revenue tag")}</b>.</div>`,
    `${rows.length} years`
  );
}

/* Each ratio here is one filed figure over another, and both are in
 * the table directly above. The working names them, so a margin stops
 * being a number the app asserts and becomes a division the reader can
 * see -- and check against the statement it came from. */
const RATIO_OF = {
  gross_margin:   ["gross_profit", "gross profit", "revenue", "revenue"],
  operating_margin: ["operating_income", "operating income", "revenue", "revenue"],
  net_margin:     ["net_income", "net income", "revenue", "revenue"],
  roe:            ["net_income", "net income", "equity", "shareholders equity"],
  current_ratio:  ["assets_current", "assets due within a year",
                   "liabilities_current", "bills due within a year"],
  debt_to_equity: ["long_term_debt", "long-term debt", "equity", "shareholders equity"],
};

function ratioWorking(row, key, asPct) {
  const spec = RATIO_OF[key];
  if (!spec || row[key] == null) return null;
  const [tk, tl, bk, bl] = spec;
  const top = row[tk], bot = row[bk];
  if (top == null || bot == null) return null;

  const W = WK();
  const lines = [
    W.line("", [W.term(tl, top, 0)]),
    W.line("/", [W.term(bl, bot, 0)]),
  ];
  if (asPct) lines.push(W.line("x", [W.term("to make it a percentage", 100, 0)]));
  return W.sum(asPct ? row[key] * 100 : row[key], lines,
               asPct ? "%" : "", "Both figures are from the filing above.");
}

function secMarginsTile(d) {
  const x = d.sec;
  const rows = (x?.annual || []).slice(-5);
  if (!rows.length) return "";
  const last = rows[rows.length - 1];

  const line = (label, key) => `<div class="fr">
      <span class="fl">${label}</span>
      ${rows.map((r) => `<span class="fv">${
        calc(PCT1(r[key]), ratioWorking(r, key, true))}</span>`).join("")}
    </div>`;

  return tile(
    "secmargins", "elastic e-derived", "w2 h2", "What it keeps, and what it owes",
    `<div class="ftab">
       <div class="fr fhead"><span class="fl">year to</span>
         ${rows.map((r) => `<span class="fv">${FYLAB(r.end)}</span>`).join("")}</div>
       ${line("gross margin", "gross_margin")}
       ${line("operating margin", "operating_margin")}
       ${line("net margin", "net_margin")}
       ${line("return on equity", "roe")}
       <div class="fr fgap"></div>
       <div class="fr"><span class="fl">current ratio</span>
         ${rows.map((r) => `<span class="fv">${r.current_ratio == null ? "&ndash;"
            : calc(nf(r.current_ratio, 2), ratioWorking(r, "current_ratio", false))
          }</span>`).join("")}</div>
       <div class="fr"><span class="fl">long-term debt to equity</span>
         ${rows.map((r) => `<span class="fv">${r.debt_to_equity == null ? "&ndash;"
            : calc(nf(r.debt_to_equity, 2), ratioWorking(r, "debt_to_equity", false))
          }</span>`).join("")}</div>
     </div>
     <div class="fnote">Worked out here from the filed figures above, so each one
       can be checked against the filing rather than taken on trust. Gross margin
       is what survives the cost of making the thing; net margin is what survives
       everything. A current ratio under 1 means more falls due within the year
       than there are liquid assets to meet it
       &mdash; normal in some industries, a warning in others.</div>`,
    last.net_margin == null ? "" : `${nf(last.net_margin * 100, 0)}% net`
  );
}

function filingsTile(f) {
  if (!f?.available) return "";
  return tile(
    "filings", "elastic e-filed t-small", "w2 h3", "Filed with the SEC",
    f.filings.slice(0, 18).map((x) => `<div class="filing">
        <span class="form ${x.age_days !== null && x.age_days <= 7 ? "hot" : ""}">${esc(x.form)}</span>
        <span class="means">${esc(x.means)}</span>
        <a class="link" href="${safeUrl(x.url)}" target="_blank">${esc(x.filed.slice(5))}</a></div>`).join(""),
    f.hot ? "recent 8-K" : ""
  );
}

function ownershipTile(o) {
  if (!o || (!o.institutions?.length && o.institution_pct === null)) return "";
  return tile(
    "ownership", "elastic e-filed t-small", "w2 h2", "Who owns it",
    kv("institutions", pct(o.institution_pct, 1)) + kv("insiders", pct(o.insider_pct, 2)) +
      (o.institution_count ? kv("institutional holders", big(o.institution_count)) : "") +
      `<div style="margin-top:5px;border-top:1px solid var(--rule);padding-top:4px">` +
      (o.institutions || []).slice(0, 6).map((i) => kv(esc(i.name || ""), nf(i.pct_out, 2) + "%")).join("") + `</div>`
  );
}

function valuationTile(f) {
  if (!f) return "";
  const v = f.valuation, h = f.health, g = f.growth;
  return tile(
    "valuation", "elastic e-derived t-small", "w1 h3", "Valuation",
    kv("P/E forward", nf(v.pe_forward, 1)) + kv("P/E trailing", nf(v.pe_trailing, 1)) +
      kv("PEG", nf(v.peg, 2)) + kv("price/sales", nf(v.price_to_sales, 1)) +
      kv("price/book", nf(v.price_to_book, 1)) + kv("EV/EBITDA", nf(v.ev_to_ebitda, 1)) +
      `<div style="margin-top:5px;border-top:1px solid var(--rule);padding-top:4px">` +
      kv("gross margin", pct100(h.gross_margin, 1)) + kv("operating margin", pct100(h.operating_margin, 1)) +
      kv("return on equity", pct100(h.roe, 1)) + kv("debt/equity", nf(h.debt_to_equity, 1)) +
      kv("revenue growth", pct100(g.revenue_growth, 1), sign(g.revenue_growth)) + `</div>`
  );
}

function analystTile(f) {
  const a = f?.analysts;
  // Nobody covers a fund, and a panel of five dashes under a headline
  // reading "--" is not an empty result -- it is a panel that should
  // not be on the page at all. SPY was carrying one.
  if (!a || !a.count || a.target_mean == null) return "";
  return tile(
    "analysts", "e-claimed t-mid", "w1 h2", "Analysts",
    `<div class="figure ${a.upside_pct > 0 ? "up" : "down"}">${signed(a.upside_pct)}</div>
     <div class="unitline">implied upside to target</div>
     ${kv("consensus", esc(a.recommendation || "--"))}${kv("covering", nf(a.count, 0))}
     ${kv("mean target", money(a.target_mean))}
     ${kv("range", `${money(a.target_low, 0)}&ndash;${money(a.target_high, 0)}`)}`
  );
}

function shortTile(f) {
  const s = f?.short_interest;
  if (!s || s.short_pct_float === null) return "";
  return tile(
    "short", "e-filed t-mid", "w1 h2", "Short interest",
    `<div class="figure ${s.short_pct_float * 100 > 10 ? "warn" : ""}">${pct100(s.short_pct_float, 2)}</div>
     <div class="unitline">of the free float</div>
     ${kv("shares short", big(s.shares_short))}${kv("days to cover", nf(s.short_ratio, 1))}
     ${kv("float", big(s.float_shares))}`
  );
}

function socialTile(s) {
  if (!s?.total) return "";
  return tile(
    "social", "elastic e-claimed t-mid", "w1 h2", "Retail chatter",
    `<div class="figure ${s.bull_pct >= 50 ? "up" : "down"}">${pct(s.bull_pct, 0)}</div>
     <div class="unitline">bullish, of tagged posts</div>
     ${kv("bullish", s.bullish, "up")}${kv("bearish", s.bearish, "down")}${kv("messages", s.total)}`
  );
}

function pipelineTile(d, tab) {
  const n = d.news, dg = d.diagnostics, st = d.crossref?.stats || {};
  return tile(
    "pipeline", "elastic e-derived t-small", "w2 h2", "How this page was built",
    kv("URLs found", n.discovered) + kv("read in full", `${n.extracted} (${n.failed} failed)`) +
      kv("stories", st.stories ?? "--") + kv("claims parsed", st.total_claims ?? "--") +
      kv("first fetch", `${(dg.total_ms / 1000).toFixed(1)}s`) +
      kv("live refresh", tab.liveMs ? `${tab.liveMs} ms` : "--") +
      kv("last update", tab.lastLive ? tab.lastLive.toLocaleTimeString() : "--") +
      kv("auto-refresh", tab.live ? `every ${LIVE_MS / 1000}s` : "paused", tab.live ? "up" : "dim")
  );
}
/* ---- zoom: a closer look, not a bigger one --------------------------
 *
 * Opening a panel should show you more than the panel does: the full series
 * rather than a sparkline, every holder rather than six, the actual posts
 * rather than a percentage, and an explanation of what the number means.
 * Charts mounted in here are fully interactive -- crosshair, drag-zoom, the
 * same component the tiles use, just given room.
 */

let ZOOM_MOUNTS = [];

/** A chart inside the zoom panel. Registers itself for mounting after paint. */
function zoomChart(key, spec, height = 300) {
  ZOOM_MOUNTS.push({ key, spec });
  return `<div class="qchart-host zoomchart" data-zchart="${key}" style="height:${height}px"></div>
    <div class="qchart-hint" style="opacity:.8">drag to zoom &middot; scroll to scale &middot; double-click to reset</div>`;
}

/** Horizontal bar for comparing magnitudes at a glance. */
function bar(label, value, max, note = "", cls = "") {
  const w = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return `<div class="dbar">
    <span class="dbar-l">${label}</span>
    <span class="dbar-t"><i class="${cls}" style="width:${w.toFixed(1)}%"></i></span>
    <span class="dbar-v">${note}</span></div>`;
}

/** Where a value sits inside a low-high band. */
function rangeBar(lo, hi, at, label) {
  const f = hi > lo ? ((at - lo) / (hi - lo)) * 100 : 50;
  return `<div class="rbar">
    <div class="rbar-head"><span>${label}</span><span>${money(lo)} &ndash; ${money(hi)}</span></div>
    <div class="rbar-t"><i style="left:${Math.max(0, Math.min(100, f)).toFixed(1)}%"></i></div>
    <div class="rbar-foot"><span>low</span><span>${money(at)}</span><span>high</span></div></div>`;
}

const statGrid = (rows) =>
  `<div class="dstats">${rows.map(([k, v, c]) =>
    `<div><span>${k}</span><b class="${c || ""}">${v}</b></div>`).join("")}</div>`;

const DETAIL = {
  /* ---- price ---- */

  quote: (d) => {
    const q = d.quote || {};
    const v = d.volume || {};
    return `<h4>Where it stands</h4>
      ${statGrid([
        ["price", money(q.price)],
        ["today", signed(q.change_pct, 2), sign(q.change)],
        ["market cap", big(q.market_cap)],
        ["beta", nf(q.beta, 2)],
      ])}
      ${q.day_low ? rangeBar(q.day_low, q.day_high, q.price, "Today's range") : ""}
      ${q.year_low ? rangeBar(q.year_low, q.year_high, q.price, "52-week range") : ""}
      <h4>Today against a normal day</h4>
      ${bar("today", v.today || 0, v.max_volume_90d || 1, big(v.today))}
      ${bar("30-day average", v.avg_30d || 0, v.max_volume_90d || 1, big(v.avg_30d))}
      ${bar("busiest in 90 days", v.max_volume_90d || 0, v.max_volume_90d || 1, big(v.max_volume_90d))}
      <div class="prose" style="margin-top:10px">Volume only means something next to a normal
      day. At <b>${nf(v.relative, 2)}&times;</b> the 30-day average, this is a
      <b>${v.relative > 1.5 ? "busy" : v.relative < 0.8 ? "quiet" : "typical"}</b> session.</div>
      <h4>The session</h4>
      ${zoomChart("quote", { points: d.intraday?.points || [], xKey: "t", yKey: "close",
        volKey: "volume", reference: q.previous_close }, 280)}`;
  },

  /* The close-up is the same chart with room to breathe: every range on one
   * axis, taller, and with the horizons it sits inside spelled out beneath.
   * Opening it should not make you re-learn a different control. */
  price: (d, tab) => {
    const s = d.series || {};
    const sel = tab?.ui?.priceRange || s.default || "6M";
    const frame = s[sel] || {};
    const ui = tab?.ui?.priceOpts || { candles: true, log: false, mas: {} };
    const lh = d.long_history || {};
    const r = lh.returns || {};
    const maxR = Math.max(...Object.values(r).map((x) => Math.abs(x || 0)), 1);
    const ranges = (s.ranges || []).filter((k) => (s[k]?.points || []).length > 1);
    const btn = (label, on, attr) => `<button ${attr} class="${on ? "on" : ""}">${label}</button>`;

    return `<h4>${esc(sel)} &mdash; ${frame.points?.length || 0} bars</h4>
      <div class="cbar">
        <div class="cseg">${ranges.map((k) => btn(k, k === sel, `data-zrange="${k}"`)).join("")}</div>
        <span class="grow"></span>
        <div class="cseg">
          ${btn("candles", ui.candles, `data-ztool="candles"`)}
          ${btn("log", ui.log, `data-ztool="log"`)}
          ${[20, 50, 200].map((p) => `<button data-zma="${p}" class="${ui.mas[p] ? "on" : ""}">
            <i class="swatch" style="background:var(--ma${p})"></i>${p}</button>`).join("")}
        </div>
        <div class="cseg">
          ${btn("bands", ui.bands, `data-ztool="bands"`)}
          ${btn("50/200 cross", ui.crosses, `data-ztool="crosses"`)}
          ${btn("RSI", ui.osc === "rsi", `data-zosc="rsi"`)}
          ${btn("MACD", ui.osc === "macd", `data-zosc="macd"`)}
        </div>
      </div>
      <div class="qchart-host zoomchart" data-zprice style="height:460px"></div>
      <div class="indnote" data-pind></div>
      <div class="cstats" data-zstats></div>
      <div class="qchart-hint" style="opacity:.8">drag to zoom &middot; shift-drag to pan &middot;
        scroll to scale &middot; double-click to reset</div>
      <div class="prose" style="margin-top:12px">A <b>hollow</b> candle closed above where it
      opened; a <b>filled</b> one closed below. The thin line through each is the high and low
      the price actually reached &mdash; the distance between body and wick is the part of the
      move that did not stick. Bars along the bottom are volume: a large body on heavy volume is
      agreement, the same body on light volume is drift.</div>
      ${Object.keys(r).length ? `<h4>Return over each horizon</h4>
      ${Object.entries(r).map(([k, v]) =>
        bar(k, Math.abs(v || 0), maxR, signed(v), v >= 0 ? "pos" : "neg")).join("")}` : ""}
      ${statGrid([
        ["all-time high", money(lh.all_time_high)],
        ["all-time low", money(lh.all_time_low)],
        ["off the high", signed(lh.off_high_pct), sign(lh.off_high_pct)],
        ["52-week range", `${money(d.quote?.year_low)} - ${money(d.quote?.year_high)}`],
      ])}`;
  },

  returns: (d, tab) => DETAIL.price(d, tab),

  /* The panel gives you the headline of each step; this gives you the
   * argument. Same nine steps in the same order -- opening the close-up
   * should deepen what you were reading, not replace it with something
   * else you then have to re-orient inside. */
  optionstory: (d, tab) => {
    const story = buildOptionStory(d, tab);
    if (!story) return `<div class="prose">No options are listed for this stock.</div>`;
    const { exp, steps, spot } = story;
    const pr = exp.probability || {};
    const ladder = (pr.ladder || []).filter((r) => r.p_touch != null);

    const N = ["", "one", "two", "three", "four", "five", "six", "seven", "eight",
               "nine", "ten"][steps.length] || steps.length;
    return `<h4>${esc(exp.expiry)} &mdash; ${plural(exp.days_to_expiry, "day")} out,
        in ${N} steps</h4>
      <div class="prose">Nothing below is a recommendation. It is the chain for one expiry, read
      in the order the numbers actually depend on each other: the clock first, because it prices
      everything; then the move the market has already agreed on; then whether that move is
      worth its price; and only then what it costs you to take a side.</div>
      <div class="story-steps full">
        ${steps.map((s, i) => storyStep(i + 1, s, true)).join("")}
      </div>
      ${ladder.length ? `<h4>The ladder behind step 5</h4>
      <div class="prose">For each move, the chance the price <i>ever</i> reaches that level
      against the chance it is <i>above</i> it at the close on ${esc(exp.expiry)}. Below today's
      price the second column runs high for the same reason it runs low above it: finishing above
      a level you have fallen through is easy, finishing above one you have to climb to is not.</div>
      <div class="lad-head"><span>move</span><span>price</span><span>ever touches</span>
        <span>closes above</span></div>
      ${ladder.map((r) => `<div class="lad">
        <span>${signed(r.move_pct, 1)}</span>
        <span>${money(r.price)}</span>
        <span>${nf(r.p_touch, 1)}%</span>
        <span>${nf(r.p_finish_above, 1)}%</span>
      </div>`).join("")}` : ""}
      ${exp.data_quality ? `<div class="prose" style="margin-top:14px">
        <b>How solid is this?</b> ${exp.data_quality.quotes_live
          ? "Live two-sided quotes are present, so marks are mid-prices rather than stale last trades."
          : "No live quotes came back, so marks fall back to the last trade &mdash; which may be hours old."}
        ${exp.data_quality.open_interest_present
          ? ""
          : " Open interest is missing for this expiry, so max pain and the positioning step are unreliable."}
        ${exp.data_quality.iv_solved_pct
          ? ` ${nf(exp.data_quality.iv_solved_pct, 0)}% of implied vols were solved from the price
              rather than taken from the vendor, because the vendor's figures were placeholders.`
          : ""}
      </div>` : ""}`;
  },

  volume: (d) => {
    const v = d.volume || {};
    return `<h4>How busy today is</h4>
      ${statGrid([
        ["today", big(v.today)],
        ["vs 30-day average", nf(v.relative, 2) + "×", v.relative > 1.5 ? "warn" : ""],
        ["30-day average", big(v.avg_30d)],
        ["90-day average", big(v.avg_90d)],
      ])}
      ${bar("today", v.today || 0, v.max_volume_90d || 1, big(v.today))}
      ${bar("30-day average", v.avg_30d || 0, v.max_volume_90d || 1, big(v.avg_30d))}
      ${bar("busiest day, 90d", v.max_volume_90d || 0, v.max_volume_90d || 1, big(v.max_volume_90d))}
      <h4>How far it moves on a normal day</h4>
      ${statGrid([
        ["average daily move", pct(v.avg_daily_move_pct, 2)],
        ["biggest up day, 90d", signed(v.biggest_up_day_pct, 2), "up"],
        ["biggest down day, 90d", signed(v.biggest_down_day_pct, 2), "down"],
        ["up days, 90d", `${v.up_day_pct}%`, v.up_day_pct >= 50 ? "up" : "down"],
      ])}
      <div class="prose">Volume is the confirmation signal. A price move on heavy volume means
      many people acted; the same move on light volume can be one order in a thin book. Up-day
      share near 50% is normal even in a strong uptrend &mdash; trends come from the size of the
      moves, not the count.</div>
      ${zoomChart("volumechart", { points: d.history?.points || [], xKey: "date",
        yKey: "close", volKey: "volume" }, 260)}`;
  },

  /* ---- volatility and options ---- */

  vol: (d) => {
    const o = d.options, v = d.volume || {};
    const iv = o?.expiries?.[0]?.stats?.atm_iv ?? null;
    const terms = volTerms(o);
    const maxIv = Math.max(iv || 0, v.realised_vol_20d || 0, v.realised_vol_60d || 0, 1);
    return `<h4>What this comparison means</h4>
      ${volatilityProse(iv, v.realised_vol_20d, v.realised_vol_60d ?? v.realised_vol_annual,
        o?.spot || d.quote?.price, o?.expiries?.[0]?.stats?.expected_move_pct,
        o?.expiries?.[0]?.expiry, terms)}
      <h4>Side by side</h4>
      ${bar("implied, at the money", iv || 0, maxIv, pct(iv, 1), "neg")}
      ${bar("realised, 20 days", v.realised_vol_20d || 0, maxIv, pct(v.realised_vol_20d, 1))}
      ${bar("realised, 60 days", v.realised_vol_60d || 0, maxIv, pct(v.realised_vol_60d, 1))}
      ${bar("realised, 90 days", v.realised_vol_annual || 0, maxIv, pct(v.realised_vol_annual, 1))}
      <h4>Implied volatility by expiry &mdash; the term structure</h4>
      ${terms.length ? zoomChart("term",
        { points: terms.map((t) => ({ date: t.expiry, close: t.iv })), xKey: "date", yKey: "close" }, 200) : ""}
      <div class="row head" style="grid-template-columns:130px 70px 1fr"><span>expiry</span><span>days</span><span>implied</span></div>
      ${terms.map((t) => `<div class="row" style="grid-template-columns:130px 70px 1fr">
        <span>${esc(t.expiry)}</span><span>${t.days}d</span><span>${pct(t.iv, 1)}</span></div>`).join("")}
      <h4>How each number is built</h4>
      <div class="prose">
        <p><b>Implied volatility</b> is inferred, not measured. Take the price someone is
        actually paying for an option, hold the strike, time and rate fixed, and solve
        Black-Scholes backwards for the only unknown left: how much movement would justify that
        price. Quipu does this solve itself, because the vendor's own IV field returns
        placeholders.</p>
        <p><b>Realised volatility</b> is measured: the standard deviation of daily log returns
        over a window, multiplied by the square root of 252 to turn a daily number into an
        annual one.</p>
        <p>Side by side they ask the only question an option trade rests on: <i>is the market
        charging more or less for movement than this stock has been delivering?</i></p>
      </div>`;
  },

  options: (d) => {
    const o = d.options;
    if (!o?.available) return `<div class="prose">No listed options.</div>`;
    const terms = volTerms(o);
    return `<h4>Every expiry we pulled</h4>
      <div class="row head" style="grid-template-columns:120px 60px 80px 90px 90px 90px 80px">
        <span>expiry</span><span>days</span><span>ATM IV</span><span>exp. move</span>
        <span>straddle</span><span>put/call</span><span>max pain</span></div>
      ${o.expiries.map((e) => `<div class="row" style="grid-template-columns:120px 60px 80px 90px 90px 90px 80px">
        <span>${esc(e.expiry)}</span><span>${e.days_to_expiry}d</span>
        <span>${pct(e.stats.atm_iv, 1)}</span>
        <span>&plusmn;${pct(e.stats.expected_move_pct, 2)}</span>
        <span>${money(e.stats.straddle_price)}</span>
        <span class="${e.stats.put_call_volume_ratio > 1 ? "down" : "up"}">${nf(e.stats.put_call_volume_ratio, 2)}</span>
        <span>${e.stats.max_pain ? money(e.stats.max_pain, 0) : "--"}</span></div>`).join("")}
      <h4>Implied volatility across expiries</h4>
      ${zoomChart("optterm", { points: terms.map((t) => ({ date: t.expiry, close: t.iv })),
        xKey: "date", yKey: "close" }, 220)}
      <h4>What the nearest expiry is saying</h4>
      <div class="prose">
        <p>At <b>${pct(o.expiries[0].stats.atm_iv, 1)}</b> implied, the market is pricing a move
        of <b>&plusmn;${pct(o.expiries[0].stats.expected_move_pct, 2)}</b> by
        <b>${esc(o.expiries[0].expiry)}</b> &mdash; about
        <b>${money((o.spot || 0) * (o.expiries[0].stats.expected_move_pct || 0) / 100)}</b> either
        way. That is the break-even a straddle buyer needs just to cover the premium.</p>
        <p><b>Max pain</b> is the strike where the most option value expires worthless. It is a
        crowd-position statistic, not a forecast, and it is meaningless without open interest &mdash;
        which is why it reads "no open interest" when the vendor returns zeros.</p>
        <p>Risk-free rate used for the greeks: <b>${pct((o.risk_free_rate || 0) * 100, 2)}</b>,
        from the 13-week Treasury bill.</p>
      </div>
      ${statGrid([
        ["quotes", o.expiries[0].data_quality.quotes_live ? "live" : "stale",
          o.expiries[0].data_quality.quotes_live ? "up" : "warn"],
        ["open interest", o.expiries[0].data_quality.open_interest_present ? "present" : "missing",
          o.expiries[0].data_quality.open_interest_present ? "up" : "warn"],
        ["IV solved locally", pct(o.expiries[0].data_quality.iv_solved_pct, 0)],
        ["expiries loaded", String(o.expiries.length)],
      ])}`;
  },

  probability: (d, tab) => {
    const o = d.options;
    const exp = o.expiries[Math.min(tab.ui.expiryIdx, o.expiries.length - 1)];
    const pr = exp?.probability;
    if (!pr?.available) return `<div class="prose">Not enough data to compute odds.</div>`;
    const spot = o.spot || d.quote?.price;
    return `<h4>Where the price is likely to be on ${esc(exp.expiry)}</h4>
      ${statGrid([
        ["spot now", money(spot)],
        ["median outcome", money(pr.median)],
        ["trading days left", String(exp.trading_days)],
        ["implied volatility", pct(exp.stats.atm_iv, 1)],
      ])}
      ${rangeBar(pr.two_sigma.low, pr.two_sigma.high, spot, "95% of outcomes fall in this range")}
      ${rangeBar(pr.one_sigma.low, pr.one_sigma.high, spot, "68% of outcomes fall in this range")}
      <h4>Odds at each level</h4>
      <div class="row head" style="grid-template-columns:70px 100px 1fr 1fr">
        <span>move</span><span>price</span><span>finish past it</span><span>touch it</span></div>
      ${pr.ladder.map((r) => `<div class="row" style="grid-template-columns:70px 100px 1fr 1fr">
        <span>${r.move_pct > 0 ? "+" : ""}${r.move_pct}%</span>
        <span>${money(r.price)}</span>
        <span>${nf(r.p_finish_above, 1)}%</span>
        <span>${r.p_touch === null ? "--" : nf(r.p_touch, 1) + "%"}</span></div>`).join("")}
      <h4>Finish against touch</h4>
      <div class="prose">
        <p><b>Finish</b> is the chance the price is past that level when the option expires.
        <b>Touch</b> is the chance it trades through that level at any point before then &mdash;
        roughly double, because a path can cross a level and come back.</p>
        <p>Which one you care about depends on the plan. Holding to expiry: read finish.
        Intending to sell into a move: read touch, because you only need the price to get
        there once.</p>
        <p>These odds come out of the same lognormal that the option prices on this page
        already assume &mdash; drift of
        <b>${pct(((o.risk_free_rate || 0) - (o.dividend_yield || 0)) * 100, 2)}</b> a year after
        the <b>${pct((o.dividend_yield || 0) * 100, 2)}</b> dividend, and
        <b>${pct(exp.stats.atm_iv, 1)}</b> implied volatility. They are therefore consistent
        with the premiums being charged, not a second opinion. They are only as good as that
        assumption: real returns have fatter tails than a lognormal, so the far columns
        understate the extremes.</p>
      </div>`;
  },

  chain: (d, tab) => {
    const o = d.options;
    if (!o?.available) return `<div class="prose">No listed options.</div>`;
    const exp = o.expiries[Math.min(tab.ui.expiryIdx, o.expiries.length - 1)];
    const spot = o.spot || d.quote?.price;
    /* The same rows as the grid's picker, and selectable the same way.
     * They were a read-only table: clicking a strike in the tile chose
     * it, clicking what looks like the same row in the opened panel did
     * nothing at all. An interface that answers in one place and not
     * the other is worse than one that never answers. */
    const chosen = tab.ui.strike;
    const side = (label, book) => `<h4>${label} &mdash; ${esc(exp.expiry)} (${exp.days_to_expiry}d)</h4>
      <div class="row head" style="grid-template-columns:64px 58px 58px 52px 58px 64px 58px 58px 66px">
        <span>strike</span><span>mark</span><span>last</span><span>iv</span><span>delta</span>
        <span>gamma</span><span>theta</span><span>vega</span><span>open int</span></div>
      ${book.map((r) => `<div class="row chain ${
          (chosen != null ? r.strike === chosen : Math.abs(r.strike - spot) < 0.01) ? "sel" : ""}"
          data-strike="${r.strike}"
          style="grid-template-columns:64px 58px 58px 52px 58px 64px 58px 58px 66px">
          <span>${nf(r.strike, 1)}${r.itm ? "*" : ""}</span><span>${nf(r.mark ?? r.last, 2)}</span>
          <span>${nf(r.last, 2)}</span><span>${r.iv ? nf(r.iv, 0) : "--"}</span>
          <span>${nf(r.delta, 3)}</span><span>${nf(r.gamma, 4)}</span>
          <span>${nf(r.theta, 2)}</span><span>${nf(r.vega, 3)}</span>
          <span>${big(r.open_interest)}</span></div>`).join("")}`;
    const smile = exp.calls.filter((c) => c.iv).map((c) => ({ date: nf(c.strike, 0), close: c.iv }));
    return `<h4>Volatility smile &mdash; IV by strike</h4>
      ${smile.length > 3 ? zoomChart("smile", { points: smile, xKey: "date", yKey: "close" }, 200) : ""}
      <div class="prose">Spot is <b>${money(spot)}</b>. Strikes marked * are in the money. A smile
      that rises steeply on the downside is the market paying up for crash protection.</div>
      ${side("Calls", exp.calls)}${side("Puts", exp.puts)}`;
  },

  unusual: (d) => {
    const rows = (d.options?.expiries || []).flatMap((e) =>
      (e.unusual_activity || []).map((r) => ({ ...r, expiry: e.expiry })));
    if (!rows.length) return `<div class="prose">Nothing is trading at more than twice its open
      interest today. That is the normal state: most option volume is existing holders trading
      among themselves.</div>`;
    const max = Math.max(...rows.map((r) => r.vol_oi_ratio || 0), 1);
    return `<h4>Contracts trading far above their open interest</h4>
      <div class="prose">Open interest is how many contracts exist. Volume is how many changed
      hands today. When volume runs well above open interest, today's trading is <b>new
      positioning</b> rather than existing holders swapping &mdash; somebody is putting a
      position on.</div>
      <div class="row head" style="grid-template-columns:1fr 90px 80px 90px 90px">
        <span>contract</span><span>expiry</span><span>ratio</span><span>volume</span><span>open int</span></div>
      ${rows.map((r) => `<div class="row" style="grid-template-columns:1fr 90px 80px 90px 90px">
        <span>${esc(r.contract || "")}</span><span>${esc(r.expiry)}</span>
        <span class="warn">${nf(r.vol_oi_ratio, 1)}&times;</span>
        <span>${big(r.volume)}</span><span>${big(r.open_interest)}</span></div>`).join("")}
      <h4>Relative size</h4>
      ${rows.slice(0, 12).map((r) =>
        bar(esc(r.contract || ""), r.vol_oi_ratio || 0, max, nf(r.vol_oi_ratio, 1) + "×", "warn")).join("")}`;
  },

  // The tile's own controls are reused here, but their ids are rewritten so
  // the two copies do not collide -- duplicate ids would mean getElementById
  // always returned the tile's, and the panel's selects would do nothing.
  greeks: (d, tab) => `<div id="zoomgreeks">${(BODIES.greeks || "").replace(/id="gk-/g, 'id="gkz-')}</div>
    <h4>What each greek is</h4>
    <div class="prose">
      <p><b>Delta</b> &mdash; how much the option price moves for a $1 move in the share price,
      and a serviceable estimate of the chance it expires in the money.</p>
      <p><b>Gamma</b> &mdash; how fast delta itself changes. High gamma means the position
      accelerates in your favour and decelerates against you. It is what makes options
      asymmetric, and what makes short options dangerous.</p>
      <p><b>Theta</b> &mdash; what you pay per day to hold optionality. It never sleeps and it
      accelerates into expiry.</p>
      <p><b>Vega</b> &mdash; exposure to the market's opinion of future movement. You can be
      right about direction and still lose if implied volatility collapses.</p>
      <p><b>Rho</b> &mdash; exposure to interest rates. Irrelevant on short-dated options.</p>
    </div>`,

  /* ---- the business ---- */

  profile: (d) => {
    const p = d.profile || {};
    return `<h4>${esc(d.quote?.name || "")}</h4>
      <div class="prose">${esc(p.summary || "No description available.")}</div>
      <h4>Details</h4>
      ${statGrid([
        ["sector", esc(p.sector || "--")],
        ["industry", esc(p.industry || "--")],
        ["employees", big(p.employees)],
        ["headquarters", esc([p.city, p.state, p.country].filter(Boolean).join(", ") || "--")],
      ])}
      ${p.website ? `<div class="kv"><span>website</span><span><a class="link" href="${safeUrl(p.website)}" target="_blank">${esc(p.website)}</a></span></div>` : ""}
      <h4>Who runs it</h4>
      <div class="row head" style="grid-template-columns:1fr 1fr 110px"><span>name</span><span>title</span><span>pay</span></div>
      ${(p.officers || []).map((o) => `<div class="row" style="grid-template-columns:1fr 1fr 110px">
        <span>${esc(o.name || "")}</span><span>${esc(o.title || "")}</span>
        <span>${o.pay ? "$" + big(o.pay) : "--"}</span></div>`).join("")}`;
  },

  financials: (d) => {
    const f = d.financials || {};
    const years = (f.annual || []).map((r) => r.year);
    const rev = (f.annual || []).map((r) => r.revenue || 0);
    const maxRev = Math.max(...rev, 1);
    const line = (label, obj) => `<div class="row" style="grid-template-columns:160px repeat(${years.length || 1},1fr)">
        <span>${label}</span>${years.map((y) => `<span>${obj?.[y] ? "$" + big(obj[y]) : "--"}</span>`).join("")}</div>`;
    return `<h4>Revenue by year</h4>
      ${(f.annual || []).map((r) => bar(esc(r.year), r.revenue || 0, maxRev,
        `$${big(r.revenue)}  ${r.revenue_growth !== null ? signed(r.revenue_growth) : ""}`)).join("")}
      <h4>Income</h4>
      <div class="row head" style="grid-template-columns:56px 1fr 90px 80px 80px 1fr">
        <span>year</span><span>revenue</span><span>growth</span><span>gross</span><span>net</span><span>operating</span></div>
      ${(f.annual || []).map((r) => `<div class="row" style="grid-template-columns:56px 1fr 90px 80px 80px 1fr">
        <span>${esc(r.year)}</span><span>${r.revenue ? "$" + big(r.revenue) : "--"}</span>
        <span class="${sign(r.revenue_growth)}">${r.revenue_growth !== null ? signed(r.revenue_growth) : "--"}</span>
        <span>${r.gross_margin !== null ? nf(r.gross_margin, 1) + "%" : "--"}</span>
        <span>${r.net_margin !== null ? nf(r.net_margin, 1) + "%" : "--"}</span>
        <span>${r.operating_income ? "$" + big(r.operating_income) : "--"}</span></div>`).join("")}
      <h4>Balance sheet</h4>
      <div class="row head" style="grid-template-columns:160px repeat(${years.length || 1},1fr)">
        <span></span>${years.map((y) => `<span>${esc(y)}</span>`).join("")}</div>
      ${line("cash", f.balance?.cash)}${line("total debt", f.balance?.total_debt)}
      ${line("total assets", f.balance?.total_assets)}${line("equity", f.balance?.equity)}
      <h4>Cash flow</h4>
      ${line("operating", f.cashflow?.operating)}${line("free cash flow", f.cashflow?.free)}
      ${line("capital spend", f.cashflow?.capex)}
      <div class="prose">Margins matter more than growth on its own: revenue that grows while
      gross margin falls is a company buying its growth.</div>`;
  },

  valuation: (d) => {
    const f = d.fundamentals;
    if (!f) return `<div class="prose">No valuation data.</div>`;
    const v = f.valuation, h = f.health, g = f.growth;
    const explain = [
      ["P/E forward", nf(v.pe_forward, 1), "Price divided by next year's expected earnings. What you pay for a dollar of future profit."],
      ["P/E trailing", nf(v.pe_trailing, 1), "The same against the last twelve months. Higher than forward means earnings are expected to grow."],
      ["PEG", nf(v.peg, 2), "P/E divided by the growth rate. Below 1 is the classic rule of thumb for growth being underpriced."],
      ["Price/sales", nf(v.price_to_sales, 1), "Used when profits are thin or lumpy; revenue is harder to massage than earnings."],
      ["Price/book", nf(v.price_to_book, 1), "Price against balance-sheet net worth. Means little for an asset-light business."],
      ["EV/EBITDA", nf(v.ev_to_ebitda, 1), "Enterprise value against operating cash profit; ignores capital structure, so it compares across debt loads."],
    ];
    return `<h4>What you are paying</h4>
      ${explain.map(([k, val, why]) => `<div class="dexp">
        <div class="dexp-h"><span>${k}</span><b>${val}</b></div>
        <div class="dexp-w">${why}</div></div>`).join("")}
      <h4>What you are buying</h4>
      ${statGrid([
        ["gross margin", pct100(h.gross_margin, 1)],
        ["operating margin", pct100(h.operating_margin, 1)],
        ["return on equity", pct100(h.roe, 1)],
        ["debt/equity", nf(h.debt_to_equity, 1)],
        ["current ratio", nf(h.current_ratio, 2)],
        ["free cash flow", h.free_cashflow ? "$" + big(h.free_cashflow) : "--"],
        ["revenue growth", pct100(g.revenue_growth, 1), sign(g.revenue_growth)],
        ["earnings growth", pct100(g.earnings_growth, 1), sign(g.earnings_growth)],
      ])}
      <div class="prose">A high multiple is not the same as expensive. It is a bet that the
      growth and the margins hold. The question these numbers pose is whether the price already
      assumes everything going right.</div>`;
  },

  earnings: (d) => {
    const e = d.earnings || {};
    const h = e.history || [];
    const max = Math.max(...h.map((x) => Math.abs(x.surprise_pct || 0)), 1);
    return `<h4>Beats and misses</h4>
      ${e.next_date ? `<div class="prose">Next report: <b>${esc(e.next_date)}</b>.</div>` : ""}
      ${statGrid([
        ["beat rate", e.beat_rate !== null ? `${e.beat_rate}%` : "--", e.beat_rate >= 75 ? "up" : ""],
        ["quarters recorded", String(e.total || 0)],
        ["beats", String(e.beats || 0), "up"],
        ["misses", String((e.total || 0) - (e.beats || 0)), "down"],
      ])}
      ${h.map((x) => bar(esc(x.date), Math.abs(x.surprise_pct || 0), max,
        signed(x.surprise_pct), (x.surprise_pct || 0) >= 0 ? "pos" : "neg")).join("")}
      <h4>Estimate against actual</h4>
      <div class="row head" style="grid-template-columns:120px 1fr 1fr 90px">
        <span>quarter</span><span>estimate</span><span>reported</span><span>surprise</span></div>
      ${h.map((x) => `<div class="row" style="grid-template-columns:120px 1fr 1fr 90px">
        <span>${esc(x.date)}</span><span>${nf(x.eps_estimate)}</span><span>${nf(x.eps_reported)}</span>
        <span class="${sign(x.surprise_pct)}">${x.surprise_pct !== null ? signed(x.surprise_pct) : "--"}</span></div>`).join("")}
      <div class="prose">A company that beats almost every quarter is usually guiding
      conservatively rather than repeatedly surprising itself. What moves the price is the
      guidance given alongside the number, not the number.</div>`;
  },

  analysts: (d) => {
    const a = d.fundamentals?.analysts;
    const price = d.quote?.price;
    if (!a) return `<div class="prose">No analyst coverage data.</div>`;
    return `<h4>The sell-side view</h4>
      ${statGrid([
        ["consensus", esc(a.recommendation || "--")],
        ["analysts covering", nf(a.count, 0)],
        ["mean target", money(a.target_mean)],
        ["implied upside", signed(a.upside_pct), sign(a.upside_pct)],
      ])}
      ${a.target_low ? rangeBar(a.target_low, a.target_high, price, "Target range against today's price") : ""}
      ${bar("today", price || 0, a.target_high || 1, money(price))}
      ${bar("mean target", a.target_mean || 0, a.target_high || 1, money(a.target_mean), "pos")}
      ${bar("highest target", a.target_high || 0, a.target_high || 1, money(a.target_high))}
      ${bar("lowest target", a.target_low || 0, a.target_high || 1, money(a.target_low), "neg")}
      <div class="prose">Price targets are twelve-month opinions, and the spread between the
      highest and lowest &mdash; here <b>${money(a.target_low, 0)}</b> to
      <b>${money(a.target_high, 0)}</b> &mdash; usually tells you more than the average does. A
      wide spread means the analysts disagree about the business, not just the price.</div>`;
  },

  ownership: (d) => {
    const o = d.ownership || {};
    const inst = o.institutions || [];
    const max = Math.max(...inst.map((i) => i.pct_out || 0), 1);
    return `<h4>Who holds the shares</h4>
      ${statGrid([
        ["institutions", pct(o.institution_pct, 1)],
        ["insiders", pct(o.insider_pct, 2)],
        ["institutional holders", o.institution_count ? big(o.institution_count) : "--"],
      ])}
      <h4>Largest holders</h4>
      ${inst.map((i) => bar(esc(i.name || ""), i.pct_out || 0, max,
        `${nf(i.pct_out, 2)}%  ${i.value ? "$" + big(i.value) : ""}`)).join("")}
      <div class="row head" style="grid-template-columns:1fr 110px 110px 90px">
        <span>holder</span><span>shares</span><span>value</span><span>% out</span></div>
      ${inst.map((i) => `<div class="row" style="grid-template-columns:1fr 110px 110px 90px">
        <span>${esc(i.name || "")}</span><span>${big(i.shares)}</span>
        <span>${i.value ? "$" + big(i.value) : "--"}</span><span>${nf(i.pct_out, 2)}%</span></div>`).join("")}
      <div class="prose">Heavy institutional ownership cuts both ways: it is a vote of
      confidence, and it means the shares are already held by people who can sell a lot at once.
      Index funds near the top of the list &mdash; Vanguard, BlackRock, State Street &mdash; are
      passive holders, not a view on the company.</div>`;
  },

  short: (d) => {
    const s = d.fundamentals?.short_interest;
    if (!s) return `<div class="prose">No short-interest data.</div>`;
    return `<h4>The bear side</h4>
      ${statGrid([
        ["short interest", pct100(s.short_pct_float, 2)],
        ["shares short", big(s.shares_short)],
        ["days to cover", nf(s.short_ratio, 1)],
        ["free float", big(s.float_shares)],
      ])}
      ${bar("shares short", s.shares_short || 0, s.float_shares || 1, big(s.shares_short), "neg")}
      ${bar("free float", s.float_shares || 0, s.float_shares || 1, big(s.float_shares))}
      <div class="prose">
        <p><b>Short interest</b> as a share of the free float is how much of the tradable stock
        has been borrowed and sold by people expecting it to fall. Under 5% is unremarkable;
        above 10% means a meaningful bear position; above 20% is a crowded short.</p>
        <p><b>Days to cover</b> is short interest divided by average daily volume &mdash; how many
        normal trading days it would take for every short to buy back. A high number is the fuel
        in a short squeeze: the shorts cannot all leave at once.</p>
      </div>`;
  },

  filings: (d) => {
    const f = d.filings || {};
    const list = f.filings || [];
    const counts = {};
    list.forEach((x) => { counts[x.form] = (counts[x.form] || 0) + 1; });
    const max = Math.max(...Object.values(counts), 1);
    return `<h4>Everything filed &mdash; newest first</h4>
      ${statGrid([
        ["company", esc(f.name || "--")],
        ["CIK", esc(f.cik || "--")],
        ["filings listed", String(list.length)],
        ["recent 8-K", f.hot ? "yes" : "no", f.hot ? "warn" : ""],
      ])}
      ${list.map((x) => `<div class="filing" style="grid-template-columns:72px 1fr 110px 96px">
        <span class="form ${x.age_days !== null && x.age_days <= 7 ? "hot" : ""}">${esc(x.form)}</span>
        <span class="means">${esc(x.means)}${x.description ? ` &mdash; ${esc(x.description)}` : ""}</span>
        <span>${esc(x.filed)}</span>
        <a class="link" href="${safeUrl(x.url)}" target="_blank">open filing</a></div>`).join("")}
      <h4>What has been filed most</h4>
      ${Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([form, n]) =>
        bar(esc(form), n, max, String(n))).join("")}
      <div class="prose">This is the highest-trust source on the page: what the company legally
      told the regulator, unedited. An 8-K is the one to watch &mdash; it means something happened
      the market must be told about now.</div>`;
  },

  /* ---- the news ---- */

  news: (d) => `<h4>Every article found &mdash; ${d.news.discovered} of them</h4>
    ${statGrid([
      ["URLs discovered", String(d.news.discovered)],
      ["read in full", String(d.news.extracted)],
      ["extraction failed", String(d.news.failed)],
      ["stories after clustering", String(d.crossref?.stats?.stories ?? "--")],
    ])}
    <div class="colset">${(d.news.articles || []).map((a) => `<div class="article">
      <a class="hl" href="${safeUrl(a.url)}" target="_blank" rel="noopener">${esc(a.title || "untitled")}</a>
      <div class="meta">${esc(a.publisher || "unknown")}<span class="dot">&bull;</span>${esc(ago(a.published) || "undated")}
        ${a.authors?.length ? `<span class="dot">&bull;</span>${esc(a.authors.join(", "))}` : ""}
        ${a.chars ? `<span class="dot">&bull;</span>${big(a.chars)} chars` : ""}</div>
      <div class="stand">${esc(a.excerpt || "")}${a.full_text ? "" : ` <span class="nofull">(headline only &mdash; body could not be extracted)</span>`}</div>
      <div class="meta" style="margin-top:3px"><a class="link" href="${safeUrl(a.url)}" target="_blank">${esc(a.url.slice(0, 74))}</a></div>
    </div>`).join("")}</div>`,

  unique: (d) => {
    const c = d.crossref?.unique_claims || [];
    const byPub = d.crossref?.stats?.unique_by_publisher || {};
    const max = Math.max(...Object.values(byPub), 1);
    return `<h4>Claims only one outlet reported &mdash; ${c.length} ranked</h4>
      <div class="prose">Each of these appeared in exactly one article and matched nothing in any
      other. Either a scoop or an error. Ranked by how much the claim could move a decision:
      dollar figures, percentages and forward-looking verbs score highest.</div>
      ${c.map((x) => `<div class="claim"><span class="src">${esc(x.publisher)}</span>
        <span class="sc">score ${nf(x.score, 1)}</span><div>${esc(x.claim)}</div>
        <div class="meta" style="margin-top:4px"><a class="link" href="${safeUrl(x.url)}" target="_blank">source</a>
        ${x.story ? ` &mdash; from: ${esc(String(x.story).slice(0, 90))}` : ""}</div></div>`).join("")}
      <h4>Who is adding information</h4>
      ${Object.entries(byPub).map(([p, n]) => bar(esc(p), n, max, `${n} unique`)).join("")}`;
  },

  corroborated: (d) => {
    const c = d.crossref?.corroborated_claims || [];
    if (!c.length) return `<div class="prose">No claim appeared in two or more outlets. Every
      story in this batch is standalone coverage, so there is nothing to cross-check against.
      That is common on a quiet day, and it is the correct answer rather than a failure: the
      engine only reports agreement where agreement exists.</div>`;
    return `<h4>Claims several outlets agree on &mdash; ${c.length}</h4>
      <div class="prose">These sentences appeared, in substance, in more than one article.
      Agreement makes a fact more likely true and also more likely already priced in.</div>
      ${c.map((x) => `<div class="claim" style="border-left-color:var(--up)">
        <span class="src up">${x.source_count} sources</span>
        <span class="sc">${esc(x.publishers.join(", "))}</span>
        <div>${esc(x.claim)}</div></div>`).join("")}`;
  },

  stories: (d) => {
    const s = d.crossref?.stories || [];
    return `<h4>Articles grouped by event &mdash; ${s.length} stories</h4>
      <div class="prose">Articles covering the same event are clustered together, whether they
      reprinted the wire or rewrote it. A cluster of one is standalone coverage.</div>
      ${s.map((x) => `<div class="dstory">
        <div class="dstory-h">
          <span class="pill">${x.size} article${x.size > 1 ? "s" : ""}</span>
          ${x.exclusive ? `<span class="pill hot">exclusive</span>` : ""}
          <span class="dim">${x.unique_count} unique &middot; ${x.corroborated_count} shared claims</span>
        </div>
        <div class="hl">${esc(x.headline || "untitled")}</div>
        <div class="meta">first seen: ${esc(x.first_seen.publisher || "?")} &middot; ${esc(ago(x.first_seen.published))}
          &middot; carried by ${esc((x.publishers || []).join(", "))}</div>
        ${(x.top_unique || []).map((u) => `<div class="stand">&mdash; ${esc(u.claim)}</div>`).join("")}
      </div>`).join("")}`;
  },

  social: (d) => {
    const s = d.social || {};
    const msgs = s.messages || [];
    return `<h4>Retail chatter</h4>
      ${statGrid([
        ["bullish share", pct(s.bull_pct, 0), s.bull_pct >= 50 ? "up" : "down"],
        ["tagged bullish", String(s.bullish || 0), "up"],
        ["tagged bearish", String(s.bearish || 0), "down"],
        ["messages pulled", String(s.total || 0)],
      ])}
      ${bar("bullish", s.bullish || 0, (s.bullish || 0) + (s.bearish || 0) || 1, String(s.bullish || 0), "pos")}
      ${bar("bearish", s.bearish || 0, (s.bullish || 0) + (s.bearish || 0) || 1, String(s.bearish || 0), "neg")}
      <div class="prose">Only a minority of posts carry a bull or bear tag, so the percentage is
      of tagged posts, not of everything said. Treat it as a temperature reading of retail mood,
      not a forecast &mdash; sentiment here is usually most extreme right at a turning point.</div>
      <h4>What people are actually posting</h4>
      ${msgs.map((m) => `<div class="dmsg">
        <div class="meta">${esc(m.user || "anon")}${m.followers ? ` &middot; ${big(m.followers)} followers` : ""}
          ${m.sentiment ? `<span class="pill ${m.sentiment === "Bullish" ? "good" : "hot"}">${esc(m.sentiment)}</span>` : ""}
          <span class="dot">&bull;</span>${esc(ago(m.created_at))}</div>
        <div>${esc(m.body || "")}</div></div>`).join("")}`;
  },

  pipeline: (d, tab) => {
    const dg = d.diagnostics || {};
    const st = d.crossref?.stats || {};
    const srcs = dg.sources || [];
    const max = Math.max(...srcs.map((s) => s.elapsed_ms || 0), dg.extract_ms || 0, 1);
    return `<h4>What this page cost to build</h4>
      ${statGrid([
        ["total", `${(dg.total_ms / 1000).toFixed(1)}s`],
        ["article extraction", `${((dg.extract_ms || 0) / 1000).toFixed(1)}s`],
        ["discovery", `${((dg.discovery_ms || 0) / 1000).toFixed(1)}s`],
        ["live refresh", tab.liveMs ? `${tab.liveMs} ms` : "--"],
      ])}
      <h4>Time per source</h4>
      ${srcs.map((s) => bar(esc(s.source), s.elapsed_ms || 0, max,
        `${s.elapsed_ms} ms${s.ok ? "" : " — failed"}`, s.ok ? "" : "neg")).join("")}
      ${bar("article extraction", dg.extract_ms || 0, max, `${dg.extract_ms} ms`)}
      <h4>What came out</h4>
      ${statGrid([
        ["URLs found", String(d.news.discovered)],
        ["read in full", String(d.news.extracted)],
        ["failed", String(d.news.failed)],
        ["stories", String(st.stories ?? "--")],
        ["claims parsed", String(st.total_claims ?? "--")],
        ["unique claims", String(st.unique_claims ?? "--")],
        ["corroborated", String(st.corroborated_claims ?? "--")],
        ["exclusive stories", String(st.exclusives ?? "--")],
      ])}
      <h4>Extraction tiers used</h4>
      ${Object.entries(dg.tiers_used || {}).map(([k, v]) => bar(esc(k), v, d.news.extracted || 1, String(v))).join("")}
      ${(dg.errors || []).length
        ? `<h4>Sources that failed</h4>${dg.errors.map((e) =>
            `<div class="kv"><span>${esc(e.source)}</span><span class="down">${esc(e.error)}</span></div>`).join("")}`
        : `<div class="prose">Every source returned cleanly on this run.</div>`}`;
  },
};

/* Opening and closing a panel touches only the overlay.
 *
 * It used to call render(), which rebuilt the whole grid -- 25 tiles thrown
 * away and recreated, each replaying its entrance animation from opacity
 * zero. That was the background flicker on every click in and out. */
function openZoom(tab, id) {
  if (!BODIES[id] && !DETAIL[id]) return;
  tab.ui.zoom = id;
  closeZoom(tab, true);                       // drop any panel already open

  const view = document.getElementById("viewport");
  const holder = document.createElement("div");
  holder.innerHTML = renderZoom(tab);
  const overlay = holder.firstElementChild;
  if (!overlay) return;
  view.appendChild(overlay);

  gloss(overlay);
  mountZoomCharts(tab);
  wireZoom(tab);
}

function closeZoom(tab, keepState = false) {
  document.getElementById("overlay")?.remove();
  if (!keepState) tab.ui.zoom = null;
}

/* The price follows you into every panel.
 *
 * Opening a close-up used to cover the whole page, price included, so you
 * were reading about a $4.15 straddle with no way to see what the stock cost
 * without closing the panel first. Every number on this page is relative to
 * that one, so it belongs on screen whichever square you are inside. */
function zoomPrice(tab) {
  const q = tab.data?.quote;
  if (!q?.price) return "";
  return `<span class="zprice" id="zoom-price">
    <b>${money(q.price)}</b>
    <span class="${sign(q.change)}">${signed(q.change_pct, 2)}</span>
    <i>${esc(tab.symbol)}</i></span>`;
}

function renderZoom(tab) {
  const id = tab.ui.zoom;
  if (!id) return "";
  ZOOM_MOUNTS = [];
  const body = DETAIL[id] ? DETAIL[id](tab.data, tab) : BODIES[id];
  if (body === undefined) return "";
  return `<div class="overlay" id="overlay">
    <div class="zoom" id="zoombox">
      <header>
        <h2>${TITLES[id] || id}</h2>
        <span class="sub">${esc(tab.data?.quote?.name || tab.symbol || (tab.kind === "world" ? "World" : ""))}</span>
        <span class="grow"></span>
        ${zoomPrice(tab)}
        <button id="zoom-close">Close &nbsp;esc</button>
      </header>
      <div class="inner">${body}</div>
    </div></div>`;
}

/* ---- dashboard ------------------------------------------------------- */

function liveBar(tab) {
  const age = tab.lastLive ? Math.round((Date.now() - tab.lastLive) / 1000) : null;
  return `<div class="livebar">
    <span class="lbsym">${esc(tab.symbol)}</span>
    <span class="lbprice">${priceNow(tab)}</span>
    <span><span class="livedot ${tab.live ? "" : "off"}"></span>${tab.live ? "Live" : "Paused"}</span>
    <span>Prices &amp; options <b>${age === null ? "--" : age + "s"}</b> old</span>
    <span style="color:#a39b8b">${tab.newsAt
      ? `News checked <b>${esc(tab.newsAt)}</b>${tab.newsNew
          ? ` &middot; <b>${tab.newsNew} new</b>` : ""}`
      : "News &amp; filings from first load"}</span>
    ${tab.liveError ? `<span class="stale">refresh failed: ${esc(tab.liveError)}</span>` : ""}
    <span class="grow"></span>
    <button id="lb-story" class="${tab.ui.story ? "on" : ""}">${tab.ui.story ? "Hide" : "Show"} the story</button>
    <button id="lb-toggle">${tab.live ? "Pause" : "Resume"}</button>
    <button id="lb-now">Refresh now</button>
    <button id="lb-full">Reload everything</button>
    ${roomNav("search")}
  </div>`;
}

function renderDashboard(d, tab) {
  BODIES = {};
  TITLES = {};
  SPANS = {};
  BADGES = {};
  readSources(d);

  // One dense grid, in the order layout.js gives. Reading order, not
  // packing order: packGrid() closes any gaps the ordering leaves, so
  // there is no need to sort by size and bury the quote.
  const half = {
    tiles: () => `<div class="grid">${compose("search", d, tab)}</div>`,
    bar: () => window.QUIPU_COURSE?.bar(tab) || "",
    // The same grid, packed the same way, in its own box so the bar can
    // sit between the page and the steps.
    steps: () => `<div class="grid steps">${compose("steps", d, tab)}</div>`,
  };
  return liveBar(tab)
    + SEARCH_ORDER.map((k) => (half[k] ? half[k]() : "")).join("")
    + renderRail()
    + renderZoom(tab)
    + wireBar(tab);
}

/* ---- packing ---------------------------------------------------------
 *
 * CSS `grid-auto-flow: dense` gets close but always leaves two kinds of hole:
 * a one-column strip down the right edge, and the tail of the final row. It
 * cannot backfill a gap that only appeared after an item was already placed,
 * and it will never resize an item to fit.
 *
 * So we place the tiles ourselves -- first-fit, largest first -- and then run a
 * grow pass: any cell still empty is absorbed by the tile above it, or failing
 * that the tile to its left. The result has no gaps at all.
 */

function packGrid() {
  // Every grid on the page -- the company's panels and the curriculum's
  // squares below the bar -- packed by the same rules.
  document.querySelectorAll(".grid").forEach(packOne);
  // Every square is refilled at its new size.
  window.QUIPU_FILL?.tiles();
  window.QUIPU_COURSE?.redraw?.();
}

function packOne(grid) {
  if (!grid) return;

  // Work the column count out from the width, the same way auto-fill would.
  // Reading it off the grid is circular: our own explicit placement below is
  // what creates those tracks, so on the second pass we would measure
  // ourselves and never notice the window had been resized.
  const gs = getComputedStyle(grid);
  const minTrack = parseFloat(gs.getPropertyValue("--tile-min")) || 230;
  const gap = parseFloat(gs.getPropertyValue("--grid-gap")) || 8;
  const inner = grid.clientWidth - parseFloat(gs.paddingLeft) - parseFloat(gs.paddingRight);
  const cols = Math.max(1, Math.floor((inner + gap) / (minTrack + gap)));
  if (cols < 2) {
    grid.style.gridTemplateColumns = "";
    [...grid.children].forEach((el) => { el.style.gridArea = ""; });
    return;                             // too narrow to pack; let CSS stack it
  }
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

  // Tiles only: an arrow layer drawn over the grid is not something to place.
  const items = [...grid.children].filter((el) => el.classList.contains("tile")).map((el) => {
    const w = Math.min(Number((el.className.match(/\bw(\d)\b/) || [, 1])[1]), cols);
    const h = Number((el.className.match(/\bh(\d)\b/) || [, 1])[1]);
    el.style.gridArea = "";
    // Only lists and charts may be stretched to close a gap. Growing a
    // panel that holds four rows of statistics does not fill the gap, it
    // moves the gap inside the panel -- which is what the page looked
    // like before.
    return { el, w, h, x: 0, y: 0, elastic: el.classList.contains("elastic"),
             region: REGION_OF[el.dataset.tile] ?? 99 };
  });

  const occ = [];                       // occ[y][x] = item index, or undefined
  const rowAt = (y) => (occ[y] ||= new Array(cols));
  const free = (y, x, w, h) => {
    for (let j = y; j < y + h; j++)
      for (let i = x; i < x + w; i++)
        if (i >= cols || rowAt(j)[i] !== undefined) return false;
    return true;
  };
  const fill = (y, x, w, h, idx) => {
    for (let j = y; j < y + h; j++)
      for (let i = x; i < x + w; i++) rowAt(j)[i] = idx;
  };

  /* Placement is cell-driven, and banded by region.
   *
   * Two problems had to be solved at once here.
   *
   * Taking each tile in turn and dropping it in the first place it fits
   * strands cells: a three-wide tile leaves a one-column gap behind it, and
   * if every tile after it is two or more wide, nothing ever fills that gap.
   * The grow pass cannot rescue it either, because a grid item has to stay a
   * rectangle -- a two-wide neighbour cannot reach into a single cell without
   * also taking the cell beside it. So we walk the grid rather than the
   * tiles, and at each empty cell take the tile that fits best.
   *
   * But letting any tile fill any gap scatters the regions: Business panels
   * got pulled up to plug holes in Options, and the page no longer had four
   * sections in it, which makes the rail beside it a lie. So each region is
   * packed into its own band of rows and cannot borrow from the next one.
   * Gaps left at the foot of a band are closed by the grow pass below, using
   * that band's own panels.
   */
  // The curriculum's squares are read in order, so their grid keeps that
  // order even where a tighter packing was possible.
  const keepOrder = grid.classList.contains("steps");

  const bands = new Map();
  items.forEach((it, i) => {
    if (!bands.has(it.region)) bands.set(it.region, []);
    bands.get(it.region).push(i);
  });

  /* Pack one band on its own scratch grid and report how well it went.
   *
   * Everything -- placement AND the grow pass that closes leftovers -- runs
   * here, inside a single region. That matters: the page-wide grow pass has
   * to refuse to pull a panel across a band boundary, and those refusals
   * were exactly what left notches at the foot of a band. In here there is
   * no boundary to cross, so it can close what it likes.
   *
   * Works on local geometry so the caller can try several orderings and
   * commit only the best; nothing touches `items` until then.
   */
  const packBand = (order) => {
    const occL = [];
    const rowL = (y) => (occL[y] ||= new Array(cols));
    // Reading must not create. rowL(y + 1) below would append a row every
    // pass, the loop bound would grow with it, and the grow pass would never
    // terminate.
    const peek = (y, x) => occL[y]?.[x];
    const freeL = (y, x, w, h) => {
      for (let j = y; j < y + h; j++)
        for (let i = x; i < x + w; i++)
          if (i >= cols || rowL(j)[i] !== undefined) return false;
      return true;
    };
    const fillL = (y, x, w, h, v) => {
      for (let j = y; j < y + h; j++)
        for (let i = x; i < x + w; i++) rowL(j)[i] = v;
    };

    const box = {};
    const pend = order.slice();
    if (keepOrder) {
      // Each square at the first place it fits that comes AFTER the one
      // before it, reading left to right, top to bottom -- so a later,
      // smaller square can never slip into a hole ahead of its turn, and
      // the path through them never doubles back.
      let ly = 0, lx = -1;
      pend.splice(0).forEach((idx) => {
        const it = items[idx];
        for (let y = ly; y < 500; y++) {
          let placed = false;
          for (let x = y === ly ? lx + 1 : 0; x + it.w <= cols; x++) {
            if (freeL(y, x, it.w, it.h)) {
              box[idx] = { x, y, w: it.w, h: it.h };
              fillL(y, x, it.w, it.h, idx);
              ly = y; lx = x; placed = true;
              break;
            }
          }
          if (placed) break;
        }
      });
    }
    for (let y = 0; pend.length && y < 400; y++) {
      for (let x = 0; x < cols && pend.length; x++) {
        if (rowL(y)[x] !== undefined) continue;
        let span = 0;
        while (x + span < cols && rowL(y)[x + span] === undefined) span++;

        // An exact-width fill first -- it is the one that leaves no
        // remainder; failing that, the widest thing that fits.
        let pick = -1, pickScore = -1;
        for (let k = 0; k < pend.length; k++) {
          const it = items[pend[k]];
          if (it.w > span || !freeL(y, x, it.w, it.h)) continue;
          const score = (it.w === span ? 20 : 0) + it.w;
          if (score > pickScore) { pick = k; pickScore = score; }
        }
        if (pick < 0) continue;
        const idx = pend.splice(pick, 1)[0];
        const it = items[idx];
        box[idx] = { x, y, w: it.w, h: it.h };
        fillL(y, x, it.w, it.h, idx);
      }
    }
    // A tile too wide for every gap goes on a fresh row below.
    pend.forEach((idx) => {
      const it = items[idx];
      for (let y = 0; y < 500; y++) {
        let done = false;
        for (let x = 0; x + it.w <= cols; x++) {
          if (freeL(y, x, it.w, it.h)) {
            box[idx] = { x, y, w: it.w, h: it.h };
            fillL(y, x, it.w, it.h, idx); done = true; break;
          }
        }
        if (done) break;
      }
    });

    /* Absorb every cell still empty into a neighbour. Above and left simply
     * grow; below and right have to move their origin as well, or a gap in
     * the first row or first column would have nothing able to reach it.
     * Only lists and charts stretch -- growing a block of statistics does
     * not fill the gap, it moves the gap inside the panel. */
    const rows = occL.length;
    let changed = true;
    while (changed) {
      changed = false;
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          if (rowL(y)[x] !== undefined) continue;
          const tries = [
            () => {                                   // stretch down
              const i = y > 0 ? rowL(y - 1)[x] : undefined;
              if (i === undefined) return false;
              const b = box[i];
              if (!items[i].elastic || b.y + b.h !== y || !freeL(y, b.x, b.w, 1)) return false;
              b.h += 1; fillL(y, b.x, b.w, 1, i); return true;
            },
            () => {                                   // widen right
              const i = x > 0 ? rowL(y)[x - 1] : undefined;
              if (i === undefined) return false;
              const b = box[i];
              if (!items[i].elastic || b.x + b.w !== x || !freeL(b.y, x, 1, b.h)) return false;
              b.w += 1; fillL(b.y, x, 1, b.h, i); return true;
            },
            () => {                                   // pull up
              const i = peek(y + 1, x);
              if (i === undefined) return false;
              const b = box[i];
              if (!items[i].elastic || b.y !== y + 1 || !freeL(y, b.x, b.w, 1)) return false;
              b.y -= 1; b.h += 1; fillL(y, b.x, b.w, 1, i); return true;
            },
            () => {                                   // pull left
              const i = rowL(y)[x + 1];
              if (i === undefined) return false;
              const b = box[i];
              if (!items[i].elastic || b.x !== x + 1 || !freeL(b.y, x, 1, b.h)) return false;
              b.x -= 1; b.w += 1; fillL(b.y, x, 1, b.h, i); return true;
            },
          ];
          if (tries.some((fn) => fn())) changed = true;
        }
      }
    }

    /* Last resort: a cell every elastic neighbour is too wide to reach.
     * One row of slack inside a panel beats a visible tear in the grid. */
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        if (rowL(y)[x] !== undefined) continue;
        for (const [i, above] of [[y > 0 ? peek(y - 1, x) : undefined, true],
                                  [peek(y + 1, x), false]]) {
          if (i === undefined) continue;
          const b = box[i];
          if (above ? b.y + b.h !== y : b.y !== y + 1) continue;
          if (!freeL(y, b.x, b.w, 1)) continue;
          if (!above) b.y -= 1;
          b.h += 1;
          fillL(y, b.x, b.w, 1, i);
          break;
        }
      }
    }

    let holes = 0;
    for (let y = 0; y < rows; y++)
      for (let x = 0; x < cols; x++) if (rowL(y)[x] === undefined) holes++;
    return { at: box, rows, holes };
  };

  let cursor = 0;
  for (const region of [...bands.keys()].sort((a, b) => a - b)) {
    const group = bands.get(region);

    /* Which order the band's panels go down in changes how well they tile.
     * A band holds at most eight, so trying a handful of orderings and
     * keeping the tightest costs nothing and removes the last gaps that one
     * fixed order leaves behind. Authored order is tried first, so it wins
     * whenever it ties -- the page keeps its intended reading wherever the
     * shapes allow it. */
    const byArea = [...group].sort((a, b) => items[b].w * items[b].h - items[a].w * items[a].h);
    const byWide = [...group].sort((a, b) => (items[b].w - items[a].w) || (items[b].h - items[a].h));
    const byTall = [...group].sort((a, b) => (items[b].h - items[a].h) || (items[b].w - items[a].w));

    let best = null;
    for (const order of keepOrder ? [group] : [group, byArea, byWide, byTall]) {
      const got = packBand(order);
      if (!best || got.holes < best.holes
                || (got.holes === best.holes && got.rows < best.rows)) best = got;
      if (best.holes === 0) break;
    }

    for (const idx of group) {
      const b = best.at[idx];
      const it = items[idx];
      it.x = b.x; it.w = b.w; it.h = b.h;
      it.y = cursor + b.y;                 // the band's own rows, offset down
      fill(it.y, it.x, it.w, it.h, idx);
    }
    cursor = Math.max(...group.map((i) => items[i].y + items[i].h));
  }

  /* Each band closed its own gaps on the way in, where there is no boundary
   * for the grow pass to refuse to cross, so there is nothing left to do
   * here but write the geometry out. */

  items.forEach((it) => {
    it.el.style.gridArea = `${it.y + 1} / ${it.x + 1} / span ${it.h} / span ${it.w}`;
  });
}

/* Repack when the grid's box changes width.
 *
 * Both obvious approaches proved unreliable here: a window resize listener
 * misses element-only resizes, and a ResizeObserver on the grid was observed
 * not firing at all after a viewport change -- the grid stayed at four columns
 * on a 1900px window. A half-second width poll is one property read and cannot
 * miss, so it is what we use, with the resize event as an immediate path. */
let packTimer = null;
const repack = () => {
  clearTimeout(packTimer);
  packTimer = setTimeout(packGrid, 100);
};

let lastGridWidth = 0;
function watchGrid() {
  const grid = document.querySelector(".grid");
  lastGridWidth = grid ? grid.clientWidth : 0;
}

setInterval(() => {
  const grid = document.querySelector(".grid");
  if (!grid) return;
  const w = grid.clientWidth;
  if (Math.abs(w - lastGridWidth) > 2) {
    lastGridWidth = w;
    packGrid();
    // The rail is hidden below 900px, and the dot field refuses to mount
    // while it is. Crossing back over the threshold has to bring it up --
    // otherwise a window that started narrow never gets the field at all.
    mountRailField();
  }
}, 500);

window.addEventListener("resize", repack);

/* ---- charts ---------------------------------------------------------- */

let liveCharts = [];

/* The one price chart, built fresh whenever the *range* changes -- a new
 * range is a new series, and the reference line and zoom that belonged to the
 * old one mean nothing against it. The toggles below never rebuild; they poke
 * the live chart, so the zoom you set survives turning an average on. */
/* Daily ranges, longest first. All four hold the same daily bars and
 * differ only in how far back they reach, so the longest is a superset
 * of every other -- which is what makes the trick below sound. */
const DAILY_RANGES = ["5Y", "1Y", "6M", "1M"];

/* The bars to compute FROM, which are not the bars to SHOW.
 *
 * A 200-day average needs 200 days. Handed only the 126 bars of a
 * six-month chart it has nothing to work with, so the line was simply
 * absent -- and a 200-day average on a six-month chart is not an
 * unreasonable thing to want. Every other platform draws it, because
 * every other platform computes it from data BEFORE the left edge.
 *
 * So on the daily ranges the chart is handed the longest daily series
 * there is and opened on the window that was asked for. The averages
 * then have all the history they need, the axis and the statistics
 * still describe the visible window, and the 200-day turns up on a
 * six-month chart the way it does everywhere else.
 *
 * Intraday is left alone: those bars are minutes, and a 200-DAY
 * average has no meaning on an axis of minutes. There the honest
 * answer is still that it cannot be drawn.
 */
function priceSource(sel) {
  const want = PRICE_SERIES?.[sel];
  if (!want?.points?.length) return null;
  if (!DAILY_RANGES.includes(sel)) {
    return { points: want.points, range: null, daily: false };
  }
  const long = DAILY_RANGES.map((r) => PRICE_SERIES[r])
    .find((f) => f?.points?.length >= want.points.length) || want;
  const n = long.points.length;
  const show = Math.min(want.points.length, n);
  return { points: long.points, range: [Math.max(0, n - show), n - 1], daily: true };
}

function mountPriceChart(tab, host, keyPrefix, statsSel, keepZoom = true) {
  if (!host || !PRICE_SERIES) return null;
  const sel = tab.ui.priceRange;
  const src = priceSource(sel);
  if (!src) return null;
  const frame = { points: src.points };
  const ui = tab.ui.priceOpts || { candles: true, log: false, mas: {} };

  const key = keyPrefix + ":price";
  const at = liveCharts.findIndex((c) => c.key === key);
  if (at >= 0) { liveCharts[at].destroy?.(); liveCharts.splice(at, 1); }

  const chart = window.QUIPU_CHART.makeChart(host, {
    points: frame.points,
    // Yesterday's close is a reference only while today is what is on screen.
    reference: sel === "1D" ? tab.data?.quote?.previous_close : null,
    candles: ui.candles,
    logScale: ui.log,
    mas: ui.mas,
    bands: ui.bands,
    osc: ui.osc,
    crosses: ui.crosses,
    range: (keepZoom && tab.ui.chartRanges[key + ":" + sel]) || src.range,
    onRange: (r) => { tab.ui.chartRanges[key + ":" + sel] = r; },
    onState: (s) => paintChartStats(s, sel, statsSel),
  });
  if (chart) liveCharts.push(Object.assign(chart, { key }));
  // Repaint the reading whenever the chart is rebuilt, not only when a
  // toggle is clicked: changing the range or a live refresh both mount a
  // new chart, and a stale "RSI 71" under a different window is worse
  // than none at all.
  // The panel and the grid each have their own note element. Write to
  // the one belonging to this chart, not to whichever comes first in
  // the document.
  paintIndicatorNote(tab, chart, host.closest("#overlay") || document);
  return chart;
}

/* One set of handlers drives both copies of the control bar -- the tile's and
 * the zoom panel's -- because they are the same control and should not drift
 * apart in behaviour. */
function wirePriceControls(tab, scope, attrs, host, statsSel, keyPrefix) {
  const root = scope || document;
  const ui = tab.ui.priceOpts;
  const chart = () => liveCharts.find((c) => c.key === keyPrefix + ":price");

  root.querySelectorAll(`[${attrs.range}]`).forEach((b) => {
    b.onclick = () => {
      const r = b.getAttribute(attrs.range);
      if (!PRICE_SERIES?.[r]?.points?.length || r === tab.ui.priceRange) return;
      tab.ui.priceRange = r;
      root.querySelectorAll(`[${attrs.range}]`).forEach((o) => o.classList.toggle("on", o === b));
      mountPriceChart(tab, host(), keyPrefix, statsSel);
    };
  });

  root.querySelectorAll(`[${attrs.tool}]`).forEach((b) => {
    b.onclick = () => {
      const t = b.getAttribute(attrs.tool);
      const on = !b.classList.contains("on");
      b.classList.toggle("on", on);
      if (t === "candles") { ui.candles = on; chart()?.setCandles(on); }
      else if (t === "bands") { ui.bands = on; chart()?.setBands(on); }
      else if (t === "crosses") {
        // The marks are on the two averages, so turning the marks on
        // turns the lines on. Asking someone to switch on three things
        // to see one is a puzzle, not an interface.
        ui.crosses = on;
        if (on) { ui.mas[50] = true; ui.mas[200] = true; }
        render(true);
      }
      else { ui.log = on; chart()?.setLog(on); }
    };
  });

  root.querySelectorAll(`[${attrs.ma}]`).forEach((b) => {
    b.onclick = () => {
      const p = Number(b.getAttribute(attrs.ma));
      const on = !b.classList.contains("on");
      b.classList.toggle("on", on);
      ui.mas[p] = on;
      chart()?.setMa(p, on);
      // A 200-day average on a six-month range draws nothing, and a
      // lit button over an unchanged chart reads as broken. The note
      // says why, so it has to be repainted from here too.
      paintIndicatorNote(tab, chart(), root);
    };
  });

  /* The oscillators are one-at-a-time. Two of them stacked under the
   * price leaves the price a strip, and the price is what the panel is
   * for -- so picking one turns the other off, and picking the one that
   * is already on turns it off and gives the room back. */
  if (attrs.osc) {
    root.querySelectorAll(`[${attrs.osc}]`).forEach((b) => {
      b.onclick = () => {
        const name = b.getAttribute(attrs.osc);
        const next = ui.osc === name ? null : name;
        ui.osc = next;
        root.querySelectorAll(`[${attrs.osc}]`).forEach((o) => {
          o.classList.toggle("on", o.getAttribute(attrs.osc) === next);
        });
        // A full re-render, because the panel changes height to make
        // room. Setting it on the chart alone left the pane trying to
        // draw inside the old one and showing nothing.
        if (keyPrefix === "grid") render(true);
        else { chart()?.setOsc(next); paintIndicatorNote(tab, chart(), root); }
      };
    });
  }
}

/* What the indicator currently reads, said in words under the chart.
 *
 * A line crossing 70 is only meaningful if you know what 70 means, and
 * the whole argument of this app is that a number should arrive with its
 * interpretation attached rather than assume the reader supplies one. */
function paintIndicatorNote(tab, chart, root = document) {
  /* Scoped to the root it was given, and the root defaults to whichever
   * one the chart is actually in. Looking it up on `document` found the
   * grid's note first, so switching an indicator inside an opened panel
   * silently updated the copy behind the panel and left the one in
   * front of you blank. */
  const host = (root.querySelector ? root : document).querySelector("[data-pind]");
  if (!host) return;
  const ui = tab.ui.priceOpts || {};
  const anyMa = [20, 50, 200].some((n) => ui.mas?.[n]);
  if ((!ui.osc && !ui.crosses && !anyMa) || !chart?.readings) {
    host.innerHTML = "";
    return;
  }

  const r = chart.readings();

  /* The 50/200 cross, named correctly.
   *
   * They are two different events with two different names, and the
   * bearish one is the DEATH cross -- the 50 falling through the 200.
   * A golden cross is the opposite and is read as strength. Labelling
   * either one wrong would be the exact failure this app exists to
   * avoid, so the panel says which is which and what it means. */
  /* An average nobody can draw.
   *
   * A 200-day average needs 200 days. On a six-month range there is no
   * such number, so the line is genuinely absent -- and a toggle that
   * lights up while nothing appears on the chart reads as broken
   * rather than as a fact about the window you picked. */
  let missing = "";
  if (r.have) {
    const gone = [20, 50, 200].filter((n) => ui.mas[n] && !r.have[n]);
    if (gone.length) {
      missing = `<span class="indname">not drawn</span>
        The ${gone.map((n) => `<b>${n}-day</b>`).join(" and ")} average
        ${gone.length > 1 ? "need" : "needs"} ${gone.map((n) => n).join(" and ")}
        sessions of history and this range holds <b>${r.bars}</b>.
        Pick a longer range to see ${gone.length > 1 ? "them" : "it"}.`;
    }
  }

  let crossNote = "";
  if (ui.crosses) {
    if (!r.cross && r.above == null) {
      crossNote = `<span class="indname">50 / 200 cross</span>
        Not enough history on this range to have a 200-day average yet.
        Try 1Y or 5Y.`;
    } else {
      const side = r.above
        ? "The 50-day average is <b>above</b> the 200-day"
        : "The 50-day average is <b>below</b> the 200-day";
      const last = r.cross
        ? ` The last crossing was a <b>${r.cross.kind === "golden"
            ? "golden cross" : "death cross"}</b> on ${esc(String(r.cross.t).slice(0, 10))},
            ${r.cross.bars_ago} sessions ago.`
        : " There has been no crossing inside this range.";
      crossNote = `<span class="indname">50 / 200 cross</span>${side}.${last}
        <span class="inddef">A <b>golden cross</b> is the 50 rising through the
        200 and is read as strength. A <b>death cross</b> is the 50 falling
        through it &mdash; that is the one people worry about and the one that
        gets written up. Both lag by construction: a 200-day average cannot say
        anything until the move is already 200 days old, so a crossing confirms
        what has happened rather than predicting what will. They are worth
        marking because so many people watch them, not because the record is
        strong.</span>`;
    }
  }
  // Stack whichever notes apply, each ruled off from the last so two
  // different subjects do not read as one run-on sentence.
  const wrap = (x) => `<div class="indsplit">${x}</div>`;
  const extras = [crossNote, missing].filter(Boolean);
  if (!ui.osc) {
    host.innerHTML = extras.length
      ? extras[0] + extras.slice(1).map(wrap).join("") : "";
    return;
  }
  const tail = extras.map(wrap).join("");
  if (ui.osc === "rsi") {
    if (r.rsi == null) { host.innerHTML = ""; return; }
    const v = r.rsi;
    const verdict = v >= 70
      ? `<b>${nf(v, 0)}</b> &mdash; above 70. It has risen hard enough for long
         enough that buyers have had to pay up every day; often it keeps going,
         and often it stalls. It is a description of the last fortnight, not a
         signal about the next one.`
      : v <= 30
        ? `<b>${nf(v, 0)}</b> &mdash; below 30. Sellers have had it every day for
           a fortnight. The same caution applies in reverse: cheap by this
           measure has no obligation to stop being cheap.`
        : `<b>${nf(v, 0)}</b> &mdash; in the middle. Gains and losses over the
           last fortnight are roughly in balance, which is where it sits most
           of the time.`;
    host.innerHTML = `<span class="indname">RSI 14</span> ${verdict}
      <span class="inddef">Compares the size of recent gains with recent losses
      over fourteen sessions, on a scale of 0 to 100. Wilder&rsquo;s smoothing.</span>`
      + tail;
    return;
  }

  if (ui.osc === "macd") {
    if (r.macd == null || r.macd_hist == null) { host.innerHTML = ""; return; }
    const above = r.macd_hist >= 0;
    // MACD is a difference of two averages, so it is denominated in
    // the share. The raw figure says nothing on its own: +5 is a fifth
    // of a $25 stock and one percent of a $500 one, and the number was
    // printed bare.
    const share = r.close ? (r.macd / r.close) * 100 : null;
    const ago = r.macd_cross_bars;
    host.innerHTML = `<span class="indname">MACD 12/26/9</span>
      <b>${nf(r.macd, 2)}</b>${share == null ? ""
        : ` &mdash; <b>${signed(share, 2)}</b> of the share price`},
      ${above ? "above" : "below"} its signal line by
      ${nf(Math.abs(r.macd_hist), 2)}. The bars are that gap.
      ${ago == null ? "" : `It last crossed <b>${plural(ago, "session")}</b> ago.`}
      <span class="inddef">The distance between a 12-day and a 26-day
      exponential average, in dollars &mdash; which is why the percentage
      matters: the same reading means a violent move on a cheap share and
      almost nothing on an expensive one. Above zero the shorter average is
      higher, so the recent trend is upward. The crossing is what people
      watch, and it lags by construction: it is two averages of the past,
      and it turns after the price does.</span>`
      + tail;
  }
}

/** Charts inside the open zoom panel, mounted after its HTML lands. */
function mountZoomCharts(tab) {
  tab.ui.chartRanges ||= {};

  const zHost = document.querySelector("[data-zprice]");
  if (zHost) {
    mountPriceChart(tab, zHost, "zoom", "[data-zstats]");
    wirePriceControls(
      tab, document.querySelector(".zoom"),
      { range: "data-zrange", tool: "data-ztool", ma: "data-zma",
        osc: "data-zosc" },
      () => document.querySelector("[data-zprice]"), "[data-zstats]", "zoom"
    );
  }

  ZOOM_MOUNTS.forEach(({ key, spec }) => {
    const host = document.querySelector(`.qchart-host[data-zchart="${key}"]`);
    if (!host || !spec.points?.length) return;
    const chart = window.QUIPU_CHART.makeChart(host, {
      ...spec,
      range: tab.ui.chartRanges["zoom:" + key],
      onRange: (r) => { tab.ui.chartRanges["zoom:" + key] = r; },
    });
    if (chart) liveCharts.push(Object.assign(chart, { key: "zoom:" + key }));
  });
}

function mountCharts(tab) {
  liveCharts.forEach((c) => c?.destroy?.());
  liveCharts = [];
  tab.ui.chartRanges ||= {};

  const pHost = document.querySelector('.qchart-host[data-chart="price"]');
  if (pHost) {
    mountPriceChart(tab, pHost, "grid", "[data-pstats]");
    wirePriceControls(
      tab, document.querySelector('.tile[data-tile="price"]'),
      { range: "data-prange", tool: "data-ptool", ma: "data-pma",
        osc: "data-posc" },
      () => document.querySelector('.qchart-host[data-chart="price"]'), "[data-pstats]", "grid"
    );
  }

}

/* ---- the story: how to study a stock -------------------------------- */

/* The order a person should actually read this page in. Price first because
 * it is the question, then the business behind it, then what people are
 * saying, and only then the options -- which only make sense once you have a
 * view. The arrows draw this path over the grid. */
const STORY = [
  ["quote", "what it costs right now"],
  ["price", "the trend it sits in, today out to five years"],
  ["profile", "what the company actually does"],
  ["financials", "how it earns"],
  ["valuation", "what you pay for those earnings"],
  ["earnings", "whether it hits its numbers"],
  ["analysts", "what the street expects"],
  ["ownership", "who holds it"],
  ["short", "who is betting against it"],
  ["news", "what is being said"],
  ["unique", "what only one source reported"],
  ["vol", "is movement cheap or expensive"],
  ["options", "what the market expects next"],
  ["optionstory", "read those options in order"],
  ["greeks", "what a position would actually cost"],
  ["chain", "pick the contract"],
];

function drawStoryArrows(tab) {
  document.getElementById("storylayer")?.remove();
  if (!tab.ui.story) return;

  const grid = document.querySelector(".grid");
  if (!grid) return;

  const steps = STORY.map(([id, why]) => ({ id, why, el: document.querySelector(`.tile[data-tile="${id}"]`) }))
    .filter((s) => s.el);
  if (steps.length < 2) return;

  const gb = grid.getBoundingClientRect();
  const centre = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left - gb.left + r.width / 2, y: r.top - gb.top + r.height / 2, r };
  };

  const svgNS = "http://www.w3.org/2000/svg";
  const layer = document.createElementNS(svgNS, "svg");
  layer.setAttribute("id", "storylayer");
  layer.setAttribute("class", "storylayer");
  layer.setAttribute("width", grid.scrollWidth);
  layer.setAttribute("height", grid.scrollHeight);
  layer.setAttribute("viewBox", `0 0 ${grid.scrollWidth} ${grid.scrollHeight}`);

  const defs = document.createElementNS(svgNS, "defs");
  defs.innerHTML =
    `<marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
       orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#E070C8"/></marker>`;
  layer.appendChild(defs);

  steps.forEach((s, i) => {
    const a = centre(s.el);

    if (i < steps.length - 1) {
      const b = centre(steps[i + 1].el);
      // Bow the line so overlapping runs stay distinguishable.
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const dx = b.x - a.x, dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      const bow = Math.min(len * 0.14, 46) * (i % 2 ? -1 : 1);
      const cx = mx - (dy / len) * bow, cy = my + (dx / len) * bow;

      const path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", `M${a.x} ${a.y} Q${cx} ${cy} ${b.x} ${b.y}`);
      path.setAttribute("class", "storyline");
      path.setAttribute("marker-end", "url(#arrowhead)");
      path.style.setProperty("--delay", `${i * 70}ms`);
      layer.appendChild(path);
    }

    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", "storystep");
    g.style.setProperty("--delay", `${i * 70}ms`);
    const c = document.createElementNS(svgNS, "circle");
    c.setAttribute("cx", a.x); c.setAttribute("cy", a.y); c.setAttribute("r", 13);
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", a.x); t.setAttribute("y", a.y + 4.5);
    t.setAttribute("text-anchor", "middle");
    t.textContent = String(i + 1);
    const title = document.createElementNS(svgNS, "title");
    title.textContent = `${i + 1}. ${s.why}`;
    g.appendChild(c); g.appendChild(t); g.appendChild(title);
    layer.appendChild(g);
  });

  grid.appendChild(layer);
}

/* ---- rail behaviour -------------------------------------------------- */

let railScrollHandler = null;
let jumpUntil = 0;
let railSync = null;
let lastScrollTop = -1;

function wireRail(tab) {
  const rail = document.getElementById("rail");
  const view = document.getElementById("viewport");
  if (!rail || !view) return;

  const tilesOf = (id) => (REGIONS.find((r) => r.id === id)?.keys || [])
    .map((k) => document.querySelector(`.tile[data-tile="${k}"]`))
    .filter(Boolean);

  const mark = (id) => rail.querySelectorAll("[data-region]")
    .forEach((b) => b.classList.toggle("on", b.dataset.region === id));

  const jump = (id) => {
    const tiles = tilesOf(id);
    if (!tiles.length) return;
    view.scrollTo({ top: Math.max(Math.min(...tiles.map((t) => t.offsetTop)) - 10, 0),
                    behavior: "smooth" });
    // Briefly mark every panel in the region, so arriving somewhere dense
    // still tells you which of the twenty panels you were sent to. Clear the
    // whole grid first, or spent marks pile up from earlier jumps.
    document.querySelectorAll(".tile.flash").forEach((t) => t.classList.remove("flash"));
    void document.body.offsetWidth;
    tiles.forEach((t) => t.classList.add("flash"));
    mark(id);
    // Hold the mark while the smooth scroll runs. Without this the area
    // check fires mid-flight and marks whatever is being scrolled past.
    jumpUntil = Date.now() + 700;
  };

  rail.querySelectorAll("[data-region]").forEach((b) => {
    b.onclick = () => jump(b.dataset.region);
  });

  /* Whichever region fills most of the screen is the one you are in. Area,
   * not the topmost tile: a short panel scrolling past the top edge should
   * not claim the view from the tall one filling it. */
  railSync = () => {
    if (Date.now() < jumpUntil) return;
    const box = view.getBoundingClientRect();
    let best = null, bestArea = 0;
    for (const r of REGIONS) {
      let area = 0;
      for (const el of tilesOf(r.id)) {
        const q = el.getBoundingClientRect();
        const vh = Math.min(q.bottom, box.bottom) - Math.max(q.top, box.top);
        if (vh > 0) area += vh * q.width;
      }
      if (area > bestArea) { bestArea = area; best = r.id; }
    }
    if (best) mark(best);
  };

  // A plain scroll listener was tried first and never fired on this
  // container -- scrollTop changed while the event count stayed at zero --
  // so the rail is driven by a cheap poll, with the event kept as a fast
  // path where it does work.
  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { railSync(); ticking = false; });
  };
  if (railScrollHandler) view.removeEventListener("scroll", railScrollHandler);
  railScrollHandler = onScroll;
  view.addEventListener("scroll", onScroll, { passive: true });

  // 1-4 jump between regions. Ignored while typing, and while a panel is open.
  document.onkeydown = (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")) return;
    if (e.key === "Escape") return;                 // the open panel owns Escape
    const n = Number(e.key);
    if (!n || n > REGIONS.length || tab.ui.zoom) return;
    const btn = rail.querySelectorAll("[data-region]")[n - 1];
    if (btn) { e.preventDefault(); jump(btn.dataset.region); }
  };

  railSync();
  mountRailField();
}

/* ---- the rail's ground -----------------------------------------------
 *
 * The gutter the rail sits in was flat black, which read as a page margin
 * rather than as part of the instrument -- nothing said the strip could be
 * pointed at. A dot field gives it a surface, and the dots lift in a ring
 * around the cursor so the surface answers as you approach it.
 *
 * Both effects sit near the threshold of visible on purpose. This is the
 * only ornament on the page, and it earns the exception by making an
 * otherwise dead column legible as something you can use.
 */
const FIELD = {
  gap: 13,          // dot pitch
  base: 0.07,       // resting ink -- barely there
  peak: 0.30,       // crest of the ripple
  reach: 150,       // how far from the cursor the field responds
  wave: 0.055,      // rings per pixel
  speed: 0.0038,    // how fast they travel outward
  ease: 0.12,       // how quickly the field wakes and settles
};

function mountRailField() {
  const rail = document.getElementById("rail");
  if (!rail || getComputedStyle(rail).display === "none") return;

  let cv = document.getElementById("railfield");
  if (!cv) {
    cv = document.createElement("canvas");
    cv.id = "railfield";
    document.body.appendChild(cv);
  }
  if (cv.dataset.live) return;              // already running
  cv.dataset.live = "1";

  const ctx = cv.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 0, H = 0, dpr = 1;
  const mouse = { x: -1e4, y: -1e4 };
  let amp = 0, want = 0, raf = null, t0 = performance.now();

  const size = () => {
    const r = rail.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.round(r.width); H = Math.round(window.innerHeight);
    cv.style.width = W + "px"; cv.style.height = H + "px";
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  /* Painting is split from scheduling on purpose. Resizing the canvas
   * clears it, and requestAnimationFrame does not run while the window is
   * hidden or backgrounded -- so a resize in that state left the gutter
   * blank until the window came forward again. paint() can be called
   * directly; frame() is only for the animation. */
  const paint = (now) => {
    const t = now - t0;
    amp += (want - amp) * FIELD.ease;
    ctx.clearRect(0, 0, W, H);

    // Inset half a pitch so the grid does not graze either edge.
    for (let y = FIELD.gap / 2; y < H; y += FIELD.gap) {
      for (let x = FIELD.gap / 2; x < W; x += FIELD.gap) {
        let a = FIELD.base, r = 0.9;
        if (amp > 0.002) {
          const dx = x - mouse.x, dy = y - mouse.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < FIELD.reach) {
            // Falls off smoothly to nothing at the edge of reach, so the
            // ripple has no rim -- a hard cutoff would read as a disc.
            const fall = Math.cos((d / FIELD.reach) * Math.PI * 0.5) ** 2;
            const ring = still ? 1 : 0.5 + 0.5 * Math.sin(d * FIELD.wave - t * FIELD.speed);
            const lift = fall * ring * amp;
            a = FIELD.base + (FIELD.peak - FIELD.base) * lift;
            r = 0.9 + 0.8 * lift;
          }
        }
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(242,242,240,${a.toFixed(3)})`;
        ctx.fill();
      }
    }

  };

  const frame = (now) => {
    paint(now);
    // Keep animating while the field is awake, or while it settles back.
    if (want > 0 || amp > 0.002) raf = requestAnimationFrame(frame);
    else raf = null;
  };

  const wake = () => { if (!raf) raf = requestAnimationFrame(frame); };

  window.addEventListener("pointermove", (e) => {
    const r = cv.getBoundingClientRect();
    mouse.x = e.clientX - r.left;
    mouse.y = e.clientY - r.top;
    // Respond from a little outside the gutter too, so the field is already
    // alive by the time the cursor arrives on it.
    want = (e.clientX > r.left - FIELD.reach) ? 1 : 0;
    wake();
  }, { passive: true });

  window.addEventListener("pointerleave", () => { want = 0; wake(); });

  let lastW = 0, lastH = 0;
  setInterval(() => {
    const r = rail.getBoundingClientRect();
    if (Math.round(r.width) === lastW && window.innerHeight === lastH) return;
    lastW = Math.round(r.width); lastH = window.innerHeight;
    size();
    paint(performance.now());     // size() cleared it; put the grid back now
    wake();                       // and resume the ripple if one is due
  }, 500);

  size();
  paint(t0);
}

setInterval(() => {
  const view = document.getElementById("viewport");
  if (!view || !railSync || !document.getElementById("rail")) return;
  if (Math.abs(view.scrollTop - lastScrollTop) < 4) return;
  lastScrollTop = view.scrollTop;
  railSync();
}, 250);

function wireDashboard(tab) {
  const on = (id, event, fn) => { const el = document.getElementById(id); if (el) el[event] = fn; };

  wireLiveBar(tab);

  // The tile's own greeks controls. Changing one repaints just the two
  // affected tiles rather than the whole page.
  on("gk-exp", "onchange", (e) => { tab.ui.expiryIdx = Number(e.target.value); tab.ui.strike = null; repaintGreeks(tab); });
  on("gk-side", "onchange", (e) => { tab.ui.side = e.target.value; tab.ui.strike = null; repaintGreeks(tab); });
  on("gk-strike", "onchange", (e) => { tab.ui.strike = Number(e.target.value); repaintGreeks(tab); });
  on("gk-budget", "onchange", (e) => {
    const v = Number(e.target.value);
    tab.ui.budget = Number.isFinite(v) && v > 0 ? v : 1000;
    repaintGreeks(tab);
  });

  // Every control a tile body can hold, wired in one place so the grid
  // and the opened panel cannot drift apart.
  wireTileControls(tab);

  document.querySelectorAll(".tile[data-tile]").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest("a, select, input, button")) return;
      openZoom(tab, el.dataset.tile);
    };
  });

  wireRail(tab);
}

/** Wire the controls inside an open panel, at creation time. */
function wireZoom(tab) {
  const overlay = document.getElementById("overlay");
  if (!overlay) return;

  const close = document.getElementById("zoom-close");
  if (close) close.onclick = () => closeZoom(tab);
  overlay.onclick = (e) => { if (!e.target.closest("#zoombox")) closeZoom(tab); };

  // The same controls the grid gets. Without this every button inside a
  // panel that was not explicitly listed below is inert.
  wireTileControls(tab, overlay);

  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onchange = fn; };
  on("gkz-exp", (e) => { tab.ui.expiryIdx = Number(e.target.value); tab.ui.strike = null; repaintGreeks(tab); });
  on("gkz-side", (e) => { tab.ui.side = e.target.value; tab.ui.strike = null; repaintGreeks(tab); });
  on("gkz-strike", (e) => { tab.ui.strike = Number(e.target.value); repaintGreeks(tab); });
  on("gkz-budget", (e) => {
    const v = Number(e.target.value);
    tab.ui.budget = Number.isFinite(v) && v > 0 ? v : 1000;
    repaintGreeks(tab);
  });
}

function wireLiveBar(tab) {
  wireRooms();
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on("lb-story", () => {
    tab.ui.story = !tab.ui.story;
    drawStoryArrows(tab);                     // arrows only; the grid stays put
    const b = document.getElementById("lb-story");
    if (b) { b.textContent = `${tab.ui.story ? "Hide" : "Show"} the story`; b.classList.toggle("on", tab.ui.story); }
  });
  on("lb-toggle", () => {
    tab.live = !tab.live;
    const b = document.getElementById("lb-toggle");
    if (b) b.textContent = tab.live ? "Pause" : "Resume";
    document.querySelectorAll(".livedot").forEach((d) => d.classList.toggle("off", !tab.live));
    renderTabs();
  });
  on("lb-now", () => refreshLive(tab, true));
  on("lb-full", () => load(tab));
}

/** Swap one tile's body without disturbing the grid or its neighbours. */
function setTileBody(id) {
  const tile = document.querySelector(`.tile[data-tile="${id}"]`);
  if (!tile || BODIES[id] === undefined) return;
  const body = tile.querySelector(".body");
  body.innerHTML = BODIES[id];
  gloss(body);
  // The masthead badge carries the expiry and the timestamp, so it has to move
  // with the body -- otherwise a repaint shows new numbers under an old label.
  const badge = tile.querySelector("h3 .badge");
  if (badge) badge.innerHTML = BADGES[id] || "";
  // New contents, so the square is filled again.
  window.QUIPU_FILL?.one(tile);
}

/* Everything a TILE BODY can contain, wired inside one given root.
 *
 * The close-up is built outside the render cycle -- openZoom appends it
 * straight to the viewport and calls a handful of wiring functions by
 * hand -- so a control added to a tile went on working in the grid and
 * was quietly dead in the panel. The calendar's two tabs did nothing at
 * all when opened, which is exactly the kind of failure that makes a
 * reader stop trusting the whole interface.
 *
 * So both paths call this, with `document` for the grid and the overlay
 * for the panel. Anything new belongs here rather than in either
 * caller, and then it cannot be wired in one place and not the other.
 */
function wireTileControls(tab, root = document) {
  /* A holding is a way into that company, not a label. "What is SPY"
   * nearly always becomes "what is the 8% of SPY that is NVIDIA", and
   * a new tab is the right answer because the fund is still the thing
   * you were reading. */
  root.querySelectorAll("[data-hold]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      newTab(b.dataset.hold);
    };
  });

  root.querySelectorAll(".mtabs button[data-model]").forEach((el) => {
    el.onclick = (e) => {
      e.stopPropagation();
      tab.ui.model = el.dataset.model;
      repaintGreeks(tab);
    };
  });

  root.querySelectorAll(".chain[data-strike]").forEach((el) => {
    el.onclick = (e) => {
      e.stopPropagation();
      tab.ui.strike = Number(el.dataset.strike);
      repaintGreeks(tab);
    };
  });

  root.querySelectorAll("[data-calside]").forEach((b) => {
    b.onclick = (e) => {
      // Stopped from reaching the tile beneath: clicking a tile opens
      // it, and a tab that also opened it would do two things at once.
      e.stopPropagation();
      const t = current();
      if (!t) return;
      t.ui.calSide = b.dataset.calside;
      if (t.ui.zoom === "calendar") {
        // Inside the panel, repaint the panel rather than the page --
        // a full render rebuilds the grid underneath and leaves the
        // open panel showing the version it was opened with.
        eventsTile(t.data, t);                 // regenerates BODIES.calendar
        setTileBody("calendar");
        const inner = document.querySelector(".zoom .inner");
        if (inner) {
          inner.innerHTML = BODIES.calendar;
          gloss(inner);
          wireTileControls(t, inner);
        }
      } else {
        render(true);
      }
    };
  });
}


/** Redraw only what a greeks selection affects: that tile, the chain, and the
 *  open panel if it happens to be showing either of them. */
function repaintGreeks(tab) {
  const d = tab.data;
  greeksTile(d, tab);                         // regenerates BODIES.greeks
  chainTile(d, tab);                          // the chain follows the same selection
  probabilityTile(d, tab);
  setTileBody("greeks");
  setTileBody("chain");
  setTileBody("probability");
  wireTileControls(tab);
  reWireGreeksTile(tab);

  const inner = document.querySelector(".zoom .inner");
  if (!inner) return;
  if (tab.ui.zoom === "greeks" || tab.ui.zoom === "chain") {
    ZOOM_MOUNTS = [];
    inner.innerHTML = DETAIL[tab.ui.zoom](d, tab);
    mountZoomCharts(tab);
    wireZoom(tab);
  }
}

function reWireGreeksTile(tab) {
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onchange = fn; };
  on("gk-exp", (e) => { tab.ui.expiryIdx = Number(e.target.value); tab.ui.strike = null; repaintGreeks(tab); });
  on("gk-side", (e) => { tab.ui.side = e.target.value; tab.ui.strike = null; repaintGreeks(tab); });
  on("gk-strike", (e) => { tab.ui.strike = Number(e.target.value); repaintGreeks(tab); });
  on("gk-budget", (e) => {
    const v = Number(e.target.value);
    tab.ui.budget = Number.isFinite(v) && v > 0 ? v : 1000;
    repaintGreeks(tab);
  });
}

/* ---- the room ------------------------------------------------------ */

/* Search draws more than HTML: the grid is packed by hand, the charts
 * are mounted into it, and the story arrows are drawn over the result,
 * so it takes the whole of the showing rather than just draw and wire. */
function showSearch(tab, view, scroll) {
  if (tab.status === "loading") {
    view.innerHTML = `<div class="loading"><div class="spinner"></div>
      <div>Gathering everything on <b>${esc(tab.symbol)}</b></div>
      <div class="stage">price &middot; options &middot; financials &middot; filings &middot; ownership &middot; news &middot; cross-referencing</div></div>`;
    return;
  }

  if (tab.status === "error") {
    view.innerHTML = `<div class="empty"><div class="down">Could not load ${esc(tab.symbol)}</div>
      <div class="stage">${esc(tab.error)}</div></div>`;
    return;
  }

  view.innerHTML = renderDashboard(tab.data, tab);
  // The entrance stagger runs on a genuine first paint only, never on the
  // re-renders that a refresh or a toggle causes.
  if (tab.ui.introDone) document.querySelector(".grid")?.classList.remove("intro");
  else { document.querySelector(".grid")?.classList.add("intro"); tab.ui.introDone = true; }
  packGrid();
  watchGrid();
  gloss(view);
  mountCharts(tab);
  mountZoomCharts(tab);
  if (tab.ui.zoom) wireZoom(tab);
  drawStoryArrows(tab);
  view.scrollTop = scroll;
  wireDashboard(tab);
  // After the glossary and the charts, which both change what a square holds.
  window.QUIPU_FILL?.tiles();
  window.QUIPU_COURSE?.mount(tab);
}

room("search", {
  open: () => newTab(),                  // a fresh blank tab
  show: showSearch,
  place: (u) => ({ zoom: u.zoom }),
  name: () => "New search",
});

/* ---- the panels ---------------------------------------------------- */

/* Every tile this room can draw, by the id it carries on the page.
 * The ids are the ones the rail, the story arrows and the live patch
 * already look tiles up by, so a tile moved or dropped in layout.js
 * is moved or dropped everywhere at once. */
panel("search", "quote", "The live price and the day's move", (d, tab) => quoteTile(d.quote, tab));
panel("search", "instant", "What lands first: wires, filings, releases, and moves nothing has explained yet", (d, tab) => instantTile(d, tab));

/* Opened, the panel lists everything kept, with each item's standfirst,
 * and says plainly what each feed is and how fast it tends to be. */
DETAIL.instant = (d, tab) => {
  const st = instantState(tab);
  return `<h4>What lands first about ${esc(tab.symbol)}</h4>
    ${instantHead(st)}
    <div class="prose">Most news reaches a page like The Wire after a wire service has
      already run it, and by then the price has usually moved. These are the places
      things are published first. The figure after the time is how long after the
      source published it QUIPU had it.</div>
    <div class="in-legend">${[
      ["Alpaca news", "seconds", "Benzinga's wire, pushed as it runs; stories tagged to the ticker"],
      ["SEC filings", "~15 s", "the company's own filings after the SEC accepts them; 8-Ks are the big ones"],
      ["Press wires", "~20 s", "PR Newswire and Business Wire: the company's announcements, and partners naming it"],
      ["Google News", "minutes", "the widest net, local and trade press included; matches the article text"],
      ["Tripwires", "each refresh", "a move, a volume burst or an options bet before any story explains it"],
    ].map(([n, s, w]) => `<div><b>${n}</b><span class="in-speed">${s}</span><span>${w}</span></div>`).join("")}</div>
    <div class="prose">No free feed reliably beats the price: a large move often starts
      as the headline lands. That is what the tripwires are for &mdash; a ten-minute move
      three times the stock's normal swing, a five-minute bar with three times the usual
      volume, or a contract suddenly trading far past its open interest. Turn alerts on
      for a sound and a desktop notification.</div>
    ${instantLists(tab)}`;
};
panel("search", "price", "The price chart, today out to five years, with indicators", (d, tab) => priceChartTile(d, tab));
panel("search", "returns", "How it has done over each horizon", (d) => returnsTile(d.long_history));
panel("search", "volume", "The tape: how much trades, and when", (d) => volumeTile(d.volume));

panel("search", "vol", "Implied against realised volatility: is movement cheap or dear", (d) => volatilityTile(d));
panel("search", "options", "The chain in summary: expected move, skew, put/call", (d) => optionsTile(d.options));
panel("search", "optionstory", "The options, read in order", (d, tab) => optionStoryTile(d, tab));
panel("search", "probability", "Chance of finishing past a price", (d, tab) => probabilityTile(d, tab));
panel("search", "unusual", "Contracts trading far out of line with their open interest", (d) => unusualTile(d.options));
panel("search", "greeks", "What one position would cost and do, in dollars", (d, tab) => greeksTile(d, tab));
panel("search", "chain", "The full board, to pick a contract", (d, tab) => chainTile(d, tab));

panel("search", "profile", "What the company does", (d) => profileTile(d.profile));
panel("search", "holdings", "What is inside it, for a fund", (d) => holdingsTile(d));
panel("search", "secfin", "The accounts, exactly as filed with the SEC", (d) => secFinTile(d));
panel("search", "secmargins", "Margins computed from those filed figures", (d) => secMarginsTile(d));
panel("search", "financials", "Annual financials", (d) => financialsTile(d.financials));
panel("search", "valuation", "What you pay for the earnings", (d) => valuationTile(d.fundamentals));
panel("search", "earnings", "Whether it hits its numbers", (d) => earningsTile(d.earnings));
panel("search", "analysts", "What the street expects", (d) => analystTile(d.fundamentals));
panel("search", "ownership", "Who holds it", (d) => ownershipTile(d.ownership));
panel("search", "short", "Who is betting against it", (d) => shortTile(d.fundamentals));
panel("search", "filings", "The latest filings, in plain English", (d) => filingsTile(d.filings));

panel("search", "calendar", "What is already on the calendar, company and market", (d, tab) => eventsTile(d, tab));
panel("search", "news", "Headlines, the price-moving ones lifted", (d) => newsTile(d.news));
panel("search", "unique", "What only one outlet reported", (d) => uniqueTile(d.crossref));
panel("search", "corroborated", "Claims two or more outlets agree on", (d) => corroboratedTile(d.crossref));
panel("search", "stories", "Articles grouped into events", (d) => storiesTile(d.crossref));
panel("search", "social", "Retail chatter", (d) => socialTile(d.social));
panel("search", "pipeline", "What this load fetched and how long each part took", (d, tab) => pipelineTile(d, tab));
