/**
 * Regression checks for the assistant's reply rendering.
 *
 * The model answers in light markdown — fenced code, inline code, emphasis,
 * lists — and printing that verbatim leaves the code answers unreadable.
 * `renderAssistantMarkup` turns exactly those constructs into elements; the
 * reply is escaped *before* any of them are applied, and only the tags the
 * renderer builds survive. This file pins both halves of that: the markup
 * renders, and nothing a reply contains can become an element or an attribute.
 *
 * Dependency-free Node, like the other .check-*.mjs scripts — renderer.js
 * touches no DOM at import time precisely so this can run.
 *
 * Run: node .check-chat-markup.mjs
 */

// renderer.js validates a link against `window.location.origin`, so the Node
// process needs one before the module is imported — hence the dynamic import.
globalThis.window = { location: { origin: 'https://csehub.example' } };
const { renderAssistantMarkup } = await import('./frontend/js/renderer.js');

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

section('code answers render as code, not as punctuation');

const fenced = renderAssistantMarkup('Example:\n\n```python\nprint("hi")\n```\n\nDone.');
check('a fence becomes a <pre><code> block', fenced.includes('<pre><code'));
check('the fence markers are gone', !fenced.includes('```'));
check('the code is preserved verbatim', fenced.includes('print(&quot;hi&quot;)'));
check('the language becomes a class', fenced.includes('class="language-python"'));
check('prose on both sides is kept', fenced.includes('<p>Example:</p>') && fenced.includes('<p>Done.</p>'));

check('an unterminated fence still opens a block', renderAssistantMarkup('```\nx = 1').includes('<pre><code'));
check('a fence-less reply gets no <pre>', !renderAssistantMarkup('just words').includes('<pre>'));
check('an empty fence renders nothing', (() => {
  const rendered = renderAssistantMarkup('before\n```\n```\nafter');
  return !rendered.includes('<pre>') && rendered.includes('before') && rendered.includes('after');
})());

section('inline constructs become elements');

const inline = renderAssistantMarkup('Use `len()` for size and **mind the edges**.');
check('inline backticks become <code>', inline.includes('<code>len()</code>'));
check('double asterisks become <strong>', inline.includes('<strong>mind the edges</strong>'));
check('the backticks and asterisks are consumed', !inline.includes('`') && !inline.includes('*'));

const emphasis = renderAssistantMarkup('The *amortised* cost is low.');
check('single asterisks become <em>', emphasis.includes('<em>amortised</em>'));

// Emphasis must not fire on ordinary arithmetic or on bullet markers.
check(
  'multiplication is left alone',
  renderAssistantMarkup('2 * 3 * 4 is 24').includes('2 * 3 * 4'),
);
check(
  'a bullet is a list, not emphasis',
  renderAssistantMarkup('- first\n- second').includes('<ul><li>first</li><li>second</li></ul>'),
);
check(
  'numbered items become an <ol>',
  renderAssistantMarkup('1. one\n2. two').includes('<ol><li>one</li><li>two</li></ol>'),
);
check(
  'a switch from bullets to numbers closes the list',
  renderAssistantMarkup('- a\n1. b').includes('</ul><ol>'),
);

section('headings do not become real heading levels');

const heading = renderAssistantMarkup('## Big point\nBody.');
check('a heading renders as bold text', heading.includes('<strong>Big point</strong>'));
check('no heading element is produced', !/<h[1-6]/.test(heading));

section('links are rebuilt, never trusted');

const link = renderAssistantMarkup('See [the docs](https://example.com/docs).');
check('a safe link becomes an anchor', link.includes('<a href="https://example.com/docs"'));
check('the anchor is hardened for a new tab', link.includes('rel="noopener noreferrer nofollow"'));

const unsafeLink = renderAssistantMarkup('See [click](javascript:alert(1)).');
check('a javascript: link stays text', !unsafeLink.includes('<a ') && unsafeLink.includes('javascript:alert(1)'));

section('a reply can never inject markup');

const attacks = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '<iframe src="https://evil.example"></iframe>',
  '<a href="https://evil.example" style="position:fixed">x</a>',
  '```html\n<svg onload=alert(1)>\n```',
  '**<b onclick="alert(1)">bold</b>**',
];

for (const attack of attacks) {
  const rendered = renderAssistantMarkup(attack);
  const injected = /<(script|img|iframe|svg|a[\s>]|b[\s>]|video|object|embed|style|link|meta)\b/i.test(rendered);
  check(`${JSON.stringify(attack)} cannot inject`, !injected, `got ${rendered}`);
}

section('line breaks and the null sentinel survive');

const breaks = renderAssistantMarkup('line one\nline two');
check('soft line breaks become <br />', breaks.includes('line one<br />line two'));
check('no sentinel bytes leak out', !breaks.includes('\u0000'));

const tricky = renderAssistantMarkup('a `code` b `code2` c');
check('two code spans both render', tricky.includes('<code>code</code>') && tricky.includes('<code>code2</code>'));
check('the text between code spans is intact', tricky.includes('a <code>code</code> b <code>code2</code> c'));

section('empty input is empty output');

for (const value of ['', null, undefined]) {
  check(`${JSON.stringify(value)} → empty`, renderAssistantMarkup(value) === '');
}

console.log(failures === 0 ? '\nAssistant markup: all checks passed.' : `\n${failures} check(s) FAILED.`);
process.exitCode = failures === 0 ? 0 : 1;
