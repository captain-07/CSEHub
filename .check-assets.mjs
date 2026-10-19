import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';

const cssFiles = readdirSync('frontend/css').filter((f) => f.endsWith('.css'));
const css = cssFiles.map((f) => readFileSync(join('frontend/css', f), 'utf8')).join('\n');

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

/** Every class name a source file declares statically, via `class="…"`. */
function classesIn(source) {
  const found = new Set();
  for (const m of source.matchAll(/class="([^"$`]*)"/g)) {
    for (const c of m[1].split(/\s+/)) {
      if (c && !c.includes('$') && !c.includes('{')) found.add(c);
    }
  }
  return found;
}

const pages = readdirSync('frontend').filter((f) => f.endsWith('.html'));

const used = new Map();
for (const f of walk('frontend/js').concat(walk('frontend').filter((p) => p.endsWith('.html')))) {
  for (const c of classesIn(readFileSync(f, 'utf8'))) {
    if (!used.has(c)) used.set(c, new Set());
    used.get(c).add(f);
  }
}

const missing = [...used.entries()].filter(([c]) => !defined.has(c) && !thirdParty.has(c));
let failures = missing.length;
if (missing.length === 0) console.log('Every statically-declared class has CSS.');
for (const [c, files] of missing) console.log(`NO CSS  .${c}  <- ${[...files].join(', ')}`);

// Asset existence. A module names assets too — `src="logo.svg"` in a template
// string breaks a page exactly as hard as a `<link>` does — so both are
// walked. Interpolated references (`src="${url}"`) hold no literal path.
const modules = walk('frontend/js');
for (const file of pages.map((p) => join('frontend', p)).concat(modules)) {
  const label = file.split('\\').join('/');
  for (const m of readFileSync(file, 'utf8').matchAll(/(?:href|src)="((?!https?:|#|mailto:)[^"]+)"/g)) {
    const ref = m[1];
    if (ref.includes('${')) continue;
    if (!existsSync(join('frontend', ref.split('?')[0]))) {
      failures += 1;
      console.log(`MISSING ASSET ${label} -> ${ref}`);
    }
  }
}

// --- Per-page stylesheet closure ------------------------------------------
// The check above only asks whether a class has a rule *somewhere*. A page can
// still use a class whose rule lives in a stylesheet it never links — article.html
// shipped without articles.css and rendered .empty-state as bare text, and
// nothing caught it.
//
// So walk each page properly: the stylesheets it links, plus the modules it
// loads. Only modules reachable from a single page are checked here; a shared
// module (renderer.js, theme.js) carries markup for several pages at once, so a
// page not loading one of its stylesheets would be reported for markup that page
// never renders. The global check above still covers those.
function moduleGraph(entry) {
  const seen = new Set();
  const queue = [entry];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file) || !existsSync(file)) continue;
    seen.add(file);
    const source = readFileSync(file, 'utf8');
    const dir = dirname(file);
    // `export … from './x.js'` re-exports are part of the graph too.
    for (const m of source.matchAll(/(?:from|import)\s*\(?\s*['"](\.[^'"]+)['"]/g)) {
      queue.push(resolve(dir, m[1]));
    }
  }
  return seen;
}

const pageData = pages.map((page) => {
  const src = readFileSync(join('frontend', page), 'utf8');
  const sheets = [...src.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g)]
    .map((m) => join('frontend', m[1]));
  const modules = [...src.matchAll(/<script[^>]+type="module"[^>]+src="([^"]+)"/g)]
    .map((m) => join('frontend', m[1]));

  const reachable = new Set();
  for (const entry of modules) for (const file of moduleGraph(entry)) reachable.add(file);
  return { page, src, sheets, reachable };
});

// How many pages load each module; 1 means the module belongs to that page alone.
const ownerCount = new Map();
for (const { reachable } of pageData) {
  for (const file of reachable) ownerCount.set(file, (ownerCount.get(file) || 0) + 1);
}

function classesDefinedIn(files) {
  const styled = new Set();
  for (const file of files) {
    if (!existsSync(file)) continue;
    const source = readFileSync(file, 'utf8');
    // A class only counts as styled when its rule actually sets something. A
    // mention in a shared transition list — `body, .empty-state, .snippet {
    // transition: … }` — is not a definition, and treating it as one is what
    // would let a page ship a component with no rules at all.
    for (const m of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const declarations = m[2].split(';').map((d) => d.trim()).filter(Boolean);
      const substantive = declarations.some((d) => {
        const property = d.split(':')[0].trim().toLowerCase().replace(/^-[a-z]+-/, '');
        return property && !property.startsWith('transition');
      });
      if (!substantive) continue;
      for (const c of m[1].matchAll(/\.([a-zA-Z][\w-]*)/g)) styled.add(c[1]);
    }
  }
  return styled;
}

let unstyled = 0;
for (const { page, src, sheets, reachable } of pageData) {
  const pageUsed = classesIn(src);
  for (const file of reachable) {
    if (ownerCount.get(file) !== 1) continue;
    for (const c of classesIn(readFileSync(file, 'utf8'))) pageUsed.add(c);
  }

  const styled = classesDefinedIn(sheets);
  for (const c of [...pageUsed].sort()) {
    if (styled.has(c) || thirdParty.has(c)) continue;
    unstyled += 1;
    failures += 1;
    console.log(`UNSTYLED CLASS  ${page}  .${c}`);
  }
}

if (unstyled === 0) console.log('Every class a page renders is defined by a stylesheet that page loads.');
console.log('Asset check complete.');
process.exitCode = failures === 0 ? 0 : 1;
