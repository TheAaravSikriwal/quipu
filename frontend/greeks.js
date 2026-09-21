/* Greeks, said out loud.
 *
 * A greek on its own is a number nobody can act on. Delta 0.43 means nothing;
 * "if it moves a dollar you make forty-three" means something. Every function
 * here takes the raw greek, multiplies it by a real position, and returns the
 * sentence a person would actually say.
 *
 * Contract multiplier is 100 -- one US equity option controls 100 shares.
 */

const MULT = 100;

/* Probability that the price finishes beyond a level, under the same
 * lognormal the option price itself assumes. This is N(d2) -- so the odds
 * quoted here are consistent with the premium being charged, rather than a
 * second opinion pulled from somewhere else. */
const normCdf = (x) => {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp(-x * x / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
};

function probAbove(spot, level, years, vol, rate = 0.04, q = 0) {
  if (!(spot > 0 && level > 0 && years > 0 && vol > 0)) return null;
  const drift = (rate - q - 0.5 * vol * vol) * years;
  const sd = vol * Math.sqrt(years);
  return normCdf((Math.log(spot / level) + drift) / sd);
}

const usd = (v) =>
  (v < 0 ? "-$" : "$") +
  Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const usd0 = (v) =>
  (v < 0 ? "-$" : "$") + Math.abs(Math.round(v)).toLocaleString();

const m = (s) => `<span class="money">${s}</span>`;

/** Size a position from a budget: how many contracts fit, what they cost. */
function sizePosition(contract, budget) {
  const premium = contract.mark || contract.last;
  if (!premium || premium <= 0) return null;

  const perContract = premium * MULT;
  const contracts = Math.max(1, Math.floor(budget / perContract));
  return {
    premium,
    contracts,
    cost: contracts * perContract,
    perContract,
    shares: contracts * MULT,
    leftover: budget - contracts * perContract,
  };
}

/** One explained greek: the number, and what it means in dollars. */
function explainDelta(c, pos, spot, isCall) {
  const perDollar = Math.abs(c.delta) * MULT * pos.contracts;
  const dir = isCall ? "rises" : "falls";
  const chance = Math.round(Math.abs(c.delta) * 100);
  return {
    name: "Delta",
    value: c.delta.toFixed(4),
    say: `If the share price ${dir} <b>$1</b>, this position gains about ${m(usd(perDollar))}.
      You are holding the equivalent of <b>${Math.round(Math.abs(c.delta) * pos.shares)} shares</b>
      of exposure, not ${pos.shares}. Delta doubles as a rough probability: the market
      is implying about a <b>${chance}%</b> chance this finishes in the money.`,
  };
}

function explainGamma(c, pos, isCall) {
  const perDollar = Math.abs(c.delta) * MULT * pos.contracts;
  const nextDelta = Math.abs(c.delta) + c.gamma;
  const nextPerDollar = nextDelta * MULT * pos.contracts;
  const accel = nextPerDollar - perDollar;
  return {
    name: "Gamma",
    value: c.gamma.toFixed(5),
    say: `Delta is not fixed &mdash; gamma is how fast it changes. After a <b>$1</b> move your
      way, delta goes from <b>${Math.abs(c.delta).toFixed(3)}</b> to <b>${nextDelta.toFixed(3)}</b>,
      so the <i>next</i> dollar pays ${m(usd(nextPerDollar))} instead of ${m(usd(perDollar))}
      &mdash; about ${m(usd(accel))} more. This is the whole appeal: the position
      accelerates when it wins and decelerates when it loses. It works in reverse too,
      which is why gamma is what shorts fear.`,
  };
}

/** "today", "1 day", "4 days" -- a same-day expiry has 0 days, not 1. */
function horizon(days) {
  if (days <= 0) return "today";
  return `${days} day${days === 1 ? "" : "s"}`;
}

function explainTheta(c, pos, days) {
  const perDay = Math.abs(c.theta) * MULT * pos.contracts;

  // A same-day expiry does not decay "per day" in any useful sense: whatever
  // premium is left goes to zero at the close, so quote that instead.
  if (days <= 0) {
    return {
      name: "Theta",
      value: c.theta.toFixed(4),
      say: `This <b>expires today</b>. Every cent of the ${m(usd(pos.cost))} you paid is
        premium that goes to zero at the close unless the price moves your way &mdash; there
        is no tomorrow to wait for. Theta is quoted at ${m(usd(perDay))} a day, but on the
        last day it is not a slow leak, it is a cliff.`,
    };
  }

  const toExpiry = perDay * days;
  const share = (toExpiry / pos.cost) * 100;
  return {
    name: "Theta",
    value: c.theta.toFixed(4),
    say: `Time costs you about ${m(usd(perDay))} <b>per day</b> &mdash; every day, weekends
      included, whether the market opens or not. Over the <b>${horizon(days)}</b>
      to expiry that is roughly ${m(usd(toExpiry))} of decay if nothing else moves, which is
      <b>${share.toFixed(0)}%</b> of what you paid. Theta is the rent on optionality.`,
  };
}

function explainVega(c, pos, atmIv) {
  const perPoint = Math.abs(c.vega) * MULT * pos.contracts;
  const iv = c.iv || atmIv;
  return {
    name: "Vega",
    value: c.vega.toFixed(4),
    say: `If implied volatility moves <b>1 point</b> &mdash; from <b>${iv ? iv.toFixed(1) : "?"}%</b>
      to <b>${iv ? (iv - 1).toFixed(1) : "?"}%</b> &mdash; the position loses about
      ${m(usd(perPoint))}, and gains the same if IV rises. You are not only betting on
      direction; you are betting on how jumpy the market expects things to be.
      ${iv && iv > 60
        ? `At <b>${iv.toFixed(0)}%</b> IV you are buying expensive insurance &mdash; a quiet
           week hurts twice, through theta and through vega together.`
        : ""}`,
  };
}

function explainRho(c, pos, rate) {
  const perPoint = Math.abs(c.rho) * MULT * pos.contracts;
  return {
    name: "Rho",
    value: c.rho.toFixed(4),
    say: `A <b>1 percentage point</b> change in interest rates (currently
      <b>${(rate * 100).toFixed(2)}%</b>) moves this about ${m(usd(perPoint))}. On a
      short-dated option that is noise &mdash; rho only starts to matter on
      positions held for many months.`,
  };
}

/** Break-even, and whether the move it needs is one the market expects. */
function verdict(c, pos, spot, isCall, days, expectedMovePct, opts_rate = 0.04, opts_q = 0, tdays = null) {
  const be = isCall ? c.strike + pos.premium : c.strike - pos.premium;
  const needPct = ((be / spot) - 1) * 100;
  const needAbs = Math.abs(needPct);

  let judgement;
  if (expectedMovePct == null) {
    judgement = "";
  } else if (needAbs <= expectedMovePct * 0.6) {
    judgement = `That is comfortably inside the <b>&plusmn;${expectedMovePct.toFixed(2)}%</b>
      move the options market is pricing in, so you are asking for something it already
      considers likely &mdash; which is also why the contract is not cheap.`;
  } else if (needAbs <= expectedMovePct * 1.3) {
    judgement = `The market is pricing a move of about <b>&plusmn;${expectedMovePct.toFixed(2)}%</b>,
      so you need roughly what it expects &mdash; close to a coin flip on the market's own numbers.`;
  } else {
    judgement = `The market is only pricing <b>&plusmn;${expectedMovePct.toFixed(2)}%</b>, so you
      need a move well beyond what it expects. Cheap for a reason: it is an unlikely outcome.`;
  }

  const iv = (c.iv || 0) / 100;
  // Trading days over 252 -- the same clock the greeks are priced on.
  const td = tdays == null ? days : tdays;
  const pWin = probAbove(spot, be, Math.max(td, 1) / 252, iv, opts_rate, opts_q);
  const chance = pWin == null ? null
    : Math.round((isCall ? pWin : 1 - pWin) * 100);
  const intrinsic = Math.max(isCall ? spot - c.strike : c.strike - spot, 0);
  const extrinsic = Math.max(pos.premium - intrinsic, 0);

  return `<span class="t">What has to happen</span>
    You paid ${m(usd(pos.cost))} for <b>${pos.contracts} contract${pos.contracts === 1 ? "" : "s"}</b>.
    At expiry this is worth nothing unless the price is
    ${isCall ? "above" : "below"} <b>${usd(c.strike)}</b>, and you only start making money past
    <b>${usd(be)}</b> &mdash; a move of <b>${needPct > 0 ? "+" : ""}${needPct.toFixed(2)}%</b>
    from ${usd(spot)}, ${days <= 0 ? "<b>before today's close</b>" : `inside <b>${horizon(days)}</b>`}.
    ${judgement}
    ${chance !== null
      ? `On the same lognormal the price of this contract already assumes, that
         is roughly a <b>${chance}%</b> chance of finishing profitable &mdash; and the
         market charges you ${m(usd(pos.cost))} for it.`
      : ""}
    Of the ${m(usd(pos.premium))} premium per share, ${m(usd(intrinsic))} is intrinsic
    (value you would have if it expired now) and <b>${m(usd(extrinsic))}</b> is time
    value, which decays to nothing by expiry.
    Most you can lose is the ${m(usd(pos.cost))} you paid.`;
}

/** Value at expiry across a spread of outcomes -- the honest picture. */
function scenarios(c, pos, spot, isCall) {
  const moves = [-10, -5, -2, 0, 2, 5, 10];
  return moves.map((pctMove) => {
    const price = spot * (1 + pctMove / 100);
    const intrinsic = isCall
      ? Math.max(price - c.strike, 0)
      : Math.max(c.strike - price, 0);
    const value = intrinsic * MULT * pos.contracts;
    const pl = value - pos.cost;
    return {
      pctMove,
      price,
      value,
      pl,
      plPct: (pl / pos.cost) * 100,
    };
  });
}

/** Everything, assembled. */
function explainContract(contract, opts) {
  const { spot, isCall, days, tradingDays, budget, rate, atmIv, expectedMovePct } = opts;
  const pos = sizePosition(contract, budget);
  if (!pos) return null;

  const greeks = [];
  if (contract.delta !== null) greeks.push(explainDelta(contract, pos, spot, isCall));
  if (contract.gamma !== null) greeks.push(explainGamma(contract, pos, isCall));
  if (contract.theta !== null) greeks.push(explainTheta(contract, pos, days));
  if (contract.vega !== null) greeks.push(explainVega(contract, pos, atmIv));
  if (contract.rho !== null) greeks.push(explainRho(contract, pos, rate ?? 0.04));

  return {
    pos,
    greeks,
    verdict: verdict(contract, pos, spot, isCall, days, expectedMovePct,
      rate ?? 0.04, opts.divYield ?? 0, tradingDays),
    scenarios: scenarios(contract, pos, spot, isCall),
  };
}

/* ---- the binomial tree, said out loud -------------------------------
 *
 * Mirrors the Cox-Ross-Rubinstein tree the backend prices on, so the panel
 * rebuilds it instantly for whatever contract is selected rather than waiting
 * on a round trip. Same parameters, same maths.
 */
function binomialTree(S, K, T, v, r, q, steps, isCall) {
  if (!(S > 0 && K > 0 && T > 0 && v > 0)) return null;
  const dt = T / steps;
  const u = Math.exp(v * Math.sqrt(dt));
  const d = 1 / u;
  const growth = Math.exp((r - q) * dt);
  if (!(d < growth && growth < u)) return null;      // no fair probability exists
  const p = (growth - d) / (u - d);
  const disc = Math.exp(-r * dt);
  const payoff = (st) => Math.max(isCall ? st - K : K - st, 0);

  const walk = (allowEarly) => {
    const val = [];
    for (let i = 0; i <= steps; i++) {
      val.push(payoff(S * Math.pow(u, steps - i) * Math.pow(d, i)));
    }
    for (let step = steps - 1; step >= 0; step--) {
      for (let i = 0; i <= step; i++) {
        const hold = (p * val[i] + (1 - p) * val[i + 1]) * disc;
        val[i] = allowEarly
          ? Math.max(hold, payoff(S * Math.pow(u, step - i) * Math.pow(d, i)))
          : hold;
      }
    }
    return val[0];
  };

  const american = walk(true);
  const european = walk(false);
  return {
    price: american, euro: european, early: Math.max(american - european, 0),
    u, d, p, dt, steps,
    upPct: (u - 1) * 100, downPct: (1 - d) * 100,
  };
}

/** Everything the tree panel needs for one contract. */
function explainBinomial(contract, pos, o) {
  const T = Math.max(o.tradingDays || 1, 1) / 252;
  const v = (contract.iv || o.atmIv || 0) / 100;
  const tree = binomialTree(o.spot, contract.strike, T, v,
                            o.rate ?? 0.04, o.divYield ?? 0, 120, o.isCall);
  if (!tree) return null;
  const market = contract.mark || contract.last;
  return {
    tree,
    market,
    gapVsMarket: market ? tree.price - market : null,
    hours: (tree.dt * 252 * 6.5).toFixed(1),
    earlyTotal: tree.early * MULT * pos.contracts,
  };
}

window.QUIPU_GREEKS = {
  binomialTree, explainBinomial, explainContract, sizePosition, usd, usd0, MULT, probAbove, normCdf };
