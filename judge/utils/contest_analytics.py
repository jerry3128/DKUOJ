import statistics
from collections import defaultdict
from itertools import combinations

from pygments.lexers import get_lexer_by_name
from pygments.token import Token
from pygments.util import ClassNotFound


def get_contest_analytics(contest):
    """Compute all analytics metrics for a contest. Returns dict with summary stats,
    per-student metrics, chart data, and cross-student similarity."""
    from judge.models.contest import ContestParticipation
    from judge.models.submission import Submission, SubmissionSource

    # Fetch participations (exclude virtual and disqualified)
    participations = list(
        ContestParticipation.objects.filter(
            contest=contest, virtual=ContestParticipation.LIVE, is_disqualified=False,
        ).select_related('user__user'),
    )

    if not participations:
        return _empty_analytics()

    user_ids = [p.user_id for p in participations]

    # Fetch all completed submissions for this contest
    submissions = list(
        Submission.objects.filter(
            contest_object=contest, user_id__in=user_ids, status='D',
        ).select_related('language', 'problem').order_by('date'),
    )

    if not submissions:
        return _empty_analytics(participations=participations)

    # Fetch source code in bulk
    sub_ids = [s.id for s in submissions]
    sources = dict(
        SubmissionSource.objects.filter(submission_id__in=sub_ids).values_list('submission_id', 'source'),
    )

    # Contest problems info
    contest_problems = list(
        contest.contest_problems.order_by('order').select_related('problem').values_list(
            'problem_id', 'problem__code', 'problem__name', 'points',
        ),
    )
    problem_ids = [cp[0] for cp in contest_problems]
    problem_info = {cp[0]: {'code': cp[1], 'name': cp[2], 'max_points': cp[3]} for cp in contest_problems}

    # Group submissions by user
    subs_by_user = defaultdict(list)
    for s in submissions:
        if s.user_id in user_ids:
            subs_by_user[s.user_id].append(s)

    # Group submissions by (user, problem)
    subs_by_user_problem = defaultdict(list)
    for s in submissions:
        if s.problem_id in problem_info:
            subs_by_user_problem[(s.user_id, s.problem_id)].append(s)

    # Compute problem difficulty (class AC rate)
    problem_ac_rates = _compute_problem_ac_rates(subs_by_user_problem, user_ids, problem_ids)

    # Build participation lookup
    # part_by_user = {p.user_id: p for p in participations}

    # Compute all metric categories
    summary = _compute_summary_stats(participations, submissions, problem_ids, problem_info)
    student_metrics = {}

    for p in participations:
        uid = p.user_id
        username = p.user.user.username
        user_subs = subs_by_user.get(uid, [])

        attempt = _compute_attempt_metrics(uid, user_subs, subs_by_user_problem, problem_ids, problem_info)
        timing = _compute_timing_metrics(uid, user_subs, subs_by_user_problem, problem_ids, p, contest)
        code = _compute_code_metrics(uid, user_subs, subs_by_user_problem, problem_ids, sources)
        score = _compute_score_metrics(uid, p, subs_by_user_problem, problem_ids, problem_info, problem_ac_rates)

        student_metrics[uid] = {
            'username': username,
            'user_id': uid,
            'score': p.score,
            'problems_solved': attempt['problems_solved'],
            'total_submissions': len(user_subs),
            'attempt': attempt,
            'timing': timing,
            'code': code,
            'score_patterns': score,
        }

    # Cross-student similarity
    similarity = _compute_cross_student_similarity(subs_by_user_problem, problem_ids, sources, submissions)

    # Compute anomaly scores
    _compute_anomaly_scores(student_metrics)

    # Chart data
    timeline_data = _build_timeline_data(submissions, participations, sources, contest, problem_info)

    return {
        'summary': summary,
        'students': student_metrics,
        'similarity': similarity,
        'timeline': timeline_data,
        'problems': problem_info,
        'problem_ac_rates': problem_ac_rates,
    }


