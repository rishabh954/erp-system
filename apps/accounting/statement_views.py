import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django import forms
from django.db import transaction
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from apps.company.views import CompanyMixin

from .models import BankAccount, BankStatement, BankStatementLine


class BankStatementListView(CompanyMixin, ListView):
    required_permission = "accounting.read"
    template_name = "accounting/bank_statements/list.html"
    context_object_name = "statements"

    def get_queryset(self):
        return BankStatement.objects.filter(
            bank_account__company=self.company()
        ).select_related("bank_account")


class BankStatementForm(forms.ModelForm):
    class Meta:
        model = BankStatement
        fields = [
            "bank_account",
            "date_start",
            "date_end",
            "starting_balance",
            "ending_balance",
            "file_upload",
        ]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = BankAccount.objects.filter(
            company=company, is_active=True, is_deleted=False
        )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("date_start")
        end = cleaned.get("date_end")
        if start and end and end < start:
            self.add_error("date_end", "End date must be on or after start date.")
        file_upload = cleaned.get("file_upload")
        if file_upload and file_upload.size > 10 * 1024 * 1024:
            self.add_error("file_upload", "CSV files must be 10 MB or smaller.")
        return cleaned


class BankStatementCreateView(CompanyMixin, CreateView):
    required_permission = "accounting.create"
    model = BankStatement
    form_class = BankStatementForm
    template_name = "accounting/bank_statements/form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.company()
        return kwargs

    def _parse_lines(self, form):
        uploaded = form.cleaned_data.get("file_upload")
        if not uploaded:
            return []
        try:
            content = uploaded.read().decode("utf-8-sig")
            uploaded.seek(0)
            reader = csv.DictReader(io.StringIO(content))
            required = {"Date", "Description", "Amount", "Reference"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("CSV must include Date, Description, Amount and Reference headers.")
            rows = []
            for row_number, row in enumerate(reader, start=2):
                if not any((value or "").strip() for value in row.values()):
                    continue
                try:
                    line_date = date.fromisoformat((row.get("Date") or "").strip())
                    amount = Decimal((row.get("Amount") or "").strip())
                except (ValueError, InvalidOperation):
                    raise ValueError(f"CSV row {row_number} has an invalid date or amount.") from None
                description = (row.get("Description") or "").strip()
                if line_date < form.cleaned_data["date_start"] or line_date > form.cleaned_data["date_end"]:
                    raise ValueError(f"CSV row {row_number} date is outside the statement period.")
                if not amount.is_finite() or amount.as_tuple().exponent < -2 or amount.adjusted() > 17:
                    raise ValueError(f"CSV row {row_number} amount must be finite with at most 2 decimals.")
                if not description or len(description) > 500:
                    raise ValueError(f"CSV row {row_number} needs a description of 1–500 characters.")
                rows.append(
                    {
                        "date": line_date,
                        "amount": amount,
                        "description": description,
                        "reference": (row.get("Reference") or "").strip()[:200],
                    }
                )
            if not rows:
                raise ValueError("CSV must contain at least one transaction.")
            return rows
        except (UnicodeDecodeError, csv.Error):
            raise ValueError("Upload a valid UTF-8 CSV file.") from None

    def form_invalid(self, form):
        try:
            form._validated_lines = self._parse_lines(form) if form.is_valid() else []
        except ValueError as exc:
            form.add_error("file_upload", str(exc))
        return super().form_invalid(form)

    def form_valid(self, form):
        try:
            rows = self._parse_lines(form)
        except ValueError as exc:
            form.add_error("file_upload", str(exc))
            return self.form_invalid(form)
        with transaction.atomic():
            form.instance.company = self.company()
            self.object = form.save()
            BankStatementLine.objects.bulk_create(
                [
                    BankStatementLine(statement=self.object, **row)
                    for row in rows
                ]
            )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("accounting:bank_statement_list")
