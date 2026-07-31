// Compile every component template with the vendored Vue compiler.
//
// A template with a typo does not throw at load time - Vue logs to the console and
// renders nothing, so the tab just goes blank. This turns that into a build-time
// failure with a line number.
//
//     node webui/check_templates.mjs
//
// The modules are imported for real, so an import typo or a missing export fails
// here too. That means the browser globals they touch at import time have to exist;
// the stubs below are the minimum to get through api.js's initToken().
import { readdirSync } from "node:fs";
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const UI = dirname(fileURLToPath(import.meta.url));
const VUE = pathToFileURL(join(UI, "vendor/vue.esm-browser.prod.js")).href;

// The modules import a bare "vue", which the browser resolves through the importmap
// in index.html. Node has no importmap, so teach its resolver the same single entry.
// Inlined as a data: URL because a loader hook has to be its own module, and a
// second file for four lines is not worth it.
register("data:text/javascript," + encodeURIComponent(`
  export function resolve(specifier, context, next) {
    if (specifier === "vue") return { url: ${JSON.stringify(VUE)}, shortCircuit: true };
    return next(specifier, context);
  }
`));

// The esm-browser Vue build reaches for the DOM while it is still evaluating (it
// builds a scratch element to sniff feature support), so a bare `{}` is not enough -
// it fails with "document.createElement is not a function" before exporting anything.
const stubEl = () => ({
  style: {}, classList: { add() {}, remove() {} }, innerHTML: "", textContent: "",
  setAttribute() {}, getAttribute: () => null, removeAttribute() {},
  appendChild() {}, removeChild() {}, insertBefore() {},
  addEventListener() {}, removeEventListener() {},
});

globalThis.window = { location: { href: "http://localhost/" }, addEventListener() {} };
globalThis.location = { href: "http://localhost/", hash: "" };
globalThis.history = { replaceState() {} };
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
// app.js only mounts when querySelector returns something, so returning null keeps
// the import side-effect-free while still exercising the module top to bottom.
globalThis.document = {
  querySelector: () => null,
  createElement: stubEl, createElementNS: stubEl,
  createTextNode: stubEl, createComment: stubEl,
  addEventListener() {}, body: stubEl(),
};

const { compile } = await import(VUE);

// Vue's default entity decoder is DOM-backed: for an attribute it assigns to
// `decoder.innerHTML` and then reads `decoder.children[0].getAttribute(...)`. Against
// a stub element that path throws, and the compiler reports it as a template error -
// a convincing false positive on templates that are perfectly fine (it fired on
// mail.js, which nobody had touched). Entities are not what this check is for, so
// hand the compiler a decoder that does not need a DOM.
const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " " };
const decodeEntities = (raw) => raw.replace(/&[a-z#0-9]+;/gi, (m) => ENTITIES[m] ?? m);

// A compiler error's `message` is often just a docs URL, which does not say WHERE.
// The location is on the error, so print the offending line with it.
function where(e, tpl) {
  const line = e.loc && e.loc.start && e.loc.start.line;
  if (!line) return e.message;
  const src = (tpl.split("\n")[line - 1] || "").trim();
  return `${e.message}\n        line ${line}: ${src.slice(0, 120)}`;
}

const files = ["app.js", ...readdirSync(join(UI, "views")).map((f) => join("views", f))]
  .filter((f) => f.endsWith(".js"));

let checked = 0;
const failures = [];

for (const file of files) {
  let mod;
  try {
    mod = await import(pathToFileURL(join(UI, file)));
  } catch (e) {
    failures.push(`${file}: import failed - ${e.message}`);
    continue;
  }
  // A module can export several components (views/_shared.js exports two), so check
  // every exported object that carries a template, not just the default.
  for (const [name, value] of Object.entries(mod)) {
    const tpl = value && typeof value === "object" ? value.template : null;
    if (typeof tpl !== "string") continue;
    try {
      // `compile` throws on a malformed template. Warnings (an unknown directive, a
      // stray attribute) do not throw, so collect them too - they are the shape of
      // bug that renders a blank panel.
      const warnings = [];
      compile(tpl, { onWarn: (w) => warnings.push(w.message), decodeEntities });
      checked++;
      for (const w of warnings) failures.push(`${file} [${name}]: ${w}`);
    } catch (e) {
      failures.push(`${file} [${name}]: ${where(e, tpl)}`);
    }
  }
}

if (failures.length) {
  for (const f of failures) console.error("FAIL " + f);
  console.error(`\n${failures.length} template problem(s)`);
  process.exit(1);
}
console.log(`webui templates ok (${checked} components, ${files.length} modules)`);
