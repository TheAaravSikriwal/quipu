/* The payoff, drawn as a payoff.
 *
 * It used to borrow the price-series chart: the curve was handed over
 * as {date: "342.50", close: -199}, so share prices were pretending to
 * be dates and profit was pretending to be a closing price. It drew a
 * line, which is most of a payoff diagram, and it could not draw any
 * of the rest -- where the strikes are, which side of zero you are on,
 * where the most you can make and lose actually happen.
 *
 * Those are the whole diagram. "I am down on an iron condor and I do
 * not know why" is answered by seeing that the price has walked out of
 * the flat top and onto a slope, and no line on its own says that.
 *
 * So: profit against finishing price, with zero drawn as the line it
 * is, the winning region tinted apart from the losing one, every
 * strike marked with the leg that put it there, both extremes labelled
 * where they occur, and today's price shown against all of it.
 *
 * Plain SVG and no dependency. The arithmetic is separated from the
 * drawing so it can be checked without a browser.
 */

/* Wrapped, because these are classic scripts sharing one global
 * scope. This file declares PAD and esc, and so do chart.js and
 * app.js -- a duplicate top-level const is a SyntaxError at parse
 * time and the whole page renders blank with one line in a console
 * nobody has open. Only the three things worth calling from
 * outside come back out. */
