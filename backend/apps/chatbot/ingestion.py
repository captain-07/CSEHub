from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone
from django.conf import settings
import html
import re


NAMESPACE = "articles"


def get_embeddings():
    _require_rag_settings()
    return GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-001",
        google_api_key=settings.GEMINI_API_KEY,
        output_dimensionality=768,
    )


def get_vectorstore():
    _require_rag_settings()
    pc = Pinecone(
        api_key=settings.PINECONE_API_KEY
    )
    return PineconeVectorStore(
        index=pc.Index(settings.PINECONE_INDEX_NAME),
        embedding=get_embeddings(),
        text_key="text",
        namespace=NAMESPACE,
    )


def _require_rag_settings():
    # Imported locally so `indexing` (which the article signals import) can use
    # the same check without pulling LangChain/Pinecone in at Django startup.
    from .indexing import rag_configured

    if not rag_configured():
        raise RuntimeError('Pinecone and Gemini environment variables are required for RAG.')


def _pinecone_index():
    """The index every write path here talks to."""
    _require_rag_settings()
    return Pinecone(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX_NAME)


def _strip_inline_html(value) -> str:
    """Editor.js stores inline formatting as HTML; embeddings should see plain text.

    Keeping raw tags in the indexed text pollutes the vector with markup and
    degrades retrieval quality, so tags are removed and entities decoded.
    """
    if not isinstance(value, str):
        return ''
    text = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    return text.strip()


def article_content_to_text(content) -> str:
    """Turn supported Editor.js blocks into useful retrieval text."""
    if isinstance(content, str):
        return _strip_inline_html(content)
    if not isinstance(content, dict):
        return ''
    lines = []
    for block in content.get('blocks', []):
        data = block.get('data', {}) if isinstance(block, dict) else {}
        kind = block.get('type') if isinstance(block, dict) else ''
        if kind == 'header':
            lines.append(f"Heading: {_strip_inline_html(data.get('text', ''))}")
        elif kind == 'list':
            items = data.get('items', [])
            lines.extend(
                f"- {_strip_inline_html(item if isinstance(item, str) else item.get('content', ''))}"
                for item in items
            )
        elif kind == 'code':
            language = data.get('language') or 'code'
            lines.append(f"Code ({language}):\n{data.get('code', '')}")
        elif kind in ('paragraph', 'quote'):
            lines.append(_strip_inline_html(data.get('text', '')))
        elif kind == 'raw':
            lines.append(_strip_inline_html(data.get('html') or data.get('text', '')))
        elif kind in ('image', 'linkTool'):
            caption = _strip_inline_html(data.get('caption') or data.get('text') or '')
            if caption:
                lines.append(f"{kind}: {caption}")
    return '\n\n'.join(line for line in lines if line.strip())


def purge_namespace() -> None:
    """Delete every vector in the RAG namespace.

    `ingest_article` only deletes vectors carrying its own article's
    `article_id`, so vectors belonging to articles that were deleted from the
    database survive forever. They are worse than dead weight: the ids get
    reused, so a similarity search filtered on a live article can match an
    orphan's text and the assistant answers from the wrong article — confidently
    and wrongly.

    Re-ingesting everything is therefore not enough on its own; the namespace has
    to be emptied first. Pinecone's index has no dimension change here, only the
    vectors go.
    """
    _pinecone_index().delete(delete_all=True, namespace=NAMESPACE)


def remove_article_vectors(article_id) -> None:
    """Delete every vector belonging to one article.

    Called when an article is unpublished or deleted. Without this, the vectors
    outlive the row and a filtered similarity search can still match their text,
    so the assistant answers from content no reader can reach (or from a
    different article, once ids are reused).

    Safe to call for an article that was never indexed: an empty namespace is
    the normal state on a fresh deployment.
    """
    try:
        _pinecone_index().delete(
            filter={"article_id": str(article_id)},
            namespace=NAMESPACE,
        )
    except Exception as exc:
        # Pinecone reports a missing namespace on the first write of a fresh
        # index. There is nothing to delete in that case.
        if "Namespace not found" not in str(exc):
            raise


def ingest_article(article) -> int:

    """
    Splits an article into chunks, generates embeddings,
    and stores them in Pinecone.

    Existing vectors for the article are deleted first
    so the article can be safely re-ingested.

    Returns:
        Number of chunks stored.
    """

    index = _pinecone_index()

    # Delete existing vectors for this article.
    # During the first ingestion, the namespace may not exist yet.
    try:
        index.delete(
            filter={
                "article_id": str(article.id)
            },
            namespace=NAMESPACE,
        )

    except Exception as e:
        if "Namespace not found" not in str(e):
            raise

    # Split article text into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )

    # The excerpt is a human-written summary of the same material, so it is a
    # cheap retrieval signal; leaving it out made the indexed text strictly
    # poorer than the card a reader searches from.
    full_text = '\n\n'.join(
        part for part in (
            article.title,
            article.excerpt,
            article_content_to_text(article.content),
        ) if part
    )

    chunks = splitter.split_text(full_text)

    # Metadata for each chunk
    metadatas = [
        {
            "article_id": str(article.id),
            "article_slug": article.slug,
            "article_title": article.title,
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    # Unique ID for every vector
    ids = [
        f"article-{article.id}-chunk-{i}"
        for i in range(len(chunks))
    ]

    # Store chunks + embeddings in Pinecone
    vectorstore = get_vectorstore()

    vectorstore.add_texts(
        texts=chunks,
        metadatas=metadatas,
        ids=ids,
        namespace=NAMESPACE,
    )

    return len(chunks)
