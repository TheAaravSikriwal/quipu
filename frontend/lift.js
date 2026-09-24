/* Test support: pull a declaration out of app.js and run it.
 *
 * app.js is a classic script, not a module -- it shares one global
 * scope with the other frontend files by design, and wrapping it up as
 * a module to make it testable would change the thing being tested.
 *
 * So the tests lift the declarations they need straight out of the
 * source and evaluate them. The point is that they test the code that
 * actually ships rather than a copy of it, which is the only kind of
 * copy that cannot drift.
 */

const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");

/** The source text of one top-level `const name = ...;` or `function name`. */
function one(name) {
  const asConst = new RegExp(`^const ${name} = `, "m");
  const asFn = new RegExp(`^function ${name}\\(`, "m");
  let start = SRC.search(asConst);
  const isFn = start < 0;
  if (isFn) start = SRC.search(asFn);
  if (start < 0) throw new Error(`could not find "${name}" in app.js`);

  // Scanned rather than matched with a regex: these have block bodies,
  // and "up to the first semicolon" stops at the first `return` inside
  // the body and lifts half a function.
  let depth = 0, str = null, sawBody = false;
  for (let i = start; i < SRC.length; i++) {
    const c = SRC[i], prev = SRC[i - 1];
    if (str) {
      if (c === str && prev !== "\\") str = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { str = c; continue; }
    if ("([{".includes(c)) {
      // The BODY brace, not the parameter list. Closing on depth-zero
      // alone ended a function declaration at its own `)` and lifted
      // just the signature.
      if (c === "{" && depth === 0) sawBody = true;
      depth++;
    } else if (")]}".includes(c)) {
      depth--;
      if (isFn && sawBody && depth === 0) return SRC.slice(start, i + 1);
    } else if (!isFn && c === ";" && depth === 0) {
      return SRC.slice(start, i + 1);
    }
  }
  throw new Error(`"${name}" in app.js never ends`);
}

/** Evaluate several declarations together and hand them back. */
function lift(...names) {
  const body = names.map(one).join("\n");
  return new Function(`${body}\nreturn { ${names.join(", ")} };`)();
}

module.exports = { lift, one, SRC };
