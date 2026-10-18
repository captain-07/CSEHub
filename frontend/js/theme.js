/**
 * Colour-theme controller — dark mode for the site.
 *
 * Initial value is applied before first paint by a tiny inline script in every
 * page's <head> (no flash of the wrong theme); this module owns everything
 * after that: the navbar toggle, persistence, and live system-preference
 * changes.
 *
 * Storage holds only an explicit user choice. While it is absent the site
 * follows `prefers-color-scheme` and keeps following it if the OS flips.
 */

const STORAGE_KEY = 'csehub-theme';

function storedTheme() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    // Privacy modes can reject even reads — treat as "no stored choice".
    return null;
  }
}

function persistTheme(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Best effort only; the session keeps the choice until reload.
  }
}

export function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
}

function systemTheme() {
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  return media.matches ? 'dark' : 'light';
}

function toggleIconMarkup() {
  // Both icons ship in the button; navbar.css shows the one matching the active
  // theme via the [data-theme] attribute, so no re-render is needed on change.
  return `
    <svg class="theme-icon theme-icon-sun" aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
    <svg class="theme-icon theme-icon-moon" aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" />
    </svg>`;
}

/**
 * Renders and wires the toggle. Called from the navbar because every page
 * loads it; also reconciles state when system preferences change.
 */
export function initThemeToggle() {
  const header = document.querySelector('.site-header');
  if (!header) return null;

  let button = header.querySelector('.theme-toggle');
  if (!button) {
    button = document.createElement('button');
    button.type = 'button';
    button.className = 'theme-toggle';
    button.innerHTML = toggleIconMarkup();
    // Position: inside the header container, immediately after the nav — on
    // desktop it trails the account area, on mobile it stays visible beside the
    // hamburger because the nav-menu collapses to a dropdown.
    const nav = header.querySelector('nav');
    if (nav && nav.parentNode) nav.parentNode.insertBefore(button, nav.nextSibling);
    else header.appendChild(button);
  }

  const label = () => `Switch to ${currentTheme() === 'dark' ? 'light' : 'dark'} theme`;
  button.setAttribute('aria-label', label());
  button.title = label();

  button.addEventListener('click', () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    persistTheme(next);
    const text = `Switch to ${next === 'dark' ? 'light' : 'dark'} theme`;
    button.setAttribute('aria-label', text);
    button.title = text;
  });

  // No explicit choice stored → the theme keeps tracking the OS. When the user
  // has chosen, their choice wins and system flips are ignored.
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (!storedTheme()) {
      applyTheme(systemTheme());
      const text = `Switch to ${currentTheme() === 'dark' ? 'light' : 'dark'} theme`;
      button.setAttribute('aria-label', text);
      button.title = text;
    }
  });

  return button;
}
