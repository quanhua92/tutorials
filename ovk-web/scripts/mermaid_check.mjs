// mermaid_check.mjs — extract every ```mermaid block from all .md files and
// validate it renders with @mermaid-js/mermaid-cli (mmdc). SKILL.md §15.1.
// Usage: node scripts/mermaid_check.mjs [globroot]
import { readdirSync, readFileSync, writeFileSync, unlinkSync, existsSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve, sep } from "node:path";

const root = resolve(process.cwd(), process.argv[2] || ".");
const tmp = join(root, ".mmdtmp");
if (existsSync(tmp)) { try { for (const f of readdirSync(tmp)) unlinkSync(join(tmp, f)); } catch {} }
mkdirSync(tmp, { recursive: true });

function walk(dir, acc) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name === "dist" || e.name === ".mmdtmp") continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else if (e.name.endsWith(".md")) acc.push(p);
  }
  return acc;
}
const mds = walk(root, []).sort();

const RE = /```mermaid\n([\s\S]*?)```/g;
let total = 0, failed = 0;
for (const md of mds) {
  const text = readFileSync(md, "utf8");
  let m, i = 0;
  while ((m = RE.exec(text)) !== null) {
    i++; total++;
    const id = `${md.split(sep).slice(-2).join("_")}_${i}`.replace(/[^A-Za-z0-9_.-]/g, "_");
    const mmd = join(tmp, `${id}.mmd`);
    const svg = join(tmp, `${id}.svg`);
    writeFileSync(mmd, m[1]);
    try {
      execFileSync("npx", ["-y", "mmdc", "-i", mmd, "-o", svg], { stdio: "ignore" });
      if (!existsSync(svg)) throw new Error("no svg output");
    } catch (e) {
      failed++;
      console.log(`  FAIL: ${md} block#${i} — ${e.message}`);
    }
  }
}
console.log(`mermaid: ${total - failed}/${total} blocks render`);
process.exit(failed > 0 ? 1 : 0);
