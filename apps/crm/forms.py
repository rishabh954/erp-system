from django import forms
from apps.authentication.models import User
from .models import Lead, Customer, Campaign

class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
            'name', 'company_name', 'email', 'phone', 'source', 'status', 
            'assigned_to', 'expected_revenue', 'probability', 
            'expected_close_date', 'notes', 'campaign'
        ]

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            'name', 'email', 'phone', 'mobile', 'website', 
            'customer_type', 'sales_rep', 'shipping_address', 'tax_id', 'currency', 'notes'
        ]

class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = [
            'name', 'status', 'start_date', 'end_date', 'budget', 'expected_revenue', 'notes'
        ]


