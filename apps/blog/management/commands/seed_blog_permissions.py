"""
Management command: seed_blog_permissions

Seeds ModulePermission rows for module='blog' for all existing roles.
Run once after deploying the blog module:

    python manage.py seed_blog_permissions
"""

from django.core.management.base import BaseCommand

from apps.authentication.models import ModulePermission, User

BLOG_PERMISSIONS = {
    # role: (can_create, can_read, can_update, can_delete, can_approve, can_export, can_import)
    User.Role.SUPER_ADMIN:       (True,  True,  True,  True,  True,  True,  True),
    User.Role.COMPANY_ADMIN:     (True,  True,  True,  True,  True,  True,  True),
    User.Role.HR_MANAGER:        (False, True,  False, False, False, False, False),
    User.Role.FINANCE_MANAGER:   (False, True,  False, False, False, False, False),
    User.Role.SALES_MANAGER:     (True,  True,  True,  False, True,  True,  False),
    User.Role.PURCHASE_MANAGER:  (False, True,  False, False, False, False, False),
    User.Role.INVENTORY_MANAGER: (False, True,  False, False, False, False, False),
    User.Role.PROJECT_MANAGER:   (False, True,  False, False, False, False, False),
    User.Role.EMPLOYEE:          (True,  True,  True,  False, False, False, False),
    User.Role.CUSTOMER_PORTAL:   (False, False, False, False, False, False, False),
}


class Command(BaseCommand):
    help = "Seeds ModulePermission rows for the blog module."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for role, perms in BLOG_PERMISSIONS.items():
            (
                can_create, can_read, can_update, can_delete,
                can_approve, can_export, can_import,
            ) = perms

            obj, was_created = ModulePermission.objects.update_or_create(
                role=role,
                module="blog",
                defaults={
                    "can_create": can_create,
                    "can_read": can_read,
                    "can_update": can_update,
                    "can_delete": can_delete,
                    "can_approve": can_approve,
                    "can_export": can_export,
                    "can_import": can_import,
                    "can_manage_users": False,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(f"  Created: {role} → blog")
            else:
                updated += 1
                self.stdout.write(f"  Updated: {role} → blog")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {created}, updated {updated} blog permission rows."
            )
        )
