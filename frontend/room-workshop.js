/* Room: Workshop -- build a position and price it.
 *
 * The three routes in (ready-made, by target price, leg by leg), the
 * board, the money block, and the analysis.
 */

function newPositionTab() {
  const book = loadBook();
  const tab = {
    id: ++state.seq, symbol: null, kind: "position", status: "position",
    data: null, error: null, live: true, loading: false,
    ui: {
      symbol: "",
      // Legs start empty: they are picked off the board, not typed in.
      legs: [],
      book,
      // The workshop is only ever the workshop now. The log is its own
      // room, so this tab does not have to decide which of the two you
      // meant by opening it.
      view: "new",
      editing: null,
      chain: null, expiry: null, chainLoading: false, chainError: null,
      basis: "atm", unit: "cash",
      // Which way in. A position restored from a previous session goes
      // straight to the custom workspace -- it already exists, and
      // hiding it behind a question about how to build it would be
      // asking someone to choose a door they are already through.
      route: null,
      leaving: null,
      suggest: [],
      zoom: null,
    },
  };
  state.tabs.push(tab);
  state.active = tab.id;
  render();
  return tab;
}

/* The legs as they would actually be traded.
 *
 * A leg carries the shape of the position -- one long call against one
 * short one is a spread whichever size it is put on in -- and `size`
 * carries how much of it. Kept apart rather than multiplied into the
 * legs themselves so the ratio survives: a 1x2 stays a 1x2 at every
 * size, and stepping the size up and back down returns the exact
 * quantities rather than something rounded twice.
 *
 * Everything that leaves the builder goes through here, so what is
 * priced and what is written to the log cannot disagree about size.
 */
function sizedLegs(u) {
  const n = Math.max(1, Math.round(Number(u.size) || 1));
  return u.legs
    .filter((l) => Number(l.qty) > 0
      && (l.kind === "stock" ? l.entry !== "" : l.strike !== "" && l.expiry))
    .map((l) => ({ ...l, qty: Number(l.qty) * n }));
}

/* Build the structures around a price, and price them all. */
async function loadTarget(tab) {
  const u = tab.ui;
  if (!u.symbol || !u.target) return;
  u.targetLoading = true;
  u.targetError = null;
  render(true);
  try {
    const res = await fetch(
      `${API}/api/target/${encodeURIComponent(u.symbol)}`
      + `?price=${encodeURIComponent(u.target)}`
      + (u.expiry ? `&expiry=${encodeURIComponent(u.expiry)}` : ""));
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.statusText);
    u.targetData = body;
  } catch (err) {
    u.targetData = null;
    u.targetError = String(err.message || err);
  }
  u.targetLoading = false;
  render(true);
}

async function analysePosition(tab) {
  const legs = sizedLegs(tab.ui);
  if (!tab.ui.symbol || !legs.length) { tab.data = null; render(); return; }

  /* Every click on the board fires one of these, and they take a couple of
   * seconds each. Adding a second leg while the first is still in flight
   * meant two requests were racing, and whichever finished last won -- so
   * building a spread by clicking twice quickly left the page insisting it
   * was a single call, with the second leg visible in the chips above and
   * missing from every number below. Stamp each request and let only the
   * newest one land. */
  const stamp = (tab.ui.req = (tab.ui.req || 0) + 1);
  tab.loading = true;
  renderPositionStatus(tab);

  let data = null, error = null;
  try {
    const res = await fetch(`${API}/api/position`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: tab.ui.symbol, legs }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.statusText);
    data = body;
  } catch (err) {
    error = String(err.message || err);
  }

  if (stamp !== tab.ui.req) return;        // a later click already won
  tab.data = data;
  tab.error = error;
  tab.loading = false;
  // A trade already in the book keeps up to date as it is edited. One
  // being built is not written until it is added, so abandoning a
  // half-assembled spread leaves no trace of it.
  if (tab.ui.editing) commitTrade(tab, tab.ui.editing);
  if (state.active === tab.id) render(true);
}

function renderPositionStatus(tab) {
  const el = document.getElementById("pos-status");
  if (el) el.textContent = tab.loading ? "pricing..." : "";
}

/* ---- positions, drawn ------------------------------------------------
 *
 * Not a form. Every options tool in existence asks you to type a strike
 * and an expiry into boxes, which means you have to already know what is
 * listed and what it costs before you can describe what you own.
 *
 * So the board comes first. Pick the company, pick the date, and the
 * actual contracts appear as a ladder with the share price drawn through
 * it -- calls to the left, puts to the right, strikes down the middle,
 * the way the chain is laid out in your head. Behind every price is a bar
 * showing open interest, so the strikes that genuinely trade are visible
 * at a glance instead of having to be read out of a column of integers.
 *
 * Then you click a price to say you bought or sold it. The leg carries
 * the mark as its entry, which is wrong -- you paid your own price, not
 * today's -- so every chip stays editable. Being approximately right in
 * one click beats being exactly right in nine.
 */

async function loadChain(tab, expiry) {
  const u = tab.ui;
  if (!u.symbol) return;
  u.chainLoading = true;
  render(true);
  try {
    const p = new URLSearchParams();
    if (expiry) p.set("expiry", expiry);
    p.set("basis", u.basis || "atm");
    const res = await fetch(`${API}/api/chain/${encodeURIComponent(u.symbol)}?${p}`);
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.statusText);
    u.chain = body;
    u.expiry = body.expiry;
    u.chainError = null;
  } catch (err) {
    u.chain = null;
    u.chainError = String(err.message || err);
  }
  u.chainLoading = false;
  render(true);
  if (u.legs.some((l) => l.strike || l.kind === "stock")) analysePosition(tab);
}

let posSuggestTimer = null;

async function posSuggest(tab, q) {
  const u = tab.ui;
  if (q.trim().length < 1) { u.suggest = []; paintPosSuggest(tab); return; }
  try {
    const res = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
    u.suggest = ((await res.json()).results || []).slice(0, 8);
  } catch { u.suggest = []; }
  paintPosSuggest(tab);
}

function paintPosSuggest(tab) {
  const box = document.getElementById("pos-suggest");
  if (!box) return;
  const rows = tab.ui.suggest || [];
  if (!rows.length) { box.innerHTML = ""; box.style.display = "none"; return; }
  box.style.display = "block";
  box.innerHTML = rows.map((r) => `<div data-psym="${esc(r.symbol)}">
      <span class="s">${esc(r.symbol)}</span><span class="n">${esc(r.name)}</span>
      <span class="e">${esc(r.exchange || "")}</span></div>`).join("");
  box.querySelectorAll("[data-psym]").forEach((el) => {
    el.onclick = () => {
      tab.ui.symbol = el.dataset.psym;
      tab.ui.suggest = [];
      tab.ui.chain = null;
      render();
      loadChain(tab);
    };
  });
}

/* Ready-made structures off the board in front of you.
 *
 * Knowing you are mildly bullish is the easy half. Turning that into
 * "long the 340 call, short the 355" is the part that stops people, and
 * it is mechanical -- so the app does it, states what you would have to
 * believe in a sentence, and puts the odds next to the payoff so the
 * trade-off is visible before you commit rather than after.
 *
 * The pattern the numbers always show is the one worth seeing: the
 * setups that work seven times in ten make small money, and the ones
 * with no cap on the upside work three times in ten. */
/* Which way a position leans, drawn the same way everywhere.
 *
 * Read off the payoff by the engine, not off the name of the structure:
 * a bull call spread entered upside-down is not bullish, and the label
 * would go on saying it was.
 *
 * The word alone is not enough. "Bullish" covers a long call that needs
 * a six percent rise and a cash-secured put that needs the price not to
 * fall four percent -- opposite amounts of hoping under one word -- so
 * the chip says whether it NEEDS the move or merely HOLDS a level.
 */
const BIAS_ARROW = { bullish: "&uarr;", bearish: "&darr;",
                     neutral: "&harr;", either: "&#8597;" };
const BIAS_WORD = { bullish: "bullish", bearish: "bearish",
                    neutral: "wants it still", either: "wants a move" };

function biasChip(p, cls = "") {
  if (!p || !p.bias || p.bias === "unclear") return "";
  return `<span class="bias b-${esc(p.bias)} ${cls}" title="${esc(p.plain || "")}">
    <i>${BIAS_ARROW[p.bias] || ""}</i>${BIAS_WORD[p.bias] || esc(p.bias)}${
      p.shade === "holds" ? `<em>holds</em>` : p.shade === "needs" ? `<em>needs it</em>` : ""}
  </span>`;
}

/* Two setups side by side, the way a character select compares two
 * fighters.
 *
 * Seventeen cards is a menu, and a menu that commits you the moment you
 * touch it is a trap. Picking one now PINS it rather than opening it,
 * and hovering any other shows the two against each other row by row,
 * so the question "is this one cheaper, and what do I give up for it"
 * is answered by looking rather than by opening both and remembering
 * the first.
 *
 * Deliberately no winner is declared. These trade off against each
 * other by construction -- the setups with the best odds are the ones
 * that make the least, which is a fact about options and not a fault
 * in any particular one -- so each ROW says which way it goes and the
 * reader decides what they are buying. Marking an overall victor would
 * be inventing a preference they have not stated.
 */

