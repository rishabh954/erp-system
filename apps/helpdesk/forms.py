from django import forms
from django.db.models import Q

from apps.authentication.models import User

from .models import Ticket, TicketCategory


class TicketCreateForm(forms.Form):
    title = forms.CharField(max_length=500)
    description = forms.CharField()
    category = forms.ModelChoiceField(
        queryset=TicketCategory.objects.none(), required=False
    )
    priority = forms.ChoiceField(choices=Ticket.Priority.choices, required=False)
    source = forms.ChoiceField(choices=Ticket.Source.choices, required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["category"].queryset = TicketCategory.objects.filter(
            company=company, is_active=True, is_deleted=False
        ).filter(
            Q(auto_assign_to__isnull=True)
            | Q(auto_assign_to__companies=company, auto_assign_to__is_active=True)
        )

    def clean_priority(self):
        return self.cleaned_data["priority"] or Ticket.Priority.MEDIUM

    def clean_source(self):
        return self.cleaned_data["source"] or Ticket.Source.PORTAL


class TicketUpdateForm(forms.Form):
    content = forms.CharField(required=False)
    is_internal = forms.BooleanField(required=False)
    new_status = forms.ChoiceField(
        choices=(("", "---------"), *Ticket.Status.choices), required=False
    )
    assigned_to = forms.ModelChoiceField(queryset=User.objects.none(), required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(
            companies=company, is_active=True
        ).distinct()
