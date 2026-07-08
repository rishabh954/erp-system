from django.core.management.base import BaseCommand

from apps.authentication.models import ModulePermission, User


class Command(BaseCommand):
    help = "Setup default RBAC permissions for all roles and modules"

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.NOTICE("Setting up default Module Permissions..."))

        # Define the modules in the system
        modules = [
            "sales",
            "crm",
            "accounting",
            "inventory",
            "projects",
            "hrms",
            "company",
            "purchase",
            "assets",
            "helpdesk",
            "documents",
            "notifications",
            "workflow",
            "dashboard",
            "manufacturing",
            "pos",
            "portals",
            "analytics",
            "ai",
        ]

        # Define the basic matrix: role -> module -> permissions (create, read, update, delete, approve, export, import)
        # We will use a helper structure:
        # matrix = { Role: { module: (c, r, u, d, a, e, i) } }
        # where tuple booleans correspond to the permissions

        # Default all False, only specify what is True
        # For Super Admin and Company Admin, we can just grant all in code.

        matrix = {
            User.Role.HR_MANAGER: {
                "hrms": (True, True, True, True, True, True, True),
                "company": (False, True, False, False, False, False, False),
            },
            User.Role.FINANCE_MANAGER: {
                "accounting": (True, True, True, True, True, True, True),
                "sales": (False, True, False, False, True, True, False),
                "purchase": (False, True, False, False, True, True, False),
                "hrms": (False, True, False, False, False, True, False),  # Read payroll
            },
            User.Role.SALES_MANAGER: {
                "sales": (True, True, True, True, True, True, True),
                "crm": (True, True, True, True, True, True, True),
                "inventory": (False, True, False, False, False, False, False),
            },
            User.Role.PURCHASE_MANAGER: {
                "purchase": (True, True, True, True, True, True, True),
                "inventory": (False, True, False, False, False, False, False),
                "accounting": (False, True, False, False, False, False, False),
            },
            User.Role.INVENTORY_MANAGER: {
                "inventory": (True, True, True, True, True, True, True),
                "purchase": (False, True, False, False, False, False, False),
                "sales": (False, True, False, False, False, False, False),
            },
            User.Role.PROJECT_MANAGER: {
                "projects": (True, True, True, True, True, True, True),
                "crm": (False, True, False, False, False, False, False),
                "hrms": (False, True, False, False, False, False, False),
            },
            User.Role.EMPLOYEE: {
                "hrms": (
                    False,
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                ),  # Can read own data, logic in views
                "projects": (
                    False,
                    True,
                    True,
                    False,
                    False,
                    False,
                    False,
                ),  # Can update assigned tasks
                "company": (False, True, False, False, False, False, False),
            },
            User.Role.CUSTOMER_PORTAL: {
                "sales": (
                    False,
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                ),  # Read own invoices
                "projects": (
                    False,
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                ),  # Read own projects
            },
        }

        created_count = 0
        updated_count = 0

        for role_choice in User.Role.choices:
            role = role_choice[0]

            for module in modules:
                # Determine permissions
                if role in [User.Role.SUPER_ADMIN, User.Role.COMPANY_ADMIN]:
                    c, r, u, d, a, e, i = (True, True, True, True, True, True, True)
                else:
                    role_matrix = matrix.get(role, {})
                    perms = role_matrix.get(
                        module, (False, False, False, False, False, False, False)
                    )
                    c, r, u, d, a, e, i = perms

                obj, created = ModulePermission.objects.update_or_create(
                    role=role,
                    module=module,
                    defaults={
                        "can_create": c,
                        "can_read": r,
                        "can_update": u,
                        "can_delete": d,
                        "can_approve": a,
                        "can_export": e,
                        "can_import": i,
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully set up permissions! Created: {created_count}, Updated: {updated_count}."
            )
        )
