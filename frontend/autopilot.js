/* Autopilot: the page side of the rule-built bots (backend/autopilot).
 *
 * Two places show it:
 *   - the Workshop's fourth route, "Run it on autopilot": the builder on
 *     the left, the bots on the right, the account and the kill switch
 *     along the top;
 *   - the Trade log, where every bot that is running or holding sits at
 *     the top under "automated", flagged "Automated trade active" while it
 *     holds a position.
 *
 * Aarav's copy only. The public site shows no trace of it: the engine
 * refuses visitors on /api/auto, and the page draws neither the route nor
 * the panel for them.
 *
 * The bots run in the engine, not here -- closing this page does not stop
 * them. The page reads their state every five seconds while it is showing
 * them, and redraws the parts that move without touching the form being
 * typed into. */
(function () {

const AP = { data: null, busy: false, error: null };

const TYPES = {
  momentum: "Momentum burst", breakout: "Breakout", rsi: "RSI", vwap: "VWAP",
  fvg: "Fair value gap", price: "Price", day_change: "Day's move", time: "Time window",
};
const DEFAULTS = {
  momentum: { dir: "up", pct: 0.6, minutes: 5, vol_x: 2 },
  breakout: { dir: "above", level: 0, vol_x: 1.5 },
  rsi: { op: "below", value: 30, period: 14, timeframe: "1Min" },
  vwap: { op: "above" },
  fvg: { dir: "bull" },
  price: { op: "above", value: 0 },
  day_change: { op: "above", pct: 1 },
  time: { from: "09:45", to: "15:30" },
};

/* Where the account itself lives. Every order a bot places, every fill and
 * the balance are on Alpaca's own dashboard too -- the place to check QUIPU
 * against, and the only place a position can be closed if QUIPU is off. */
const ALPACA = {
  home: "https://alpaca.markets",
  paper: "https://app.alpaca.markets/paper/dashboard/overview",
  live: "https://app.alpaca.markets/dashboard/overview",
};
const ext = (href, text, title = "") =>
  `<a class="ap-ext" href="${href}" target="_blank" rel="noopener"${title ? ` title="${title}"` : ""}>${text} &#8599;</a>`;

const clone = (x) => JSON.parse(JSON.stringify(x));
const sm = (v) => (v == null ? "--" : `${v < 0 ? "-" : "+"}$${Math.abs(v).toFixed(2)}`);
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/* ---- talking to the engine ---- */

async function refresh() {
  if (!IS_OWNER || AP.busy) return;
  AP.busy = true;
  try {
    const r = await fetch(`${API}/api/auto`);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    AP.data = j;
    AP.error = null;
  } catch (e) {
    AP.error = String(e.message || e);
  } finally {
    AP.busy = false;
  }
  paint();
}

async function post(path, body) {
  const r = await fetch(`${API}/api/auto${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
  return j;
}

const onAuto = (t) => t && roomOf(t) === "position" && t.ui.route === "auto";

function paint() {
  const t = current();
  if (onAuto(t)) {
    if (!document.querySelector(".ap")) { render(true); return; }
    const h = document.getElementById("ap-head");
    if (h) h.innerHTML = headHtml();
    const b = document.getElementById("ap-bots");
    if (b) b.innerHTML = botsHtml();
  } else if (t && roomOf(t) === "log") {
    const el = document.getElementById("ap-log");
    if (el) el.outerHTML = logHtml();
  }
  renderTabs();
}

setInterval(() => {
  if (document.hidden) return;
  const t = current();
  if (onAuto(t) || (t && roomOf(t) === "log")) refresh();
}, 5000);
// Once at start, so the Trade log's tab can say a bot is active -- on this
// computer only; the public address would only be told no.
if (["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) setTimeout(refresh, 1500);

/* ---- the draft a bot is built in ---- */

function draftFrom(key, symbol) {
  const t = AP.data?.templates?.[key];
  return {
    name: `${symbol || "New"} ${t ? t.label.toLowerCase() : "bot"}`,
    symbol: symbol || "",
    mode: "watch",
    pot: 1000,
    long: clone(t?.long || { enabled: true, match: "all", conditions: [] }),
    short: clone(t?.short || { enabled: false, match: "all", conditions: [] }),
    exits: clone(t?.exits || { take_profit_pct: 1, stop_loss_pct: 0.5, trail_pct: 0, max_minutes: 0 }),
    size: { dollars: 500 },
    limits: { max_trades_day: 5, max_loss_day: 50, cooldown_min: 5 },
    session: { from: "09:35", to: "15:50", flatten: true, flatten_min: 5 },
  };
}

function state(tab) {
  const u = tab.ui;
  u.auto ||= { draft: null, editing: null, check: null, msg: "", tpl: "momentum" };
  if (!u.auto.draft && AP.data) u.auto.draft = draftFrom("momentum", u.symbol || "");
  return u.auto;
}

/* ---- the top: account, live switch, kill switch ---- */

function headHtml() {
  const d = AP.data || {};
  const p = d.paper || {}, live = d.live || {}, mk = d.market || {}, eng = d.engine || {};
  const running = (d.bots || []).filter((b) => b.status === "running").length;
  return `<div class="ap-headrow">
    <div class="ap-title"><h2>Autopilot</h2>
      <span>Bots that trade one stock by rules you build, through your
        ${ext(ALPACA.home, "Alpaca", "The broker every order goes through")} account. Watch mode places no orders.</span></div>
    <div class="ap-acct">${p.error ? `<span class="down">paper account: ${esc(p.error)}</span>`
      : `Paper account <b>${money(Number(p.equity))}</b> &middot; buying power ${money(Number(p.buying_power))}`}
      &middot; ${ext(ALPACA.paper, "open on Alpaca", "Your paper account on Alpaca: orders, fills, positions, balance")}
      ${live.enabled && live.account && !live.account.error ? ` &middot; <span class="ap-livebadge">Live ${money(Number(live.account.equity))}</span>
        ${ext(ALPACA.live, "live account on Alpaca")}` : ""}</div>
    <div class="ap-live">${live.enabled
      ? `<span class="ap-livebadge">LIVE TRADING ON</span><button data-ap-live="off">Switch live off</button>`
      : live.available ? `<button data-ap-live="on" title="Lets bots set to Live mode trade the real account">Switch live on&hellip;</button>`
      : `<span class="dim" title="Add ALPACA_LIVE_API_KEY_ID and ALPACA_LIVE_API_SECRET_KEY to quipu/.env to make live trading possible">Live trading: no live keys</span>`}</div>
    <span class="ap-market"><i class="led ${mk.is_open ? "on" : "off"}"></i>${mk.is_open ? "Market open" : "Market closed"}
      &middot; ${running} running${eng.error ? ` &middot; <span class="down">${esc(eng.error)}</span>` : ""}</span>
    <button class="ap-kill" data-ap-kill title="Stops every bot and closes every position they hold">Stop every bot</button>
  </div>${AP.error ? `<div class="ap-err">${esc(AP.error)}</div>` : ""}`;
}

/* ---- the builder ---- */

function condHtml(side, i, c) {
  const inp = (k, w = 58, step = "any") =>
    `<input type="number" step="${step}" data-c="${side}|${i}|${k}" value="${esc(c[k] ?? "")}" style="width:${w}px">`;
  const sel = (k, opts) => `<select data-c="${side}|${i}|${k}">${opts.map(([v, l]) =>
    `<option value="${v}"${c[k] === v ? " selected" : ""}>${l}</option>`).join("")}</select>`;
  const tim = (k) => `<input type="time" data-c="${side}|${i}|${k}" value="${esc(c[k] || "")}">`;
  const ab = [["above", "above"], ["below", "below"]];
  const body = {
    momentum: () => `price moves ${sel("dir", [["up", "up"], ["down", "down"]])} ${inp("pct")}% within
      ${inp("minutes", 46, 1)} min, on ${inp("vol_x")}&times; normal volume <i>(0 = ignore)</i>`,
    breakout: () => `price crosses ${sel("dir", ab)} $${inp("level", 84)}, with ${inp("vol_x")}&times; volume on that minute <i>(0 = ignore)</i>`,
    rsi: () => `RSI(${inp("period", 44, 1)}) on ${sel("timeframe", [["1Min", "1-minute"], ["5Min", "5-minute"]])} bars is
      ${sel("op", ab)} ${inp("value")}`,
    vwap: () => `price is ${sel("op", [...ab, ["cross_above", "crossing above"], ["cross_below", "crossing below"]])} today's VWAP`,
    fvg: () => `a ${sel("dir", [["bull", "bullish"], ["bear", "bearish"]])} 3-candle gap on 5-minute bars, price back to its middle`,
    price: () => `price is ${sel("op", ab)} $${inp("value", 84)}`,
    day_change: () => `today's move is ${sel("op", ab)} ${inp("pct")}%`,
    time: () => `the time is between ${tim("from")} and ${tim("to")} ET`,
  }[c.type];
  return `<div class="ap-cond"><span class="ap-ctype">${TYPES[c.type] || esc(c.type)}</span>
    <span class="ap-cbody">${body ? body() : ""}</span>
    <button data-del-cond="${side}|${i}" title="Remove this condition" aria-label="Remove">&times;</button></div>`;
}

function sideHtml(d, side) {
  const s = d[side];
  return `<fieldset class="ap-rules${s.enabled ? "" : " off"}">
    <legend><label><input type="checkbox" data-side-on="${side}"${s.enabled ? " checked" : ""}>
      ${side === "long" ? "Buy (go long) when" : "Short when"}</label>
      <select data-side-match="${side}"><option value="all"${s.match !== "any" ? " selected" : ""}>ALL of these are true</option>
        <option value="any"${s.match === "any" ? " selected" : ""}>ANY of these is true</option></select></legend>
    ${s.conditions.map((c, i) => condHtml(side, i, c)).join("") || `<div class="dim ap-none">no conditions yet</div>`}
    <select class="ap-addc" data-add-cond="${side}"><option value="">+ add a condition&hellip;</option>
      ${Object.entries(TYPES).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
  </fieldset>`;
}

function field(label, key, value, attrs = "", note = "") {
  return `<label class="ap-f"><span>${label}</span><input ${attrs} data-k="${key}" value="${esc(value ?? "")}">${note ? `<i>${note}</i>` : ""}</label>`;
}

function builderHtml(a) {
  const d = a.draft;
  const live = AP.data?.live?.enabled;
  const num = 'type="number" step="any"';
  const tpls = AP.data?.templates || {};
  return `<div class="ap-tpl"><span>Start from</span>${Object.entries(tpls).map(([k, t]) =>
      `<button data-ap-tpl="${k}" title="${esc(t.say)}">${esc(t.label)}</button>`).join("")}</div>
    <div class="ap-top">
      ${field("Name", "name", d.name, 'type="text" maxlength="60"')}
      ${field("Symbol", "symbol", d.symbol, 'type="text" maxlength="12" style="text-transform:uppercase"')}
      <label class="ap-f"><span>Mode</span><select data-k="mode">
        <option value="watch"${d.mode === "watch" ? " selected" : ""}>Watch only (no orders)</option>
        <option value="paper"${d.mode === "paper" ? " selected" : ""}>Paper account</option>
        <option value="live"${d.mode === "live" ? " selected" : ""}${live ? "" : " disabled"}>Live money${live ? "" : " (switched off)"}</option>
      </select></label>
    </div>
    ${sideHtml(d, "long")}${sideHtml(d, "short")}
    <div class="ap-sets">
      <fieldset><legend>Exits</legend>
        ${field("Take profit %", "exits.take_profit_pct", d.exits.take_profit_pct, num)}
        ${field("Stop loss %", "exits.stop_loss_pct", d.exits.stop_loss_pct, num)}
        ${field("Trailing stop %", "exits.trail_pct", d.exits.trail_pct, num, "0 = off")}
        ${field("Time stop, min", "exits.max_minutes", d.exits.max_minutes, num, "0 = off")}
      </fieldset>
      <fieldset><legend>Money</legend>
        ${field("$ per trade", "size.dollars", d.size.dollars, num)}
        ${a.editing ? `<div class="ap-f"><span>Pot</span><i>add or pull cash on the bot's card</i></div>`
          : field("Pot to start with $", "pot", d.pot, num, "its profits and losses land here")}
      </fieldset>
      <fieldset><legend>Limits</legend>
        ${field("Trades a day, max", "limits.max_trades_day", d.limits.max_trades_day, 'type="number" step="1"')}
        ${field("Daily loss limit $", "limits.max_loss_day", d.limits.max_loss_day, num, "pauses the bot")}
        ${field("Cooldown, min", "limits.cooldown_min", d.limits.cooldown_min, num, "after each exit")}
      </fieldset>
      <fieldset><legend>Hours (ET)</legend>
        ${field("Trades from", "session.from", d.session.from, 'type="time"')}
        ${field("Until", "session.to", d.session.to, 'type="time"')}
        <label class="ap-f ap-chk"><input type="checkbox" data-k="session.flatten"${d.session.flatten ? " checked" : ""}>
          <span>Flatten before the close</span></label>
        ${field("Minutes before close", "session.flatten_min", d.session.flatten_min, num, "unticked: holds overnight")}
      </fieldset>
    </div>
    <div class="ap-actions">
      <button data-ap-check>Check now</button>
      <button data-ap-save>${a.editing ? "Save changes" : "Save"}</button>
      <button data-ap-save-start class="primary">${a.editing ? "Save and run" : "Save and start"}</button>
      ${a.editing ? `<button data-ap-new>New bot instead</button>` : ""}
      <span class="ap-msg">${esc(a.msg || "")}</span>
    </div>
    <div id="ap-check">${checkHtml(a.check)}</div>`;
}

function checkHtml(c) {
  if (!c) return "";
  const sides = Object.entries(c.sides || {});
  return `<div class="ap-check"><div class="ap-chead">Read at ${clock(c.at)} &middot; price ${money(c.price)}
      ${c.size ? ` &middot; would trade ${c.size.qty} share${c.size.qty === 1 ? "" : "s"} (${money(c.size.cost)})` : ""}</div>
    ${sides.map(([side, r]) => `<div class="ap-cside${r.met ? " met" : ""}">
      <b>${side === "long" ? "Long" : "Short"}: ${r.met ? "would enter now" : "not yet"}</b>
      ${r.conditions.map((x) => `<div class="ap-cres ${x.met ? "ok" : "no"}"><i class="led"></i>${esc(TYPES[x.type] || x.type)}: ${esc(x.say)}</div>`).join("")}
      ${c.levels ? `<div class="dim">target ${money(c.levels[side].take_profit)} &middot; stop ${money(c.levels[side].stop_loss)}</div>` : ""}
    </div>`).join("")}</div>`;
}

/* ---- the bots ---- */

function statusOf(b) {
  const s = b.state || {};
  if (s.position) return ["active", "Automated trade active"];
  if (s.pending) return ["active", "Order sent"];
  if (s.closing) return ["active", "Closing"];
  if (b.status === "running") return ["run", "Running &middot; waiting for its entry"];
  if (b.status === "paused") return ["pause", "Paused"];
  return ["stop", "Stopped"];
}

function openPnl(b) {
  const p = b.state?.position, m = b.state?.mark;
  if (!p || !m) return null;
  return (m - p.entry) * p.qty * (p.side === "long" ? 1 : -1);
}

function botsHtml() {
  const bots = AP.data?.bots || [];
  const trades = (AP.data?.trades || []).slice(-12).reverse();
  if (!bots.length) return `<div class="dim ap-none">No bots yet. Build one on the left, press Check now to see what
    its conditions read, then save it. Start in Watch mode: it trades on paper-thin air, no orders at all.</div>`;
  return bots.map((b) => {
    const s = b.state || {}, t = s.today || {}, p = s.position;
    const [cls, label] = statusOf(b);
    const pnl = openPnl(b);
    const btn = (act, text, extra = "") => `<button data-ap-act="${b.id}|${act}" ${extra}>${text}</button>`;
    return `<div class="ap-bot st-${cls}">
      <div class="ap-bhead"><b>${esc(b.name)}</b><span class="ap-mode m-${b.mode}">${b.mode}</span>
        <span class="ap-status">${label}</span></div>
      <div class="ap-bnums">${esc(b.symbol)} &middot; pot <b>${money(b.pot)}</b> &middot; today ${t.trades || 0} trade${t.trades === 1 ? "" : "s"},
        <span class="${(t.pnl || 0) >= 0 ? "up" : "down"}">${sm(t.pnl || 0)}</span></div>
      ${p ? `<div class="ap-pos">${p.side} ${p.qty} @ ${money(p.entry)} &middot; now ${money(s.mark)}
          &middot; <b class="${(pnl || 0) >= 0 ? "up" : "down"}">${sm(pnl)}</b><br>
          target ${money(p.tp)} &middot; stop ${money(p.stop)}</div>`
        : b.status === "running" && s.blocked ? `<div class="ap-wait">waiting: ${esc(s.blocked)}</div>` : ""}
      ${!p && b.status === "running" && s.last_check ? `<div class="ap-sees">${["long", "short"].filter((k) => s.last_check[k]).map((k) =>
          `<div><b>${k}</b>${s.last_check[k].conditions.map((c) =>
            `<span class="ap-cres ${c.met ? "ok" : "no"}"><i class="led"></i>${esc(c.say)}</span>`).join("")}</div>`).join("")}</div>` : ""}
      ${s.error ? `<div class="ap-err">${esc(s.error)}</div>` : ""}
      <div class="ap-events">${(s.events || []).slice(-3).reverse().map((e) =>
        `<div><span>${clock(e.at)}</span>${esc(e.say)}</div>`).join("")}</div>
      <div class="ap-bbtns">
        ${b.status === "running" ? btn("pause", "Pause") : btn("start", b.status === "paused" ? "Resume" : "Start")}
        ${b.status !== "stopped" || p ? btn("stop", "Stop") : ""}
        <button data-ap-edit="${b.id}">Edit</button>
        ${b.status === "stopped" && !p ? btn("delete", "Delete") : ""}
        <span class="ap-cash"><input type="number" min="0" step="any" placeholder="$" data-cash-amt="${b.id}">
          <button data-cash="${b.id}|1">Add</button><button data-cash="${b.id}|-1">Pull</button></span>
      </div>
    </div>`;
  }).join("") + (trades.length ? `<h4 class="ap-th">Recent automated trades</h4>
    <div class="ap-trades">${trades.map((t) => `<div class="ap-trade">
      <span>${clock(t.exit_at)}</span><span>${esc(t.symbol)} ${t.side} ${t.qty}</span>
      <span>${money(t.entry)} &rarr; ${money(t.exit)}</span><span class="${t.pnl >= 0 ? "up" : "down"}">${sm(t.pnl)}</span>
      <span class="dim">${esc(t.reason)}${t.mode === "watch" ? " &middot; simulated" : ""}</span></div>`).join("")}</div>` : "");
}

function workshop(tab) {
  // Only on Aarav's own copy. The public site never draws the route, so
  // arriving here as a visitor (a stale tab) just goes back to the routes.
  if (!IS_OWNER) { tab.ui.route = null; setTimeout(render, 0); return ""; }
  if (!AP.data) {
    refresh();
    return `<div class="loading" style="height:40%"><div class="spinner"></div><div>Loading autopilot&hellip;</div>
      ${AP.error ? `<div class="stage down">${esc(AP.error)}</div>` : ""}</div>`;
  }
  const a = state(tab);
  return `<div class="ap">
    <div id="ap-head" class="ap-head">${headHtml()}</div>
    <div class="ap-cols">
      <section class="ap-build">${builderHtml(a)}</section>
      <section class="ap-side"><h3>Your bots</h3><div id="ap-bots">${botsHtml()}</div></section>
    </div>
  </div>`;
}

/* ---- the Trade log's panel ---- */

function logHtml() {
  if (!IS_OWNER) return "";
  if (!AP.data) return `<div id="ap-log"></div>`;
  const bots = (AP.data.bots || []).filter((b) => b.status !== "stopped" || b.state?.position);
  const trades = (AP.data.trades || []).slice(-6).reverse();
  if (!bots.length && !trades.length) {
    return `<div id="ap-log" class="ap-lognone">No automated trades.
      <button class="plink" data-ap-open>Build a bot on Autopilot</button></div>`;
  }
  return `<div id="ap-log"><div class="bookhead">automated <button class="plink" data-ap-open>open Autopilot</button></div>
    <div class="booklist">
      ${bots.map((b) => {
        const s = b.state || {}, p = s.position, [cls, label] = statusOf(b), pnl = openPnl(b);
        return `<div class="bookrow ap-lrow">
          <span>${esc(b.symbol)}</span>
          <span><span class="ap-flag f-${cls}">${p ? "Automated trade active" : label.replace("&middot;", "&middot;")}</span>
            ${esc(b.name)} &middot; ${b.mode}${p ? ` &middot; ${p.side} ${p.qty} @ ${money(p.entry)}` : ""}</span>
          <span class="${(pnl || 0) >= 0 ? "up" : "down"}">${p ? sm(pnl) : ""}</span>
          <span>today ${sm(s.today?.pnl || 0)}</span>
          <span>${p ? `stop ${money(p.stop)}` : `pot ${money(b.pot)}`}</span>
        </div>`;
      }).join("")}
      ${trades.map((t) => `<div class="bookrow ap-lrow done">
          <span>${esc(t.symbol)}</span><span>closed ${t.side} ${t.qty} &middot; ${esc(t.bot_name || "")} &middot; ${esc(t.reason)}${t.mode === "watch" ? " (simulated)" : ""}</span>
          <span class="${t.pnl >= 0 ? "up" : "down"}">${sm(t.pnl)}</span><span>${money(t.entry)} &rarr; ${money(t.exit)}</span>
          <span>${clock(t.exit_at)}</span></div>`).join("")}
    </div></div>`;
}

function badge() {
  const n = (AP.data?.bots || []).filter((b) => b.state?.position).length;
  const r = (AP.data?.bots || []).filter((b) => b.status === "running").length;
  return n ? `${n} auto active` : r ? `${r} auto` : "";
}

/* ---- wiring: once, on the document, so a redraw never needs rewiring ---- */

function setPath(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  keys.slice(0, -1).forEach((k) => { o = o[k] ||= {}; });
  o[keys[keys.length - 1]] = value;
}

const draftTab = () => { const t = current(); return onAuto(t) ? t : null; };

function redrawBuilder(tab) {
  const el = document.querySelector(".ap-build");
  if (el) { el.innerHTML = builderHtml(state(tab)); gloss(el); }
}

function readValue(el) {
  if (el.type === "checkbox") return el.checked;
  if (el.type === "number") return el.value === "" ? 0 : Number(el.value);
  return el.value;
}

document.addEventListener("change", (e) => {
  const tab = draftTab();
  if (!tab) return;
  const a = state(tab), d = a.draft, el = e.target;
  if (el.dataset.k) {
    let v = readValue(el);
    if (el.dataset.k === "symbol") v = String(v).trim().toUpperCase();
    setPath(d, el.dataset.k, v);
  } else if (el.dataset.c) {
    const [side, i, k] = el.dataset.c.split("|");
    d[side].conditions[Number(i)][k] = readValue(el);
  } else if (el.dataset.sideOn) {
    d[el.dataset.sideOn].enabled = el.checked;
    el.closest(".ap-rules")?.classList.toggle("off", !el.checked);
  } else if (el.dataset.sideMatch) {
    d[el.dataset.sideMatch].match = el.value;
  } else if (el.dataset.addCond) {
    if (!el.value) return;
    d[el.dataset.addCond].conditions.push({ type: el.value, ...clone(DEFAULTS[el.value]) });
    d[el.dataset.addCond].enabled = true;
    redrawBuilder(tab);
  }
});

async function run(tab, fn, okMsg) {
  const a = tab ? state(tab) : null;
  try {
    const out = await fn();
    if (a && okMsg) a.msg = okMsg;
    await refresh();
    return out;
  } catch (err) {
    if (a) a.msg = String(err.message || err);
    else alert(String(err.message || err));
    return null;
  } finally {
    if (a) { const m = document.querySelector(".ap-msg"); if (m) m.textContent = a.msg; }
  }
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-ap-tpl], [data-del-cond], [data-ap-check], [data-ap-save], [data-ap-save-start], "
    + "[data-ap-new], [data-ap-act], [data-ap-edit], [data-cash], [data-ap-kill], [data-ap-live], [data-ap-open]");
  if (!el) return;
  const tab = draftTab();
  const a = tab ? state(tab) : null;

  if (el.dataset.apOpen !== undefined) {
    const t = newPositionTab();
    t.ui.route = "auto";
    t.ui.view = "work";
    render();
    return;
  }
  if (el.dataset.apKill !== undefined) {
    if (!confirm("Stop every bot? Any position a bot holds is closed at market.")) return;
    return run(tab, () => post("/kill"), "every bot stopped");
  }
  if (el.dataset.apLive) {
    if (el.dataset.apLive === "on") {
      const word = prompt("Bots set to Live mode will trade REAL MONEY on your Alpaca live account.\n\nType LIVE to switch live trading on.");
      if (word === null) return;
      return run(tab, () => post("/live", { enabled: true, confirm: word.trim() }), "live trading on");
    }
    return run(tab, () => post("/live", { enabled: false }), "live trading off");
  }
  if (el.dataset.apAct) {
    const [id, act] = el.dataset.apAct.split("|");
    const bot = (AP.data?.bots || []).find((b) => b.id === id);
    if (act === "stop" && bot?.state?.position && !confirm(`Stop ${bot.name}? Its open position is closed at market.`)) return;
    if (act === "delete" && !confirm(`Delete ${bot?.name}? Its past trades stay in the log.`)) return;
    if (act === "start" && bot?.mode === "live" && !confirm(`${bot.name} trades REAL MONEY. Start it?`)) return;
    return run(tab, () => post(`/bots/${id}/${act}`), `${act === "start" ? "started" : act + "d"}`);
  }
  if (el.dataset.cash) {
    const [id, dir] = el.dataset.cash.split("|");
    const amt = Number(document.querySelector(`[data-cash-amt="${id}"]`)?.value || 0);
    if (!(amt > 0)) return;
    return run(tab, () => post(`/bots/${id}/cash`, { amount: amt * Number(dir) }), "");
  }
  if (!tab) return;

  if (el.dataset.apTpl) {
    a.draft = draftFrom(el.dataset.apTpl, a.draft?.symbol || tab.ui.symbol || "");
    a.editing = null;
    a.check = null;
    a.msg = "";
    redrawBuilder(tab);
  } else if (el.dataset.delCond) {
    const [side, i] = el.dataset.delCond.split("|");
    a.draft[side].conditions.splice(Number(i), 1);
    redrawBuilder(tab);
  } else if (el.dataset.apNew !== undefined) {
    a.draft = draftFrom("momentum", a.draft?.symbol || "");
    a.editing = null;
    a.check = null;
    a.msg = "";
    redrawBuilder(tab);
  } else if (el.dataset.apEdit) {
    const bot = (AP.data?.bots || []).find((b) => b.id === el.dataset.apEdit);
    if (!bot) return;
    const { name, symbol, mode, long, short, exits, size, limits, session, pot } = clone(bot);
    a.draft = { name, symbol, mode, long, short, exits, size, limits, session, pot };
    a.editing = bot.id;
    a.check = null;
    a.msg = `editing ${bot.name}`;
    redrawBuilder(tab);
  } else if (el.dataset.apCheck !== undefined) {
    a.msg = "reading the market…";
    document.querySelector(".ap-msg").textContent = a.msg;
    try {
      a.check = await post("/check", a.draft);
      a.msg = "";
    } catch (err) {
      a.msg = String(err.message || err);
    }
    const c = document.getElementById("ap-check");
    if (c) c.innerHTML = checkHtml(a.check);
    document.querySelector(".ap-msg").textContent = a.msg;
  } else if (el.dataset.apSave !== undefined || el.dataset.apSaveStart !== undefined) {
    const start = el.dataset.apSaveStart !== undefined;
    if (start && a.draft.mode === "live" && !confirm("This bot trades REAL MONEY. Save and start it?")) return;
    const saved = await run(tab, () => post("/bots", { ...a.draft, id: a.editing }), "saved");
    if (!saved) return;
    a.editing = saved.id;
    if (start && saved.status !== "running") await run(tab, () => post(`/bots/${saved.id}/start`), "saved and started");
    redrawBuilder(tab);
  }
});

panel("log", "auto", "Bots running or holding, flagged while a trade is active", () => logHtml());

window.QUIPU_AUTO = { workshop, logHtml, badge, refresh };
}());
