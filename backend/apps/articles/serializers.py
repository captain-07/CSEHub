import re

from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field

from .models import (
    Category, Tag, Article, ArticleReaction, CodeSnippet, QuizQuestion,
    SUPPORTED_BLOCK_TYPES, REACTION_LIKE, REACTION_DISLIKE, REACTION_NONE,
)
from .quiz_ai import DEFAULT_QUESTION_COUNT, MAX_QUESTIONS_PER_REQUEST


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']


class TagSerializer(serializers.ModelSerializer):
    """A tag and the single category it belongs to.

    Reads carry the category nested so a client can group tags without a second
    request; writes pass `category_id`, because a nested serializer would make
    the write shape ambiguous with the read shape. `category_id` is required —
    a tag cannot exist without a category.
    """

    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source='category',
        queryset=Category.objects.all(),
        write_only=True,
    )

    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug', 'category', 'category_id']


class CodeSnippetSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeSnippet
        fields = ['language', 'code', 'order']


def article_author_name(article):
    """Public byline for an article, or None when it has no author.

    The name is always derived server-side: `display_name` when the author set
    one, otherwise the username, and only as a last resort the email. The FK is
    nullable, so every consumer must tolerate a null byline.
    """
    author = article.author
    if not author:
        return None
    return author.display_name or author.username or author.email


# Word count is derived server-side because cards are built from the *list*
# endpoint, which omits `content` on purpose (see `ArticleListSerializer`). The
# client used to compute this from `article.content`, which is absent from list
# payloads, so the reading time silently never rendered on any card.
_WORDS_PER_MINUTE = 200
_HTML_BREAK_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^>]*>')


def _plain_text(value):
    """Inline HTML -> plain text, mirroring `renderer.stripInlineHtml`."""
    text = _HTML_BREAK_RE.sub(' ', str(value))
    text = _HTML_TAG_RE.sub('', text)
    return ' '.join(text.split())


def _content_words(content):
    """Word count of an Editor.js document, mirroring `renderer.contentToPlainText`."""
    parts = []

    def push(value):
        text = _plain_text(value)
        if text:
            parts.append(text)

    if isinstance(content, str):
        push(content)
    elif isinstance(content, dict):
        blocks = content.get('blocks')
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                data = block.get('data')
                if not isinstance(data, dict):
                    continue
                if isinstance(data.get('text'), str):
                    push(data['text'])
                elif isinstance(data.get('code'), str):
                    if data['code'].strip():
                        parts.append(data['code'])
                elif isinstance(data.get('items'), list):
                    for item in data['items']:
                        push(item.get('content') if isinstance(item, dict) else item)
                elif isinstance(data.get('caption'), str):
                    push(data['caption'])
                elif isinstance(data.get('url'), str):
                    push(data['url'])

    return len(' '.join(parts).split())


def article_reading_time(content):
    """Approximate reading time ("5 min read"), or None when there is no text.

    `int(x + 0.5)` reproduces JavaScript's `Math.round` so the label matches the
    client fallback at exact half-minute boundaries, where Python's banker's
    rounding would round the other way.
    """
    words = _content_words(content)
    if not words:
        return None
    minutes = max(1, int(words / _WORDS_PER_MINUTE + 0.5))
    return f'{minutes} min read'


# Both read serializers expose the byline. Cards are built from the *list*
# endpoint, so restricting it to the detail serializer silently guarantees that
# article grids can never show an author regardless of what the database holds.
# The fields are repeated rather than mixed in because DRF's metaclass only
# collects declared fields from classes it built, so a plain mixin contributes
# nothing and `author_name` would be treated as a model field.
class ArticleListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    author_email = serializers.EmailField(source='author.email', read_only=True, default=None)
    author_name = serializers.SerializerMethodField()
    reading_time = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['id', 'title', 'slug', 'excerpt', 'featured_image', 'video_url', 'category', 'tags',
                  'author_name', 'author_email', 'reading_time',
                  'like_count', 'dislike_count', 'view_count',
                  'is_published', 'is_featured', 'created_at', 'updated_at']
        # The tallies are derived from ArticleReaction rows by the manager, and
        # `view_count` is written only by `Article.record_view`. They are
        # declared read-only explicitly rather than relying on the serializer
        # never being used for writes, so that adding them here cannot quietly
        # turn them into client-settable fields on a future write serializer.
        read_only_fields = ['like_count', 'dislike_count', 'view_count']

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_author_name(self, article):
        return article_author_name(article)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reading_time(self, article):
        return article_reading_time(article.content)


class ArticleDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    code_snippets = CodeSnippetSerializer(many=True, read_only=True)
    author_email = serializers.EmailField(source='author.email', read_only=True, default=None)
    author_name = serializers.SerializerMethodField()
    reading_time = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()
    # Lets the article page hide the "Quiz me" button when an article has no
    # questions. One extra query on the detail route, not on the list route.
    quiz_question_count = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'excerpt', 'featured_image', 'video_url', 'content', 'category',
            'tags', 'code_snippets', 'author_name', 'author_email', 'reading_time',
            'like_count', 'dislike_count', 'view_count', 'my_reaction', 'quiz_question_count',
            'is_published', 'is_featured', 'created_at', 'updated_at'
        ]
        read_only_fields = ['like_count', 'dislike_count', 'view_count']

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_author_name(self, article):
        return article_author_name(article)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reading_time(self, article):
        return article_reading_time(article.content)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_my_reaction(self, article):
        """The requesting reader's own verdict, so the UI can highlight it.

        Null for anonymous callers and for readers who have not reacted. Only on
        the detail serializer: resolving this needs a query per article, which
        would turn the list endpoint into an N+1 on a page that shows 20 rows.
        """
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return None
        return article.reactions.filter(user=user).values_list('value', flat=True).first()

    @extend_schema_field(serializers.IntegerField())
    def get_quiz_question_count(self, article):
        return article.quiz_questions.filter(is_active=True).count()


class ArticleReactionSerializer(serializers.ModelSerializer):
    """A reader's stored verdict. Read-only; writes go through `set_reaction`."""

    class Meta:
        model = ArticleReaction
        fields = ['id', 'value', 'created_at', 'updated_at']
        read_only_fields = fields


class ReactionResultSerializer(serializers.Serializer):
    """What `react` returns: the verdict now stored plus fresh tallies.

    The counts come back with every reaction so the UI never has to re-fetch the
    article to settle its buttons.
    """

    value = serializers.ChoiceField(choices=[REACTION_LIKE, REACTION_DISLIKE], allow_null=True)
    like_count = serializers.IntegerField()
    dislike_count = serializers.IntegerField()


class ViewResultSerializer(serializers.Serializer):
    """What `view` returns: the tally as it now stands.

    Returned so the reader's page can settle its own counter without a second
    fetch — the byline renders the number the detail request carried, which is
    one behind by the time this response lands.
    """

    view_count = serializers.IntegerField()


class QuizOptionSerializer(serializers.Serializer):
    """One option as the reader sees it. `id` is the stored option index."""

    id = serializers.IntegerField()
    text = serializers.CharField()


class QuizQuestionPublicSerializer(serializers.Serializer):
    """A question as the reader receives it.

    It deliberately has no `correct_option` and no `explanation`: the answer key
    is only sent by the grading response, after the reader has committed to an
    answer. The options arrive shuffled, so their order carries no signal.
    """

    id = serializers.IntegerField()
    prompt = serializers.CharField()
    options = QuizOptionSerializer(many=True)


class QuizPayloadSerializer(serializers.Serializer):
    """Body of `GET /api/articles/<slug>/quiz/`."""

    questions = QuizQuestionPublicSerializer(many=True)
    total = serializers.IntegerField()


class QuizAnswerSerializer(serializers.Serializer):
    question_id = serializers.IntegerField()
    option_id = serializers.IntegerField(min_value=0, max_value=3)


class QuizSubmissionSerializer(serializers.Serializer):
    """Body of `POST /api/articles/<slug>/quiz/submit/`.

    The client sends only the questions it was shown. Each question may appear
    once, and every id must belong to the article being graded.
    """

    answers = QuizAnswerSerializer(many=True, allow_empty=False)


class QuizAnswerResultSerializer(serializers.Serializer):
    question_id = serializers.IntegerField()
    chosen_option_id = serializers.IntegerField()
    correct_option_id = serializers.IntegerField()
    is_correct = serializers.BooleanField()
    explanation = serializers.CharField(allow_blank=True)


class QuizResultSerializer(serializers.Serializer):
    """What `quiz/submit/` returns. Nothing is persisted."""

    score = serializers.IntegerField()
    total = serializers.IntegerField()
    percent = serializers.IntegerField()
    results = QuizAnswerResultSerializer(many=True)


class QuizGenerationRequestSerializer(serializers.Serializer):
    """Body of `POST /api/articles/<slug>/quiz/generate/`.

    `replace` removes only AI-generated rows; hand-written questions are never
    touched. `activate` is explicit because the default is to leave drafts
    inactive for review.
    """

    count = serializers.IntegerField(
        min_value=1,
        max_value=MAX_QUESTIONS_PER_REQUEST,
        default=DEFAULT_QUESTION_COUNT,
    )
    replace = serializers.BooleanField(default=False)
    activate = serializers.BooleanField(default=False)


class QuizQuestionAdminSerializer(serializers.ModelSerializer):
    """A quiz question including its answer key, for the editor only.

    This serializer is also the write shape for the review panel. `source` and
    `ai_model` are read-only because they record provenance, not editorial
    intent: an editor may rewrite an AI draft, but must not be able to pass it
    off as hand-written or forge the model id.
    """

    class Meta:
        model = QuizQuestion
        fields = [
            'id', 'prompt', 'option_a', 'option_b', 'option_c', 'option_d',
            'correct_option', 'explanation', 'source', 'ai_model', 'is_active',
        ]
        read_only_fields = ['id', 'source', 'ai_model']

    def update(self, instance, validated_data):
        # `ModelSerializer` validates field types but never calls the model's
        # `clean()`. Without this, a PATCH could make two options identical even
        # though the Django admin and the AI generator both reject that.
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                getattr(exc, 'message_dict', None) or exc.messages
            )
        instance.save()
        return instance


