/* Fill: every square in the app is full, each with its own size.
 *
 * The curriculum's squares fill themselves by ranked blocks (course.js).
 * Every other square -- the search page's tiles, the World page's market
 * cells, the Workshop's ready-made setups -- was written in pixel sizes
 * long before this, with no notion of which part matters most, so it is
 * filled the one way that works on any content: the whole of it is scaled,
 * with CSS zoom, until it meets the square's edges. Zoom rather than
 * transform because zoom lays the content out again at the new size --
 * text rewraps to the square's width -- so "fill" means fill, not stretch.
 *
 * The room a square has is measured BEFORE anything is scaled, so a card
 * in a grid row is filled to the height the row already has and cannot
 * push the row taller. Grown only as far as it fits, and shrunk at most to
 * 0.82 to bring a slightly-too-full square inside; a list far longer than
 * its square (the news, the filings) is full already, and scrolls. Squares
 * that draw a live chart are left alone -- the chart sizes itself to the
 * square, and a zoomed canvas blurs.
 *
 * Batched: each guess is written to every square and then all of them are
 * measured, so the page is laid out once per round rather than once per
 * square per guess.
 */
(function () {

const MIN = 0.82, MAX = 2.4;

/* Where each kind of square keeps its contents, and what it is. */
const KINDS = [
  { sel: ".grid:not(.steps) > .tile", inner: (el) => el.querySelector(":scope > .body") },
  { sel: ".wxgrid > .wxcell", inner: (el) => el },
  { sel: ".pregrid > .pcard", inner: (el) => el },
];

/* The square's contents, in one wrapper the zoom can go on. Made at fit
 * time rather than where the square is drawn, so nothing that draws one
 * has to change. */
function wrap(box) {
  const first = box.firstElementChild;
  if (box.children.length === 1 && first.classList.contains("fill")) return first;
  const w = document.createElement("div");
  w.className = "fill";
  while (box.firstChild) w.appendChild(box.firstChild);
  box.appendChild(w);
  return w;
}

const skip = (el) => !!el.querySelector("canvas, .qchart-host, .ct-face");

function room(box) {
  const cs = getComputedStyle(box);
  return {
    h: box.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom),
    w: box.clientWidth,
  };
}

function fitBoxes(list) {
  const S = list.filter(({ el }) => !skip(el)).map(({ el, box }) => {
    if (!box || !box.firstChild) return null;
    const w = wrap(box);
    w.style.zoom = "1";
    return { box, w, lo: MIN, hi: MAX };
  }).filter(Boolean);
  // Measured once, at natural size, before anything moves.
  S.forEach((x) => { x.room = room(x.box); });
  const set = (x, z) => { x.w.style.zoom = String(z); };
  // Height against the room measured at the start; width against the box
  // as it is now -- a scrollbar that goes away when the content fits hands
  // its width back, and a cached width would call that an overflow.
  const fits = (x) => x.w.getBoundingClientRect().height <= x.room.h + 1
    && x.box.scrollWidth <= x.box.clientWidth + 1;

  // Too full at natural size: a small shrink may bring it inside;
  // otherwise it stays as written, and scrolls.
  const over = S.filter((x) => !fits(x));
  over.forEach((x) => set(x, MIN));
  over.forEach((x) => { if (fits(x)) x.hi = 1; else x.keep = true; });
  over.forEach((x) => { if (x.keep) set(x, 1); });

  const grow = S.filter((x) => !x.keep);
  for (let round = 0; round < 7; round++) {
    grow.forEach((x) => set(x, (x.lo + x.hi) / 2));
    grow.forEach((x) => { const m = (x.lo + x.hi) / 2; if (fits(x)) x.lo = m; else x.hi = m; });
  }
  grow.forEach((x) => set(x, x.lo.toFixed(3)));
}

const gather = (root = document) => KINDS.flatMap((k) =>
  [...root.querySelectorAll(k.sel)].map((el) => ({ el, box: k.inner(el) })));

/* Every square on screen that is not one of the curriculum's. */
function all() { fitBoxes(gather()); }

function one(el) {
  if (!el) return;
  const k = KINDS.find((k) => el.matches(k.sel));
  if (k) fitBoxes([{ el, box: k.inner(el) }]);
}

// The squares change size with the window; fill them again when it settles.
let settle = null;
window.addEventListener("resize", () => { clearTimeout(settle); settle = setTimeout(all, 180); });

window.QUIPU_FILL = { all, tiles: all, one };
}());
