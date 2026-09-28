# QUIPU

*The knot record.*

Named for the Incan knotted-cord system — the most sophisticated accounting
technology ever built without writing, used to hold the tribute, census and
stores of an empire on lengths of string.

Search a company by name or ticker and the whole screen fills with it: live
price, options chains with every greek translated into plain English, five years
of revenue and margins, the earnings record, who owns the shares, SEC filings,
retail chatter, and every news article the tool can find — then it reads those
articles and tells you **which facts only one outlet reported**. Each search
opens its own tab, like a browser.

---

## The greeks, said out loud

This is the part worth having. A greek on its own is a number nobody can act on.
Delta 0.50 means nothing. So Quipu multiplies every greek by a real position and
writes the sentence a person would actually say. Pick an expiry, a side, a
strike and a budget; it does the rest.

Real output, AMD at $547.36, the $547.50 call seven days out, $1,000 budget:

> **Delta 0.5175** — If the share price rises **$1**, this position gains about
> **$51.75**. You are holding the equivalent of **52 shares** of exposure, not
> 100. Delta doubles as a rough probability: the market is implying about a
> **52%** chance this finishes in the money.
>
> **Gamma 0.0197** — Delta is not fixed. After a **$1** move your way, delta
> goes from 0.517 to 0.537, so the *next* dollar pays **$53.72** instead of
> **$51.75**. This is the whole appeal: the position accelerates when it wins
> and decelerates when it loses. It works in reverse too, which is why gamma is
> what shorts fear.
>
> **Theta −1.2124** — Time costs you about **$121.24 per day**, every day,
> weekends included, whether the market opens or not. Over the **7 days** to
> expiry that is roughly **$848.68** of decay if nothing else moves — **51%** of
> what you paid. Theta is the rent on optionality.
>
> **Vega 0.3021** — If implied volatility moves **1 point**, from 54.8% to
> 53.8%, the position loses about **$30.21**, and gains the same if IV rises.
> You are not only betting on direction; you are betting on how jumpy the market
> expects things to be.
>
> **What has to happen** — You paid **$1,670.00** for 1 contract. At expiry this
> is worth nothing unless the price is above **$547.50**, and you only start
> making money past **$564.20** — a move of **+3.08%**, inside **7 days**. That
> is comfortably inside the **±5.86%** the options market is pricing, so you are
> asking for something it already considers likely — which is also why the
> contract is not cheap. Most you can lose is the $1,670.00 you paid.

Under that, profit and loss at expiry across a spread of outcomes, from −10% to
+10%, in dollars and in percent.

Same-day expiries get their own wording, because "0 days of decay" is nonsense:
*"This expires today. Every cent you paid goes to zero at the close unless the
price moves your way — there is no tomorrow to wait for."*

---

## Live

The fast half refreshes itself every 15 seconds against a separate endpoint —
price, intraday chart, options and greeks. The slow half (news, filings,
financials, ownership) is fetched once and left alone, deliberately:
re-scraping 45 articles four times a minute would get the tool rate-limited
within the hour, and quarterly figures cannot change between ticks.

A bar across the top always says which is which, and how old the live numbers
are. Pause it, refresh on demand with the button or the **R** key, or reload
everything from scratch.

---

## Searching

Type a company name, not a ticker. "advanced micro" finds AMD; "nvidia" finds
NVDA. Resolution runs against Yahoo's symbol search — free, no key — and the
dropdown shows exchange and instrument type so you do not pick the Frankfurt
listing by mistake. Arrow keys and Enter work.

---

## How it looks

**The launcher** is newsprint: cream paper, carved capitals, and the quipu
itself — a primary cord with knotted pendant cords.

**The dashboard** is a snapshot of the internet for one ticker. Every panel is
skinned as a different kind of page, with its own display face, masthead and
paper stock — eleven distinct heading typefaces across twenty-four panels:

| Skin | Reads like | Used for |
|---|---|---|
| Ticker | Bloomberg — dark, Anton, amber | Quote |
| Tech | A product blog — Space Grotesk, airy | Charts |
| Wire | Reuters — Roboto Condensed, red rule | Returns, flow, stories |
| Tabloid | Archivo Black, black bar, one huge number | Volume, analysts, shorts |
| Magazine | DM Serif feature spread | Implied vs realised, unique claims |
| Terminal | A trading screen — mono on phosphor green | Options, chain, pipeline |
| Broadsheet | WSJ — Playfair headlines, warm stock | The greeks, The Wire |
| Reference | A wiki article — serif, blue links | The business |
| Ledger | Accounts page — mono, gold double rule | Financials, valuation |
| Filing | Official document — typewriter, boxed | SEC, earnings, ownership |
| Forum | A message board — Inter, loud accent | Retail chatter |

