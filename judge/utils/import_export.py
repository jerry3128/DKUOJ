
import csv
import io
import zipfile
from typing import Optional, Tuple

from django.contrib.auth.models import User
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils.translation import gettext as _

from judge.models import (
    Class, Contest, ContestParticipation, ContestSubmission, Organization, Profile, SubmissionSource)


class UserImportResult:
    def __init__(self):
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.errors = []
        self.org_linked = 0
        self.class_linked = 0


def process_user_csv(csv_file, organization: Organization = None, target_class: Class = None,
                     update_existing: bool = False, activate: bool = True) -> UserImportResult:
    """
    Parses a CSV file object and imports users.
    Expected CSV columns: username, first_name, last_name, email, password (optional)
    """
    result = UserImportResult()

    # Read CSV content
    try:
        decoded_file = csv_file.read().decode('utf-8-sig').splitlines()
    except UnicodeDecodeError:
        result.errors.append(_('File is not a valid UTF-8 CSV.'))
        return result

    reader = csv.DictReader(decoded_file)
    if not reader.fieldnames:
        result.errors.append(_('CSV file is empty or missing headers.'))
        return result

    required = {'username', 'first_name', 'last_name', 'email'}
    headers = {h.strip() for h in reader.fieldnames}
    missing = required - headers
    if missing:
        result.errors.append(_('Missing required columns: %s') % ', '.join(sorted(missing)))
        return result

    for row_idx, raw in enumerate(reader, start=1):
        row = {k.strip(): (v or '').strip() for k, v in raw.items()}
        username = row.get('username')
        if not username:
            continue

        try:
            with transaction.atomic():
                outcome, user = _upsert_user(row, update_existing, activate)
                if outcome == 'created':
                    result.created += 1
                elif outcome == 'updated':
                    result.updated += 1
                else:
                    result.skipped += 1

                if organization and user:
                    if _add_user_to_org(user, organization):
                        result.org_linked += 1

                if target_class and user:
                    if _add_user_to_class(user, target_class):
                        result.class_linked += 1

        except Exception as exc:
            result.errors.append(_('Row %(row)d (%(username)s): %(error)s') % {
                'row': row_idx, 'username': username, 'error': str(exc),
            })

    return result


def _ensure_profile(user: User) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _upsert_user(row: dict, update_existing: bool, activate: bool) -> Tuple[str, Optional[User]]:
    username = row.get('username')
    first_name = row.get('first_name', '')
    last_name = row.get('last_name', '')
    email = row.get('email', '')
    password = row.get('password', '123456')  # Default password if not provided

    try:
        user = User.objects.get(username=username)
        if update_existing:
            updated_fields = []
            if first_name and user.first_name != first_name:
                user.first_name = first_name
                updated_fields.append('first_name')
            if last_name and user.last_name != last_name:
                user.last_name = last_name
                updated_fields.append('last_name')
            if email and user.email != email:
                user.email = email
                updated_fields.append('email')
            if activate and not user.is_active:
                user.is_active = True
                updated_fields.append('is_active')

            if updated_fields:
                user.save(update_fields=updated_fields)

            _ensure_profile(user)
            return 'updated', user
        else:
            return 'skipped', user
    except User.DoesNotExist:
        try:
            user = User.objects.create_user(
                username=username,
                email=email or '',
                password=password,
            )
            user.first_name = first_name or ''
            user.last_name = last_name or ''
            if activate:
                user.is_active = True
            user.save()
            _ensure_profile(user)
            return 'created', user
        except IntegrityError as e:
            raise Exception(f'Integrity Error: {str(e)}')


def _add_user_to_org(user: User, org: Organization) -> bool:
    profile = _ensure_profile(user)
    if org.members.filter(id=profile.id).exists():
        return False
    org.members.add(profile)
    return True


def _add_user_to_class(user: User, target_class: Class) -> bool:
    profile = _ensure_profile(user)
    if target_class.members.filter(id=profile.id).exists():
        return False
    target_class.members.add(profile)
    return True


# --- Contest Export Logic ---

def export_contest_scores_csv(contest: Contest, include_disqualified: bool = False,
                              include_virtual: bool = False) -> str:
    """
    Generates a CSV string of contest scores.
    """
    qs = ContestParticipation.objects.filter(contest=contest)
    if not include_disqualified:
        qs = qs.filter(is_disqualified=False)
    if not include_virtual:
        qs = qs.filter(virtual=ContestParticipation.LIVE)

    qs = qs.select_related('user__user').order_by('-score', 'cumtime', 'user__user__username')

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['NetID', 'first_name', 'last_name', 'score'])

    for participation in qs:
        user = participation.user.user
        writer.writerow([
            user.username or '',
            user.first_name or '',
            user.last_name or '',
            participation.score,
        ])

    return output.getvalue()


def export_contest_submissions_zip(contest: Contest, include_disqualified: bool = False,
                                   include_virtual: bool = False, latest_only: bool = True) -> bytes:
    """
    Generates a ZIP file (bytes) of contest submissions.
    """
    qs = ContestSubmission.objects.filter(participation__contest=contest)

    if not include_disqualified:
        qs = qs.filter(participation__is_disqualified=False)
    if not include_virtual:
        qs = qs.filter(participation__virtual=ContestParticipation.LIVE)

    qs = qs.select_related(
        'participation__user__user',
        'submission__user__user',
        'submission__problem',
        'submission__language',
        'problem__problem',
    ).prefetch_related('submission__source')

    if latest_only:
        qs = qs.order_by('submission__user_id', 'submission__problem_id', '-submission__date', '-submission__id')
    else:
        qs = qs.order_by('submission__user__user__username', 'submission__problem__code', 'submission__id')

    zip_buffer = io.BytesIO()
    seen_pairs = set()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for cs in qs.iterator():
            sub = cs.submission

            if latest_only:
                key = (sub.user_id, sub.problem_id)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)

            try:
                source_obj = sub.source
            except SubmissionSource.DoesNotExist:
                continue

            if not source_obj or not source_obj.source:
                continue

            prof_user = sub.user.user
            username = prof_user.username or f'user{prof_user.id}'
            problem_code = (sub.problem.code or cs.problem.problem.code or f'prob{cs.problem_id}')

            ext = sub.language.extension or 'txt'
            fname = f'{username}/{problem_code}-{sub.id}.{ext}'
            zf.writestr(fname, source_obj.source)

    return zip_buffer.getvalue()
