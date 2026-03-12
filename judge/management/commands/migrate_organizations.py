"""
Management command to migrate from "one Organization per session" to "one Organization
with multiple Classes per course".

This command reads a JSON configuration file that specifies:
- Target organization (with optional creation)
- Source organizations to migrate from
- Class names and slugs to create for each source organization
- Admin assignment rules

The migration:
- Creates Classes under the target organization
- Adds source organization members to both the target organization and their respective Class
- Moves Problems from source to target organization (adds Class visibility)
- Moves Contests from source to target organization (adds Class visibility)
- Handles join_organizations field for contests
- Keeps old organizations as empty shells (not deleted)

Usage:
    python manage.py migrate_organizations config.json --dry-run
    python manage.py migrate_organizations config.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from judge.models import Class, Contest, Organization, Problem


class DryRunRollback(Exception):
    """Internal sentinel exception to trigger a rollback in dry-run mode."""


class Command(BaseCommand):
    help = (
        'Migrate organizations from "one org per session" to "one org with multiple classes". '
        'Reads a JSON config file specifying target org, source orgs, and class mappings.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'config_path',
            type=str,
            help='Path to the JSON configuration file.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without applying them to the database.',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each migrated item.',
        )

    def handle(self, *args, **opts):
        config_path = Path(opts['config_path']).expanduser().resolve()
        if not config_path.exists():
            raise CommandError(f'Config file not found: {config_path}')

        try:
            with config_path.open('r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON in config file: {e}')

        migrations = config.get('migrations', [])
        if not migrations:
            self.stdout.write(self.style.WARNING('No migrations defined in config file.'))
            return

        dry_run = opts['dry_run']
        verbose = opts['verbose']

        if dry_run:
            self.stdout.write(self.style.NOTICE('=== DRY RUN MODE - No changes will be saved ==='))

        try:
            with transaction.atomic():
                for i, migration in enumerate(migrations, start=1):
                    self.stdout.write('')
                    self.stdout.write(self.style.NOTICE(f'--- Migration {i}/{len(migrations)} ---'))
                    self._process_migration(migration, dry_run, verbose)

                if dry_run:
                    raise DryRunRollback()

        except DryRunRollback:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('=== DRY RUN COMPLETE - No changes were saved ==='))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Migration complete.'))

    def _process_migration(self, migration: dict, dry_run: bool, verbose: bool):
        """Process a single migration entry from the config."""
        target_config = migration.get('target_organization', {})
        source_configs = migration.get('source_organizations', [])

        if not target_config.get('slug'):
            raise CommandError('target_organization.slug is required.')

        # Get or create target organization
        target_org = self._get_or_create_target_org(target_config, dry_run)

        self.stdout.write(f'Target organization: {target_org.name} ({target_org.slug})')
        self.stdout.write(f'Source organizations: {len(source_configs)}')

        # Process each source organization
        for source_config in source_configs:
            self._process_source_org(target_org, source_config, dry_run, verbose)

    def _get_or_create_target_org(self, config: dict, dry_run: bool) -> Organization:
        """Get or create the target organization based on config."""
        slug = config['slug']
        name = config.get('name', slug.replace('-', ' ').title())
        short_name = config.get('short_name', slug[:20])
        create_if_missing = config.get('create_if_missing', False)

        try:
            org = Organization.objects.get(slug=slug)
            self.stdout.write(f'Found existing target organization: {org.name}')
            return org
        except Organization.DoesNotExist:
            if create_if_missing:
                org = Organization.objects.create(
                    slug=slug,
                    name=name,
                    short_name=short_name,
                    about='',
                )
                self.stdout.write(self.style.SUCCESS(f'Created target organization: {org.name} ({org.slug})'))
                return org
            else:
                raise CommandError(
                    f"Target organization '{slug}' not found. "
                    'Set create_if_missing: true in config to create it.',
                )

    def _process_source_org(self, target_org: Organization, config: dict, dry_run: bool, verbose: bool):
        """Process a single source organization migration."""
        source_slug = config.get('slug')
        class_name = config.get('class_name')
        class_slug = config.get('class_slug')
        make_admins_org_admins = config.get('make_admins_org_admins', False)
        make_admins_class_admins = config.get('make_admins_class_admins', True)

        if not source_slug:
            raise CommandError('source_organizations[].slug is required.')
        if not class_name:
            raise CommandError(f'source_organizations[].class_name is required for source {source_slug}.')
        if not class_slug:
            raise CommandError(f'source_organizations[].class_slug is required for source {source_slug}.')

        # Get source organization
        try:
            source_org = Organization.objects.get(slug=source_slug)
        except Organization.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"Source organization '{source_slug}' not found. Skipping."))
            return

        self.stdout.write('')
        self.stdout.write(f'Processing source: {source_org.name} ({source_org.slug})')

        # Create or get Class under target organization
        new_class = self._get_or_create_class(target_org, class_name, class_slug, verbose)

        # Get source organization members and admins
        source_members = list(source_org.members.all())
        source_admins = list(source_org.admins.all())

        self.stdout.write(f'  Members to migrate: {len(source_members)}')
        self.stdout.write(f'  Admins in source: {len(source_admins)}')

        # Stats tracking
        stats = {
            'members_added_to_org': 0,
            'members_added_to_class': 0,
            'problems_migrated': 0,
            'contests_migrated': 0,
            'admins_added_to_org': 0,
            'admins_added_to_class': 0,
        }

        # Copy members to target org and new class
        for member in source_members:
            # Add to target organization (if not already a member)
            if not target_org.members.filter(id=member.id).exists():
                target_org.members.add(member)
                stats['members_added_to_org'] += 1
                if verbose:
                    self.stdout.write(f'    Added {member.user.username} to org {target_org.slug}')

            # Add to new class (if not already a member)
            if not new_class.members.filter(id=member.id).exists():
                new_class.members.add(member)
                stats['members_added_to_class'] += 1
                if verbose:
                    self.stdout.write(f'    Added {member.user.username} to class {new_class.slug}')

        # Handle admins based on config flags
        for admin in source_admins:
            if make_admins_org_admins:
                if not target_org.admins.filter(id=admin.id).exists():
                    target_org.admins.add(admin)
                    stats['admins_added_to_org'] += 1
                    if verbose:
                        self.stdout.write(f'    Added {admin.user.username} as org admin')

            if make_admins_class_admins:
                if not new_class.admins.filter(id=admin.id).exists():
                    new_class.admins.add(admin)
                    stats['admins_added_to_class'] += 1
                    if verbose:
                        self.stdout.write(f'    Added {admin.user.username} as class admin')

        # Move problems
        problems = Problem.objects.filter(organizations=source_org)
        for problem in problems:
            # Add target org to organizations
            if not problem.organizations.filter(id=target_org.id).exists():
                problem.organizations.add(target_org)

            # Add new class to classes
            if not problem.classes.filter(id=new_class.id).exists():
                problem.classes.add(new_class)

            # Remove source org from organizations
            problem.organizations.remove(source_org)
            stats['problems_migrated'] += 1

            if verbose:
                self.stdout.write(f'    Migrated problem: {problem.code}')

        # Move contests
        contests = Contest.objects.filter(organizations=source_org)
        for contest in contests:
            # Add target org to organizations
            if not contest.organizations.filter(id=target_org.id).exists():
                contest.organizations.add(target_org)

            # Add new class to classes
            if not contest.classes.filter(id=new_class.id).exists():
                contest.classes.add(new_class)

            # Remove source org from organizations
            contest.organizations.remove(source_org)
            stats['contests_migrated'] += 1

            if verbose:
                self.stdout.write(f'    Migrated contest: {contest.key}')

        # Handle join_organizations field for contests
        join_contests = Contest.objects.filter(join_organizations=source_org)
        join_contests_count = 0
        for contest in join_contests:
            # Add target org to join_organizations
            if not contest.join_organizations.filter(id=target_org.id).exists():
                contest.join_organizations.add(target_org)

            # Remove source org from join_organizations
            contest.join_organizations.remove(source_org)
            join_contests_count += 1

            if verbose:
                self.stdout.write(f'    Updated join_organizations for contest: {contest.key}')

        # Print summary for this source org
        self.stdout.write(f'  Summary for {source_org.slug}:')
        self.stdout.write(f'    Members added to org: {stats["members_added_to_org"]}')
        self.stdout.write(f'    Members added to class: {stats["members_added_to_class"]}')
        self.stdout.write(f'    Problems migrated: {stats["problems_migrated"]}')
        self.stdout.write(f'    Contests migrated: {stats["contests_migrated"]}')
        if join_contests_count > 0:
            self.stdout.write(f'    Contests join_organizations updated: {join_contests_count}')
        self.stdout.write(f'    Admins added to org: {stats["admins_added_to_org"]}')
        self.stdout.write(f'    Admins added to class: {stats["admins_added_to_class"]}')

    def _get_or_create_class(self, org: Organization, name: str, slug: str, verbose: bool) -> Class:
        """Get or create a Class under the given organization."""
        # Check if class already exists with same slug under this org
        try:
            existing_class = Class.objects.get(slug=slug, organization=org)
            if verbose:
                self.stdout.write(f'  Found existing class: {existing_class.name}')
            return existing_class
        except Class.DoesNotExist:
            pass

        # Check if class name is already taken (globally unique constraint for active classes)
        try:
            existing_by_name = Class.objects.get(name=name, is_active=True)
            # Name conflict - append org slug to make unique
            new_name = f'{name} ({org.slug})'
            self.stdout.write(
                self.style.WARNING(
                    f"  Class name '{name}' already exists. Using '{new_name}' instead.",
                ),
            )
            name = new_name
        except Class.DoesNotExist:
            pass

        # Create new class
        new_class = Class.objects.create(
            organization=org,
            name=name,
            slug=slug,
            description='',
            is_active=True,
        )
        self.stdout.write(self.style.SUCCESS(f'  Created class: {new_class.name} ({new_class.slug})'))
        return new_class
