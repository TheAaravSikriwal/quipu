/* The glossary.
 *
 * This page is dense with terms that carry a precise meaning and are almost
 * never explained anywhere you can reach while reading them. Looking one up
 * means leaving the page, and leaving the page means losing your place, so
 * in practice nobody looks anything up and the number just gets skipped.
 *
 * So the definitions come to the term instead. Every entry answers three
 * questions in the order a person actually asks them:
 *
 *   plain    what it means, in a sentence, with no other jargon in it
 *   formula  how it is actually computed, where that is a real formula and
 *            not a decoration -- omitted entirely for non-mathematical terms,
 *            because a fake formula is worse than none
 *   note     the thing people get wrong about it
 *
 * Keys are matched case-insensitively against whole words in the rendered
 * text. `alt` lists other spellings that should point at the same entry.
 */

const TERMS = {
  /* ---- volatility ---- */

  "implied volatility": {
    alt: ["implied vol", "iv"],
    plain: "How much movement the option's own price says traders are expecting, quoted as a yearly percentage.",
    formula: "solve  BlackScholes(σ) = market price  for σ",
    note: "It is backed out of the price, not measured from the stock. 50% does not mean it will move 50% — it means one year's typical swing is 50%.",
    use: "Compare it against realised volatility on the same stock. Well above and " +
         "the options are dear, which favours selling; well below and they are " +
         "cheap, which favours buying. The volatility panel does that comparison for " +
         "you.",
  },
  "annualised volatility": {
    alt: ["annualized volatility", "annualised", "annualized"],
    plain: "A rate of movement scaled up to what it would amount to over a full year, so periods of different length can be compared.",
    formula: "σ_year = σ_day × √252",
    note: "252 is the number of trading days in a year. Movement grows with the square root of time, not with time — four times the days is only twice the movement.",
    use: "It exists so two stocks, or two periods of different length, can be put " +
         "side by side. To get back to the move over your own holding period, divide " +
         "by √252 and multiply by the sessions you will hold.",
  },
  "realised volatility": {
    alt: ["realized volatility", "realised vol", "historical volatility"],
    plain: "How much the stock has actually moved recently, measured from its own closing prices.",
    formula: "stdev(ln(Pₜ / Pₜ₋₁)) × √252",
    note: "This is the past. Implied volatility is the future being guessed at. The gap between them is the whole options trade.",
    use: "This is the yardstick for whether an option is expensive. If implied sits " +
         "well above it and nothing is scheduled before expiry, you are being paid " +
         "above the odds to sell.",
  },
  "standard deviation": {
    alt: ["sigma", "one sigma", "1σ"],
    plain: "The typical distance of an outcome from the average — a measure of how spread out the possibilities are.",
    formula: "σ = √( mean of (x − mean)² )",
    note: "About 68% of outcomes fall within one standard deviation of the middle, and 95% within two.",
    use: "Read the expected move as one of these: roughly two times in three the " +
         "stock finishes inside it. A strike beyond two is a long shot, and it is " +
         "priced like one.",
  },
  "lognormal distribution": {
    alt: ["lognormal"],
    plain: "The shape used for where a share price might end up: it can rise without limit but cannot fall below zero, so the spread is lopsided upwards.",
    formula: "ln(Pₜ / P₀)  is normally distributed",
    note: "It is the percentage moves that are treated as symmetric, not the dollar moves. A 50% fall and a 50% rise are not opposites — you need +100% to undo −50%.",
    use: "It is why the odds are not symmetric — a share can triple but cannot go " +
         "below zero. Do not assume a 10% rise and a 10% fall are equally likely; " +
         "the upside tail is longer.",
  },
  "variance risk premium": {
    plain: "The extra amount option sellers charge above what the stock has actually been doing — payment for carrying the risk of a surprise.",
    formula: "implied vol − realised vol",
    note: "Usually positive. That is why selling options wins often and loses big.",
    use: "Wide, and sellers are being overpaid — credit structures have the wind " +
         "behind them. Negative, and buying is the cheaper side of the market.",
  },

  /* ---- the greeks ---- */

  delta: {
    plain: "How much the option's price moves for a $1 move in the stock.",
    formula: "Δ = ∂V/∂S    (call: e^−qT·N(d₁))",
    note: "Also read as share-equivalents: a 0.60 delta contract behaves like 60 shares. Loosely, it is the market's odds of finishing in the money.",
    use: "Use it to size a position: a 0.30 call behaves like 30 shares, so three of " +
         "them is about 100 shares of exposure. It is also the quickest read on the " +
         "odds of finishing in the money.",
  },
  gamma: {
    plain: "How fast delta itself changes as the stock moves — the acceleration behind the position.",
    formula: "Γ = ∂Δ/∂S = e^−qT·N′(d₁) / (S·σ·√T)",
    note: "High gamma means the position speeds up when it works and stalls when it fails. It peaks at the money and near expiry.",
    use: "High gamma is the warning that a position will change character fast. Near " +
         "the money and near expiry it needs watching daily rather than weekly.",
  },
  theta: {
    plain: "How much value the option loses per day purely from time passing.",
    formula: "Θ = ∂V/∂t   (quoted per day)",
    note: "Always working against the buyer. It accelerates as expiry approaches rather than bleeding evenly.",
    use: "Your rent as a buyer and your income as a seller. Compare it against the " +
         "move you need: if theta costs more per day than the stock typically moves " +
         "in your favour, time is the bigger opponent than direction.",
  },
  vega: {
    plain: "How much the option's price moves when implied volatility changes by one percentage point.",
    formula: "ν = ∂V/∂σ = S·e^−qT·N′(d₁)·√T / 100",
    note: "You can be right about direction and still lose if volatility collapses. That is vega.",
    use: "Check it before buying into an event. The volatility collapse after an " +
         "earnings report can cost you more than a correct call on direction earns.",
  },
  rho: {
    plain: "How much the option's price moves when interest rates change by one percentage point.",
    formula: "ρ = ∂V/∂r",
    note: "The greek that matters least on short-dated options and most on long ones.",
    use: "Safe to ignore on anything under a few months. On a LEAP it is part of why " +
         "the call costs what it does.",
  },

  /* ---- pricing models ---- */

  "black-scholes": {
    alt: ["black scholes"],
    plain: "The standard formula for what an option should cost, given the price, the strike, the time left, interest rates and expected movement.",
    formula: "C = S·e^−qT·N(d₁) − K·e^−rT·N(d₂)",
    note: "It assumes the option can only be exercised at expiry and that volatility is constant. Neither is quite true, which is why real prices drift from it.",
    use: "Use it for the comparison, not for the answer. Its value tells you whether " +
         "a listed price sits above or below one consistent benchmark, which is what " +
         "the fair-value column on the board is.",
  },
  "binomial tree": {
    alt: ["binomial", "cox-ross-rubinstein", "crr"],
    plain: "Prices an option by drawing every up-or-down path the stock could take, then working backwards from expiry to today.",
    formula: "u = e^(σ√Δt),  d = 1/u,  p = (e^((r−q)Δt) − d)/(u − d)",
    note: "Slower than Black-Scholes but it can handle early exercise, so it is the honest model for American options.",
    use: "Reach for it over Black-Scholes wherever early exercise is possible: an " +
         "American option on a dividend payer, or a deep in-the-money put.",
  },
  "american option": {
    alt: ["american options", "early exercise"],
    plain: "An option you are allowed to exercise on any day up to expiry, not only on the last one.",
    note: "That freedom has a value, so an American option is never worth less than the European equivalent. Nearly all single-stock options are American.",
    use: "The practical consequence is assignment. Short an in-the-money call going " +
         "into an ex-dividend date and you should expect to be exercised early and " +
         "left short the stock.",
  },
  "european option": {
    alt: ["european options"],
    plain: "An option that can only be exercised on the expiry date itself.",
    note: "Simpler to price — Black-Scholes assumes this. Index options are usually European.",
    use: "Nothing to manage before expiry. Index options are usually European, which " +
         "is exactly why they cannot be assigned early.",
  },
  "risk-free rate": {
    alt: ["risk free rate"],
    plain: "The return you could get with no risk at all, used as the baseline every other return is judged against.",
    formula: "usually the short-term Treasury yield",
    note: "It appears in option pricing because holding stock ties up cash that could have been earning this instead.",
    use: "Negligible on a weekly, material on a LEAP. If you are weighing a " +
         "long-dated call against buying the shares outright, this is part of the " +
         "difference.",
  },
  "n(d2)": {
    alt: ["d2"],
    plain: "The model's own estimate of the chance the option finishes in the money.",
    formula: "d₂ = d₁ − σ√T",
    note: "This is a probability under the pricing model's assumptions, not a forecast of what will happen.",
    use: "Read it as the market's own odds that the option finishes in the money, " +
         "then compare it with your view. Where you disagree with it is the trade.",
  },

  /* ---- chain mechanics ---- */

  strike: {
    alt: ["strike price"],
    plain: "The price at which the option lets you buy (call) or sell (put) the stock.",
    note: "The whole contract is a bet about where the stock sits relative to this number on expiry day.",
    use: "Choosing it is choosing your odds. A strike near the money is likely to " +
         "matter and costs accordingly; one far out is cheap because it probably " +
         "will not.",
  },
  "open interest": {
    plain: "How many contracts are currently held open — positions that exist right now, not trades made today.",
    note: "Compare it with today's volume: volume far above open interest means the position was opened today, not closed.",
    use: "Use it to judge whether you can get back out. A strike with a few hundred " +
         "contracts open will cost you on the spread the day you want to close.",
  },
  "in the money": {
    alt: ["itm"],
    plain: "The option already has real value if exercised now — a call below the share price, or a put above it.",
    formula: "call: S > K     put: S < K",
    use: "It decides assignment. A short option that is in the money at expiry " +
         "becomes stock — shares you must deliver, or cash you must find.",
  },
  "at the money": {
    alt: ["atm"],
    plain: "The strike sitting closest to today's share price.",
    note: "Where gamma and time decay are both at their strongest.",
    use: "The most sensitive strike on the board: the most time value, the most " +
         "gamma, the most vega. Where to go for a bet on movement rather than " +
         "direction.",
  },
  "intrinsic value": {
    alt: ["intrinsic"],
    plain: "What the option would be worth if it expired this instant.",
    formula: "call: max(S − K, 0)    put: max(K − S, 0)",
    use: "The part that cannot decay. An option that is nearly all intrinsic behaves " +
         "like the stock and is a way of buying it with less capital.",
  },
  "extrinsic value": {
    alt: ["extrinsic", "time value"],
    plain: "Everything you pay above intrinsic value — the price of the time and uncertainty still left.",
    formula: "price − intrinsic value",
    note: "This is the part that decays to nothing by expiry. On an out-of-the-money option it is the entire premium.",
    use: "This is the part that decays, so it is the part you are really trading. " +
         "Paying a lot of it means buying time you have to be right inside; selling " +
         "it means being paid to wait.",
  },
  straddle: {
    plain: "Buying the call and the put at the same strike — a bet on movement in either direction.",
    formula: "cost = call + put  (both at the money)",
    note: "Its price is the cleanest read on the move the market expects, because direction cancels out.",
    use: "Buy one when you expect a move and have no view on direction, and check " +
         "the expected move first — that is the size of move you need just to " +
         "break even.",
  },
  "expected move": {
    alt: ["implied move"],
    plain: "How far the options market is pricing the stock to travel by expiry, up or down.",
    formula: "≈ straddle price ÷ share price",
    note: "Roughly a one-standard-deviation range: the stock stays inside it about two times in three.",
    use: "Set your strikes against it. Selling inside it is selling the range the " +
         "market already expects; buying outside it needs more than an ordinary move " +
         "to pay off.",
  },
  "max pain": {
    plain: "The strike at which the largest amount of option value would expire worthless.",
    note: "Widely treated as a magnet. There is no mechanism that drags price to it — it only tells you where option sellers are most comfortable.",
    use: "Treat it as folklore with a grain of truth in it. Worth knowing where it " +
         "is, not worth taking a position on.",
  },
  "put/call ratio": {
    alt: ["put-call ratio", "p/c ratio", "put call ratio"],
    plain: "Puts traded for every call traded — a rough read on whether the crowd is leaning defensive or bullish.",
    formula: "put volume ÷ call volume",
    note: "Above 1 means more puts than calls. Compare today's flow with open interest: the signal is when they disagree.",
    use: "A crowding gauge, and only readable against its own history. An absolute " +
         "level means nothing without knowing what is normal for this name.",
  },
  "bid-ask spread": {
    alt: ["bid/ask spread", "spread", "bid", "ask"],
    plain: "The gap between the highest price a buyer will pay and the lowest a seller will take.",
    formula: "(ask − bid) ÷ ask",
    note: "A cost you pay on the way in and again on the way out. Wide spreads quietly ruin otherwise sound trades.",
    use: "Half of it is your cost to get in and the other half your cost to get out. " +
         "On a wide spread the trade has to work by more than it appears to.",
  },
  mark: {
    plain: "The fair current price of a contract, taken as the midpoint between bid and ask.",
    formula: "(bid + ask) ÷ 2",
    note: "More honest than the last traded price, which can be hours stale on a quiet strike.",
    use: "Use it to value what you hold, never to plan a trade. You cannot " +
         "transact at the mark; you buy at the ask and sell at the bid, which is " +
         "why the board makes those two the buttons.",
  },
  "trading days": {
    alt: ["trading day"],
    plain: "Days the market is actually open — weekends and holidays excluded.",
    formula: "T = trading days ÷ 252",
    note: "Options decay on trading days, not calendar days, which is why a weekend costs a holder almost nothing.",
    use: "Judge decay in trading days, not calendar ones. A three-day weekend costs " +
         "you one day of time value, not three.",
  },
  "probability of touch": {
    alt: ["p_touch", "touch"],
    plain: "The chance the price reaches a level at any point before expiry, even if it falls back afterwards.",
    formula: "≈ 2 × P(finishing past it)",
    note: "Roughly double the chance of finishing there. The gap is the difference between a trade you manage and one you hold.",
    use: "Roughly twice the odds of finishing there. If you are selling a strike, " +
         "this is the chance you get tested at some point — and get frightened — " +
         "even on trades that finish fine.",
  },

  /* ---- valuation ---- */

  "p/e ratio": {
    alt: ["p/e", "pe ratio", "price to earnings", "pe trailing", "pe forward"],
    plain: "What you pay for each dollar the company earns in a year.",
    formula: "share price ÷ earnings per share",
    note: "A P/E of 30 means thirty years of today's earnings to pay for the share. High is only bad if the growth does not arrive.",
    use: "Only useful against the company's own history and its direct rivals. " +
         "Comparing one across industries tells you about the industries.",
  },
  peg: {
    alt: ["peg ratio"],
    plain: "The P/E ratio measured against how fast earnings are growing — an attempt to say whether a high P/E is deserved.",
    formula: "P/E ÷ earnings growth rate (%)",
    note: "Below 1 is the traditional rule of thumb for cheap. It is only as good as the growth estimate inside it.",
    use: "Around 1 is the old rule of thumb for a fair price, but it depends " +
         "entirely on the growth estimate underneath it — so it is only as good as " +
         "that forecast.",
  },
  "price to book": {
    alt: ["p/b", "price/book"],
    plain: "The share price against the accounting value of what the company owns outright.",
    formula: "market cap ÷ (assets − liabilities)",
    note: "Meaningful for banks and asset-heavy businesses, close to meaningless for software companies whose value is not on the balance sheet.",
    use: "Informative for banks and asset-heavy businesses where the book is real. " +
         "Close to meaningless for software, where the assets are people.",
  },
  "price to sales": {
    alt: ["p/s", "price/sales"],
    plain: "What you pay for each dollar of revenue, regardless of whether any of it is profit.",
    formula: "market cap ÷ annual revenue",
    note: "The fallback measure for companies with no earnings yet.",
    use: "The fallback when there are no earnings to divide by, so it is the one to " +
         "use on a loss-making growth company.",
  },
  "ev/ebitda": {
    alt: ["enterprise value", "ebitda"],
    plain: "The whole cost of buying the business, including its debt, against its rough operating cash profit.",
    formula: "(market cap + debt − cash) ÷ EBITDA",
    note: "Harder to flatter than P/E because it counts debt, which a share price alone ignores.",
    use: "The measure that survives different debt loads, which makes it the fairer " +
         "comparison between two companies financed differently.",
  },
  "free cash flow": {
    alt: ["free cashflow", "fcf"],
    plain: "Cash left over after running the business and paying for the equipment it needs.",
    formula: "operating cash flow − capital expenditure",
    note: "Harder to manipulate than earnings. This is the money available for dividends, buybacks and debt.",
    use: "This is what dividends and buybacks are actually paid out of. A company " +
         "reporting profit but generating no cash is worth a second look.",
  },
  "market cap": {
    alt: ["market capitalisation", "market capitalization"],
    plain: "The total value of all the company's shares at today's price.",
    formula: "share price × shares outstanding",
    note: "What the equity costs, not what the company costs — that would also include its debt.",
    use: "What the whole equity would cost. Set it against free cash flow for a " +
         "rough yield on owning the entire business.",
  },
  "return on equity": {
    alt: ["roe"],
    plain: "How much profit the company makes for each dollar shareholders have in it.",
    formula: "net income ÷ shareholders' equity",
    note: "Can be inflated by borrowing, so read it alongside debt to equity.",
    use: "High and steady is a moat. High and driven by borrowing is leverage in " +
         "disguise — check it against debt to equity before being impressed.",
  },
  "debt to equity": {
    alt: ["debt/equity", "d/e"],
    plain: "How much the company has borrowed for every dollar its owners have put in.",
    formula: "total debt ÷ shareholders' equity",
    note: "Leverage magnifies both directions. It is what turns a bad year into a fatal one.",
    use: "Read it with the current ratio. Heavy debt is survivable on steady cash " +
         "flow and dangerous without it.",
  },
  "current ratio": {
    plain: "Whether the company can cover the bills due within a year out of what it can turn into cash within a year.",
    formula: "current assets ÷ current liabilities",
    note: "Below 1 means it cannot, on paper.",
    use: "Under 1 means more falls due within the year than there are liquid assets " +
         "to meet it. Normal in some industries, a warning in others.",
  },
  "profit margin": {
    alt: ["net margin"],
    plain: "How much of each dollar of revenue survives all the way to profit.",
    formula: "net income ÷ revenue",
    use: "Compare with direct rivals, never across industries. A margin rising on " +
         "flat revenue is pricing power, which is the rarer and better thing.",
  },
  "operating margin": {
    plain: "How much of each revenue dollar is left after the costs of actually running the business, before interest and tax.",
    formula: "operating income ÷ revenue",
    use: "The cleanest read on the business itself, before financing and tax " +
         "decisions muddy it.",
  },
  "gross margin": {
    plain: "How much of each revenue dollar is left after only the direct cost of making the product.",
    formula: "(revenue − cost of goods) ÷ revenue",
    note: "The ceiling on every other margin, and the clearest sign of pricing power.",
    use: "What survives the cost of making the thing. Falling gross margin on rising " +
         "revenue means the company is buying its growth.",
  },
  "earnings per share": {
    alt: ["eps"],
    plain: "The company's profit divided across every share, so it can be compared with the share price.",
    formula: "net income ÷ shares outstanding",
    note: "Rises when profit rises — or when the company simply buys back its own shares.",
    use: "Watch the share count alongside it. EPS can rise on buybacks alone, with " +
         "the company earning no more than it did last year.",
  },
  "payout ratio": {
    plain: "The share of profit handed to shareholders as dividends rather than kept in the business.",
    formula: "dividends ÷ net income",
    note: "Above 100% means the dividend is being paid out of something other than this year's earnings.",
    use: "Over 100% the dividend is coming from somewhere other than earnings. Check " +
         "this before relying on the yield.",
  },
  "dividend yield": {
    plain: "The annual dividend as a percentage of what a share costs today.",
    formula: "annual dividend ÷ share price",
    note: "It rises when the price falls, so an unusually high yield is often a warning rather than a bargain.",
    use: "For options it matters twice: dividends push call prices down and put " +
         "prices up, and an ex-date before your expiry is when a short in-the-money " +
         "call is most likely to be assigned early.",
  },
  beta: {
    plain: "How hard the stock moves compared with the market as a whole.",
    formula: "β = cov(stock, market) ÷ var(market)",
    note: "Beta 1.5 means it has historically moved 50% more than the index, both ways. It measures past sensitivity, not risk of failure.",
    use: "Use it to judge how much of a position's risk is really just the " +
         "market's. A high-beta name in a falling market needs no company-specific " +
         "bad news to hurt you.",
  },

  /* ---- ownership and flow ---- */

  float: {
    alt: ["free float", "floating shares"],
    plain: "The shares actually available to trade, after insiders and locked-up holdings are taken out.",
    note: "A small float makes a stock jumpy: the same order moves the price much further.",
    use: "A small float means the price moves further on the same order. Check it " +
         "before assuming a stock can absorb your size, or before reading much " +
         "into a big daily move.",
  },
  "short interest": {
    alt: ["shares short", "short percent of float"],
    plain: "How many shares have been borrowed and sold by people betting the price falls.",
    formula: "shares short ÷ float",
    note: "Those shares must eventually be bought back, which is what makes a heavily shorted stock capable of a violent rally.",
    use: "It cuts both ways. It is a considered bearish opinion, and it is also fuel " +
         "if the stock starts rising.",
  },
  "days to cover": {
    alt: ["short ratio"],
    plain: "How many normal trading days it would take short sellers to buy back everything they owe.",
    formula: "shares short ÷ average daily volume",
    note: "The higher it is, the more crowded the exit — and the sharper a squeeze can be.",
    use: "The larger it is, the longer a squeeze can run once one starts, because " +
         "the exit takes that many days of normal volume.",
  },
  "institutional ownership": {
    alt: ["institutions"],
    plain: "The share of the company held by funds, pensions and other professional managers rather than individuals.",
    note: "High ownership means the price is set by people who publish their reasoning quarterly and move in size.",
    use: "Very high leaves little marginal buying left to come. Very low means no " +
         "professional has looked, which is either an opportunity or a reason.",
  },

  /* ---- price and chart ---- */

  "moving average": {
    alt: ["sma", "simple moving average", "ma20", "ma50", "ma200"],
    plain: "The average closing price over the last N days, redrawn each day, used to see the trend through the noise.",
    formula: "SMAₙ = (P₁ + P₂ + … + Pₙ) ÷ n",
    note: "It always lags, by roughly half its length. Crossings are watched because many people watch them.",
    use: "Use it as a reference level rather than a signal. Where the price sits " +
         "against the 200-day is how most of the market frames the trend, which " +
         "makes it worth knowing whoever you are.",
  },
  candlestick: {
    alt: ["candle", "candles", "ohlc"],
    plain: "One bar showing four prices for a period: where it opened, the highest and lowest it traded, and where it closed.",
    note: "Here a hollow body closed up and a filled body closed down. The thin line is the high and low — the part of the move that did not stick.",
    use: "Read the body against the wick. A long wick and a small body means the " +
         "move was attempted and rejected, which is a different day from a long " +
         "solid body.",
  },
  volume: {
    plain: "How many shares changed hands in the period.",
    note: "Only meaningful next to a normal day. A big move on light volume is drift; the same move on heavy volume is agreement.",
    use: "Volume is the corroboration. A large move on light volume is drift; the " +
         "same move on heavy volume is agreement, and far more likely to hold.",
  },
  "52-week range": {
    alt: ["52 week range", "52-week high", "52-week low"],
    plain: "The highest and lowest the stock has traded over the past year.",
    note: "Where the price sits inside that band is a quick read on whether you are buying strength or weakness.",
    use: "Where in the range it sits is the mood. Near the high, something is going " +
         "right and expectations have risen with it — which is also what makes a " +
         "miss expensive.",
  },
  "price target": {
    alt: ["target price", "analyst target"],
    plain: "Where an analyst publicly expects the share price to be, usually twelve months out.",
    note: "An opinion with a number on it. The spread between the highest and lowest target says more than the average.",
    use: "An opinion with a sell-side incentive behind it. Useful as a spread of " +
         "views and a sense of the consensus, not as a number to trade to.",
  },
  "log scale": {
    alt: ["logarithmic"],
    plain: "An axis where equal distances mean equal percentage changes rather than equal dollar changes.",
    formula: "position ∝ ln(price)",
    note: "The honest way to read multi-year charts: a rise from $10 to $20 and from $100 to $200 are the same move and should look the same.",
    use: "Switch to it for anything over a year. On a linear scale the recent years " +
         "always look the most dramatic, purely because the price is bigger.",
  },
};

