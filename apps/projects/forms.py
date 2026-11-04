from django import forms

from apps.authentication.models import User
from apps.crm.models import Customer

from .models import Project, Task


class ProjectCreateForm(forms.Form):
    name = forms.CharField(max_length=500)
    description = forms.CharField(required=False)
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), required=False)
    status = forms.ChoiceField(choices=Project.Status.choices, required=False)
    priority = forms.ChoiceField(choices=Project.Priority.choices, required=False)
    start_date = forms.DateField(required=False)
    end_date = forms.DateField(required=False)
    budget = forms.DecimalField(
        required=False, max_digits=18, decimal_places=2, min_value=0, initial=0
    )
    is_billable = forms.BooleanField(required=False)

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["customer"].queryset = Customer.objects.filter(
            company=company, is_deleted=False
        )

    def clean_status(self):
        return self.cleaned_data["status"] or Project.Status.PLANNING

    def clean_priority(self):
        return self.cleaned_data["priority"] or Project.Priority.MEDIUM

    def clean_budget(self):
        return self.cleaned_data["budget"] if self.cleaned_data["budget"] is not None else 0

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be before start date.")
        return cleaned_data


class TaskCreateForm(forms.Form):
    project = forms.ModelChoiceField(queryset=Project.objects.none())
    title = forms.CharField(max_length=500)
    description = forms.CharField(required=False)
    status = forms.ChoiceField(choices=Task.Status.choices, required=False)
    priority = forms.ChoiceField(choices=Task.Priority.choices, required=False)
    assigned_to = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    due_date = forms.DateField(required=False)
    estimated_hours = forms.DecimalField(
        required=False, max_digits=8, decimal_places=2, min_value=0, initial=0
    )

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["project"].queryset = Project.objects.filter(
            company=company, is_deleted=False
        )
        self.fields["assigned_to"].queryset = User.objects.filter(
            companies=company,
            projectmember__project__company=company,
            projectmember__project__is_deleted=False,
            is_active=True,
        ).distinct()

    def clean_status(self):
        return self.cleaned_data["status"] or Task.Status.TODO

    def clean_priority(self):
        return self.cleaned_data["priority"] or Task.Priority.MEDIUM

    def clean_estimated_hours(self):
        value = self.cleaned_data["estimated_hours"]
        return value if value is not None else 0


class TimeLogCreateForm(forms.Form):
    hours = forms.DecimalField(max_digits=6, decimal_places=2, min_value=0)
    description = forms.CharField(required=False)
    is_billable = forms.BooleanField(required=False)

    def clean_hours(self):
        hours = self.cleaned_data["hours"]
        if hours <= 0:
            raise forms.ValidationError("Hours must be greater than zero.")
        return hours
