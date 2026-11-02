// Writes roots-tokens.css (CSS custom properties) from the design system's tokens.json,
// so the store and the panel read their colors, fonts, spacing, radii and shadows from one place.
//   node tools/build-tokens.mjs store/roots-tokens.css panel/roots-tokens.css
// Netlify runs it on every deploy (see store/netlify.toml and panel/netlify.toml).
import { readFileSync, writeFileSync } from "node:fs";

const src = new URL("../design-system/project/tokens.json", import.meta.url);
const t = JSON.parse(readFileSync(src, "utf8"));
const first = t.color.themes[0].id;
const lines = [];
const add = (name, value) => { if (value != null && value !== "") lines.push(`  --${name}: ${value};`); };
const val = (tok) => (typeof tok.value === "string" ? tok.value : tok.value[first]);
const resolveAlias = (v) => v.replace(/^\{([^}]+)\}$/, "var(--$1)");

for (const tok of t.color.tokens) add(tok.name, resolveAlias(val(tok)));
for (const [key, stack] of Object.entries(t.type.families || {})) add(`font-${key}`, stack);
for (const fam of ["spacing", "radius", "shadow"]) for (const tok of (t[fam]?.tokens || [])) add(tok.name, val(tok));

const css = `/* Roots tokens · generated from design-system/project/tokens.json by tools/build-tokens.mjs.
   Don't edit this file: change tokens.json (or the Roots design system) and rebuild. */
:root {
${lines.join("\n")}
}
`;
const outs = process.argv.slice(2);
if (!outs.length) { console.error("usage: node tools/build-tokens.mjs <out.css> [more.css]"); process.exit(1); }
for (const out of outs) writeFileSync(out, css);
console.log(`roots-tokens.css: ${lines.length} tokens → ${outs.join(", ")}`);
