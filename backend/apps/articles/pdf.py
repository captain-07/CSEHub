"""Article body -> PDF, rendered with ReportLab.

ReportLab is pure Python, which is why it was chosen over WeasyPrint: the
production image is `python:3.12-slim` and must not grow a pango/cairo
dependency to export an article. Two consequences shape this module.

*No bundled Unicode font.* The base-14 fonts are single-byte, so text is
normalised to Latin-1: typographic quotes and dashes become ASCII, and anything
outside the range becomes `?`. A stray emoji in an article must never fail a
download, so the conversion is a sanitizer rather than an exception.

*Images are referenced, not fetched.* Downloading a remote image while building
the PDF would put a third-party request inside a request of ours, with its own
timeout and failure mode. An image block renders as its caption plus its URL
instead — the reader can still find the picture.
"""

import io
import re
from html import escape
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
)

from .serializers import article_author_name, article_reading_time

PAGE = A4
MARGIN_X = 20 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 20 * mm

GREY = colors.HexColor('#6b7280')
INK = colors.HexColor('#111827')
RULE = colors.HexColor('#e5e7eb')
CODE_BG = colors.HexColor('#f6f8fa')

# Width available to a flowable, in points, used to wrap code by character
# count: the body font is monospaced, so a character budget is exact.
_TEXT_WIDTH = PAGE[0] - (2 * MARGIN_X)
_CODE_CHAR_WIDTH = 8.4 * 0.6  # Courier at the size below

# Editor.js stores text as raw text with inline HTML tags. Only these tags mean
# anything to ReportLab; `<mark>`, `<span>` and friends are dropped while their
# content survives.
_TAG_RE = re.compile(r'</?([a-zA-Z][a-zA-Z0-9]*)((?:\s[^>]*?)?)\s*/?>')
_TAG_SPLIT_RE = re.compile(r'(</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*?)?\s*/?>)')
_HREF_RE = re.compile(r'href\s*=\s*"([^"]*)"', re.IGNORECASE)

# What each supported inline tag means to ReportLab. A tag absent from this map
# (`span`, `mark`, ...) is dropped while its text survives.
_CANONICAL = {
    'b': 'b', 'strong': 'b',
    'i': 'i', 'em': 'i',
    'u': 'u',
    'code': 'font',
    'a': 'link',
}
_CLOSERS = {
    'b': '</b>', 'i': '</i>', 'u': '</u>', 'font': '</font>', 'link': '</link>',
}
# `xml_escape` escapes & < > already; an attribute also needs the quote.
_ATTRIBUTE_ESCAPES = {'"': '&quot;'}

_REPLACEMENTS = {
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00a0': ' ',
    '\u2022': '*', '\u200b': '', '\ufeff': '',
}


def _safe(text):
    """Normalise to something the base-14 fonts can draw.

    Explicit replacements first (so an em dash reads as a dash rather than a
    question mark), then a lossy encode for everything else.
    """
    text = ''.join(_REPLACEMENTS.get(char, char) for char in str(text or ''))
    return text.encode('latin-1', 'replace').decode('latin-1')


def _opener(tag):
    """One opening tag -> `(canonical name, ReportLab markup)`, or None.

    None means "not emitted": an unknown tag, a link with no `href`, or a link
    to something that is not a web URL. A refused opener must also refuse its
    closing tag, which is why the canonical name and the markup are returned
    together.
    """
    match = _TAG_RE.fullmatch(tag)
    if not match:
        return None

    name = match.group(1).lower()
    canonical = _CANONICAL.get(name)
    if canonical is None:
        return None

    if name == 'a':
        found = _HREF_RE.search(match.group(2) or '')
        if not found:
            return None
        href = found.group(1)
        # A PDF link is still a link: refuse anything that is not a web URL, for
        # the same reason the reader never frames a stored URL.
        if not href.lower().startswith(('http://', 'https://')):
            return None
        return 'link', f'<link href="{xml_escape(href, _ATTRIBUTE_ESCAPES)}">'

    if canonical == 'font':
        return 'font', '<font face="Courier">'

    return canonical, f'<{canonical}>'


