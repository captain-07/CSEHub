from django.contrib import admin
from .models import Problem, TestCase, Submission

# Register your models here.

@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = ['title', 'difficulty', 'category', 'is_published']
    list_filter = ['difficulty', 'category', 'is_published']
    search_fields = ['title']
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ['is_published']


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ['problem', 'is_hidden']
    list_filter = ['is_hidden', 'problem']


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'problem', 'verdict', 'language', 'created_at']
    list_filter = ['verdict', 'language']
    readonly_fields = ['created_at']