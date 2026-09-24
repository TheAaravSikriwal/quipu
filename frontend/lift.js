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

const cache = {};

function source(file) {
  if (!(file in cache)) {
    cache[file] = fs.readFileSync(path.join(__dirname, file), "utf8");
  }
  return cache[file];
}

/** The source text of one top-level `const name = ...;` or `function name`. */
function one(name, file = "app.js") {
  const src = source(file);
  const asConst = new RegExp(`^const ${name} = `, "m");
  const asFn = new RegExp(`^function ${name}\\(`, "m");
  let start = src.search(asConst);
  const isFn = start < 0;
  if (isFn) start = src.search(asFn);
  if (start < 0) throw new Error(`could not find "${name}" in ${file}`);

  // Scanned rather than matched with a regex: these have block bodies,
  // and "up to the first semicolon" stops at the first `return` inside
  // the body and lifts half a function.
  let depth = 0, str = null, sawBody = false;
  for (let i = start; i < src.length; i++) {
    const c = src[i], prev = src[i - 1];
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
      if (isFn && sawBody && depth === 0) return src.slice(start, i + 1);
    } else if (!isFn && c === ";" && depth === 0) {
      return src.slice(start, i + 1);
    }
  }
  throw new Error(`"${name}" in ${file} never ends`);
}

/** Evaluate several declarations together and hand them back.
 *
 * Names may be given as "name" (from app.js) or "file.js:name".
 */
function lift(...names) {
  const parts = names.map((n) => {
    const i = n.indexOf(":");
    return i < 0 ? { file: "app.js", name: n }
                 : { file: n.slice(0, i), name: n.slice(i + 1) };
  });
  const body = parts.map((p) => one(p.name, p.file)).join("\n");
  const keys = parts.map((p) => p.name);
  return new Function(`${body}\nreturn { ${keys.join(", ")} };`)();
}

module.exports = { lift, one, source };
