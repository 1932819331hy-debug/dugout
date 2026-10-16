// Next's static export writes segment-prefetch files as `__next.club/$d$slug/__PAGE__.txt`, but the router
// requests `__next.club.$d$slug.__PAGE__.txt`, so every prefetch 404s on a plain static host. Write the dotted
// copies next to the nested ones.
import { copyFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = fileURLToPath(new URL("../out/", import.meta.url));

function files(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p).map((f) => join(n, f)) : [n];
  });
}

let n = 0;
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (!statSync(p).isDirectory()) continue;
    if (name.startsWith("__next.")) {
      for (const f of files(p)) {
        copyFileSync(join(p, f), join(dir, [name, ...f.split(/[\\/]/)].join(".")));
        n++;
      }
    } else {
      walk(p);
    }
  }
})(OUT);
console.log(`flatten-prefetch: ${n} file(s)`);
