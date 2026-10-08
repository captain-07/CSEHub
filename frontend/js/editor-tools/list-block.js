/**
 * List block adapter.
 *
 * Neither published `@editorjs/list` line reads the item shape this project
 * stores, and both fail destructively rather than loudly:
 *
 *   * list 2.x expects a recursive `{ style, items: [{ content, meta, items }] }`
 *     (see its `ListData` type). Given our `{ style, items: [{ content }] }` it
 *     throws `Cannot read properties of undefined (reading 'length')` while
 *     rendering, and Editor.js degrades the block to a `ce-stub`.
 *   * list 1.x expects the older `items: string[]`. It renders our objects as
 *     `[object Object]` and rewrites them that way on save â€” silent corruption.
 *
 * So the stored schema is kept (the API allow-list, `renderer.js` and the
 * existing articles all depend on it) and list 1.x is adapted at the boundary:
 * items are flattened to strings on load and rebuilt as `{ content }` objects on
 * save. The mature list editor is reused rather than reimplemented.
 *
 * Anything else on the block â€” `style`, and per-item keys such as a nested
 * `items` array â€” is carried through untouched.
 */

/** Editor.js expects `{ content }` objects; returns the text of one item. */
export function listItemText(item) {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object' && typeof item.content === 'string') return item.content;
  return '';
}

/**
 * Reads a stored list block.
 *
 * @returns {{style: string, items: Array<{content: string}>}} the canonical shape.
 */
export function normalizeListBlockData(data) {
  const source = data && typeof data === 'object' ? data : {};
  const items = Array.isArray(source.items) ? source.items : [];
  return {
    style: source.style === 'ordered' ? 'ordered' : 'unordered',
    items: items.map((item) => ({ ...(item && typeof item === 'object' ? item : {}), content: listItemText(item) })),
  };
}

/** Converts the stored shape into the `items: string[]` that list 1.x reads. */
export function toLegacyListData(data) {
  const { style, items } = normalizeListBlockData(data);
  return { style, items: items.map((item) => item.content) };
}

/**
 * Rebuilds the stored shape from list 1.x output.
 *
 * Keys the original block carried (including per-item extras such as nested
 * `items`, and any block-level key this tool does not model) are merged back by
 * position, so opening and saving does not quietly flatten or drop them.
 */
export function fromLegacyListData(saved, original) {
  const source = saved && typeof saved === 'object' ? saved : {};
  const originalItems = normalizeListBlockData(original).items;
  const texts = Array.isArray(source.items) ? source.items : [];

  return {
    ...(original && typeof original === 'object' ? original : {}),
    style: source.style === 'ordered' ? 'ordered' : 'unordered',
    items: texts.map((text, index) => ({
      ...(originalItems[index] || {}),
      content: listItemText(text),
    })),
  };
}

/** Resolved lazily so importing this module stays free of DOM access. */
function legacyListTool() {
  const ctor = typeof window === 'undefined' ? undefined : window.List;
  if (typeof ctor !== 'function') {
    throw new Error('@editorjs/list did not load, so list blocks cannot be edited.');
  }
  return ctor;
}

export class ListBlockTool {
  static get toolbox() {
    return legacyListTool().toolbox;
  }

  static get isReadOnlySupported() {
    return legacyListTool().isReadOnlySupported !== false;
  }

  static get enableLineBreaks() {
    return legacyListTool().enableLineBreaks === true;
  }

  static get pasteConfig() {
    return legacyListTool().pasteConfig;
  }

  constructor({ data, config, api, readOnly, block } = {}) {
    this.original = data && typeof data === 'object' ? { ...data } : {};
    const Tool = legacyListTool();
    this.inner = new Tool({
      data: toLegacyListData(this.original),
      config,
      api,
      readOnly,
      block,
    });
  }

  render() {
    return this.inner.render();
  }

  save() {
    return fromLegacyListData(this.inner.save(), this.original);
  }

  renderSettings(...args) {
    return typeof this.inner.renderSettings === 'function' ? this.inner.renderSettings(...args) : [];
  }

  onPaste(...args) {
    if (typeof this.inner.onPaste === 'function') return this.inner.onPaste(...args);
    return undefined;
  }

  merge(...args) {
    if (typeof this.inner.merge === 'function') this.inner.merge(...args);
  }

  destroy() {
    if (typeof this.inner.destroy === 'function') this.inner.destroy();
  }
}
