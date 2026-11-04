from decimal import Decimal

from django import forms

from .models import Campaign, Contract, Customer, Lead, LeadActivity


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

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            from apps.authentication.models import User

            self.fields["assigned_to"].queryset = User.objects.filter(
                companies=company, is_active=True
            ).distinct()
            self.fields["campaign"].queryset = Campaign.objects.filter(
                company=company, is_deleted=False
            )

    def clean_expected_revenue(self):
        return self.cleaned_data["expected_revenue"] or Decimal("0")


class CustomerForm(forms.ModelForm):
    customer_type = forms.ChoiceField(
        choices=Customer.CustomerType.choices, required=False
    )
    credit_limit = forms.DecimalField(
        max_digits=18, decimal_places=2, min_value=0, required=False
    )
    payment_terms = forms.IntegerField(min_value=0, required=False)

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
            "address_line1",
            "city",
            "country",
            "credit_limit",
            "payment_terms",
            "customer_code",
            "is_active",
        ]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["customer_code"].disabled = True

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and self.company is not None:
            customers = Customer.objects.filter(
                company=self.company, email__iexact=email, is_deleted=False
            )
            if self.instance.pk:
                customers = customers.exclude(pk=self.instance.pk)
            if customers.exists():
                raise forms.ValidationError("A customer with this email already exists.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone and self.company is not None:
            customers = Customer.objects.filter(
                company=self.company, phone=phone, is_deleted=False
            )
            if self.instance.pk:
                customers = customers.exclude(pk=self.instance.pk)
            if customers.exists():
                raise forms.ValidationError(
                    "A customer with this phone number already exists."
                )
        return phone

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("customer_type"):
            cleaned_data["customer_type"] = (
                self.instance.customer_type
                if self.instance.pk
                else Customer.CustomerType.BUSINESS
            )
        if cleaned_data.get("credit_limit") is None:
            cleaned_data["credit_limit"] = (
                self.instance.credit_limit
                if self.instance.pk
                else Decimal("0")
            )
        if cleaned_data.get("payment_terms") is None:
            cleaned_data["payment_terms"] = (
                self.instance.payment_terms if self.instance.pk else 30
            )
        return cleaned_data


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

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date must be on or after the start date.")
        return cleaned_data


class LeadActivityForm(forms.ModelForm):
    class Meta:
        model = LeadActivity
        fields = [
            "activity_type",
            "subject",
            "description",
            "duration_minutes",
            "scheduled_at",
        ]

    def clean_subject(self):
        subject = self.cleaned_data["subject"].strip()
        if not subject:
            raise forms.ValidationError("This field is required.")
        return subject


class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = [
            "customer",
            "title",
            "contract_number",
            "status",
            "start_date",
            "end_date",
            "value",
            "document",
            "notes",
        ]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["customer"].queryset = Customer.objects.filter(
                company=company, is_deleted=False
            )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date must be on or after the start date.")
        return cleaned_data
