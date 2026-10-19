/**
 * WCAG contrast check for the design tokens.
 *
 * Both palettes live as `:root` custom properties in frontend/css/style.css.
 * This reads them, composites any translucent value over the surface it is
 * painted on, and asserts a minimum ratio for every foreground/background pair
 * the site actually renders.
 *
 * It exists because the dark theme flips the fills: a hardcoded `white` label,
 * or a label inherited from `--text-primary`, is readable in one theme and
 * near-invisible in the other. Nothing else in the repo would catch that — it
 * is a static property of two CSS blocks, not of any rendered page.
 *
 * Run from the repo root: `node .check-contrast.mjs`
 */
import { readFileSync } from 'node:fs';

const css = readFileSync('frontend/css/style.css', 'utf8');

/** Reads one `{ … }` block of `--token: value;` declarations. */
function readPalette(selector) {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`Token block not found: ${selector}`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  const body = css.slice(open + 1, close).replace(/\/\*[\s\S]*?\*\//g, '');

  const tokens = {};
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    // Keyed without the leading dashes, so pairs read as `accent`/`bg-primary`.
    tokens[match[1].replace(/^--/, '')] = match[2].trim();
  }
  return tokens;
}

// The dark block only re-points the tokens whose value actually changes, so it
// is merged over the light palette rather than read on its own.
const light = readPalette(':root {');
const dark = { ...light, ...readPalette(":root[data-theme='dark'] {") };

function parseColor(value, palette, seen = new Set()) {
  const text = String(value).trim();

  const reference = /^var\(\s*(--[\w-]+)\s*\)$/.exec(text);
  if (reference) {
    const name = reference[1].replace(/^--/, '');
    if (seen.has(name)) throw new Error(`Circular token reference: ${name}`);
    seen.add(name);
    if (!(name in palette)) throw new Error(`Unknown token: ${name}`);
    return parseColor(palette[name], palette, seen);
  }

  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
  if (hex) {
    const digits = hex[1].length === 3
      ? hex[1].split('').map((d) => d + d).join('')
      : hex[1];
    return {
      r: parseInt(digits.slice(0, 2), 16),
      g: parseInt(digits.slice(2, 4), 16),
      b: parseInt(digits.slice(4, 6), 16),
      a: 1,
    };
  }

  const rgb = /^rgba?\(([^)]+)\)$/i.exec(text);
  if (rgb) {
    const parts = rgb[1].split(',').map((part) => parseFloat(part));
    if (parts.length < 3 || parts.some((part) => Number.isNaN(part))) {
      throw new Error(`Unreadable colour: ${text}`);
    }
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  }

  throw new Error(`Unsupported colour syntax: ${text}`);
}

/** Composites a translucent colour over the opaque colour behind it. */
function flatten(color, backdrop) {
  if (color.a >= 1) return { r: color.r, g: color.g, b: color.b, a: 1 };
  const over = (front, back) => front * color.a + back * (1 - color.a);
  return { r: over(color.r, backdrop.r), g: over(color.g, backdrop.g), b: over(color.b, backdrop.b), a: 1 };
}

const channel = (value) => {
  const scaled = value / 255;
  return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
};

const luminance = ({ r, g, b }) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);

function contrast(fg, bg) {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

/*
 * Every pair below is one the site actually renders. `base` is the opaque
 * surface behind a translucent background (dark-mode `--accent-soft` is 14%
 * green, so its real colour depends on what it sits on).
 */
const PAIRS = [
  ['text-primary', 'bg-primary', 4.5, 'body text'],
  ['text-secondary', 'bg-primary', 4.5, 'secondary text on the page'],
  ['text-secondary', 'bg-secondary', 4.5, 'secondary text on cards / table rows'],
  ['accent', 'bg-primary', 4.5, 'links, active nav, brand'],
  ['accent', 'bg-secondary', 4.5, 'accent text on cards'],
  ['on-accent', 'accent', 4.5, 'primary button, skip link, brand mark, user bubble'],
  ['on-accent', 'accent-hover', 4.5, 'primary button on hover'],
  ['on-error', 'error', 4.5, 'danger button'],
  ['google-btn-text', 'google-btn-bg', 4.5, 'Google sign-in label'],
  ['google-btn-text', 'google-btn-bg-hover', 4.5, 'Google sign-in label on hover'],
  ['error', 'error-soft', 4.5, 'error alert / inline error'],
  ['success', 'success-soft', 4.5, 'success alert / published badge'],
  ['warning', 'warning-soft', 4.5, 'draft badge'],
  ['success', 'bg-secondary', 4.5, 'published status in a table'],
  ['error', 'bg-primary', 4.5, 'reaction error text'],
  ['accent-strong', 'accent-soft', 4.5, 'optional-field chip', 'bg-secondary'],
  ['accent', 'accent-soft', 4.5, 'badge / avatar initials', 'bg-secondary'],
  ['text-secondary', 'accent-soft', 4.5, 'chat header strap line', 'bg-secondary'],
  ['code-text', 'code-bg', 4.5, 'code surfaces'],
];

let failures = 0;
for (const [theme, palette] of [['light', light], ['dark', dark]]) {
  for (const [fgToken, bgToken, min, label, baseToken = 'bg-primary'] of PAIRS) {
    const base = parseColor(palette[baseToken], palette);
    const background = flatten(parseColor(palette[bgToken], palette), base);
    const foreground = flatten(parseColor(palette[fgToken], palette), background);
    const value = contrast(foreground, background);
    const ok = value >= min;
    if (!ok) failures += 1;
    console.log(
      `${ok ? 'ok  ' : 'FAIL'} ${theme.padEnd(5)} ${value.toFixed(2).padStart(5)}:1  `
      + `(min ${min})  ${fgToken} on ${bgToken}  — ${label}`,
    );
  }
}

console.log(failures === 0
  ? 'Contrast check complete — every pair meets its minimum.'
  : `Contrast check complete — ${failures} pair(s) below the minimum.`);
process.exitCode = failures === 0 ? 0 : 1;
