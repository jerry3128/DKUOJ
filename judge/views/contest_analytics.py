import json
import statistics

from django.http import Http404
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.generic.detail import DetailView

from judge.utils.contest_analytics import _get_nested, get_contest_analytics
from judge.utils.views import TitleMixin
from judge.views.contests import ContestMixin


class ContestAnalytics(TitleMixin, ContestMixin, DetailView):
    template_name = 'contest/analytics.html'

    def get_title(self):
        return _('%s Analytics') % self.object.name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if not self.can_edit:
            raise Http404()

        analytics = get_contest_analytics(self.object)

        # Build table data: list of student dicts sorted by anomaly score descending
        students_list = sorted(
            analytics['students'].values(),
            key=lambda s: s.get('anomaly_score', 0),
            reverse=True,
        )

        # Compute class-wide stats for z-score coloring in template
        if len(students_list) >= 3:
            metric_paths = [
                'attempt.first_try_ac_rate',
                'attempt.avg_attempts_before_ac',
                'timing.burst_count',
                'code.avg_comment_density',
                'code.avg_source_length',
                'score_patterns.perfect_score_rate',
            ]
            class_stats = {}
            for path in metric_paths:
                vals = []
                for s in students_list:
                    v = _get_nested(s, path)
                    if v is not None:
                        vals.append(v)
                if len(vals) >= 2:
                    class_stats[path] = {
                        'mean': statistics.mean(vals),
                        'stdev': statistics.stdev(vals),
                    }
            context['class_stats'] = class_stats
        else:
            context['class_stats'] = {}

        context['analytics_summary'] = analytics['summary']
        context['students_list'] = students_list
        context['problems'] = analytics['problems']
        context['problem_ac_rates'] = analytics['problem_ac_rates']

        uid_to_username = {s['user_id']: s['username'] for s in students_list}
        similarity_sections = []
        for pid, pairs in analytics['similarity'].items():
            prob = analytics['problems'].get(pid, {})
            similarity_sections.append({
                'problem_code': prob.get('code', ''),
                'problem_name': prob.get('name', ''),
                'pairs': [
                    {
                        'user1': uid_to_username.get(p['user1'], '?'),
                        'user2': uid_to_username.get(p['user2'], '?'),
                        'similarity': p['similarity'],
                    }
                    for p in pairs
                ],
            })
        similarity_sections.sort(key=lambda s: -(s['pairs'][0]['similarity'] if s['pairs'] else 0))
        context['similarity_sections'] = similarity_sections

        # JSON data for charts (escape </ to prevent script tag injection)
        context['timeline_json'] = mark_safe(json.dumps(analytics['timeline']).replace('</', '<\\/'))
        context['problem_ac_rates_json'] = mark_safe(json.dumps(analytics['problem_ac_rates']).replace('</', '<\\/'))
        context['students_json'] = mark_safe(json.dumps(students_list, default=str).replace('</', '<\\/'))
        context['has_timeline_data'] = bool(analytics['timeline']['submissions'])

        return context