def _empty_analytics(participations=None):
    summary = {
        'total_students': len(participations) if participations else 0,
        'total_submissions': 0,
        'highest_score': 0,
        'lowest_score': 0,
        'mean_score': 0,
        'median_score': 0,
        'score_std_dev': 0,
        'avg_problems_solved': 0,
        'total_ac_rate': 0,
        'avg_submissions_per_student': 0,
    }
    return {
        'summary': summary,
        'students': {},
        'similarity': {},
        'timeline': {'submissions': [], 'students': [], 'deadline': None, 'start': None},
        'problems': {},
        'problem_ac_rates': {},
    }


def _compute_summary_stats(participations, submissions, problem_ids, problem_info):
    scores = [p.score for p in participations]
    ac_count = sum(1 for s in submissions if s.result == 'AC')

    # Count problems solved per student
    solved_by_user = defaultdict(set)
    for s in submissions:
        if s.result == 'AC' and s.problem_id in problem_info:
            solved_by_user[s.user_id].add(s.problem_id)
    problems_solved_counts = [len(solved_by_user.get(p.user_id, set())) for p in participations]

    return {
        'total_students': len(participations),
        'total_submissions': len(submissions),
        'highest_score': max(scores) if scores else 0,
        'lowest_score': min(scores) if scores else 0,
        'mean_score': round(statistics.mean(scores), 2) if scores else 0,
        'median_score': round(statistics.median(scores), 2) if scores else 0,
        'score_std_dev': round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
        'avg_problems_solved': round(statistics.mean(problems_solved_counts), 2) if problems_solved_counts else 0,
        'total_ac_rate': round(ac_count / len(submissions) * 100, 1) if submissions else 0,
        'avg_submissions_per_student': round(len(submissions) / len(participations), 1) if participations else 0,
    }


def _compute_problem_ac_rates(subs_by_user_problem, user_ids, problem_ids):
    """Compute per-problem AC rate across all students."""
    rates = {}
    for pid in problem_ids:
        attempted = 0
        solved = 0
        for uid in user_ids:
            user_problem_subs = subs_by_user_problem.get((uid, pid), [])
            if user_problem_subs:
                attempted += 1
                if any(s.result == 'AC' for s in user_problem_subs):
                    solved += 1
        rates[pid] = round(solved / attempted * 100, 1) if attempted > 0 else 0
    return rates


def _compute_attempt_metrics(uid, user_subs, subs_by_user_problem, problem_ids, problem_info):
    """Compute attempt pattern metrics for a student."""
    problems_solved = 0
    first_try_ac = 0
    total_attempts_before_ac = []
    no_progression_count = 0
    problems_attempted = 0

    for pid in problem_ids:
        ups = subs_by_user_problem.get((uid, pid), [])
        if not ups:
            continue
        problems_attempted += 1
        solved = any(s.result == 'AC' for s in ups)
        if solved:
            problems_solved += 1
            # Count attempts before first AC
            attempts = 0
            for s in ups:
                attempts += 1
                if s.result == 'AC':
                    break
            total_attempts_before_ac.append(attempts)
            if attempts == 1:
                first_try_ac += 1

            # Check no-progression: went from 0 points to full score without partial
            points_sequence = [s.case_points for s in ups if s.case_total and s.case_total > 0]
            max_total = max((s.case_total for s in ups if s.case_total and s.case_total > 0), default=0)
            if len(points_sequence) >= 1 and max_total > 0:
                has_partial = any(0 < p < max_total for p in points_sequence)
                if not has_partial and solved:
                    no_progression_count += 1

    first_try_ac_rate = round(first_try_ac / problems_solved * 100, 1) if problems_solved > 0 else 0
    avg_attempts = round(statistics.mean(total_attempts_before_ac), 2) if total_attempts_before_ac else 0
    no_progression_rate = round(no_progression_count / problems_solved * 100, 1) if problems_solved > 0 else 0

    return {
        'problems_solved': problems_solved,
        'problems_attempted': problems_attempted,
        'first_try_ac_rate': first_try_ac_rate,
        'avg_attempts_before_ac': avg_attempts,
        'no_progression_rate': no_progression_rate,
    }


