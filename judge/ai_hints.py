import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    'You are a programming tutor reviewing a competitive programming submission. '
    'Do NOT reveal the correct algorithm, solution, or give away the answer. '
    'Give a concise, guiding hint (2-4 sentences) that helps the student identify '
    'the category of their mistake so they can fix it themselves.'
)


@dataclass
class HintResult:
    hint_text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    model_name: str = ''
    response_time_ms: int | None = None


def _cache_key(user_id: int) -> str:
    today = timezone.localdate().isoformat()
    return f'ai_hint_daily:{user_id}:{today}'


def _ttl_to_midnight() -> int:
    """Seconds until the next local midnight."""
    tomorrow = timezone.localdate() + timedelta(days=1)
    midnight_dt = timezone.make_aware(datetime.combine(tomorrow, time.min))
    return max(60, int((midnight_dt - timezone.now()).total_seconds()))


def get_remaining(user_id: int) -> int:
    limit = getattr(settings, 'DMOJ_AI_HINT_DAILY_LIMIT', 5)
    cache_key = _cache_key(user_id)
    used = cache.get(cache_key)
    if used is not None:
        return max(0, limit - used)
    # Cache miss: count from DB
    from judge.models.ai_hints import AIHintLog
    today = timezone.localdate()
    used = AIHintLog.objects.filter(user_id=user_id, requested_at__date=today, success=True).count()
    cache.set(cache_key, used, _ttl_to_midnight())
    return max(0, limit - used)


def _increment(user_id: int) -> None:
    key = _cache_key(user_id)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, _ttl_to_midnight())


def is_configured() -> bool:
    return bool(getattr(settings, 'AZURE_OPENAI_ENDPOINT', None))


def build_user_message(submission) -> str:
    """Assemble the user message from submission data."""
    problem = submission.problem
    lang = submission.language.name

    try:
        source = submission.source.source
    except Exception:
        source = '(source unavailable)'

    lines = [
        f'Problem: {problem.name}',
        f'Time limit: {problem.time_limit}s | Memory limit: {problem.memory_limit} KB',
        '',
        'Problem statement:',
        problem.description[:4000],
        '',
        f"Student's {lang} code:",
        '```',
        source[:8000],
        '```',
        '',
        f'Result: {submission.get_result_display()}',
    ]

    if submission.result == 'CE' and submission.error:
        lines += ['', 'Compiler error:', submission.error[:2000]]
    else:
        failing = (
            submission.test_cases
            .exclude(status='AC')
            .order_by('case')[:3]
        )
        if failing:
            lines += ['', 'Failing test cases (first 3 shown):']
            for tc in failing:
                lines.append(
                    f'  Case {tc.case}: {tc.status} | {tc.time:.3f}s | {tc.memory} KB',
                )
                if tc.output:
                    lines.append(f'    Your output: {tc.output[:300]}')
                if tc.feedback:
                    lines.append(f'    Feedback: {tc.feedback}')
                if tc.extended_feedback:
                    lines.append(f'    Details: {tc.extended_feedback[:500]}')

    lines.append('')
    lines.append('Give a brief, guiding hint to help the student find their bug without revealing the solution.')
    return '\n'.join(lines)


def get_hint(submission) -> HintResult:
    """Call Azure OpenAI and return a HintResult. Raises on failure."""
    client = AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-01'),
    )
    user_message = build_user_message(submission)

    start = _time.monotonic()
    response = client.chat.completions.create(
        model=settings.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user', 'content': user_message},
        ],
        max_completion_tokens=getattr(settings, 'AZURE_OPENAI_MAX_TOKENS', 2048),
    )
    elapsed_ms = int((_time.monotonic() - start) * 1000)

    logger.debug('AI hint response: id=%s, model=%s, finish_reason=%s',
                 response.id, response.model,
                 response.choices[0].finish_reason if response.choices else 'N/A')

    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError('AI service returned an empty response. Please try again.')

    usage = response.usage
    return HintResult(
        hint_text=content.strip(),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        model_name=response.model or '',
        response_time_ms=elapsed_ms,
    )
