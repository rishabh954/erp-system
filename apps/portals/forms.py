from django import forms


class CustomerProfileForm(forms.Form):
    phone = forms.CharField(max_length=30, required=False)
    billing_address = forms.CharField(max_length=255, required=False)


class VendorProfileForm(forms.Form):
    phone = forms.CharField(max_length=30, required=False)
