"""
Sales Module Views
Quotations, Sales Orders, Invoices, Payments — list/create/detail/update
"""

from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from decimal import Decimal

from .models import Quotation, QuotationLine, SalesOrder, SalesOrderLine, Invoice, InvoiceLine, Payment
from apps.crm.models import Customer
from apps.inventory.models import Product
from apps.company.models import Currency, Tax
from core.services import BaseService


# ─── Mixin: company scoping ───────────────────────────────────────────────────

class CompanyScopedMixin(LoginRequiredMixin):
    def get_company(self):
        return self.request.user.primary_company

    def get_base_qs(self, model):
        return model.objects.filter(
            company=self.get_company(), is_deleted=False
        ).select_related()


# ════════════════════════ QUOTATIONS ══════════════════════════════════════════

class QuotationListView(CompanyScopedMixin, ListView):
    template_name = 'sales/quotations/list.html'
    context_object_name = 'quotations'
    paginate_by = 25

    def get_queryset(self):
        qs = self.get_base_qs(Quotation).select_related('customer', 'sales_rep', 'branch').order_by('-created_at')
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Quotation.Status.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['search_query'] = self.request.GET.get('q', '')
        ctx['total_count'] = self.get_queryset().count()
        return ctx


class QuotationCreateView(CompanyScopedMixin, View):
    template_name = 'sales/quotations/form.html'

    def get(self, request):
        ctx = self._ctx()
        ctx['selected_customer'] = request.GET.get('customer_id')
        return render(request, self.template_name, ctx)

    def post(self, request):
        data = request.POST
        company = self.get_company()
        try:
            from .services import QuotationService
            service = QuotationService(user=request.user, company=company)
            quot = service.create_quotation(data, request.user)

            messages.success(request, f'Quotation {quot.number} created successfully.')
            return redirect('sales:quotation_detail', pk=quot.pk)

        except Exception as e:
            messages.error(request, f'Error creating quotation: {e}')
            return render(request, self.template_name, self._ctx())

    def _ctx(self):
        company = self.get_company()
        return {
            'customers': Customer.objects.filter(company=company, is_deleted=False).order_by('name'),
            'products': Product.objects.filter(company=company, is_active=True, is_deleted=False).order_by('name'),
            'currencies': Currency.objects.filter(is_active=True),
            'taxes': Tax.objects.filter(company=company, is_active=True),
            'status_choices': Quotation.Status.choices,
        }


