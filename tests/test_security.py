"""
Tests for Security & RBAC in ERP system.
"""
import pytest
from django.urls import reverse

from apps.administration.models import RolePermission
from apps.authentication.models import ModulePermission


@pytest.mark.django_db
class TestSecurity:
    def test_unauthenticated_access_redirects_to_login(self, client):
        """Test: unauthenticated access redirects to login"""
        response = client.get(reverse('dashboard:index'))
        assert response.status_code == 302
        assert 'login' in response.url

    def test_cross_company_data_access(self, client, company, user):
        """Test: cross-company data access returns 403 or 404"""
        from apps.company.models import Company
        from apps.crm.models import Customer

        company2 = Company.objects.create(name="Other Co", legal_name="Other", company_type="LLC")
        cust2 = Customer.objects.create(company=company2, name="Cross Co Customer")

        client.force_login(user)
        response = client.get(reverse('crm:customer_detail', kwargs={'pk': cust2.pk}))
        assert response.status_code == 404

    def test_rbac_user_without_permission_cannot_access(self, client, user, company):
        """Test: RBAC: user without 'ai.read' cannot access /ai/ views"""
        RolePermission.objects.filter(role=user.role).delete()
        ModulePermission.objects.filter(role=user.role).delete()
        user.is_superuser = False
        user.save()
        client.force_login(user)

        response = client.get(reverse('ai:hub'))
        assert response.status_code in (403, 302, 404)

    def test_csrf_token_required_for_post(self, user):
        """Test: CSRF token required for POST requests"""
        from django.test import Client as DjangoClient
        user.is_superuser = True
        user.save()
        # enforce_csrf_checks must be passed at construction — setting the
        # attribute afterwards is a no-op because ClientHandler is already built.
        csrf_client = DjangoClient(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        response = csrf_client.post(reverse('crm:customer_create'), {"name": "Test"})
        assert response.status_code == 403
