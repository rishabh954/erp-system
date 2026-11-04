from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import TemplateView, View

from apps.crm.models import Contract
from apps.documents.models import Document
from apps.helpdesk.forms import TicketCreateForm
from apps.helpdesk.models import Ticket, TicketCategory, TicketReply
from apps.hrms.models import Employee, ExpenseClaim, LeaveRequest
from apps.purchase.models import Bill, PurchaseOrder
from apps.purchase.models import Payment as PurchasePayment
from apps.sales.models import Invoice, SalesOrder, Shipment
from apps.sales.models import Payment as SalesPayment

from .forms import CustomerProfileForm, VendorProfileForm

# ------------------------------------------------------------------------
# CUSTOMER PORTAL VIEWS
# ------------------------------------------------------------------------


class CustomerPortalMixin(LoginRequiredMixin):
    """Base mixin for customer portal."""

    login_url = "/auth/login/"

    def get_customer(self):
        return getattr(self.request.user, "customer_profile", None)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.get_customer():
            messages.error(request, "No customer account is linked to this login.")
            return redirect("auth:login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.get_customer()
        return ctx


class CustomerPortalView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cust = self.get_customer()
        orders_qs = SalesOrder.objects.filter(customer=cust).order_by("-order_date")
        invoices_qs = Invoice.objects.filter(customer=cust).order_by("-invoice_date")
        tickets_qs = Ticket.objects.filter(customer=cust)
        ctx["orders"] = orders_qs[:5]
        ctx["invoices"] = invoices_qs[:5]
        ctx["total_orders"] = orders_qs.count()
        ctx["open_orders"] = orders_qs.exclude(
            status__in=["delivered", "cancelled"]
        ).count()
        ctx["unpaid_invoices"] = invoices_qs.exclude(status="paid").count()
        ctx["open_tickets"] = tickets_qs.filter(
            status__in=["open", "in_progress", "reopened"]
        ).count()
        return ctx


class CustomerOrderListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_orders.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["orders"] = SalesOrder.objects.filter(
            customer=self.get_customer()
        ).order_by("-order_date")
        return ctx


class CustomerOrderDetailView(CustomerPortalMixin, View):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_order_detail.html"

    def get(self, request, pk):
        cust = self.get_customer()
        order = get_object_or_404(SalesOrder, pk=pk, customer=cust)
        return render(request, self.template_name, {"order": order, "customer": cust})


class CustomerInvoiceListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_invoices.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["invoices"] = Invoice.objects.filter(customer=self.get_customer()).order_by(
            "-invoice_date"
        )
        return ctx


class CustomerPaymentListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"
    template_name = "portals/customer_payments.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payments"] = SalesPayment.objects.filter(
            customer=self.get_customer()
        ).order_by("-payment_date")
        return ctx


class CustomerTicketListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_tickets.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tickets"] = Ticket.objects.filter(customer=self.get_customer()).order_by(
            "-created_at"
        )
        return ctx


class CustomerTicketDetailView(CustomerPortalMixin, View):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_ticket_detail.html"

    def get(self, request, pk):
        cust = self.get_customer()
        ticket = get_object_or_404(Ticket, pk=pk, customer=cust)
        return render(request, self.template_name, {"ticket": ticket, "customer": cust})

    def post(self, request, pk):
        cust = self.get_customer()
        ticket = get_object_or_404(Ticket, pk=pk, customer=cust)
        content = request.POST.get("content", "").strip()
        if content:
            with transaction.atomic():
                TicketReply.objects.create(
                    company=ticket.company,
                    ticket=ticket,
                    author=request.user,
                    content=content,
                    is_internal=False,
                )
                if ticket.status in ["resolved", "closed"]:
                    ticket.status = Ticket.Status.REOPENED
                    ticket.save(update_fields=["status"])
            messages.success(request, "Your reply has been sent.")
        return redirect("portals:customer_ticket_detail", pk=pk)


class CustomerTicketCreateView(CustomerPortalMixin, View):
    required_permission = "portals.create"
    template_name = "portals/customer_ticket_create.html"

    def get(self, request):
        customer = self.get_customer()
        categories = TicketCategory.objects.filter(
            company=customer.company, is_active=True, is_deleted=False
        )
        return render(
            request,
            self.template_name,
            {"categories": categories, "customer": customer},
        )

    def post(self, request):
        cust = self.get_customer()
        form = TicketCreateForm(request.POST, company=cust.company)
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(
                    error for errors in form.errors.values() for error in errors
                ),
            )
            return redirect("portals:customer_ticket_create")
        data = form.cleaned_data
        with transaction.atomic():
            ticket = Ticket.objects.create(
                company=cust.company,
                customer=cust,
                title=data["title"],
                description=data["description"],
                priority=data["priority"],
                category=data["category"],
                requester=request.user,
                source=Ticket.Source.PORTAL,
                status=Ticket.Status.OPEN,
            )
        messages.success(request, f"Ticket {ticket.number} submitted successfully.")
        return redirect("portals:customer_ticket_detail", pk=ticket.pk)


class CustomerDocumentListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_documents.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["documents"] = Document.objects.filter(
            company=self.get_customer().company
        ).order_by("-created_at")[:20]
        return ctx


class CustomerContractListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_contracts.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["contracts"] = Contract.objects.filter(
            customer=self.get_customer()
        ).order_by("-start_date")
        return ctx


class CustomerShipmentListView(CustomerPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_shipments.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = SalesOrder.objects.filter(customer=self.get_customer())
        ctx["shipments"] = Shipment.objects.filter(sales_order__in=orders).order_by(
            "-created_at"
        )
        return ctx


class CustomerShipmentDetailView(CustomerPortalMixin, View):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_shipment_detail.html"

    def get(self, request, pk):
        cust = self.get_customer()
        orders = SalesOrder.objects.filter(customer=cust)
        shipment = get_object_or_404(Shipment, pk=pk, sales_order__in=orders)
        return render(
            request, self.template_name, {"shipment": shipment, "customer": cust}
        )


class CustomerProfileView(CustomerPortalMixin, View):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/customer_profile.html"

    def get(self, request):
        return render(request, self.template_name, {"customer": self.get_customer()})

    def post(self, request):
        cust = self.get_customer()
        form = CustomerProfileForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(
                    error for errors in form.errors.values() for error in errors
                ),
            )
            return redirect("portals:customer_profile")
        with transaction.atomic():
            if "phone" in request.POST:
                cust.phone = form.cleaned_data["phone"]
            if "billing_address" in request.POST:
                cust.address_line1 = form.cleaned_data["billing_address"]
            cust.save(update_fields=["phone", "address_line1"])
        messages.success(request, "Profile updated successfully.")
        return redirect("portals:customer_profile")


# ------------------------------------------------------------------------
# VENDOR PORTAL VIEWS
# ------------------------------------------------------------------------


class VendorPortalMixin(LoginRequiredMixin):
    """Base mixin for vendor portal."""

    login_url = "/auth/login/"

    def get_vendor(self):
        return getattr(self.request.user, "vendor_profile", None)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.get_vendor():
            messages.error(request, "No vendor account is linked to this login.")
            return redirect("auth:login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vendor"] = self.get_vendor()
        return ctx


class VendorPortalView(VendorPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/vendor_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vendor = self.get_vendor()
        pos_qs = PurchaseOrder.objects.filter(vendor=vendor).order_by("-order_date")
        bills_qs = Bill.objects.filter(vendor=vendor).order_by("-bill_date")
        ctx["orders"] = pos_qs[:5]
        ctx["bills"] = bills_qs[:5]
        ctx["total_orders"] = pos_qs.count()
        ctx["pending_orders"] = pos_qs.filter(status="draft").count()
        ctx["unpaid_bills"] = bills_qs.exclude(status="paid").count()
        return ctx


class VendorOrderListView(VendorPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/vendor_orders.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["orders"] = PurchaseOrder.objects.filter(vendor=self.get_vendor()).order_by(
            "-order_date"
        )
        return ctx


class VendorOrderDetailView(VendorPortalMixin, View):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/vendor_order_detail.html"

    def get(self, request, pk):
        vendor = self.get_vendor()
        order = get_object_or_404(PurchaseOrder, pk=pk, vendor=vendor)
        return render(request, self.template_name, {"order": order, "vendor": vendor})


class VendorBillListView(VendorPortalMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/vendor_bills.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["bills"] = Bill.objects.filter(vendor=self.get_vendor()).order_by("-bill_date")
        return ctx


class VendorPaymentListView(VendorPortalMixin, TemplateView):
    required_permission = "portals.read"
    template_name = "portals/vendor_payments.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payments"] = PurchasePayment.objects.filter(
            vendor=self.get_vendor()
        ).order_by("-payment_date")
        return ctx


class VendorProfileView(VendorPortalMixin, View):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/vendor_profile.html"

    def get(self, request):
        return render(request, self.template_name, {"vendor": self.get_vendor()})

    def post(self, request):
        vendor = self.get_vendor()
        form = VendorProfileForm(request.POST)
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(
                    error for errors in form.errors.values() for error in errors
                ),
            )
            return redirect("portals:vendor_profile")
        if "phone" in request.POST:
            vendor.phone = form.cleaned_data["phone"]
            vendor.save(update_fields=["phone"])
        messages.success(request, "Profile updated successfully.")
        return redirect("portals:vendor_profile")


# ------------------------------------------------------------------------
# EMPLOYEE PORTAL VIEWS (STUB)
# ------------------------------------------------------------------------


class EmployeePortalView(LoginRequiredMixin, TemplateView):
    required_permission = "portals.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "portals.create"
            elif request.method in ["PUT", "PATCH"]:
                return "portals.update"
            elif request.method == "DELETE":
                return "portals.delete"
        return self.required_permission
    template_name = "portals/employee_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = Employee.objects.filter(user=self.request.user).first()
        ctx["employee"] = emp
        if emp:
            ctx["leaves"] = LeaveRequest.objects.filter(employee=emp).order_by(
                "-start_date"
            )[:5]
            ctx["expenses"] = ExpenseClaim.objects.filter(employee=emp).order_by(
                "-expense_date"
            )[:5]
        return ctx
