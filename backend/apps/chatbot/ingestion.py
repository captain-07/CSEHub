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
    if not all((settings.PINECONE_API_KEY, settings.PINECONE_INDEX_NAME, settings.GEMINI_API_KEY)):
        raise RuntimeError('Pinecone and Gemini environment variables are required for RAG.')


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


def ingest_article(article) -> int:
    """
    Splits an article into chunks, generates embeddings,
    and stores them in Pinecone.

    Existing vectors for the article are deleted first
    so the article can be safely re-ingested.

    Returns:
        Number of chunks stored.
    """

    _require_rag_settings()
    pc = Pinecone(
        api_key=settings.PINECONE_API_KEY
    )

    index = pc.Index(
        settings.PINECONE_INDEX_NAME
    )

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

    full_text = f"{article.title}\n\n{article_content_to_text(article.content)}"

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
