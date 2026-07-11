"""
CRM Views
Leads, Pipeline, Customers, Activities
"""

from django.contrib import messages
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
    View,
)

from core.mixins import CompanyMixin
from core.services import BaseService

from .forms import LeadForm
from .models import Campaign, Contract, Customer, Lead, LeadActivity

# ════════════════════════ LEADS ═══════════════════════════════════════════════


class LeadListView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/leads/list.html"
    context_object_name = "leads"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Lead.objects.filter(company=self.company(), is_deleted=False)
            .select_related("assigned_to", "customer")
            .order_by("-created_at")
        )

        q = self.request.GET.get("q", "")
        status = self.request.GET.get("status", "")
        source = self.request.GET.get("source", "")

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(company_name__icontains=q)
                | Q(email__icontains=q)
                | Q(number__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if source:
            qs = qs.filter(source=source)

        # Non-sales managers see only their own leads
        if self.request.user.role not in (
            "sales_manager",
            "company_admin",
            "super_admin",
        ):
            qs = qs.filter(assigned_to=self.request.user)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        ctx["status_choices"] = Lead.Status.choices
        ctx["source_choices"] = Lead.Source.choices
        ctx["pipeline_counts"] = {
            s[0]: Lead.objects.filter(company=c, status=s[0], is_deleted=False).count()
            for s in Lead.Status.choices
        }
        ctx["total_value"] = (
            Lead.objects.filter(
                company=c,
                is_deleted=False,
                status__in=["qualified", "proposal", "negotiation", "won"],
            ).aggregate(t=Sum("expected_revenue"))["t"]
            or 0
        )
        return ctx


class LeadDetailView(CompanyMixin, DetailView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/leads/detail.html"
    context_object_name = "lead"

    def get_object(self):
        return get_object_or_404(
            Lead, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["activities"] = (
            self.object.activities.filter(is_deleted=False)
            .select_related("assigned_to")
            .order_by("-created_at")
        )
        ctx["activity_type_choices"] = LeadActivity.ActivityType.choices
        ctx["status_choices"] = Lead.Status.choices
        return ctx


class LeadCreateView(CompanyMixin, CreateView):
    required_permission = "crm.create"
    model = Lead
    form_class = LeadForm
    template_name = "crm/leads/form.html"

    def get_context_data(self, **kwargs):
        from apps.authentication.models import User

        ctx = super().get_context_data(**kwargs)
        c = self.request.user.primary_company
        ctx["status_choices"] = Lead.Status.choices
        ctx["source_choices"] = Lead.Source.choices
        ctx["sales_users"] = User.objects.filter(
            companies=c,
            is_active=True,
            role__in=["sales_manager", "employee", "company_admin"],
        ).order_by("first_name")
        ctx["campaigns"] = Campaign.objects.filter(company=c, is_deleted=False)
        return ctx

    def form_valid(self, form):
        # Generate sequence number and set other defaults
        form.instance.company = self.request.user.primary_company
        form.instance.number = BaseService.generate_sequence_number(
            "LD", Lead, self.request.user.primary_company.pk
        )
        messages.success(self.request, f"Lead {form.instance.name} created.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("crm:lead_detail", kwargs={"pk": self.object.pk})


class LeadUpdateView(CompanyMixin, UpdateView):
    required_permission = "crm.update"
    model = Lead
    form_class = LeadForm
    template_name = "crm/leads/form.html"
    context_object_name = "lead"

    def get_context_data(self, **kwargs):
        from apps.authentication.models import User

        ctx = super().get_context_data(**kwargs)
        c = self.request.user.primary_company
        ctx["status_choices"] = Lead.Status.choices
        ctx["source_choices"] = Lead.Source.choices
        ctx["sales_users"] = User.objects.filter(
            companies=c,
            is_active=True,
            role__in=["sales_manager", "employee", "company_admin"],
        ).order_by("first_name")
        ctx["campaigns"] = Campaign.objects.filter(company=c, is_deleted=False)
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Lead updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("crm:lead_detail", kwargs={"pk": self.object.pk})


class LeadDeleteView(CompanyMixin, View):
    required_permission = "crm.delete"
    def post(self, request, pk):
        c = self.company()
        lead = get_object_or_404(Lead, pk=pk, company=c)
        try:
            # Soft delete if supported
            if hasattr(lead, "is_deleted"):
                lead.is_deleted = True
                lead.save()
            else:
                lead.delete()
            messages.success(request, f"Lead {lead.number} deleted successfully.")
        except Exception as e:
            messages.error(request, f"Error deleting lead: {e}")
        return redirect("crm:leads")


class LeadUpdateStatusView(CompanyMixin, View):
    required_permission = "crm.update"
    """AJAX: update lead pipeline status."""

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk, company=self.company(), is_deleted=False)

        new_status = request.POST.get("status")
        if not new_status and request.content_type == "application/json":
            import json

            try:
                data = json.loads(request.body)
                new_status = data.get("status")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Failed to parse status: %s", e)

        if new_status in dict(Lead.Status.choices):
            lead.status = new_status
            if new_status == "won":
                lead.converted_to_customer = True
                if not lead.customer:
                    # Create Customer
                    from core.services import BaseService

                    cust = Customer(
                        company=lead.company,
                        name=lead.company_name if lead.company_name else lead.name,
                        email=lead.email,
                        phone=lead.phone,
                    )
                    cust.customer_code = BaseService.generate_sequence_number(
                        "CUST", Customer, lead.company.pk, field_name="customer_code"
                    )
                    cust.save()
                    lead.customer = cust
            lead.save(update_fields=["status", "converted_to_customer", "customer"])
            return JsonResponse(
                {"ok": True, "status": new_status, "label": lead.get_status_display()}
            )
        return JsonResponse({"ok": False, "error": "Invalid status"}, status=400)


# ════════════════════════ CAMPAIGNS ═══════════════════════════════════════════


class CampaignListView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/campaigns/list.html"
    context_object_name = "campaigns"
    paginate_by = 25

    def get_queryset(self):
        qs = Campaign.objects.filter(company=self.company()).order_by("-created_at")
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()

        if q:
            qs = qs.filter(name__icontains=q)
        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        context["status_choices"] = Campaign.Status.choices
        return context


class CampaignDetailView(CompanyMixin, DetailView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/campaigns/detail.html"
    context_object_name = "campaign"

    def get_queryset(self):
        return Campaign.objects.filter(company=self.company())


class CampaignCreateView(CompanyMixin, View):
    required_permission = "crm.create"
    def get(self, request):
        return render(
            request, "crm/campaigns/create.html", {"statuses": Campaign.Status.choices}
        )

    def post(self, request):
        campaign = Campaign.objects.create(
            company=self.company(),
            name=request.POST.get("name"),
            status=request.POST.get("status", "planning"),
            budget=request.POST.get("budget") or 0,
            expected_revenue=request.POST.get("expected_revenue") or 0,
        )
        messages.success(request, "Campaign created.")
        return redirect("crm:campaigns")


# ════════════════════════ PIPELINE & MEETINGS ═════════════════════════════════


class MeetingSchedulerView(CompanyMixin, TemplateView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/meeting_scheduler.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["meetings"] = LeadActivity.objects.filter(
            company=self.company(), activity_type="meeting"
        ).order_by("scheduled_at")
        return ctx


class LeadConvertView(CompanyMixin, View):
    required_permission = "crm.approve"
    """Convert won lead to a Customer record."""

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk, company=self.company(), is_deleted=False)
        if lead.customer:
            messages.info(request, "Lead already converted to customer.")
            return redirect("crm:customer_detail", pk=lead.customer.pk)

        customer = Customer(
            company=lead.company,
            name=lead.company_name or lead.name,
            email=lead.email,
            phone=lead.phone,
        )
        customer.customer_code = BaseService.generate_sequence_number(
            "CUST", Customer, lead.company_id, field_name="customer_code"
        )
        customer.save()

        lead.customer = customer
        lead.status = Lead.Status.WON
        lead.converted_to_customer = True
        lead.save(update_fields=["customer", "status", "converted_to_customer"])

        messages.success(request, f"Lead converted to customer: {customer.name}")
        return redirect("crm:customer_detail", pk=customer.pk)


class LeadToggleOpportunityView(CompanyMixin, View):
    required_permission = "crm.update"
    """Toggle a lead's status as an Opportunity."""

    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk, company=self.company(), is_deleted=False)
        lead.is_opportunity = not lead.is_opportunity
        lead.save(update_fields=["is_opportunity"])
        if lead.is_opportunity:
            messages.success(request, f"{lead.name} is now marked as an Opportunity.")
        else:
            messages.success(request, f"{lead.name} is now marked as a standard Lead.")
        return redirect("crm:lead_detail", pk=lead.pk)


class AddActivityView(CompanyMixin, View):
    required_permission = "crm.create"
    def post(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk, company=self.company(), is_deleted=False)
        duration = request.POST.get("duration_minutes")
        scheduled_at_str = request.POST.get("scheduled_at")

        scheduled_at = None
        if scheduled_at_str:
            from django.utils import timezone
            from django.utils.dateparse import parse_datetime

            dt = parse_datetime(scheduled_at_str)
            if dt is not None:
                if timezone.is_naive(dt):
                    scheduled_at = timezone.make_aware(dt)
                else:
                    scheduled_at = dt

        LeadActivity.objects.create(
            company=self.company(),
            lead=lead,
            activity_type=request.POST.get("activity_type", "note"),
            subject=request.POST.get("subject", ""),
            description=request.POST.get("description", ""),
            duration_minutes=int(duration) if duration else None,
            scheduled_at=scheduled_at,
            assigned_to=request.user,
        )
        messages.success(request, "Activity logged.")
        return redirect("crm:lead_detail", pk=pk)


# ════════════════════════ PIPELINE VIEW ══════════════════════════════════════


class PipelineView(CompanyMixin, TemplateView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/pipeline.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        stages = [s for s in Lead.Status.choices]
        columns = {}
        for val, label in stages:
            qs = (
                Lead.objects.filter(company=c, status=val, is_deleted=False)
                .select_related("assigned_to")
                .order_by("-expected_revenue")
            )
            columns[val] = {
                "label": label,
                "leads": qs,
                "count": qs.count(),
                "value": qs.aggregate(t=Sum("expected_revenue"))["t"] or 0,
            }
        ctx["columns"] = columns
        ctx["status_choices"] = Lead.Status.choices
        return ctx


# ════════════════════════ CUSTOMERS ══════════════════════════════════════════


class CustomerListView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/customers/list.html"
    context_object_name = "customers"
    paginate_by = 25

    def get_queryset(self):
        qs = Customer.objects.filter(company=self.company(), is_deleted=False).order_by(
            "name"
        )

        q = self.request.GET.get("q", "")
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(email__icontains=q)
                | Q(customer_code__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_count"] = Customer.objects.filter(
            company=self.company(), is_deleted=False
        ).count()
        return ctx


class CustomerDetailView(CompanyMixin, DetailView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/customers/detail.html"
    context_object_name = "customer"

    def get_object(self):
        return get_object_or_404(
            Customer, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        customer = self.object
        ctx["leads"] = customer.leads.filter(is_deleted=False).order_by("-created_at")
        try:
            from apps.sales.models import Invoice, SalesOrder

            ctx["invoices"] = Invoice.objects.filter(
                customer=customer, is_deleted=False
            ).order_by("-invoice_date")[:10]
            ctx["orders"] = SalesOrder.objects.filter(
                customer=customer, is_deleted=False
            ).order_by("-order_date")[:10]
            ctx["total_revenue"] = (
                Invoice.objects.filter(
                    customer=customer,
                    status__in=["sent", "partial", "paid"],
                    is_deleted=False,
                ).aggregate(t=Sum("total"))["t"]
                or 0
            )
            ctx["outstanding"] = customer.outstanding_balance
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to get customer context: %s", e)
        return ctx


class CustomerCreateView(CompanyMixin, View):
    required_permission = "crm.create"
    template_name = "crm/customers/form.html"

    def get(self, request):
        from apps.company.models import Currency

        return render(
            request,
            self.template_name,
            {
                "customer_type_choices": Customer.CustomerType.choices,
                "currencies": Currency.objects.filter(is_active=True),
            },
        )

    def post(self, request):
        data = request.POST
        company = self.company()

        email = data.get("email", "").strip()
        phone = data.get("phone", "").strip()

        if (
            email
            and Customer.objects.filter(
                company=company, email=email, is_deleted=False
            ).exists()
        ):
            messages.error(request, f"A customer with email '{email}' already exists.")
            return redirect("crm:customer_create")

        if (
            phone
            and Customer.objects.filter(
                company=company, phone=phone, is_deleted=False
            ).exists()
        ):
            messages.error(
                request, f"A customer with phone number '{phone}' already exists."
            )
            return redirect("crm:customer_create")

        try:
            customer = Customer(
                company=company,
                name=data["name"],
                customer_type=data.get("customer_type", "business"),
                customer_code=data.get("customer_code", "")
                or BaseService.generate_sequence_number(
                    "CUST", Customer, company.pk, field_name="customer_code"
                ),
                email=data.get("email", ""),
                phone=data.get("phone", ""),
                address_line1=data.get("address_line1", ""),
                city=data.get("city", ""),
                country=data.get("country", ""),
                shipping_address=data.get("shipping_address", ""),
                shipping_same_as_billing=data.get("shipping_same_as_billing") == "on",
                tax_id=data.get("tax_id", ""),
                credit_limit=float(data.get("credit_limit", 0)),
                payment_terms=int(data.get("payment_terms", 30)),
                currency_id=data.get("currency") or None,
                notes=data.get("notes", ""),
            )
            customer.save()
            messages.success(request, f"Customer {customer.name} created.")
            return redirect("crm:customer_detail", pk=customer.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return render(
                request,
                self.template_name,
                {
                    "customer_type_choices": Customer.CustomerType.choices,
                },
            )


class CustomerUpdateView(CompanyMixin, View):
    required_permission = "crm.update"
    template_name = "crm/customers/form.html"

    def get(self, request, pk):
        from apps.company.models import Currency

        customer = get_object_or_404(
            Customer, pk=pk, company=self.company(), is_deleted=False
        )
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "customer_type_choices": Customer.CustomerType.choices,
                "currencies": Currency.objects.filter(is_active=True),
            },
        )

    def post(self, request, pk):
        customer = get_object_or_404(
            Customer, pk=pk, company=self.company(), is_deleted=False
        )
        data = request.POST
        company = self.company()

        email = data.get("email", "").strip()
        phone = data.get("phone", "").strip()

        if (
            email
            and Customer.objects.filter(company=company, email=email, is_deleted=False)
            .exclude(pk=customer.pk)
            .exists()
        ):
            messages.error(
                request, f"Another customer with email '{email}' already exists."
            )
            return redirect("crm:customer_update", pk=customer.pk)

        if (
            phone
            and Customer.objects.filter(company=company, phone=phone, is_deleted=False)
            .exclude(pk=customer.pk)
            .exists()
        ):
            messages.error(
                request, f"Another customer with phone number '{phone}' already exists."
            )
            return redirect("crm:customer_update", pk=customer.pk)

        try:
            customer.name = data["name"]
            customer.customer_type = data.get("customer_type", "business")
            if data.get("customer_code"):
                customer.customer_code = data.get("customer_code")
            customer.email = data.get("email", "")
            customer.phone = data.get("phone", "")
            customer.address_line1 = data.get("address_line1", "")
            customer.city = data.get("city", "")
            customer.country = data.get("country", "")
            customer.shipping_address = data.get("shipping_address", "")
            customer.shipping_same_as_billing = (
                data.get("shipping_same_as_billing") == "on"
            )
            customer.tax_id = data.get("tax_id", "")
            customer.credit_limit = float(data.get("credit_limit", 0))
            customer.payment_terms = int(data.get("payment_terms", 30))
            customer.currency_id = data.get("currency") or None
            customer.notes = data.get("notes", "")
            customer.is_active = data.get("is_active") == "on"
            customer.save()
            messages.success(request, f"Customer {customer.name} updated successfully.")
            return redirect("crm:customer_detail", pk=customer.pk)
        except Exception as e:
            messages.error(request, f"Error updating customer: {e}")
            return redirect("crm:customer_update", pk=customer.pk)


class CustomerDeleteView(CompanyMixin, View):
    required_permission = "crm.delete"
    def post(self, request, pk):
        customer = get_object_or_404(
            Customer, pk=pk, company=self.company(), is_deleted=False
        )
        customer.is_deleted = True
        customer.save()
        messages.success(request, f"Customer {customer.name} deleted successfully.")
        return redirect("crm:customers")


# ════════════════════════ OPPORTUNITIES ══════════════════════════════════════


class OpportunityListView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/opportunities/list.html"
    context_object_name = "opportunities"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Lead.objects.filter(
                company=self.company(), is_deleted=False, is_opportunity=True
            )
            .select_related("assigned_to", "customer")
            .order_by("-expected_revenue")
        )

        status = self.request.GET.get("status", "")
        q = self.request.GET.get("q", "").strip()

        if status:
            qs = qs.filter(status=status)

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(customer__name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
            )

        if self.request.user.role not in (
            "sales_manager",
            "company_admin",
            "super_admin",
        ):
            qs = qs.filter(assigned_to=self.request.user)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_value"] = (
            self.get_queryset().aggregate(t=Sum("expected_revenue"))["t"] or 0
        )
        ctx["status_choices"] = Lead.Status.choices
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


# ════════════════════════ CONTRACTS ══════════════════════════════════════════


class ContractListView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/contracts/list.html"
    context_object_name = "contracts"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Contract.objects.filter(company=self.company())
            .select_related("customer")
            .order_by("-created_at")
        )
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(contract_number__icontains=q)
                | Q(customer__name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        context["status_choices"] = Contract.Status.choices
        return context


class ContractDetailView(CompanyMixin, DetailView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/contracts/detail.html"
    context_object_name = "contract"

    def get_object(self):
        return get_object_or_404(Contract, pk=self.kwargs["pk"], company=self.company())


class ContractCreateView(CompanyMixin, View):
    required_permission = "crm.create"
    def get(self, request):
        return render(
            request,
            "crm/contracts/form.html",
            {
                "customers": Customer.objects.filter(
                    company=self.company(), is_deleted=False
                ).order_by("name"),
                "statuses": Contract.Status.choices,
            },
        )

    def post(self, request):
        try:
            customer = get_object_or_404(
                Customer, pk=request.POST.get("customer"), company=self.company()
            )
            contract = Contract.objects.create(
                company=self.company(),
                customer=customer,
                title=request.POST.get("title"),
                contract_number=request.POST.get("contract_number", ""),
                status=request.POST.get("status", "draft"),
                start_date=request.POST.get("start_date"),
                end_date=request.POST.get("end_date") or None,
                value=request.POST.get("value") or 0,
                notes=request.POST.get("notes", ""),
            )
            if request.FILES.get("document"):
                contract.document = request.FILES["document"]
                contract.save()
            messages.success(request, "Contract created successfully.")
            return redirect("crm:contract_detail", pk=contract.pk)
        except Exception as e:
            messages.error(request, f"Error creating contract: {e}")
            return redirect("crm:contracts")


class ContractUpdateView(CompanyMixin, View):
    required_permission = "crm.update"
    def get(self, request, pk):
        contract = get_object_or_404(Contract, pk=pk, company=self.company())
        return render(
            request,
            "crm/contracts/form.html",
            {
                "contract": contract,
                "customers": Customer.objects.filter(
                    company=self.company(), is_deleted=False
                ).order_by("name"),
                "statuses": Contract.Status.choices,
            },
        )

    def post(self, request, pk):
        contract = get_object_or_404(Contract, pk=pk, company=self.company())
        try:
            customer = get_object_or_404(
                Customer, pk=request.POST.get("customer"), company=self.company()
            )
            contract.customer = customer
            contract.title = request.POST.get("title")
            contract.contract_number = request.POST.get("contract_number", "")
            contract.status = request.POST.get("status", "draft")
            contract.start_date = request.POST.get("start_date")
            contract.end_date = request.POST.get("end_date") or None
            contract.value = request.POST.get("value") or 0
            if request.POST.get("notes") is not None:
                contract.notes = request.POST.get("notes")

            if request.FILES.get("document"):
                contract.document = request.FILES["document"]

            contract.save()
            messages.success(request, "Contract updated successfully.")
            return redirect("crm:contract_detail", pk=contract.pk)
        except Exception as e:
            messages.error(request, f"Error updating contract: {e}")
            return redirect("crm:contract_detail", pk=contract.pk)


class ContractDeleteView(CompanyMixin, View):
    required_permission = "crm.delete"
    def post(self, request, pk):
        contract = get_object_or_404(Contract, pk=pk, company=self.company())
        title = contract.title
        contract.delete()
        messages.success(request, f'Contract "{title}" has been deleted.')
        return redirect("crm:contracts")


# ════════════════════════ INTERACTIONS ═══════════════════════════════════════


class InteractionListView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/interactions/list.html"
    context_object_name = "interactions"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            LeadActivity.objects.filter(company=self.company())
            .select_related("lead", "assigned_to")
            .order_by("-created_at")
        )
        if self.request.user.role not in (
            "sales_manager",
            "company_admin",
            "super_admin",
        ):
            qs = qs.filter(assigned_to=self.request.user)

        q = self.request.GET.get("q", "").strip()
        activity_type = self.request.GET.get("activity_type", "").strip()

        if q:
            qs = qs.filter(
                Q(subject__icontains=q)
                | Q(description__icontains=q)
                | Q(lead__name__icontains=q)
            )
        if activity_type:
            qs = qs.filter(activity_type=activity_type)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        context["activity_type_choices"] = LeadActivity.ActivityType.choices
        return context


# ════════════════════════ REPORTS ══════════════════════════════════════════════


class CampaignReportView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/campaigns/report.html"
    context_object_name = "campaigns"

    def get_queryset(self):
        qs = Campaign.objects.filter(company=self.company(), is_deleted=False).order_by(
            "-start_date"
        )
        status = self.request.GET.get("status", "").strip()
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Campaign.Status.choices

        # Calculate totals for the report
        qs = self.get_queryset()
        total_budget = sum(c.budget for c in qs)
        total_revenue = sum(c.actual_revenue_generated for c in qs)
        total_roi = (
            ((float(total_revenue) - float(total_budget)) / float(total_budget) * 100)
            if total_budget > 0
            else 0
        )

        ctx["totals"] = {
            "budget": total_budget,
            "revenue": total_revenue,
            "roi": total_roi,
            "campaigns": qs.count(),
        }
        return ctx


class ContractReportView(CompanyMixin, ListView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/contracts/report.html"
    context_object_name = "contracts"

    def get_queryset(self):
        # Default sort by end_date so expiring soonest are at top
        qs = Contract.objects.filter(company=self.company(), is_deleted=False).order_by(
            "end_date"
        )

        status = self.request.GET.get("status", "").strip()
        if status:
            qs = qs.filter(status=status)
        else:
            qs = qs.filter(status="active")

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Contract.Status.choices

        # Calculate totals for the report
        qs = self.get_queryset()
        total_value = sum(c.value for c in qs)

        import datetime

        from django.utils import timezone

        thirty_days = timezone.now().date() + datetime.timedelta(days=30)
        expiring_soon = sum(
            1
            for c in qs
            if c.end_date and timezone.now().date() <= c.end_date <= thirty_days
        )

        ctx["totals"] = {
            "value": total_value,
            "contracts": qs.count(),
            "expiring_soon": expiring_soon,
        }
        return ctx


# ════════════════════════ CRM DASHBOARD ══════════════════════════════════════


class CRMDashboardView(CompanyMixin, TemplateView):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    template_name = "crm/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()

        # Funnel Analytics
        leads = Lead.objects.filter(company=c, is_deleted=False)
        ctx["funnel"] = {
            "total": leads.count(),
            "opportunities": leads.filter(is_opportunity=True).count(),
            "won": leads.filter(status="won").count(),
        }

        # Calculate conversion rate
        if ctx["funnel"]["total"] > 0:
            ctx["funnel"]["conversion_rate"] = round(
                (ctx["funnel"]["won"] / ctx["funnel"]["total"]) * 100, 1
            )
        else:
            ctx["funnel"]["conversion_rate"] = 0

        # Recent Activities
        ctx["recent_activities"] = (
            LeadActivity.objects.filter(company=c)
            .select_related("lead", "assigned_to")
            .order_by("-created_at")[:5]
        )

        # CLV Estimate: Top Customers by total revenue (Invoice.objects.filter(customer=..., status='paid').aggregate(Sum('total')))
        # We can approximate this by sorting Customers by a property or doing an annotation.
        # For performance in a simple dashboard, we can just grab top 5 customers with most paid invoices.
        try:
            top_customers = (
                Customer.objects.filter(
                    company=c,
                    is_deleted=False,
                    invoices__status__in=["sent", "partial", "paid"],
                )
                .annotate(total_invoiced=Sum("invoices__total"))
                .order_by("-total_invoiced")[:5]
            )
            ctx["top_customers"] = top_customers
        except Exception:
            ctx["top_customers"] = []

        # Campaign Analytics
        active_campaigns = Campaign.objects.filter(
            company=c, status="active", is_deleted=False
        )
        total_budget = active_campaigns.aggregate(t=Sum("budget"))["t"] or 0
        total_revenue = 0
        for camp in active_campaigns:
            total_revenue += float(camp.actual_revenue_generated)

        ctx["campaigns"] = {
            "active_count": active_campaigns.count(),
            "total_budget": total_budget,
            "total_revenue": total_revenue,
            "roi": (
                (
                    (float(total_revenue) - float(total_budget))
                    / float(total_budget)
                    * 100
                )
                if total_budget > 0
                else 0
            ),
        }

        # Contracts Analytics
        import datetime

        from django.utils import timezone

        active_contracts = Contract.objects.filter(
            company=c, status="active", is_deleted=False
        )
        total_contract_value = active_contracts.aggregate(t=Sum("value"))["t"] or 0
        thirty_days_from_now = timezone.now().date() + datetime.timedelta(days=30)
        expiring_count = active_contracts.filter(
            end_date__lte=thirty_days_from_now, end_date__gte=timezone.now().date()
        ).count()

        ctx["contracts"] = {
            "active_value": total_contract_value,
            "expiring_count": expiring_count,
            "active_count": active_contracts.count(),
        }

        return ctx
