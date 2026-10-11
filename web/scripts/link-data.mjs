// Link public/library → ../../data/library so `next dev` serves the static
// library export (scripts/export_library.py) at /library.
import { existsSync, lstatSync, mkdirSync, symlinkSync, unlinkSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const target = resolve(web, "../data/library");
const link = join(web, "public/library");

if (!existsSync(join(target, "index.json"))) {
  console.error(
    `No library export at ${target}.\nRun \`uv run python -m scripts.export_library\` from the repo root first.`,
  );
  process.exit(1);
}

try {
  if (lstatSync(link).isSymbolicLink()) unlinkSync(link);
  else {
    console.error(`${link} exists and is not a symlink; remove it first.`);
    process.exit(1);
  }
} catch (err) {
  if (err.code !== "ENOENT") throw err;
}

mkdirSync(dirname(link), { recursive: true });
symlinkSync(relative(dirname(link), target), link, "dir");
console.log(`Linked ${relative(web, link)} → ${relative(web, target)}`);
