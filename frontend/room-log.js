/* Room: Trade log -- what you are holding now.
 *
 * The book, its expiry states, closing and settling, and the two
 * places every row can go.
 */

/* The log, as a place rather than a view.
 *
 * It used to be a mode of the workshop tab -- open the log and the
 * workshop was gone, open a trade and the log was gone. Two things you
 * move between constantly, taking turns in one window. Splitting them
 * means a trade can be open in front of you WHILE the log is still
 * there to go back to, which is the whole reason a tab strip exists.
 */

function newLogTab() {
  const book = loadBook();
  const tab = {
    id: ++state.seq, symbol: null, kind: "log", status: "log",
    data: null, error: null, live: true, loading: false,
    ui: { book, closing: null, marks: {}, zoom: null,
          bankedFrom: loadBankedFrom() },
  };
  state.tabs.push(tab);
  state.active = tab.id;
  render();
  markBook(tab);
  return tab;
}

/* ---- the logbook ---------------------------------------------------
 *
 * Where this tab lives. Both ways of building a trade -- picking
 * contracts off the board and taking a ready-made structure -- end
 * here, because they are two routes to the same destination: a trade
 * you now hold and will want to look at again next week.
 */
/* How close a trade is to expiring, and how loudly to say so.
 *
 * The log already printed "2 sessions" in the same grey as everything
 * else on the row, which is a fact rather than a warning. An option
 * that expires this week is the one thing in a log that has a deadline
 * attached to it -- miss it and the position settles itself, at
 * whatever the price happens to be.
 *
 * Counted from the legs rather than from the analysis, so the mark
 * does not have to have loaded for the warning to be there: the dates
 * are already in the log and a trade expiring today should not be
 * waiting on a network call to say so.
 *
 * Sessions are used where the analysis has them, because a Friday
 * expiry three calendar days out is one trading day away and those are
 * different amounts of time to react in.
 */
/* When the thing actually expires, and what happens if you are still
 * holding it.
 *
 * A session count says how LONG you have. It does not say when, and
 * "1 session left" is not a deadline anybody can act on -- a deadline
 * is a day and a clock time.
 *
 * And for a long option the moment that matters is not really expiry,
 * it is the last moment you can sell. Hold one that finishes in the
 * money and the clearing house exercises it for you: the OCC exercises
 * by exception anything a cent or more in the money unless told
 * otherwise. For a long call that means buying a hundred shares per
 * contract -- a five-figure bill on a share like MSTR, and exactly
 * what somebody trading the option rather than the stock does not
 * want.
 *
 * US equity options stop trading at 4:00pm New York time on the expiry
 * date. That is the deadline, and it is quoted in New York alongside
 * the reader's own clock, because a market deadline in the wrong
 * timezone is worse than no deadline at all.
 */
const NY = "America/New_York";

function sellBy(t, a) {
  const opts = t.legs.filter((l) => l.kind !== "stock" && l.expiry);
  if (!opts.length) return null;                 // stock only: nothing expires

  const next = opts.map((l) => l.expiry).sort()[0];
  const close = nyClose(next);
  if (!close) return null;

  // en-US, because the zone abbreviation is the point of the line and
  // this is a US market deadline: "EDT" is what a trader reads, where
  // en-GB renders the same instant as "GMT-4" and makes them do the
  // arithmetic themselves.
  const fmt = (tz, withZone) => new Intl.DateTimeFormat("en-US", {
    weekday: "short", day: "numeric", month: "short",
    hour: "numeric", minute: "2-digit", hour12: true, timeZone: tz,
    ...(withZone ? { timeZoneName: "short" } : {}),
  }).format(close);

  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const sameClock = fmt(here) === fmt(NY);

  // Only the legs that finish in the money get exercised or assigned,
  // so only those are worth warning about.
  // Only the legs expiring AT this deadline, and only the ones that
  // would be in the money. A calendar spread holds a December leg
  // behind a September one, and warning that December's call will be
  // exercised at September's close names a deadline it does not have.
  const spot = a?.spot;
  const exposed = spot == null ? [] : opts.filter((l) =>
    l.expiry === next
    && (l.kind === "call" ? spot > l.strike : spot < l.strike));

  return {
    at: close,
    ny: fmt(NY, true),
    local: sameClock ? null : fmt(here, true),
    expiry: next,
    exposed,
    consequence: consequenceOf(exposed, next, spot != null),
  };
}

