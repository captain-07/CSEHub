import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname, resolve, relative } from 'node:path';

const root = 'frontend/js';

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : (p.endsWith('.js') ? [p] : []);
  });
}

const files = walk(root);
const exportsOf = new Map();
const importSites = [];

for (const file of files) {
  const src = readFileSync(file, 'utf8');
  const names = new Set();

  for (const m of src.matchAll(/export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z0-9_$]+)/g)) names.add(m[1]);
  for (const m of src.matchAll(/export\s*\{([^}]+)\}/g)) {
    m[1].split(',').forEach((n) => names.add(n.trim().split(/\s+as\s+/).pop().trim()));
  }
  exportsOf.set(resolve(file), names);

  for (const m of src.matchAll(/import\s+(?:([A-Za-z0-9_$]+)\s*,\s*)?(?:\{([^}]*)\}|\*\s+as\s+([A-Za-z0-9_$]+)|([A-Za-z0-9_$]+))\s+from\s+['"]([^'"]+)['"]/g)) {
    const [, def, named, , defaultName, spec] = m;
    if (!spec.startsWith('.')) continue;
    const target = resolve(dirname(file), spec);
    const wanted = [];
    if (defaultName) wanted.push('default');
    if (def) wanted.push(def);
    if (named) named.split(',').map((s) => s.trim()).filter(Boolean).forEach((s) => wanted.push(s.split(/\s+as\s+/)[0].trim()));
    importSites.push({ file, target, wanted, spec });
  }
}

let problems = 0;
for (const { file, target, wanted, spec } of importSites) {
  if (!exportsOf.has(target)) {
    console.log(`MISSING MODULE  ${relative('.', file)} -> ${spec}`);
    problems++;
    continue;
  }
  for (const name of wanted) {
    if (!exportsOf.get(target).has(name)) {
      console.log(`MISSING EXPORT  ${relative('.', file)} imports { ${name} } from ${spec}`);
      problems++;
    }
  }
}
console.log(problems === 0 ? 'All imports resolve.' : `${problems} problem(s).`);

// Duplicate top-level declarations within a file
for (const file of files) {
  const src = readFileSync(file, 'utf8');
  const seen = new Map();
  for (const m of src.matchAll(/^(?:export\s+)?(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z0-9_$]+)/gm)) {
    seen.set(m[1], (seen.get(m[1]) || 0) + 1);
  }
  for (const [name, n] of seen) if (n > 1) console.log(`DUPLICATE DECL ${file}: ${name} x${n}`);
}
