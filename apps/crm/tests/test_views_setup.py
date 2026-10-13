"""
Regression tests for CRM setup views — Phase 4 fix.
Ensures TerritoryListView, TerritoryCreateView, LeadAssignmentRuleListView,
LeadAssignmentRuleCreateView, SalesTargetListView, SalesTargetCreateView
all have the required_permission attribute.
"""
import pytest

pytestmark = pytest.mark.django_db


class TestCRMSetupViewPermissions:
    """All CRM setup views must declare required_permission."""

    def _check_permission(self, view_cls, expected_permission):
        assert hasattr(view_cls, "required_permission"), (
            f"{view_cls.__name__} is missing required_permission attribute"
        )
        assert view_cls.required_permission == expected_permission, (
            f"{view_cls.__name__}.required_permission is '{view_cls.required_permission}', "
            f"expected '{expected_permission}'"
        )

    def test_territory_list_view_permission(self):
        from apps.crm.views_setup import TerritoryListView
        self._check_permission(TerritoryListView, "crm.read")

    def test_territory_create_view_permission(self):
        from apps.crm.views_setup import TerritoryCreateView
        self._check_permission(TerritoryCreateView, "crm.create")

    def test_lead_assignment_rule_list_view_permission(self):
        from apps.crm.views_setup import LeadAssignmentRuleListView
        self._check_permission(LeadAssignmentRuleListView, "crm.read")

    def test_lead_assignment_rule_create_view_permission(self):
        from apps.crm.views_setup import LeadAssignmentRuleCreateView
        self._check_permission(LeadAssignmentRuleCreateView, "crm.create")

    def test_sales_target_list_view_permission(self):
        from apps.crm.views_setup import SalesTargetListView
        self._check_permission(SalesTargetListView, "crm.read")

    def test_sales_target_create_view_permission(self):
        from apps.crm.views_setup import SalesTargetCreateView
        self._check_permission(SalesTargetCreateView, "crm.create")
