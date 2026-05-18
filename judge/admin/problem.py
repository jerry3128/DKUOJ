from operator import attrgetter

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import ModelForm
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_lazy as _, ngettext
from reversion.admin import VersionAdmin

from judge.models import Class, Language, LanguageLimit, Problem, ProblemClarification, ProblemGroup, \
    ProblemPointsVote, ProblemTemplate, ProblemTranslation, ProblemType, Profile, Solution, \
    SubmissionSourceAccess
from judge.utils.views import NoBatchDeleteMixin
from judge.widgets import AdminHeavySelect2MultipleWidget, AdminMartorWidget, AdminSelect2MultipleWidget, \
    AdminSelect2Widget, CheckboxSelectMultipleWithSelectAll


class SimpleProblemCreationForm(ModelForm):
    CREATION_PRESET_ALL_CLOSED = 'all_closed'

    creation_preset = forms.ChoiceField(
        label=_('Creation preset'),
        required=False,
        initial=CREATION_PRESET_ALL_CLOSED,
        choices=((CREATION_PRESET_ALL_CLOSED, _('All closed')),),
        help_text=_('Automatically applies defaults for all other problem settings.'),
    )

    class Meta:
        model = Problem
        fields = ('code', 'name', 'description')
        widgets = {
            'description': AdminMartorWidget(attrs={'data-markdownfy-url': reverse_lazy('problem_preview')}),
        }

    def clean(self):
        cleaned_data = super().clean()

        if getattr(self, 'default_group', None) is None:
            raise forms.ValidationError(_('You must create at least one problem group before creating a problem.'))
        if getattr(self, 'default_type', None) is None:
            raise forms.ValidationError(_('You must create at least one problem type before creating a problem.'))
        if not getattr(self, 'default_languages', None):
            raise forms.ValidationError(_('You must configure at least one language before creating a problem.'))

        return cleaned_data


class ProblemForm(ModelForm):
    change_message = forms.CharField(max_length=256, label=_('Edit reason'), required=False)

    def __init__(self, *args, **kwargs):
        super(ProblemForm, self).__init__(*args, **kwargs)
        self.fields['authors'].widget.can_add_related = False
        self.fields['curators'].widget.can_add_related = False
        self.fields['testers'].widget.can_add_related = False
        self.fields['banned_users'].widget.can_add_related = False
        self.fields['change_message'].widget.attrs.update({
            'placeholder': gettext('Describe the changes you made (optional)'),
        })

    def clean(self):
        cleaned_data = super().clean()
        organizations = cleaned_data.get('organizations')
        classes = cleaned_data.get('classes')

        if classes and organizations:
            org_ids = set(organizations.values_list('id', flat=True))
            invalid_classes = classes.exclude(organization_id__in=org_ids)
            if invalid_classes.exists():
                raise forms.ValidationError(
                    _('Selected classes must belong to selected organizations.'),
                )
        elif classes and not organizations:
            raise forms.ValidationError(
                _('You must select organizations before selecting classes.'),
            )

        return cleaned_data

    class Meta:
        widgets = {
            'authors': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'curators': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'testers': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'banned_users': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'organizations': AdminHeavySelect2MultipleWidget(data_view='organization_select2'),
            'classes': AdminHeavySelect2MultipleWidget(data_view='class_select2'),
            'types': AdminSelect2MultipleWidget,
            'group': AdminSelect2Widget,
            'description': AdminMartorWidget(attrs={'data-markdownfy-url': reverse_lazy('problem_preview')}),
        }


class ProblemCreatorListFilter(admin.SimpleListFilter):
    title = parameter_name = 'creator'

    def lookups(self, request, model_admin):
        queryset = Profile.objects.exclude(authored_problems=None).values_list('user__username', flat=True)
        return [(name, name) for name in queryset]

    def queryset(self, request, queryset):
        if self.value() is None:
            return queryset
        return queryset.filter(authors__user__username=self.value())


class LanguageLimitInlineForm(ModelForm):
    class Meta:
        widgets = {'language': AdminSelect2Widget}


