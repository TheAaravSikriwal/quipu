/* The trade log's arithmetic, kept apart from the page that draws it.
 *
 * Three small functions, and every one of them is about money the user
 * is going to believe. They live here rather than inside app.js for one
 * reason: app.js cannot be loaded outside a browser, and arithmetic
 * that cannot be tested is arithmetic nobody has checked.
 */

/** What a closed trade actually made.
 *
 * The same shape as the live profit -- what came back less what went
 * out -- but computed once from a figure the user supplies and then
 * frozen. `netCost` is positive for a debit (you paid it) and negative
 * for a credit (you were paid), which is the convention the whole
 * position engine uses, so a credit trade closed for nothing correctly
 * realises the credit in full.
 */
function realised(received, netCost, risk) {
  if (received == null || netCost == null) return { pl: null, pct: null };
  const pl = received - netCost;
  // Against what was at risk, not against the cost. For a credit trade
  // the cost is negative, and a percentage of a negative number is a
  // sign error wearing a percent sign.
  const base = risk != null && risk > 0 ? risk : (netCost > 0 ? netCost : null);
  return { pl, pct: base ? (pl / base) * 100 : null };
}

/** The totals under the log.
 *
 * Open and closed are kept apart because they are different facts: one
 * moves every time the market does and the other never will again.
 *
 * Each figure is rounded to whole dollars BEFORE being added rather
 * than after. Summed first, -6.50 and +151.00 print as -7 and +151
 * above a total of +145 -- three numbers on one screen that do not add
 * up, which makes a reader distrust all three.
 */
function bookTotals(openPls, closedPls) {
  const whole = (v) => Math.round(v);
  const open = (openPls || []).filter((v) => v != null).map(whole);
  const shut = (closedPls || []).filter((v) => v != null).map(whole);
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);

  return {
    open: sum(open),
    banked: sum(shut),
    all: sum(open) + sum(shut),
    priced: open.length,
    closed: shut.length,
    wins: shut.filter((v) => v > 0).length,
  };
}

if (typeof window !== "undefined") window.QUIPU_LEDGER = { realised, bookTotals };
if (typeof module !== "undefined") module.exports = { realised, bookTotals };
