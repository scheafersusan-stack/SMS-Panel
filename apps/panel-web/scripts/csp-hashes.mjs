// Post-build: collect the sha256 of every inline <script> that `next build` emitted into dist/
// (flight data, bootstrap) and write a Caddy snippet that sets the Content-Security-Policy.
// Output: .csp/csp.caddy (git-ignored), imported by infra/Caddyfile. Rerun on every build.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const DIST = "dist";
const OUT = ".csp";

function* htmlFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) yield* htmlFiles(p);
    else if (entry.name.endsWith(".html")) yield p;
  }
}

const hashes = new Set();
for (const file of htmlFiles(DIST)) {
  const html = readFileSync(file, "utf8");
  for (const m of html.matchAll(/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
    if (m[1].trim() === "") continue;
    hashes.add(`'sha256-${createHash("sha256").update(m[1]).digest("base64")}'`);
  }
}

const policy = [
  "default-src 'self'",
  `script-src 'self' ${[...hashes].sort().join(" ")}`.trimEnd(),
  // Static HTML carries style="" attributes (React inline styles); scripts stay hash-locked.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, "csp.caddy"), `header Content-Security-Policy "${policy}"\n`);
console.log(`csp: ${hashes.size} inline script hash(es) -> ${join(OUT, "csp.caddy")}`);