/** The rows, and which direction is which. `good` is per-row only. */
const VS_ROWS = [
  {
    key: "cash", label: "cash today",
    /* Positive is money out. A credit trade is negative, and
     * "cheaper" across a debit and a credit is not a comparison
     * anybody means -- so the row says which it is in words. */
    of: (p) => p.net_cost ?? null,
    show: (v) => (v == null ? "&ndash;"
      : v >= 0 ? `you pay ${money(Math.abs(v), 0)}`
               : `you receive ${money(Math.abs(v), 0)}`),
    good: "low", note: "less out of your account",
  },
  {
    key: "chance", label: "chance of making money",
    of: (p) => p.chance ?? null,
    show: (v) => (v == null ? "&ndash;" : nf(v, 0) + "%"),
    good: "high", note: "more often right",
  },
  {
    key: "best", label: "most it can make",
    of: (p) => (p.max_profit_unbounded ? Infinity : p.max_profit ?? null),
    show: (v) => (v == null ? "&ndash;" : v === Infinity ? "no cap" : money(v, 0)),
    good: "high", note: "more when it works",
  },
  {
    key: "worst", label: "most it can lose",
    of: (p) => (p.max_loss_unbounded ? Infinity
      : p.max_loss == null ? null : Math.abs(p.max_loss)),
    show: (v) => (v == null ? "&ndash;" : v === Infinity ? "no limit" : money(v, 0)),
    good: "low", note: "less when it does not",
  },
  {
    key: "ratio", label: "made for each $1 risked",
    of: (p) => {
      const mp = p.max_profit_unbounded ? Infinity : p.max_profit;
      const ml = p.max_loss_unbounded ? Infinity
        : (p.max_loss == null ? null : Math.abs(p.max_loss));
      if (mp == null || ml == null || ml === 0) return null;
      if (mp === Infinity) return Infinity;
      if (ml === Infinity) return 0;
      return mp / ml;
    },
    // A cash-secured put makes $130 against $33,120 at risk. Two
    // decimals prints that as "0.00x", which reads as zero rather than
    // as very small -- and very small is the whole point of the row.
    show: (v) => (v == null ? "&ndash;" : v === Infinity ? "uncapped"
      : v === 0 ? "no cap on the risk"
      : nf(v, v < 0.1 ? 3 : 2) + "\u00d7"),
    good: "high", note: "more per dollar at stake",
  },
  {
    key: "move", label: "move it needs",
    /* How far the share has to travel to break even. The honest
     * common denominator between a call and a condor: both have a
     * level, and the distance to it is what has to happen. */
    of: (p) => {
      const bes = p.breakevens || [];
      const spot = p.spot_used;
      if (!bes.length || !spot) return null;
      return Math.min(...bes.map((b) => Math.abs(b / spot - 1) * 100));
    },
    show: (v) => (v == null ? "&ndash;" : nf(v, 1) + "%"),
    good: "low", note: "less has to happen",
  },
];

/** One setup against another, or on its own when nothing is hovered. */
function vsBody(pin, hov) {
  const cell = (r, p) => (p ? r.show(r.of(p)) : "");

  const verdict = (r) => {
    if (!hov) return "";
    const a = r.of(pin), b = r.of(hov);
    if (a == null || b == null || a === b) return "";
    const hovWins = r.good === "high" ? b > a : b < a;
    // Named rather than coloured alone, and always says which SETUP --
    // "better" with no subject is the thing that makes these panels
    // unreadable.
    return `<span class="vsw ${hovWins ? "vsb" : "vsa"}">${
      esc((hovWins ? hov : pin).name)}: ${esc(r.note)}</span>`;
  };

  return `
    <div class="vshead">
      <div class="vscol vspin">
        <span class="vslab">holding</span>
        <b>${esc(pin.name)}</b>${biasChip(pin)}
      </div>
      ${hov ? `<div class="vscol vshov">
        <span class="vslab">comparing</span>
        <b>${esc(hov.name)}</b>${biasChip(hov)}
      </div>` : `<div class="vscol vsempty">
        <span class="vslab">comparing</span>
        <i>hover another setup</i>
      </div>`}
    </div>
    <div class="vsrows">
      ${VS_ROWS.map((r) => `<div class="vsrow">
        <span class="vsname">${esc(r.label)}</span>
        <span class="vsv">${cell(r, pin)}</span>
        <span class="vsv vsv2">${hov ? cell(r, hov) : "&middot;"}</span>
        <span class="vsverdict">${verdict(r)}</span>
      </div>`).join("")}
    </div>
    <div class="vsfoot">
      These pull against each other: the setups with the best odds are the
      ones that make the least, and the ones with no cap on the upside are
      right least often. No row here outranks another.
    </div>
    <div class="vsact">
      <button class="bookadd" data-openpre="${esc(pin.id)}">open ${esc(pin.name)} &rarr;</button>
      <button class="bookclose" data-unpin="1">clear</button>
    </div>`;
}

function renderPresets(tab, c) {
  const list = c.presets || [];
  if (!list.length) return "";
  const open = tab.ui.presetsOpen !== false;
  const chosen = list.find((p) => p.id === tab.ui.preset);

  // Picking one opens it rather than loading it. Eleven cards is a menu,
  // and a menu that commits you the moment you touch it is a trap -- the
  // whole point of looking at a setup is to find out whether you want it.
  if (chosen) return `<div class="presets">${presetDetail(tab, chosen, c)}</div>`;

  const pin = list.find((p) => p.id === tab.ui.pinned);

  return `<div class="presets${pin ? " haspin" : ""}">
    <div class="expbar">
      <span class="explab">ready-made setups</span>
      <button class="plink" id="pre-toggle">${open ? "hide" : "show"}</button>
      <span class="exphint">${pin
        ? "hover any other to compare it against the one you are holding"
        : "pick one to hold it, then hover the others to compare"}</span>
    </div>
    ${pin ? `<aside class="vs" id="vs-panel">${vsBody(pin, null)}</aside>` : ""}
    ${open ? `<div class="pregrid">
      ${list.map((p) => `
        <button class="pcard lean-${esc(p.bias || "unclear")}${
          p.id === tab.ui.pinned ? " pinned" : ""}" data-preset="${esc(p.id)}">
          <span class="odds"><b>${p.chance == null ? "--"
            : calc(nf(p.chance, 0) + "%", p.chance_working)}</b>
            <i>chance of making money</i></span>
          <span class="pname">${esc(p.name)}${biasChip(p)}</span>
          <span class="pview">${esc(p.view)}</span>
          <span class="psum">${p.summary}</span>
          <span class="plegs">${p.legs.map((l) =>
            `${l.side === "long" ? "buy" : "sell"} ${l.qty}
             ${l.kind === "stock" ? "shares"
               : `${nf(l.strike, l.strike % 1 ? 1 : 0)} ${l.kind}`}`).join(" &middot; ")}</span>
          <span class="puse">${p.id === tab.ui.pinned
            ? "holding &mdash; open it &rarr;" : "hold this one"}</span>
        </button>`).join("")}
    </div>
    <div class="prenote">The percentage is the chance the setup is worth more
      than it cost by expiry, worked out from today&rsquo;s option prices. It is
      not a forecast, and it says nothing about <b>how much</b> &mdash; the setups
      with the best odds are the ones that make the least.</div>` : ""}
  </div>`;
}

/* ---- the money, before anything else ---------------------------------
 *
 * Everything on this page used to sit at one weight: what you paid was a
 * chip the same size as how many sessions were left. So the single most
 * important fact about a trade -- this much leaves your account today,
 * and here is the most it can ever come back as -- had to be assembled
 * by a reader out of a row of equal-looking numbers.
 *
 * Three columns, in the order the money actually moves. Today, then the
 * best case, then the worst. Each says what the number IS as well as
 * what it is worth, because "you receive $57" and "you keep $57" are
 * different claims and a credit trade is where people confuse them: the
 * cash arrives immediately and is not yours until the thing expires.
 */
/* "has to stay below $343" reads correctly; "you keep it if it stay
 * below $343" does not. The backend hands over a bare verb phrase so it
 * can follow "has to", and this puts it in the third person for the
 * sentences that need it. */
function third(text) {
  if (!text) return text;
  const i = text.indexOf(" ");
  const head = i < 0 ? text : text.slice(0, i);
  const tail = i < 0 ? "" : text.slice(i);
  return head + (/(s|sh|ch|x|z)$/.test(head) ? "es" : "s") + tail;
}

/* What the trade costs to place, which is not nothing.
 *
 * The page said "commissions are not included" and stopped, which is
 * true and useless: on a four-leg iron condor taking in $51, a round
 * turn at the going rate is $5.20 -- ten percent of the maximum
 * profit, on the structure the app is most likely to recommend for
 * its odds. A disclaimer that does not carry a number cannot be
 * weighed against anything.
 *
 * Per contract per leg, charged again to close. Stock legs are free
 * at every broker worth using. The rate is an estimate and is named
 * as one: brokers differ, some charge nothing, and a few still charge
 * a ticket fee on top.
 */
const FEE_PER_CONTRACT = 0.65;

function commissionOf(legs) {
  const contracts = (legs || [])
    .filter((l) => l.kind !== "stock")
    .reduce((n, l) => n + Math.abs(Number(l.qty) || 0), 0);
  if (!contracts) return null;
  const one = contracts * FEE_PER_CONTRACT;
  return { contracts, open: one, round: one * 2 };
}

