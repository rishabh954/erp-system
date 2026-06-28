from django.views.generic import TemplateView, View, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from apps.sales.models import SalesOrder, Invoice
from apps.purchase.models import PurchaseOrder, Bill
from apps.hrms.models import LeaveRequest, ExpenseClaim, Employee
from apps.helpdesk.models import Ticket, TicketReply, TicketCategory
from apps.crm.models import Customer


class PortalMixin(LoginRequiredMixin):
    """Base mixin for customer portal. Ensures the user has a customer profile."""
    login_url = '/auth/login/'

    def get_customer(self):
        return getattr(self.request.user, 'customer_profile', None)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.get_customer():
            messages.error(request, "No customer account is linked to this login.")
            return redirect('auth:login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['customer'] = self.get_customer()
        return ctx


class CustomerPortalView(PortalMixin, TemplateView):
    template_name = 'portals/customer_dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cust = self.get_customer()
        orders_qs = SalesOrder.objects.filter(customer=cust).order_by('-date')
        invoices_qs = Invoice.objects.filter(customer=cust).order_by('-date')
        tickets_qs = Ticket.objects.filter(customer=cust)

        ctx['orders'] = orders_qs[:5]
        ctx['invoices'] = invoices_qs[:5]
        ctx['total_orders'] = orders_qs.count()
        ctx['open_orders'] = orders_qs.exclude(status__in=['delivered', 'cancelled']).count()
        ctx['unpaid_invoices'] = invoices_qs.exclude(status='paid').count()
        ctx['open_tickets'] = tickets_qs.filter(status__in=['open', 'in_progress', 'reopened']).count()
        return ctx


class CustomerOrderListView(PortalMixin, TemplateView):
    template_name = 'portals/customer_orders.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['orders'] = SalesOrder.objects.filter(customer=self.get_customer()).order_by('-date')
        return ctx


class CustomerOrderDetailView(PortalMixin, View):
    template_name = 'portals/customer_order_detail.html'

    def get(self, request, pk):
        from django.shortcuts import render
        cust = self.get_customer()
        order = get_object_or_404(SalesOrder, pk=pk, customer=cust)
        return render(request, self.template_name, {'order': order, 'customer': cust})


class CustomerInvoiceListView(PortalMixin, TemplateView):
    template_name = 'portals/customer_invoices.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['invoices'] = Invoice.objects.filter(customer=self.get_customer()).order_by('-date')
        return ctx


class CustomerTicketListView(PortalMixin, TemplateView):
    template_name = 'portals/customer_tickets.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tickets'] = Ticket.objects.filter(customer=self.get_customer()).order_by('-created_at')
        return ctx


class CustomerTicketDetailView(PortalMixin, View):
    template_name = 'portals/customer_ticket_detail.html'

    def get(self, request, pk):
        from django.shortcuts import render
        cust = self.get_customer()
        ticket = get_object_or_404(Ticket, pk=pk, customer=cust)
        return render(request, self.template_name, {'ticket': ticket, 'customer': cust})

    def post(self, request, pk):
        cust = self.get_customer()
        ticket = get_object_or_404(Ticket, pk=pk, customer=cust)
        content = request.POST.get('content', '').strip()
        if content:
            TicketReply.objects.create(
                company=ticket.company,
                ticket=ticket,
                author=request.user,
                content=content,
                is_internal=False,
            )
            # Reopen ticket if it was resolved/closed
            if ticket.status in ['resolved', 'closed']:
                ticket.status = Ticket.Status.REOPENED
                ticket.save(update_fields=['status'])
            messages.success(request, "Your reply has been sent.")
        return redirect('portals:customer_ticket_detail', pk=pk)


class CustomerTicketCreateView(PortalMixin, View):
    template_name = 'portals/customer_ticket_create.html'

    def get(self, request):
        from django.shortcuts import render
        categories = TicketCategory.objects.filter(is_active=True)
        return render(request, self.template_name, {'categories': categories, 'customer': self.get_customer()})

    def post(self, request):
        cust = self.get_customer()
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        priority = request.POST.get('priority', 'medium')
        category_id = request.POST.get('category')

        if not title or not description:
            messages.error(request, "Subject and description are required.")
            return redirect('portals:customer_ticket_create')

        category = None
        if category_id:
            category = TicketCategory.objects.filter(pk=category_id).first()

        ticket = Ticket.objects.create(
            company=cust.company,
            customer=cust,
            title=title,
            description=description,
            priority=priority,
            category=category,
            source=Ticket.Source.PORTAL,
            status=Ticket.Status.OPEN,
        )
        messages.success(request, f"Ticket {ticket.number} submitted successfully. Our team will respond shortly.")
        return redirect('portals:customer_ticket_detail', pk=ticket.pk)


# --- Legacy / other portal views kept for compatibility ---

class VendorPortalView(LoginRequiredMixin, TemplateView):
    template_name = 'portals/vendor_dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if hasattr(self.request.user, 'vendor_profile'):
            vendor = self.request.user.vendor_profile
            ctx['orders'] = PurchaseOrder.objects.filter(vendor=vendor).order_by('-date')[:5]
            ctx['bills'] = Bill.objects.filter(vendor=vendor).order_by('-date')[:5]
        return ctx


class EmployeePortalView(LoginRequiredMixin, TemplateView):
    template_name = 'portals/employee_dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = Employee.objects.filter(user=self.request.user).first()
        ctx['employee'] = emp
        if emp:
            ctx['leaves'] = LeaveRequest.objects.filter(employee=emp).order_by('-start_date')[:5]
            ctx['expenses'] = ExpenseClaim.objects.filter(employee=emp).order_by('-expense_date')[:5]
        return ctx
