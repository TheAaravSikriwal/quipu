/* Test support: pull a declaration out of a frontend file and run it.
 *
 * These are classic scripts, not modules -- they share one global
 * scope by design, and several of them touch `document` at load, so
 * requiring them is not an option. Wrapping them up as modules to make
 * them testable would change the thing being tested.
 *
 * So the tests lift the declarations they need straight out of the
 * source and evaluate those. The point is that they test the code that
 * actually ships rather than a copy of it, which is the only kind of
 * copy that cannot drift.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const cache = {};

function source(file) {
  if (!(file in cache)) {
    cache[file] = fs.readFileSync(path.join(__dirname, file), "utf8");
  }
  return cache[file];
}

/* Every script the page loads, in the order it loads them.
 *
 * Read off index.html rather than listed, so a declaration can move
 * from one file to another -- which is the whole point of splitting
 * the app by room -- without a single test having to be told.
 */
function shipped() {
  const page = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  return [...page.matchAll(/<script src="[^"]*?\/?([\w.-]+\.js)"/g)].map((m) => m[1]);
}

/* Which shipped file declares `name` at the top level. Exactly one
 * may: two would be a SyntaxError on the page before it is a question
 * here. */
function whereIs(name) {
  const decl = new RegExp(`^(?:const ${name} = |function ${name}\\()`, "m");
  // A file wrapped in an IIFE declares nothing on the page, so a name
  // inside one is not the page's -- ask for it as "file.js:name".
  const wrapped = (f) => /^\(function \(\) \{/m.test(source(f))
    && source(f).trimEnd().endsWith("}());");
  const hits = shipped().filter((f) => !wrapped(f) && decl.test(source(f)));
  if (hits.length === 1) return hits[0];
  if (!hits.length) throw new Error(`no shipped script declares "${name}"`);
  throw new Error(`"${name}" is declared by ${hits.join(" and ")}`);
}

/** The source text of one top-level `const name = ...;` or `function name`. */
function one(name, file = whereIs(name)) {
  const src = source(file);
  const asConst = new RegExp(`^const ${name} = `, "m");
  const asFn = new RegExp(`^function ${name}\\(`, "m");
  let start = src.search(asConst);
  const isFn = start < 0;
  if (isFn) start = src.search(asFn);
  if (start < 0) throw new Error(`could not find "${name}" in ${file}`);

  // The declaration ends at the first closing `}` (a function) or `;`
  // (a const) where the text so far is a complete program -- asked of
  // the JavaScript parser rather than worked out by counting brackets.
  //
  // It was counted, and the counter knew about quotes but not comments,
  // so an apostrophe in a comment ("the market's close") opened a string
  // that ran on until some unrelated quote further down happened to
  // close it. In one 7,000-line file that always turned up eventually;
  // split by room, it ran off the end of the file.
  const closer = isFn ? "}" : ";";
  for (let i = src.indexOf(closer, start); i >= 0; i = src.indexOf(closer, i + 1)) {
    const text = src.slice(start, i + 1);
    try {
      new vm.Script(text);
      return text;
    } catch (e) {
      if (!(e instanceof SyntaxError)) throw e;
    }
  }
  throw new Error(`"${name}" in ${file} never ends`);
}

/** Evaluate several declarations together and hand them back.
 *
 * Names may be given as "name" (found in whichever shipped script
 * declares it) or "file.js:name" to insist on one file.
 */
function lift(...names) {
  const parts = names.map((n) => {
    const i = n.indexOf(":");
    return i < 0 ? { file: undefined, name: n }
                 : { file: n.slice(0, i), name: n.slice(i + 1) };
  });
  const body = parts.map((p) => one(p.name, p.file)).join("\n");
  const keys = parts.map((p) => p.name);
  return new Function(`${body}\nreturn { ${keys.join(", ")} };`)();
}

/** Load the whole page, script by script, into one sandbox.
 *
 * For the tests that are about how the pieces fit together rather than
 * what one function returns: every script runs in page order against
 * a document that answers anything, so what comes back is the page's
 * real global scope. boot.js is left out -- it opens a tab.
 *
 * Top-level `const` and `let` do not become properties of the global
 * object, so they are handed back by evaluating their names inside it.
 */
function page(...names) {
  const any = new Proxy(function () {}, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "length" ? 0 : any),
    apply: () => any, construct: () => any, set: () => true,
  });
  const ctx = {
    console: { ...console, warn: (...a) => ctx.warnings.push(a.join(" ")) },
    warnings: [],
    setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {},
    fetch: () => new Promise(() => {}),
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: any, navigator: any, location: any, requestAnimationFrame: () => 0,
    ResizeObserver: function () { return any; }, matchMedia: () => any,
    addEventListener() {}, removeEventListener() {},
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const f of shipped().filter((f) => f !== "boot.js")) {
    vm.runInContext(source(f), ctx, { filename: f });
  }
  const out = vm.runInContext(`({ ${names.join(", ")} })`, ctx);
  out.warnings = ctx.warnings;
  // Anything else, evaluated inside the page's own scope.
  out.run = (code) => vm.runInContext(code, ctx);
  return out;
}

module.exports = { lift, one, source, shipped, whereIs, page };
