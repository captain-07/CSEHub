/**
 * Regression checks for the optional article video.
 *
 * `Article.video_url` is editor-supplied, so the reader must never hand it to an
 * iframe. `videoEmbed` allow-lists the host, reads a video id out of the URL, and
 * rebuilds the embed source from that id; anything else degrades to a plain link.
 * This file pins that, plus the property that the rendered frame carries the
 * derived URL rather than the stored one.
 *
 * A regression here is a security bug rather than a cosmetic one: framing the
 * stored string would let any page render inside an article.
 *
 * Dependency-free Node, like .check-imports.mjs and .check-assets.mjs — these
 * modules touch no DOM at import time precisely so this can run.
 *
 * Run: node .check-video-embed.mjs
 */

import { videoEmbed, videoMarkup } from './frontend/js/renderer.js';

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
      && !markup.includes('<iframe'),
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

section('an embeddable URL renders the player itself');

const player = videoMarkup('https://youtu.be/dQw4w9WgXcQ', { title: 'Graphs' });
check('the frame is rendered directly, with no button to press', player.includes('<iframe') && !player.includes('<button'));
check('the frame source is the derived embed URL', player.includes(`src="${YOUTUBE_EMBED}"`));
check('the stored URL is not rendered back into the panel', !player.includes('youtu.be/dQw4w9WgXcQ'));
check('the frame is titled for assistive tech', player.includes('title="Graphs"'));
check('the frame does not block the article on load', player.includes('loading="lazy"'));

const vimeoPlayer = videoMarkup('https://vimeo.com/123456789');
check('Vimeo resolves to the derived player URL', vimeoPlayer.includes(`src="${VIMEO_EMBED}"`));

console.log(failures === 0 ? '\nVideo embed: all checks passed.' : `\n${failures} check(s) FAILED.`);
process.exit(failures === 0 ? 0 : 1);
