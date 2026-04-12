from django.db import models
from django.conf import settings
from apps.articles.models import Category

# Create your models here.

class Problem(models.Model):
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=255)
    description = models.TextField()
    difficulty = models.CharField(
        max_length=10,
        choices=DIFFICULTY_CHOICES,
        default='easy'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='problems'
    )
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ['difficulty', 'title']

    def __str__(self):
        return self.title


class TestCase(models.Model):
    problem = models.ForeignKey(
        Problem,
        on_delete=models.CASCADE,
        related_name='test_cases'
    )
    input = models.TextField()
    expected_output = models.TextField()
    is_hidden = models.BooleanField(default=False)

    def __str__(self):
        return f"TestCase for {self.problem.title}"


class Submission(models.Model):
    VERDICT_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('wrong_answer', 'Wrong Answer'),
        ('runtime_error', 'Runtime Error'),
        ('time_limit', 'Time Limit Exceeded'),
    ]

    problem = models.ForeignKey(
        Problem,
        on_delete=models.CASCADE,
        related_name='submissions'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='submissions'
    )
    language = models.CharField(max_length=30)
    code = models.TextField()
    verdict = models.CharField(
        max_length=20,
        choices=VERDICT_CHOICES,
        default='pending'
    )
    runtime_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']