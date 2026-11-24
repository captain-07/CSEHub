"""Report what a chat model can actually do before a setting depends on it.

The assistant relies on four capabilities, and a model can fail any of them
independently: plain generation, a system instruction, streaming, and — for
quiz generation — structured output. Google retires and renames model ids
without warning, and an open-weight family such as Gemma is served through the
same endpoint with a smaller feature set, so "it exists" is not "it works here".

Run this against a candidate before pointing `GEMINI_CHAT_MODEL` or
`GEMINI_QUIZ_MODEL` at it:

    python backend/manage.py check_llm --model <id>

It exits non-zero if any capability is missing, so it is also usable in a
deploy step.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from apps.chatbot.llm import LLMServiceError, build_llm
from apps.chatbot.rag_chat import chunk_text


class _Probe(BaseModel):
    """The smallest structured response that proves schema support."""

    answer: str = Field(description="The single word the prompt asked for.")


class Command(BaseCommand):
    help = 'Probe a model for the capabilities the assistant depends on.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            default=settings.GEMINI_CHAT_MODEL,
            help='Model id to probe (default: GEMINI_CHAT_MODEL).',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=30,
            help='Seconds to allow each provider call.',
        )

    def handle(self, *args, **options):
        model = options['model']
        self.stdout.write(f'Probing {model}…\n')

        checks = (
            ('generation', self._check_generation),
            ('system instruction', self._check_system_instruction),
            ('streaming', self._check_streaming),
            ('structured output', self._check_structured_output),
        )

        failed = []
        for name, check in checks:
            started = time.monotonic()
            try:
                detail = check(model, options['timeout'])
            except Exception as exc:
                failed.append(name)
                self.stdout.write(self.style.ERROR(
                    f'  FAIL  {name} ({time.monotonic() - started:.1f}s): {exc}'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'  ok    {name} ({time.monotonic() - started:.1f}s): {detail}'
                ))

        if failed:
            raise CommandError(
                'Missing capability: ' + ', '.join(failed) + '. '
                'Keep the feature that needs it on a model that passes.'
            )

        self.stdout.write(self.style.SUCCESS(f'\n{model} is usable for chat.'))

    # -- checks -------------------------------------------------------------

    def _llm(self, model, timeout):
        # One attempt: a probe should report a failure, not wait through retries.
        return build_llm(model=model, timeout=timeout, max_retries=0)

    def _check_generation(self, model, timeout):
        llm = self._llm(model, timeout)
        response = self._retry(lambda: llm.invoke(
            [HumanMessage(content='Reply with the single word: ready.')]
        ))
        text = self._text(response)
        return f'replied {text[:40]!r}'

    def _check_system_instruction(self, model, timeout):
        llm = self._llm(model, timeout)
        response = self._retry(lambda: llm.invoke([
            SystemMessage(
                content='You are a parrot. When asked for the code word, answer '
                        'with exactly one word: pineapple.'
            ),
            HumanMessage(content='What is the code word?'),
        ]))
        text = self._text(response)
        if 'pineapple' not in text.lower():
            raise RuntimeError(
                f'ignored the system instruction (said {text[:60]!r}); '
                'set GEMINI_CHAT_SYSTEM_INSTRUCTION=False for this model'
            )
        return 'honoured'

    def _check_streaming(self, model, timeout):
        llm = self._llm(model, timeout)

        def first_text():
            for piece in llm.stream([HumanMessage(content='Count from one to three.')]):
                text = chunk_text(piece)
                if text.strip():
                    return text
            raise RuntimeError('the stream produced no text')

        return f'first chunk {self._retry(first_text)[:40]!r}'

    def _check_structured_output(self, model, timeout):
        llm = self._llm(model, timeout)
        result = self._retry(
            lambda: llm.with_structured_output(_Probe).invoke(
                'Reply with answer set to the single word: ready.'
            )
        )
        if not isinstance(result, _Probe):
            result = _Probe.model_validate(result)
        if not result.answer.strip():
            raise RuntimeError('returned an empty structured response')
        return f'answer={result.answer[:40]!r}'

    # -- helpers ------------------------------------------------------------

    def _retry(self, call):
        """Retry a transient 503; a missing capability is not transient.

        Google answers `503 UNAVAILABLE — high demand` for a model that is
        otherwise fine, and a probe that reports that as "unsupported" would
        send someone hunting for the wrong problem.
        """
        for attempt in range(3):
            try:
                return call()
            except Exception as exc:
                text = str(exc)
                transient = any(
                    token in text
                    for token in ('UNAVAILABLE', '503', '504', 'DEADLINE_EXCEEDED', 'timed out')
                )
                if not transient or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        raise AssertionError('unreachable')

    def _text(self, response):
        content = getattr(response, 'content', response)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = ''.join(
                item if isinstance(item, str)
                else item.get('text', '') if isinstance(item, dict) else ''
                for item in content
            )
        else:
            text = ''
        if not text.strip():
            raise LLMServiceError('the model returned an empty response')
        return text.strip()
