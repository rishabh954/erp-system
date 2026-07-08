import logging
import csv
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from apps.company.views import CompanyMixin

from .models import BankStatement, BankStatementLine


logger = logging.getLogger(__name__)


class BankStatementListView(CompanyMixin, ListView):
    template_name = "accounting/bank_statements/list.html"
    context_object_name = "statements"

    def get_queryset(self):
        return BankStatement.objects.filter(
            bank_account__company=self.company()
        ).select_related("bank_account")


class BankStatementCreateView(CompanyMixin, CreateView):
    model = BankStatement
    template_name = "accounting/bank_statements/form.html"
    fields = [
        "bank_account",
        "date_start",
        "date_end",
        "starting_balance",
        "ending_balance",
        "file_upload",
    ]

    def form_valid(self, form):
        form.instance.company = self.company()
        response = super().form_valid(form)

        # Parse CSV
        if self.object.file_upload:
            try:
                decoded_file = (
                    self.object.file_upload.read().decode("utf-8").splitlines()
                )
                reader = csv.DictReader(decoded_file)
                # Expecting columns: Date, Description, Amount, Reference
                for row in reader:
                    date_val = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                    amount_val = Decimal(row["Amount"])
                    BankStatementLine.objects.create(
                        statement=self.object,
                        date=date_val,
                        description=row.get("Description", ""),
                        amount=amount_val,
                        reference=row.get("Reference", ""),
                    )
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                messages.error(self.request, f"Failed to process CSV: {"An unexpected error occurred."}")

        return response

    def get_success_url(self):
        return reverse_lazy("accounting:bank_statement_list")