class LanguageLimitInline(admin.TabularInline):
    model = LanguageLimit
    fields = ('language', 'time_limit', 'memory_limit')
    form = LanguageLimitInlineForm


class ProblemClarificationForm(ModelForm):
    class Meta:
        widgets = {'description': AdminMartorWidget(attrs={'data-markdownfy-url': reverse_lazy('comment_preview')})}


class ProblemClarificationInline(admin.StackedInline):
    model = ProblemClarification
    fields = ('description',)
    form = ProblemClarificationForm
    extra = 0


class ProblemSolutionForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super(ProblemSolutionForm, self).__init__(*args, **kwargs)
        self.fields['authors'].widget.can_add_related = False

    class Meta:
        widgets = {
            'authors': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'content': AdminMartorWidget(attrs={'data-markdownfy-url': reverse_lazy('solution_preview')}),
        }


class ProblemSolutionInline(admin.StackedInline):
    model = Solution
    fields = ('is_public', 'publish_on', 'authors', 'content')
    form = ProblemSolutionForm
    extra = 0


class ProblemTranslationForm(ModelForm):
    class Meta:
        widgets = {'description': AdminMartorWidget(attrs={'data-markdownfy-url': reverse_lazy('problem_preview')})}


class ProblemTranslationInline(admin.StackedInline):
    model = ProblemTranslation
    fields = ('language', 'name', 'description')
    form = ProblemTranslationForm
    extra = 0

    def has_permission_full_markup(self, request, obj=None):
        if not obj:
            return True
        return request.user.has_perm('judge.problem_full_markup') or not obj.is_full_markup

    has_add_permission = has_change_permission = has_delete_permission = has_permission_full_markup


class ProblemTemplateInline(admin.StackedInline):
    model = ProblemTemplate
    fields = ('language', 'code')
    extra = 0


