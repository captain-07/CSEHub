/**
 * Custom Editor.js block for source code.
 *
 * Why this replaces `@editorjs/code`:
 *
 * 1. That package exports the global `CodeTool`, not `Code`, so the old
 *    `typeof window.Code === 'function'` check silently skipped it and code
 *    blocks degraded to `ce-stub` placeholders — see `registry.js`.
 * 2. Even when loaded, it saves only `{ code }`. The stored schema has always
 *    been `{ code, language }` (see `ArticleWriteSerializer`, the block-type
 *    round-trip test in `apps/articles/tests.py`, and `renderer.js`, which
 *    renders `snippet-lang` from `data.language`), so its output would have
 *    silently dropped the language on every save.
 *
 * Saved data is unchanged: `{ code, language }`. Unknown keys on the stored
 * block are carried through untouched, and an unrecognised language is added to
 * the selector rather than replaced, so opening and saving an article never
 * loses or rewrites what an author wrote.
 */

/**
 * Selector options. `code` is first and is the label `renderer.js` already falls
 * back to when `language` is absent, so it doubles as "unspecified" and as the
 * default for legacy blocks that stored only `code`.
 */
export const CODE_LANGUAGES = Object.freeze([
  { value: 'code', label: 'Plain text' },
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'typescript', label: 'TypeScript' },
  { value: 'java', label: 'Java' },
  { value: 'c', label: 'C' },
  { value: 'cpp', label: 'C++' },
  { value: 'csharp', label: 'C#' },
  { value: 'go', label: 'Go' },
  { value: 'rust', label: 'Rust' },
  { value: 'sql', label: 'SQL' },
  { value: 'bash', label: 'Shell' },
  { value: 'html', label: 'HTML' },
  { value: 'css', label: 'CSS' },
  { value: 'json', label: 'JSON' },
  { value: 'yaml', label: 'YAML' },
]);

export const DEFAULT_CODE_LANGUAGE = 'code';

const INDENT = '  ';

/** Reads a stored code block into the `{ code, language }` shape the editor uses. */
export function normalizeCodeBlockData(data) {
  const source = data && typeof data === 'object' ? data : {};
  const language = typeof source.language === 'string' ? source.language.trim() : '';
  return {
    code: typeof source.code === 'string' ? source.code : '',
    language: language || DEFAULT_CODE_LANGUAGE,
  };
}

/**
 * The option list for the selector, with `current` guaranteed present.
 *
 * A language written before this tool existed (or one this build does not list)
 * is appended rather than dropped, so selecting another language and saving is
 * the only way it changes — never merely opening the article.
 */
export function codeLanguageOptions(current) {
  const options = CODE_LANGUAGES.map((option) => ({ ...option }));
  const value = typeof current === 'string' ? current.trim() : '';
  if (value && !options.some((option) => option.value === value)) {
    options.push({ value, label: `${value} (not recognised)` });
  }
  return options;
}

/** Indent the caret position, or every line touched by the selection. */
function indent(textarea) {
  const { selectionStart: start, selectionEnd: end, value } = textarea;

  if (start === end) {
    textarea.setRangeText(INDENT, start, end, 'end');
    return;
  }

  const lineStart = value.lastIndexOf('\n', start - 1) + 1;
  const shifted = value.slice(lineStart, end).replace(/^/gm, INDENT);
  textarea.setRangeText(shifted, lineStart, end, 'select');
}

/** Unindent: remove up to 2 leading spaces from each line touched by the selection. */
function unindent(textarea) {
  const { selectionStart: start, selectionEnd: end, value } = textarea;
  const lineStart = value.lastIndexOf('\n', start - 1) + 1;
  const target = value.slice(lineStart, end);
  const unshifted = target.replace(/^( {1,2})/gm, '');
  textarea.setRangeText(unshifted, lineStart, end, 'select');
}

