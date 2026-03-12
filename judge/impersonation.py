from django.contrib.auth.models import User
from django.db.models import Q

from judge.models import ContestParticipation, Profile

IMPERSONATE_PERMS = (
    'judge.impersonate_org',
    'judge.impersonate_class',
    'judge.impersonate_contest',
)


def _is_protected_user(user):
    """Return True if user should never be impersonated by non-superusers."""
    if user.is_superuser or user.is_staff:
        return True
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        return True  # Fail closed: treat profileless users as protected
    if profile.admin_of.exists() or profile.class_admin_of.exists():
        return True
    return False


def can_impersonate(request):
    """IMPERSONATE_CUSTOM_ALLOW callback.

    Returns True if the request user is allowed to impersonate anyone at all.
    """
    user = request.user
    if user.is_superuser:
        return True
    return any(user.has_perm(p) for p in IMPERSONATE_PERMS)


def get_impersonable_users(request):
    """IMPERSONATE_CUSTOM_USER_QUERYSET callback.

    Returns a QuerySet of users that the request user may impersonate.
    """
    user = request.user

    if user.is_superuser:
        return User.objects.filter(is_superuser=False)

    profile = user.profile
    qs = User.objects.none()

    if user.has_perm('judge.impersonate_org'):
        admin_org_ids = profile.admin_of.values_list('id', flat=True)
        qs = qs | User.objects.filter(profile__organizations__in=admin_org_ids)

    if user.has_perm('judge.impersonate_class'):
        admin_class_ids = profile.class_admin_of.values_list('id', flat=True)
        qs = qs | User.objects.filter(profile__classes__in=admin_class_ids)

    if user.has_perm('judge.impersonate_contest'):
        contest_ids = set()
        contest_ids.update(profile.authored_contests.values_list('id', flat=True))
        contest_ids.update(profile.curated_contests.values_list('id', flat=True))
        if contest_ids:
            live_participant_profiles = ContestParticipation.objects.filter(
                contest_id__in=contest_ids,
                virtual=ContestParticipation.LIVE,
            ).values_list('user__user_id', flat=True)
            qs = qs | User.objects.filter(id__in=live_participant_profiles)

    # Exclude protected users: superusers, staff, org admins, class admins
    qs = qs.exclude(is_superuser=True).exclude(is_staff=True)
    qs = qs.exclude(
        Q(profile__admin_of__isnull=False) | Q(profile__class_admin_of__isnull=False),
    )

    return qs.exclude(id=user.id).distinct()


def can_impersonate_user(request, target_profile):
    """Jinja2 template helper: can the current user impersonate target_profile?

    target_profile is a Profile instance (the user being viewed).
    """
    # Don't show impersonate button while already impersonating
    if getattr(request, 'impersonator', None):
        return False

    real_user = request.user

    if not real_user.is_authenticated:
        return False

    target_user = target_profile.user

    # Cannot impersonate yourself
    if real_user.id == target_user.id:
        return False

    # Superuser can impersonate any non-superuser
    if real_user.is_superuser:
        return not target_user.is_superuser

    # Non-superuser must have at least one impersonate permission
    if not any(real_user.has_perm(p) for p in IMPERSONATE_PERMS):
        return False

    # Non-superuser cannot impersonate protected users
    if _is_protected_user(target_user):
        return False

    # Check scope: target must be in at least one group the impersonator admins
    real_profile = real_user.profile

    if real_user.has_perm('judge.impersonate_org'):
        admin_org_ids = set(real_profile.admin_of.values_list('id', flat=True))
        if target_profile.organizations.filter(id__in=admin_org_ids).exists():
            return True

    if real_user.has_perm('judge.impersonate_class'):
        admin_class_ids = set(real_profile.class_admin_of.values_list('id', flat=True))
        if target_profile.classes.filter(id__in=admin_class_ids).exists():
            return True

    if real_user.has_perm('judge.impersonate_contest'):
        contest_ids = set()
        contest_ids.update(real_profile.authored_contests.values_list('id', flat=True))
        contest_ids.update(real_profile.curated_contests.values_list('id', flat=True))
        if contest_ids:
            has_participation = ContestParticipation.objects.filter(
                contest_id__in=contest_ids,
                virtual=ContestParticipation.LIVE,
                user=target_profile,
            ).exists()
            if has_participation:
                return True

    return False