/* ---- lookup table ------------------------------------------------------
 * Longest phrase first, so "implied volatility" wins over "volatility" and
 * "put/call ratio" is never chopped into "ratio". */
const LOOKUP = new Map();
for (const [key, def] of Object.entries(TERMS)) {
  LOOKUP.set(key.toLowerCase(), { key, def });
  for (const a of def.alt || []) LOOKUP.set(a.toLowerCase(), { key, def });
}
const PHRASES = [...LOOKUP.keys()].sort((a, b) => b.length - a.length);

/* Terms too short or too common to match safely on their own. They still get
 * a definition when written in full, but a bare "mark" or "spread" in a
 * sentence is usually the ordinary English word. */
const RISKY = new Set(["iv", "atm", "itm", "crr", "d2", "pe ratio", "p/e", "p/b", "p/s",
  "d/e", "eps", "roe", "fcf", "peg", "beta", "delta", "gamma", "theta", "vega", "rho",
  "mark", "spread", "bid", "ask", "volume", "float", "strike", "touch", "annualised",
  "annualized", "binomial", "candle", "candles", "ohlc", "logarithmic", "sma"]);

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&");

/* One regular expression for everything, built once. \b does not work at the
 * edge of "p/e" or "n(d2)", so the boundaries are written as lookarounds on
 * word characters instead. */
