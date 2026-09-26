/* QUIPU -- what is on screen, and in what order.
 *
 * The switchboard. Every room's panels, by name, in the order they
 * appear. Delete a line and that panel is gone from the room; move a
 * line and it moves; move it into another group and the search rail
 * files it there. Nothing else decides what is shown.
 *
 * Each name is a panel registered by its room's file with panel(), so
 * a panel taken out of this list still exists and costs nothing -- it
 * is simply not drawn, and putting the line back brings it back. A
 * name that nothing registered draws as nothing and says so once in
 * the console, rather than taking the room down with it.
 *
 * To see what exists, including what is not currently shown, run
 * inventory() in the console.
 */
const LAYOUT = {
  /* The curriculum, "From Chart to Trade", run on this company: the
   * step-by-step guide at the top of a search. The answer first, then
   * each step, each consuming the one before it. */
  guide: [
    "verdict",          // direction, conviction, target, the trade, the thesis
    "step1",            // find: liquidity, IV environment, expected move, catalysts
    "step2",            // direction: nine weighted signals and the scorecard
    "news",             // headlines tagged bullish / bearish -- shown, not scored
    "step3",            // build: matrix, expiry, strikes, payoff, odds, greeks
    "step4",            // size: contracts, exposure, stops, target, time, thesis
  ],

  /* One company, everything else on it. The groups are the rail's regions, top to bottom,
   * and the packer keeps each group in one run down the page. */
  search: [
    { id: "price", label: "Price", panels: [
      "quote",          // the live price and the day's move
      "price",          // the price chart, today out to five years
      "returns",        // how it has done over each horizon
      "volume",         // the tape: how much trades, and when
    ] },
    { id: "options", label: "Options", panels: [
      "vol",            // implied against realised: is movement cheap
      "options",        // the chain in summary: expected move, skew
      "optionstory",    // the options, read in order
      "probability",    // chance of finishing past a price
      "unusual",        // volume far out of line with open interest
      "greeks",         // what one position would actually cost and do
      "chain",          // the full board, to pick a contract
    ] },
    { id: "business", label: "Business", panels: [
      "profile",        // what the company does
      "holdings",       // what is inside it, for a fund
      "secfin",         // the accounts, exactly as filed
      "secmargins",     // margins computed from those filings
      "financials",     // annual financials
      "valuation",      // what you pay for the earnings
      "earnings",       // whether it hits its numbers
      "analysts",       // what the street expects
      "ownership",      // who holds it
      "short",          // who is betting against it
      "filings",        // the latest filings, in plain English
    ] },
    { id: "news", label: "News", panels: [
      "calendar",       // what is already on the calendar
      "news",           // headlines, the price-moving ones lifted
      "unique",         // what only one outlet reported
      "corroborated",   // claims two or more outlets agree on
      "stories",        // articles grouped into events
      "social",         // retail chatter
      "pipeline",       // what this load did and how long it took
    ] },
  ],

  /* A priced position, whichever route built it. */
  position: [
    "head",             // the strategy's name and what it is
    "money",            // the big numbers: cost, max win, max loss
    "plain",            // the position in two sentences
    "now",              // profit now, break-even, chance, time left
    "payoff",           // the payoff diagram
    "figures",          // the greeks, as shares and dollars
    "legs",             // each leg, marked
    "guidance",         // what to do with it
    "commit",           // put it in the trade log
    "footnote",         // where the marks came from
  ],

  /* The trade log. */
  log: [
    "head",             // title, counts, + new trade
    "open",             // open trades, marked to the market
    "totals",           // still open / banked / all in
    "closed",           // closed trades, as settled
    "footnote",         // what the log keeps and where
  ],

  /* The market as a whole. */
  world: [
    "barometer",        // indices, VIX, Treasuries, gold, oil: where it is
    "headlines",        // what happened, ranked
    "calendar",         // what is coming
  ],
};

/* Lists above that are part of a room rather than a room of their own. */
const LAYOUT_PARTS = { guide: "search" };

/* The search page's two halves, top to bottom: the step-by-step guide,
 * then every panel the page had before it. Swap them to put the panels
 * first; drop one to show only the other. */
const SEARCH_ORDER = ["guide", "tiles"];
