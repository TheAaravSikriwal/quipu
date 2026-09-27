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
  /* One company. The groups are the rail's regions, top to bottom,
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

  /* "From Chart to Trade", the curriculum, run on this company: every
   * number it produces is a square in its own grid below the page, in
   * the order the curriculum reads them -- which is also the order
   * "Create the path" numbers them. The groups are rail regions too. */
  steps: [
    { id: "find", label: "Find", panels: [
      "c-spread",       // 1.1 bid-ask spread at the strike you would trade
      "c-oi",           // 1.1 open interest there
      "c-vol_oi",       // 1.1 today's volume against it
      "c-iv_rank",      // 1.2 IV Rank (Alpaca history)
      "c-iv_pct",       // 1.2 IV Percentile
      "c-hv20",         // 1.2 what the stock has actually been doing
      "c-iv_hv",        // 1.2 implied against realised
      "c-em_model",     // 1.3 the expected move, from IV
      "c-em_market",    // 1.3 the expected move, from the straddle
      "c-daily_move",   // 0.5 a normal day, the rule of 16
      "c-earnings_date",// 1.3 the next report, and whether it is in the window
      "c-market_events",// 1.3 Fed, CPI, jobs before expiry
      "c-unusual",      // 1.4 unusual activity
      "c-pc_screen",    // 1.5 put/call, raw
    ] },
    { id: "direction", label: "Direction", panels: [
      "c-trend",        // 2.1 the moving averages
      "c-levels",       // 2.2 support, resistance, pivots, reward/risk
      "c-pattern",      // 2.3 RVOL and breakouts
      "c-catalyst",     // 2.4 earnings reactions against what is priced
      "c-fundamentals", // 2.5 estimate revisions, P/E against peers
      "c-rs",           // 2.6 RS line, RS Rating, beta, alpha
      "c-rsi",          // 2.7 RSI and divergence
      "c-pc",           // 2.8 put/call against its own normal
      "c-skew",         // 2.9 25-delta skew against its normal
      "c-news",         // headlines tagged bullish / bearish -- not scored
      "c-scorecard",    // 2.10 the weighted total, and the verdict
    ] },
    { id: "build", label: "Build", panels: [
      "c-matrix",       // 3.1 the strategy matrix
      "c-expiry",       // 3.3 the expiration
      "c-strikes",      // 3.4 the strikes
      "c-payoff",       // 3.2 what you pay, most you make and lose
      "c-odds",         // 3.5 probability of profit, touch, EV
      "c-greeks",       // 3.5 net delta, theta, vega
    ] },
    { id: "size", label: "Size", panels: [
      "c-size",         // 4.1 how many contracts
      "c-exposure",     // 4.2 beta-weighted delta
      "c-exits",        // 4.3-4.5 stops, target, time exit
      "c-thesis",       // the one sentence, and Open in Workshop
    ] },
  ],

  /* The market as a whole, as the same grid of squares. Each group is a
   * band the packer keeps in one run down the page. */
  world: [
    { id: "where", label: "Where it is", panels: [
      "barometer",      // indices, VIX, Treasuries, gold, oil: a square each
    ] },
    { id: "happened", label: "What happened", panels: [
      "lead",           // the highest-ranked story
      "headlines",      // a square per kind of source, ranked
    ] },
    { id: "coming", label: "What is coming", panels: [
      "calendar",       // a square per scheduled release
    ] },
  ],
};

/* Lists above that are part of a room rather than a room of their own. */
const LAYOUT_PARTS = { steps: "search" };

/* The search page, top to bottom: every panel it had, the thin bar with
 * "Create the path", then the curriculum's squares. Reorder to move a
 * part; drop one to hide it. */
const SEARCH_ORDER = ["tiles", "bar", "steps"];