const MATCHER = new RegExp(
  "(?<![\\w-])(" + PHRASES.map(escapeRe).join("|") + ")(?![\\w-])", "gi");

const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "SVG", "TEXTAREA", "INPUT", "SELECT",
  "OPTION", "BUTTON", "H2", "H3", "CODE"]);

/**
 * Wrap known terms inside `root` so they can be hovered.
 *
 * Walks text nodes only. Rewriting innerHTML with a regex would happily
 * corrupt an href or a data attribute that happens to contain the word
 * "delta"; a text node cannot contain markup, so there is nothing there to
 * break.
 *
 * Each term is linked once per container. Every instance underlined would
 * turn a paragraph into a field of dots and make the page harder to read,
 * which is the opposite of the point.
 */
function annotate(root) {
  if (!root) return;
  const seen = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue || node.nodeValue.length < 3) return NodeFilter.FILTER_REJECT;
      for (let p = node.parentElement; p && p !== root; p = p.parentElement) {
        if (SKIP_TAGS.has(p.tagName) || p.classList.contains("term")) {
          return NodeFilter.FILTER_REJECT;
        }
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });

  const targets = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) targets.push(n);

  for (const node of targets) {
    const text = node.nodeValue;
    MATCHER.lastIndex = 0;
    let match, out = null, last = 0;

    while ((match = MATCHER.exec(text)) !== null) {
      const raw = match[0];
      const lower = raw.toLowerCase();
      const hit = LOOKUP.get(lower);
      if (!hit) continue;
      // A short ambiguous token only counts when it is capitalised as a
      // label ("Delta") or already stood alone; lower-case prose gets left be.
      if (RISKY.has(lower) && raw[0] === raw[0].toLowerCase() && raw.length < 7) continue;
      if (seen.has(hit.key)) continue;
      seen.add(hit.key);

      out ||= document.createDocumentFragment();
      if (match.index > last) {
        out.appendChild(document.createTextNode(text.slice(last, match.index)));
      }
      const span = document.createElement("span");
      span.className = "term";
      span.dataset.term = hit.key;
      span.textContent = raw;
      out.appendChild(span);
      last = match.index + raw.length;
    }

    if (out) {
      if (last < text.length) out.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(out, node);
    }
  }
}

