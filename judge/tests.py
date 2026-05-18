from django.test import Client, TestCase
from django.urls import reverse

from judge.models import Language, Problem
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

    def test_admin_add_page_uses_simplified_problem_form(self):
        response = self.client.get(reverse('admin:judge_problem_add'))

        self.assertContains(response, 'name="code"', html=False)
        self.assertContains(response, 'name="name"', html=False)
        self.assertContains(response, 'name="description"', html=False)
        self.assertContains(response, 'name="creation_preset"', html=False)
        self.assertContains(response, '?advanced=1', html=False)
        self.assertNotContains(response, 'name="is_public"', html=False)
        self.assertNotContains(response, 'name="time_limit"', html=False)
        self.assertNotContains(response, 'name="allowed_languages"', html=False)

    def test_admin_advanced_add_page_uses_original_problem_form(self):
        response = self.client.get('{}?advanced=1'.format(reverse('admin:judge_problem_add')))

        self.assertContains(response, 'name="code"', html=False)
        self.assertContains(response, 'name="name"', html=False)
        self.assertContains(response, 'name="description"', html=False)
        self.assertContains(response, 'name="is_public"', html=False)
        self.assertContains(response, 'name="time_limit"', html=False)
        self.assertContains(response, 'name="allowed_languages"', html=False)
        self.assertNotContains(response, 'name="creation_preset"', html=False)

    def test_admin_add_page_can_create_problem_with_automatic_defaults(self):
        response = self.client.post(reverse('admin:judge_problem_add'), data={
            'code': 'simpleprob',
            'name': 'Simple Problem',
            'description': 'Problem statement',
            'creation_preset': 'all_closed',
            '_save': 'Save',
        })

        self.assertEqual(response.status_code, 302)

        problem = Problem.objects.get(code='simpleprob')
        self.assertEqual(problem.name, 'Simple Problem')
        self.assertEqual(problem.description, 'Problem statement')
        self.assertFalse(problem.is_public)
        self.assertFalse(problem.is_manually_managed)
        self.assertFalse(problem.is_organization_private)
        self.assertFalse(problem.view_test_cases)
        self.assertFalse(problem.view_tester)
        self.assertFalse(problem.ai_hints_enabled)
        self.assertEqual(problem.time_limit, 1)
        self.assertEqual(problem.memory_limit, 65536)
        self.assertEqual(problem.points, 1)
        self.assertEqual(problem.group.name, 'default-group')
        self.assertCountEqual(problem.types.values_list('name', flat=True), ['default-type'])
        self.assertCountEqual(
            problem.allowed_languages.values_list('id', flat=True),
            Language.objects.values_list('id', flat=True),
        )
        self.assertCountEqual(
            problem.authors.values_list('id', flat=True),
            [self.users['superuser'].profile.id],
        )
