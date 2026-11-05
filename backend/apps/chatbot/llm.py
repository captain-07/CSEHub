"""Shared LangChain/Gemini plumbing.

The assistant and the quiz generator use the same provider but want different
sampling settings and error wording. Keeping client construction and response
normalisation here means a provider change — a retired model id, a new content
shape — is made once instead of in each feature.
"""

from django.conf import settings
from langchain_google_genai import ChatGoogleGenerativeAI


class LLMServiceError(Exception):
    """A configuration or provider failure that is safe to report through the API."""


def build_llm(*, temperature=0.3, timeout=30, max_retries=2):
    """Return a configured Gemini chat client.

    `temperature` is ignored by `gemini-3.5-flash-lite`, which fixes its own
    sampling defaults; it is still passed for models that honour it.
    """
    if not settings.GEMINI_API_KEY:
        raise LLMServiceError('The AI service is not configured.')
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries,
    )


def response_text(response) -> str:
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
        raise LLMServiceError('The AI service returned an empty response.')
    return text.strip()
