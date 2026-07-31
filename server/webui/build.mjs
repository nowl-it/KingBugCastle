// Bundle + minify the dashboard UI into dist/ with esbuild.
// The importmap indirection disappears: vue is bundled in from vendor/.
// dashboard.py serves webui/dist instead of webui/ when dist exists, so a
// stock git pull is enough on the server - no node needed there.
//
//     npm run build
import { build } from "esbuild";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const UI = dirname(fileURLToPath(import.meta.url));
const DIST = join(UI, "dist");

rmSync(DIST, { recursive: true, force: true });
mkdirSync(DIST, { recursive: true });

await build({
  entryPoints: [join(UI, "app.js")],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020"],
  outdir: DIST,
  outbase: UI,
  alias: { vue: join(UI, "vendor", "vue.esm-browser.prod.js") },
  legalComments: "none",
  logLevel: "info",
});

for (const f of ["styles.css", "favicon.svg"]) {
  cpSync(join(UI, f), join(DIST, f));
}

const src = readFileSync(join(UI, "index.html"), "utf8");
const built = src
  .replace(/  <script type="importmap">[\s\S]*?<\/script>\n/, "")
  .replace('src="/ui/app.js?v=6"', 'src="/ui/app.js?v=7"');
writeFileSync(join(DIST, "index.html"), built);

console.log(`[webui] built ${DIST}`);
