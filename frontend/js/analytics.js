/**
 * Google Analytics 4.
 *
 * One job: load gtag.js with the measurement id from config.js.
 *
 * There are no custom events. GA4's "Enhanced measurement" already supplies
 * page views, referrers, devices, scroll depth, outbound clicks and site search,
 * so the dashboard works without any wiring here. Make sure Enhanced
 * measurement is left on for the data stream.
 *
 * An empty id is the off switch, and localhost is skipped, so local clones do
 * not pollute the property.
 */

import { CONFIG } from './config.js';

const id = String(CONFIG.GA_MEASUREMENT_ID || '').trim();
const isLocalhost = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);

if (id && !isLocalhost) {
  window.dataLayer = window.dataLayer || [];
  function gtag() {
    window.dataLayer.push(arguments);
  }
  window.gtag = gtag;

  gtag('js', new Date());
  gtag('config', id);

  const script = document.createElement('script');
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`;
  document.head.appendChild(script);
}