(function () {


  const PAD = { top: 18, right: 64, bottom: 30, left: 58 };

  /** Where the numbers sit in the box. */
  function scales(curve, w, h) {
    const xs = curve.map((p) => p.s);
    const ys = curve.map((p) => p.pl);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);

    // Zero has to be ON the chart even when the position never loses --
    // a payoff drawn without its zero line is a shape with no meaning.
    let y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
    if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1; }
    const room = (y1 - y0) * 0.08;
    y0 -= room; y1 += room;

    const iw = Math.max(1, w - PAD.left - PAD.right);
    const ih = Math.max(1, h - PAD.top - PAD.bottom);
    return {
      x0, x1, y0, y1,
      x: (v) => PAD.left + ((v - x0) / (x1 - x0 || 1)) * iw,
      y: (v) => PAD.top + ih - ((v - y0) / (y1 - y0 || 1)) * ih,
      iw, ih,
    };
  }

  /** Where the curve crosses zero, so the tints can stop in the right place. */
  function zeroCrossings(curve) {
    const out = [];
    for (let i = 1; i < curve.length; i++) {
      const a = curve[i - 1], b = curve[i];
      if ((a.pl < 0) === (b.pl < 0)) continue;
      const t = Math.abs(a.pl) / (Math.abs(a.pl) + Math.abs(b.pl) || 1);
      out.push(a.s + (b.s - a.s) * t);
    }
    return out;
  }

  /** The legs that put a strike on the board, grouped by strike. */
  function strikeMarks(legs) {
    const by = new Map();
    (legs || []).forEach((l) => {
      if (l.kind === "stock" || l.strike == null) return;
      const k = Number(l.strike);
      const at = by.get(k) || { strike: k, legs: [] };
      at.legs.push(l);
      by.set(k, at);
    });
    return [...by.values()].sort((a, b) => a.strike - b.strike);
  }

  const esc = (t) => String(t == null ? "" : t).replace(
    /[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                          '"': "&quot;", "'": "&#39;" }[c]));

  const usd = (v, dp = 0) => (v == null ? "--"
    : (v < 0 ? "−" : "") + "$" + Math.abs(v).toLocaleString("en-US",
        { minimumFractionDigits: dp, maximumFractionDigits: dp }));

  const strikeText = (v) => "$" + (Number(v) % 1 === 0
    ? Number(v).toLocaleString("en-US")
    : Number(v).toFixed(2).replace(/0$/, ""));

  /**
   * @param {object} o
   *   curve       [{s, pl}]  profit against finishing price
   *   legs        [{kind, side, strike, qty}]
   *   spot        number     where it trades now
   *   breakevens  number[]
   *   maxProfit / maxLoss           the figures, already computed
   *   bestAt / worstAt              [{lo, hi, to_zero, to_inf}]
   *   unboundedUp / unboundedDown   booleans
   *   valuedAt    string     the date the curve is drawn for, if not expiry
   */
    /* The stretch of price worth drawing.
   *
   * The engine computes the payoff from roughly forty percent of spot
   * to nearly twice it, which is right for finding the extremes and
   * hopeless for looking at. An iron condor does all of its work in a
   * twelve-dollar window on a three-hundred-dollar share, and drawn
   * across five hundred dollars it is a spike with two flat lines
   * either side -- the exact shape of "I cannot tell what this is
   * doing".
   *
   * So the window is the part with anything in it: every strike, both
   * break-evens, today's price, and a margin either side so the flat
   * parts are visibly flat rather than cropped at the corner.
   */
  function focus(curve, legs, spot, breakevens) {
    const marks = [];
    (legs || []).forEach((l) => {
      if (l.kind !== "stock" && l.strike != null) marks.push(Number(l.strike));
    });
    (breakevens || []).forEach((b) => marks.push(Number(b)));
    if (Number.isFinite(spot)) marks.push(Number(spot));
    const usable = marks.filter(Number.isFinite);
    if (!usable.length) return curve;

    let lo = Math.min(...usable), hi = Math.max(...usable);
    // A single-strike position has no width of its own, so it borrows
    // one: enough either side to show the payoff turn.
    const span = Math.max(hi - lo, (spot || hi) * 0.12);
    lo -= span * 0.55;
    hi += span * 0.55;

    const inside = curve.filter((p) => p.s >= lo && p.s <= hi);
    return inside.length >= 4 ? inside : curve;
  }

  function payoffSvg(o) {
    const whole = (o.curve || []).filter(
      (p) => Number.isFinite(p.s) && Number.isFinite(p.pl));
    const curve = focus(whole, o.legs, o.spot, o.breakevens);
    const w = o.width || 860, h = o.height || 300;
    if (curve.length < 2) {
      return `<div class="pfempty">nothing to draw yet</div>`;
    }

    const s = scales(curve, w, h);
    const zeroY = s.y(0);
    const pt = (p) => `${s.x(p.s).toFixed(2)},${s.y(p.pl).toFixed(2)}`;

    // The winning and losing parts of the curve, filled down to zero.
    // Split at the crossings so a region never bleeds across the line.
    const cuts = zeroCrossings(curve);
    const bands = [];
    let from = s.x0;
    [...cuts, s.x1].forEach((to) => {
      const inside = curve.filter((p) => p.s >= from && p.s <= to);
      if (inside.length >= 2) {
        const mid = inside[Math.floor(inside.length / 2)].pl;
        bands.push({
          win: mid >= 0,
          d: `M ${s.x(from).toFixed(2)},${zeroY.toFixed(2)} `
             + inside.map((p) => `L ${pt(p)}`).join(" ")
             + ` L ${s.x(to).toFixed(2)},${zeroY.toFixed(2)} Z`,
        });
      }
      from = to;
    });

    // Vertical grid at each strike, labelled with the legs that put it
    // there -- which is the question "what part of the graph is the put".
    const marks = strikeMarks(o.legs).map((m) => {
      const x = s.x(m.strike);
      if (x < PAD.left - 1 || x > w - PAD.right + 1) return "";
      const label = m.legs.map((l) =>
        `${l.side === "long" ? "+" : "−"}${l.qty} ${l.kind}`).join("  ");
      return `<g class="pfstrike">
        <line x1="${x.toFixed(1)}" y1="${PAD.top}" x2="${x.toFixed(1)}"
              y2="${(h - PAD.bottom).toFixed(1)}"/>
        <text x="${x.toFixed(1)}" y="${(h - PAD.bottom + 12).toFixed(1)}"
              text-anchor="middle">${esc(strikeText(m.strike))}</text>
        <text x="${x.toFixed(1)}" y="${(h - PAD.bottom + 22).toFixed(1)}"
              text-anchor="middle" class="pfleg">${esc(label)}</text>
      </g>`;
    }).join("");

    // Both extremes, marked where they actually happen.
    const extreme = (regions, value, unbounded, kind) => {
      if (unbounded) {
        const atEdge = kind === "best" ? s.x1 : s.x0;
        return `<g class="pfext ${kind}">
          <text x="${(s.x(atEdge) + (kind === "best" ? -6 : 6)).toFixed(1)}"
                y="${(kind === "best" ? PAD.top + 12 : h - PAD.bottom - 6).toFixed(1)}"
                text-anchor="${kind === "best" ? "end" : "start"}"
          >${kind === "best" ? "no cap" : "no limit"}</text></g>`;
      }
      const r = (regions || [])[0];
      if (!r || value == null) return "";
      // A flat region has no single point, so mark where it begins --
      // the corner the payoff turns at, not the middle of a plateau.
      const at = r.to_inf ? r.lo : r.to_zero ? r.hi : (r.lo + r.hi) / 2;
      const x = Math.min(Math.max(s.x(at), PAD.left), w - PAD.right);
      const y = s.y(value);
      const right = x < w / 2;
      return `<g class="pfext ${kind}">
        <line x1="${PAD.left}" y1="${y.toFixed(1)}" x2="${(w - PAD.right).toFixed(1)}"
              y2="${y.toFixed(1)}"/>
        <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5"/>
        <text x="${(x + (right ? 9 : -9)).toFixed(1)}" y="${(y - 7).toFixed(1)}"
              text-anchor="${right ? "start" : "end"}"
        >${kind === "best" ? "most it can make" : "most it can lose"} ${usd(value)}</text>
      </g>`;
    };

    const bes = (o.breakevens || []).map((b) => {
      const x = s.x(b);
      if (x < PAD.left || x > w - PAD.right) return "";
      return `<g class="pfbe">
        <line x1="${x.toFixed(1)}" y1="${(zeroY - 7).toFixed(1)}"
              x2="${x.toFixed(1)}" y2="${(zeroY + 7).toFixed(1)}"/>
        <text x="${x.toFixed(1)}" y="${(zeroY - 11).toFixed(1)}"
              text-anchor="middle">${esc(strikeText(b))}</text>
      </g>`;
    }).join("");

    const spotX = o.spot == null ? null : s.x(o.spot);
    const spotLine = (spotX == null || spotX < PAD.left || spotX > w - PAD.right)
      ? "" : `<g class="pfspot">
          <line x1="${spotX.toFixed(1)}" y1="${PAD.top}"
                x2="${spotX.toFixed(1)}" y2="${(h - PAD.bottom).toFixed(1)}"/>
          <text x="${spotX.toFixed(1)}" y="${(PAD.top - 6).toFixed(1)}"
                text-anchor="middle">now ${esc(strikeText(o.spot))}</text>
        </g>`;

    // The profit axis, in money, with zero always on it.
    const ticks = [s.y1, (s.y1 + s.y0) / 2, s.y0]
      .concat([0])
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((v) => `<g class="pfytick${Math.abs(v) < 1e-9 ? " zero" : ""}">
        <text x="${PAD.left - 8}" y="${(s.y(v) + 3.5).toFixed(1)}"
              text-anchor="end">${usd(v)}</text></g>`).join("");

    return `<svg class="pfsvg" viewBox="0 0 ${w} ${h}"
        preserveAspectRatio="none" role="img"
        aria-label="Profit against the price it finishes at">
      ${bands.map((b) => `<path class="pfband ${b.win ? "win" : "lose"}" d="${b.d}"/>`).join("")}
      <line class="pfzero" x1="${PAD.left}" y1="${zeroY.toFixed(1)}"
            x2="${(w - PAD.right).toFixed(1)}" y2="${zeroY.toFixed(1)}"/>
      ${marks}
      ${extreme(o.bestAt, o.maxProfit, o.unboundedUp, "best")}
      ${extreme(o.worstAt, o.maxLoss, o.unboundedDown, "worst")}
      <polyline class="pfline" points="${curve.map(pt).join(" ")}"/>
      ${bes}
      ${spotLine}
      ${ticks}
    </svg>`;
  }

    if (typeof window !== "undefined") {
    window.QUIPU_PAYOFF = { payoffSvg, scales, zeroCrossings, strikeMarks };
  }
    if (typeof module !== "undefined") {
    module.exports = { payoffSvg, scales, zeroCrossings, strikeMarks };
  }
}());