def _compute_timing_metrics(uid, user_subs, subs_by_user_problem, problem_ids, participation, contest):
    """Compute timing pattern metrics for a student."""
    solve_times = []  # seconds from first sub to AC per problem
    ac_timestamps = []  # timestamps of AC submissions

    for pid in problem_ids:
        ups = subs_by_user_problem.get((uid, pid), [])
        if not ups:
            continue
        first_sub_time = ups[0].date
        for s in ups:
            if s.result == 'AC':
                solve_time = (s.date - first_sub_time).total_seconds()
                solve_times.append(solve_time)
                ac_timestamps.append(s.date)
                break

    # Burst pattern: count pairs of AC submissions less than 5 minutes apart
    burst_count = 0
    ac_timestamps.sort()
    for i in range(1, len(ac_timestamps)):
        if (ac_timestamps[i] - ac_timestamps[i - 1]).total_seconds() < 300:
            burst_count += 1

    # Submission spacing variance
    all_times = sorted(s.date for s in user_subs)
    spacing_variance = 0
    if len(all_times) > 2:
        gaps = [(all_times[i] - all_times[i - 1]).total_seconds() for i in range(1, len(all_times))]
        spacing_variance = round(statistics.variance(gaps), 1) if len(gaps) > 1 else 0

    avg_solve_time = round(statistics.mean(solve_times), 1) if solve_times else None

    return {
        'avg_solve_time_seconds': avg_solve_time,
        'burst_count': burst_count,
        'spacing_variance': spacing_variance,
        'total_ac_count': len(ac_timestamps),
    }


def _tokenize_source(source, language_pygments):
    """Tokenize source code using Pygments. Returns (comment_tokens, name_tokens, total_tokens)."""
    try:
        lexer = get_lexer_by_name(language_pygments)
    except ClassNotFound:
        return [], [], 0

    tokens = list(lexer.get_tokens(source))
    comment_tokens = []
    name_tokens = []
    for ttype, value in tokens:
        # Pygments token types use 'is' subtokentype check via `in`
        if ttype in Token.Comment:
            comment_tokens.append(value)
        elif ttype in Token.Name:
            name_tokens.append(value)

    return comment_tokens, name_tokens, len(tokens)


def _compute_code_metrics(uid, user_subs, subs_by_user_problem, problem_ids, sources):
    """Compute code style metrics using Pygments tokenization."""
    comment_densities = []
    source_lengths = []

    for pid in problem_ids:
        ups = subs_by_user_problem.get((uid, pid), [])
        # Use the best (AC) submission, or the last one
        best_sub = None
        for s in ups:
            if s.result == 'AC':
                best_sub = s
                break
        if best_sub is None and ups:
            best_sub = ups[-1]
        if best_sub is None:
            continue

        source = sources.get(best_sub.id)
        if not source:
            continue

        source_lengths.append(len(source))

        lang_pygments = best_sub.language.pygments if hasattr(best_sub.language, 'pygments') else None
        if not lang_pygments:
            continue

        comment_tokens, name_tokens, total_tokens = _tokenize_source(source, lang_pygments)
        if total_tokens > 0:
            comment_densities.append(len(comment_tokens) / total_tokens)

    avg_comment_density = round(statistics.mean(comment_densities) * 100, 1) if comment_densities else 0
    avg_source_length = round(statistics.mean(source_lengths), 0) if source_lengths else 0
    source_length_variance = round(statistics.variance(source_lengths), 0) if len(source_lengths) > 1 else 0

    return {
        'avg_comment_density': avg_comment_density,
        'avg_source_length': avg_source_length,
        'source_length_variance': source_length_variance,
    }


