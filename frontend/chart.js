/* Charts.
 *
 * Built rather than imported. A charting library would drop one generic house
 * style into a page where every panel is deliberately a different publication,
 * and would bring a few hundred kilobytes to draw a line. This is the part of
 * a professional chart that actually matters: real axes, gridlines you can
 * read a value off, a crosshair that names the number under the cursor, and
 * zoom that lets you interrogate a range instead of squinting at it.
 *
 * Direction is carried by the candle body, not by colour: HOLLOW closed up,
 * FILLED closed down. That is the original Japanese convention, it survives a
 * monochrome page, and it agrees with the triangles used everywhere else.
 *
 * Interaction
 *   move            crosshair, OHLC readout, price pinned to the axis
 *   drag            select a range to zoom into
 *   shift + drag    pan
 *   wheel           zoom about the cursor
 *   double-click    back to the full range
 */

const PAD = { left: 8, right: 56, top: 10, bottom: 20 };

/* Read the palette from CSS rather than repeating hex values here. The chart
 * colours drifted from the design system last time they were hard-coded. */
const ink = (name, fallback) => {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
};

/* Round the raw step to the *nearest* number on the 1-2-5-10 ladder, not the
 * next one up. Rounding up turned a wanted step of 20 into 50, which left a
 * $160-$241 axis with a single label on it. */