function moneyBlock(a, symbol, spot, size = 1) {
  const cost = a.net_cost || 0;
  const credit = cost < 0;
  const paid = Math.abs(cost);
  const n = a.needs || {};
  /* A maximum without the price it happens at is half a fact -- and the
   * price is nearly always a range, because these payoffs go flat once
   * past a strike. */
  const oneRange = (r) => {
    // A single point first: a cash-secured put reaches its worst case
    // only if the shares go to zero, and "at or below $0.00" would make
    // that sound like a range of outcomes rather than the one.
    if (Math.abs(r.hi - r.lo) < 0.005) return `at ${money(r.lo)}`;
    if (r.to_zero && r.to_inf) return "anywhere";
    if (r.to_zero) return `at or below ${money(r.hi)}`;
    if (r.to_inf) return `at or above ${money(r.lo)}`;
    return `between ${money(r.lo)} and ${money(r.hi)}`;
  };
  const at = (rs) => {
    if (!rs || !rs.length) return "";
    const t = rs.map(oneRange).join(", or ");
    return `If it finishes ${t}: `;
  };

  const mp = a.max_profit_unbounded ? null : a.max_profit;
  const ml = a.max_loss_unbounded ? null : (a.max_loss == null ? null : Math.abs(a.max_loss));

  // What the worst case means in cash, which is not the same sentence
  // for money you have already handed over and money you have taken in.
  let worstWhy;
  if (a.max_loss_unbounded) {
    worstWhy = "There is no ceiling on a share price, so there is no floor "
             + "under this loss. It can exceed what you were paid many times over.";
  } else if (credit) {
    worstWhy = `${at(a.worst_at)}you keep the ${money(paid)} you were paid, but `
             + `closing it costs ${money((ml || 0) + paid)} &mdash; ${money(ml)} down overall.`;
  } else if (ml != null && Math.abs(ml - paid) < 0.51) {
    worstWhy = `${at(a.worst_at)}every penny you paid. It expires worthless `
             + "and there is nothing left to sell.";
  } else {
    worstWhy = `${at(a.worst_at)}less than the ${money(paid)} you paid, because `
             + "part of the position still has value at expiry.";
  }

  const bestWhy = a.max_profit_unbounded
    ? "Nothing caps this. The further it runs, the more it makes."
    : credit
      // Two ranges in one sentence, and they were different ranges:
      // where the maximum is reached, and where the position stops
      // making anything. "yours if it finishes between 219.49 and
      // 228.01" contradicted the "between 220.00 and 227.50" directly
      // in front of it. The break-evens have their own rows above.
      ? `${at(a.best_at)}you keep the whole ${money(paid)} you were paid, and no more.`
      : mp != null
        ? `${at(a.best_at)}you sell it back for ${money(mp + paid)}, having paid ${money(paid)}.`
        : "";

  const ratio = (!credit && mp != null && paid > 0)
    ? `Risking ${money(paid)} to make ${money(mp)} &mdash; <b>${nf(mp / paid, 1)}&times;</b> what you put in.`
    : (credit && ml != null && paid > 0)
      ? `Risking ${money(ml)} to make ${money(paid)} &mdash; you are putting up <b>${nf(ml / paid, 1)}&times;</b> what you stand to earn.`
      : "";

  const arrow = { up: "&uarr;", down: "&darr;", still: "&ndash;", move: "&harr;" }[n.dir] || "";

  /* What is actually being bought, in the same words the order would
   * use. The grid below says what it costs and what it can do; without
   * this it never says what IT IS, and a reader had to reconstruct that
   * from the leg table further down the page. */
  const legLine = (l) => `<span class="mnyleg ${l.side}"><b>${
    l.side === "long" ? "buy" : "sell"} ${nf(l.qty, 0)}</b> ${
    l.kind === "stock" ? "shares"
      : `${strikeOf(l.strike)} ${l.kind}${l.expiry ? ` <i>${esc(l.expiry)}</i>` : ""}`}</span>`;
  const buying = (a.legs || []).map(legLine).join("");

  const contracts = (a.legs || [])
    .filter((l) => l.kind !== "stock")
    .reduce((t, l) => t + (Number(l.qty) || 0), 0);

  return `
  <div class="mny">
    ${hopeBlock(a, symbol, spot, n, arrow)}

    <div class="mnysize">
      <span class="mszlab">size</span>
      <button class="mszbtn" data-size="down" title="one less"
              aria-label="one less">&minus;</button>
      <input class="mszin" id="pos-size" value="${size}" inputmode="numeric"
             aria-label="how many of this structure to trade">
      <button class="mszbtn" data-size="up" title="one more"
              aria-label="one more">+</button>
      <span class="mszhint">&times; the structure below${
        contracts ? ` &mdash; <b>${nf(contracts, 0)}</b> contract${contracts === 1 ? "" : "s"} in total` : ""
      }. Every figure on this page moves with it.</span>
    </div>

    <div class="mnywhat">
      <div class="mnylab">what you are buying</div>
      <div class="mnylegs">${buying}</div>
    </div>

    <div class="mnygrid four">
      <div class="mnycol today">
        <div class="mnylab">${credit ? "you receive today" : "you pay today"}</div>
        <div class="mnybig">${credit ? "+" : "&minus;"}${
          calc(money(paid), a.working?.net_cost)}</div>
        <div class="mnywhy">${credit
          ? "Cash arrives in your account now &mdash; but it is not yours to keep until this is closed or expires."
          : "Cash leaves your account now. This is the whole of what you have committed."}</div>
      </div>
      <div class="mnycol best">
        <div class="mnylab">most you can make</div>
        <div class="mnybig">${a.max_profit_unbounded ? "no cap"
          : "+" + calc(money(mp), a.working?.max_profit)}</div>
        <div class="mnywhy">${bestWhy}</div>
      </div>
      <div class="mnycol worst">
        <div class="mnylab">most you can lose</div>
        <div class="mnybig">${a.max_loss_unbounded ? "no limit"
          : "&minus;" + calc(money(ml), a.working?.max_loss)}</div>
        <div class="mnywhy">${worstWhy}</div>
      </div>
    </div>
    ${ratio ? `<div class="mnyratio">${ratio}</div>` : ""}
    ${(() => {
      const fee = commissionOf(a.legs);
      if (!fee) return "";
      const cap = a.max_profit_unbounded ? null : a.max_profit;
      // Against the maximum rather than against the cost: the cost of
      // trading matters in proportion to what the trade can win, and
      // on a high-odds credit structure that proportion is the thing
      // nobody mentions.
      const bite = cap && cap > 0 ? (fee.round / cap) * 100 : null;
      return `<div class="mnyfee">Commission is on top of all of this:
        about <b>${money(fee.round)}</b> for the round turn
        (${plural(fee.contracts, "contract")} in and out at
        ${money(FEE_PER_CONTRACT)} each)${bite == null ? ""
          : ` &mdash; <b>${nf(bite, 0)}%</b> of the most this can make`}.
        An estimate: brokers differ, and some charge nothing.
        You are also down half the spread the moment you open: you buy at
        the ask and the position is marked at the middle, so a fresh trade
        shows a small loss before anything has happened.</div>`;
    })()}
    ${mnyMath(a)}
  </div>`;
}

/* The three sums, open on the page.
 *
 * Hovering a number to see where it came from works when you already
 * suspect it. It does not work for the figure you are deciding on,
 * which wants to be readable without being asked for -- so the
 * arithmetic behind what you pay, what you can make and what you can
 * lose is simply printed underneath them.
 */
function mnyMath(a) {
  const w = a.working || {};
  const panes = [
    ["what you pay to open it", w.net_cost],
    ["the most it can make", w.max_profit],
    ["the most it can lose", w.max_loss],
  ].filter(([, x]) => x && x.lines?.length);
  if (!panes.length) return "";

  return `<details class="mnymath" open>
    <summary>the arithmetic behind those three numbers</summary>
    <div class="mnymathgrid">
      ${panes.map(([label, x]) => `<div class="mnymathpane">
        <h6>${label}</h6>${wcalc(x)}</div>`).join("")}
    </div>
  </details>`;
}

/* Which way you want it to go, and how far.
 *
 * The direction on its own does not tell you what you have signed up
 * for. "Bullish" covers a long call that needs a six percent rise and a
 * cash-secured put that needs the price not to fall four percent --
 * opposite amounts of hoping, under one word. So the levels are printed
 * in the order the share price would reach them, each with the move it
 * represents from where the stock actually is.
 */
function hopeBlock(a, symbol, spot, n, arrow) {
  const h = a.hope;
  const sym = esc(symbol || "It");

  // No payoff to read a direction off: say the sentence that is still
  // true rather than inventing a lean.
  if (!h || !h.bias || h.bias === "unclear") {
    return `<div class="mnyneed ${esc(n.dir || "")}">
      <span class="mnyarrow">${arrow}</span>
      <span class="mnytext">${sym} has to
        <b>${esc(n.text || "finish in profit")}</b></span></div>`;
  }

  const want = { bullish: "go up", bearish: "go down",
                 neutral: "stay where it is", either: "move, either way" }[h.bias];
  const hold = { bullish: "stay up", bearish: "stay down",
                 neutral: "stay in its range", either: "move" }[h.bias];

  return `<div class="mnyhope lean-${esc(h.bias)}">
    <div class="mnyhead">
      <span class="mnyarrow">${BIAS_ARROW[h.bias] || arrow}</span>
      <span class="mnywant">you want ${sym} to
        <b>${h.shade === "holds" ? hold : want}</b></span>
      ${biasChip(h, "big")}
    </div>
    <div class="mnyfrom">from <b>${money(spot)}</b>, where it is now</div>
    ${h.steps?.length ? `<ol class="mnysteps">
      ${h.steps.map((st) => `<li>
        <span class="mslab">${esc(st.label)}</span>
        <span class="msval">${st.level == null ? "&mdash;" : money(st.level)}</span>
        <span class="mspct ${st.pct == null ? "" : st.pct >= 0 ? "up" : "down"}">${
          st.pct == null ? "" : signed(st.pct, 1)}</span>
        <span class="msnote">${esc(st.note || "")}</span>
      </li>`).join("")}
    </ol>` : ""}
  </div>`;
}

