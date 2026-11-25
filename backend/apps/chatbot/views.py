import json
import logging

from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404, StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.exceptions import NotAcceptable
from rest_framework import status
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from apps.articles.models import Article
from apps.payments.access import PAID_ARTICLE_MESSAGE, can_read_article
from .models import Conversation, Message
from .serializers import ConversationSerializer, AskQuestionSerializer
from .rag_chat import answer_question, stream_answer, ChatServiceError
from .throttling import ChatBurstThrottle, ChatDailyThrottle

logger = logging.getLogger(__name__)

# How much of the conversation the model sees. Six messages (three exchanges)
# buys continuity for a follow-up; a longer window is resent on every question
# and buys little, so it is a token cost rather than a quality feature. Shared
# by both ask routes so a reader's second question arrives with the same
# continuity as their first.
HISTORY_TURNS = 6


def _published_article(slug):
    """The published article a reader means, by slug or (legacy) numeric id."""
    article = Article.objects.filter(slug=slug, is_published=True).first()
    if not article and str(slug).isdigit():
        article = Article.objects.filter(pk=int(slug), is_published=True).first()
    if not article:
        raise Http404("No published article found matching the query")
    return article


def _prepare_question(request, article, question):
    """Record the reader's message, and return (conversation, history).

    The history is read *before* the new message is written, so the model is not
    handed the same question twice. It is returned as message rows rather than a
    transcript string: `rag_chat` turns them into real conversation turns, which
    is what lets a follow-up ("why?") be understood as a follow-up instead of a
    quote inside a new question. Shared by the whole-answer and streaming paths,
    so a provider failure must leave the conversation in exactly one state,
    whichever route the reader used.
    """
    conversation, _ = Conversation.objects.get_or_create(
        user=request.user,
        article=article,
    )

    recent_messages = list(
        conversation.messages.order_by('-created_at')[:HISTORY_TURNS]
    )
    history = list(reversed(recent_messages))
    Message.objects.create(
        conversation=conversation,
        role='user',
        content=question,
    )
    return conversation, history


def _conversation_payload(conversation, messages):
    """One response shape for both ask and history, so clients need one parser."""
    return {
        'id': conversation.id,
        'article': conversation.article_id,
        'article_title': conversation.article.title,
        'created_at': conversation.created_at,
        'messages': [
            {
                'id': message.id,
                'role': message.role,
                'content': message.content,
                'created_at': message.created_at,
            }
            for message in messages
        ],
    }