function niceTicks(lo, hi, count = 4) {
  const span = hi - lo;
  if (!(span > 0) || !Number.isFinite(span)) return [];
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const mult = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
  const step = mult * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

const fmtPrice = (v) =>
  // `v + 0` collapses JavaScript's negative zero, which Math.ceil happily
  // produces and toLocaleString then renders as "-0".
  "$" + (v + 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtVol = (v) =>
  v >= 1e9 ? (v / 1e9).toFixed(1) + "B"
    : v >= 1e6 ? (v / 1e6).toFixed(1) + "M"
    : v >= 1e3 ? (v / 1e3).toFixed(0) + "K" : String(v);

/* Every point becomes OHLCV internally, so one draw path serves both the
 * candle chart and the dozen little line panels that only ever had closes. */
function normalise(points, opts) {
  const first = points[0] || {};
  if (first.c !== undefined && first.o !== undefined) return points;
  const xKey = opts.xKey || "date", yKey = opts.yKey || "close", volKey = opts.volKey;
  return points.map((p) => {
    const c = Number(p[yKey]);
    return { t: p[xKey], o: c, h: c, l: c, c, v: volKey ? (p[volKey] || 0) : 0 };
  });
}

/** Simple moving average over closes, stamped at the end of each window. */
function sma(points, period) {
  const out = new Array(points.length).fill(null);
  if (points.length < period) return out;
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    sum += points[i].c;
    if (i >= period) sum -= points[i - period].c;
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/* ResizeObserver and scroll events never fire in this shell -- verified by
 * instrumenting both -- so one shared poll watches every mounted chart for a
 * size change. One timer for the page beats one observer per panel. */
const MOUNTED = new Set();
setInterval(() => { MOUNTED.forEach((c) => c._checkSize()); }, 400);

/**
 * @param host  element to draw into
 * @param opts  { points, xKey, yKey, volKey, reference, range, onRange,
 *                candles, logScale, mas, onState }
 */
function makeChart(host, opts) {
  let all = normalise(opts.points || [], opts);
  if (all.length < 2) {
    host.innerHTML = `<div class="dim" style="padding:8px">not enough data to chart</div>`;
    return null;
  }

  /* Candles need four distinct prices. A series carrying only closes gets a
   * line whatever the caller asked for, because flat-bodied candles would be
   * a row of dashes pretending to be information. */
  const hasOHLC = all.some((p) => p.h > p.l);
  let candles = hasOHLC && opts.candles !== false;
  let logScale = !!opts.logScale;
  let mas = Object.assign({ 20: false, 50: false, 200: false }, opts.mas || {});

  let range = opts.range && opts.range[1] > opts.range[0]
    ? [Math.max(0, opts.range[0]), Math.min(all.length - 1, opts.range[1])]
    : [0, all.length - 1];

  let W = host.clientWidth || 320;
  let H = host.clientHeight || 120;

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("class", "qchart");
  host.innerHTML = "";
  host.appendChild(svg);

  const readout = document.createElement("div");
  readout.className = "qchart-readout";
  readout.style.display = "none";
  host.appendChild(readout);

  const el = (tag, attrs = {}) => {
    const n = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };

  let plot = {};                        // geometry of the current draw

  function draw() {
    W = host.clientWidth || W;
    H = host.clientHeight || H;
    /* viewBox only -- deliberately no width/height attributes. With them set,
     * the SVG has an intrinsic size, that size becomes the flex basis of the
     * host, and the host then grows to whatever the last draw measured. The
     * chart ratchets taller every redraw and overflows its tile. Sized purely
     * by CSS, the host takes the space the tile has left and the viewBox
     * follows it. */
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = "";

    const [i0, i1] = range;
    const slice = all.slice(i0, i1 + 1);
    if (slice.length < 2) return;

    // Past a few hundred bars a candle is thinner than its own outline, so
    // the chart falls back to the line it would otherwise be imitating.
    const showCandles = candles && slice.length <= 400;
    const hasVol = slice.some((p) => p.v);
    const volH = hasVol ? Math.max(14, (H - PAD.top - PAD.bottom) * 0.2) : 0;

    const x0 = PAD.left, x1 = W - PAD.right;
    const y0 = PAD.top, y1 = H - PAD.bottom - volH;
    const pw = Math.max(x1 - x0, 1), ph = Math.max(y1 - y0, 1);

    // Candles are drawn to the wick, so the axis has to hold the wick.
    let lo = Math.min(...slice.map((p) => (showCandles ? p.l : p.c)));
    let hi = Math.max(...slice.map((p) => (showCandles ? p.h : p.c)));
    if (opts.reference != null && opts.reference > 0) {
      lo = Math.min(lo, opts.reference);
      hi = Math.max(hi, opts.reference);
    }
    // Headroom above and below, but never below zero -- a share price cannot
    // go there, and padding into it wastes a fifth of the plot.
    const padY = (hi - lo || 1) * 0.07;
    lo = Math.max(logScale ? Math.max(lo * 0.5, 0.01) : 0, lo - padY);
    hi += padY;

    const lg = (v) => Math.log(Math.max(v, 1e-9));
    const span = logScale ? (lg(hi) - lg(lo)) : (hi - lo);
    const Y = logScale
      ? (v) => y1 - ((lg(v) - lg(lo)) / (span || 1)) * ph
      : (v) => y1 - ((v - lo) / (span || 1)) * ph;
    const Yinv = logScale
      ? (y) => Math.exp(lg(lo) + ((y1 - y) / ph) * (span || 1))
      : (y) => lo + ((y1 - y) / ph) * (span || 1);

    // Candles sit in slots; a line runs edge to edge. Slot centres for both,
    // so the crosshair lands on the same bar in either mode.
    const X = (i) => x0 + ((i + 0.5) / slice.length) * pw;
    const bw = Math.max((pw / slice.length) * 0.68, 1);

    const stroke = ink("--text", "#F2F2F0");
    const dim = ink("--text2", "#A3A3A0");

    // gridlines and price axis, labelled on the RIGHT so the newest bars --
    // the ones you came to look at -- are never sitting under the numbers.
    for (const t of niceTicks(lo, hi, 4)) {
      if (logScale && t <= 0) continue;
      const y = Y(t);
      if (y < y0 - 1 || y > y1 + 1) continue;
      svg.appendChild(el("line", {
        x1: x0, y1: y, x2: x1, y2: y, stroke: ink("--rule", "#262629"), "stroke-width": 1,
        "shape-rendering": "crispEdges",
      }));
      const lab = el("text", { x: x1 + 5, y: y + 3.2, class: "qc-axis" });
      lab.textContent = fmtPrice(t).replace(".00", "");
      svg.appendChild(lab);
    }

    // previous close, where we have one
    if (opts.reference != null && opts.reference > 0) {
      const y = Y(opts.reference);
      svg.appendChild(el("line", {
        x1: x0, y1: y, x2: x1, y2: y, stroke: ink("--faint", "#6E6E6C"),
        "stroke-width": 1, "stroke-dasharray": "4 3",
      }));
    }

    // volume, underneath
    if (hasVol) {
      const vmax = Math.max(...slice.map((p) => p.v || 0)) || 1;
      slice.forEach((p, i) => {
        const h = ((p.v || 0) / vmax) * (volH - 4);
        svg.appendChild(el("rect", {
          x: X(i) - bw / 2, y: H - PAD.bottom - h,
          width: Math.max(bw, 0.6), height: h,
          fill: p.c >= p.o ? ink("--rule2", "#3A3A3E") : dim,
        }));
      });
    }

    if (showCandles) {
      const panel = ink("--panel", "#121214");
      slice.forEach((p, i) => {
        const x = X(i);
        svg.appendChild(el("line", {
          x1: x, y1: Y(p.h), x2: x, y2: Y(p.l), stroke: stroke, "stroke-width": 1,
        }));
        const top = Y(Math.max(p.o, p.c));
        const bot = Y(Math.min(p.o, p.c));
        svg.appendChild(el("rect", {
          x: x - bw / 2, y: top, width: bw, height: Math.max(bot - top, 1),
          fill: p.c >= p.o ? panel : stroke, stroke: stroke, "stroke-width": 1,
        }));
      });
    } else {
      // The line does not encode direction -- its shape already does that, and
      // colour here would be a second channel saying the same thing.
      const pts = slice.map((p, i) => `${X(i).toFixed(2)},${Y(p.c).toFixed(2)}`).join(" ");
      svg.appendChild(el("polygon", {
        points: `${X(0).toFixed(2)},${y1} ${pts} ${X(slice.length - 1).toFixed(2)},${y1}`,
        fill: stroke, opacity: 0.07,
      }));
      svg.appendChild(el("polyline", {
        points: pts, fill: "none", stroke: stroke, "stroke-width": 1.7,
        "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke",
      }));
    }

    // Moving averages, dashed at three weights so they read as annotation
    // rather than as a second price series.
    const dashes = { 20: "2 2", 50: "5 3", 200: "9 4" };
    for (const period of [20, 50, 200]) {
      if (!mas[period]) continue;
      const series = sma(all, period);
      const pts = [];
      for (let i = i0; i <= i1; i++) {
        if (series[i] == null) continue;
        pts.push(`${X(i - i0).toFixed(2)},${Y(series[i]).toFixed(2)}`);
      }
      if (pts.length > 1) {
        svg.appendChild(el("polyline", {
          points: pts.join(" "), fill: "none", stroke: dim,
          "stroke-width": 1.2, "stroke-dasharray": dashes[period],
        }));
      }
    }

    // date axis: first, middle, last
    [0, Math.floor((slice.length - 1) / 2), slice.length - 1].forEach((i, n) => {
      const t = el("text", {
        x: X(i), y: H - 6, class: "qc-axis",
        "text-anchor": n === 0 ? "start" : n === 2 ? "end" : "middle",
      });
      t.textContent = String(slice[i].t ?? "");
      svg.appendChild(t);
    });

    // interaction layer
    const cross = el("g", { class: "qc-cross", visibility: "hidden" });
    const vline = el("line", { y1: y0, y2: y1 + volH, stroke: stroke, "stroke-width": 1, "stroke-dasharray": "3 2", opacity: .85 });
    const hline = el("line", { x1: x0, x2: x1, stroke: stroke, "stroke-width": 1, "stroke-dasharray": "3 2", opacity: .85 });
    const dot = el("circle", { r: 3, fill: stroke, stroke: ink("--black", "#0A0A0B"), "stroke-width": 1.6 });
    const tagBg = el("rect", { x: x1 + 1, width: PAD.right - 2, height: 14, fill: stroke });
    const tag = el("text", { x: x1 + 5, class: "qc-tag" });
    cross.appendChild(vline); cross.appendChild(hline); cross.appendChild(dot);
    cross.appendChild(tagBg); cross.appendChild(tag);
    svg.appendChild(cross);

    const band = el("rect", { y: y0, height: ph + volH, fill: stroke, opacity: 0.14, visibility: "hidden" });
    svg.appendChild(band);

    const hit = el("rect", { x: x0, y: y0, width: pw, height: ph + volH, fill: "transparent", cursor: "crosshair" });
    svg.appendChild(hit);

    plot = { slice, X, Y, Yinv, x0, x1, y0, y1, pw, ph, volH, i0, hasVol,
             showCandles, cross, vline, hline, dot, tag, tagBg, band, hit };
    wire();
    opts.onState?.(stateOf());
  }

  /* What the *visible window* says -- not the whole series. Zooming into
   * March should change the numbers in the header, otherwise the header is
   * describing a chart you are no longer looking at. */
  function stateOf() {
    const [i0, i1] = range;
    const slice = all.slice(i0, i1 + 1);
    if (slice.length < 2) return null;
    const last = slice[slice.length - 1];
    return {
      bars: slice.length,
      from: slice[0].t,
      to: last.t,
      high: Math.max(...slice.map((p) => p.h)),
      low: Math.min(...slice.map((p) => p.l)),
      last: last.c,
      changePct: slice[0].c ? ((last.c / slice[0].c) - 1) * 100 : null,
      avgVol: slice.reduce((a, p) => a + (p.v || 0), 0) / slice.length,
      zoomed: i0 !== 0 || i1 !== all.length - 1,
      candles: plot.showCandles ?? candles,
      logScale,
      mas: { ...mas },
    };
  }

  let dragFrom = null, panFrom = null;

  function indexAt(clientX) {
    const r = svg.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * W;
    const f = (px - plot.x0) / plot.pw;
    return Math.max(0, Math.min(plot.slice.length - 1, Math.round(f * plot.slice.length - 0.5)));
  }

  function wire() {
    const { hit, cross, vline, hline, dot, tag, tagBg, band } = plot;

    hit.addEventListener("pointermove", (e) => {
      const i = indexAt(e.clientX);
      const p = plot.slice[i];
      if (!p) return;
      const x = plot.X(i);
      const r = svg.getBoundingClientRect();
      const my = Math.max(plot.y0, Math.min(plot.y1, ((e.clientY - r.top) / r.height) * H));

      cross.setAttribute("visibility", "visible");
      vline.setAttribute("x1", x); vline.setAttribute("x2", x);
      hline.setAttribute("y1", my); hline.setAttribute("y2", my);
      dot.setAttribute("cx", x); dot.setAttribute("cy", plot.Y(p.c));
      tagBg.setAttribute("y", my - 7);
      tag.setAttribute("y", my + 3.4);
      tag.textContent = fmtPrice(plot.Yinv(my)).replace(".00", "");

      readout.style.display = "block";
      readout.innerHTML =
        `<b>${fmtPrice(p.c)}</b><span>${p.t ?? ""}</span>` +
        (plot.showCandles
          ? `<span>O ${p.o.toFixed(2)} H ${p.h.toFixed(2)} L ${p.l.toFixed(2)}</span>` : "") +
        (plot.hasVol && p.v ? `<span>vol ${fmtVol(p.v)}</span>` : "");
      const left = Math.min(Math.max(x - 40, 2), Math.max(W - 132, 2));
      readout.style.left = `${(left / W) * 100}%`;

      if (dragFrom !== null) {
        const a = Math.min(plot.X(dragFrom), x), b = Math.max(plot.X(dragFrom), x);
        band.setAttribute("visibility", "visible");
        band.setAttribute("x", a);
        band.setAttribute("width", Math.max(b - a, 1));
      } else if (panFrom !== null) {
        const shift = panFrom.i - i;
        if (shift !== 0) {
          const width = range[1] - range[0];
          const a = Math.max(0, Math.min(all.length - 1 - width, panFrom.r0 + shift));
          setRange([a, a + width]);
        }
      }
    });

    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden");
      readout.style.display = "none";
    });

    hit.addEventListener("pointerdown", (e) => {
      hit.setPointerCapture(e.pointerId);
      if (e.shiftKey) panFrom = { i: indexAt(e.clientX), r0: range[0] };
      else dragFrom = indexAt(e.clientX);
    });

    hit.addEventListener("pointerup", (e) => {
      const to = indexAt(e.clientX);
      plot.band.setAttribute("visibility", "hidden");
      if (dragFrom !== null && Math.abs(to - dragFrom) >= 2) {
        setRange([plot.i0 + Math.min(dragFrom, to), plot.i0 + Math.max(dragFrom, to)]);
      }
      dragFrom = null; panFrom = null;
    });

    hit.addEventListener("wheel", (e) => {
      e.preventDefault();
      const i = plot.i0 + indexAt(e.clientX);
      const [a, b] = range;
      const width = b - a;
      const next = Math.max(6, Math.round(width * (e.deltaY > 0 ? 1.25 : 0.8)));
      const frac = width ? (i - a) / width : 0.5;
      let na = Math.round(i - next * frac);
      let nb = na + next;
      if (na < 0) { na = 0; nb = Math.min(next, all.length - 1); }
      if (nb > all.length - 1) { nb = all.length - 1; na = Math.max(0, nb - next); }
      setRange([na, nb]);
    }, { passive: false });

    hit.addEventListener("dblclick", () => setRange([0, all.length - 1]));
  }

  function setRange(r) {
    range = r;
    opts.onRange?.(range);
    draw();
  }

  draw();

  let lastW = host.clientWidth, lastH = host.clientHeight;
  const api = {
    redraw: draw,
    /* Update the series in place. The live refresh appends new bars every
     * fifteen seconds; tearing the chart down and rebuilding it would blink
     * and throw away the zoom the user set. */
    setPoints: (points, keepRange = true) => {
      const next = normalise(points || [], opts);
      if (next.length < 2) return;
      const wasFullRange = range[0] === 0 && range[1] === all.length - 1;
      const grew = next.length - all.length;
      all = next;
      if (!keepRange || wasFullRange) {
        range = [0, all.length - 1];
      } else {
        range = [
          Math.max(0, Math.min(range[0] + Math.max(grew, 0), all.length - 2)),
          Math.min(range[1] + Math.max(grew, 0), all.length - 1),
        ];
      }
      draw();
    },
    reset: () => setRange([0, all.length - 1]),
    getRange: () => [...range],
    state: stateOf,
    setCandles: (v) => { candles = !!v && hasOHLC; draw(); },
    setLog: (v) => { logScale = !!v; draw(); },
    setMa: (period, on) => { mas[period] = !!on; draw(); },
    canCandle: () => hasOHLC,
    zoomed: () => range[0] !== 0 || range[1] !== all.length - 1,
    _checkSize: () => {
      const w = host.clientWidth, h = host.clientHeight;
      if (w && h && (w !== lastW || h !== lastH)) { lastW = w; lastH = h; draw(); }
    },
    destroy: () => { MOUNTED.delete(api); host.innerHTML = ""; },
  };
  MOUNTED.add(api);
  return api;
}

window.QUIPU_CHART = { makeChart };
