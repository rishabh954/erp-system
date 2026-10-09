from decimal import Decimal

from django import forms

from .models import Campaign, Customer, Lead


class LeadForm(forms.ModelForm):
    expected_revenue = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0,
        required=False,
    )

    class Meta:
        model = Lead
        fields = [
            "name",
            "company_name",
            "email",
            "phone",
            "source",
            "status",
            "assigned_to",
            "expected_revenue",
            "probability",
            "expected_close_date",
            "notes",
            "campaign",
        ]

    def clean_expected_revenue(self):
        return self.cleaned_data["expected_revenue"] or Decimal("0")


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "name",
            "email",
            "phone",
            "mobile",
            "website",
            "customer_type",
            "sales_rep",
            "shipping_address",
            "tax_id",
            "currency",
            "notes",
        ]


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = [
            "name",
            "status",
            "start_date",
            "end_date",
            "budget",
            "expected_revenue",
            "notes",
        ]