/* 4pm on the expiry date, in New York, as a real instant.
 *
 * Built by asking the runtime where 4pm UTC lands in New York on that
 * date and correcting by the difference, rather than hard-coding an
 * offset: it is four hours in summer and five in winter, and a
 * position opened in October and expiring in November straddles the
 * changeover.
 */
function nyClose(isoDate) {
  const [y, m, d] = String(isoDate).split("-").map(Number);
  if (!y || !m || !d) return null;

  /* Solved rather than offset-corrected.
   *
   * The obvious trick -- render an instant in New York, re-parse it,
   * and take the difference -- is an identity on a machine that is
   * ALREADY in New York, so it shifted nothing and every expiry
   * printed as noon. It only appeared to work from another timezone,
   * which is the worst kind of wrong: right on the developer's laptop
   * and wrong for the person the deadline belongs to.
   *
   * So: guess an instant, ask what New York wall clock it lands on,
   * and correct by how far that is from 4pm. Twice, because the
   * correction can itself cross the daylight-saving boundary.
   */
  const want = Date.UTC(y, m - 1, d, 16, 0, 0);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: NY, hour12: false,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });

  let t = want;
  for (let i = 0; i < 2; i++) {
    const p = {};
    parts.formatToParts(new Date(t)).forEach((x) => { p[x.type] = x.value; });
    const asUTC = Date.UTC(+p.year, +p.month - 1, +p.day,
                           +p.hour % 24, +p.minute, +p.second);
    if (asUTC === want) break;
    t += want - asUTC;
  }
  return new Date(t);
}

function consequenceOf(exposed, expiry, known) {
  // Not knowing where the stock is, and saying nothing is in the money,
  // are different statements. The mark had not loaded -- or had failed
  // -- and this printed the reassuring one, which is the reassurance
  // there is least reason to give.
  if (!known) {
    return `Trading in these stops at the close on ${expiry}. Anything `
         + `in the money at that point is exercised or assigned `
         + `automatically; selling before the close avoids it. What is `
         + `in the money cannot be said here because the live price has `
         + `not come back.`;
  }
  if (!exposed.length) {
    return `Trading in these stops at the close on ${expiry}. Nothing here `
         + `is in the money at today's price, so it would expire `
         + `rather than be exercised — still worth closing if it has `
         + `value left.`;
  }
  const parts = exposed.map((l) => {
    const shares = (Number(l.qty) || 0) * 100;
    const cash = shares * Number(l.strike);
    const long = String(l.side).toLowerCase().startsWith("l");
    if (l.kind === "call") {
      return long
        ? `you would buy ${nf(shares, 0)} shares at ${strikeOf(l.strike)}, about ${money(cash, 0)}`
        : `you would have to deliver ${nf(shares, 0)} shares at ${strikeOf(l.strike)}`;
    }
    return long
      ? `you would sell ${nf(shares, 0)} shares at ${strikeOf(l.strike)}, about ${money(cash, 0)}`
      : `you would be put ${nf(shares, 0)} shares at ${strikeOf(l.strike)}, about ${money(cash, 0)}`;
  });
  return `Trading stops at the close on ${expiry}. If it is still in the money `
       + `then: ${parts.join("; ")}. Selling before the close avoids it. Your `
       + `broker's own cut-off is earlier than the market's.`;
}