Under each masthead is a source line naming where that data actually came
from. It sells the collage, and it happens to be the honest thing to show.

The grid underneath stays a completely filled square — see *Packing* below.

**The compass**, bottom right, is the index. Its cardinal points are the four
data groups rather than N/E/S/W: north is Price, then Options, Business, News
clockwise. Click a bearing to jump to that group and light it up; the needle
swings on its own to whichever group currently fills most of the screen. Click
the hub to fold it away.

### Packing

The tiles are placed by hand in JavaScript, not by `grid-auto-flow: dense`.
Dense packing always left two holes — a one-column strip down the right edge
and the tail of the last row — because it cannot backfill a gap that appeared
after an item was placed, and never resizes anything. Quipu does a first-fit
pass and then a grow pass, where any cell still empty is absorbed by a
neighbour. The result is zero empty cells at any width: 7 columns at 1900px,
5 at 1366px, 4 at 1150px, every row solid.

---

## Running it

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
npm run api          # then open http://127.0.0.1:8848
```

Or as a desktop app:

```bash
npm install && npm start
```

No API keys needed. Everything above runs on free, keyless sources.

### Optional

| Environment variable | What it adds |
|---|---|
| `FINNHUB_API_KEY` | A fourth news-discovery feed |
| `FIRECRAWL_API_KEY` | Paid extraction tier — JavaScript pages and PDFs |
| `SEC_USER_AGENT` | Your `name email`. SEC rate-limits generic agents |

---

## How it is put together

```
backend/
  app.py              FastAPI. /api/ticker/{sym}, /api/live/{sym}, /api/search
  fanout.py           Parallel fan-out, throttled per source
  sources/
    quotes.py         Price, valuation, intraday and daily history
    options.py        Chains, Black-Scholes greeks, IV solver, flow
    deep.py           Profile, annual financials, earnings, ownership, volume
    symbols.py        Company name -> ticker
    news_rss.py       Article discovery + retail chatter
    sec_edgar.py      Filings in plain English
  extract/tiered.py   trafilatura -> news-please -> Firecrawl
  crossref/
    cluster.py        Group articles into stories
    claims.py         Diff claims: corroborated vs unique
frontend/
  greeks.js           The translator: greeks -> sentences with real dollars
  core.js             Formatting, tab state, trade-log storage, calc(), panel()
  layout.js           What each room shows, and in what order
  shell.js            Tab strip, room ring, launcher, render()
  room-search.js      One company: live loop, every tile, zoom, rail
  room-workshop.js    Build a position: routes, board, money, analysis
  room-log.js         Trade log: book, expiry, closing, settling
  room-world.js       The market as a whole
  room-finder.js      Rank the market
  boot.js             Start (loads last)
  styles.css          Newsprint
electron/main.js      Desktop shell; runs the API as a child process
```

### The news pipeline

1. **Fan out** — every source at once, throttled within each.
2. **Discover** — pool several feeds, deduplicate by URL. Pooling roughly
   doubles what any single feed returns.
3. **Extract** — full text, cheapest tier first, bounded concurrency.
4. **Cross-reference** — cluster into stories, then diff the claims:
   **corroborated** (several outlets say it) versus **unique** (one outlet does
   — either a scoop or an error). Unique claims are ranked by how much they
   could move a decision.

Most news tools deduplicate: they spot forty articles about one event and throw
thirty-nine away. That deletes the thing you want. Quipu groups and keeps
everything, then diffs it.

---

## Two things worth knowing

**We do not trust Yahoo's implied volatility.** It frequently returns
placeholders like `0.00001`, which would make every greek zero. Quipu solves IV
from the traded price by bisection instead, and labels each row `solved` or
`vendor`. Yahoo also zeroes bid/ask and open interest outside market hours —
when that happens the tile says "stale" and max pain reads "no open interest"
rather than inventing a number.

**Discovery is the weak link, not extraction.** Per-ticker feeds are noisy: ask
for NVDA and you get articles about Snowflake. Extraction succeeds on ~95% of
what it is given, so relevance filtering will do more for output quality than
any extraction upgrade.

## Not done

Persistent caching between runs, a real-time quote source (Alpaca or Tradier
would replace delayed Yahoo prices), and multi-leg option strategies — spreads,
straddles, condors — which the greeks translator currently cannot size.

## License

[MIT](LICENSE) © 2026 Aarav Sikriwal
