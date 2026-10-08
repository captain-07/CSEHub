/**
 * Custom Editor.js block for a standalone link.
 *
 * The seeded articles contain `linkTool` blocks (`{ url, text }`, which is what
 * `renderer.js#renderLinkBlock` and the backend block-type fixture expect), but
 * no tool was ever registered for them — so they loaded as `ce-stub`
 * placeholders and would have been dropped from the document on save.
 *
 * Keeping it here rather than adding another CDN dependency means every block
 * type in `SUPPORTED_BLOCK_TYPES` now has a working editor, which is what makes
 * the save guard in `registry.js` a genuine safety net instead of a permanent
 * block on editing real articles.
 */

const TOOLBOX_ICON = `<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M8.5 11.5a3 3 0 0 0 4.24 0l2.12-2.12a3 3 0 0 0-4.24-4.24l-1.06 1.06M11.5 8.5a3 3 0 0 0-4.24 0L5.14 10.62a3 3 0 0 0 4.24 4.24l1.06-1.06" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

/** Reads a stored link block, defaulting the visible text to the URL as the renderer does. */
export function normalizeLinkBlockData(data) {
  const source = data && typeof data === 'object' ? data : {};
  const url = typeof source.url === 'string' ? source.url.trim() : '';
  const text = typeof source.text === 'string' ? source.text.trim() : '';
  return { url, text: text || url };
}

export class LinkBlockTool {
  static get toolbox() {
    return { title: 'Link', icon: TOOLBOX_ICON };
  }

  static get isReadOnlySupported() {
    return true;
  }

  constructor({ data, readOnly } = {}) {
    // Merged back on save so an unexpected stored key is never discarded.
    this.original = data && typeof data === 'object' ? { ...data } : {};
    this.normalized = normalizeLinkBlockData(this.original);
    this.readOnly = Boolean(readOnly);
  }

  render() {
    const container = document.createElement('div');
    container.className = 'cdx-block cdx-link';

    const makeField = (className, labelText, value, placeholder) => {
      const field = document.createElement('label');
      field.className = `cdx-link__field ${className}`;

      const label = document.createElement('span');
      label.className = 'cdx-link__label';
      label.textContent = labelText;

      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'cdx-link__input';
      input.value = value;
      input.placeholder = placeholder;
      input.readOnly = this.readOnly;
      input.spellcheck = false;

      field.append(label, input);
      return { field, input };
    };

    const url = makeField('cdx-link__field--url', 'URL', this.normalized.url, 'https://example.com/page');
    const text = makeField('cdx-link__field--text', 'Text', this.normalized.text, 'What the reader sees');

    this.urlInput = url.input;
    this.textInput = text.input;

    container.append(url.field, text.field);
    return container;
  }

  save() {
    return {
      ...this.original,
      url: this.urlInput ? this.urlInput.value.trim() : this.normalized.url,
      text: this.textInput ? this.textInput.value.trim() : this.normalized.text,
    };
  }

  destroy() {
    this.urlInput = null;
    this.textInput = null;
  }
}