function expiryState(t, a) {
  if (t.closed) return null;
  const dates = t.legs.map((l) => l.expiry).filter(Boolean).sort();
  if (!dates.length) return null;             // stock only: nothing expires

  const today = new Date().toISOString().slice(0, 10);
  const next = dates[0];
  const days = Math.round(
    (Date.parse(next + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);
  const sessions = a?.days_left;

  // Already past. The position has settled whether or not the log says
  // so, and leaving it in the open list quietly overstates what is at
  // risk -- so this is the loudest state, not the quietest.
  if (days < 0) {
    return { level: "gone", label: "expired " + next, urgent: true,
             why: "This expired on " + next + ". It has already settled; "
                + "close it in the log so the totals stop counting it as open." };
  }
  if (days === 0) {
    return { level: "today", label: "expires today", urgent: true,
             why: "Today is the last day to trade it." };
  }
  if (sessions === 0) {
    return { level: "today", label: "last session", urgent: true,
             why: "No trading sessions left before it expires on " + next + "." };
  }
  const n = sessions == null ? days : sessions;
  const unit = sessions == null ? "day" : "session";
  const word = `${n} ${unit}${n === 1 ? "" : "s"}`;
  if (n <= 1) return { level: "soon", label: word + " left", urgent: true,
                       why: "Expires " + next + "." };
  if (n <= 5) return { level: "soon", label: word + " left", urgent: false,
                       why: "Expires " + next + "." };
  if (n <= 15) return { level: "near", label: word, urgent: false, why: "" };
  return { level: "far", label: word, urgent: false, why: "" };
}

function renderBook(tab) {
  const u = tab.ui;
  const live = bookOpen(u.book);
  const done = u.book.filter((t) => t.closed);

  const head = `<div class="bookbar">
    <h2>Trade log</h2>
    <span class="bookn">${live.length} open${done.length ? ` &middot; ${done.length} closed` : ""}</span>
    <span class="grow"></span>
    <button class="bookadd" id="book-new">+ new trade</button>
  </div>`;

  if (!live.length && !done.length) {
    return head + `<div class="loading" style="height:44%">
      <div>Nothing in the log yet</div>
      <div class="stage">build a position yourself, or start from a ready-made
        setup &mdash; either way it ends up here</div></div>`;
  }

  /* An open trade is marked to the market and the figure moves with it.
   * A closed one is settled: the result is whatever you actually got,
   * recorded once and never touched again. Showing a stale live mark on
   * a trade you are out of would be the log quietly rewriting history. */
  const row = (t) => {
    const a = u.marks?.[t.id];
    const pl = t.closed ? t.realised : a?.pl;
    const pct = t.closed ? t.realised_pct : a?.pl_pct;
    const cls = pl == null ? "" : pl >= 0 ? "up" : "down";
    const closing = u.closing === t.id;

    const x = expiryState(t, a);
    const sb = t.closed ? null : sellBy(t, a);

    return `<div class="bookitem${closing ? " closing" : ""}${
      x ? " exp-" + x.level : ""}${x?.urgent ? " urgent" : ""}">
      <button class="bookrow ${t.closed ? "shut" : ""}" data-open="${esc(t.id)}">
        <span class="bsym" data-stock="${esc(t.symbol)}" role="button" tabindex="0"
              title="Open everything on ${esc(t.symbol)}">${esc(t.symbol)}</span>
        <span class="bname">${esc(t.name || a?.strategy?.name || legSummary(t.legs))}
          <i>${t.legs.length} leg${t.legs.length > 1 ? "s" : ""}
            &middot; opened ${whenText(t.opened_at, t.opened)}${t.closed
              ? ` &middot; closed ${whenText(t.closed_at, t.closed)}` : ""}</i></span>
        <span class="bpl ${cls}">${pl == null ? (a === null ? "&hellip;" : "&ndash;")
          : calc((pl >= 0 ? "+" : "&minus;") + money(Math.abs(pl), 0),
                 t.closed ? null : a?.attribution)}</span>
        <span class="bpct ${cls}">${pctOfRisk(pct)}</span>
        <span class="bdays" title="${esc(sb?.consequence || x?.why || "")}">${
          t.closed ? "settled"
          : sb ? `${x?.urgent ? `<i class="expdot"></i>` : ""}<b>${esc(sb.ny)}</b>${
              sb.local ? `<i class="blocal">${esc(sb.local)} your time</i>` : ""}`
          : "&ndash;"}</span>
      </button>
      <button class="brow-act" data-stock="${esc(t.symbol)}"
        title="Everything on ${esc(t.symbol)} -- price, options, filings, news">stock</button>
      ${t.closed
        ? `<button class="brow-act" data-reopen="${esc(t.id)}"
             title="Put it back in the open list">reopen</button>`
        : `<button class="brow-act" data-closing="${esc(t.id)}"
             title="Record what you closed it for">close</button>`}
      ${closing ? closeForm(t, a) : ""}
    </div>`;
  };

  /* Two totals, because they are two different facts. What is still at
   * risk moves every time the market does; what is banked does not. A
   * single combined number hides which is which, so they are added
   * together only underneath the pair. */
  // Closed trades from before the line are still listed; they are
  // simply not counted. Two different statements, and the tile says
  // which it is making.
  const from = u.bankedFrom ?? null;
  const counted = done.filter((t) => countsAsBanked(t, from));
  const T = window.QUIPU_LEDGER.bookTotals(
    live.map((t) => u.marks?.[t.id]?.pl ?? null),
    counted.map((t) => t.realised ?? null));
  const openPl = T.open, banked = T.banked, priced = T.priced, wins = T.wins;
  const skipped = done.length - counted.length;

  const tot = (label, value, note, cls) => `<div class="btot ${cls}">
    <span class="btl">${label}</span>
    <b>${value >= 0 ? "+" : "&minus;"}${money(Math.abs(value), 0)}</b>
    <span class="btn2">${note}</span>
  </div>`;

  const totals = (priced || done.length) ? `<div class="booktots">
    ${priced ? tot("still open", openPl,
        `${priced} trade${priced === 1 ? "" : "s"}, marked to the market`,
        openPl >= 0 ? "up" : "down") : ""}
    ${done.length ? tot("banked", banked,
        (counted.length
          ? `${counted.length} closed &middot; ${wins} of ${counted.length} made money`
          : "nothing closed since the reset")
        + (skipped ? ` &middot; <button class="btreset" data-unreset="1"
             title="Count them again">${skipped} earlier one${
               skipped === 1 ? "" : "s"} not counted</button>`
           : ` &middot; <button class="btreset" data-reset="1"
             title="Keep the trades, start the total again from now"
             >reset to zero</button>`),
        banked >= 0 ? "up" : "down") : ""}
    ${priced && done.length ? tot("all in", openPl + banked,
        skipped ? "open and counted, together" : "open and closed together",
        (openPl + banked) >= 0 ? "up" : "down") : ""}
  </div>` : "";

  return head
    + (live.length ? `<div class="booklist">
        <div class="bookrow bhead"><span>ticker</span><span>position</span>
          <span>profit</span><span>of risk</span><span>expires</span></div>
        ${live.map(row).join("")}
      </div>` : "")
    + totals
    + (done.length ? `<div class="bookhead">closed</div>
        <div class="booklist">${done.map(row).join("")}</div>` : "")
    + `<div class="fnote prose">Kept on this machine only. An open trade is
       marked against the entry prices on each leg, which default to the mark
       when the leg was added &mdash; open it to correct them to what you
       actually paid. A closed one keeps whatever you recorded on the way out
       and stops moving.</div>`;
}

/* Closing a trade asks one question, because there is only one thing
 * the app cannot work out for itself: what you actually got for it.
 * The live value is offered as the default, since most of the time
 * that is close enough -- but a trade closed in a hurry rarely fills
 * at the midpoint, and a log that quietly assumes it did will flatter
 * every result in it. */
/* When a trade was opened and when it was closed, to the minute.
 *
 * The log recorded dates. Two trades opened four hours apart on either
 * side of an earnings print read as the same day, and a closing price
 * with no time on it cannot be checked against anything -- a tape, a
 * statement, or your own memory of what you were looking at.
 *
 * Stored as a full instant and shown in local time. The date-only
 * fields stay, because trades already in the log have only those and a
 * log that loses its own history to a format change is worse than one
 * that never had the time.
 */
const stamp = () => new Date().toISOString();

function whenText(iso, dateOnly) {
  if (!iso) return dateOnly ? esc(dateOnly) : "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(dateOnly || "");
  return esc(new Intl.DateTimeFormat("en-GB", {
    day: "numeric", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).format(d));
}

/* What closing actually comes to, written as the subtraction it is.
 *
 * The form asked for a number and then printed a result, with the step
 * between them left to the reader -- and that step is not obvious for
 * anything sold, where "what you paid to open" is a negative number
 * and the result is a sum of two things that both look like income.
 */
function closingWorking(received, cost, paying) {
  if (received == null || cost == null) return null;
  const W = WK();
  const credit = cost < 0;

  // Written in the order the money moved, so the signs match what
  // actually happened rather than what the stored fields look like.
  const lines = credit
    ? [
        W.line("", [W.term("what you were paid to open it", Math.abs(cost))],
               Math.abs(cost)),
        W.line("-", [W.term("what it costs you to close it", Math.abs(received))],
               Math.abs(received)),
      ]
    : [
        W.line("", [W.term("what you get back for closing it", received)], received),
        W.line("-", [W.term("what you paid to open it", cost)], cost),
      ];

  return W.sum(round2(received - cost), lines, "$",
    credit
      ? "You keep the difference. Closing a sold position means buying it "
      + "back, so the whole of what you were paid is only yours if it "
      + "costs nothing to close."
      : "What you get back, less what it cost you. Commissions are not in "
      + "this, and neither is the spread you crossed to get out.");
}

const round2 = (v) => Math.round(v * 100) / 100;

function closeForm(t, a) {
  const value = a?.value_now;
  const cost = a?.net_cost;

  /* Which way the money went, and therefore which question to ask.
   *
   * The engine carries the value of a position signed: a spread you
   * are short is worth a negative amount, because closing it means
   * paying. That is correct and it is also unaskable -- nobody types
   * "-196" under a field marked "value received". So a short position
   * is asked what it COST to close, in plain positive dollars, and the
   * sign is put back on before the arithmetic sees it. */
  const paying = (value != null && value < 0) || (value == null && cost != null && cost < 0);
  const shown = value == null ? null : Math.abs(value);

  return `<div class="closeform" data-paying="${paying ? "1" : "0"}">
    <div class="cfq">${paying
      ? "What did it cost you to close it?"
      : "What did you get for closing it?"}</div>
    <div class="cfrow">
      <span class="cfl">${paying ? "paid to close" : "value received"}</span>
      <input id="close-val" type="text" inputmode="decimal"
        value="${shown == null ? "" : nf(shown, 2)}"
        placeholder="0.00" autocomplete="off">
      <span class="cfhint">${shown == null
        ? "not priced &mdash; enter the amount"
        : `today it would ${paying ? "cost" : "be worth"} ${money(shown)}`}</span>
    </div>
    <div class="cfrow cfsay">
      <span class="cfl"></span>
      <div class="cfhelp">${paying
        ? `The cash that <b>left</b> your account to buy this back, in total
           across every leg &mdash; what your broker charged you to close it.
           Enter it as a positive number.`
        : `The cash that <b>landed in</b> your account when you sold it, in
           total across every leg. If you let it expire worthless, that is
           <b>0</b>.`}
        ${shown == null ? "" : `The box is filled with
          ${shown === 0 ? "<b>0</b>, because the position has no value left at "
            + "today&rsquo;s prices" : `today&rsquo;s mark, ${money(shown)}`}
          &mdash; change it to what you actually
          ${paying ? "paid" : "got"}.`}</div>
    </div>
    ${cost != null ? `<div class="cfrow">
      <span class="cfl">${cost >= 0 ? "you paid to open" : "you were paid to open"}</span>
      <span class="cfv">${money(Math.abs(cost))}</span>
      <span class="cfhint">the result is the difference between the two</span>
    </div>` : ""}
    <div class="cfrow cfwork">
      <span class="cfl">what that comes to</span>
      <div class="cfsum" id="close-sum">${closingSum(t, a, shown, paying)}</div>
    </div>
    <div class="cfrow cfact">
      <span class="cfl"></span>
      <button class="bookadd" data-confirm="${esc(t.id)}">close the trade</button>
      <button class="bookclose" data-cancelclose="1">cancel</button>
    </div>
  </div>`;
}

/* The sum under the closing field, for whatever is typed in it. */
function closingSum(t, a, typed, paying) {
  const cost = a?.net_cost ?? t.net_cost ?? null;
  if (cost == null) {
    return `<span class="cfnone">What it cost to open is not recorded for
      this trade, so the result cannot be worked out &mdash; the amount you
      enter is stored as it is.</span>`;
  }
  const n = typed == null || typed === "" ? null
    : Number(String(typed).replace(/[^0-9.-]/g, ""));
  if (n == null || !Number.isFinite(n)) {
    return `<span class="cfnone">Enter what it
      ${paying ? "cost to close" : "came back for"} and the result appears here.</span>`;
  }
  // Asked as a positive amount, stored signed: money out is a negative
  // amount received, which is what the arithmetic downstream expects.
  const received = paying ? -Math.abs(n) : n;
  const w = closingWorking(received, cost, paying);
  const pl = received - cost;
  return (w ? wcalc(w) : "")
    + `<div class="cfres ${pl >= 0 ? "up" : "down"}">${
        pl >= 0 ? "a gain of " : "a loss of "}<b>${money(Math.abs(pl))}</b></div>`;
}

/* A return against what was at risk, which for a cash-secured put is
 * the whole strike. Twenty dollars on thirty-three thousand rounds to
 * "+0%", which reads as nothing happening rather than as a small gain
 * on a large commitment. */
function pctOfRisk(v) {
  if (v == null) return "";
  if (v === 0) return "0%";
  if (Math.abs(v) < 1) return (v > 0 ? "+" : "−") + "<1%";
  return signed(v, 0);
}

/** A trade with no strategy name yet, described by its legs. */
function legSummary(legs) {
  return legs.slice(0, 3).map((l) =>
    `${l.side === "long" ? "+" : "-"}${l.qty} ${l.kind === "stock" ? "shares"
      : `${nf(Number(l.strike), Number(l.strike) % 1 ? 1 : 0)}${l.kind[0]}`}`
  ).join(" ") + (legs.length > 3 ? ` +${legs.length - 3}` : "");
}

/* Price every open trade so the log shows where they stand. One request
 * each, fired together rather than in turn -- a log of six trades
 * should not take six round trips end to end. */
/* Trading sessions between a date and now.
 *
 * Weekends are not decay. A position opened on Friday and looked at
 * on Monday has aged one session, not three, and telling somebody
 * their theta ran for three days over a weekend is telling them
 * something false about where their money went.
 */
function sessionsSince(iso) {
  if (!iso) return 0;
  const from = new Date(iso);
  if (Number.isNaN(from.getTime())) return 0;
  let n = 0;
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  while (d < today) {
    d.setDate(d.getDate() + 1);
    const day = d.getDay();
    if (day !== 0 && day !== 6) n += 1;
  }
  return n;
}

async function markBook(tab) {
  const live = bookOpen(tab.ui.book);
  if (!live.length) return;
  tab.ui.marks ||= {};
  live.forEach((t) => { if (!(t.id in tab.ui.marks)) tab.ui.marks[t.id] = null; });

  await Promise.all(live.map(async (t) => {
    try {
      const res = await fetch(`${API}/api/position`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: t.symbol,
          legs: t.legs,
          // Sessions are counted here rather than on the server: the
          // log is the only thing that knows when this was opened.
          opened: t.opened_spot ? {
            spot: t.opened_spot,
            vol: t.opened_vol,
            sessions: sessionsSince(t.opened_at || t.opened),
          } : undefined,
        }),
      });
      const body = await res.json();
      tab.ui.marks[t.id] = res.ok ? body : undefined;
    } catch {
      tab.ui.marks[t.id] = undefined;
    }
  }));
  if (state.active === tab.id && tab.kind === "log") render(true);
}