/* One setup, opened up.
 *
 * The card answers "what is this". This answers "what am I actually
 * signing up for", which is a different question and needs the arithmetic
 * rather than a summary of it: every leg spelled out and why that strike
 * and not the one beside it, what it is worth across a spread of finishing
 * prices, and where the line crosses zero.
 */
function presetDetail(tab, p, c) {
  const legs = p.legs_explained || [];

  /* Only what is particular to a ready-made setup lives here: what you
   * would have to believe, the odds, and why these strikes and not the
   * ones beside them. Everything below is renderAnalysis -- the same
   * document the build-it-yourself route ends at, because they are the
   * same position and two presentations of one thing would only raise
   * the question of which to believe. */
  return `
  <div class="expbar">
    <button class="plink" id="pre-back">&larr; all setups</button>
    <span class="exphint">${esc(p.expiry || "")}${p.days_left == null ? ""
      : ` &middot; ${p.days_left} trading session${p.days_left === 1 ? "" : "s"} left`}</span>
  </div>

  <div class="pdhead">
    <div class="pdname">
      <h4>${esc(p.name)}</h4>
      <div class="pdview">${esc(p.view)} ${esc(p.note || "")}</div>
    </div>
    <div class="pdodds">
      <b>${p.chance == null ? "--" : calc(nf(p.chance, 0) + "%", p.chance_working)}</b>
      <span>chance of making money</span>
      <em>The odds this is worth more than it cost by ${esc(p.expiry || "expiry")},
        worked out from today&rsquo;s option prices. Not a forecast.</em>
      ${p.chance_working ? `<details class="oddswork">
        <summary>where this number comes from</summary>
        ${wcalc(p.chance_working)}</details>` : ""}
    </div>
  </div>

  <div class="pdsec">why these strikes</div>
  ${legs.map((l) => `<div class="pdleg">
      <span class="pdlt">${esc(l.text)}</span>
      <span class="pdlc">${l.direction === "out" ? "&minus;" : "+"}${money(Math.abs(l.cash))}</span>
      ${l.why ? `<span class="pdlw">${esc(l.why)}</span>` : ""}
    </div>`).join("")}
  <div class="prenote">Strikes are picked by delta, which is the only strike
    selector that carries across from a $16 stock to a $340 one. Each leg is
    priced at what you would actually pay to buy or receive to sell, not the
    midpoint between them.</div>

  ${tab.data ? renderAnalysis(tab)
    : `<div class="loading" style="height:160px"><div class="spinner"></div>
        <div>Pricing it</div></div>`}

  <button class="pduse" data-use="${esc(p.id)}">Open this on the board to edit it
    &rarr;</button>
  <div class="prenote">Takes the same legs into the build-it-yourself workspace,
    where the strikes, the quantities and the prices you actually paid can all be
    changed. Nothing here is placed with a broker.</div>`;
}

function renderLadder(tab, withPresets = true) {
  const u = tab.ui, c = u.chain;
  if (u.chainLoading) {
    return `<div class="loading" style="height:180px"><div class="spinner"></div>
      <div>Loading the chain for ${esc(u.symbol)}</div></div>`;
  }
  if (u.chainError) {
    return `<div class="empty" style="height:130px"><div class="down">No contracts</div>
      <div class="stage">${esc(u.chainError)}</div></div>`;
  }
  if (!c) return "";

  const exps = c.all_expiries || [];
  const pills = `<div class="cseg expiries">${exps.slice(0, 12).map((e) => `
    <button data-pexp="${esc(e)}" class="${e === u.expiry ? "on" : ""}">${esc(e.slice(5))}</button>`
  ).join("")}</div>`;

  // Which contracts you already hold, so the row can say so.
  const held = new Map();
  u.legs.forEach((l) => {
    if (l.kind === "stock" || !l.strike) return;
    const k = `${l.kind}:${Number(l.strike)}`;
    const cur = held.get(k) || { qty: 0 };
    cur.qty += (l.side === "short" ? -1 : 1) * (Number(l.qty) || 0);
    held.set(k, cur);
  });

  const byStrike = new Map();
  (c.calls || []).forEach((r) => byStrike.set(r.strike, { strike: r.strike, call: r }));
  (c.puts || []).forEach((r) => {
    const e = byStrike.get(r.strike) || { strike: r.strike };
    e.put = r; byStrike.set(r.strike, e);
  });
  const all = [...byStrike.values()].sort((a, b) => a.strike - b.strike);
  const spot = c.spot || 0;
  const rows = all
    .map((r, i) => ({ r, i, d: Math.abs(r.strike - spot) }))
    .sort((a, b) => a.d - b.d).slice(0, 20)
    .concat(all.map((r, i) => ({ r, i, d: 0 })).filter((x) =>
      held.has(`call:${x.r.strike}`) || held.has(`put:${x.r.strike}`)))
    .filter((x, i, arr) => arr.findIndex((y) => y.r.strike === x.r.strike) === i)
    .sort((a, b) => a.r.strike - b.r.strike).map((x) => x.r);

  /* At the money is the listed strike closest to the share price.
   *
   * Not a band and not a rule of thumb: the board has a finite ladder
   * of strikes and exactly one of them is nearest. That is the row the
   * whole chain is read outward from -- it carries the volatility every
   * other strike is compared against -- and it was the only landmark on
   * the board with no mark on it at all. */
  const atmStrike = rows.length
    ? rows.reduce((best, r) =>
        Math.abs(r.strike - spot) < Math.abs(best.strike - spot) ? r : best).strike
    : null;

  const inVol = u.unit === "vol";
  const num = (v, dp = 2) => (v == null ? "&ndash;" : nf(v, dp));

  // What the stock has actually done, over the window the panel names.
  // One figure for the whole board -- it is a property of the share,
  // not of any strike -- so it is stated once in the bar and only the
  // gap is repeated down the rows.
  const hv = c.realised?.rv20 ?? null;

  const side = (r, kind, strike, itm) => {
    if (!r) return `<span class="q oi">&ndash;</span><span class="q">&ndash;</span>
      <span class="q">&ndash;</span><span class="q">&ndash;</span><span class="q">&ndash;</span>
      <span class="q edge">&ndash;</span><span class="q px">&ndash;</span><span class="q px">&ndash;</span>`;
    const ed = inVol ? r.edge_vol : r.edge;
    const edCls = ed == null ? "" : (ed > (inVol ? 0.2 : 0.02) ? "dear"
      : ed < (inVol ? -0.2 : -0.02) ? "cheap" : "flat");
    const edTxt = ed == null ? "&ndash;"
      : (ed > 0 ? "+" : "−") + nf(Math.abs(ed), inVol ? 1 : 2);
    const bid = r.bid, ask = r.ask;
    const cells = [
      // Open interest says one thing: whether you can get back out.
      // The number alone cannot -- 1,240 is a deep strike on one board
      // and a backwater on another -- so the read against the rest of
      // this board travels with it, and the thin ones are marked.
      `<span class="q oi ${esc((r.oi_read?.level) || "")}"
         title="${esc(r.oi_read?.say || `${big(r.open_interest)} contracts open`)}"
         >${big(r.open_interest)}</span>`,
      `<span class="q">${big(r.volume)}</span>`,
      `<span class="q">${r.iv == null ? "&ndash;" : nf(r.iv, 1)}</span>`,
      // Implied against what the stock has actually been doing. One
      // number per strike, because implied volatility varies across
      // the board and realised does not -- the gap is the thing that
      // differs, so the gap is what gets the column.
      (() => {
        const gap = (r.iv == null || hv == null) ? null : r.iv - hv;
        const cls = gap == null ? "" : gap > 1.5 ? "dear" : gap < -1.5 ? "cheap" : "flat";
        return `<span class="q ivhv ${cls}" title="${r.iv == null || hv == null ? ""
          : `implied ${nf(r.iv, 1)}% against realised ${nf(hv, 1)}%`}">${
          gap == null ? "&ndash;" : (gap > 0 ? "+" : "\u2212") + nf(Math.abs(gap), 1)}</span>`;
      })(),
      `<span class="q">${r.delta == null ? "&ndash;" : nf(Math.abs(r.delta), 2)}</span>`,
      `<span class="q edge ${edCls}" title="${r.fair == null ? "" : `worth ${money(r.fair)} at the reference`}">${edTxt}</span>`,
      bid ? `<button class="q px sell" data-add="short|${kind}|${strike}|${bid}"
              title="Sell one ${kind} at the bid, ${money(bid)}">${num(bid)}</button>`
          : `<span class="q px">&ndash;</span>`,
      ask ? `<button class="q px buy" data-add="long|${kind}|${strike}|${ask}"
              title="Buy one ${kind} at the ask, ${money(ask)}">${num(ask)}</button>`
          : `<span class="q px">&ndash;</span>`,
    ];
    // Puts mirror: bid and ask stay next to the strike on both sides.
    // Six informational cells now, not five, so the split moves with it
    // -- hard-coding the old index put the bid and ask in the middle of
    // the put side and the open interest against the strike.
    return (kind === "put" ? cells.slice(6).concat(cells.slice(0, 6).reverse())
                           : cells).join("");
  };

  let spotDrawn = false;
  const body = rows.map((row) => {
    const crossed = !spotDrawn && row.strike > spot;
    if (crossed) spotDrawn = true;
    const hc = held.get(`call:${row.strike}`)?.qty || 0;
    const hp = held.get(`put:${row.strike}`)?.qty || 0;
    const badge = (q) => q ? `<i class="pos ${q > 0 ? "l" : "s"}">${q > 0 ? "+" : ""}${q}</i>` : "";
    /* The share price used to be labelled in the centre of the board,
     * directly on top of the strike column it was trying not to obscure.
     * The line still runs across -- knowing which rungs are above and
     * below is the point of it -- but the label sits out in the margin. */
    return (crossed
      ? `<div class="spotrow"><span>${esc(u.symbol)} ${money(spot)}</span></div>` : "")
      + `<div class="crow${hc || hp ? " mine" : ""}${
            row.strike === atmStrike ? " atm" : ""}">
          <div class="cside calls ${row.strike < spot ? "itm" : "otm"}">
            ${side(row.call, "call", row.strike, row.strike < spot)}</div>
          <div class="cstrike" title="${row.strike === atmStrike
            ? "At the money: the listed strike nearest " + money(spot)
            : row.strike < spot
              ? "Calls here are in the money, puts are out"
              : "Puts here are in the money, calls are out"}">${badge(hc)}<b>${
            nf(row.strike, row.strike % 1 ? 1 : 0)}</b>${badge(hp)}</div>
          <div class="cside puts ${row.strike > spot ? "itm" : "otm"}">
            ${side(row.put, "put", row.strike, row.strike > spot)}</div>
        </div>`;
  }).join("");

  const callHead = ["open int", "volume", "impl vol", "iv \u2212 hv", "delta",
                    inVol ? "vs fair" : "vs fair $", "bid", "ask"];
  const putHead = ["bid", "ask", inVol ? "vs fair" : "vs fair $", "delta",
                   "iv \u2212 hv", "impl vol", "volume", "open int"];

  return `<div class="chainwrap">
    <div class="expbar">
      <span class="explab">expiry</span>${pills}
      <span class="exphint">${c.days == null ? "" : `${c.trading_days} sessions away`}</span>
    </div>
    <div class="expbar">
      <span class="explab">compare against</span>
      <div class="cseg">
        <button data-basis="atm" class="${(u.basis || "atm") === "atm" ? "on" : ""}">at-the-money${c.atm_iv ? ` ${nf(c.atm_iv, 0)}%` : ""}</button>
        <button data-basis="realised" class="${u.basis === "realised" ? "on" : ""}">realised${c.realised?.rv20 ? ` ${nf(c.realised.rv20, 0)}%` : ""}</button>
      </div>
      <div class="cseg">
        <button data-unit="cash" class="${(u.unit || "cash") === "cash" ? "on" : ""}">in $</button>
        <button data-unit="vol" class="${u.unit === "vol" ? "on" : ""}">in vol pts</button>
      </div>
      <span class="mnykey">
        <b class="k-itm">in the money</b>
        <b class="k-atm">at the money</b>
        <b class="k-otm">out of the money</b>
      </span>
      <span class="exphint">${hv == null ? ""
        : `realised <b>${nf(hv, 1)}%</b> over 20 sessions &middot; `}click an
        <b>ask</b> to buy &middot; click a <b>bid</b> to sell</span>
    </div>

    ${withPresets ? renderPresets(tab, c) : ""}

    <div class="chain">
      <div class="crow chead2">
        <div class="cside calls"><span class="hd">calls
          <i class="mny-dir">in the money below ${money(spot)} &darr;</i></span></div>
        <div class="cstrike"></div>
        <div class="cside puts"><span class="hd">puts
          <i class="mny-dir">&uarr; in the money above ${money(spot)}</i></span></div>
      </div>
      <div class="crow chead">
        <div class="cside calls">${callHead.map((h) => `<span class="q">${h}</span>`).join("")}</div>
        <div class="cstrike"><b>strike</b></div>
        <div class="cside puts">${putHead.map((h) => `<span class="q">${h}</span>`).join("")}</div>
      </div>
      ${body}
    </div>
    <div class="cfoot">
      <b>open int</b> is how many contracts are standing open at that strike,
      which is the size of the crowd you would be selling back to. It is the
      one number on the board that answers &ldquo;can I get out of this&rdquo;
      &mdash; hover any of them for what it means against the rest of this
      board, since a thousand contracts is deep on one chain and quiet on
      another. Strikes with almost nothing open are marked.
      <b>iv &minus; hv</b> is this strike&rsquo;s implied volatility less what the
      share has actually done over the last twenty sessions, in points. Positive
      means the option is priced for more movement than the stock has been
      producing, which favours selling it; negative, the reverse. It is not a
      verdict &mdash; implied volatility is about the future and realised is
      about the past, and a gap is often there for a reason that has not
      happened yet.
      <b>vs fair</b> is what the contract costs over (+) or under (&minus;) the same
      option valued at ${esc(c.fair_label || "the reference")} volatility${inVol
        ? ", in points of volatility &mdash; the unit that compares across strikes, "
          + "since a far out-of-the-money contract barely responds to volatility at all"
        : ", in dollars"}.
      <b>Shaded cells are in the money</b> &mdash; already worth something if
      today were expiry. Which side that is flips at the share price: a call is
      in the money below ${money(spot)} and a put above it, so the shading runs
      down one side of the board and up the other. The
      <b>ruled row</b> is at the money, the listed strike nearest the share
      price. Everything unshaded is out of the money and worth nothing at
      expiry unless the price comes to it.
      ${c.spot_source && c.spot_source !== "quote"
        ? `Priced off <b>${money(c.spot)}</b>, read from ${esc(c.spot_source)} rather than the
           quoted ${money(c.spot_quoted)}: the quote lags the options tape, and using it put the
           call and the put on one strike three points of volatility apart.`
        : ""}
    </div>
  </div>`;
}

