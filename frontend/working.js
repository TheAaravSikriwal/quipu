/* The arithmetic behind a number, shown when you hover it.
 *
 * A figure sitting in the middle of a sentence cannot carry its own
 * derivation -- there is nowhere to put it without wrecking the
 * sentence. So the number is marked, and the sum appears over it when
 * the cursor lands, in the same place and the same shape as a glossary
 * definition. One habit to learn, not two.
 *
 * Only DERIVED numbers are marked. A share price is read off a quote
 * and has no working; marking it would say there is something to see
 * and then waste the reader's time proving there is not. The rule is
 * that a marked number is one this app computed, and hovering it shows
 * what from.
 *
 * The sums are built server-side wherever the server already has the
 * inputs -- there is one Black-Scholes in this codebase and it is in
 * Python. The small ones a panel works out for itself are built here,
 * in the same shape, so both render through one path.
 */

/* Wrapped, so the only thing this file puts in the page's one shared
 * scope is QUIPU_WORKING. Classic scripts all share it, and a helper
 * named `calc` here collided with one of the same name in app.js --
 * which does not fail quietly: the second declaration throws at parse
 * time and the whole page renders blank. */
(function () {

const WK = {
  /* Build a working from parts, in the shape backend/working.py emits.
   *   term(label, value, dp)          one named quantity
   *   line(op, ...terms, gives)       one row of the sum
   */
  term: (label, value, dp = 2, note = "") => ({ label, value, dp, note }),
  line: (op, terms, gives = null, dp = 2) => ({ op, terms, gives, dp }),
  sum: (result, lines, unit = "$", note = "", perShare = false) =>
    ({ result, lines, unit, note, per_share: perShare }),
};

/** A number, marked as having a derivation behind it. */
function calc(formatted, working) {
  if (!working) return formatted;
  const json = JSON.stringify(working).replace(/"/g, "&quot;");
  return `<span class="calc" data-calc="${json}">${formatted}</span>`;
}

function fmtVal(t) {
  const v = t.value;
  if (v === null || v === undefined) return "&ndash;";
  const dp = t.dp === undefined ? 2 : t.dp;
  return Number(v).toLocaleString("en-US",
    { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/** The sum, laid out so the columns line up and it reads as arithmetic. */
function renderWorking(w) {
  if (!w || !w.lines?.length) return "";
  const unit = w.unit === "%" ? "%" : "";
  const money = w.unit === "$" && !w.per_share;

  const rows = w.lines.map((ln) => {
    const terms = ln.terms.map((t) =>
      `<span class="wt"><i>${t.label}</i><b>${fmtVal(t)}</b></span>`
    ).join(`<span class="wop">&times;</span>`);
    const gives = ln.gives === null || ln.gives === undefined ? ""
      : `<span class="wgives">= ${Number(ln.gives).toLocaleString("en-US",
          { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
    const op = ln.op === "" ? "" : ln.op === "-" ? "&minus;"
      : ln.op === "x" ? "&times;" : ln.op === "/" ? "&divide;"
      : ln.op === "floor" ? "" : ln.op;
    return `<div class="wrow${ln.op === "floor" ? " wfloor" : ""}">
      <span class="wsign">${op}</span>
      <span class="wterms">${terms}</span>${gives}</div>`;
  }).join("");

  const total = Number(w.result).toLocaleString("en-US",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // A per-share figure is not the price of anything you can buy; the
  // contract is a hundred of them, and leaving that out is the single
  // easiest way to be wrong by two orders of magnitude.
  const hundred = w.per_share
    ? `<div class="wrow wx100"><span class="wsign">&times;</span>
        <span class="wterms"><span class="wt"><i>shares in one contract</i><b>100</b></span></span>
        <span class="wgives">= ${(w.result * 100).toLocaleString("en-US",
          { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span></div>` : "";

  const notes = w.lines.flatMap((ln) => ln.terms.filter((t) => t.note)
    .map((t) => `<div class="wnote"><b>${t.label}</b> ${t.note}</div>`)).join("");

  return `<div class="wcalc">
    ${rows}
    <div class="wrow wtotal"><span class="wsign">=</span>
      <span class="wterms">${money ? "$" : ""}${total}${unit}${
        w.per_share ? " a share" : ""}</span></div>
    ${hundred}
    ${notes}
    ${w.note ? `<div class="wfoot">${w.note}</div>` : ""}
  </div>`;
}

/* ---- the hover ------------------------------------------------------
 *
 * Deliberately the same element and the same placement rule as the
 * glossary tip, and deliberately without a transition on it: a running
 * animation overrides an element's own inline style for every property
 * it touches, and this one is positioned by inline transform. That bug
 * pinned the glossary to the corner of the screen once already.
 */
let wkTip = null;
let wkHide = null;

function wkEnsure() {
  if (wkTip && wkTip.isConnected) return wkTip;
  if (wkTip) wkTip.remove();
  document.querySelectorAll(".calctip").forEach((n) => n.remove());
  wkTip = document.createElement("div");
  wkTip.className = "calctip";
  wkTip.style.display = "none";
  document.body.appendChild(wkTip);
  wkTip.addEventListener("pointerenter", () => clearTimeout(wkHide));
  wkTip.addEventListener("pointerleave", wkClose);
  return wkTip;
}

function wkClose() {
  wkHide = setTimeout(() => { if (wkTip) wkTip.style.display = "none"; }, 120);
}

function wkShow(el) {
  let w;
  try { w = JSON.parse(el.dataset.calc); } catch { return; }
  if (!w) return;
  clearTimeout(wkHide);

  const t = wkEnsure();
  t.innerHTML = `<h6>how this is worked out</h6>${renderWorking(w)}`;
  t.style.display = "block";
  t.style.transform = "translate3d(0,0,0)";

  const r = el.getBoundingClientRect();
  const b = t.getBoundingClientRect();
  const margin = 10;
  let left = r.left + r.width / 2 - b.width / 2;
  left = Math.max(margin, Math.min(left, window.innerWidth - b.width - margin));
  let top = r.bottom + 8;
  if (top + b.height > window.innerHeight - margin) {
    top = Math.max(margin, r.top - b.height - 8);
  }
  t.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
}

// Delegated, so numbers rendered after this runs still work.
document.addEventListener("pointerover", (e) => {
  const el = e.target.closest?.(".calc");
  if (el) wkShow(el);
});
document.addEventListener("pointerout", (e) => {
  if (e.target.closest?.(".calc")) wkClose();
});

window.QUIPU_WORKING = { calc, renderWorking, WK };
}());
