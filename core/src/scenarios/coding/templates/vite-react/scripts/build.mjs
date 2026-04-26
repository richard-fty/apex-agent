import { chmodSync, copyFileSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const dist = resolve("dist");
rmSync(dist, { recursive: true, force: true });
mkdirSync(resolve(dist, "src"), { recursive: true });

for (const [source, target] of [
  ["index.html", "index.html"],
  ["src/items.js", "src/items.js"],
  ["src/main.js", "src/main.js"],
  ["src/styles.css", "src/styles.css"],
]) {
  const output = resolve(dist, target);
  copyFileSync(source, output);
  chmodSync(output, 0o644);
}

console.log("Build completed.");