def _inline(value):
    """Editor.js inline HTML -> ReportLab's mini-markup, escaped apart from tags.

    Tags are balanced here rather than trusted. ReportLab raises a `ValueError`
    on an unclosed `<b>`, and stored content is free text an editor may have
    left malformed, so a whole download must not fail over one missing close
    tag: a stray close is dropped, a crossed pair is closed in order, and
    whatever is still open is closed at the end.
    """
    source = _safe(value)
    out = []
    stack = []

    for piece in _TAG_SPLIT_RE.split(source):
        if not piece:
            continue

        if not (piece.startswith('<') and piece.endswith('>')):
            out.append(escape(piece).replace('\n', '<br/>'))
            continue

        match = _TAG_RE.fullmatch(piece)
        if not match:
            # A lone `<` or something that only looks like a tag is text.
            out.append(escape(piece))
            continue

        name = match.group(1).lower()
        if name == 'br':
            if not piece.startswith('</'):
                out.append('<br/>')
            continue

        if piece.startswith('</'):
            canonical = _CANONICAL.get(name)
            if canonical is None:
                continue
            index = next(
                (i for i in range(len(stack) - 1, -1, -1) if stack[i] == canonical),
                None,
            )
            if index is None:
                # A stray close, or the close of a link we refused to open.
                continue
            while len(stack) > index + 1:
                out.append(_CLOSERS[stack.pop()])
            out.append(_CLOSERS[stack.pop()])
            continue

        opened = _opener(piece)
        if opened:
            canonical, markup = opened
            out.append(markup)
            stack.append(canonical)

    while stack:
        out.append(_CLOSERS[stack.pop()])

    return ''.join(out).strip()


def _plain(value):
    """Inline HTML -> plain text, for captions and metadata lines."""
    text = _TAG_RE.sub(' ', _safe(value))
    return ' '.join(text.split())


def _wrap_code(code, limit=None):
    """Hard-wrap code at the printable width.

    `Preformatted` does not wrap and the page clips what overflows, so the line
    has to be broken before it gets there. A continuation is indented, which
    reads as a wrap rather than as new code.
    """
    limit = limit or max(40, int(_TEXT_WIDTH / _CODE_CHAR_WIDTH) - 2)
    lines = []
    for raw in _safe(code).replace('\t', '    ').splitlines() or ['']:
        while len(raw) > limit:
            lines.append(raw[:limit])
            raw = '    ' + raw[limit:]
        lines.append(raw)
    return '\n'.join(lines)


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'PdfTitle', parent=base['Title'], fontName='Helvetica-Bold',
            fontSize=22, leading=27, alignment=TA_LEFT, textColor=INK,
            spaceAfter=6,
        ),
        'meta': ParagraphStyle(
            'PdfMeta', parent=base['Normal'], fontSize=8.5, leading=12,
            textColor=GREY, spaceAfter=2,
        ),
        'excerpt': ParagraphStyle(
            'PdfExcerpt', parent=base['Normal'], fontName='Helvetica-Oblique',
            fontSize=11.5, leading=17, textColor=colors.HexColor('#374151'),
            spaceAfter=10,
        ),
        'h1': ParagraphStyle(
            'PdfH1', parent=base['Normal'], fontName='Helvetica-Bold',
            fontSize=15, leading=19, textColor=INK, spaceBefore=14, spaceAfter=6,
            keepWithNext=1,
        ),
        'h2': ParagraphStyle(
            'PdfH2', parent=base['Normal'], fontName='Helvetica-Bold',
            fontSize=13, leading=17, textColor=INK, spaceBefore=12, spaceAfter=5,
            keepWithNext=1,
        ),
        'h3': ParagraphStyle(
            'PdfH3', parent=base['Normal'], fontName='Helvetica-Bold',
            fontSize=11.5, leading=15, textColor=INK, spaceBefore=10, spaceAfter=4,
            keepWithNext=1,
        ),
        'body': ParagraphStyle(
            'PdfBody', parent=base['Normal'], fontSize=10.5, leading=16,
            alignment=TA_JUSTIFY, textColor=INK, spaceAfter=8,
        ),
        'tight': ParagraphStyle(
            'PdfTight', parent=base['Normal'], fontSize=10.5, leading=16,
            textColor=INK,
        ),
        'quote': ParagraphStyle(
            'PdfQuote', parent=base['Normal'], fontName='Helvetica-Oblique',
            fontSize=10.5, leading=16, textColor=colors.HexColor('#374151'),
            leftIndent=12, borderPadding=6, backColor=CODE_BG,
            borderWidth=0, spaceBefore=4, spaceAfter=10,
        ),
        'code': ParagraphStyle(
            'PdfCode', parent=base['Normal'], fontName='Courier', fontSize=8.4,
            leading=11.5, textColor=colors.HexColor('#1f2937'),
            backColor=CODE_BG, borderPadding=6, spaceBefore=2, spaceAfter=10,
        ),
        'caption': ParagraphStyle(
            'PdfCaption', parent=base['Normal'], fontName='Helvetica-Oblique',
            fontSize=8.5, leading=12, textColor=GREY, spaceAfter=10,
        ),
        'note': ParagraphStyle(
            'PdfNote', parent=base['Normal'], fontSize=8, leading=11,
            textColor=GREY, spaceBefore=12,
        ),
    }