class AskArticleView(APIView):
    permission_classes = [IsAuthenticated]
    # These routes spend provider money on every request, so each is capped per
    # user. See `throttling.py` for why both windows exist.
    throttle_classes = [ChatBurstThrottle, ChatDailyThrottle]

    @extend_schema(
        request=AskQuestionSerializer,
        responses={200: ConversationSerializer},
        summary='Ask the learning assistant about an article',
    )
    def post(self, request, slug):
        article = _published_article(slug)

        # The assistant answers *from* the article's indexed content, so this
        # route is a full-text back door unless it consults the same gate as
        # the article itself.
        if not can_read_article(request.user, article):
            return Response(
                {'detail': PAID_ARTICLE_MESSAGE},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        conversation, history = _prepare_question(request, article, question)

        try:
            answer = answer_question(article, question, history=history)
        except ChatServiceError as exc:
            # Surface the real reason instead of a generic apology with a 200:
            # the client can then tell the user whether to retry.
            logger.warning('RAG chat unavailable for article %s: %s', article.slug, exc)
            return Response(
                {'detail': str(exc), 'code': 'chat_unavailable'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception('Unexpected RAG chat failure for article %s', article.slug)
            return Response(
                {'detail': 'The assistant is temporarily unavailable. Please try again.',
                 'code': 'chat_error'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        Message.objects.create(
            conversation=conversation,
            role='assistant',
            content=answer,
        )

        messages = list(conversation.messages.order_by('created_at'))
        return Response(_conversation_payload(conversation, messages))


class ConversationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: ConversationSerializer},
        summary='Fetch the current user conversation for an article',
    )
    def get(self, request, slug):
        article = _published_article(slug)

        # Stored replies quote the article, so the history is content too. A
        # reader whose access has lapsed must not read it back through here.
        if not can_read_article(request.user, article):
            return Response(
                {'detail': PAID_ARTICLE_MESSAGE},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        conversation = Conversation.objects.filter(
            user=request.user, article=article
        ).first()

        if not conversation:
            return Response({
                'id': None,
                'article': article.id,
                'article_title': article.title,
                'created_at': None,
                'messages': [],
            })

        messages = list(conversation.messages.order_by('created_at'))
        return Response(_conversation_payload(conversation, messages))


def _sse(payload):
    """One server-sent event frame.

    Only `data:` is used: the client parses the JSON payload and ignores the
    event name, so a reply and a terminal error travel through one parser.
    """
    return 'data: ' + json.dumps(payload, cls=DjangoJSONEncoder) + '\n\n'


def _stream_events(article, conversation, first, pieces):
    """Yield the rest of the reply, then the saved conversation.

    The reply is written to the database only after it has been fully streamed.
    A reader who closes the drawer mid-answer leaves the question on record and
    no assistant row, which is the same state a failed non-streaming ask leaves
    — and better than storing half a sentence as if it were the answer.
    """
    answer = first
    yield _sse({'type': 'delta', 'text': first})

    try:
        for piece in pieces:
            answer += piece
            yield _sse({'type': 'delta', 'text': piece})
    except ChatServiceError as exc:
        logger.warning('Streamed RAG chat unavailable for article %s: %s', article.slug, exc)
        yield _sse({'type': 'error', 'detail': str(exc), 'code': 'chat_unavailable'})
        return
    except Exception:
        logger.exception('Unexpected streamed RAG chat failure for article %s', article.slug)
        yield _sse({
            'type': 'error',
            'detail': 'The assistant was interrupted. Please ask again.',
            'code': 'chat_error',
        })
        return

    Message.objects.create(
        conversation=conversation,
        role='assistant',
        content=answer,
    )
    messages = list(conversation.messages.order_by('created_at'))
    yield _sse({'type': 'done', 'conversation': _conversation_payload(conversation, messages)})


class EventStreamNegotiation(DefaultContentNegotiation):
    """Let a client ask for `text/event-stream` and still reach the handler.

    DRF negotiates against its renderers *before* the view method runs, and
    those renderers only know JSON. A browser sending `Accept: text/event-stream`
    was therefore answered 406 — the SSE endpoint never got the chance to reply
    in the media type it exists to serve. The body is built by hand rather than
    rendered, so an Accept header no renderer claims is not a failure here:
    fall back to the first renderer, which is the JSON one a refused request
    (402/404/503) still needs.
    """

    def select_renderer(self, request, renderers, format_suffix=None):
        try:
            return super().select_renderer(request, renderers, format_suffix)
        except NotAcceptable:
            return renderers[0], renderers[0].media_type


class AskArticleStreamView(APIView):
    """The same assistant as `AskArticleView`, replying in pieces.

    A stream cannot change its own status once the body has started, so the
    first chunk is pulled here, before the response is handed back. A provider
    that is down therefore still answers 503 (the wording the frontend already
    maps to "not configured or temporarily unavailable") instead of a 200 whose
    only content is an apology. Failures *after* the first chunk travel in-band
    as an `error` event, because 200 has already been sent.
    """

    permission_classes = [IsAuthenticated]
    content_negotiation_class = EventStreamNegotiation
    # The same budget as the whole-answer route: asking in pieces must not buy a
    # second allowance.
    throttle_classes = [ChatBurstThrottle, ChatDailyThrottle]

    @extend_schema(
        request=AskQuestionSerializer,
        responses={(200, 'text/event-stream'): OpenApiTypes.STR},
        summary='Ask the learning assistant about an article, streamed',
        description=(
            'Server-sent events. Each frame is a JSON object in a `data:` line: '
            '`{"type": "delta", "text": ...}` for part of the reply, '
            '`{"type": "done", "conversation": ...}` as the last frame (the '
            'same payload as `GET .../conversation/`), or '
            '`{"type": "error", "detail": ..., "code": ...}` if the provider '
            'failed after the reply had begun.'
        ),
    )
    def post(self, request, slug):
        article = _published_article(slug)

        # Same gate as the whole-answer route: the reply is written from the
        # article's indexed body, so an unpaid reader must not reach it here.
        if not can_read_article(request.user, article):
            return Response(
                {'detail': PAID_ARTICLE_MESSAGE},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data['question']

        conversation, history = _prepare_question(request, article, question)

        try:
            pieces = stream_answer(article, question, history=history)
            first = next(pieces)
        except StopIteration:
            return Response(
                {'detail': 'The assistant did not return an answer. Please try again.',
                 'code': 'chat_error'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ChatServiceError as exc:
            logger.warning('RAG chat unavailable for article %s: %s', article.slug, exc)
            return Response(
                {'detail': str(exc), 'code': 'chat_unavailable'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception('Unexpected RAG chat failure for article %s', article.slug)
            return Response(
                {'detail': 'The assistant is temporarily unavailable. Please try again.',
                 'code': 'chat_error'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response = StreamingHttpResponse(
            _stream_events(article, conversation, first, pieces),
            content_type='text/event-stream',
        )
        # A cached or proxy-buffered stream is not a stream: nginx honours
        # X-Accel-Buffering, and no-store keeps a shared cache out of it.
        response['Cache-Control'] = 'no-cache, no-store'
        response['X-Accel-Buffering'] = 'no'
        return response
