/**
 * The admin editor's tool registry, and the guard that stops an unavailable tool
 * from destroying an article.
 *
 * There is exactly one list here, and everything else is derived from it:
 *
 *   * which tools are handed to Editor.js,
 *   * which block types are therefore safe to load, edit and save,
 *   * what the panel reports when a tool failed to load.
 *
 * A hand-maintained "missing tools" list cannot work: the original bug was a
 * `typeof window.Code === 'function'` check that quietly skipped the code tool
 * while a separate list only tracked the image tool. Nothing complained, code
 * and list blocks rendered as `ce-stub`, and saving the article dropped them.
 * Availability is now measured, not declared.
 *
 * Module scope stays free of DOM access so the regression checks in
 * `.check-editor-tools.mjs` can import this under Node.
 */

import { CodeBlockTool } from './code-block.js';
import { LinkBlockTool } from './link-block.js';
import { ListBlockTool } from './list-block.js';

/**
 * Mirrors SUPPORTED_BLOCK_TYPES in backend/apps/articles/models.py â€” the
 * allow-list the API enforces. `.check-editor-tools.mjs` fails if the two drift.
 */
export const SUPPORTED_BLOCK_TYPES = Object.freeze([
  'paragraph',
  'header',
  'list',
  'quote',
  'code',
  'image',
  'delimiter',
  'linkTool',
]);

/** Editor.js supplies `paragraph` itself, so it is never "missing". */
export const BUILT_IN_BLOCK_TYPES = Object.freeze(['paragraph']);

/** Reading a UMD global that may not exist (bad CDN, blocked, renamed export). */
function globalOf(name) {
  if (typeof window === 'undefined') return undefined;
  return window[name];
}

export const EDITOR_TOOLS = Object.freeze([
  {
    blockType: 'header',
    label: 'Heading',
    source: 'cdn',
    // `@editorjs/header` UMD build.
    globalName: 'Header',
    load: () => globalOf('Header'),
    configure: (Tool) => ({
      class: Tool,
      inlineToolbar: true,
      config: { levels: [2, 3, 4], defaultLevel: 2 },
    }),
  },
  {
    blockType: 'list',
    label: 'List',
    source: 'cdn',
    // `@editorjs/list@1.10.0` -> window.List. Version and adapter go together:
    // list 1.x is the line driven by `items: string[]`, which `ListBlockTool`
    // converts to and from this project's `items: [{ content }]`. list 2.x uses a
    // recursive shape and throws while rendering ours.
    globalName: 'List',
    // Availability probe only; the adapter resolves the global itself.
    load: () => globalOf('List'),
    configure: () => ListBlockTool,
  },
  {
    blockType: 'quote',
    label: 'Quote',
    source: 'cdn',
    globalName: 'Quote',
    load: () => globalOf('Quote'),
    configure: (Tool) => ({ class: Tool, inlineToolbar: true }),
  },
  {
    blockType: 'image',
    label: 'Image',
    source: 'cdn',
    globalName: 'ImageTool',
    // The uploader needs the API client, which is not importable here without
    // dragging the window-dependent config module into Node. The caller supplies it.
    load: () => globalOf('ImageTool'),
    configure: (Tool, { imageToolConfig }) => ({
      class: Tool,
      inlineToolbar: true,
      config: imageToolConfig || {},
    }),
  },
  {
    blockType: 'delimiter',
    label: 'Divider',
    source: 'cdn',
    globalName: 'Delimiter',
    load: () => globalOf('Delimiter'),
    configure: (Tool) => Tool,
  },
  {
    blockType: 'code',
    label: 'Code',
    // Local tool: `@editorjs/code` drops `language`, which the stored schema
    // and `renderer.js` both rely on.
    source: 'local',
    globalName: null,
    load: () => CodeBlockTool,
    configure: (Tool) => ({ class: Tool, inlineToolbar: true }),
  },
  {
    blockType: 'linkTool',
    label: 'Link',
    source: 'local',
    globalName: null,
    load: () => LinkBlockTool,
    configure: (Tool) => ({ class: Tool }),
  },
]);

/** True when every supported block type has a tool configured for it. */
export function registryCoversSupportedBlockTypes() {
  const configured = new Set(EDITOR_TOOLS.map((tool) => tool.blockType));
  return SUPPORTED_BLOCK_TYPES.every((type) => BUILT_IN_BLOCK_TYPES.includes(type) || configured.has(type));
}

/**
 * Resolves the tool map Editor.js should be constructed with.
 *
 * @returns {{tools: object, available: Set<string>, missing: Array<{blockType: string, label: string, source: string, globalName: ?string}>}}
 *   `tools` is what Editor.js accepts, `available` the block types that can be
 *   round-tripped, and `missing` everything the panel must warn about.
 */
export function resolveEditorTools({ imageToolConfig } = {}) {
  const tools = {};
  const available = new Set(BUILT_IN_BLOCK_TYPES);
  const missing = [];

  for (const definition of EDITOR_TOOLS) {
    let loaded;
    try {
      loaded = definition.load();
    } catch (error) {
      loaded = null;
    }

    if (typeof loaded !== 'function') {
      missing.push({
        blockType: definition.blockType,
        label: definition.label,
        source: definition.source,
        globalName: definition.globalName,
      });
      continue;
    }

    tools[definition.blockType] = definition.configure(loaded, { imageToolConfig });
    available.add(definition.blockType);
  }

  return { tools, available, missing };
}

/** Distinct block types present in a stored Editor.js document. */
export function documentBlockTypes(document) {
  if (!document || typeof document !== 'object') return [];
  const blocks = Array.isArray(document.blocks) ? document.blocks : [];

  const types = new Set();
  for (const block of blocks) {
    if (block && typeof block.type === 'string' && block.type) types.add(block.type);
  }
  return [...types];
}

/** Block types in `document` that the editor cannot faithfully represent. */
export function unsupportedBlockTypes(document, available) {
  const known = available instanceof Set ? available : new Set(available || []);
  return documentBlockTypes(document)
    .filter((type) => !known.has(type))
    .sort();
}

export class UnsupportedBlocksError extends Error {
  constructor(blockTypes) {
    super(
      `Cannot save this article safely. Unsupported Editor.js blocks: ${blockTypes.join(', ')}. ` +
        'Loading and saving would remove that content.',
    );
    this.name = 'UnsupportedBlocksError';
    this.blockTypes = [...blockTypes];
  }
}

/**
 * Refuses to let an article be saved when a block type it contains has no tool.
 *
 * Called against the *original* stored document before `editor.save()`, so the
 * request is never sent and the article is left exactly as it was. Editor.js
 * omits unregistered blocks from its save output, which is the silent data loss
 * this exists to prevent.
 *
 * @throws {UnsupportedBlocksError} listing every offending block type.
 */
export function assertDocumentIsEditable(document, available) {
  const unsupported = unsupportedBlockTypes(document, available);
  if (unsupported.length) throw new UnsupportedBlocksError(unsupported);
  return true;
}
