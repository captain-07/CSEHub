from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone
from django.conf import settings


NAMESPACE = "articles"


def get_embeddings():
    return GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-001",
        google_api_key=settings.GEMINI_API_KEY,
        output_dimensionality=768,
    )


def get_vectorstore():
    pc = Pinecone(
        api_key=settings.PINECONE_API_KEY
    )

    return PineconeVectorStore(
        index=pc.Index(settings.PINECONE_INDEX_NAME),
        embedding=get_embeddings(),
        text_key="text",
        namespace=NAMESPACE,
    )


def ingest_article(article) -> int:
    """
    Splits an article into chunks, generates embeddings,
    and stores them in Pinecone.

    Existing vectors for the article are deleted first
    so the article can be safely re-ingested.

    Returns:
        Number of chunks stored.
    """

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

    full_text = f"{article.title}\n\n{article.content}"

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