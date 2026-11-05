from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from rest_framework.test import APITestCase

from apps.chatbot.llm import LLMServiceError

from .models import Article, QuizQuestion
from .quiz_ai import (
    DraftQuestion,
    DraftQuiz,
    QuizGenerationError,
    draft_questions,
    generate_quiz_questions,
)


ARTICLE_TEXT = (
    'A hash map stores key-value pairs and gives average O(1) lookup time. '
    'It handles collisions by chaining entries in a bucket.'
)
CONFIGURED_MODEL = 'gemini-test-model'


def make_article(**overrides):
    values = {
        'title': 'Hash Maps',
        'slug': 'hash-maps',
        'content': {'blocks': [
            {'type': 'paragraph', 'data': {'text': ARTICLE_TEXT}},
        ]},
        'is_published': True,
    }
    values.update(overrides)
    return Article.objects.create(**values)


def make_draft(
    prompt='What is the average lookup time of a hash map?',
    *,
    options=None,
    correct_index=0,
    evidence='A hash map stores key-value pairs and gives average O(1) lookup time.',
    explanation='The article states that lookup is O(1) on average.',
):
    return DraftQuestion(
        prompt=prompt,
        options=options or ['O(1)', 'O(n)', 'O(log n)', 'O(n log n)'],
        correct_index=correct_index,
        explanation=explanation,
        evidence=evidence,
    )