def _compute_score_metrics(uid, participation, subs_by_user_problem, problem_ids, problem_info, problem_ac_rates):
    """Compute score pattern metrics."""
    perfect_count = 0
    solved_count = 0
    difficulties = []  # (problem difficulty, student solved?)
    solve_order = []  # (problem difficulty, solve position)

    solve_position = 0
    for pid in problem_ids:
        ups = subs_by_user_problem.get((uid, pid), [])
        difficulty = problem_ac_rates.get(pid, 50)
        solved = any(s.result == 'AC' for s in ups)
        if ups:
            difficulties.append((difficulty, solved))
        if solved:
            solved_count += 1
            solve_position += 1
            solve_order.append((difficulty, solve_position))
            # Check if full points
            best_points = max((s.case_points for s in ups if s.case_total and s.case_total > 0), default=0)
            max_case_total = max((s.case_total for s in ups if s.case_total and s.case_total > 0), default=0)
            if max_case_total > 0 and best_points >= max_case_total:
                perfect_count += 1

    perfect_score_rate = round(perfect_count / solved_count * 100, 1) if solved_count > 0 else 0

    # Difficulty-performance correlation: do they struggle more on harder problems?
    # Lower correlation = suspicious (solving hard and easy equally)
    difficulty_correlation = None
    if len(solve_order) >= 3:
        # If they solve easy problems first (high AC rate first), correlation is positive (normal)
        diffs = [d for d, _ in solve_order]
        positions = [p for _, p in solve_order]
        try:
            difficulty_correlation = round(_pearson_correlation(diffs, positions), 2)
        except (ZeroDivisionError, statistics.StatisticsError):
            difficulty_correlation = None

    return {
        'perfect_score_rate': perfect_score_rate,
        'difficulty_correlation': difficulty_correlation,
    }


def _compute_cross_student_similarity(subs_by_user_problem, problem_ids, sources, submissions):
    """Compute identifier similarity between student pairs per problem."""
    # Extract identifiers per (user, problem)
    identifiers_by_up = {}
    # sub_lookup = {s.id: s for s in submissions}

    for (uid, pid), ups in subs_by_user_problem.items():
        if pid not in problem_ids:
            continue
        # Use best AC submission
        best_sub = None
        for s in ups:
            if s.result == 'AC':
                best_sub = s
                break
        if best_sub is None:
            continue

        source = sources.get(best_sub.id)
        if not source:
            continue

        lang_pygments = best_sub.language.pygments if hasattr(best_sub.language, 'pygments') else None
        if not lang_pygments:
            continue

        _, name_tokens, _ = _tokenize_source(source, lang_pygments)
        # Filter to meaningful identifiers (length > 1)
        identifiers = set(t for t in name_tokens if len(t) > 1)
        identifiers_by_up[(uid, pid)] = identifiers

    # Compute per-problem similarity between all student pairs
    similarity_by_problem = {}
    for pid in problem_ids:
        users_with_ids = [(uid, identifiers_by_up[(uid, pid)])
                          for (uid, p) in identifiers_by_up if p == pid]
        if len(users_with_ids) < 2:
            continue

        pairs = []
        for (uid1, ids1), (uid2, ids2) in combinations(users_with_ids, 2):
            if ids1 and ids2:
                jaccard = len(ids1 & ids2) / len(ids1 | ids2)
                if jaccard > 0.5:  # Only report notable similarity
                    pairs.append({
                        'user1': uid1,
                        'user2': uid2,
                        'similarity': round(jaccard, 3),
                    })
        if pairs:
            similarity_by_problem[pid] = sorted(pairs, key=lambda x: -x['similarity'])

    return similarity_by_problem