def _blocks(content):
    """Normalise stored content into Editor.js blocks."""
    if isinstance(content, str):
        return _legacy_blocks(content)
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, dict) and isinstance(content.get('blocks'), list):
        return [block for block in content['blocks'] if isinstance(block, dict)]
    return []


def _legacy_blocks(text):
    """A pre-Editor.js body: markdown-ish headings over blank-line paragraphs."""
    blocks = []
    for chunk in re.split(r'\n\s*\n', str(text or '')):
        chunk = chunk.strip()
        if not chunk:
            continue
        heading = re.match(r'^(#{1,3})\s+(.*)$', chunk, re.DOTALL)
        if heading:
            blocks.append({
                'type': 'header',
                'data': {'level': len(heading.group(1)), 'text': heading.group(2)},
            })
        else:
            blocks.append({'type': 'paragraph', 'data': {'text': chunk}})
    return blocks


def _data(block):
    value = block.get('data')
    return value if isinstance(value, dict) else {}


def _list_items(data, styles):
    items = data.get('items')
    if not isinstance(items, list):
        return None
    rendered = []
    for item in items:
        text = item.get('content') if isinstance(item, dict) else item
        content = _inline(text)
        if content:
            rendered.append(ListItem(Paragraph(content, styles['tight']), leftIndent=10))
    if not rendered:
        return None
    return ListFlowable(
        rendered,
        bulletType='1' if data.get('style') == 'ordered' else 'bullet',
        bulletFontSize=8,
        leftIndent=16,
        bulletOffsetY=-1,
        spaceAfter=8,
    )


def _block_flowables(block, styles):
    """One block -> flowables. Unknown types degrade rather than raise."""
    data = _data(block)
    kind = block.get('type')

    if kind == 'header':
        try:
            level = max(1, min(3, int(data.get('level') or 2)))
        except (TypeError, ValueError):
            level = 2
        text = _inline(data.get('text'))
        # The article title owns the top of the page, so every in-body heading
        # starts one level below it.
        return [Paragraph(text, styles[f'h{level}'])] if text else []

    if kind == 'list':
        flowable = _list_items(data, styles)
        return [flowable] if flowable else []

    if kind == 'code':
        code = str(data.get('code') or '')
        return [Preformatted(_wrap_code(code), styles['code'])] if code.strip() else []

    if kind == 'quote':
        text = _inline(data.get('text'))
        if not text:
            return []
        parts = [Paragraph(text, styles['quote'])]
        caption = _plain(data.get('caption'))
        if caption:
            parts.append(Paragraph(f'&#8212; {escape(caption)}', styles['caption']))
        # The attribution belongs to the quotation: split apart, the caption
        # opens the next page over the wrong paragraph.
        return [KeepTogether(parts)]

    if kind == 'delimiter':
        return [HRFlowable(width='100%', color=RULE, spaceBefore=6, spaceAfter=12)]

    if kind == 'image':
        file = data.get('file')
        file_url = file.get('url') if isinstance(file, dict) else file
        url = _plain(file_url or data.get('url') or '')
        caption = _plain(data.get('caption'))
        if not url and not caption:
            return []
        label = caption or 'Image'
        return [Paragraph(
            f'{escape(label)}<br/><font color="#6b7280">{escape(url)}</font>'
            if url else escape(label),
            styles['caption'],
        )]

    if kind == 'linkTool':
        url = _plain(data.get('url') or data.get('link') or '')
        # The reader renders a link's label as text, not as inline markup, so a
        # label that happens to contain `<b>` or another `<a>` is not parsed
        # into (possibly nested) reportlab tags here either.
        text = _plain(data.get('text') or data.get('link') or url)
        if not text:
            return []
        if url.lower().startswith(('http://', 'https://')):
            href = xml_escape(url, _ATTRIBUTE_ESCAPES)
            return [Paragraph(
                f'<link href="{href}" color="#27644c">{escape(text)}</link>',
                styles['body'],
            )]
        return [Paragraph(escape(text), styles['body'])]

    if kind == 'raw':
        text = _plain(data.get('text'))
        return [Paragraph(escape(text), styles['body'])] if text else []

    # 'paragraph' and anything unrecognised.
    text = _inline(data.get('text'))
    return [Paragraph(text, styles['body'])] if text else []