/* Settle a trade: record what it was closed for, and stop marking it.
 *
 * The result is the same arithmetic as the live P&L -- what you got out
 * less what you put in -- but computed once, from a number you supply,
 * and then frozen. A closed trade whose figure keeps moving with the
 * market is not a record of anything.
 */
function settleTrade(tab, id, received) {
  const t = tab.ui.book.find((x) => x.id === id);
  if (!t) return;
  const a = tab.ui.marks?.[id];
  const cost = a?.net_cost;

  t.closed = new Date().toISOString().slice(0, 10);
  t.closed_at = stamp();
  t.exit_value = received;
  // Keep the name and the cost with the trade. Both came from an
  // analysis that will not be run again once it is closed, and a log
  // that forgets what a settled trade WAS is not much of a log.
  t.name = t.name || a?.strategy?.name || null;
  t.net_cost = cost ?? t.net_cost ?? null;

  if (received != null && t.net_cost != null) {
    const r = window.QUIPU_LEDGER.realised(received, t.net_cost, a?.risk ?? null);
    t.realised = r.pl;
    t.realised_pct = r.pct;
  } else {
    // Nothing to work from: keep the last live mark rather than
    // inventing a result, and say nothing more confident than that.
    t.realised = a?.pl ?? null;
    t.realised_pct = a?.pl_pct ?? null;
  }
  saveBook(tab.ui.book);
}

