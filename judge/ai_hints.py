from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from openai import AzureOpenAI

_SYSTEM_PROMPT = (
    'You are a programming tutor reviewing a competitive programming submission. '
    'Do NOT reveal the correct algorithm, solution, or give away the answer. '
    'Give a concise, guiding hint (2-4 sentences) that helps the student identify '
    'the category of their mistake so they can fix it themselves.'
)


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
    used = cache.get(_cache_key(user_id), 0)
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


def get_hint(submission) -> str:
    """Call Azure OpenAI and return the hint text. Raises on failure."""
    client = AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-01'),
    )
    response = client.chat.completions.create(
        model=settings.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user', 'content': build_user_message(submission)},
        ],
        max_completion_tokens=400,
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise RuntimeError('AI service returned an empty response. Please try again.')

    _increment(submission.user_id)
    return content.strip()