const TOOLBOX_ICON = `<svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M7.5 5.5L3 10l4.5 4.5M12.5 5.5L17 10l-4.5 4.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

export class CodeBlockTool {
  static get toolbox() {
    return { title: 'Code', icon: TOOLBOX_ICON };
  }

  static get isReadOnlySupported() {
    return true;
  }

  /** Keeps an author-supplied default language inside the known set. */
  static sanitize(config) {
    const requested = typeof config?.defaultLanguage === 'string' ? config.defaultLanguage.trim() : '';
    return {
      defaultLanguage: requested || DEFAULT_CODE_LANGUAGE,
      rows: Number.isFinite(config?.rows) && config.rows > 0 ? Math.floor(config.rows) : 10,
    };
  }

  constructor({ data, config, readOnly } = {}) {
    // Retained verbatim so `save` can merge rather than replace: an unexpected
    // key on a stored block survives an edit.
    this.original = data && typeof data === 'object' ? { ...data } : {};
    this.normalized = normalizeCodeBlockData(this.original);
    this.readOnly = Boolean(readOnly);
    this.config = CodeBlockTool.sanitize(config || {});
  }

  render() {
    const container = document.createElement('div');
    container.className = 'cdx-block cdx-code';

    const bar = document.createElement('div');
    bar.className = 'cdx-code__bar';

    const barLeft = document.createElement('div');
    barLeft.className = 'cdx-code__bar-left';

    const selectId = `cdx-code-language-${Math.random().toString(36).slice(2, 9)}`;
    const label = document.createElement('label');
    label.className = 'cdx-code__label';
    label.htmlFor = selectId;
    label.textContent = 'Language';

    this.select = document.createElement('select');
    this.select.id = selectId;
    this.select.className = 'cdx-code__select';
    for (const option of codeLanguageOptions(this.normalized.language)) {
      const element = document.createElement('option');
      element.value = option.value;
      element.textContent = option.label;
      this.select.appendChild(element);
    }
    this.select.value = this.normalized.language;
    this.select.disabled = this.readOnly;

    barLeft.append(label, this.select);

    const barRight = document.createElement('div');
    barRight.className = 'cdx-code__bar-right';

    this.stats = document.createElement('span');
    this.stats.className = 'cdx-code__stats';

    this.copyBtn = document.createElement('button');
    this.copyBtn.type = 'button';
    this.copyBtn.className = 'cdx-code__copy-btn';
    this.copyBtn.textContent = 'Copy';
    this.copyBtn.title = 'Copy code snippet';

    let copyResetTimer = null;
    this.copyBtn.addEventListener('click', async () => {
      const code = this.textarea ? this.textarea.value : this.normalized.code;
      if (!code) return;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(code);
        } else {
          const scratch = document.createElement('textarea');
          scratch.value = code;
          scratch.style.position = 'fixed';
          scratch.style.opacity = '0';
          document.body.appendChild(scratch);
          scratch.select();
          document.execCommand('copy');
          scratch.remove();
        }
        this.copyBtn.textContent = 'Copied!';
        this.copyBtn.classList.add('is-copied');
        clearTimeout(copyResetTimer);
        copyResetTimer = setTimeout(() => {
          if (this.copyBtn) {
            this.copyBtn.textContent = 'Copy';
            this.copyBtn.classList.remove('is-copied');
          }
        }, 2000);
      } catch (err) {
        console.warn('Unable to copy code', err);
      }
    });

    barRight.append(this.stats, this.copyBtn);
    bar.append(barLeft, barRight);

    this.textarea = document.createElement('textarea');
    this.textarea.className = 'cdx-code__textarea';
    this.textarea.spellcheck = false;
    this.textarea.autocapitalize = 'off';
    this.textarea.autocomplete = 'off';
    // `wrap="off"` plus horizontal scrolling keeps code readable; soft wrapping
    // would silently rewrite the author's line structure.
    this.textarea.setAttribute('wrap', 'off');
    this.textarea.rows = this.config.rows;
    this.textarea.value = this.normalized.code;
    this.textarea.readOnly = this.readOnly;
    this.textarea.setAttribute('aria-label', 'Code');

    const updateStatsAndHeight = () => {
      if (!this.textarea || !this.stats) return;
      const val = this.textarea.value;
      const lines = val ? (val.match(/\n/g) || []).length + 1 : 0;
      this.stats.textContent = `${lines} line${lines === 1 ? '' : 's'}`;
      this.textarea.style.height = 'auto';
      const newHeight = Math.max(140, this.textarea.scrollHeight + 4);
      this.textarea.style.height = `${newHeight}px`;
    };

    this.textarea.addEventListener('input', updateStatsAndHeight);

    // Tab indents instead of leaving the field; Shift+Tab unindents.
    // Escape is the way out, so the block never becomes a keyboard trap.
    this.textarea.addEventListener('keydown', (event) => {
      if (event.key === 'Tab') {
        event.preventDefault();
        if (event.shiftKey) {
          unindent(this.textarea);
        } else {
          indent(this.textarea);
        }
        updateStatsAndHeight();
      } else if (event.key === 'Escape') {
        this.textarea.blur();
      }
    });

    container.append(bar, this.textarea);
    setTimeout(updateStatsAndHeight, 0);
    return container;
  }

  save() {
    const language = this.select?.value || this.normalized.language;
    return {
      ...this.original,
      code: this.textarea ? this.textarea.value : this.normalized.code,
      language: language || DEFAULT_CODE_LANGUAGE,
    };
  }

  destroy() {
    this.select = null;
    this.textarea = null;
    this.stats = null;
    this.copyBtn = null;
  }
}