@override_settings(GEMINI_MODEL=CONFIGURED_MODEL)
class QuizGenerationServiceTests(TestCase):
    def setUp(self):
        self.article = make_article()

    def test_generation_stores_inactive_ai_rows(self):
        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            created, rejected = generate_quiz_questions(self.article)

        self.assertEqual(len(created), 1)
        self.assertEqual(rejected, 0)
        question = self.article.quiz_questions.get()
        self.assertEqual(question.source, QuizQuestion.SOURCE_AI)
        self.assertEqual(question.ai_model, CONFIGURED_MODEL)
        self.assertFalse(question.is_active)

    def test_activate_makes_the_rows_reader_visible(self):
        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            created, _ = generate_quiz_questions(self.article, activate=True)

        self.assertTrue(created[0].is_active)
        self.assertEqual(self.article.quiz_questions.filter(is_active=True).count(), 1)

    def test_an_unverifiable_evidence_quote_is_rejected(self):
        drafts = [
            make_draft('What is O(1) worth?'),
            make_draft(
                'Which collision strategy is mentioned?',
                evidence='The article recommends open addressing.',
            ),
        ]
        with patch('apps.articles.quiz_ai.draft_questions', return_value=drafts):
            created, rejected = generate_quiz_questions(self.article)

        self.assertEqual(len(created), 1)
        self.assertEqual(rejected, 1)
        self.assertEqual(self.article.quiz_questions.count(), 1)

    def test_duplicate_prompts_inside_one_batch_are_rejected(self):
        drafts = [make_draft(), make_draft()]
        with patch('apps.articles.quiz_ai.draft_questions', return_value=drafts):
            created, rejected = generate_quiz_questions(self.article)

        self.assertEqual(len(created), 1)
        self.assertEqual(rejected, 1)

    def test_an_existing_prompt_is_not_generated_again(self):
        QuizQuestion.objects.create(
            article=self.article,
            prompt=make_draft().prompt,
            option_a='A', option_b='B', option_c='C', option_d='D',
            correct_option=0,
        )
        drafts = [
            make_draft(),
            make_draft('How are collisions handled?', evidence='It handles collisions by chaining entries in a bucket.'),
        ]

        with patch('apps.articles.quiz_ai.draft_questions', return_value=drafts):
            created, rejected = generate_quiz_questions(self.article)

        self.assertEqual(len(created), 1)
        self.assertEqual(rejected, 1)
        self.assertEqual(self.article.quiz_questions.count(), 2)

    def test_count_caps_the_number_of_accepted_questions(self):
        drafts = [
            make_draft('Question one about lookup?'),
            make_draft('Question two about storage?'),
            make_draft('Question three about collisions?'),
        ]
        with patch('apps.articles.quiz_ai.draft_questions', return_value=drafts):
            created, rejected = generate_quiz_questions(self.article, count=2)

        self.assertEqual(len(created), 2)
        self.assertEqual(rejected, 0)
        self.assertEqual(self.article.quiz_questions.count(), 2)

    def test_replace_ai_removes_only_ai_rows(self):
        manual = QuizQuestion.objects.create(
            article=self.article,
            prompt='Hand-written question?',
            option_a='A', option_b='B', option_c='C', option_d='D',
            correct_option=0,
            source=QuizQuestion.SOURCE_MANUAL,
        )
        old_ai = QuizQuestion.objects.create(
            article=self.article,
            prompt=make_draft().prompt,
            option_a='A', option_b='B', option_c='C', option_d='D',
            correct_option=0,
            source=QuizQuestion.SOURCE_AI,
            ai_model='old-model',
        )

        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            created, _ = generate_quiz_questions(self.article, replace_ai=True)

        self.assertTrue(QuizQuestion.objects.filter(pk=manual.pk).exists())
        self.assertFalse(QuizQuestion.objects.filter(pk=old_ai.pk).exists())
        self.assertEqual(self.article.quiz_questions.count(), 2)
        self.assertEqual(created[0].prompt, make_draft().prompt)

    def test_append_keeps_existing_ai_rows(self):
        old_ai = QuizQuestion.objects.create(
            article=self.article,
            prompt='An older AI question?',
            option_a='A', option_b='B', option_c='C', option_d='D',
            correct_option=0,
            source=QuizQuestion.SOURCE_AI,
        )
        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            generate_quiz_questions(self.article)

        self.assertTrue(QuizQuestion.objects.filter(pk=old_ai.pk).exists())
        self.assertEqual(self.article.quiz_questions.count(), 2)

    def test_an_empty_article_is_rejected_without_calling_the_model(self):
        empty = make_article(slug='empty', content={'blocks': []})

        with patch('apps.articles.quiz_ai.draft_questions') as generator:
            with self.assertRaises(QuizGenerationError) as raised:
                generate_quiz_questions(empty)

        self.assertEqual(raised.exception.status_code, 400)
        generator.assert_not_called()

    def test_count_outside_the_allowed_range_is_rejected(self):
        for count in (0, 21):
            with self.subTest(count=count):
                with self.assertRaises(QuizGenerationError) as raised:
                    generate_quiz_questions(self.article, count)
                self.assertEqual(raised.exception.status_code, 400)


@override_settings(GEMINI_MODEL=CONFIGURED_MODEL)
class DraftQuestionsTests(TestCase):
    def setUp(self):
        self.article = make_article()

    @patch('apps.articles.quiz_ai.build_llm')
    def test_prompt_contains_the_article_and_uses_structured_output(self, build_llm):
        structured = build_llm.return_value.with_structured_output.return_value
        structured.invoke.return_value = DraftQuiz(questions=[make_draft()])

        result = draft_questions(self.article, 1)

        self.assertEqual(len(result), 1)
        build_llm.assert_called_once_with(temperature=0.2, timeout=25, max_retries=0)
        build_llm.return_value.with_structured_output.assert_called_once_with(DraftQuiz)
        prompt = structured.invoke.call_args[0][0]
        self.assertIn('Hash Maps', prompt)
        self.assertIn('average O(1) lookup time', prompt)
        self.assertIn('Write 1 question(s)', prompt)

    @patch('apps.articles.quiz_ai.build_llm', side_effect=LLMServiceError('missing key'))
    def test_missing_configuration_is_a_503(self, build_llm):
        with self.assertRaises(QuizGenerationError) as raised:
            draft_questions(self.article)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn('not configured', str(raised.exception))

    @patch('apps.articles.quiz_ai.build_llm')
    def test_provider_failure_is_a_503(self, build_llm):
        build_llm.return_value.with_structured_output.return_value.invoke.side_effect = RuntimeError('boom')

        with self.assertRaises(QuizGenerationError) as raised:
            draft_questions(self.article)

        self.assertEqual(raised.exception.status_code, 503)

    @patch('apps.articles.quiz_ai.build_llm')
    def test_unexpected_output_shape_is_a_502(self, build_llm):
        build_llm.return_value.with_structured_output.return_value.invoke.return_value = 'not a quiz'

        with self.assertRaises(QuizGenerationError) as raised:
            draft_questions(self.article)

        self.assertEqual(raised.exception.status_code, 502)