def _compute_anomaly_scores(student_metrics):
    """Compute composite anomaly scores based on z-scores across all metrics."""
    if len(student_metrics) < 3:
        for uid in student_metrics:
            student_metrics[uid]['anomaly_score'] = 0
            student_metrics[uid]['anomaly_percentile'] = 0
            student_metrics[uid]['outlier_metrics'] = []
        return

    # Metrics to evaluate: (path, higher_is_suspicious)
    metric_defs = [
        ('attempt.first_try_ac_rate', True),
        ('attempt.avg_attempts_before_ac', False),  # Lower = suspicious
        ('attempt.no_progression_rate', True),
        ('timing.burst_count', True),
        ('timing.spacing_variance', False),  # Lower = suspicious
        ('code.avg_comment_density', True),
        ('code.avg_source_length', True),
        ('score_patterns.perfect_score_rate', True),
    ]

    threshold = 1.5

    for uid in student_metrics:
        student_metrics[uid]['outlier_metrics'] = []

    for metric_path, higher_is_suspicious in metric_defs:
        values = {}
        for uid, m in student_metrics.items():
            val = _get_nested(m, metric_path)
            if val is not None:
                values[uid] = val

        if len(values) < 3:
            continue

        vals = list(values.values())
        mean = statistics.mean(vals)
        stdev = statistics.stdev(vals)
        if stdev == 0:
            continue

        for uid, val in values.items():
            z = (val - mean) / stdev
            # Flip sign if lower is suspicious
            if not higher_is_suspicious:
                z = -z
            if z > threshold:
                student_metrics[uid]['outlier_metrics'].append({
                    'metric': metric_path,
                    'z_score': round(z, 2),
                    'value': val,
                })

    # Composite score: sum of excess z-scores
    raw_scores = {}
    for uid in student_metrics:
        outliers = student_metrics[uid]['outlier_metrics']
        raw_scores[uid] = sum(o['z_score'] - threshold for o in outliers)

    # Convert to percentile
    all_scores = sorted(raw_scores.values())
    for uid in student_metrics:
        score = raw_scores[uid]
        rank = sum(1 for s in all_scores if s <= score)
        student_metrics[uid]['anomaly_score'] = round(score, 2)
        student_metrics[uid]['anomaly_percentile'] = round(rank / len(all_scores) * 100, 0)


def _build_timeline_data(submissions, participations, sources, contest, problem_info):
    """Build data for timeline chart visualization."""
    user_lookup = {p.user_id: p.user.user.username for p in participations}
    student_list = sorted(user_lookup.values())

    sub_data = []
    for s in submissions:
        if s.user_id not in user_lookup:
            continue
        if s.problem_id not in problem_info:
            continue
        sub_data.append({
            'username': user_lookup[s.user_id],
            'user_id': s.user_id,
            'problem_code': problem_info[s.problem_id]['code'],
            'problem_name': problem_info[s.problem_id]['name'],
            'date': s.date.isoformat(),
            'result': s.result or s.status,
            'points': s.case_points,
            'total_points': s.case_total,
            'source_length': len(sources.get(s.id, '')),
        })

    return {
        'submissions': sub_data,
        'students': student_list,
        'deadline': contest.end_time.isoformat() if contest.end_time else None,
        'start': contest.start_time.isoformat() if contest.start_time else None,
    }


def _get_nested(d, path):
    """Get a value from a nested dict using dot notation."""
    keys = path.split('.')
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return None
    return d


def _pearson_correlation(x, y):
    """Compute Pearson correlation coefficient between two lists."""
    n = len(x)
    if n < 3:
        return 0
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)
    std_x = statistics.stdev(x)
    std_y = statistics.stdev(y)
    if std_x == 0 or std_y == 0:
        return 0
    covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / (n - 1)
    return covariance / (std_x * std_y)


def classify_outlier(z, threshold=1.5):
    """Classify a z-score as normal, notable, or outlier."""
    if abs(z) > threshold:
        return 'outlier'
    elif abs(z) > 1.0:
        return 'notable'
    return 'normal'


def compute_z_scores(values):
    """Compute z-scores for a list of values. Returns dict mapping index to z-score."""
    if len(values) < 2:
        return {i: 0 for i in range(len(values))}
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return {i: 0 for i in range(len(values))}
    return {i: (v - mean) / stdev for i, v in enumerate(values)}
