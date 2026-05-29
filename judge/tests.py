from django.utils import timezone
from django.test import Client, TestCase
from django.urls import reverse

from judge.models import Contest, Language, Problem
from judge.models.tests.util import CommonDataMixin, create_problem_group, create_problem_type


class ProblemAdminCreationTestCase(CommonDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        create_problem_group(name='default-group')
        create_problem_type(name='default-type')

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.users['superuser'])

    def test_admin_add_page_uses_embedded_advanced_creation_form(self):
        response = self.client.get(reverse('admin:judge_problem_add'))

        self.assertContains(response, 'name="name"', html=False)
        self.assertContains(response, 'name="description"', html=False)
        self.assertContains(response, 'name="creation_preset"', html=False)
        self.assertContains(response, 'value="default"', html=False)
        self.assertContains(response, 'value="custom"', html=False)
        self.assertContains(response, 'id="embedded-advanced-toggle"', html=False)
        self.assertContains(response, 'name="embedded_advanced_mode"', html=False)

    def test_admin_advanced_add_page_uses_original_problem_form(self):
        response = self.client.get('{}?advanced=1'.format(reverse('admin:judge_problem_add')))

        self.assertContains(response, 'name="code"', html=False)
        self.assertContains(response, 'name="time_limit"', html=False)
        self.assertContains(response, 'name="allowed_languages"', html=False)
        self.assertNotContains(response, 'name="creation_preset"', html=False)

    def test_admin_add_page_can_create_problem_with_automatic_defaults(self):
        response = self.client.post(reverse('admin:judge_problem_add'), data={
            'name': 'Simple Problem',
            'description': 'Problem statement',
            'creation_preset': 'default',
            '_save': 'Save',
        })

        self.assertEqual(response.status_code, 302)

        problem = Problem.objects.get(name='Simple Problem')
        self.assertEqual(problem.code, 'simpleproblem')
        self.assertFalse(problem.is_public)
        self.assertEqual(problem.time_limit, 1)
        self.assertEqual(problem.memory_limit, 262144)
        self.assertEqual(problem.points, 100)
        self.assertEqual(problem.group.name, 'default-group')
        self.assertCountEqual(problem.types.values_list('name', flat=True), ['default-type'])
        self.assertCountEqual(
            problem.allowed_languages.values_list('id', flat=True),
            Language.objects.values_list('id', flat=True),
        )

    def test_admin_embedded_advanced_mode_can_use_manual_settings(self):
        response = self.client.post(reverse('admin:judge_problem_add'), data={
            'embedded_advanced_mode': '1',
            'creation_preset': 'custom',
            'code': 'manualcode',
            'name': 'Manual Problem',
            'description': 'Problem statement',
            'group': create_problem_group(name='manual-group').pk,
            'types': [create_problem_type(name='manual-type').pk],
            'allowed_languages': list(Language.objects.values_list('pk', flat=True)[:2]),
            'time_limit': 2,
            'memory_limit': 131072,
            'points': 5,
            '_save': 'Save',
        })

        self.assertEqual(response.status_code, 302)
        problem = Problem.objects.get(code='manualcode')
        self.assertEqual(problem.name, 'Manual Problem')
        self.assertEqual(problem.time_limit, 2)
        self.assertEqual(problem.memory_limit, 131072)
        self.assertEqual(problem.points, 5)


class ContestAdminCreationTestCase(CommonDataMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(self.users['superuser'])

    def contest_post_data(self, name='Simple Contest'):
        start = timezone.now() + timezone.timedelta(days=1)
        end = start + timezone.timedelta(hours=2)
        return {
            'name': name,
            'start_time_0': start.strftime('%Y-%m-%d'),
            'start_time_1': start.strftime('%H:%M:%S'),
            'end_time_0': end.strftime('%Y-%m-%d'),
            'end_time_1': end.strftime('%H:%M:%S'),
        }

    def test_admin_add_page_uses_embedded_advanced_creation_form(self):
        response = self.client.get(reverse('admin:judge_contest_add'))

        self.assertContains(response, 'name="name"', html=False)
        self.assertContains(response, 'name="start_time_0"', html=False)
        self.assertContains(response, 'name="end_time_0"', html=False)
        self.assertContains(response, 'name="creation_preset"', html=False)
        self.assertContains(response, 'id="embedded-advanced-toggle"', html=False)
        self.assertContains(response, 'name="embedded_advanced_mode"', html=False)

    def test_admin_advanced_add_page_uses_original_contest_form(self):
        response = self.client.get('{}?advanced=1'.format(reverse('admin:judge_contest_add')))

        self.assertContains(response, 'name="key"', html=False)
        self.assertContains(response, 'name="authors"', html=False)
        self.assertContains(response, 'name="format_name"', html=False)
        self.assertNotContains(response, 'name="creation_preset"', html=False)

    def test_admin_add_page_can_create_contest_with_automatic_defaults(self):
        data = self.contest_post_data()
        data.update({
            'creation_preset': 'default',
            '_save': 'Save',
        })

        response = self.client.post(reverse('admin:judge_contest_add'), data=data)

        self.assertEqual(response.status_code, 302)

        contest = Contest.objects.get(name='Simple Contest')
        self.assertTrue(contest.key.startswith('c'))
        self.assertEqual(len(contest.key), 7)
        self.assertCountEqual(contest.authors.values_list('user__username', flat=True), ['superuser'])
        self.assertFalse(contest.is_visible)
        self.assertTrue(contest.use_clarifications)
        self.assertEqual(contest.scoreboard_visibility, Contest.SCOREBOARD_VISIBLE)
        self.assertEqual(contest.points_precision, 3)
        self.assertEqual(contest.format_name, 'default')
        self.assertEqual(contest.access_code, '')

    def test_admin_embedded_advanced_mode_can_use_manual_settings(self):
        data = self.contest_post_data(name='Manual Contest')
        data.update({
            'embedded_advanced_mode': '1',
            'creation_preset': 'custom',
            'key': 'manualcontest',
            'authors': [self.users['superuser'].profile.pk],
            'is_visible': 'on',
            'use_clarifications': 'on',
            'scoreboard_visibility': Contest.SCOREBOARD_HIDDEN,
            'points_precision': 5,
            'format_name': 'default',
            'access_code': 'contest-code',
            'allow_virtual_participation': 'on',
            '_save': 'Save',
        })

        response = self.client.post(reverse('admin:judge_contest_add'), data=data)

        self.assertEqual(response.status_code, 302)
        contest = Contest.objects.get(key='manualcontest')
        self.assertEqual(contest.name, 'Manual Contest')
        self.assertTrue(contest.is_visible)
        self.assertTrue(contest.use_clarifications)
        self.assertEqual(contest.scoreboard_visibility, Contest.SCOREBOARD_HIDDEN)
        self.assertEqual(contest.points_precision, 5)
        self.assertEqual(contest.access_code, 'contest-code')
