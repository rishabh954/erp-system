from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.authentication.models import ModulePermission, Role, User
from apps.company.models import Company


class RBACTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Test Company")

        self.employee = User.objects.create_user(
            email="employee@test.com",
            password="password123",
            first_name="Emp",
            last_name="Loyee",
            role=User.Role.EMPLOYEE,
        )
        self.employee.companies.add(self.company)
        self.employee.primary_company = self.company
        self.employee.save()

        self.admin = User.objects.create_user(
            email="admin@test.com",
            password="password123",
            first_name="Ad",
            last_name="Min",
            role=User.Role.COMPANY_ADMIN,
        )
        self.admin.companies.add(self.company)
        self.admin.primary_company = self.company
        self.admin.save()

        self.role = Role.objects.create(
            company=self.company, name="Custom Role", code="custom-role"
        )

        self.mod_perm = ModulePermission.objects.create(
            role=User.Role.EMPLOYEE, module="test"
        )

    def test_employee_cannot_create_user(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.post("/api/v1/auth/users/", {"email": "new@test.com"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_user(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            "/api/v1/auth/users/",
            {
                "email": "new@test.com",
                "first_name": "New",
                "last_name": "User",
                "password": "password123",
                "password_confirm": "password123",
                "role": User.Role.EMPLOYEE,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_employee_cannot_deactivate_user(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.post(
            f"/api/v1/auth/users/{self.admin.id}/toggle_active/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_employee_cannot_create_role(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.post(
            "/api/v1/auth/roles/", {"name": "Hacker Role", "code": "hacker"}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_employee_cannot_update_module_permission(self):
        self.client.force_authenticate(user=self.employee)
        response = self.client.patch(
            f"/api/v1/auth/module-permissions/{self.mod_perm.id}/", {"can_create": True}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_update_module_permission(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch(
            f"/api/v1/auth/module-permissions/{self.mod_perm.id}/", {"can_create": True}
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN
        )  # Only superusers can edit module permissions