/* ---- the fork ---------------------------------------------------- */

function renderRoutes(tab) {
  const going = tab.ui.leaving;
  return `<div class="routewrap">
    <div class="routes${going ? ` picked to-${going}` : ""}">
      <button class="route" data-route="custom">
        <span class="rk">Build it myself</span>
        <span class="rd">Click prices off the option board to assemble any
          position, one leg at a time. Quipu names the structure once it
          recognises it, and tells you what to do with it.</span>
        <span class="rg">any structure &middot; 28 recognised</span>
      </button>
      <button class="route" data-route="ready">
        <span class="rk">Use a ready-made setup</span>
        <span class="rd">Seventeen standard structures, already built from
          today&rsquo;s prices with the strikes chosen for you, each with the
          odds on it and what you would have to believe.</span>
        <span class="rg">pick from a menu &middot; nothing to assemble</span>
      </button>
      <button class="route" data-route="target">
        <span class="rk">I have a price in mind</span>
        <span class="rd">Name the price you think it reaches and Quipu builds
          the structures around that number rather than around a delta,
          then ranks them by what each one pays if you turn out to be
          right.</span>
        <span class="rg">strikes from your number &middot; capped against uncapped</span>
      </button>
      ${IS_OWNER ? `<button class="route" data-route="auto">
        <span class="rk">Run it on autopilot</span>
        <span class="rd">Build a bot from conditions &mdash; momentum, breakouts,
          RSI, VWAP, fair value gaps &mdash; and it trades the stock by itself
          with a stop-loss and take-profit on every trade. Watch mode first,
          then paper, then live when you switch it on.</span>
        <span class="rg">stocks &middot; long or short &middot; start and stop any time</span>
      </button>` : ""}
    </div>
  </div>`;
}

/* Structures built around a price you name.
 *
 * The catalogue picks strikes by delta, which is right when the view
 * is about direction. When the view is about a NUMBER, the strikes
 * should come from the number -- and then the comparison becomes
 * interesting rather than obvious, because a capped structure
 * usually beats an uncapped one at a specific target. You are
 * refusing to pay for upside past the point you have said it stops.
 */