/** Write the working position into the book, new or existing. */
function commitTrade(tab, id = null) {
  const u = tab.ui;
  const legs = sizedLegs(u);
  if (!u.symbol || !legs.length) return null;

  const at = id ? u.book.findIndex((t) => t.id === id) : -1;
  if (at >= 0) {
    u.book[at] = { ...u.book[at], symbol: u.symbol, legs };
    saveBook(u.book);
    return u.book[at].id;
  }
  // Where it started. Without the share price and the volatility at
  // the moment of opening, "why is this down" can only ever be
  // answered with "the stock moved", which for an option position is
  // frequently not the main reason and sometimes not a reason at all.
  const openedAt = tab.data || {};
  const trade = {
    id: "t" + Date.now() + Math.random().toString(36).slice(2, 6),
    symbol: u.symbol, legs,
    opened_spot: at.spot ?? null,
    opened_vol: at.vol_used ?? null,
    opened: new Date().toISOString().slice(0, 10),
    opened_at: stamp(),
    closed: null,
    closed_at: null,
  };
  u.book.unshift(trade);
  saveBook(u.book);
  return trade.id;
}

/* The log as its own room, and the two places every row can go.
 *
 * A trade in the log is a fact about two different things -- a
 * structure you built, and a company. Both are worth opening and they
 * are not the same destination, so the row offers both rather than
 * picking one and making the other a detour through search.
 */