def _meta_line(article):
    parts = []
    author = article_author_name(article)
    if author:
        parts.append(f'By {author}')
    created = getattr(article, 'created_at', None)
    if created:
        parts.append(created.strftime('%d %b %Y'))
    reading = article_reading_time(getattr(article, 'content', None))
    if reading:
        parts.append(reading)
    if getattr(article, 'category', None):
        parts.append(article.category.name)
    return ' &#183; '.join(escape(_safe(part)) for part in parts)


def _snippet_flowables(article, styles):
    """Attached code snippets, in their stored order."""
    flowables = []
    for snippet in article.code_snippets.all():
        code = str(snippet.code or '')
        if not code.strip():
            continue
        language = _plain(snippet.language) or 'code'
        flowables.append(Paragraph(escape(language), styles['caption']))
        flowables.append(Preformatted(_wrap_code(code), styles['code']))
    if flowables:
        flowables.insert(0, Paragraph('Code', styles['h2']))
    return flowables


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(GREY)
    width, _ = PAGE
    canvas.drawString(MARGIN_X, 11 * mm, 'CSEHub')
    canvas.drawRightString(width - MARGIN_X, 11 * mm, f'Page {doc.page}')
    canvas.restoreState()


def article_to_story(article, *, licensed_to=''):
    """The document as a list of flowables.

    Separate from `render_article_pdf` so the content mapping can be tested
    without parsing a PDF: the assertions are about what the document says.
    """
    styles = _styles()
    story = []

    title = Paragraph(_inline(article.title) or 'Untitled', styles['title'])
    story.append(title)

    meta = _meta_line(article)
    if meta:
        story.append(Paragraph(meta, styles['meta']))

    story.append(HRFlowable(width='100%', color=RULE, spaceBefore=8, spaceAfter=12))

    excerpt = _plain(article.excerpt)
    if excerpt:
        story.append(Paragraph(escape(excerpt), styles['excerpt']))

    blocks = _blocks(article.content)
    if not blocks:
        story.append(Paragraph('This article has no content yet.', styles['body']))
    else:
        for block in blocks:
            story.extend(_block_flowables(block, styles))

    # `CodeSnippet` rows are rendered after the body on the page, so they follow
    # it here too. An unsaved article has no pk and therefore no snippets, which
    # is why the guard is on `pk` rather than on a try/except.
    if getattr(article, 'pk', None):
        story.extend(_snippet_flowables(article, styles))

    story.append(HRFlowable(width='100%', color=RULE, spaceBefore=14, spaceAfter=8))
    story.append(Paragraph(
        'A paid article from CSEHub.' if article.is_paid else 'From CSEHub.',
        styles['note'],
    ))
    if licensed_to:
        story.append(Paragraph(
            f'Licensed to {escape(_safe(licensed_to))}. Please do not redistribute.',
            styles['note'],
        ))

    return story


def render_article_pdf(article, *, licensed_to=''):
    """Render the article and return the PDF as bytes."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=PAGE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=_plain(article.title),
        author=_safe(article_author_name(article) or 'CSEHub'),
        subject=_plain(article.excerpt),
        creator='CSEHub',
    )
    document.build(
        article_to_story(article, licensed_to=licensed_to),
        onFirstPage=_footer,
        onLaterPages=_footer,
    )
    return buffer.getvalue()
