from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from rest_framework.test import APITestCase

from .models import Article, QuizQuestion


class QuizAPITests(APITestCase):
    """The hand-written quiz on an article.

    The contract defended here is small but load-bearing: the public payload
    must not contain the answer key, the reader gets a random subset on every
    request, and grading is stateless. Nothing writes an attempt row, so there
    is no "already taken" state to leak or to clean up.
    """

    def setUp(self):
        self.article = Article.objects.create(
            title='Public', slug='public', content={'blocks': []}, is_published=True
        )
        self.draft = Article.objects.create(
            title='Draft', slug='draft', content={'blocks': []}, is_published=False
        )

    def make_question(self, article=None, **overrides):
        values = {
            'article': article or self.article,
            'prompt': 'Which option is correct?',
            'option_a': 'Alpha',
            'option_b': 'Bravo',
            'option_c': 'Charlie',
            'option_d': 'Delta',
            'correct_option': 1,
            'explanation': 'Bravo is the correct one.',
        }
        values.update(overrides)
        return QuizQuestion.objects.create(**values)

    def quiz_url(self, article=None):
        article = article or self.article
        return f'/api/articles/{article.slug}/quiz/'

    def submit_url(self, article=None):
        article = article or self.article
        return f'/api/articles/{article.slug}/quiz/submit/'

    # --- reading -----------------------------------------------------------

    def test_quiz_is_public_and_never_exposes_the_answer_key(self):
        self.make_question()

        response = self.client.get(self.quiz_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 1)
        question = response.data['questions'][0]
        self.assertNotIn('correct_option', question)
        self.assertNotIn('explanation', question)
        self.assertEqual(len(question['options']), 4)
        for option in question['options']:
            self.assertNotIn('is_correct', option)

    def test_quiz_returns_a_random_subset_of_at_most_five(self):
        bank = [
            self.make_question(prompt=f'Question {index}')
            for index in range(12)
        ]

        response = self.client.get(self.quiz_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 5)
        question_ids = [question['id'] for question in response.data['questions']]
        self.assertEqual(len(question_ids), 5)
        self.assertEqual(len(set(question_ids)), 5)
        self.assertTrue(set(question_ids).issubset({question.pk for question in bank}))

    def test_quiz_returns_whatever_exists_when_there_are_fewer_than_five(self):
        self.make_question(prompt='One')
        self.make_question(prompt='Two')

        response = self.client.get(self.quiz_url())

        self.assertEqual(response.data['total'], 2)
        self.assertEqual(
            {question['prompt'] for question in response.data['questions']},
            {'One', 'Two'},
        )

    def test_inactive_questions_are_not_served(self):
        active = self.make_question(prompt='Shown')
        self.make_question(prompt='Hidden', is_active=False)

        response = self.client.get(self.quiz_url())

        self.assertEqual([question['id'] for question in response.data['questions']], [active.pk])

    def test_options_carry_the_stored_text_and_their_original_index(self):
        question = self.make_question()

        response = self.client.get(self.quiz_url())

        options = response.data['questions'][0]['options']
        self.assertEqual(
            {option['id']: option['text'] for option in options},
            {0: 'Alpha', 1: 'Bravo', 2: 'Charlie', 3: 'Delta'},
        )

    def test_a_draft_article_has_no_public_quiz(self):
        self.make_question(article=self.draft)

        self.assertEqual(self.client.get(self.quiz_url(self.draft)).status_code, 404)
        self.assertEqual(
            self.client.post(
                self.submit_url(self.draft),
                {'answers': [{'question_id': 1, 'option_id': 0}]},
                format='json',
            ).status_code,
            404,
        )

    # --- grading -----------------------------------------------------------

    def test_submit_grades_and_reveals_the_answer_key(self):
        correct = self.make_question(prompt='Correct one')
        wrong = self.make_question(
            prompt='Wrong one', option_a='A2', option_b='B2', option_c='C2', option_d='D2',
            correct_option=2,
        )

        response = self.client.post(
            self.submit_url(),
            {
                'answers': [
                    {'question_id': correct.pk, 'option_id': correct.correct_option},
                    {'question_id': wrong.pk, 'option_id': 0},
                ]
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['score'], 1)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['percent'], 50)
        self.assertNotIn('attempt_id', response.data)

        first, second = response.data['results']
        self.assertTrue(first['is_correct'])
        self.assertEqual(first['correct_option_id'], correct.correct_option)
        self.assertFalse(second['is_correct'])
        self.assertEqual(second['correct_option_id'], wrong.correct_option)
        self.assertEqual(second['explanation'], wrong.explanation)

    def test_submit_accepts_every_correct_answer(self):
        question = self.make_question()

        response = self.client.post(
            self.submit_url(),
            {'answers': [{'question_id': question.pk, 'option_id': question.correct_option}]},
            format='json',
        )

        self.assertEqual(response.data['score'], 1)
        self.assertEqual(response.data['percent'], 100)
        self.assertTrue(response.data['results'][0]['is_correct'])

    def test_submit_rejects_a_question_answered_twice(self):
        question = self.make_question()

        response = self.client.post(
            self.submit_url(),
            {
                'answers': [
                    {'question_id': question.pk, 'option_id': 0},
                    {'question_id': question.pk, 'option_id': 1},
                ]
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('answers', response.data)

    def test_submit_rejects_a_question_from_another_article(self):
        other = Article.objects.create(
            title='Other', slug='other', content={'blocks': []}, is_published=True
        )
        foreign = self.make_question(article=other)

        response = self.client.post(
            self.submit_url(),
            {'answers': [{'question_id': foreign.pk, 'option_id': 0}]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('answers', response.data)

    def test_submit_rejects_an_unknown_question(self):
        response = self.client.post(
            self.submit_url(),
            {'answers': [{'question_id': 999999, 'option_id': 0}]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('answers', response.data)

    def test_submit_rejects_an_out_of_range_option(self):
        question = self.make_question()

        response = self.client.post(
            self.submit_url(),
            {'answers': [{'question_id': question.pk, 'option_id': 4}]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_submit_rejects_an_empty_attempt(self):
        response = self.client.post(self.submit_url(), {'answers': []}, format='json')

        self.assertEqual(response.status_code, 400)

    def test_submit_rejects_more_answers_than_one_quiz_can_show(self):
        questions = [
            self.make_question(prompt=f'Question {index}')
            for index in range(6)
        ]

        response = self.client.post(
            self.submit_url(),
            {'answers': [
                {'question_id': question.pk, 'option_id': 0}
                for question in questions
            ]},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('answers', response.data)

    # --- article exposure --------------------------------------------------

    def test_article_detail_exposes_the_active_question_count(self):
        self.make_question()
        self.make_question(prompt='Second')
        self.make_question(prompt='Hidden', is_active=False)

        response = self.client.get(f'/api/articles/{self.article.slug}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['quiz_question_count'], 2)

    def test_article_detail_reports_zero_without_a_quiz(self):
        response = self.client.get(f'/api/articles/{self.article.slug}/')

        self.assertEqual(response.data['quiz_question_count'], 0)

    def test_the_list_endpoint_does_not_carry_the_quiz_count(self):
        """Cards do not render a quiz button, so this stays off the list route."""
        self.make_question()

        row = self.client.get('/api/articles/').data['results'][0]

        self.assertNotIn('quiz_question_count', row)


class QuizQuestionModelTests(TestCase):
    def setUp(self):
        self.article = Article.objects.create(
            title='Public', slug='public', content={'blocks': []}, is_published=True
        )

    def question(self, **overrides):
        values = {
            'article': self.article,
            'prompt': 'Question?',
            'option_a': 'A',
            'option_b': 'B',
            'option_c': 'C',
            'option_d': 'D',
            'correct_option': 0,
        }
        values.update(overrides)
        return QuizQuestion(**values)

    def test_all_four_options_are_required(self):
        with self.assertRaises(ValidationError):
            self.question(option_c='  ').full_clean()

    def test_options_must_be_distinct(self):
        with self.assertRaises(ValidationError):
            self.question(option_b='A', option_c='A', option_d='A').full_clean()

    def test_a_valid_question_passes_validation(self):
        self.question().full_clean()

    def test_the_database_caps_the_correct_option_index(self):
        """`choices` is a form-level check; this is the layer that holds even
        when a row is written by a script or a data migration."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.question(correct_option=4).save()

    def test_the_database_rejects_a_negative_option_index(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.question(correct_option=-1).save()


class SeedQuizTests(TestCase):
    """`build.sh` runs `seed` on every deploy, so the sample questions have to
    be valid four-option questions or the demo button ships broken."""

    def test_seed_adds_valid_questions_to_the_sample_articles(self):
        call_command('seed', stdout=StringIO(), stderr=StringIO())

        questions = QuizQuestion.objects.filter(article__slug='two-sum-explained')
        self.assertTrue(questions.exists())
        for question in questions:
            for field in QuizQuestion.OPTION_FIELDS:
                self.assertTrue(getattr(question, field).strip())
            self.assertIn(question.correct_option, range(4))

    def test_reseeding_does_not_duplicate_questions(self):
        call_command('seed', stdout=StringIO(), stderr=StringIO())
        before = QuizQuestion.objects.count()

        call_command('seed', stdout=StringIO(), stderr=StringIO())

        self.assertEqual(QuizQuestion.objects.count(), before)