class ProblemAdmin(NoBatchDeleteMixin, VersionAdmin):
    add_fieldsets = (
        (None, {
            'fields': ('code', 'name', 'description', 'creation_preset'),
        }),
    )
    fieldsets = (
        (None, {
            'fields': (
                'code', 'name', 'is_public', 'is_manually_managed', 'date', 'authors', 'curators', 'testers',
                'organizations', 'classes', 'submission_source_visibility_mode', 'is_full_markup',
                'view_test_cases', 'view_tester', 'ai_hints_enabled',
                'description', 'license',
            ),
        }),
        (_('Social Media'), {'classes': ('collapse',), 'fields': ('og_image', 'summary')}),
        (_('Taxonomy'), {'fields': ('types', 'group')}),
        (_('Points'), {'fields': (('points', 'partial'), 'short_circuit')}),
        (_('Limits'), {'fields': ('time_limit', 'memory_limit')}),
        (_('Language'), {'fields': ('allowed_languages',)}),
        (_('Justice'), {'fields': ('banned_users',)}),
        (_('History'), {'fields': ('change_message',)}),
    )
    list_display = ['code', 'name', 'show_authors', 'points', 'is_public', 'show_public']
    ordering = ['code']
    search_fields = ('code', 'name', 'authors__user__username', 'curators__user__username')
    inlines = [LanguageLimitInline, ProblemClarificationInline, ProblemSolutionInline,
               ProblemTranslationInline, ProblemTemplateInline]
    list_max_show_all = 1000
    actions_on_top = True
    actions_on_bottom = True
    list_filter = ('is_public', 'group', 'types', ProblemCreatorListFilter)
    form = ProblemForm
    date_hierarchy = 'date'

    def is_advanced_add_mode(self, request, obj=None):
        return obj is None and (request.GET.get('advanced') == '1' or request.POST.get('_advanced_mode') == '1')

    def get_actions(self, request):
        actions = super(ProblemAdmin, self).get_actions(request)

        if request.user.has_perm('judge.change_public_visibility') or \
                request.user.has_perm('judge.create_private_problem'):
            func, name, desc = self.get_action('make_public')
            actions[name] = (func, name, desc)

            func, name, desc = self.get_action('make_private')
            actions[name] = (func, name, desc)

        func, name, desc = self.get_action('update_publish_date')
        actions[name] = (func, name, desc)

        return actions

    def get_default_group(self):
        return ProblemGroup.objects.order_by('full_name', 'name').first()

    def get_default_type(self):
        return ProblemType.objects.order_by('full_name', 'name').first()

    def get_default_languages(self):
        return list(Language.objects.order_by('id'))

    def get_default_time_limit(self):
        return min(max(1, settings.DMOJ_PROBLEM_MIN_TIME_LIMIT), settings.DMOJ_PROBLEM_MAX_TIME_LIMIT)

    def get_default_memory_limit(self):
        return min(max(65536, settings.DMOJ_PROBLEM_MIN_MEMORY_LIMIT), settings.DMOJ_PROBLEM_MAX_MEMORY_LIMIT)

    def get_default_points(self):
        return max(1, settings.DMOJ_PROBLEM_MIN_PROBLEM_POINTS)

    def apply_creation_defaults(self, request, obj):
        obj.group = self.get_default_group()
        obj.time_limit = self.get_default_time_limit()
        obj.memory_limit = self.get_default_memory_limit()
        obj.points = self.get_default_points()
        obj.short_circuit = False
        obj.partial = False
        obj.is_public = False
        obj.is_manually_managed = False
        obj.date = None
        obj.license = None
        obj.og_image = ''
        obj.summary = ''
        obj.is_full_markup = False
        obj.submission_source_visibility_mode = SubmissionSourceAccess.FOLLOW
        obj.view_test_cases = False
        obj.view_tester = False
        obj.ai_hints_enabled = False
        obj.is_organization_private = False

    def get_fieldsets(self, request, obj=None):
        if obj is None and not self.is_advanced_add_mode(request, obj):
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def get_inline_instances(self, request, obj=None):
        if obj is None and not self.is_advanced_add_mode(request, obj):
            return []
        return super().get_inline_instances(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = self.readonly_fields
        if not request.user.has_perm('judge.create_private_problem'):
            fields += ('organizations', 'classes')
            if not request.user.has_perm('judge.change_public_visibility'):
                fields += ('is_public',)
        if not request.user.has_perm('judge.change_manually_managed'):
            fields += ('is_manually_managed',)
        if not request.user.has_perm('judge.problem_full_markup'):
            fields += ('is_full_markup',)
            if obj and obj.is_full_markup:
                fields += ('description',)
        return fields

    @admin.display(description=_('authors'))
    def show_authors(self, obj):
        return ', '.join(map(attrgetter('user.username'), obj.authors.all()))

    @admin.display(description='')
    def show_public(self, obj):
        return format_html('<a href="{1}">{0}</a>', gettext('View on site'), obj.get_absolute_url())

    def _rescore(self, request, problem_id):
        from judge.tasks import rescore_problem
        transaction.on_commit(rescore_problem.s(problem_id).delay)

    @admin.display(description=_('Set publish date to now'))
    def update_publish_date(self, request, queryset):
        count = queryset.update(date=timezone.now())
        self.message_user(request, ngettext("%d problem's publish date successfully updated.",
                                            "%d problems' publish date successfully updated.",
                                            count) % count)

    @admin.display(description=_('Mark problems as public'))
    def make_public(self, request, queryset):
        if not request.user.has_perm('judge.change_public_visibility'):
            queryset = queryset.filter(is_organization_private=True)
        count = queryset.update(is_public=True)
        for problem_id in queryset.values_list('id', flat=True):
            self._rescore(request, problem_id)
        self.message_user(request, ngettext('%d problem successfully marked as public.',
                                            '%d problems successfully marked as public.',
                                            count) % count)

    @admin.display(description=_('Mark problems as private'))
    def make_private(self, request, queryset):
        if not request.user.has_perm('judge.change_public_visibility'):
            queryset = queryset.filter(is_organization_private=True)
        count = queryset.update(is_public=False)
        for problem_id in queryset.values_list('id', flat=True):
            self._rescore(request, problem_id)
        self.message_user(request, ngettext('%d problem successfully marked as private.',
                                            '%d problems successfully marked as private.',
                                            count) % count)

    def get_queryset(self, request):
        return Problem.get_editable_problems(request.user).prefetch_related('authors__user').distinct()

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return request.user.has_perm('judge.edit_own_problem')
        return obj.is_editable_by(request.user)

    def formfield_for_manytomany(self, db_field, request=None, **kwargs):
        if db_field.name == 'allowed_languages':
            kwargs['widget'] = CheckboxSelectMultipleWithSelectAll()
        return super(ProblemAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None and not self.is_advanced_add_mode(request, obj):
            kwargs['form'] = SimpleProblemCreationForm
        form = super(ProblemAdmin, self).get_form(request, obj, **kwargs)
        if obj is None and not self.is_advanced_add_mode(request, obj):
            form.default_group = self.get_default_group()
            form.default_type = self.get_default_type()
            form.default_languages = self.get_default_languages()
        if 'authors' in form.base_fields:
            form.base_fields['authors'].queryset = Profile.objects.all()
        if 'classes' in form.base_fields:
            form.base_fields['classes'].queryset = Class.get_visible_classes(request.user)
        return form

    class Media:
        js = ('admin_class_filter.js',)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context['show_advanced_add_button'] = add and not self.is_advanced_add_mode(request, obj)
        context['advanced_add_url'] = '{}?advanced=1'.format(request.path)
        context['is_advanced_add'] = add and self.is_advanced_add_mode(request, obj)
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request, obj, form, change):
        if not change and not self.is_advanced_add_mode(request, obj):
            self.apply_creation_defaults(request, obj)

        # `organizations` and `classes` will not appear in `cleaned_data` if user cannot edit them
        if form.changed_data:
            if 'organizations' in form.changed_data or 'classes' in form.changed_data:
                has_orgs = form.cleaned_data.get('organizations')
                has_classes = form.cleaned_data.get('classes')
                obj.is_organization_private = bool(has_orgs or has_classes)

        if form.cleaned_data.get('is_public') and not request.user.has_perm('judge.change_public_visibility'):
            if not obj.is_organization_private:
                raise PermissionDenied
            if not request.user.has_perm('judge.create_private_problem'):
                raise PermissionDenied

        super(ProblemAdmin, self).save_model(request, obj, form, change)
        if (
            form.changed_data and
            any(f in form.changed_data for f in ('is_public', 'organizations', 'classes', 'points', 'partial'))
        ):
            self._rescore(request, obj.id)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if change or self.is_advanced_add_mode(request, form.instance):
            return

        problem = form.instance
        default_type = self.get_default_type()
        default_languages = self.get_default_languages()

        if default_type is not None:
            problem.types.set([default_type])
        if default_languages:
            problem.allowed_languages.set(default_languages)
        if hasattr(request.user, 'profile'):
            problem.authors.set([request.user.profile])

    def construct_change_message(self, request, form, *args, **kwargs):
        if form.cleaned_data.get('change_message'):
            return form.cleaned_data['change_message']
        return super(ProblemAdmin, self).construct_change_message(request, form, *args, **kwargs)


class ProblemPointsVoteAdmin(admin.ModelAdmin):
    list_display = ('points', 'voter', 'linked_problem', 'vote_time')
    search_fields = ('voter__user__username', 'problem__code', 'problem__name')
    readonly_fields = ('voter', 'problem', 'vote_time')

    def get_queryset(self, request):
        return ProblemPointsVote.objects.filter(problem__in=Problem.get_editable_problems(request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return request.user.has_perm('judge.edit_own_problem')
        return obj.problem.is_editable_by(request.user)

    def lookup_allowed(self, key, value):
        return super().lookup_allowed(key, value) or key in ('problem__code',)

    @admin.display(description=_('problem'), ordering='problem__name')
    def linked_problem(self, obj):
        link = reverse('problem_detail', args=[obj.problem.code])
        return format_html('<a href="{0}">{1}</a>', link, obj.problem.name)