function renderTarget(tab) {
  const u = tab.ui;
  const c = u.chain;
  const spot = c?.spot;

  const field = `<div class="tgbar">
    <span class="explab">price you think it reaches</span>
    <div class="tginput">
      <span class="tgcur">$</span>
      <input id="tg-price" type="text" inputmode="decimal" autocomplete="off"
        value="${u.target == null ? "" : esc(String(u.target))}"
        placeholder="${spot ? nf(spot, 2) : "0.00"}">
    </div>
    <button class="bookadd" id="tg-go">build them</button>
    ${spot ? `<span class="exphint">it trades at <b>${money(spot)}</b>${
      u.target ? ` &middot; your number is
        <b>${signed((u.target / spot - 1) * 100, 1)}</b> from there` : ""}</span>` : ""}
  </div>`;

  if (!u.symbol) {
    return field + `<div class="loading" style="height:30%">
      <div>Which company?</div></div>`;
  }
  if (u.targetLoading) {
    return field + `<div class="loading" style="height:30%">
      <div class="spinner"></div><div>Building them around ${
        money(u.target)}</div></div>`;
  }
  if (u.targetError) {
    return field + `<div class="empty" style="height:130px">
      <div class="down">Could not build those</div>
      <div class="stage">${esc(u.targetError)}</div></div>`;
  }
  const r = u.targetData;
  if (!r) {
    return field + `<div class="empty" style="height:140px">
      <div>Name a price above</div>
      <div class="stage">every structure here will be built around it,
        and ranked by what it pays if the stock gets there</div></div>`;
  }

  const money0 = (v) => (v == null ? "&ndash;" : money(v, 0));
  const rows = (r.ideas || []).map((i, n) => `
    <div class="tgrow${n === 0 ? " best" : ""}">
      <div class="tgname">
        <b>${esc(i.name)}</b>
        <span class="tgcap ${i.max_profit_unbounded ? "uncapped" : "capped"}">${
          i.max_profit_unbounded ? "no cap on the upside" : "capped"}</span>
        ${biasChip(i)}
      </div>
      <div class="tgnums">
        <span class="tgn"><i>costs today</i><b>${i.net_cost >= 0
          ? "&minus;" + money0(Math.abs(i.net_cost))
          : "+" + money0(Math.abs(i.net_cost))}</b></span>
        <span class="tgn big"><i>pays at ${money(r.target)}</i><b class="${
          i.at_target >= 0 ? "up" : "down"}">${i.at_target >= 0 ? "+" : "&minus;"}${
          money0(Math.abs(i.at_target))}</b></span>
        <span class="tgn"><i>on what is at risk</i><b>${
          i.on_risk == null ? "&ndash;" : nf(i.on_risk, 0) + "%"}</b></span>
        <span class="tgn"><i>most it could make</i><b>${
          i.max_profit_unbounded ? "no cap" : money0(i.max_profit)}</b></span>
        <span class="tgn"><i>most it could lose</i><b>${
          i.max_loss_unbounded ? "no limit" : money0(Math.abs(i.max_loss || 0))}</b></span>
        <span class="tgn"><i>chance of any profit</i><b>${
          i.chance == null ? "&ndash;"
            : calc(nf(i.chance, 0) + "%", i.chance_working)}</b></span>
      </div>
      <div class="tgwhy">${esc(i.why)}</div>
      <div class="tglegs">${(i.legs || []).map((l) =>
        `<span class="mnyleg ${l.side}"><b>${l.side === "long" ? "buy" : "sell"}
          ${nf(l.qty, 0)}</b> ${strikeOf(l.strike)} ${esc(l.kind)}</span>`).join("")}
        <button class="plink" data-tguse="${n}">open this one &rarr;</button>
      </div>
    </div>`).join("");

  return field + `<div class="tgwrap">
    <div class="tghead">If ${esc(u.symbol)} finishes at
      <b>${money(r.target)}</b> on ${esc(r.expiry)} &mdash;
      ${signed(r.move_pct, 1)} from ${money(r.spot)}</div>
    <div class="tgrows">${rows}</div>
    <div class="fnote">Ranked by what each pays IF THE PRICE IS REACHED, which
      is a conditional and not a prediction: nothing here says your number is
      likely, and the chance of any profit at all sits in every row so the two
      can be read together. The capped structures usually win this ranking
      precisely because they are capped &mdash; selling the part above your
      number is what makes them cheaper, and you have already said you do not
      expect it.</div>
  </div>`;
}

/* Once you are inside a route, the other one is a single quiet word
 * rather than a permanent half of the screen. */
function renderRouteBar(tab) {
  const u = tab.ui;
  // Three routes, so "the other one" is no longer a single thing.
  const NAMES = { custom: "build it myself", ready: "use a ready-made setup",
                  target: "name a price", ...(IS_OWNER ? { auto: "autopilot" } : {}) };
  const others = Object.keys(NAMES).filter((k) => k !== u.route);
  const HERE = { custom: "Building it yourself", ready: "Ready-made setups",
                 target: "Built around your price", auto: "Autopilot" };
  return `<div class="routebar">
    <span class="rbnow">${HERE[u.route] || "Workshop"}</span>
    ${others.map((k) =>
      `<button class="plink" data-switch="${k}">${NAMES[k]}</button>`).join("")}
  </div>`;
}

/* ---- the ready-made route ---------------------------------------- */

function renderReady(tab) {
  const u = tab.ui, c = u.chain;
  if (u.chainLoading) {
    return `<div class="loading" style="height:200px"><div class="spinner"></div>
      <div>Building the setups for ${esc(u.symbol)}</div></div>`;
  }
  if (u.chainError) {
    return `<div class="empty" style="height:140px"><div class="down">No contracts</div>
      <div class="stage">${esc(u.chainError)}</div></div>`;
  }
  if (!c) return "";

  const exps = c.all_expiries || [];
  const pills = `<div class="cseg expiries">${exps.slice(0, 12).map((e) => `
    <button data-pexp="${esc(e)}" class="${e === u.expiry ? "on" : ""}">${esc(e.slice(5))}</button>`
  ).join("")}</div>`;

  return `<div class="chainwrap readywrap">
    <div class="expbar">
      <span class="explab">expiry</span>${pills}
      <span class="exphint">${c.days == null ? "" : `${c.trading_days} sessions away`}</span>
    </div>
    ${renderPresets(tab, c)}
  </div>`;
}

function renderPosition(tab) {
  const u = tab.ui, d = tab.data, c = u.chain;

  const bar = `<div class="livebar">
    <span class="lbsym">${esc(u.symbol || "Position")}</span>
    ${c ? `<span class="lbprice"><b>${money(c.spot)}</b>
      <span class="${sign(c.change_pct)}">${signed(c.change_pct, 2)}</span></span>` : ""}
    <span class="grow"></span>
    <span id="pos-status" class="dim"></span>
    ${d ? `<span>${d.marks_live}/${d.legs.filter((l) => l.kind !== "stock").length} legs priced live</span>
           <span>IV <b>${pct(d.vol_used, 1)}</b></span>` : ""}
    ${d ? `<button id="pos-price">Reprice</button>` : ""}
    ${roomNav("position")}
  </div>`;

  const picker = `<div class="pospick">
    <div class="searchwrap" style="width:min(420px,60vw)">
      <div class="searchbox">
        <input id="pos-sym" value="${esc(u.symbol)}" autocomplete="off" spellcheck="false"
          placeholder="Company name or ticker">
      </div>
      <div class="suggest" id="pos-suggest" style="display:none"></div>
    </div>
    <button id="pos-stock">+ shares</button>
    ${u.legs.length ? `<button id="pos-clear">clear all</button>` : ""}
  </div>`;

  const chips = u.legs.length ? `<div class="chips">
    ${u.legs.map((l, i) => `<div class="chip ${l.side}" data-leg="${i}">
      <span class="cs">${l.side}</span>
      <input data-f="qty" value="${esc(l.qty)}" title="contracts, or shares for stock">
      <span class="ck">${l.kind === "stock" ? "shares"
        : `${nf(Number(l.strike), Number(l.strike) % 1 ? 1 : 0)} ${l.kind}`}</span>
      ${l.kind === "stock" ? "" : `<span class="cx">${esc((l.expiry || "").slice(5))}</span>`}
      <span class="at">@</span>
      <input data-f="entry" value="${esc(l.entry)}" title="what you actually paid, per share">
      <button data-drop="${i}" title="Remove"
        aria-label="Remove this leg">&times;</button>
    </div>`).join("")}
  </div>` : `<div class="chips empty-chips">Nothing yet &mdash; click a price on the board below</div>`;

  // ---- the fork -------------------------------------------------
  //
  // Two entirely different jobs were sharing one screen. Building a
  // spread leg by leg and picking a ready-made structure off a menu
  // want opposite things: the first wants the board and a set of
  // chips, the second wants to be left alone with eleven cards. Shown
  // together, the board pushed the setups below the fold and the
  // setups made the board look like something you had to read first.
  if (!u.route) return bar + renderRoutes(tab);

  // The bots: their own builder, no option board.
  if (u.route === "auto") return bar + renderRouteBar(tab) + window.QUIPU_AUTO.workshop(tab);

  if (u.route === "target") {
    // renderTarget handles "no company yet" itself, and the price
    // field belongs on screen before the ticker is chosen -- the
    // number is the whole point of this route and hiding it until
    // something else is filled in reads as a broken page.
    return bar + renderRouteBar(tab) + picker + renderTarget(tab)
      + (u.legs.length ? chips + renderAnalysis(tab) : "");
  }

  let out = bar + renderRouteBar(tab) + picker;
  if (u.route === "ready") {
    if (!u.symbol) {
      return out + `<div class="loading" style="height:34%">
        <div>Which company?</div>
        <div class="stage">the setups are built from its live option prices</div></div>`;
    }
    return out + renderReady(tab);
  }

  out += chips;
  if (!u.symbol) {
    out += `<div class="loading" style="height:34%">
      <div>Search for the company you traded</div>
      <div class="stage">the contracts load, you click the ones you own,
        and the strategy is worked out from them</div></div>`;
    return out;
  }
  out += renderLadder(tab, false);

  return out + renderAnalysis(tab);
}

/* The analysis itself, which is the same document however you arrived at
 * it. Building a spread by hand and picking one off the menu produce the
 * same legs, so they get the same page: the name the detector gave it,
 * the money, the payoff, each leg, and what to do with it. Two different
 * presentations of one position would only invite the question of which
 * one to believe. */
/* The last thing on both routes.
 *
 * Whichever way the position was assembled, it ends the same way: into
 * the log. The route was a path, and this is where both paths arrive. */
function renderCommit(tab) {
  const u = tab.ui;
  if (u.editing) {
    const t = u.book.find((x) => x.id === u.editing);
    return `<div class="commitbar">
      <span class="cmsg">In your log since ${esc(t?.opened || "")}. Changes here
        are saved as you make them.</span>
      <span class="grow"></span>
      <button class="bookclose" data-close="${esc(u.editing)}">mark as closed</button>
      <button class="bookadd" id="book-done">done &rarr;</button>
    </div>`;
  }
  return `<div class="commitbar">
    <span class="cmsg">Nothing is saved until you add it. Entry prices default
      to today&rsquo;s mark &mdash; correct them above to what you actually paid
      before adding, or edit them later from the log.</span>
    <span class="grow"></span>
    <button class="bookadd" id="book-save">add to the trade log &rarr;</button>
  </div>`;
}