@override_settings(GEMINI_MODEL=CONFIGURED_MODEL)
class QuizGenerationEndpointTests(APITestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email='staff@example.com',
            username='staff',
            password='password',
            is_staff=True,
        )
        self.other_staff = get_user_model().objects.create_user(
            email='other@example.com',
            username='other',
            password='password',
            is_staff=True,
        )
        self.reader = get_user_model().objects.create_user(
            email='reader@example.com',
            username='reader',
            password='password',
        )
        self.article = make_article(author=self.staff)
        self.url = f'/api/articles/{self.article.slug}/quiz/generate/'

    def test_endpoint_is_admin_only_and_author_scoped(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)

        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.post(self.url).status_code, 403)

        self.client.force_authenticate(self.other_staff)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_endpoint_returns_the_generated_questions(self):
        QuizQuestion.objects.create(
            article=self.article,
            prompt='An existing active question?',
            option_a='A', option_b='B', option_c='C', option_d='D',
            correct_option=0,
            is_active=True,
        )
        self.client.force_authenticate(self.staff)

        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['rejected'], 0)
        self.assertEqual(response.data['active_count'], 1)
        question = response.data['questions'][0]
        self.assertEqual(question['source'], QuizQuestion.SOURCE_AI)
        self.assertEqual(question['ai_model'], CONFIGURED_MODEL)
        self.assertFalse(question['is_active'])
        self.assertIn('correct_option', question)

    def test_activate_is_honoured(self):
        self.client.force_authenticate(self.staff)

        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            response = self.client.post(self.url, {'activate': True}, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['questions'][0]['is_active'])
        self.assertEqual(response.data['active_count'], 1)

    def test_invalid_count_is_a_400(self):
        self.client.force_authenticate(self.staff)
        for count in (0, 21):
            with self.subTest(count=count):
                response = self.client.post(self.url, {'count': count}, format='json')
                self.assertEqual(response.status_code, 400)

    def test_unusable_model_output_is_a_502(self):
        self.client.force_authenticate(self.staff)

        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft(evidence='This sentence is not in the article.')],
        ):
            response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, 502)
        self.assertIn('detail', response.data)

    def test_public_quiz_never_generates(self):
        self.assertEqual(
            self.client.get(f'/api/articles/{self.article.slug}/quiz/').status_code,
            200,
        )
        self.assertEqual(self.article.quiz_questions.count(), 0)


@override_settings(GEMINI_MODEL=CONFIGURED_MODEL)
class GenerateQuizCommandTests(TestCase):
    def setUp(self):
        self.article = make_article()

    def test_command_generates_inactive_questions(self):
        with patch(
            'apps.articles.quiz_ai.draft_questions',
            return_value=[make_draft()],
        ):
            output = StringIO()
            call_command('generate_quiz', self.article.slug, stdout=output)

        self.assertEqual(self.article.quiz_questions.count(), 1)
        self.assertIn('Generated 1 question(s)', output.getvalue())
        self.assertIn('inactive', output.getvalue())

    def test_command_rejects_a_bad_count(self):
        with self.assertRaises(CommandError):
            call_command('generate_quiz', self.article.slug, count=0)

    def test_command_rejects_an_unknown_slug(self):
        with self.assertRaises(CommandError):
            call_command('generate_quiz', 'does-not-exist')