function renderLogTab(tab) {
  return `<div class="livebar">
      <span class="lbsym">Trade log</span>
      <span class="grow"></span>
      ${roomNav("log")}
    </div>` + renderBook(tab);
}

function wireLog(tab) {
  const u = tab.ui;
  wireRooms();

  const nu = document.getElementById("book-new");
  if (nu) nu.onclick = () => openRoom("position");

  // Open the structure. A new tab, because the log is a place you come
  // back to -- replacing it with the trade you just opened is what made
  // moving between the two feel like going somewhere and losing it.
  document.querySelectorAll("[data-open]").forEach((b) => {
    b.onclick = () => openTrade(u.book.find((x) => x.id === b.dataset.open));
  });

  // Open the company.
  document.querySelectorAll("[data-stock]").forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); newTab(b.dataset.stock); };
  });

  wireBookRows(tab);
}

/* A held trade, opened into a workshop tab of its own. */
function openTrade(t) {
  if (!t) return null;
  const tab = newPositionTab();
  const u = tab.ui;
  u.editing = t.id;
  u.symbol = t.symbol;
  u.legs = t.legs.map((l) => ({ ...l }));
  // These quantities are already the real ones. A multiplier left over
  // from the last thing built would reopen the trade at that size.
  u.size = 1;
  u.view = "work";
  u.route = "custom";
  u.chain = null;
  u.preset = null;
  render();
  loadChain(tab);
  analysePosition(tab);
  return tab;
}