function renderAnalysis(tab) {
  if (tab.error) {
    return `<div class="empty" style="height:140px"><div class="down">Could not price that</div>
      <div class="stage">${esc(tab.error)}</div></div>`;
  }
  if (!tab.data) return "";
  // Which parts, and in what order, is layout.js's call.
  return `<div class="posbody">${compose("position", tab)}</div>`;
}

/* ---- the analysis, piece by piece ----------------------------------
 *
 * Each piece is drawn from the priced position alone, so any of them
 * can be moved, dropped, or reused somewhere else without the others
 * noticing.
 */
const posChip = (label, value, cls = "") =>
  `<div class="pstat"><span>${label}</span><b class="${cls}">${value}</b></div>`;
const MINUS = "−";

panel("position", "head", "The strategy's name, its family, and what it is", (tab) => {
  const s = tab.data.strategy;
  return `<div class="phead">
        <h2>${esc(s.name)}</h2>
        <span class="fam">${esc(s.family)}</span>
        ${s.note ? `<p>${esc(s.note)}</p>` : ""}
      </div>`;
});

panel("position", "money", "The big numbers: what you pay, the most you can win and lose, and the sums",
  (tab) => moneyBlock(tab.data, tab.ui.symbol, tab.data.spot, tab.ui.size || 1));

panel("position", "plain", "The position in two plain sentences", (tab) => {
  const d = tab.data;
  return d.plain ? `<div class="plain">
        <p>${d.plain.position}</p>
        ${d.plain.behaviour ? `<p>${d.plain.behaviour}</p>` : ""}
      </div>` : "";
});

panel("position", "now", "Profit now, of risk, value if closed, break-even, chance, time left", (tab) => {
  const d = tab.data;
  const plCls = d.pl >= 0 ? "up" : "down";
  return `<div class="pstats">
        ${posChip("profit / loss right now",
          calc((d.pl >= 0 ? "+" : MINUS) + money(Math.abs(d.pl), 0), d.working?.profit), plCls)}
        ${posChip("of what is at risk",
          d.pl_pct == null ? "--" : calc(signed(d.pl_pct, 0), d.working?.pl_pct), plCls)}
        ${posChip("worth if closed now", money(d.value_now, 0))}
        ${posChip("break-even", (d.breakevens || []).length
          ? d.breakevens.map((b, i) =>
              calc(money(b), d.breakeven_working?.[i])).join("  /  ")
          : "--")}
        ${posChip("chance of making money", d.chance == null ? "--"
          : calc(nf(d.chance, 0) + "%", d.chance_working))}
        ${posChip("sessions left", d.days_left == null ? "--" : String(d.days_left))}
      </div>`;
});

panel("position", "payoff", "The payoff diagram: strikes, break-evens, max win and loss", (tab) => {
  const d = tab.data;
  return `<h4>${d.valued_at ? `Profit on ${esc(d.valued_at)}, the first expiry`
        : "Profit at expiry"}, against where it finishes</h4>
      ${d.valued_at ? `<div class="fnote" style="padding-top:0">The legs expiring
        later are still alive on that date, so they are valued rather than
        settled &mdash; which is the whole of how this position makes money.</div>` : ""}
      <div class="qchart-host poschart" style="height:250px"></div>`;
});

panel("position", "figures", "The greeks, as shares and dollars", (tab) => {
  const d = tab.data;
  return `<h4>The same thing, as figures</h4>
      <div class="pstats">
        ${posChip("behaves like owning",
          calc(nf(d.share_equivalent, 0) + " shares", d.greek_working?.delta))}
        ${posChip("gain per $1 rise", money(d.greeks.delta, 0))}
        ${posChip("and that grows by",
          calc(nf(d.greeks.gamma, 1) + " shares / $1", d.greek_working?.gamma))}
        ${posChip("time, each day",
          calc((d.greeks.theta >= 0 ? "+" : MINUS) + money(Math.abs(d.greeks.theta)),
               d.greek_working?.theta), d.greeks.theta >= 0 ? "up" : "down")}
        ${posChip("if volatility rises 1pt",
          calc((d.greeks.vega >= 0 ? "+" : MINUS) + money(Math.abs(d.greeks.vega)),
               d.greek_working?.vega))}
      </div>`;
});

panel("position", "legs", "Each leg: expiry, entry, mark, delta, profit", (tab) => {
  const d = tab.data;
  return `<h4>Each leg</h4>
      <div class="plegs">
        <div class="pleg plhead"><span>leg</span><span>expiry</span><span>sessions</span>
          <span>entry</span><span>mark</span><span>delta</span><span>profit</span></div>
        ${d.legs.map((l) => `<div class="pleg">
          <span><b>${l.side} ${nf(l.qty, 0)}</b> ${l.kind === "stock" ? "stock" : `${strikeOf(l.strike)} ${l.kind}`}</span>
          <span>${esc(l.expiry || "--")}</span>
          <span>${l.days == null ? "--" : l.days}</span>
          <span>${money(l.entry)}</span>
          <span>${money(l.mark)}</span>
          <span>${l.delta == null ? "--" : nf(l.delta, 3)}</span>
          <span class="${l.pl >= 0 ? "up" : "down"}">${(l.pl >= 0 ? "+" : MINUS) + money(Math.abs(l.pl), 0)}</span>
        </div>`).join("")}
      </div>`;
});

panel("position", "guidance", "What to do with it, step by step", (tab) => {
  const d = tab.data;
  return `<h4>What to do with it</h4>
      <div class="story-steps full">
        ${(d.guidance || []).map((g, i) => `
          <div class="sstep">
            <span class="sn">${i + 1}</span>
            <div class="sbody">
              <h5>${esc(g.head)}</h5>
              ${g.figure ? `<div class="sfig">${
                // Only hover-attach a sum that comes to the figure it is
                // attached to. A labelled sum explains something next to
                // the figure rather than the figure itself, and hanging
                // it off the number would claim a derivation it is not.
                calc(esc(g.figure), g.working_label ? null : g.working)}</div>` : ""}
              <p>${g.body}</p>
              ${g.working ? `<details class="sworking">
                <summary>${esc(g.working_label || "where that number comes from")}</summary>
                ${wcalc(g.working)}</details>` : ""}
            </div>
          </div>`).join("")}
      </div>`;
});

panel("position", "commit", "Put it in the trade log", (tab) => renderCommit(tab));

panel("position", "footnote", "Where the marks came from, and what is not included", (tab) => {
  const d = tab.data;
  const optLegs = d.legs.filter((l) => l.kind !== "stock").length;
  return `<div class="fnote prose">
        Marks come from the live chain where the contract is listed and from
        Black-Scholes where it is not &mdash; ${d.marks_live} of ${optLegs} option
        legs here are real quotes. Entry prices default to today's mark, which is
        not what you paid: edit them on the chips above. The spread you would
        cross to get out is not included either. Volatility
        ${pct(d.vol_used, 1)}, rate ${pct(d.rate, 2)}, dividend yield ${pct(d.div_yield, 2)}.
      </div>`;
});

