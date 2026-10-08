import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const css = readdirSync('frontend/css')
  .filter((f) => f.endsWith('.css'))
  .map((f) => readFileSync(join('frontend/css', f), 'utf8'))
  .join('\n');

const defined = new Set([...css.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1]));
// Classes created at runtime by Editor.js / Supabase, not authored by us.
const thirdParty = new Set([
  'codex-editor', 'ce-block', 'ce-toolbar', 'ce-inline-toolbar', 'ce-popover', 'ce-converter',
  'ce-paragraph', 'ce-header', 'ce-list', 'ce-quote', 'ce-code', 'ce-delimiter', 'ce-toolbar-plus',
  'cdx-block', 'cdx-input', 'cdx-loader', 'ce-settings', 'ce-button', 'ce-autofocus', 'ce-inline-tool',
  'grecaptcha', 'supabase', 'hidden',
]);

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : (p.endsWith('.js') || p.endsWith('.html') ? [p] : []);
  });
}

const used = new Map();
for (const f of walk('frontend/js').concat(walk('frontend').filter((p) => p.endsWith('.html')))) {
  const src = readFileSync(f, 'utf8');
  for (const m of src.matchAll(/class="([^"$`]*)"/g)) {
    for (const c of m[1].split(/\s+/)) {
      if (c && !c.includes('$') && !c.includes('{')) {
        if (!used.has(c)) used.set(c, new Set());
        used.get(c).add(f);
      }
    }
  }
}

const missing = [...used.entries()].filter(([c]) => !defined.has(c) && !thirdParty.has(c));
if (missing.length === 0) console.log('Every statically-declared class has CSS.');
for (const [c, files] of missing) console.log(`NO CSS  .${c}  <- ${[...files].join(', ')}`);

// Asset existence per page
for (const page of readdirSync('frontend').filter((f) => f.endsWith('.html'))) {
  const src = readFileSync(join('frontend', page), 'utf8');
  for (const m of src.matchAll(/(?:href|src)="((?!https?:|#|mailto:)[^"]+)"/g)) {
    const ref = m[1].split('?')[0];
    if (!existsSync(join('frontend', ref))) console.log(`MISSING ASSET ${page} -> ${ref}`);
  }
}
console.log('Asset check complete.');