/* Closing, reopening and settling, which the log and the workshop both
 * do and which used to be written out once inside the workshop's wiring
 * where only the workshop could reach it. */
function wireBookRows(tab) {
  const u = tab.ui;

  document.querySelectorAll("[data-closing]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      u.closing = b.dataset.closing;
      render(true);
      document.getElementById("close-val")?.focus();
    };
  });

  // Repainted in place rather than through render(), which would
  // rebuild the input and take the cursor out of it mid-number.
  const val = document.getElementById("close-val");
  const sumHost = document.getElementById("close-sum");
  if (val && sumHost) {
    const t = u.book.find((x) => x.id === u.closing);
    const paying = document.querySelector(".closeform")?.dataset.paying === "1";
    val.oninput = () => {
      sumHost.innerHTML = closingSum(t, u.marks?.[u.closing], val.value, paying);
    };
  }

  const cancelClose = document.querySelector("[data-cancelclose]");
  if (cancelClose) {
    cancelClose.onclick = (e) => { e.stopPropagation(); u.closing = null; render(true); };
  }

  document.querySelectorAll("[data-confirm]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const raw = document.getElementById("close-val")?.value;
      const paying = document.querySelector(".closeform")?.dataset.paying === "1";
      let got = raw == null || String(raw).trim() === "" ? null
        : Number(String(raw).replace(/[^0-9.-]/g, ""));
      // Asked as a positive cost, stored as a negative value: money out
      // is a negative amount received.
      if (got != null && Number.isFinite(got) && paying) got = -Math.abs(got);
      settleTrade(tab, b.dataset.confirm, Number.isFinite(got) ? got : null);
      u.closing = null;
      render(true);
    };
  });

  const reset = document.querySelector("[data-reset]");
  if (reset) reset.onclick = (e) => {
    e.stopPropagation();
    // From now. Anything closed after this counts; everything before
    // it stays in the log and stops being added up.
    u.bankedFrom = new Date().toISOString();
    saveBankedFrom(u.bankedFrom);
    render(true);
  };

  const unreset = document.querySelector("[data-unreset]");
  if (unreset) unreset.onclick = (e) => {
    e.stopPropagation();
    u.bankedFrom = null;
    saveBankedFrom(null);
    render(true);
  };

  document.querySelectorAll("[data-reopen]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const t = u.book.find((x) => x.id === b.dataset.reopen);
      if (!t) return;
      // Closing one by mistake should not be a dead end.
      t.closed = null;
      t.exit_value = null;
      t.realised = null;
      t.realised_pct = null;
      saveBook(u.book);
      render(true);
      markBook(tab);
    };
  });
}