/* ---- the tip ---------------------------------------------------------- */

let tip = null;
let hideTimer = null;

function ensureTip() {
  // Re-create when the cached node is no longer in the document. Holding on
  // to a detached element means styling something that is not on screen and
  // never noticing -- the tip simply stops appearing.
  if (tip && tip.isConnected) return tip;
  if (tip) tip.remove();
  document.querySelectorAll(".termtip").forEach((n) => n.remove());
  tip = document.createElement("div");
  tip.className = "termtip";
  tip.style.display = "none";
  document.body.appendChild(tip);
  // Staying inside the tip keeps it open, so a long definition can be read
  // without the cursor having to hover a four-character word the whole time.
  tip.addEventListener("pointerenter", () => clearTimeout(hideTimer));
  tip.addEventListener("pointerleave", hideTip);
  return tip;
}

function hideTip() {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    if (!tip) return;
    tip.style.display = "none";
  }, 120);
}

function showTip(el) {
  const hit = LOOKUP.get(el.dataset.term);
  if (!hit) return;
  clearTimeout(hideTimer);
  const t = ensureTip();
  const { key, def } = hit;

  t.innerHTML =
    `<h6>${key}</h6>` +
    `<p>${def.plain}</p>` +
    (def.formula ? `<pre>${def.formula}</pre>` : "") +
    (def.note ? `<p class="note">${def.note}</p>` : "") +
    // What it means is half an answer. The other half is what to do
    // with it, which is the half a glossary normally leaves out.
    (def.use ? `<p class="use"><b>Using it</b>${def.use}</p>` : "");

  /* Positioned by transform, not by left/top. The tip is pinned at the
   * viewport origin in CSS and moved from there, which keeps it on the
   * compositor and avoids a layout on every hover. */
  t.style.display = "block";
  t.style.transform = "translate3d(0,0,0)";

  // Place it under the word, then pull it back inside the window. Above
  // instead if there is no room below -- a tip half off the screen is worse
  // than no tip.
  const r = el.getBoundingClientRect();
  const b = t.getBoundingClientRect();
  const margin = 10;
  let left = r.left + r.width / 2 - b.width / 2;
  left = Math.max(margin, Math.min(left, window.innerWidth - b.width - margin));
  let top = r.bottom + 8;
  if (top + b.height > window.innerHeight - margin) top = r.top - b.height - 8;
  // Clamp both edges, not just the top. A term scrolled out of view reports a
  // rect far below the fold, and guarding one side sent the tip with it.
  top = Math.max(margin, Math.min(top, window.innerHeight - b.height - margin));

  t.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
}

/* One delegated listener for the whole document rather than one per term.
 * The page re-annotates on every live tick; per-element listeners would
 * accumulate by the hundred. */
document.addEventListener("pointerover", (e) => {
  const el = e.target.closest?.(".term");
  if (el) showTip(el);
});
document.addEventListener("pointerout", (e) => {
  if (e.target.closest?.(".term")) hideTip();
});
document.addEventListener("scroll", () => { if (tip) tip.style.display = "none"; }, true);

window.QUIPU_GLOSSARY = { annotate, TERMS, has: (t) => LOOKUP.has(String(t).toLowerCase()) };
