"""
Sales REST API
Quotations, Sales Orders, Invoices, Payments
"""

from rest_framework import serializers, viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from ..models import Quotation, QuotationLine, SalesOrder, SalesOrderLine, Invoice, InvoiceLine, Payment


# ─── Serializers ──────────────────────────────────────────────────────────────

class QuotationLineSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField()

    class Meta:
        model = QuotationLine
        fields = ['id', 'product', 'product_name', 'description', 'quantity',
                  'unit_price', 'discount_percent', 'tax', 'subtotal',
                  'tax_amount', 'discount_amount', 'total', 'sort_order']
        read_only_fields = ['subtotal', 'tax_amount', 'discount_amount', 'total']

    def get_product_name(self, obj):
        return obj.product.name if obj.product else None


class QuotationSerializer(serializers.ModelSerializer):
    lines = QuotationLineSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = Quotation
        fields = ['id', 'number', 'customer', 'customer_name', 'status', 'status_display',
                  'validity_date', 'delivery_date', 'payment_terms', 'currency',
                  'subtotal', 'tax_amount', 'discount_amount', 'total',
                  'notes', 'terms_conditions', 'sales_rep', 'lines', 'created_at']
        read_only_fields = ['number', 'subtotal', 'tax_amount', 'discount_amount', 'total', 'created_at']

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None

    def get_status_display(self, obj):
        return obj.get_status_display()


class SalesOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrderLine
        fields = ['id', 'product', 'description', 'quantity', 'unit_price',
                  'discount_percent', 'tax', 'subtotal', 'tax_amount', 'total',
                  'qty_delivered', 'qty_invoiced']


class SalesOrderSerializer(serializers.ModelSerializer):
    lines = SalesOrderLineSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrder
        fields = ['id', 'number', 'customer', 'customer_name', 'status',
                  'order_date', 'delivery_date', 'payment_terms', 'currency',
                  'subtotal', 'tax_amount', 'discount_amount', 'total',
                  'shipping_address', 'notes', 'lines', 'created_at']
        read_only_fields = ['number', 'total', 'created_at']

    def get_customer_name(self, obj):
        return obj.customer.name


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ['id', 'product', 'description', 'quantity', 'unit_price',
                  'discount_percent', 'tax', 'subtotal', 'tax_amount', 'total']


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ['id', 'number', 'customer', 'customer_name', 'status',
                  'invoice_date', 'due_date', 'payment_terms', 'currency',
                  'subtotal', 'tax_amount', 'discount_amount', 'total',
                  'amount_paid', 'balance_due', 'notes', 'lines',
                  'is_overdue', 'created_at']
        read_only_fields = ['number', 'amount_paid', 'balance_due', 'created_at']

    def get_customer_name(self, obj):
        return obj.customer.name

    def get_is_overdue(self, obj):
        from datetime import date
        return obj.status in ('sent', 'partial') and obj.due_date < timezone.localdate()


class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'number', 'invoice', 'invoice_number', 'customer',
                  'amount', 'currency', 'payment_date', 'method', 'status',
                  'reference', 'notes', 'created_at']
        read_only_fields = ['number', 'created_at']

    def get_invoice_number(self, obj):
        return obj.invoice.number


# ─── ViewSets ─────────────────────────────────────────────────────────────────

