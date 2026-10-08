/**
 * Regression checks for the admin editor's tool registry.
 *
 * Covers two failures this file exists for:
 *   1. `@editorjs/code` exports `CodeTool`, not `Code`, and admin.js checked for
 *      `window.Code`; `@editorjs/list` exports `List` for the pinned 1.x build.
 *      Both tools were skipped silently, their blocks rendered as `ce-stub`
 *      placeholders, and Editor.js dropped them on save.
 *   2. list 2.x (global `EditorjsList`) needs Editor.js 2.31+ and uses the stored
 *      item shape `items: [{ content }]`; the 1.x line renders that shape as
 *      `[object Object]` and rewrites it that way on save. The registry pins the
 *      global so the version and the expectation cannot drift apart.
 *
 * Dependency-free Node, like .check-imports.mjs and .check-assets.mjs — these
 * modules touch no DOM at import time precisely so this can run.
 *
 * Run: node .check-editor-tools.mjs
 */

import { readFileSync } from 'node:fs';

import {
  EDITOR_TOOLS,
  SUPPORTED_BLOCK_TYPES,
  BUILT_IN_BLOCK_TYPES,
  resolveEditorTools,
  registryCoversSupportedBlockTypes,
  documentBlockTypes,
  unsupportedBlockTypes,
  assertDocumentIsEditable,
  UnsupportedBlocksError,
} from './frontend/js/editor-tools/registry.js';

import { CodeBlockTool, 
  DEFAULT_CODE_LANGUAGE,
  normalizeCodeBlockData,
  codeLanguageOptions,
} from './frontend/js/editor-tools/code-block.js';

import { LinkBlockTool, normalizeLinkBlockData } from './frontend/js/editor-tools/link-block.js';

import {
  ListBlockTool, normalizeListBlockData, toLegacyListData, fromLegacyListData,
} from './frontend/js/editor-tools/list-block.js';



import { renderArticleContent } from './frontend/js/renderer.js';

let failures = 0;

