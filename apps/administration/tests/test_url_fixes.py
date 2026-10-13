"""
Regression tests for administration URL bug fixes — Phase 4.

- BUG-ADMIN-1: AdminRequiredMixin redirected to "dashboard:home" (doesn't exist),
               should be "dashboard:index".
- BUG-ADMIN-2: DataImportView.post redirected to "administration:import_export"
               (doesn't exist), should be "administration:data_import".
- BUG-PURCHASE-1: CreateBillFromPOView redirected to "purchase:po_detail" (wrong),
                  should be "purchase:order_detail".
"""
import pytest
from django.urls import NoReverseMatch, reverse

pytestmark = pytest.mark.django_db


class TestURLFixes:
    def test_dashboard_index_resolves(self):
        """dashboard:index must resolve without error."""
        url = reverse("dashboard:index")
        assert url is not None

    def test_dashboard_home_does_not_exist(self):
        """dashboard:home must NOT exist (it was the buggy URL name)."""
        with pytest.raises(NoReverseMatch):
            reverse("dashboard:home")

    def test_administration_data_import_resolves(self):
        """administration:data_import must resolve."""
        url = reverse("administration:data_import")
        assert url is not None

    def test_administration_import_export_does_not_exist(self):
        """administration:import_export must NOT exist."""
        with pytest.raises(NoReverseMatch):
            reverse("administration:import_export")

    def test_purchase_order_detail_resolves(self):
        """purchase:order_detail must resolve (was incorrectly po_detail)."""
        import uuid
        url = reverse("purchase:order_detail", kwargs={"pk": uuid.uuid4()})
        assert url is not None

    def test_admin_mixin_uses_dashboard_index(self):
        """AdminRequiredMixin.dispatch must reference dashboard:index, not dashboard:home."""
        import inspect
        from apps.administration.views import AdminRequiredMixin
        source = inspect.getsource(AdminRequiredMixin.dispatch)
        assert "dashboard:home" not in source, (
            "AdminRequiredMixin.dispatch still references 'dashboard:home'"
        )
        assert "dashboard:index" in source, (
            "AdminRequiredMixin.dispatch must reference 'dashboard:index'"
        )

    def test_data_import_view_uses_data_import_url(self):
        """DataImportView.post must use 'administration:data_import' redirect."""
        import inspect
        from apps.administration.views import DataImportView
        source = inspect.getsource(DataImportView.post)
        assert "import_export" not in source, (
            "DataImportView.post still uses 'administration:import_export'"
        )
        assert "data_import" in source, (
            "DataImportView.post must redirect to 'administration:data_import'"
        )

    def test_create_bill_from_po_uses_order_detail(self):
        """CreateBillFromPOView must redirect to purchase:order_detail, not po_detail."""
        import inspect
        from apps.purchase.views import CreateBillFromPOView
        source = inspect.getsource(CreateBillFromPOView.post)
        assert "po_detail" not in source, (
            "CreateBillFromPOView still uses 'purchase:po_detail'"
        )
        assert "order_detail" in source, (
            "CreateBillFromPOView must redirect to 'purchase:order_detail'"
        )
