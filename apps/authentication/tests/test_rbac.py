import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.authentication.models import ModulePermission, User
from apps.company.models import Company


@pytest.mark.django_db
class TestRBAC:
    @pytest.fixture
    def setup_data(self):
        self.company = Company.objects.create(name="Test Company")
        self.super_admin = User.objects.create_superuser("admin@test.com", "pass", first_name="Admin", last_name="User", primary_company=self.company)

        # User with limited role
        self.employee = User.objects.create_user(
            "emp@test.com", "pass",
            first_name="Emp", last_name="User",
            role=User.Role.EMPLOYEE,
            primary_company=self.company
        )
        self.employee.companies.add(self.company)

        # Give employee access to accounting read ONLY
        ModulePermission.objects.update_or_create(
            role=User.Role.EMPLOYEE,
            module="accounting",
            defaults={
                "can_read": True,
                "can_create": False,
                "can_update": False,
                "can_delete": False
            }
        )

        self.client_admin = APIClient()
        self.client_admin.force_authenticate(user=self.super_admin)

        self.client_emp = APIClient()
        self.client_emp.force_authenticate(user=self.employee)

    def test_drf_module_permission(self, setup_data):
        # Admin accesses quotes -> 200 (HasModulePermission lets superusers bypass)
        url = reverse("api:quotation-list")
        response = self.client_admin.get(url)
        assert response.status_code == status.HTTP_200_OK

        # Employee accesses quotes -> 403 (Doesn't have sales.read)
        response = self.client_emp.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_django_view_module_permission(self, setup_data, client):
        client.force_login(self.super_admin)
        url = reverse("accounting:chart_of_accounts")
        response = client.get(url)
        assert response.status_code == 200

        client.force_login(self.employee)
        # Employee has accounting.read, should succeed
        response = client.get(url)
        assert response.status_code == 200

        # Try to access create view (requires accounting.create)
        url_create = reverse("accounting:account_create")
        response_create = client.get(url_create)
        assert response_create.status_code == 403
