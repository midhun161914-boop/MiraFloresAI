// WCAG contrast check for the design tokens. Reads src/ui/tokens.css so the
// check can never drift from the palette. Exit 1 if any pair fails.
//   npm run check:contrast
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../src/ui/tokens.css"), "utf8");
const raw = Object.fromEntries([...css.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
const token = (name) => {
  let v = raw[name];
  for (let i = 0; v && v.startsWith("var(") && i < 5; i++) v = raw[v.slice(6, -1)];
  if (!/^#[0-9a-f]{6}$/i.test(v ?? "")) throw new Error(`token --${name} is not a hex colour (${v})`);
  return v;
};
const lin = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
const lum = (h) => { const [r, g, b] = lin(h); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// [foreground, background, minimum] — 4.5 for text, 3 for UI boundaries/icons.
const pairs = [
  ["text-primary", "bg", 4.5], ["text-primary", "bg-canvas", 4.5],
  ["text-secondary", "bg", 4.5], ["text-secondary", "bg-canvas", 4.5], ["text-secondary", "bg-muted", 4.5],
  ["text-tertiary", "bg", 4.5], ["text-tertiary", "bg-canvas", 4.5],
  ["accent-text", "bg", 4.5], ["accent-text", "accent-subtle", 4.5], ["text-inverse", "accent", 4.5],
  ["text-inverse", "bg-inverse", 4.5],
  ...["verified", "open", "warning", "error", "neutral"].map((s) => [`${s}-fg`, `${s}-bg`, 4.5]),
  ...["verified", "open", "warning", "error"].map((s) => [`${s}-fg`, "bg", 4.5]),
  ["text-primary", "highlight", 4.5],
  ["border-strong", "bg", 3], ["focus-ring", "bg", 3], ["focus-ring", "bg-canvas", 3],
];

let failed = 0;
for (const [fg, bg, min] of pairs) {
  const r = ratio(token(fg), token(bg));
  const ok = r >= min;
  if (!ok) failed++;
  console.log(`${ok ? "pass" : "FAIL"}  ${r.toFixed(2).padStart(5)} ≥ ${min}  --${fg} on --${bg}`);
}
console.log(failed ? `\n${failed} pair(s) below WCAG AA` : `\nAll ${pairs.length} pairs meet WCAG AA`);
process.exit(failed ? 1 : 0);