class QuizReviewPayloadSerializer(serializers.Serializer):
    """What `quiz/review/` returns: every row, including inactive drafts."""

    questions = QuizQuestionAdminSerializer(many=True)
    total = serializers.IntegerField()
    active_count = serializers.IntegerField()


class QuizGenerationResultSerializer(serializers.Serializer):
    """What `quiz/generate/` returns.

    `active_count` lets the editor see whether the reader-facing quiz actually
    exists yet; generated rows are inactive by default, so `created` alone
    would look like the quiz is live when it is not.
    """

    created = serializers.IntegerField()
    rejected = serializers.IntegerField()
    active_count = serializers.IntegerField()
    questions = QuizQuestionAdminSerializer(many=True)


class ReactionRequestSerializer(serializers.Serializer):
    """Body of `POST /api/articles/<slug>/react/`.

    `none` clears the reaction rather than storing a third state. The client
    states the verdict it wants instead of asking for a toggle, so a duplicated
    or retried request converges instead of flipping the reaction twice.
    """

    value = serializers.ChoiceField(choices=[REACTION_LIKE, REACTION_DISLIKE, REACTION_NONE])


class ArticleWriteSerializer(serializers.ModelSerializer):
    """Staff-facing representation with explicit writable relationships."""

    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False, allow_null=True
    )
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    code_snippets = CodeSnippetSerializer(many=True, required=False)
    slug = serializers.CharField(required=False, allow_blank=True, max_length=255)
    # Gated by `_reject_author_reassignment`: a plain admin sending this is
    # refused, because writes are scoped to the article's own author and a
    # writable `author` would otherwise let any admin PATCH someone else's
    # article to reassign it to themselves and thereby acquire write access.
    # Only a superuser may reassign.
    author = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'excerpt', 'featured_image', 'video_url', 'content', 'category', 'tags',
            'code_snippets', 'author', 'is_published', 'is_featured', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_code_snippets(self, snippets):
        orders = [snippet.get('order', 0) for snippet in snippets]
        if len(orders) != len(set(orders)):
            raise serializers.ValidationError('Each code snippet must have a unique order.')
        return snippets

    def _reject_author_reassignment(self):
        """Refuse a client-supplied `author` unless a superuser sent it.

        The field is read-only, so DRF would silently drop the value and report
        a 200 while the byline never changed. That is the worst outcome: an
        editor who believes they handed an article to a colleague has not.
        """
        if 'author' not in self.initial_data:
            return
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated and user.is_superuser):
            raise serializers.ValidationError({
                'author': 'Only a superuser can reassign an article to a different author.'
            })

    def validate(self, attrs):
        """Derive a unique slug when the client leaves it blank.

        On a partial update neither title nor slug may be present, so the
        existing slug is retained rather than demanding one from the client.
        """
        self._reject_author_reassignment()
        slug = (attrs.get('slug') or '').strip()
        title = (attrs.get('title') or '').strip()

        if self.instance is not None and not slug and not title:
            return attrs

        if not slug and title:
            slug = slugify(title)[:255]
        if not slug:
            raise serializers.ValidationError({'slug': 'A slug or a title is required.'})

        queryset = Article.objects.filter(slug=slug)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            base, suffix = slug, 2
            while Article.objects.filter(slug=f'{base}-{suffix}').exists():
                suffix += 1
            slug = f'{base}-{suffix}'
        attrs['slug'] = slug
        return attrs

    def validate_content(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Content must be an Editor.js document object.')
        blocks = value.get('blocks')
        if not isinstance(blocks, list):
            raise serializers.ValidationError('Content must include a blocks array.')
        if len(blocks) > 500:
            raise serializers.ValidationError('Content has too many blocks.')
        for block in blocks:
            if not isinstance(block, dict) or block.get('type') not in SUPPORTED_BLOCK_TYPES or not isinstance(block.get('data'), dict):
                raise serializers.ValidationError('Content contains an unsupported or malformed Editor.js block.')
        return value

    @transaction.atomic
    def create(self, validated_data):
        tags = validated_data.pop('tags', [])
        snippets = validated_data.pop('code_snippets', [])
        article = Article.objects.create(**validated_data)
        article.tags.set(tags)
        CodeSnippet.objects.bulk_create(
            [CodeSnippet(article=article, **snippet) for snippet in snippets]
        )
        return article

    @transaction.atomic
    def update(self, instance, validated_data):
        tags = validated_data.pop('tags', None)
        snippets = validated_data.pop('code_snippets', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        if snippets is not None:
            instance.code_snippets.all().delete()
            CodeSnippet.objects.bulk_create(
                [CodeSnippet(article=instance, **snippet) for snippet in snippets]
            )
        return instance
