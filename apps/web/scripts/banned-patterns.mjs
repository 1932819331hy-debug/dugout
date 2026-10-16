// Banned-pattern review for "The Dossier" brief. Fails (exit 1) if the source uses a banned design pattern.
// Banned: dark navy backgrounds, purple/blue gradients, neon glow, rounded cards with faint 1px borders,
// icon-in-a-box feature grids, centred hero + three cards, default drop shadows, Inter-only typography.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const RULES = [
  [/bg-(?:slate|blue|indigo|navy|sky)-(?:8|9)\d\d|#0[0-9a-f]1[0-9a-f]3[0-9a-f]|\bnavy\b/i, "dark navy background"],
  [/(?:bg-gradient|linear-gradient|radial-gradient)[^;"'`]*(?:purple|violet|indigo|blue|#[6-9a][0-9a-f]{2}[c-f][0-9a-f]{2})/i, "purple/blue gradient"],
  [/glow|shadow-\[0_0_|drop-shadow-\[|text-shadow:\s*0 0/i, "neon glow"],
  [/rounded(?:-\w+)?\b[^"'`]*\bborder\b[^"'`]*(?:\/10|\/20|opacity|border-gray-[12]00|border-white\/)/, "rounded card with faint border"],
  [/\bshadow(?:-sm|-md|-lg|-xl|-2xl)?\b(?!-\[)(?=[\s"'`])/, "default drop shadow"],
  [/font-family:\s*["']?Inter\b|next\/font\/google["'];?[^]*\bInter\b/, "Inter typography"],
  [/grid-cols-3[^"'`]*(?:text-center|items-center)/, "centred three-card grid"],
];

function* files(dir) {
  for (const name of readdirSync(dir)) {
    if (["node_modules", ".next", "out", "scripts"].includes(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* files(p);
    else if (/\.(tsx?|css)$/.test(name)) yield p;
  }
}

let failures = 0;
for (const f of files(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"))) {
  const text = readFileSync(f, "utf-8");
  for (const [re, name] of RULES) {
    const m = text.match(re);
    if (m) {
      failures++;
      const line = text.slice(0, m.index).split("\n").length;
      console.log(`${f}:${line}: banned pattern (${name}): ${m[0].slice(0, 60)}`);
    }
  }
}
console.log(failures ? `${failures} banned pattern(s) found` : "banned-pattern review: clean");
process.exit(failures ? 1 : 0);
