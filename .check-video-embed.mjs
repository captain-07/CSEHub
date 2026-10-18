/**
 * Regression checks for the optional article video.
 *
 * `Article.video_url` is editor-supplied, so the reader must never hand it to an
 * iframe. `videoEmbed` allow-lists the host, reads a video id out of the URL, and
 * rebuilds the embed source from that id; anything else degrades to a plain link.
 * This file pins that, plus the click-to-load property — the markup holds no
 * frame, and the frame created on click carries only the derived URL.
 *
 * A regression here is a security bug rather than a cosmetic one: framing the
 * stored string would let any page render inside an article.
 *
 * Dependency-free Node, like .check-imports.mjs and .check-assets.mjs — these
 * modules touch no DOM at import time precisely so this can run.
 *
 * Run: node .check-video-embed.mjs
 */

import { videoEmbed, videoMarkup, bindVideoFacades } from './frontend/js/renderer.js';

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

const YOUTUBE_EMBED = 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ';
const VIMEO_EMBED = 'https://player.vimeo.com/video/123456789';

section('a provider URL resolves to an embed source built from its id');

for (const [url, provider, src] of [
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'YouTube', YOUTUBE_EMBED],
  ['https://youtu.be/dQw4w9WgXcQ', 'YouTube', YOUTUBE_EMBED],
  ['https://www.youtube.com/embed/dQw4w9WgXcQ', 'YouTube', YOUTUBE_EMBED],
  ['https://www.youtube.com/shorts/dQw4w9WgXcQ', 'YouTube', YOUTUBE_EMBED],
  ['https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30s&list=PL1', 'YouTube', YOUTUBE_EMBED],
  ['https://vimeo.com/123456789', 'Vimeo', VIMEO_EMBED],
  ['https://player.vimeo.com/video/123456789', 'Vimeo', VIMEO_EMBED],
  ['https://vimeo.com/channels/staffpicks/123456789', 'Vimeo', VIMEO_EMBED],
]) {
  const result = videoEmbed(url);
  check(
    `${url} → ${provider}`,
    result?.provider === provider && result?.src === src,
    `got ${JSON.stringify(result)}`,
  );
}

section('anything else degrades to a link, never a frame');

for (const url of [
  'https://evil.example/watch?v=dQw4w9WgXcQ',
  // The host is compared exactly, so a provider name used as a suffix or a
  // prefix cannot borrow its allow-listing.
  'https://www.youtube.com.evil.example/watch?v=dQw4w9WgXcQ',
  'https://evil.example/www.youtube.com/watch?v=dQw4w9WgXcQ',
  // Right host, but nothing that reads as a video id.
  'https://www.youtube.com/watch?v=short',
  'https://vimeo.com/notanumber',
  'https://example.com/interesting-talk',
]) {
  const result = videoEmbed(url);
  const markup = videoMarkup(url);
  check(
    `${url} renders as a link`,
    result?.provider === null
      && result?.href === url
      && markup.includes('href=')
      && !markup.includes('data-video-src'),
    `got ${JSON.stringify(result)}`,
  );
}

section('nothing to render produces no markup at all');

for (const value of ['', '   ', null, undefined, 'javascript:alert(1)', 'data:text/html,<b>x</b>', 'not a url']) {
  check(
    `${JSON.stringify(value)} → nothing`,
    videoEmbed(value) === null && videoMarkup(value) === '',
  );
}

section('the facade holds no frame until a reader presses play');

const facade = videoMarkup('https://youtu.be/dQw4w9WgXcQ', { title: 'Graphs' });
check('the rendered markup contains no iframe', !facade.includes('<iframe'));
check('the derived source is carried as a data attribute', facade.includes(`data-video-src="${YOUTUBE_EMBED}"`));
check('the facade is a button, so it is keyboard reachable', facade.includes('<button') && facade.includes('data-video-play'));
check('the pasted URL is not rendered back into the panel', !facade.includes('youtu.be/dQw4w9WgXcQ'));
check('the panel is labelled with the title', facade.includes('data-video-title="Graphs"'));

section('the frame created on click carries the derived URL, not the stored one');

// The binder is the only place that touches a frame source, so this is where
// "never the stored string" actually has to hold.
globalThis.document = {
  createElement: (tag) => ({
    tagName: tag,
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
  }),
};

function fakePanel() {
  const handlers = [];
  const replaced = [];
  return {
    dataset: { videoSrc: YOUTUBE_EMBED, videoTitle: 'Graphs' },
    querySelector: () => ({ addEventListener: (_type, handler) => handlers.push(handler) }),
    replaceChildren: (node) => replaced.push(node),
    press: () => handlers.forEach((handler) => handler()),
    replaced,
  };
}

const panel = fakePanel();
bindVideoFacades({ querySelectorAll: () => [panel] });
check('nothing is created before the click', panel.replaced.length === 0);

panel.press();
check('one frame replaces the facade', panel.replaced.length === 1 && panel.replaced[0].tagName === 'iframe');
check('the frame source is the derived embed URL', panel.replaced[0]?.attrs.src === YOUTUBE_EMBED);
check('the frame is titled for assistive tech', Boolean(panel.replaced[0]?.attrs.title));

console.log(failures === 0 ? '\nVideo embed: all checks passed.' : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
