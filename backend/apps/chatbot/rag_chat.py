from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from django.conf import settings
from .ingestion import get_vectorstore


class ChatServiceError(Exception):
    """A provider failure safe to report through the API."""


# Returned when the article has no matching indexed content. This is a content
# problem rather than a provider failure, so it is a normal 200 answer rather than
# a 5xx — the client distinguishes "nothing to say" from "the service is down".
NO_CONTEXT_ANSWER = "I don't have enough information from this article to answer that."

SYSTEM_PROMPT = PromptTemplate(
    input_variables=["context", "history", "question"],
    template=(
        "You are a helpful assistant answering questions about a specific "
        "CS article. Use ONLY the context below to answer. If the answer "
        "isn't in the context, say you don't know based on this article.\n\n"
        "Context:\n{context}\n\nRecent conversation:\n{history}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    ),
)


def get_llm():
    if not settings.GEMINI_API_KEY:
        raise ChatServiceError("The chat service is not configured.")
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.3,
        timeout=30,
        max_retries=2,
    )


def _response_text(response) -> str:
    """Normalize LangChain/Gemini content without assuming one provider shape."""
    content = getattr(response, 'content', response)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get('text'), str):
                parts.append(item['text'])
        text = ''.join(parts)
    else:
        text = ''
    if not text.strip():
        raise ChatServiceError("The chat service returned an empty response.")
    return text.strip()


def answer_question(article, question: str, history: str = '', k: int = 4) -> str:
    """
    Retrieves relevant chunks for this article and generates a grounded answer.
    """
    try:
        vectorstore = get_vectorstore()

        docs = vectorstore.similarity_search(
            query=question, k=k, filter={"article_id": str(article.id)}
        )
    except ChatServiceError:
        raise
    except Exception as exc:
        raise ChatServiceError("The learning service is temporarily unavailable.") from exc

    # An empty result set is a content problem, not an infrastructure fault: the
    # article simply has nothing indexed that matches. Reported as a plain answer
    # so the article author can tell the difference from an outage.
    if not docs:
        return NO_CONTEXT_ANSWER

    context = "\n\n".join(doc.page_content for doc in docs)

    try:
        prompt = SYSTEM_PROMPT.format(context=context, history=history or '(none)', question=question)
        return _response_text(get_llm().invoke(prompt))
    except ChatServiceError:
        raise
    except Exception as exc:
        raise ChatServiceError("The learning service is temporarily unavailable.") from exc
