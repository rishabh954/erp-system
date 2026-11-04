from decimal import Decimal

from django import forms

from apps.authentication.models import User
from apps.company.models import Branch
from apps.purchase.models import Vendor

from .models import Asset, AssetCategory, AssetMaintenance


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = [
            "name",
            "asset_code",
            "category",
            "branch",
            "purchase_date",
            "purchase_cost",
            "salvage_value",
            "useful_life_years",
            "depreciation_method",
            "vendor",
            "serial_number",
            "model_number",
            "location",
            "assigned_to",
            "warranty_expiry",
            "notes",
            "image",
        ]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        if company is not None:
            self.fields["category"].queryset = AssetCategory.objects.filter(
                company=company, is_deleted=False
            )
            self.fields["branch"].queryset = Branch.objects.filter(
                company=company, is_active=True, is_deleted=False
            )
            self.fields["vendor"].queryset = Vendor.objects.filter(
                company=company, status="active", is_deleted=False
            )
            self.fields["assigned_to"].queryset = User.objects.filter(
                companies=company, is_active=True
            ).distinct()
        self.fields["purchase_cost"].min_value = Decimal("0")
        self.fields["salvage_value"].min_value = Decimal("0")
        self.fields["useful_life_years"].min_value = 1

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("purchase_cost") is not None
            and cleaned_data.get("salvage_value") is not None
            and cleaned_data["salvage_value"] > cleaned_data["purchase_cost"]
        ):
            self.add_error("salvage_value", "Cannot exceed the purchase cost.")
        return cleaned_data


class MaintenanceForm(forms.ModelForm):
    class Meta:
        model = AssetMaintenance
        fields = [
            "title",
            "description",
            "maintenance_type",
            "scheduled_date",
            "cost",
            "performed_by",
            "next_maintenance_date",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cost"].min_value = Decimal("0")

    def clean(self):
        cleaned_data = super().clean()
        scheduled = cleaned_data.get("scheduled_date")
        next_date = cleaned_data.get("next_maintenance_date")
        if scheduled and next_date and next_date < scheduled:
            self.add_error(
                "next_maintenance_date",
                "Next maintenance date must be on or after the scheduled date.",
            )
        return cleaned_data