class QuotationViewSet(viewsets.ModelViewSet):
    serializer_class = QuotationSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'customer', 'sales_rep']
    search_fields = ['number', 'customer__name']
    ordering_fields = ['created_at', 'total', 'validity_date']
    ordering = ['-created_at']

    def get_queryset(self):
        return Quotation.objects.filter(
            company=self.request.user.primary_company, is_deleted=False
        ).select_related('customer', 'currency', 'sales_rep')

    def perform_create(self, serializer):
        from core.services import BaseService
        company = self.request.user.primary_company
        number = BaseService.generate_sequence_number('QUO', Quotation, company.pk)
        serializer.save(company=company, number=number, created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        quot = self.get_object()
        if quot.status != Quotation.Status.DRAFT:
            return Response({'error': 'Only draft quotations can be sent.'}, status=400)
        quot.status = Quotation.Status.SENT
        quot.save(update_fields=['status'])
        return Response(QuotationSerializer(quot).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        quot = self.get_object()
        quot.status = Quotation.Status.APPROVED
        quot.approved_by = request.user
        quot.save(update_fields=['status', 'approved_by'])
        return Response(QuotationSerializer(quot).data)

    @action(detail=True, methods=['post'])
    def convert_to_order(self, request, pk=None):
        quot = self.get_object()
        if quot.status not in (Quotation.Status.SENT, Quotation.Status.APPROVED):
            return Response({'error': 'Quotation must be sent or approved.'}, status=400)
        # Delegate to service
        from apps.sales.services import SalesService
        so = SalesService(user=request.user, company=request.user.primary_company).convert_quote_to_order(quot)
        return Response({'order_id': str(so.pk), 'order_number': so.number}, status=201)


class SalesOrderViewSet(viewsets.ModelViewSet):
    serializer_class = SalesOrderSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'customer']
    search_fields = ['number', 'customer__name']
    ordering = ['-order_date']

    def get_queryset(self):
        return SalesOrder.objects.filter(
            company=self.request.user.primary_company, is_deleted=False
        ).select_related('customer', 'currency')

    def perform_create(self, serializer):
        from core.services import BaseService
        company = self.request.user.primary_company
        number = BaseService.generate_sequence_number('SO', SalesOrder, company.pk)
        serializer.save(company=company, number=number, created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        order = self.get_object()
        from apps.sales.services import SalesOrderService
        try:
            order = SalesOrderService(user=request.user, company=request.user.primary_company).confirm_order(order)
            return Response(SalesOrderSerializer(order).data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

    @action(detail=True, methods=['post'])
    def create_invoice(self, request, pk=None):
        order = self.get_object()
        from apps.sales.services import SalesService
        inv = SalesService(user=request.user, company=request.user.primary_company).create_invoice_from_order(order)
        return Response({'invoice_id': str(inv.pk), 'invoice_number': inv.number}, status=201)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'customer']
    search_fields = ['number', 'customer__name']
    ordering = ['-invoice_date']

    def get_queryset(self):
        return Invoice.objects.filter(
            company=self.request.user.primary_company, is_deleted=False
        ).select_related('customer', 'currency')

    def perform_create(self, serializer):
        from core.services import BaseService
        company = self.request.user.primary_company
        number = BaseService.generate_sequence_number('INV', Invoice, company.pk)
        serializer.save(company=company, number=number, created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def send_invoice(self, request, pk=None):
        invoice = self.get_object()
        from django.utils import timezone
        invoice.status = Invoice.Status.SENT
        invoice.sent_at = timezone.now()
        invoice.save(update_fields=['status', 'sent_at'])
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=['post'])
    def record_payment(self, request, pk=None):
        invoice = self.get_object()
        serializer = PaymentSerializer(data={**request.data, 'invoice': invoice.pk, 'customer': invoice.customer_id})
        serializer.is_valid(raise_exception=True)
        from core.services import BaseService
        company = self.request.user.primary_company
        number = BaseService.generate_sequence_number('PAY', Payment, company.pk)
        payment = serializer.save(company=company, number=number, created_by=request.user)
        return Response(PaymentSerializer(payment).data, status=201)

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        invoice = self.get_object()
        # Return PDF URL for frontend to open
        return Response({'pdf_url': f'/sales/invoices/{invoice.pk}/pdf/'})


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'method', 'customer']
    search_fields = ['number', 'reference']
    ordering = ['-payment_date']

    def get_queryset(self):
        return Payment.objects.filter(
            company=self.request.user.primary_company, is_deleted=False
        ).select_related('invoice', 'customer', 'currency')