function wirePosition(tab) {
  const u = tab.ui;
  wireRooms();

  const sym = document.getElementById("pos-sym");
  if (sym) {
    sym.oninput = () => {
      clearTimeout(posSuggestTimer);
      const q = sym.value;
      posSuggestTimer = setTimeout(() => posSuggest(tab, q), 200);
    };
    sym.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      u.symbol = sym.value.trim().toUpperCase();
      u.suggest = [];
      u.chain = null;
      render();
      loadChain(tab);
    };
  }
  paintPosSuggest(tab);

  document.querySelectorAll("[data-pexp]").forEach((b) => {
    b.onclick = () => loadChain(tab, b.dataset.pexp);
  });

  const bnew = document.getElementById("book-new");
  if (bnew) bnew.onclick = () => {
    u.view = "new"; u.route = null; u.editing = null;
    u.legs = []; tab.data = null; u.preset = null;
    render();
  };

  // Adding to the log used to throw the workshop away and show the
  // log instead, which is a strange reward for saving something: the
  // thing you just built disappears. It stays, now marked as logged,
  // and the log is a click away in the nav like everything else.
  const bsave = document.getElementById("book-save");
  if (bsave) bsave.onclick = () => {
    const id = commitTrade(tab);
    if (!id) return;
    u.editing = id;
    u.marks = { ...(u.marks || {}), [id]: tab.data };
    u.justSaved = true;
    render(true);
  };

  const bdone = document.getElementById("book-done");
  if (bdone) bdone.onclick = () => openRoom("log");

  // Closing from inside an open trade. The live analysis is right
  // there, so what it is worth now is the sensible default and there is
  // nothing further to ask.
  document.querySelectorAll("[data-close]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      u.marks ||= {};
      u.marks[b.dataset.close] = tab.data || u.marks[b.dataset.close];
      settleTrade(tab, b.dataset.close, tab.data?.value_now ?? null);
      render(true);
    };
  });

  document.querySelectorAll("[data-route]").forEach((b) => {
    b.onclick = () => {
      const pick = b.dataset.route;
      // Let the chooser play out before the page changes under it: the
      // unchosen card collapses and the chosen one slides to the middle,
      // and only then does it become the thing it opens.
      u.leaving = pick;
      render();
      setTimeout(() => {
        u.route = pick;
        u.view = "work";
        u.leaving = null;
        render();
        if (u.symbol && !u.chain) loadChain(tab);
      }, 420);
    };
  });

  document.querySelectorAll("[data-switch]").forEach((b) => {
    b.onclick = () => {
      u.route = b.dataset.switch;
      u.preset = null;
      render();
      if (u.symbol && !u.chain) loadChain(tab);
    };
  });

  /* Size.
   *
   * Re-prices rather than scaling the numbers in the browser: max loss
   * is not always linear in size once a position has a stock leg in it,
   * and a figure multiplied client-side would quietly disagree with the
   * one the server would give. One source for every number on the page.
   */
  const setSize = (next) => {
    const n = Math.max(1, Math.min(9999, Math.round(Number(next) || 1)));
    if (n === (u.size || 1)) return;
    u.size = n;
    render(true);
    analysePosition(tab);
  };

  const szin = document.getElementById("pos-size");
  if (szin) {
    szin.onchange = () => setSize(szin.value);
    szin.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); setSize(szin.value); }
      if (e.key === "ArrowUp") { e.preventDefault(); setSize((u.size || 1) + 1); }
      if (e.key === "ArrowDown") { e.preventDefault(); setSize((u.size || 1) - 1); }
    };
  }
  document.querySelectorAll("[data-size]").forEach((b) => {
    b.onclick = () => setSize((u.size || 1) + (b.dataset.size === "up" ? 1 : -1));
  });

  const tgGo = document.getElementById("tg-go");
  const tgPrice = document.getElementById("tg-price");
  const takeTarget = () => {
    const v = Number(String(tgPrice?.value || "").replace(/[^0-9.]/g, ""));
    if (!Number.isFinite(v) || v <= 0) return;
    u.target = v;
    loadTarget(tab);
  };
  if (tgGo) tgGo.onclick = takeTarget;
  if (tgPrice) tgPrice.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); takeTarget(); }
  };

  // Opening one hands it to the workshop, which is where every route
  // ends: the same legs, the same analysis, the same page.
  document.querySelectorAll("[data-tguse]").forEach((b) => {
    b.onclick = () => {
      const idea = (u.targetData?.ideas || [])[Number(b.dataset.tguse)];
      if (!idea) return;
      u.legs = idea.legs.map((l) => ({
        kind: l.kind, side: l.side, qty: l.qty, entry: l.entry,
        strike: l.strike ?? "", expiry: l.expiry ?? "",
      }));
      u.size = 1;
      render(true);
      analysePosition(tab);
      document.querySelector(".chips")?.scrollIntoView(
        { behavior: "smooth", block: "center" });
    };
  });

  const pt = document.getElementById("pre-toggle");
  if (pt) pt.onclick = () => { u.presetsOpen = u.presetsOpen === false; render(true); };

  /* Picking a setup HOLDS it rather than opening it.
   *
   * Seventeen cards is a menu, and a menu that commits you the moment
   * you touch it is a trap: the whole point of looking at a setup is
   * to find out whether you want it. The first click pins it beside
   * the grid; hovering any other compares the two; opening is its own
   * button, so it is always a deliberate act. */
  const presets = () => u.chain?.presets || [];
  const vsHost = () => document.getElementById("vs-panel");

  const repaintVs = (hovId) => {
    const host = vsHost();
    const p = presets().find((x) => x.id === u.pinned);
    if (!host || !p) return;
    // Patched in place rather than through render(): a full rebuild on
    // every mouseenter across seventeen cards is a redraw of the whole
    // board, and the pointer would be over a different element by the
    // time it finished.
    host.innerHTML = vsBody(p, hovId && hovId !== u.pinned
      ? presets().find((x) => x.id === hovId) : null);
    wireVsButtons();
  };

  const openPreset = (id) => {
    const p = presets().find((x) => x.id === id);
    if (!p) return;
    u.preset = id;
    u.legs = p.legs.map((l) => ({
      kind: l.kind, side: l.side, qty: l.qty, entry: l.entry,
      strike: l.strike ?? "", expiry: l.expiry ?? "",
    }));
    render();
    analysePosition(tab);
  };

  function wireVsButtons() {
    const go = document.querySelector("[data-openpre]");
    if (go) go.onclick = (e) => { e.stopPropagation(); openPreset(go.dataset.openpre); };
    const clear = document.querySelector("[data-unpin]");
    if (clear) clear.onclick = (e) => {
      e.stopPropagation(); u.pinned = null; render(true);
    };
  }
  wireVsButtons();

  document.querySelectorAll("[data-preset]").forEach((b) => {
    const id = b.dataset.preset;
    b.onclick = () => {
      // Clicking the one already held opens it -- the second click on
      // the same card is unambiguous about what it means.
      if (u.pinned === id) return openPreset(id);
      u.pinned = id;
      render(true);
    };
    b.onmouseenter = () => { if (u.pinned) repaintVs(id); };
    b.onfocus = () => { if (u.pinned) repaintVs(id); };
    b.onmouseleave = () => { if (u.pinned) repaintVs(null); };
    b.onblur = () => { if (u.pinned) repaintVs(null); };
  });
  const pb = document.getElementById("pre-back");
  if (pb) pb.onclick = () => {
    // The setup stays held on the way back, so returning to the grid
    // returns you to the comparison you were in the middle of.
    u.preset = null; u.legs = []; u.size = 1; tab.data = null; render(true);
  };

  document.querySelectorAll("[data-use]").forEach((b) => {
    b.onclick = () => {
      const p = (u.chain?.presets || []).find((x) => x.id === b.dataset.use);
      if (!p) return;
      // Replaces rather than appends: these are whole structures, and
      // stacking two of them silently makes a third thing you did not pick.
      // Only the fields a leg is made of -- the catalogue rows also carry
      // the delta and IV they were chosen by, which are not part of a leg.
      u.legs = p.legs.map((l) => ({
        kind: l.kind, side: l.side, qty: l.qty, entry: l.entry,
        strike: l.strike ?? "", expiry: l.expiry ?? "",
      }));
      u.preset = null;
      u.route = "custom";
      render();
      analysePosition(tab);
      document.querySelector(".chips")?.scrollIntoView({ behavior: "smooth", block: "center" });
    };
  });

  document.querySelectorAll("[data-unit]").forEach((b) => {
    b.onclick = () => {
      if ((u.unit || "cash") === b.dataset.unit) return;
      u.unit = b.dataset.unit;
      render(true);    // no refetch: both numbers are already on every row
    };
  });

  document.querySelectorAll("[data-basis]").forEach((b) => {
    b.onclick = () => {
      if ((u.basis || "atm") === b.dataset.basis) return;
      u.basis = b.dataset.basis;
      loadChain(tab, u.expiry);
    };
  });

  // Click a price: that contract, that side, one lot, at today's mark.
  document.querySelectorAll("[data-add]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const [side, kind, strike, px] = b.dataset.add.split("|");
      u.legs.push({ kind, side, strike, qty: 1, entry: px, expiry: u.expiry });
      render(true);
      analysePosition(tab);
    };
  });

  const addStock = document.getElementById("pos-stock");
  if (addStock) addStock.onclick = () => {
    u.legs.push({ kind: "stock", side: "long", strike: "", qty: 100,
                  entry: u.chain?.spot ? String(u.chain.spot) : "", expiry: "" });
    render(true);
    analysePosition(tab);
  };

  const clear = document.getElementById("pos-clear");
  if (clear) clear.onclick = () => {
    u.legs = []; tab.data = null;
    if (u.editing) commitTrade(tab, u.editing);
    render(true);
  };

  document.querySelectorAll(".chip[data-leg]").forEach((row) => {
    const i = Number(row.dataset.leg);
    row.querySelectorAll("[data-f]").forEach((inp) => {
      inp.onchange = () => { u.legs[i][inp.dataset.f] = inp.value.trim(); analysePosition(tab); };
    });
    const drop = row.querySelector("[data-drop]");
    if (drop) drop.onclick = () => {
      u.legs.splice(i, 1);
      render(true);
      if (u.legs.length) analysePosition(tab); else { tab.data = null; render(); }
    };
  });

  const price = document.getElementById("pos-price");
  if (price) price.onclick = () => analysePosition(tab);

  const host = document.querySelector(".poschart");
  if (host && tab.data?.curve?.length) {
    // Drawn as a payoff rather than borrowed from the price-series
    // chart. That one was handed {date: "342.50", close: -199} --
    // share prices pretending to be dates -- and could draw the line
    // but none of the things that make the line mean anything: where
    // the strikes are, which side of zero you are on, where the most
    // you can make and lose actually happen.
    const d = tab.data;
    host.innerHTML = window.QUIPU_PAYOFF.payoffSvg({
      curve: d.curve,
      legs: d.legs,
      spot: d.spot,
      breakevens: d.breakevens,
      maxProfit: d.max_profit,
      maxLoss: d.max_loss,
      bestAt: d.best_at,
      worstAt: d.worst_at,
      unboundedUp: d.max_profit_unbounded,
      unboundedDown: d.max_loss_unbounded,
      width: Math.max(560, Math.round(host.clientWidth || 860)),
      height: Math.max(240, Math.round(host.clientHeight || 300)),
    });
  }
}

/* ---- the room ------------------------------------------------------ */

room("position", {
  open: newPositionTab,
  draw: renderPosition,
  wire: wirePosition,
  place: (u) => ({ view: u.view, route: u.route, editing: u.editing,
                   preset: u.preset, symbol: u.symbol,
                   legs: JSON.stringify(u.legs || []) }),
  // The legs came back, the analysis of them did not, and showing the
  // old one would be showing numbers for a different trade.
  resume: (tab) => { if (tab.ui.legs?.length) analysePosition(tab); },
  name: (tab) => (tab.ui.symbol ? tab.ui.symbol + " workshop" : "Workshop"),
});
