/* The expiry deadline the trade log prints.
 *
 * Run:  node frontend/expiry.test.js
 *
 * The log used to say "1 session left", which is a duration and not a
 * deadline -- you cannot act on it without doing arithmetic against a
 * calendar you do not have. It now prints the day and the clock time
 * trading stops, which is 4:00pm in New York on the expiry date.
 *
 * Two bugs here were found by hand and are pinned by these tests:
 *
 *   The offset trick -- render an instant in New York, re-parse it,
 *   take the difference -- is an IDENTITY on a machine already set to
 *   New York, so it shifted nothing and every expiry printed as noon.
 *   It looked right from any other timezone, which is the worst kind
 *   of wrong: correct on the developer's laptop, wrong for the person
 *   the deadline belongs to.
 *
 *   And with no live price, the warning said "nothing here is in the
 *   money" -- stating as fact the one thing it had no way to know, and
 *   giving the reassurance there was least reason to give.
 */

const { lift } = require("./lift.js");

// NY is the timezone constant the deadline is defined in; the three
// functions below all close over it.
const { NY, nf, money, strikeOf, nyClose, consequenceOf, sellBy } =
  lift("NY", "nf", "money", "strikeOf", "nyClose", "consequenceOf", "sellBy");

let pass = 0, fail = 0;

function is(name, got, want) {
  const ok = got === want;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name.padEnd(50)} got ${got}  want ${want}`);
  ok ? pass++ : fail++;
}
function yes(name, cond, detail = "") {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name.padEnd(50)} ${detail}`);
  cond ? pass++ : fail++;
}
function section(t) { console.log(`\n${t}\n${"-".repeat(t.length)}`); }

const inNY = (dt) => new Intl.DateTimeFormat("en-US", {
  hour: "numeric", minute: "2-digit", hour12: true,
  timeZone: NY, timeZoneName: "short",
}).format(dt);

section("The deadline is 4pm in New York, whatever the season");

// Summer: New York is UTC-4, so 4pm there is 20:00 UTC.
is("a September expiry", nyClose("2026-09-25").toISOString(),
   "2026-09-25T20:00:00.000Z");
is("and it reads as four o'clock", inNY(nyClose("2026-09-25")), "4:00 PM EDT");

// Winter: UTC-5, so the same wall clock is a different instant.
is("a December expiry", nyClose("2026-12-18").toISOString(),
   "2026-12-18T21:00:00.000Z");
is("and it also reads as four o'clock", inNY(nyClose("2026-12-18")), "4:00 PM EST");

// The changeover itself. US daylight saving ends on the first Sunday
// in November, so these two Fridays sit either side of it.
is("the Friday before the clocks change", inNY(nyClose("2026-10-30")), "4:00 PM EDT");
is("the Friday after", inNY(nyClose("2026-11-06")), "4:00 PM EST");

// Every third Friday of 2027, which is where monthly options land.
const monthlies = ["2027-01-15", "2027-02-19", "2027-03-19", "2027-04-16",
                   "2027-05-21", "2027-06-18", "2027-07-16", "2027-08-20",
                   "2027-09-17", "2027-10-15", "2027-11-19", "2027-12-17"];
const offClock = monthlies.filter((d) => inNY(nyClose(d)).slice(0, 7) !== "4:00 PM");
yes("all twelve monthly expiries land on 4:00 PM", offClock.length === 0,
    offClock.length ? offClock.join(", ") : "none drift");

section("It refuses a date it cannot read");

is("empty", nyClose(""), null);
is("nonsense", nyClose("not-a-date"), null);
is("null", nyClose(null), null);

section("What happens if you do not sell says only what is known");

const call160 = { kind: "call", side: "long", strike: 160, qty: 1, expiry: "2026-09-25" };

// No price: it must not claim anything about moneyness.
const blind = consequenceOf([], "2026-09-25", false);
yes("with no live price it does not claim nothing is in the money",
    !/nothing here is in the money/i.test(blind)
    && /has not come back/i.test(blind));

// Known and out of the money: it may say so.
const clear = consequenceOf([], "2026-09-25", true);
yes("with a price and nothing exposed it says so",
    /nothing here is in the money/i.test(clear));

// Known and in the money: it must name the bill.
const owed = consequenceOf([call160], "2026-09-25", true);
yes("an in-the-money long call names what you would be buying",
    /buy 100 shares at \$160/.test(owed), owed.slice(0, 90));
yes("and the cash it would cost", /\$16,000/.test(owed));
yes("and says the broker cuts off earlier", /broker/i.test(owed));

section("A position with nothing to expire has no deadline");

is("shares only", sellBy({ legs: [{ kind: "stock", side: "long", qty: 100 }] }, {}),
   null);

section("The nearest expiry is the one that governs");

// A calendar: a December leg sitting behind a September one. The
// deadline is September's, and only September's leg can be exercised
// at it -- warning about the December call there would name a
// deadline that leg does not have.
const cal = sellBy({
  legs: [
    { kind: "call", side: "long", strike: 160, qty: 1, expiry: "2026-12-18" },
    { kind: "call", side: "short", strike: 170, qty: 1, expiry: "2026-09-25" },
  ],
}, { spot: 175 });
is("the deadline is the earlier of the two", cal.expiry, "2026-09-25");
is("only the leg expiring then can be exercised at it", cal.exposed.length, 1);
is("and it is the September one", cal.exposed[0].expiry, "2026-09-25");
yes("a short call in the money warns about delivery, not a purchase",
    /deliver 100 shares at \$170/.test(cal.consequence),
    cal.consequence.slice(0, 100));

// The out-of-the-money side of the same structure.
const safe = sellBy({
  legs: [{ kind: "call", side: "short", strike: 170, qty: 1, expiry: "2026-09-25" }],
}, { spot: 165 });
is("below the strike, a short call is not exposed", safe.exposed.length, 0);

section("Both sides of a put are named correctly");

const longPut = sellBy({
  legs: [{ kind: "put", side: "long", strike: 160, qty: 2, expiry: "2026-09-25" }],
}, { spot: 150 });
yes("a long put in the money would SELL the shares",
    /sell 200 shares at \$160/.test(longPut.consequence),
    longPut.consequence.slice(0, 100));

const shortPut = sellBy({
  legs: [{ kind: "put", side: "short", strike: 160, qty: 1, expiry: "2026-09-25" }],
}, { spot: 150 });
yes("a short put in the money would have them PUT to you",
    /put 100 shares at \$160/.test(shortPut.consequence),
    shortPut.consequence.slice(0, 100));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
