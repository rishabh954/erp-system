"""
Purchase Management Views
Vendors, Purchase Requests, Purchase Orders, Goods Receipts
"""

from django.views.generic import ListView, DetailView, View, TemplateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.db.models import Q, Sum
from django.utils import timezone
from django.urls import reverse_lazy

from .models import (
    Vendor, PurchaseRequest, PurchaseRequestLine,
    PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine
)
from core.services import BaseService


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


# ════════════════════════ VENDORS ═════════════════════════════════════════════

class VendorListView(CompanyMixin, ListView):
    template_name = 'purchase/vendors/list.html'
    context_object_name = 'vendors'
    paginate_by = 25

    def get_queryset(self):
        qs = Vendor.objects.filter(
            company=self.company(), is_deleted=False
        ).order_by('name')
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(vendor_code__icontains=q) | Q(email__icontains=q))
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Vendor.Status.choices
        ctx['total_count'] = Vendor.objects.filter(company=self.company(), is_deleted=False).count()
        return ctx


class VendorDetailView(CompanyMixin, DetailView):
    template_name = 'purchase/vendors/detail.html'
    context_object_name = 'vendor'

    def get_object(self):
        return get_object_or_404(Vendor, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vendor = self.object
        ctx['purchase_orders'] = vendor.purchase_orders.filter(
            is_deleted=False
        ).order_by('-order_date')[:10]
        ctx['total_orders'] = vendor.purchase_orders.filter(is_deleted=False).count()
        ctx['total_spent'] = vendor.purchase_orders.filter(
            is_deleted=False, status__in=['received', 'invoiced']
        ).aggregate(t=Sum('total'))['t'] or 0
        return ctx


class VendorCreateView(CompanyMixin, View):
    template_name = 'purchase/vendors/form.html'

    def get(self, request):
        from apps.company.models import Currency
        return render(request, self.template_name, {
            'vendor_type_choices': Vendor.VendorType.choices,
            'currencies': Currency.objects.filter(is_active=True),
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            vendor = Vendor(
                company=company,
                name=data['name'],
                vendor_code=data.get('vendor_code', ''),
                vendor_type=data.get('vendor_type', 'supplier'),
                email=data.get('email', ''),
                phone=data.get('phone', ''),
                address_line1=data.get('address_line1', ''),
                city=data.get('city', ''),
                country=data.get('country', ''),
                tax_id=data.get('tax_id', ''),
                payment_terms=int(data.get('payment_terms', 30)),
                currency_id=data.get('currency') or None,
                notes=data.get('notes', ''),
            )
            vendor.save()
            messages.success(request, f'Vendor {vendor.name} created.')
            return redirect('purchase:vendor_detail', pk=vendor.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('purchase:vendors')


class VendorUpdateView(CompanyMixin, View):
    template_name = 'purchase/vendors/form.html'

    def get(self, request, pk):
        from apps.company.models import Currency
        vendor = get_object_or_404(Vendor, pk=pk, company=self.company())
        return render(request, self.template_name, {
            'vendor': vendor,
            'vendor_type_choices': Vendor.VendorType.choices,
            'currencies': Currency.objects.filter(is_active=True),
        })

    def post(self, request, pk):
        vendor = get_object_or_404(Vendor, pk=pk, company=self.company())
        data = request.POST
        try:
            vendor.name = data['name']
            vendor.vendor_code = data.get('vendor_code', '')
            vendor.vendor_type = data.get('vendor_type', 'supplier')
            vendor.email = data.get('email', '')
            vendor.phone = data.get('phone', '')
            vendor.address_line1 = data.get('address_line1', '')
            vendor.city = data.get('city', '')
            vendor.country = data.get('country', '')
            vendor.tax_id = data.get('tax_id', '')
            vendor.payment_terms = int(data.get('payment_terms', 30))
            vendor.currency_id = data.get('currency') or None
            vendor.notes = data.get('notes', '')
            vendor.save()
            messages.success(request, f'Vendor {vendor.name} updated.')
            return redirect('purchase:vendor_detail', pk=vendor.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('purchase:vendor_update', pk=vendor.pk)


class VendorDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        vendor = get_object_or_404(Vendor, pk=pk, company=self.company())
        name = vendor.name
        try:
            vendor.delete()
            messages.success(request, f'Vendor {name} deleted.')
        except Exception as e:
            messages.error(request, f'Could not delete vendor {name}. It might be linked to other records. {e}')
        return redirect('purchase:vendors')


# ════════════════════════ PURCHASE REQUESTS ═══════════════════════════════════

class PurchaseRequestListView(CompanyMixin, ListView):
    template_name = 'purchase/requests/list.html'
    context_object_name = 'requests'
    paginate_by = 25

    def get_queryset(self):
        qs = PurchaseRequest.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('requested_by', 'department').order_by('-created_at')

        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)

        # Non-managers see only their own requests
        if self.request.user.role not in ('purchase_manager', 'company_admin', 'super_admin'):
            qs = qs.filter(requested_by=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = PurchaseRequest.Status.choices
        ctx['pending_count'] = PurchaseRequest.objects.filter(
            company=self.company(), status='submitted', is_deleted=False
        ).count()
        return ctx


class PurchaseRequestCreateView(CompanyMixin, View):
    template_name = 'purchase/requests/form.html'

    def get(self, request):
        from apps.inventory.models import Product, UnitOfMeasure
        from apps.company.models import Department
        c = self.company()
        return render(request, self.template_name, {
            'departments': Department.objects.filter(company=c, is_active=True, is_deleted=False),
            'products': Product.objects.filter(company=c, is_active=True, is_deleted=False).order_by('name'),
            'uoms': UnitOfMeasure.objects.filter(company=c, is_active=True, is_deleted=False),
            'priority_choices': PurchaseRequest.Priority.choices,
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            pr = PurchaseRequest(
                company=company,
                title=data['title'],
                department_id=data.get('department') or None,
                requested_by=request.user,
                required_by=data.get('required_by') or None,
                priority=data.get('priority', 'medium'),
                notes=data.get('notes', ''),
                status='draft',
            )
            pr.number = BaseService.generate_sequence_number('PR', PurchaseRequest, company.pk)
            pr.save()

            # Process lines
            products     = data.getlist('product[]')
            descriptions = data.getlist('description[]')
            quantities   = data.getlist('quantity[]')
            est_prices   = data.getlist('estimated_unit_price[]')

            total = 0
            for i, desc in enumerate(descriptions):
                if not desc.strip():
                    continue
                qty   = float(quantities[i] or 1)
                price = float(est_prices[i] or 0)
                line_total = qty * price
                PurchaseRequestLine.objects.create(
                    request=pr,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=qty,
                    estimated_unit_price=price,
                    estimated_total=line_total,
                )
                total += line_total

            pr.estimated_cost = total
            pr.save(update_fields=['estimated_cost'])

            messages.success(request, f'Purchase Request {pr.number} created.')
            return redirect('purchase:request_detail', pk=pr.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('purchase:requests')


class PurchaseRequestUpdateView(CompanyMixin, View):
    template_name = 'purchase/requests/form.html'

    def get(self, request, pk):
        from apps.inventory.models import Product, UnitOfMeasure
        from apps.company.models import Department
        c = self.company()
        pr = get_object_or_404(PurchaseRequest, pk=pk, company=c, is_deleted=False)
        
        if pr.status != 'draft':
            messages.error(request, 'Only draft purchase requests can be edited.')
            return redirect('purchase:request_detail', pk=pr.pk)
            
        return render(request, self.template_name, {
            'pr': pr,
            'departments': Department.objects.filter(company=c, is_active=True, is_deleted=False),
            'products': Product.objects.filter(company=c, is_active=True, is_deleted=False).order_by('name'),
            'uoms': UnitOfMeasure.objects.filter(company=c, is_active=True, is_deleted=False),
            'priority_choices': PurchaseRequest.Priority.choices,
        })

    def post(self, request, pk):
        c = self.company()
        pr = get_object_or_404(PurchaseRequest, pk=pk, company=c, is_deleted=False)
        
        if pr.status != 'draft':
            messages.error(request, 'Only draft purchase requests can be edited.')
            return redirect('purchase:request_detail', pk=pr.pk)
            
        data = request.POST
        try:
            pr.title = data['title']
            pr.department_id = data.get('department') or None
            pr.required_by = data.get('required_by') or None
            pr.priority = data.get('priority', 'medium')
            pr.notes = data.get('notes', '')
            pr.save()

            # Process lines (delete old and recreate)
            pr.lines.all().delete()
            products     = data.getlist('product[]')
            descriptions = data.getlist('description[]')
            quantities   = data.getlist('quantity[]')
            est_prices   = data.getlist('estimated_unit_price[]')

            total = 0
            for i, desc in enumerate(descriptions):
                if not desc.strip():
                    continue
                qty   = float(quantities[i] or 1)
                price = float(est_prices[i] or 0)
                line_total = qty * price
                PurchaseRequestLine.objects.create(
                    request=pr,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=qty,
                    estimated_unit_price=price,
                    estimated_total=line_total,
                )
                total += line_total

            pr.estimated_cost = total
            pr.save(update_fields=['estimated_cost'])

            messages.success(request, f'Purchase Request {pr.number} updated.')
            return redirect('purchase:request_detail', pk=pr.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('purchase:request_update', pk=pr.pk)


class PurchaseRequestDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        pr = get_object_or_404(PurchaseRequest, pk=pk, company=self.company(), is_deleted=False)
        if pr.status != 'draft':
            messages.error(request, 'Only draft purchase requests can be deleted.')
            return redirect('purchase:request_detail', pk=pr.pk)
            
        number = pr.number
        pr.is_deleted = True
        pr.save(update_fields=['is_deleted'])
        messages.success(request, f'Purchase Request {number} deleted.')
        return redirect('purchase:requests')


class PurchaseRequestDetailView(CompanyMixin, DetailView):
    template_name = 'purchase/requests/detail.html'
    context_object_name = 'pr'

    def get_object(self):
        return get_object_or_404(PurchaseRequest, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['lines'] = self.object.lines.all().select_related('product', 'unit')
        return ctx


class ApprovePurchaseRequestView(CompanyMixin, View):
    def post(self, request, pk):
        pr = get_object_or_404(PurchaseRequest, pk=pk, company=self.company(), is_deleted=False)
        action = request.POST.get('action')
        if action == 'submit' and pr.status == 'draft':
            pr.status = 'submitted'
            pr.save(update_fields=['status'])
            messages.success(request, f'{pr.number} submitted for approval.')
        elif action == 'approve':
            pr.status = 'approved'
            pr.approved_by = request.user
            pr.approved_at = timezone.now()
            pr.save(update_fields=['status', 'approved_by', 'approved_at'])
            messages.success(request, f'{pr.number} approved.')
        elif action == 'reject':
            pr.status = 'rejected'
            pr.rejection_reason = request.POST.get('rejection_reason', '')
            pr.save(update_fields=['status', 'rejection_reason'])
            messages.warning(request, f'{pr.number} rejected.')
        return redirect('purchase:request_detail', pk=pk)


# ════════════════════════ PURCHASE ORDERS ═════════════════════════════════════

class PurchaseOrderListView(CompanyMixin, ListView):
    template_name = 'purchase/orders/list.html'
    context_object_name = 'orders'
    paginate_by = 25

    def get_queryset(self):
        qs = PurchaseOrder.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('vendor').order_by('-order_date')
        status = self.request.GET.get('status', '')
        q = self.request.GET.get('q', '')
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(vendor__name__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = PurchaseOrder.Status.choices
        ctx['total_outstanding'] = PurchaseOrder.objects.filter(
            company=self.company(), status__in=['confirmed', 'partial'], is_deleted=False
        ).aggregate(t=Sum('balance_due'))['t'] or 0
        return ctx


class PurchaseOrderCreateView(CompanyMixin, View):
    template_name = 'purchase/orders/form.html'

    def get(self, request):
        from apps.inventory.models import Product, UnitOfMeasure, Warehouse
        from apps.company.models import Currency, Tax
        c = self.company()
        return render(request, self.template_name, {
            'vendors': Vendor.objects.filter(company=c, status='active', is_deleted=False).order_by('name'),
            'products': Product.objects.filter(company=c, is_active=True, is_deleted=False).order_by('name'),
            'warehouses': Warehouse.objects.filter(company=c, is_active=True, is_deleted=False),
            'currencies': Currency.objects.filter(is_active=True),
            'taxes': Tax.objects.filter(company=c, is_active=True),
            'uoms': UnitOfMeasure.objects.filter(company=c, is_active=True, is_deleted=False),
            'purchase_requests': PurchaseRequest.objects.filter(
                company=c, status='approved', is_deleted=False
            ).order_by('-created_at'),
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from decimal import Decimal
            po = PurchaseOrder(
                company=company,
                vendor_id=data['vendor'],
                purchase_request_id=data.get('purchase_request') or None,
                purchase_contract_id=data.get('purchase_contract') or None,
                warehouse_id=data.get('warehouse') or None,
                order_date=data['order_date'],
                expected_delivery=data.get('expected_delivery') or None,
                payment_terms=int(data.get('payment_terms', 30)),
                currency_id=data.get('currency') or None,
                notes=data.get('notes', ''),
                terms_conditions=data.get('terms_conditions', ''),
                status='draft',
            )
            po.number = BaseService.generate_sequence_number('PO', PurchaseOrder, company.pk)
            po.save()

            products     = data.getlist('product[]')
            descriptions = data.getlist('description[]')
            quantities   = data.getlist('quantity[]')
            prices       = data.getlist('unit_price[]')
            discounts    = data.getlist('discount_percent[]')
            taxes        = data.getlist('tax[]')

            subtotal = Decimal('0')
            tax_total = Decimal('0')

            for i, desc in enumerate(descriptions):
                if not desc.strip():
                    continue
                qty  = Decimal(quantities[i] or '1')
                price = Decimal(prices[i] or '0')
                disc  = Decimal(discounts[i] or '0')
                sub   = qty * price
                disc_amt = sub * disc / 100
                taxable  = sub - disc_amt
                tax_amt  = Decimal('0')
                if taxes[i]:
                    from apps.company.models import Tax
                    try:
                        t = Tax.objects.get(pk=taxes[i])
                        tax_amt = t.compute(taxable)
                    except Exception:
                        pass
                total = taxable + tax_amt
                PurchaseOrderLine.objects.create(
                    purchase_order=po,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=qty,
                    unit_price=price,
                    discount_percent=disc,
                    tax_id=taxes[i] if taxes[i] else None,
                    subtotal=sub,
                    tax_amount=tax_amt,
                    total=total,
                )
                
                # Drawdown from contract if applicable
                if po.purchase_contract_id and products[i]:
                    try:
                        contract_line = po.purchase_contract.lines.get(product_id=products[i])
                        contract_line.quantity_ordered += qty
                        contract_line.save(update_fields=['quantity_ordered'])
                    except Exception:
                        pass
                
                subtotal += sub
                tax_total += tax_amt

            po.subtotal = subtotal
            po.tax_amount = tax_total
            po.total = subtotal + tax_total
            po.balance_due = po.total
            po.save(update_fields=['subtotal', 'tax_amount', 'total', 'balance_due'])

            messages.success(request, f'Purchase Order {po.number} created.')
            return redirect('purchase:order_detail', pk=po.pk)
        except Exception as e:
            messages.error(request, f'Error creating PO: {e}')
            return redirect('purchase:orders')


class PurchaseOrderUpdateView(CompanyMixin, View):
    template_name = 'purchase/orders/form.html'

    def get(self, request, pk):
        from apps.inventory.models import Product, UnitOfMeasure, Warehouse
        from apps.company.models import Currency, Tax
        c = self.company()
        po = get_object_or_404(PurchaseOrder, pk=pk, company=c, is_deleted=False)
        
        if po.status != 'draft':
            messages.error(request, 'Only draft purchase orders can be edited.')
            return redirect('purchase:order_detail', pk=po.pk)
            
        return render(request, self.template_name, {
            'po': po,
            'vendors': Vendor.objects.filter(company=c, status='active', is_deleted=False).order_by('name'),
            'products': Product.objects.filter(company=c, is_active=True, is_deleted=False).order_by('name'),
            'warehouses': Warehouse.objects.filter(company=c, is_active=True, is_deleted=False),
            'currencies': Currency.objects.filter(is_active=True),
            'taxes': Tax.objects.filter(company=c, is_active=True),
            'uoms': UnitOfMeasure.objects.filter(company=c, is_active=True, is_deleted=False),
            'purchase_requests': PurchaseRequest.objects.filter(
                company=c, status='approved', is_deleted=False
            ).order_by('-created_at'),
        })

    def post(self, request, pk):
        c = self.company()
        po = get_object_or_404(PurchaseOrder, pk=pk, company=c, is_deleted=False)
        
        if po.status != 'draft':
            messages.error(request, 'Only draft purchase orders can be edited.')
            return redirect('purchase:order_detail', pk=po.pk)
            
        data = request.POST
        try:
            from decimal import Decimal
            po.vendor_id = data['vendor']
            po.purchase_request_id = data.get('purchase_request') or None
            po.warehouse_id = data.get('warehouse') or None
            po.order_date = data['order_date']
            po.expected_delivery = data.get('expected_delivery') or None
            po.payment_terms = int(data.get('payment_terms', 30))
            po.currency_id = data.get('currency') or None
            po.notes = data.get('notes', '')
            po.terms_conditions = data.get('terms_conditions', '')
            po.save()

            po.lines.all().delete()
            products     = data.getlist('product[]')
            descriptions = data.getlist('description[]')
            quantities   = data.getlist('quantity[]')
            prices       = data.getlist('unit_price[]')
            discounts    = data.getlist('discount_percent[]')
            taxes        = data.getlist('tax[]')

            subtotal = Decimal('0')
            tax_total = Decimal('0')

            for i, desc in enumerate(descriptions):
                if not desc.strip():
                    continue
                qty  = Decimal(quantities[i] or '1')
                price = Decimal(prices[i] or '0')
                disc  = Decimal(discounts[i] or '0')
                sub   = qty * price
                disc_amt = sub * disc / 100
                taxable  = sub - disc_amt
                tax_amt  = Decimal('0')
                if taxes[i]:
                    from apps.company.models import Tax
                    try:
                        t = Tax.objects.get(pk=taxes[i])
                        tax_amt = t.compute(taxable)
                    except Exception:
                        pass
                total = taxable + tax_amt
                PurchaseOrderLine.objects.create(
                    purchase_order=po,
                    product_id=products[i] if products[i] else None,
                    description=desc,
                    quantity=qty,
                    unit_price=price,
                    discount_percent=disc,
                    tax_id=taxes[i] if taxes[i] else None,
                    subtotal=sub,
                    tax_amount=tax_amt,
                    total=total,
                )
                subtotal += sub
                tax_total += tax_amt

            po.subtotal = subtotal
            po.tax_amount = tax_total
            po.total = subtotal + tax_total
            po.balance_due = po.total
            po.save(update_fields=['subtotal', 'tax_amount', 'total', 'balance_due'])

            messages.success(request, f'Purchase Order {po.number} updated.')
            return redirect('purchase:order_detail', pk=po.pk)
        except Exception as e:
            messages.error(request, f'Error updating PO: {e}')
            return redirect('purchase:order_update', pk=po.pk)


class PurchaseOrderDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        po = get_object_or_404(PurchaseOrder, pk=pk, company=self.company(), is_deleted=False)
        if po.status != 'draft':
            messages.error(request, 'Only draft purchase orders can be deleted.')
            return redirect('purchase:order_detail', pk=po.pk)
            
        number = po.number
        po.is_deleted = True
        po.save(update_fields=['is_deleted'])
        messages.success(request, f'Purchase Order {number} deleted.')
        return redirect('purchase:orders')


class PurchaseOrderDetailView(CompanyMixin, DetailView):
    template_name = 'purchase/orders/detail.html'
    context_object_name = 'order'

    def get_object(self):
        return get_object_or_404(PurchaseOrder, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['lines'] = self.object.lines.all().select_related('product', 'tax', 'unit')
        ctx['receipts'] = self.object.receipts.filter(is_deleted=False)
        return ctx


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = 'purchase'

urlpatterns = [
    path('vendors/', VendorListView.as_view(), name='vendors'),
    path('vendors/create/', VendorCreateView.as_view(), name='vendor_create'),
    path('vendors/<uuid:pk>/', VendorDetailView.as_view(), name='vendor_detail'),
    path('requests/', PurchaseRequestListView.as_view(), name='requests'),
    path('requests/create/', PurchaseRequestCreateView.as_view(), name='request_create'),
    path('requests/<uuid:pk>/', PurchaseRequestDetailView.as_view(), name='request_detail'),
    path('requests/<uuid:pk>/action/', ApprovePurchaseRequestView.as_view(), name='request_action'),
    path('orders/', PurchaseOrderListView.as_view(), name='orders'),
    path('orders/create/', PurchaseOrderCreateView.as_view(), name='order_create'),
    path('orders/<uuid:pk>/', PurchaseOrderDetailView.as_view(), name='order_detail'),
]


# ========================================== BILL VIEWS ==========================================

from .models import Bill, BillLine, Payment
from django.utils import timezone
from core.services import BaseService

class CreateBillFromPOView(CompanyMixin, View):
    def post(self, request, pk):
        po = get_object_or_404(PurchaseOrder, pk=pk, company=self.company())
        if po.status not in [PurchaseOrder.Status.CONFIRMED, PurchaseOrder.Status.PARTIAL, PurchaseOrder.Status.RECEIVED]:
            messages.error(request, 'Cannot create bill for this Purchase Order status.')
            return redirect('purchase:po_detail', pk=pk)

        bill = Bill.objects.create(
            company=self.company(),
            vendor=po.vendor,
            purchase_order=po,
            bill_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=po.payment_terms),
            status=Bill.Status.DRAFT,
            currency=po.currency
        )
        bill.number = BaseService.generate_sequence_number('BILL', Bill, self.company().pk)
        bill.save(update_fields=['number'])

        for line in po.lines.all():
            qty_to_bill = float(line.qty_received) - float(line.qty_invoiced)
            if qty_to_bill <= 0:
                continue
            BillLine.objects.create(
                bill=bill,
                product=line.product,
                description=line.description,
                quantity=qty_to_bill,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax=line.tax
            )
            line.qty_invoiced += qty_to_bill
            line.save(update_fields=['qty_invoiced'])
        
        bill.calculate_totals()
        
        messages.success(request, f'Draft Bill {bill.number} created from Purchase Order.')
        return redirect('purchase:bill_detail', pk=bill.pk)


class BillUpdateView(CompanyMixin, UpdateView):
    model = Bill
    fields = ['bill_date', 'due_date', 'terms_conditions', 'notes']
    template_name = 'purchase/bills/form.html'
    
    def get_success_url(self):
        return reverse_lazy('purchase:bill_detail', kwargs={'pk': self.object.pk})
        
    def get_queryset(self):
        return super().get_queryset().filter(company=self.company(), is_deleted=False)

    def form_valid(self, form):
        messages.success(self.request, 'Bill updated successfully.')
        return super().form_valid(form)


class BillDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        bill = get_object_or_404(Bill, pk=pk, company=self.company(), is_deleted=False)
        if bill.status != Bill.Status.DRAFT:
            messages.error(request, 'Only draft bills can be deleted.')
            return redirect('purchase:bill_detail', pk=pk)
            
        number = bill.number
        bill.is_deleted = True
        bill.save(update_fields=['is_deleted'])
        messages.success(request, f'Bill {number} deleted.')
        return redirect('purchase:bills')


class BillListView(CompanyMixin, ListView):
    model = Bill
    template_name = 'purchase/bills/list.html'
    context_object_name = 'bills'

    def get_queryset(self):
        qs = super().get_queryset().filter(company=self.company())
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-created_at')


class BillDetailView(CompanyMixin, DetailView):
    model = Bill
    template_name = 'purchase/bills/detail.html'
    context_object_name = 'bill'

    def get_queryset(self):
        return super().get_queryset().filter(company=self.company())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['lines'] = self.object.lines.all()
        ctx['payments'] = self.object.payments.all()
        return ctx


class RecordVendorPaymentView(CompanyMixin, View):
    def post(self, request, pk):
        bill = get_object_or_404(Bill, pk=pk, company=self.company())
        amount = request.POST.get('amount')
        method = request.POST.get('method', 'bank_transfer')
        reference = request.POST.get('reference', '')
        
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (ValueError, TypeError):
            messages.error(request, 'Invalid payment amount.')
            return redirect('purchase:bill_detail', pk=pk)

        payment = Payment.objects.create(
            company=self.company(),
            bill=bill,
            vendor=bill.vendor,
            amount=amount,
            payment_date=timezone.now().date(),
            method=method,
            reference=reference,
            status=Payment.Status.COMPLETED,
            currency=bill.currency
        )
        payment.number = BaseService.generate_sequence_number('VPAY', Payment, self.company().pk)
        payment.save(update_fields=['number'])

        messages.success(request, f'Payment of {payment.currency.symbol} {payment.amount} recorded successfully.')
        return redirect('purchase:bill_detail', pk=pk)



# ════════════════════════ GOODS RECEIPTS ═════════════════════════════════════

class GoodsReceiptListView(CompanyMixin, ListView):
    model = GoodsReceipt
    template_name = 'purchase/receipts/list.html'
    context_object_name = 'receipts'
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().filter(company=self.company())
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-created_at')

class GoodsReceiptUpdateView(CompanyMixin, UpdateView):
    model = GoodsReceipt
    fields = ['receipt_date', 'quality_check', 'qc_notes', 'notes']
    template_name = 'purchase/receipts/form_update.html'
    
    def get_success_url(self):
        return reverse_lazy('purchase:receipt_detail', kwargs={'pk': self.object.pk})
        
    def get_queryset(self):
        return super().get_queryset().filter(company=self.company(), is_deleted=False)

    def form_valid(self, form):
        messages.success(self.request, 'Goods Receipt updated successfully.')
        return super().form_valid(form)


class GoodsReceiptDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        receipt = get_object_or_404(GoodsReceipt, pk=pk, company=self.company(), is_deleted=False)
        
        if receipt.status == GoodsReceipt.Status.COMPLETED:
            # Reverse stock movements
            for line in receipt.lines.all():
                if line.po_line:
                    line.po_line.qty_received -= line.quantity_accepted
                    line.po_line.save(update_fields=['qty_received'])
                    
                from apps.inventory.models import StockRecord, StockMovement
                if line.po_line.product and receipt.warehouse:
                    stock_record, _ = StockRecord.objects.get_or_create(
                        company=self.company(),
                        product=line.po_line.product,
                        warehouse=receipt.warehouse,
                        defaults={'quantity_on_hand': 0}
                    )
                    stock_record.quantity_on_hand -= line.quantity_accepted
                    stock_record.save(update_fields=['quantity_on_hand'])
                    
                    StockMovement.objects.create(
                        company=self.company(),
                        product=line.po_line.product,
                        warehouse=receipt.warehouse,
                        movement_type=StockMovement.MovementType.ADJUSTMENT,
                        quantity=-line.quantity_accepted,
                        movement_date=timezone.now().date(),
                        reference_type='Receipt Cancelled',
                        reference_id=str(receipt.pk),
                        stock_after=stock_record.quantity_on_hand
                    )
                    
        receipt.is_deleted = True
        receipt.status = GoodsReceipt.Status.CANCELLED
        receipt.save(update_fields=['is_deleted', 'status'])
        messages.success(request, f'Receipt {receipt.number} deleted and stock reversed.')
        return redirect('purchase:receipts')

class GoodsReceiptDetailView(CompanyMixin, DetailView):
    model = GoodsReceipt
    template_name = 'purchase/receipts/detail.html'
    context_object_name = 'receipt'

    def get_queryset(self):
        return super().get_queryset().filter(company=self.company())

class GoodsReceiptCreateView(CompanyMixin, View):
    def get(self, request, pk):
        po = get_object_or_404(PurchaseOrder, pk=pk, company=self.company())
        if po.status not in [PurchaseOrder.Status.CONFIRMED, PurchaseOrder.Status.PARTIAL]:
            messages.error(request, 'Cannot receive goods for this PO status.')
            return redirect('purchase:order_detail', pk=pk)
        return render(request, 'purchase/receipts/form.html', {'po': po})

    def post(self, request, pk):
        po = get_object_or_404(PurchaseOrder, pk=pk, company=self.company())
        if po.status not in [PurchaseOrder.Status.CONFIRMED, PurchaseOrder.Status.PARTIAL]:
            messages.error(request, 'Cannot receive goods for this PO.')
            return redirect('purchase:order_detail', pk=pk)

        receipt = GoodsReceipt.objects.create(
            company=self.company(),
            purchase_order=po,
            warehouse_id=request.POST.get('warehouse'),
            receipt_date=timezone.now().date(),
            received_by=request.user,
            status=GoodsReceipt.Status.COMPLETED,
            notes=request.POST.get('notes', '')
        )
        receipt.number = BaseService.generate_sequence_number('GRN', GoodsReceipt, self.company().pk)
        receipt.save(update_fields=['number'])

        all_received = True
        for line in po.lines.all():
            qty_input = request.POST.get(f'qty_{line.pk}')
            if not qty_input:
                continue
            from decimal import Decimal
            qty = Decimal(qty_input)
            if qty > 0:
                GoodsReceiptLine.objects.create(
                    goods_receipt=receipt,
                    po_line=line,
                    quantity_received=qty,
                    quantity_accepted=qty,
                    batch_number=request.POST.get(f'batch_{line.pk}', '')
                )
                line.qty_received += qty
                line.save(update_fields=['qty_received'])
                
                # Update stock level
                from apps.inventory.models import StockRecord, StockMovement
                if line.product and receipt.warehouse:
                    stock_record, _ = StockRecord.objects.get_or_create(
                        company=self.company(),
                        product=line.product,
                        warehouse=receipt.warehouse,
                        defaults={'quantity_on_hand': 0}
                    )
                    stock_record.quantity_on_hand += qty
                    stock_record.save(update_fields=['quantity_on_hand'])
                    
                    StockMovement.objects.create(
                        company=self.company(),
                        product=line.product,
                        warehouse=receipt.warehouse,
                        movement_type=StockMovement.MovementType.RECEIPT,
                        quantity=qty,
                        movement_date=timezone.now().date(),
                        reference_type='GoodsReceipt',
                        reference_id=str(receipt.pk),
                        stock_after=stock_record.quantity_on_hand
                    )
            
            if line.qty_received < line.quantity:
                all_received = False
        
        po.status = PurchaseOrder.Status.RECEIVED if all_received else PurchaseOrder.Status.PARTIAL
        po.save(update_fields=['status'])

        messages.success(request, f'Goods Receipt {receipt.number} created.')
        return redirect('purchase:receipt_detail', pk=receipt.pk)

# ════════════════════════ ENTERPRISE PURCHASE VIEWS ═══════════════════════════

from .models import RequestForQuotation, RFQLine, VendorBid, VendorBidLine

class RFQListView(CompanyMixin, ListView):
    template_name = 'purchase/rfqs/list.html'
    context_object_name = 'rfqs'
    
    def get_queryset(self):
        return RequestForQuotation.objects.filter(company=self.company()).select_related('created_by')

class RFQDetailView(CompanyMixin, DetailView):
    template_name = 'purchase/rfqs/detail.html'
    context_object_name = 'rfq'
    
    def get_queryset(self):
        return RequestForQuotation.objects.filter(company=self.company()).prefetch_related('lines', 'bids')


class RFQCreateView(CompanyMixin, View):
    def get(self, request):
        from apps.inventory.models import Product
        return render(request, 'purchase/rfqs/form.html', {
            'products': Product.objects.filter(company=self.company(), is_active=True, is_deleted=False)
        })

    def post(self, request):
        try:
            rfq = RequestForQuotation(
                company=self.company(),
                title=request.POST.get('title'),
                deadline=request.POST.get('deadline'),
                delivery_date=request.POST.get('delivery_date') or None,
                created_by=request.user,
                status=RequestForQuotation.Status.DRAFT
            )
            rfq.number = BaseService.generate_sequence_number('RFQ', RequestForQuotation, self.company().pk)
            rfq.save()
            
            products = request.POST.getlist('product[]')
            quantities = request.POST.getlist('quantity[]')
            descriptions = request.POST.getlist('description[]')
            
            for i, prod_id in enumerate(products):
                if prod_id or descriptions[i]:
                    RFQLine.objects.create(
                        rfq=rfq,
                        product_id=prod_id if prod_id else None,
                        quantity=quantities[i] or 1,
                        description=descriptions[i]
                    )
            messages.success(request, f'RFQ {rfq.number} created.')
            return redirect('purchase:rfq_detail', pk=rfq.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('purchase:rfqs')


class RFQUpdateView(CompanyMixin, View):
    def get(self, request, pk):
        from apps.inventory.models import Product
        rfq = get_object_or_404(RequestForQuotation, pk=pk, company=self.company())
        if rfq.status != 'draft':
            messages.error(request, 'Only draft RFQs can be edited.')
            return redirect('purchase:rfq_detail', pk=rfq.pk)
            
        return render(request, 'purchase/rfqs/form.html', {
            'rfq': rfq,
            'products': Product.objects.filter(company=self.company(), is_active=True, is_deleted=False)
        })

    def post(self, request, pk):
        rfq = get_object_or_404(RequestForQuotation, pk=pk, company=self.company())
        if rfq.status != 'draft':
            messages.error(request, 'Only draft RFQs can be edited.')
            return redirect('purchase:rfq_detail', pk=rfq.pk)
            
        try:
            rfq.title = request.POST.get('title')
            rfq.deadline = request.POST.get('deadline')
            rfq.delivery_date = request.POST.get('delivery_date') or None
            rfq.save()
            
            rfq.lines.all().delete()
            products = request.POST.getlist('product[]')
            quantities = request.POST.getlist('quantity[]')
            descriptions = request.POST.getlist('description[]')
            
            for i, prod_id in enumerate(products):
                if prod_id or descriptions[i]:
                    RFQLine.objects.create(
                        rfq=rfq,
                        product_id=prod_id if prod_id else None,
                        quantity=quantities[i] or 1,
                        description=descriptions[i]
                    )
            messages.success(request, f'RFQ {rfq.number} updated.')
            return redirect('purchase:rfq_detail', pk=rfq.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('purchase:rfq_detail', pk=rfq.pk)


class RFQDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        rfq = get_object_or_404(RequestForQuotation, pk=pk, company=self.company())
        if rfq.status != 'draft':
            messages.error(request, 'Only draft RFQs can be deleted.')
            return redirect('purchase:rfq_detail', pk=rfq.pk)
        rfq.status = RequestForQuotation.Status.CANCELLED
        rfq.save(update_fields=['status'])
        messages.success(request, f'RFQ {rfq.number} deleted.')
        return redirect('purchase:rfqs')


class VendorBidListView(CompanyMixin, ListView):
    template_name = 'purchase/bids/list.html'
    context_object_name = 'bids'
    
    def get_queryset(self):
        return VendorBid.objects.filter(company=self.company()).select_related('rfq', 'vendor')

class VendorBidDetailView(CompanyMixin, DetailView):
    template_name = 'purchase/bids/detail.html'
    context_object_name = 'bid'
    
    def get_queryset(self):
        return VendorBid.objects.filter(company=self.company()).select_related('rfq', 'vendor').prefetch_related('lines')


class VendorBidCreateView(CompanyMixin, View):
    def get(self, request):
        rfq_id = request.GET.get('rfq')
        rfq = get_object_or_404(RequestForQuotation, pk=rfq_id, company=self.company()) if rfq_id else None
        
        return render(request, 'purchase/bids/form.html', {
            'rfq': rfq,
            'vendors': Vendor.objects.filter(company=self.company(), status='active', is_deleted=False)
        })

    def post(self, request):
        try:
            rfq = get_object_or_404(RequestForQuotation, pk=request.POST.get('rfq'), company=self.company())
            vendor = get_object_or_404(Vendor, pk=request.POST.get('vendor'), company=self.company())
            
            bid, created = VendorBid.objects.get_or_create(
                company=self.company(),
                rfq=rfq,
                vendor=vendor,
                defaults={
                    'valid_until': request.POST.get('valid_until') or None,
                    'notes': request.POST.get('notes', ''),
                    'status': VendorBid.Status.PENDING
                }
            )
            
            if not created:
                bid.lines.all().delete()
                bid.valid_until = request.POST.get('valid_until') or None
                bid.notes = request.POST.get('notes', '')
                bid.status = VendorBid.Status.PENDING
                bid.save()

            from decimal import Decimal
            total = Decimal('0')
            
            prices = request.POST.getlist('price[]')
            for i, line in enumerate(rfq.lines.all()):
                price = Decimal(prices[i] or '0')
                VendorBidLine.objects.create(
                    bid=bid,
                    rfq_line=line,
                    unit_price=price,
                    subtotal=price * line.quantity
                )
                total += price * line.quantity
                
            bid.total_amount = total
            bid.save(update_fields=['total_amount'])
            
            messages.success(request, f'Bid from {vendor.name} recorded.')
            return redirect('purchase:bid_detail', pk=bid.pk)
        except Exception as e:
            messages.error(request, f'Error recording bid: {e}')
            return redirect('purchase:bids')


class VendorBidActionView(CompanyMixin, View):
    def post(self, request, pk):
        bid = get_object_or_404(VendorBid, pk=pk, company=self.company())
        action = request.POST.get('action')
        
        if action == 'accept':
            bid.status = VendorBid.Status.ACCEPTED
            bid.save(update_fields=['status'])
            
            # Auto-generate PO
            po = PurchaseOrder.objects.create(
                company=self.company(),
                vendor=bid.vendor,
                order_date=timezone.now().date(),
                status=PurchaseOrder.Status.DRAFT,
                notes=f"Generated from RFQ {bid.rfq.number}"
            )
            po.number = BaseService.generate_sequence_number('PO', PurchaseOrder, self.company().pk)
            po.save(update_fields=['number'])
            
            from decimal import Decimal
            total = Decimal('0')
            for b_line in bid.lines.all():
                PurchaseOrderLine.objects.create(
                    purchase_order=po,
                    product=b_line.rfq_line.product,
                    description=b_line.rfq_line.description,
                    quantity=b_line.rfq_line.quantity,
                    unit_price=b_line.unit_price,
                    subtotal=b_line.subtotal,
                    total=b_line.subtotal
                )
                total += b_line.subtotal
            
            po.subtotal = total
            po.total = total
            po.balance_due = total
            po.save(update_fields=['subtotal', 'total', 'balance_due'])
            
            messages.success(request, f'Bid accepted and Draft PO {po.number} generated.')
            return redirect('purchase:order_detail', pk=po.pk)
            
        elif action == 'reject':
            bid.status = VendorBid.Status.REJECTED
            bid.save(update_fields=['status'])
            messages.warning(request, 'Bid rejected.')
            
        return redirect('purchase:bid_detail', pk=bid.pk)

# ════════════════════════ DASHBOARD & VENDOR EVAL ════════════════════════════

class PurchaseDashboardView(CompanyMixin, TemplateView):
    template_name = 'purchase/dashboard.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.db.models import Sum, Avg
        from decimal import Decimal
        c = self.company()
        
        ctx['total_expenses'] = Bill.objects.filter(company=c, status__in=['paid', 'partial']).aggregate(t=Sum('amount_paid'))['t'] or 0
        ctx['outstanding_payables'] = Bill.objects.filter(company=c, status__in=['open', 'partial', 'overdue']).aggregate(t=Sum('balance_due'))['t'] or 0
        ctx['pending_pos_count'] = PurchaseOrder.objects.filter(company=c, status__in=['confirmed', 'partial']).count()
        
        # Purchase Forecast (expected cash outflow from CONFIRMED but unpaid POs)
        ctx['purchase_forecast'] = PurchaseOrder.objects.filter(
            company=c, status__in=['confirmed', 'partial']
        ).aggregate(t=Sum('balance_due'))['t'] or 0

        # Supplier Performance
        perf = Vendor.objects.filter(company=c, status='active').aggregate(
            avg_rating=Avg('rating'),
            avg_on_time=Avg('on_time_delivery_pct'),
            avg_defect=Avg('defect_rate_pct')
        )
        ctx['supplier_perf'] = perf
        
        # Cost Analysis (Sum of all POs this month vs last month, simplified for now to total PO value)
        ctx['cost_analysis_total'] = PurchaseOrder.objects.filter(company=c, is_deleted=False).aggregate(t=Sum('total'))['t'] or 0

        ctx['recent_pos'] = PurchaseOrder.objects.filter(company=c).select_related('vendor').order_by('-created_at')[:5]
        
        return ctx

class VendorEvaluateView(CompanyMixin, View):
    def get(self, request, pk):
        vendor = get_object_or_404(Vendor, pk=pk, company=self.company())
        
        # Simple evaluation logic: calculate metrics from POs
        pos = vendor.purchase_orders.all()
        total_pos = pos.count()
        delivered_on_time = 0
        for po in pos.filter(status='received'):
            if po.expected_delivery and po.actual_delivery and po.actual_delivery <= po.expected_delivery:
                delivered_on_time += 1
                
        if total_pos > 0:
            vendor.on_time_delivery_pct = (delivered_on_time / total_pos) * 100
        else:
            vendor.on_time_delivery_pct = 100
            
        vendor.save(update_fields=['on_time_delivery_pct'])
        
        return render(request, 'purchase/vendor_evaluate.html', {
            'vendor': vendor
        })
        
    def post(self, request, pk):
        vendor = get_object_or_404(Vendor, pk=pk, company=self.company())
        rating = int(request.POST.get('rating', 3))
        vendor.rating = rating
        vendor.save(update_fields=['rating'])
        messages.success(request, f'Vendor {vendor.name} rating updated.')
        return redirect('purchase:vendor_detail', pk=vendor.pk)