class QuotationUpdateView(CompanyScopedMixin, View):
    template_name = 'sales/quotations/form.html'

    def get(self, request, pk):
        quotation = get_object_or_404(Quotation, pk=pk, company=self.get_company())
        ctx = QuotationCreateView()._ctx.__get__(self)()
        ctx['quotation'] = quotation
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        quotation = get_object_or_404(Quotation, pk=pk, company=self.get_company())
        data = request.POST
        try:
            quotation.customer_id = data['customer']
            quotation.validity_date = data.get('validity_date') or None
            quotation.delivery_date = data.get('delivery_date') or None
            quotation.payment_terms = int(data.get('payment_terms', 30))
            quotation.currency_id = data.get('currency') or None
            quotation.notes = data.get('notes', '')
            quotation.terms_conditions = data.get('terms_conditions', '')
            quotation.save()

            quotation.lines.all().delete()
            products   = data.getlist('product[]')
            descs      = data.getlist('description[]')
            quantities = data.getlist('quantity[]')
            prices     = data.getlist('unit_price[]')
            discounts  = data.getlist('discount_percent[]')
            taxes      = data.getlist('tax[]')

            for i, desc in enumerate(descs):
                if not desc.strip():
                    continue
                line = QuotationLine(
                    quotation=quotation,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal('1'),
                    unit_price=Decimal(str(prices[i])) if prices[i] else Decimal('0'),
                    discount_percent=Decimal(str(discounts[i])) if discounts[i] else Decimal('0'),
                    tax_id=taxes[i] if taxes[i] else None,
                    sort_order=i,
                )
                line.save()

            quotation.recalculate_totals()
            messages.success(request, f'Quotation {quotation.number} updated.')
            return redirect('sales:quotation_detail', pk=quotation.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            ctx = QuotationCreateView()._ctx.__get__(self)()
            ctx['quotation'] = quotation
            return render(request, self.template_name, ctx)


class QuotationDeleteView(CompanyScopedMixin, View):
    def post(self, request, pk):
        quot = get_object_or_404(Quotation, pk=pk, company=self.get_company())
        quot.delete()
        messages.success(request, f'Quotation {quot.number} deleted.')
        return redirect('sales:quotations')


class QuotationDetailView(CompanyScopedMixin, DetailView):
    template_name = 'sales/quotations/detail.html'
    context_object_name = 'quotation'

    def get_object(self):
        return get_object_or_404(Quotation.objects.select_related('customer', 'sales_rep', 'branch'), pk=self.kwargs['pk'],
                                  company=self.get_company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['lines'] = self.object.lines.all().select_related('product', 'tax')
        return ctx


class QuotationSendView(CompanyScopedMixin, View):
    def post(self, request, pk):
        quot = get_object_or_404(Quotation, pk=pk, company=self.get_company(), is_deleted=False)
        if quot.status == Quotation.Status.DRAFT:
            quot.status = Quotation.Status.SENT
            quot.save(update_fields=['status'])
            # Email customer
            if quot.customer.email:
                from apps.notifications.tasks import send_email_task
                send_email_task.delay(
                    to_email=quot.customer.email,
                    to_name=quot.customer.name,
                    subject=f'Quotation {quot.number} from {quot.company.name}',
                    template='quotation',
                    context={'quotation_number': quot.number, 'total': float(quot.total)},
                    company_id=str(quot.company_id),
                )
            messages.success(request, f'Quotation {quot.number} sent to {quot.customer.name}.')
        return redirect('sales:quotation_detail', pk=pk)


class QuotationRejectView(CompanyScopedMixin, View):
    def post(self, request, pk):
        quot = get_object_or_404(Quotation, pk=pk, company=self.get_company(), is_deleted=False)
        if quot.status in (Quotation.Status.CONVERTED,):
            messages.error(request, 'Converted Quotations cannot be rejected.')
            return redirect('sales:quotation_detail', pk=pk)
        
        quot.status = Quotation.Status.REJECTED
        reject_reason = request.POST.get('reject_reason', '').strip()
        if reject_reason:
            quot.reject_reason = reject_reason
        quot.save(update_fields=['status', 'reject_reason'])
        messages.success(request, f'Quotation {quot.number} marked as Rejected.')
        return redirect('sales:quotation_detail', pk=pk)

class QuotationApproveView(CompanyScopedMixin, View):
    def post(self, request, pk):
        quot = get_object_or_404(Quotation, pk=pk, company=self.get_company(), is_deleted=False)
        if quot.status in (Quotation.Status.CONVERTED, Quotation.Status.REJECTED):
            messages.error(request, 'Converted or rejected quotations cannot be approved.')
            return redirect('sales:quotation_detail', pk=pk)
        
        quot.status = Quotation.Status.APPROVED
        quot.save(update_fields=['status'])
        messages.success(request, f'Quotation {quot.number} approved successfully.')
        return redirect('sales:quotation_detail', pk=pk)

class QuotationConvertToSOView(CompanyScopedMixin, View):
    def post(self, request, pk):
        quot = get_object_or_404(Quotation, pk=pk, company=self.get_company(), is_deleted=False)
        if quot.status not in (Quotation.Status.SENT, Quotation.Status.APPROVED):
            messages.error(request, 'Quotation must be sent or approved before converting.')
            return redirect('sales:quotation_detail', pk=pk)

        try:
            from apps.sales.services import SalesService
            service = SalesService(request.user)
            
            # Check Credit Limit
            if not service.verify_credit_limit(quot.customer, quot.total):
                messages.warning(request, f'Credit limit exceeded for {quot.customer.name}. Order requires approval.')
                so = service.convert_quote_to_order(quot)
                so.status = SalesOrder.Status.DRAFT
                so.save(update_fields=['status'])
                messages.success(request, f'Sales Order {so.number} created (Draft pending approval).')
                return redirect('sales:order_detail', pk=so.pk)

            from apps.sales.services import SalesOrderService
            so = service.convert_quote_to_order(quot)
            so = SalesOrderService(user=request.user, company=self.get_company()).confirm_order(so)
            
            messages.success(request, f'Successfully converted to Sales Order {so.number}.')
            return redirect('sales:order_detail', pk=so.pk)
        except Exception as e:
            messages.error(request, f'Error converting quotation: {str(e)}')
            return redirect('sales:quotation_detail', pk=pk)


# ════════════════════════ SALES ORDERS ══════════════════════════════════════

class SalesOrderListView(CompanyScopedMixin, ListView):
    template_name = 'sales/orders/list.html'
    context_object_name = 'orders'
    paginate_by = 25

    def get_queryset(self):
        qs = self.get_base_qs(SalesOrder).select_related('customer').order_by('-order_date')
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = SalesOrder.Status.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        return ctx


class SalesOrderCreateView(CompanyScopedMixin, View):
    template_name = 'sales/orders/form.html'

    def get(self, request):
        return render(request, self.template_name, self._ctx())

    def post(self, request):
        data = request.POST
        company = self.get_company()
        try:
            from .services import SalesOrderService
            service = SalesOrderService(user=request.user, company=company)
            order = service.create_order(data, request.user)
            messages.success(request, f'Sales Order {order.number} created successfully.')
            return redirect('sales:orders')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return render(request, self.template_name, self._ctx())

    def _ctx(self):
        company = self.get_company()
        return {
            'customers': Customer.objects.filter(company=company, is_deleted=False).order_by('name'),
            'products': Product.objects.filter(company=company, is_active=True, is_deleted=False).order_by('name'),
            'currencies': Currency.objects.filter(is_active=True),
            'taxes': Tax.objects.filter(company=company, is_active=True),
            'status_choices': SalesOrder.Status.choices,
        }


class SalesOrderUpdateView(CompanyScopedMixin, View):
    template_name = 'sales/orders/form.html'

    def get(self, request, pk):
        order = get_object_or_404(SalesOrder, pk=pk, company=self.get_company())
        ctx = SalesOrderCreateView()._ctx.__get__(self)()
        ctx['order'] = order
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        order = get_object_or_404(SalesOrder, pk=pk, company=self.get_company())
        data = request.POST
        try:
            order.customer_id = data['customer']
            order.order_date = data.get('order_date') or timezone.now().date()
            order.delivery_date = data.get('delivery_date') or None
            order.payment_terms = int(data.get('payment_terms', 30))
            order.currency_id = data.get('currency') or None
            order.notes = data.get('notes', '')
            order.terms_conditions = data.get('terms_conditions', '')
            order.save()

            order.lines.all().delete()
            products   = data.getlist('product[]')
            descs      = data.getlist('description[]')
            quantities = data.getlist('quantity[]')
            prices     = data.getlist('unit_price[]')
            discounts  = data.getlist('discount_percent[]')
            taxes      = data.getlist('tax[]')

            for i, desc in enumerate(descs):
                if not desc.strip():
                    continue
                line = SalesOrderLine(
                    sales_order=order,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal('1'),
                    unit_price=Decimal(str(prices[i])) if prices[i] else Decimal('0'),
                    discount_percent=Decimal(str(discounts[i])) if discounts[i] else Decimal('0'),
                    tax_id=taxes[i] if taxes[i] else None,
                    sort_order=i,
                )
                line.save()

            order.recalculate_totals()
            messages.success(request, f'Sales Order {order.number} updated.')
            return redirect('sales:order_detail', pk=order.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            ctx = SalesOrderCreateView()._ctx.__get__(self)()
            ctx['order'] = order
            return render(request, self.template_name, ctx)


class SalesOrderDeleteView(CompanyScopedMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(SalesOrder, pk=pk, company=self.get_company())
        order.delete()
        messages.success(request, f'Sales Order {order.number} deleted.')
        return redirect('sales:orders')


class SalesOrderCancelView(CompanyScopedMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(SalesOrder, pk=pk, company=self.get_company(), is_deleted=False)
        
        if order.status in (SalesOrder.Status.SHIPPED, SalesOrder.Status.DELIVERED):
            messages.error(request, 'Cannot cancel an order that has already been shipped or delivered.')
            return redirect('sales:order_detail', pk=pk)
            
        if order.invoices.filter(status='paid').exists():
            messages.error(request, 'Cannot cancel an order with paid invoices.')
            return redirect('sales:order_detail', pk=pk)
            
        cancel_reason = request.POST.get('cancel_reason', '').strip()
        try:
            from apps.sales.services import SalesOrderService
            SalesOrderService(user=request.user, company=self.get_company()).cancel_order(order, reason=cancel_reason)
        except Exception as e:
            messages.error(request, f'Error cancelling order: {e}')
            return redirect('sales:order_detail', pk=pk)
        for delivery in order.delivery_orders.filter(status__in=['draft', 'ready']):
            delivery.status = 'cancelled'
            delivery.save(update_fields=['status'])
            
        messages.success(request, f'Sales Order {order.number} cancelled successfully.')
        return redirect('sales:order_detail', pk=pk)


class SalesOrderDetailView(CompanyScopedMixin, DetailView):
    template_name = 'sales/orders/detail.html'
    context_object_name = 'order'

    def get_object(self):
        return get_object_or_404(SalesOrder, pk=self.kwargs['pk'],
                                  company=self.get_company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['lines'] = self.object.lines.all().select_related('product', 'tax')
        ctx['invoices'] = self.object.invoices.filter(is_deleted=False)
        ctx['deliveries'] = self.object.delivery_orders.all()
        return ctx


class CreateDeliveryFromSOView(CompanyScopedMixin, View):
    def post(self, request, pk):
        so = get_object_or_404(SalesOrder, pk=pk, company=self.get_company(), is_deleted=False)
        try:
            from .services import SalesOrderService
            service = SalesOrderService(user=request.user, company=self.get_company())
            delivery = service.create_delivery(so)
            messages.success(request, f'Delivery Note {delivery.number} created successfully.')
            return redirect('inventory:delivery_detail', pk=delivery.pk)
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('sales:order_detail', pk=so.pk)


class CreateInvoiceFromSOView(CompanyScopedMixin, View):
    def post(self, request, pk):
        so = get_object_or_404(SalesOrder, pk=pk, company=self.get_company(), is_deleted=False)
        try:
            from .services import SalesOrderService
            service = SalesOrderService(user=request.user, company=self.get_company())
            inv = service.create_invoice(so)
            messages.success(request, f'Invoice {inv.number} created.')
            return redirect('sales:invoice_detail', pk=inv.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('sales:order_detail', pk=so.pk)
# ════════════════════════ INVOICES ════════════════════════════════════════════

class InvoiceListView(CompanyScopedMixin, ListView):
    template_name = 'sales/invoices/list.html'
    context_object_name = 'invoices'
    paginate_by = 25

    def get_queryset(self):
        qs = self.get_base_qs(Invoice).select_related('customer').order_by('-invoice_date')
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q))
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        ctx['status_choices'] = Invoice.Status.choices
        ctx['total_outstanding'] = qs.filter(
            status__in=['sent', 'partial']
        ).aggregate(t=Sum('balance_due'))['t'] or 0
        ctx['total_overdue'] = qs.filter(
            status__in=['sent', 'partial'],
            due_date__lt=timezone.now().date()
        ).aggregate(t=Sum('balance_due'))['t'] or 0
        return ctx


class InvoiceCreateView(CompanyScopedMixin, View):
    template_name = 'sales/invoices/form.html'

    def get(self, request):
        return render(request, self.template_name, self._ctx())

    def post(self, request):
        data = request.POST
        company = self.get_company()
        try:
            from .services import InvoiceService
            service = InvoiceService(user=request.user, company=company)
            invoice = service.create_invoice(data)
            messages.success(request, f'Invoice {invoice.number} created successfully.')
            return redirect('sales:invoices')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return render(request, self.template_name, self._ctx())

    def _ctx(self):
        company = self.get_company()
        return {
            'customers': Customer.objects.filter(company=company, is_deleted=False).order_by('name'),
            'products': Product.objects.filter(company=company, is_active=True, is_deleted=False).order_by('name'),
            'currencies': Currency.objects.filter(is_active=True),
            'taxes': Tax.objects.filter(company=company, is_active=True),
            'status_choices': Invoice.Status.choices,
        }


class InvoiceUpdateView(CompanyScopedMixin, View):
    template_name = 'sales/invoices/form.html'

    def get(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, company=self.get_company())
        if invoice.sales_order:
            messages.error(request, 'Invoices generated from Sales Orders cannot be edited directly.')
            return redirect('sales:invoice_detail', pk=invoice.pk)
        ctx = InvoiceCreateView()._ctx.__get__(self)()
        ctx['invoice'] = invoice
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, company=self.get_company())
        if invoice.sales_order:
            messages.error(request, 'Invoices generated from Sales Orders cannot be edited directly.')
            return redirect('sales:invoice_detail', pk=invoice.pk)
        data = request.POST
        try:
            invoice.customer_id = data['customer']
            invoice.invoice_date = data.get('invoice_date') or timezone.now().date()
            invoice.due_date = data.get('due_date') or timezone.now().date()
            invoice.payment_terms = int(data.get('payment_terms', 30))
            invoice.currency_id = data.get('currency') or None
            invoice.notes = data.get('notes', '')
            invoice.terms_conditions = data.get('terms_conditions', '')
            invoice.save()

            invoice.lines.all().delete()
            products   = data.getlist('product[]')
            descs      = data.getlist('description[]')
            quantities = data.getlist('quantity[]')
            prices     = data.getlist('unit_price[]')
            discounts  = data.getlist('discount_percent[]')
            taxes      = data.getlist('tax[]')

            for i, desc in enumerate(descs):
                if not desc.strip():
                    continue
                line = InvoiceLine(
                    invoice=invoice,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal('1'),
                    unit_price=Decimal(str(prices[i])) if prices[i] else Decimal('0'),
                    discount_percent=Decimal(str(discounts[i])) if discounts[i] else Decimal('0'),
                    tax_id=taxes[i] if taxes[i] else None,
                    sort_order=i,
                )
                line.save()

            invoice.recalculate_totals()
            messages.success(request, f'Invoice {invoice.number} updated.')
            return redirect('sales:invoice_detail', pk=invoice.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            ctx = InvoiceCreateView()._ctx.__get__(self)()
            ctx['invoice'] = invoice
            return render(request, self.template_name, ctx)


class InvoiceDeleteView(CompanyScopedMixin, View):
    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, company=self.get_company())
        if invoice.sales_order:
            messages.error(request, 'Invoices generated from Sales Orders cannot be deleted directly.')
            return redirect('sales:invoices')
        invoice.delete()
        messages.success(request, f'Invoice {invoice.number} deleted.')
        return redirect('sales:invoices')


class InvoiceDetailView(CompanyScopedMixin, DetailView):
    template_name = 'sales/invoices/detail.html'
    context_object_name = 'invoice'

    def get_object(self):
        return get_object_or_404(Invoice, pk=self.kwargs['pk'],
                                  company=self.get_company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['lines'] = self.object.lines.all().select_related('product', 'tax')
        ctx['payments'] = self.object.payments.filter(status='completed').order_by('payment_date')
        return ctx

class InvoiceGeneratePaymentLinkView(CompanyScopedMixin, View):
    def post(self, request, pk):
        from apps.administration.services.integrations import RazorpayService
        invoice = get_object_or_404(Invoice, pk=pk, company=self.get_company(), is_deleted=False)
        
        if invoice.status in ['paid', 'void']:
            messages.error(request, "Cannot generate payment link for paid or void invoices.")
            return redirect('sales:invoice_detail', pk=pk)
            
        service = RazorpayService(credentials={'api_key': 'mock', 'api_secret': 'mock'})
        
        try:
            # Calculate remaining amount
            paid_amount = sum(p.amount for p in invoice.payments.filter(status='completed'))
            remaining = invoice.total - paid_amount
            
            link = service.generate_payment_link(
                amount=float(remaining),
                currency=invoice.currency.code if invoice.currency else 'USD',
                reference_id=invoice.number,
                description=f"Payment for Invoice {invoice.number}",
                customer_email=invoice.customer.email if invoice.customer else '',
                customer_phone=invoice.customer.phone if invoice.customer else ''
            )
            
            # Save the link in invoice notes or just show it in a message for mock purposes
            invoice.notes = (invoice.notes or "") + f"\n\nPayment Link Generated: {link['short_url']}"
            invoice.save(update_fields=['notes'])
            
            messages.success(request, f"Payment link generated: {link['short_url']}")
        except Exception as e:
            messages.error(request, f"Error generating payment link: {e}")
            
        return redirect('sales:invoice_detail', pk=pk)


class InvoicePDFView(CompanyScopedMixin, View):
    def get(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, company=self.get_company(), is_deleted=False)
        lines = invoice.lines.all().select_related('product', 'tax')
        context = {
            'invoice': invoice,
            'lines': lines,
            'company': self.get_company(),
        }
        html = render(request, 'sales/invoices/pdf_template.html', context)
        try:
            from xhtml2pdf import pisa
            import io
            result = io.BytesIO()
            pdf = pisa.pisaDocument(io.BytesIO(html.content), result)
            if not pdf.err:
                response = HttpResponse(result.getvalue(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="{invoice.number}.pdf"'
                return response
            return html
        except Exception:
            return html


class RecordPaymentView(CompanyScopedMixin, View):
    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, company=self.get_company(), is_deleted=False)
        try:
            from .services import PaymentService
            service = PaymentService(user=request.user, company=self.get_company())
            payment = service.record_payment(invoice, request.POST)
            messages.success(request, f'Payment of {payment.amount} recorded for invoice {invoice.number}.')
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Error: {e}')

        return redirect('sales:invoice_detail', pk=pk)


class PaymentListView(CompanyScopedMixin, ListView):
    template_name = 'sales/payments/list.html'
    context_object_name = 'payments'
    paginate_by = 25

    def get_queryset(self):
        qs = self.get_base_qs(Payment).select_related('invoice', 'customer', 'currency').order_by('-payment_date')
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        method = self.request.GET.get('method', '')
        if q:
            qs = qs.filter(
                Q(number__icontains=q) | 
                Q(invoice__number__icontains=q) | 
                Q(customer__name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if method:
            qs = qs.filter(method=method)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base_qs = self.get_base_qs(Payment)
        ctx['status_choices'] = Payment.Status.choices
        ctx['method_choices'] = Payment.Method.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['current_method'] = self.request.GET.get('method', '')
        ctx['search_query'] = self.request.GET.get('q', '')
        
        # Dashboard aggregates
        ctx['total_received'] = base_qs.filter(status='completed').aggregate(t=Sum('amount'))['t'] or 0
        ctx['total_pending'] = base_qs.filter(status='pending').aggregate(t=Sum('amount'))['t'] or 0
        
        return ctx


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = 'sales'

urlpatterns = [
    # Quotations
    path('quotations/', QuotationListView.as_view(), name='quotations'),
    path('quotations/create/', QuotationCreateView.as_view(), name='quotation_create'),
    path('quotations/<uuid:pk>/', QuotationDetailView.as_view(), name='quotation_detail'),
    path('quotations/<uuid:pk>/send/', QuotationSendView.as_view(), name='quotation_send'),
    path('quotations/<uuid:pk>/convert/', QuotationConvertToSOView.as_view(), name='quotation_convert'),

    # Sales Orders
    path('orders/', SalesOrderListView.as_view(), name='orders'),
    path('orders/<uuid:pk>/', SalesOrderDetailView.as_view(), name='order_detail'),
    path('orders/<uuid:pk>/invoice/', CreateInvoiceFromSOView.as_view(), name='order_invoice'),

    # Invoices
    path('invoices/', InvoiceListView.as_view(), name='invoices'),
    path('invoices/<uuid:pk>/', InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<uuid:pk>/pdf/', InvoicePDFView.as_view(), name='invoice_pdf'),
    path('invoices/<uuid:pk>/payment/', RecordPaymentView.as_view(), name='invoice_payment'),

    # Payments
    path('payments/', InvoiceListView.as_view(), name='payments'),  # placeholder
]

# ════════════════════════ ENTERPRISE SALES VIEWS ═════════════════════════════

from .models import PriceList, PriceListItem, DiscountRule, Subscription, CreditNote, CreditNoteLine, SalesCommission

class PriceListListView(CompanyScopedMixin, ListView):
    template_name = 'sales/price_lists/list.html'
    context_object_name = 'price_lists'
    
    def get_queryset(self):
        return self.get_base_qs(PriceList)

class PriceListDetailView(CompanyScopedMixin, DetailView):
    template_name = 'sales/price_lists/detail.html'
    context_object_name = 'price_list'
    
    def get_queryset(self):
        return self.get_base_qs(PriceList)

class SubscriptionListView(CompanyScopedMixin, ListView):
    template_name = 'sales/subscriptions/list.html'
    context_object_name = 'subscriptions'
    
    def get_queryset(self):
        from django.db.models import Q
        qs = self.get_base_qs(Subscription).select_related('customer', 'product').order_by('-created_at')
        
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        
        if q:
            qs = qs.filter(
                Q(customer__name__icontains=q) |
                Q(product__name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
            
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['search_query'] = self.request.GET.get('q', '')
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['status_choices'] = Subscription.Status.choices
        return ctx

class SubscriptionDetailView(CompanyScopedMixin, DetailView):
    template_name = 'sales/subscriptions/detail.html'
    context_object_name = 'subscription'
    
    def get_queryset(self):
        return self.get_base_qs(Subscription).select_related('customer', 'product')

class CreditNoteListView(CompanyScopedMixin, ListView):
    template_name = 'sales/credit_notes/list.html'
    context_object_name = 'credit_notes'
    
    def get_queryset(self):
        return self.get_base_qs(CreditNote).select_related('customer', 'invoice', 'branch')

class CreditNoteDetailView(CompanyScopedMixin, DetailView):
    template_name = 'sales/credit_notes/detail.html'
    context_object_name = 'credit_note'
    
    def get_queryset(self):
        return self.get_base_qs(CreditNote).select_related('customer', 'invoice')

class SalesCommissionListView(CompanyScopedMixin, ListView):
    template_name = 'sales/commissions/list.html'
    context_object_name = 'commissions'
    
    def get_queryset(self):
        from django.db.models import Q
        qs = self.get_base_qs(SalesCommission).select_related('sales_rep', 'invoice').order_by('-created_at')
        if not self.request.user.is_superuser and self.request.user.role != 'company_admin':
            qs = qs.filter(sales_rep=self.request.user)
            
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        
        if q:
            qs = qs.filter(
                Q(sales_rep__first_name__icontains=q) |
                Q(sales_rep__last_name__icontains=q) |
                Q(invoice__number__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
            
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['search_query'] = self.request.GET.get('q', '')
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['status_choices'] = SalesCommission.Status.choices
        return ctx

class SalesCommissionPayView(CompanyScopedMixin, View):
    def post(self, request, pk):
        if not (request.user.is_superuser or request.user.role in ['company_admin', 'super_admin']):
            messages.error(request, 'Only administrators can mark commissions as paid.')
            return redirect('sales:commissions')
            
        commission = get_object_or_404(SalesCommission, pk=pk, company=self.get_company())
        if commission.status == SalesCommission.Status.PENDING:
            commission.status = SalesCommission.Status.PAID
            commission.save(update_fields=['status'])
            messages.success(request, f'Commission for {commission.sales_rep.full_name} marked as paid.')
        else:
            messages.info(request, 'Commission is already paid.')
            
        return redirect('sales:commissions')


class SubscriptionCreateView(CompanyScopedMixin, View):
    def get(self, request):
        from apps.crm.models import Customer
        from apps.inventory.models import Product
        return render(request, 'sales/subscriptions/form.html', {
            'customers': Customer.objects.filter(company=self.get_company(), is_deleted=False),
            'products': Product.objects.filter(company=self.get_company()),
            'cycles': Subscription.BillingCycle.choices,
            'statuses': Subscription.Status.choices
        })
        
    def post(self, request):
        from apps.crm.models import Customer
        from apps.inventory.models import Product
        customer = Customer.objects.get(pk=request.POST.get('customer'), company=self.get_company())
        product = Product.objects.get(pk=request.POST.get('product'), company=self.get_company())
        Subscription.objects.create(
            company=self.get_company(),
            customer=customer,
            product=product,
            billing_cycle=request.POST.get('billing_cycle'),
            status=request.POST.get('status'),
            start_date=request.POST.get('start_date'),
            next_billing_date=request.POST.get('next_billing_date'),
            recurring_amount=request.POST.get('recurring_amount')
        )
        messages.success(request, 'Subscription created.')
        return redirect('sales:subscriptions')

class SubscriptionUpdateView(CompanyScopedMixin, View):
    def get(self, request, pk):
        from apps.crm.models import Customer
        from apps.inventory.models import Product
        sub = get_object_or_404(Subscription, pk=pk, company=self.get_company())
        return render(request, 'sales/subscriptions/form.html', {
            'subscription': sub,
            'customers': Customer.objects.filter(company=self.get_company(), is_deleted=False),
            'products': Product.objects.filter(company=self.get_company()),
            'cycles': Subscription.BillingCycle.choices,
            'statuses': Subscription.Status.choices
        })
        
    def post(self, request, pk):
        sub = get_object_or_404(Subscription, pk=pk, company=self.get_company())
        sub.billing_cycle = request.POST.get('billing_cycle')
        sub.status = request.POST.get('status')
        sub.start_date = request.POST.get('start_date')
        sub.next_billing_date = request.POST.get('next_billing_date')
        sub.recurring_amount = request.POST.get('recurring_amount')
        sub.save()
        messages.success(request, 'Subscription updated.')
        return redirect('sales:subscriptions')

class SubscriptionGenerateInvoiceView(CompanyScopedMixin, View):
    def post(self, request, pk):
        from datetime import timedelta
        import calendar
        from core.services import BaseService
        
        sub = get_object_or_404(Subscription, pk=pk, company=self.get_company())
        
        if sub.status != Subscription.Status.ACTIVE:
            messages.error(request, 'Cannot generate invoice for inactive subscription.')
            return redirect('sales:subscription_detail', pk=sub.pk)
            
        inv = Invoice(
            company=sub.company,
            customer=sub.customer,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30), # Default 30 days term
            subtotal=sub.recurring_amount,
            tax_amount=0,
            discount_amount=0,
            total=sub.recurring_amount,
            balance_due=sub.recurring_amount,
        )
        inv.number = BaseService.generate_sequence_number('INV', Invoice, sub.company_id)
        inv.save()
        
        InvoiceLine.objects.create(
            invoice=inv,
            product=sub.product,
            description=f"Subscription: {sub.get_billing_cycle_display()} billing",
            quantity=1,
            unit_price=sub.recurring_amount,
            subtotal=sub.recurring_amount,
            total=sub.recurring_amount,
        )
        
        def add_months(sourcedate, months):
            month = sourcedate.month - 1 + months
            year = sourcedate.year + month // 12
            month = month % 12 + 1
            day = min(sourcedate.day, calendar.monthrange(year,month)[1])
            return sourcedate.replace(year=year, month=month, day=day)
            
        if sub.billing_cycle == 'monthly':
            sub.next_billing_date = add_months(sub.next_billing_date, 1)
        elif sub.billing_cycle == 'quarterly':
            sub.next_billing_date = add_months(sub.next_billing_date, 3)
        elif sub.billing_cycle == 'yearly':
            sub.next_billing_date = sub.next_billing_date.replace(year=sub.next_billing_date.year + 1)
            
        sub.save(update_fields=['next_billing_date'])
        
        messages.success(request, f'Invoice {inv.number} generated successfully. Next billing date advanced.')
        return redirect('sales:invoice_detail', pk=inv.pk)

# ════════════════════════ DASHBOARD & POS ════════════════════════════════════

class SalesDashboardView(CompanyScopedMixin, TemplateView):
    template_name = 'sales/dashboard.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Sum, Count
        from django.utils import timezone
        import datetime
        c = self.get_company()
        
        # Summary Metrics
        total_rev = Invoice.objects.filter(company=c, status__in=['paid', 'partial']).aggregate(t=Sum('amount_paid'))['t'] or 0
        ctx['total_revenue'] = total_rev
        ctx['outstanding_receivables'] = Invoice.objects.filter(company=c, status__in=['sent', 'partial', 'overdue']).aggregate(t=Sum('balance_due'))['t'] or 0
        ctx['orders_count'] = SalesOrder.objects.filter(company=c, status__in=['confirmed', 'processing', 'shipped']).count()
        
        # Profit & Margin Analysis (Simplified: Assuming 40% average margin if COGS isn't strictly tracked)
        profit = float(total_rev) * 0.40
        ctx['profit_analysis'] = profit
        ctx['margin_analysis'] = 40.0 # 40%
        
        # Sales Forecast (Sum of all sent/approved quotations)
        ctx['sales_forecast'] = Quotation.objects.filter(
            company=c, status__in=['sent', 'approved']
        ).aggregate(t=Sum('total'))['t'] or 0
        
        # Recent Orders
        ctx['recent_orders'] = SalesOrder.objects.filter(company=c).select_related('customer').order_by('-created_at')[:5]
        
        return ctx

class POSView(CompanyScopedMixin, TemplateView):
    template_name = 'sales/pos.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.inventory.models import Product
        from apps.crm.models import Customer
        from apps.company.models import Tax
        import json
        
        products = list(Product.objects.filter(company=self.get_company()).values('id', 'name', 'sku', 'sale_price', 'barcode'))
        for p in products:
            p['id'] = str(p['id'])
            p['sale_price'] = str(p['sale_price'])
            
        ctx['products_json'] = json.dumps(products)
        ctx['customers'] = Customer.objects.filter(company=self.get_company(), is_deleted=False).order_by('name')
        ctx['taxes'] = Tax.objects.filter(company=self.get_company()).order_by('name')
        return ctx

from django.http import JsonResponse
import json

class POSAPIView(CompanyScopedMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            customer_id  = data.get('customer_id') or ''
            items        = data.get('items', [])
            amount_paid  = float(data.get('amount_paid', 0))
            payment_method = data.get('payment_method', 'cash')

            if not items:
                return JsonResponse({'success': False, 'error': 'Cart is empty.'}, status=400)

            from apps.crm.models import Customer
            from apps.inventory.models import Product
            from apps.company.models import Currency
            from decimal import Decimal
            from datetime import date

            company = self.get_company()

            # ── Customer ─────────────────────────────────────────────────────
            if customer_id:
                customer = Customer.objects.get(pk=customer_id, company=company)
            else:
                customer, _ = Customer.objects.get_or_create(
                    company=company,
                    name='Walk-in Customer',
                    defaults={'phone': '0000000000'}
                )

            # ── Currency (required FK on Payment) ────────────────────────────
            currency = Currency.objects.filter(is_active=True).first()
            if not currency:
                currency = Currency.objects.first()
            if not currency:
                return JsonResponse({'success': False, 'error': 'No currency configured. Please add a currency in company settings.'}, status=400)

            # ── Create Invoice ────────────────────────────────────────────────
            invoice = Invoice.objects.create(
                company=company,
                customer=customer,
                invoice_date=timezone.localdate(),
                due_date=timezone.localdate(),
                status=Invoice.Status.DRAFT,
            )

            # ── Create Invoice Lines ──────────────────────────────────────────
            for item in items:
                prod = Product.objects.get(pk=item['product_id'], company=company)
                qty  = Decimal(str(item['quantity']))
                price = Decimal(str(item['price']))
                subtotal = qty * price
                InvoiceLine.objects.create(
                    invoice=invoice,
                    product=prod,
                    description=prod.name,
                    quantity=qty,
                    unit_price=price,
                    subtotal=subtotal,
                    tax_amount=Decimal('0'),
                    discount_amount=Decimal('0'),
                    total=subtotal,
                )

            # Recalculate totals from lines
            invoice.recalculate_totals()
            # Refresh from DB after recalculate
            invoice.refresh_from_db()

            # ── Record Payment ────────────────────────────────────────────────
            if amount_paid > 0:
                Payment.objects.create(
                    company=company,
                    invoice=invoice,
                    customer=customer,
                    amount=Decimal(str(amount_paid)),
                    currency=currency,
                    payment_date=timezone.localdate(),
                    method=payment_method,
                    status=Payment.Status.COMPLETED,
                )
                # This triggers update_balance → marks invoice paid/partial
                invoice.refresh_from_db()
                invoice.update_balance()

            change_due = max(0, amount_paid - float(invoice.total))

            return JsonResponse({
                'success': True,
                'invoice_id': str(invoice.pk),
                'invoice_number': invoice.number,
                'invoice_total': float(invoice.total),
                'amount_paid': amount_paid,
                'change_due': round(change_due, 2),
            })

        except Product.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'One or more products not found.'}, status=400)
        except Customer.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Customer not found.'}, status=400)
        except Exception as e:
            import traceback
            return JsonResponse({'success': False, 'error': str(e), 'detail': traceback.format_exc()}, status=400)