function check(label, condition, detail = '') {
  if (condition) {
    console.log(`  ok    ${label}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

const SUPPORTED_IN_BACKEND = (() => {
  const source = readFileSync('backend/apps/articles/models.py', 'utf8');
  const block = source.match(/SUPPORTED_BLOCK_TYPES\s*=\s*\(([^)]*)\)/s);
  if (!block) return null;
  return [...block[1].matchAll(/'([^']+)'/g)].map((match) => match[1]);
})();

section('registry <-> backend allow-list');
check('SUPPORTED_BLOCK_TYPES was parsed from models.py', SUPPORTED_IN_BACKEND !== null);
check(
  'frontend allow-list matches SUPPORTED_BLOCK_TYPES in models.py',
  SUPPORTED_IN_BACKEND !== null
    && SUPPORTED_IN_BACKEND.length === SUPPORTED_BLOCK_TYPES.length
    && SUPPORTED_IN_BACKEND.every((type, index) => type === SUPPORTED_BLOCK_TYPES[index]),
  `backend=${JSON.stringify(SUPPORTED_IN_BACKEND)} frontend=${JSON.stringify(SUPPORTED_BLOCK_TYPES)}`,
);
check('every supported block type has a tool or is built in', registryCoversSupportedBlockTypes());
check(
  'the registry defines no block type outside the allow-list',
  EDITOR_TOOLS.every((tool) => SUPPORTED_BLOCK_TYPES.includes(tool.blockType)),
);

section('tool registration is derived, not declared');
// Pinned so a dependency bump cannot quietly change which global is expected:
// `@editorjs/code` -> CodeTool, and `@editorjs/list` is held on the 2.x line
// (global `EditorjsList`) because that is the line using `items: [{ content }]`.
const EXPECTED_GLOBALS = {
  header: 'Header',
  list: 'List',
  quote: 'Quote',
  image: 'ImageTool',
  delimiter: 'Delimiter',
};
for (const [blockType, expected] of Object.entries(EXPECTED_GLOBALS)) {
  const tool = EDITOR_TOOLS.find((entry) => entry.blockType === blockType);
  check(`${blockType} expects window.${expected}`, tool?.globalName === expected, `got ${tool?.globalName}`);
}
check('code and linkTool are local tools with no CDN global',
  ['code', 'linkTool'].every((blockType) => {
    const tool = EDITOR_TOOLS.find((entry) => entry.blockType === blockType);
    return tool?.source === 'local' && tool?.globalName === null;
  }));

// Under Node there is no `window`, so every CDN tool must be reported missing
// while the two local tools stay available. A hard-coded list could not do this.
const resolved = resolveEditorTools();
check(
  'CDN tools are reported unavailable when their globals are absent',
  resolved.missing.length === EDITOR_TOOLS.filter((tool) => tool.source === 'cdn').length,
  `missing=${resolved.missing.map((tool) => tool.blockType).join(',')}`,
);
check(
  'every reported tool names the global it expected',
  resolved.missing.every((tool) => tool.source === 'cdn' && typeof tool.globalName === 'string'),
);
check(
  'unavailable tools are excluded from the Editor.js tool map',
  Object.keys(resolved.tools).length === EDITOR_TOOLS.length - resolved.missing.length,
);
check(
  'unavailable block types are excluded from `available`',
  resolved.missing.every((tool) => !resolved.available.has(tool.blockType)),
);
check('built-in paragraph is always available', resolved.available.has('paragraph'));
check(
  'local tools are available without any CDN script',
  resolved.available.has('code') && resolved.available.has('linkTool'),
);
check(
  'local tools expose an Editor.js class',
  typeof CodeBlockTool === 'function' && typeof LinkBlockTool === 'function',
);

section('availability is compared against the stored document');
const FULL_DOCUMENT = {
  time: 0,
  version: '2.30.8',
  blocks: [
    { type: 'header', data: { text: 'Section', level: 2 } },
    { type: 'paragraph', data: { text: 'Body' } },
    { type: 'list', data: { style: 'unordered', items: [{ content: 'One' }] } },
    { type: 'quote', data: { text: 'Quoted', caption: 'Someone' } },
    { type: 'code', data: { code: "print('hello')", language: 'python' } },
    { type: 'image', data: { file: { url: 'https://example.com/a.png' }, caption: 'Fig' } },
    { type: 'delimiter', data: {} },
    { type: 'linkTool', data: { url: 'https://example.com', text: 'Link' } },
  ],
};
const EVERYTHING = new Set([...BUILT_IN_BLOCK_TYPES, ...SUPPORTED_BLOCK_TYPES]);

check(
  'documentBlockTypes finds every type in a full document',
  documentBlockTypes(FULL_DOCUMENT).length === SUPPORTED_BLOCK_TYPES.length,
  documentBlockTypes(FULL_DOCUMENT).join(','),
);
check('documentBlockTypes tolerates junk', documentBlockTypes(null).length === 0
  && documentBlockTypes({}).length === 0
  && documentBlockTypes({ blocks: 'no' }).length === 0);
check('a fully supported document passes the guard', assertDocumentIsEditable(FULL_DOCUMENT, EVERYTHING) === true);
check('an empty document passes the guard', assertDocumentIsEditable({ blocks: [] }, EVERYTHING) === true);

section('save safety: an unavailable tool can never silently drop a block');
// This is the exact scenario: the code and list tools failed to load, but the
// stored article contains both. Editor.js would drop them from save() output.
const partial = new Set(['paragraph', 'header', 'quote', 'delimiter', 'image']);
check('unsupported types are detected',
  unsupportedBlockTypes(FULL_DOCUMENT, partial).join(',') === 'code,linkTool,list',
  unsupportedBlockTypes(FULL_DOCUMENT, partial).join(','));

let thrown = null;
try {
  assertDocumentIsEditable(FULL_DOCUMENT, partial);
} catch (error) {
  thrown = error;
}
check('the guard throws instead of allowing a lossy save', thrown instanceof UnsupportedBlocksError);
check('the error names every offending block type',
  thrown instanceof UnsupportedBlocksError && thrown.blockTypes.join(',') === 'code,linkTool,list',
  thrown?.blockTypes?.join(','));
check('the error message is readable', /Cannot save this article safely/.test(thrown?.message || ''));

// The regression itself: a block type nobody registered must never pass silently.
const unknown = { blocks: [{ type: 'someFutureTool', data: {} }] };
check('an unknown block type is refused, not ignored',
  unsupportedBlockTypes(unknown, EVERYTHING).join(',') === 'someFutureTool');
check('a Set and an array of available types behave the same',
  unsupportedBlockTypes(unknown, ['paragraph', 'header']).join(',') === 'someFutureTool');

section('code block round trip preserves the stored schema');
const python = { code: "def hello():\n    print('hello')", language: 'python' };
check('code and language are both preserved', (() => {
  const normalized = normalizeCodeBlockData(python);
  return normalized.code === python.code && normalized.language === 'python';
})());
check('a legacy block with only `code` falls back without corrupting it',
  normalizeCodeBlockData({ code: 'x = 1' }).language === DEFAULT_CODE_LANGUAGE);
check('a block with no data at all still normalises',
  normalizeCodeBlockData(undefined).code === '' && normalizeCodeBlockData(null).language === DEFAULT_CODE_LANGUAGE);
check('a blank language is treated as absent', normalizeCodeBlockData({ code: 'a', language: '   ' }).language === DEFAULT_CODE_LANGUAGE);
check('an unrecognised language is offered rather than replaced',
  codeLanguageOptions('brainfuck').some((option) => option.value === 'brainfuck'));
check('a recognised language is not duplicated',
  codeLanguageOptions('python').filter((option) => option.value === 'python').length === 1);
check('the default language is selectable',
  codeLanguageOptions(DEFAULT_CODE_LANGUAGE).some((option) => option.value === DEFAULT_CODE_LANGUAGE));

const tool = new CodeBlockTool({ data: python });
check('a constructed tool keeps the stored code', tool.normalized.code === python.code);
check('a constructed tool keeps the stored language', tool.normalized.language === 'python');
check('unexpected keys on the block survive a save',
  new CodeBlockTool({ data: { ...python, caption: 'keep me' } }).save().caption === 'keep me');
check('save returns exactly code and language plus carried-over keys',
  Object.keys(new CodeBlockTool({ data: python }).save()).sort().join(',') === 'code,language');

section('list block round trip preserves the stored item shape');
const storedList = { style: 'unordered', items: [{ content: 'bullet one' }, { content: 'bullet two' }] };
const legacy = toLegacyListData(storedList);
check('items are flattened for list 1.x', legacy.items.join(',') === 'bullet one,bullet two', JSON.stringify(legacy));
check('style is carried through', legacy.style === 'unordered');
check('the stored shape survives a load/save cycle',
  JSON.stringify(fromLegacyListData(legacy, storedList)) === JSON.stringify(storedList),
  JSON.stringify(fromLegacyListData(legacy, storedList)));
check('a legacy items: string[] block converts to { content } objects',
  JSON.stringify(fromLegacyListData({ style: 'ordered', items: ['x'] }, null))
    === JSON.stringify({ style: 'ordered', items: [{ content: 'x' }] }));
check('normalizeListBlockData reads both item shapes',
  normalizeListBlockData({ items: ['a', { content: 'b' }] }).items.map((i) => i.content).join(',') === 'a,b');
check('per-item extras are preserved across a cycle', (() => {
  const nested = { style: 'unordered', items: [{ content: 'a', items: [{ content: 'nested' }] }] };
  return fromLegacyListData(toLegacyListData(nested), nested).items[0].items.length === 1;
})());
const ordered = { style: 'ordered', items: [{ content: 'first' }, { content: 'second' }] };
check('an ordered stored block stays ordered when the editor does not change it',
  fromLegacyListData(toLegacyListData(ordered), ordered).style === 'ordered');
check("the editor's current style wins over the stored one (so a toggle survives)",
  fromLegacyListData({ style: 'ordered', items: ['a'] }, { style: 'unordered', items: [{ content: 'a' }] }).style === 'ordered');

section('renderer compatibility (frontend/js/renderer.js)');
const renderedCode = renderArticleContent({
  blocks: [{ type: 'code', data: { code: "print('hello')", language: 'python' } }],
});
check('a code block renders as a snippet', /class="snippet"/.test(renderedCode));
check('the stored language reaches .snippet-lang', /class="snippet-lang">python</.test(renderedCode),
  renderedCode.match(/snippet-lang">([^<]*)</)?.[1]);
check('the code is escaped, not injected', /print\(&#039;hello&#039;\)|print\('hello'\)/.test(renderedCode));

// What the code tool saves is exactly what the renderer reads.
const toolSaved = new CodeBlockTool({ data: { code: "print('hello')", language: 'python' } }).save();
const toolRendered = renderArticleContent({ blocks: [{ type: 'code', data: toolSaved }] });
check('the code tool output renders the same as the stored block', toolRendered === renderedCode);

check('a code block with no language falls back to the existing "code" label',
  /class="snippet-lang">code</.test(renderArticleContent({ blocks: [{ type: 'code', data: { code: 'x' } }] })));

const renderedList = renderArticleContent({ blocks: [{ type: 'list', data: storedList }] });
check('a stored list renders as <ul> with its items',
  /<ul class="article-list">/.test(renderedList) && /<li>bullet one<\/li>/.test(renderedList)
    && /<li>bullet two<\/li>/.test(renderedList), renderedList);
// The list adapter's output must render identically to what is stored.
const adapterSaved = fromLegacyListData(toLegacyListData(storedList), storedList);
check('the list adapter output renders the same as the stored block',
  renderArticleContent({ blocks: [{ type: 'list', data: adapterSaved }] }) === renderedList);

check('a list tool that cannot load throws a clear error rather than failing silently', (() => {
  try { new ListBlockTool({ data: storedList }); return 'constructed'; } catch (error) { return /did not load/.test(error.message); }
})());

section('link block round trip');
check('url and text are preserved',
  (() => { const n = normalizeLinkBlockData({ url: 'https://example.com', text: 'Link' }); return n.url === 'https://example.com' && n.text === 'Link'; })());
check('missing text falls back to the url, matching the renderer',
  normalizeLinkBlockData({ url: 'https://example.com' }).text === 'https://example.com');
check('a bare url string does not throw', normalizeLinkBlockData('https://example.com').url === '');

console.log(failures === 0 ? '\nEditor tool registry: all checks passed.' : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
