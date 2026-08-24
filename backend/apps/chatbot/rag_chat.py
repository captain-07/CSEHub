from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from django.conf import settings
from .ingestion import get_vectorstore


SYSTEM_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=(
        "You are a helpful assistant answering questions about a specific "
        "CS article. Use ONLY the context below to answer. If the answer "
        "isn't in the context, say you don't know based on this article.\n\n"
        "Context:\n{context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    ),
)


def get_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.3,
    )


def answer_question(article, question: str, k: int = 4) -> str:
    """
    Retrieves relevant chunks for this article and generates a grounded answer.
    """
    vectorstore = get_vectorstore()

    docs = vectorstore.similarity_search(
        query=question,
        k=k,
        filter={"article_id": str(article.id)},
    )

    if not docs:
        return "I don't have enough information from this article to answer that."

    context = "\n\n".join(doc.page_content for doc in docs)

    prompt = SYSTEM_PROMPT.format(context=context, question=question)
    llm = get_llm()
    response = llm.invoke(prompt)

    return response.content