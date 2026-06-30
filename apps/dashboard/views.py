"""
Dashboard API Views
CEO, HR, Sales, Finance dashboards — all KPIs and chart data
"""

from datetime import date, timedelta
from django.db.models import Sum, Count, Avg, Q, F
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page


def get_period_dates(period='month'):
    today = date.today()
    if period == 'today':
        return today, today
    if period == 'week':
        start = today - timedelta(days=today.weekday())
        return start, today
    if period == 'month':
        return today.replace(day=1), today
    if period == 'quarter':
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=q_start_month, day=1), today
    if period == 'year':
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


# ─── CEO Dashboard API ─────────────────────────────────────────────────────

class CEODashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        if not company:
            return Response({'error': 'No company assigned'}, status=400)

        period = request.query_params.get('period', 'month')
        start_date, end_date = get_period_dates(period)

        return Response({
            'kpis': self._get_kpis(company, start_date, end_date),
            'charts': self._get_charts(company, start_date, end_date),
            'meta': {'period': period, 'start': start_date, 'end': end_date},
        })

    def _get_kpis(self, company, start, end):
        from apps.sales.models import Invoice, Payment
        from apps.hrms.models import Employee
        from apps.accounting.models import JournalEntry, JournalItem

        # Revenue
        revenue = Invoice.objects.filter(
            company=company, invoice_date__range=(start, end),
            status__in=['sent', 'partial', 'paid']
        ).aggregate(total=Sum('total'))['total'] or 0

        # Expenses (debit entries in expense accounts)
        expenses = JournalItem.objects.filter(
            journal_entry__company=company,
            journal_entry__date__range=(start, end),
            journal_entry__status='posted',
            account__account_type='expense',
        ).aggregate(total=Sum('debit'))['total'] or 0

        profit = revenue - expenses

        # Employees
        employees = Employee.objects.filter(
            company=company, status='active', is_deleted=False
        ).count()

        # Inventory value
        from apps.inventory.models import StockRecord
        inv_value = StockRecord.objects.filter(
            company=company, is_deleted=False
        ).aggregate(
            total=Sum(F('quantity_on_hand') * F('average_cost'))
        )['total'] or 0

        # Outstanding receivables
        receivables = Invoice.objects.filter(
            company=company, status__in=['sent', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0

        # Open leads
        from apps.crm.models import Lead
        open_leads = Lead.objects.filter(
            company=company, is_deleted=False,
            status__in=['new', 'contacted', 'qualified', 'proposal', 'negotiation']
        ).count()

        # Open tickets
        from apps.helpdesk.models import Ticket
        open_tickets = Ticket.objects.filter(
            company=company, is_deleted=False,
            status__in=['open', 'in_progress']
        ).count()

        return {
            'revenue': float(revenue),
            'expenses': float(expenses),
            'profit': float(profit),
            'profit_margin': round(float(profit / revenue * 100), 1) if revenue else 0,
            'employees': employees,
            'inventory_value': float(inv_value),
            'receivables': float(receivables),
            'open_leads': open_leads,
            'open_tickets': open_tickets,
        }

    def _get_charts(self, company, start, end):
        from apps.sales.models import Invoice
        from apps.accounting.models import JournalItem
        import calendar

        months = []
        revenue_data = []
        expense_data = []

        # Build monthly chart for last 12 months
        today = date.today()
        for i in range(11, -1, -1):
            m_date = today.replace(day=1) - timedelta(days=i * 28)
            m_date = m_date.replace(day=1)
            last_day = calendar.monthrange(m_date.year, m_date.month)[1]
            m_end = m_date.replace(day=last_day)

            label = m_date.strftime('%b %y')
            months.append(label)

            rev = Invoice.objects.filter(
                company=company, invoice_date__range=(m_date, m_end),
                status__in=['sent', 'partial', 'paid']
            ).aggregate(t=Sum('total'))['t'] or 0

            exp = JournalItem.objects.filter(
                journal_entry__company=company,
                journal_entry__date__range=(m_date, m_end),
                journal_entry__status='posted',
                account__account_type='expense',
            ).aggregate(t=Sum('debit'))['t'] or 0

            revenue_data.append(float(rev))
            expense_data.append(float(exp))

        # Pipeline by stage
        from apps.crm.models import Lead
        pipeline = {
            label: Lead.objects.filter(company=company, status=val, is_deleted=False).count()
            for val, label in [
                ('new', 'New'), ('contacted', 'Contacted'), ('qualified', 'Qualified'),
                ('proposal', 'Proposal'), ('won', 'Won'),
            ]
        }

        # Revenue breakdown by top product categories
        from apps.sales.models import InvoiceLine
        breakdown_qs = InvoiceLine.objects.filter(
            invoice__company=company,
            invoice__invoice_date__range=(start, end),
            invoice__status__in=['sent', 'partial', 'paid'],
            product__category__isnull=False,
        ).values('product__category__name').annotate(total=Sum('total')).order_by('-total')[:5]

        breakdown = {row['product__category__name']: float(row['total']) for row in breakdown_qs}
        if not breakdown:
            breakdown = {'Products': 60, 'Services': 25, 'Consulting': 10, 'Other': 5}

        from apps.inventory.models import StockRecord
        inv_breakdown_qs = StockRecord.objects.filter(
            company=company, is_deleted=False, product__category__isnull=False
        ).values('product__category__name').annotate(
            total=Sum(F('quantity_on_hand') * F('average_cost'))
        ).order_by('-total')[:6]

        inv_categories = [row['product__category__name'] for row in inv_breakdown_qs]
        inv_values = [float(row['total']) for row in inv_breakdown_qs]

        if not inv_categories:
            inv_categories = ['Electronics', 'Raw Materials', 'Finished Goods', 'Consumables']
            inv_values = [0, 0, 0, 0]

        return {
            'months': months,
            'revenue': revenue_data,
            'expenses': expense_data,
            'pipeline': pipeline,
            'breakdown': breakdown,
            'inventory_categories': inv_categories,
            'inventory_values': inv_values,
            'cash_inflow': revenue_data,
            'cash_outflow': expense_data,
        }


# ─── HR Dashboard API ─────────────────────────────────────────────────────

class HRDashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        period = request.query_params.get('period', 'month')
        start_date, end_date = get_period_dates(period)

        from apps.hrms.models import Employee, Attendance, LeaveRequest, PayrollPeriod

        total_employees = Employee.objects.filter(company=company, status='active', is_deleted=False).count()
        today = date.today()

        # Attendance today
        present_today = Attendance.objects.filter(
            company=company, date=today, status='present'
        ).count()

        absent_today = Attendance.objects.filter(
            company=company, date=today, status='absent'
        ).count()

        on_leave = Attendance.objects.filter(
            company=company, date=today, status='on_leave'
        ).count()

        # Pending leave requests
        pending_leaves = LeaveRequest.objects.filter(
            company=company, status='pending', is_deleted=False
        ).count()

        # Department distribution
        dept_data = Employee.objects.filter(
            company=company, status='active', is_deleted=False
        ).values('department__name').annotate(count=Count('id')).order_by('-count')[:8]

        return Response({
            'kpis': {
                'total_employees': total_employees,
                'present_today': present_today,
                'absent_today': absent_today,
                'on_leave': on_leave,
                'pending_leaves': pending_leaves,
                'attendance_rate': round(present_today / total_employees * 100, 1) if total_employees else 0,
            },
            'charts': {
                'dept_labels': [d['department__name'] or 'Unassigned' for d in dept_data],
                'dept_values': [d['count'] for d in dept_data],
            }
        })


# ─── Sales Dashboard API ───────────────────────────────────────────────────

class SalesDashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        period = request.query_params.get('period', 'month')
        start_date, end_date = get_period_dates(period)

        from apps.sales.models import Invoice, SalesOrder, Quotation
        from apps.crm.models import Lead, Customer

        total_leads = Lead.objects.filter(company=company, is_deleted=False).count()
        won_leads = Lead.objects.filter(company=company, status='won', is_deleted=False).count()
        conversion = round(won_leads / total_leads * 100, 1) if total_leads else 0

        revenue = Invoice.objects.filter(
            company=company, invoice_date__range=(start_date, end_date),
            status__in=['sent', 'partial', 'paid']
        ).aggregate(t=Sum('total'))['t'] or 0

        open_orders = SalesOrder.objects.filter(
            company=company, status__in=['confirmed', 'processing'], is_deleted=False
        ).count()

        return Response({
            'kpis': {
                'total_leads': total_leads,
                'won_leads': won_leads,
                'conversion_rate': conversion,
                'revenue': float(revenue),
                'open_orders': open_orders,
                'total_customers': Customer.objects.filter(company=company, is_deleted=False).count(),
            }
        })


# ─── Finance Dashboard API ─────────────────────────────────────────────────

class FinanceDashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        period = request.query_params.get('period', 'month')
        start_date, end_date = get_period_dates(period)

        from apps.sales.models import Invoice
        from apps.purchase.models import PurchaseOrder
        from apps.accounting.models import BankAccount

        receivables = Invoice.objects.filter(
            company=company, status__in=['sent', 'partial']
        ).aggregate(t=Sum('balance_due'))['t'] or 0

        payables = PurchaseOrder.objects.filter(
            company=company, status__in=['confirmed', 'partial']
        ).aggregate(t=Sum('balance_due'))['t'] or 0

        cash = BankAccount.objects.filter(
            company=company, is_active=True
        ).aggregate(t=Sum('current_balance'))['t'] or 0

        overdue = Invoice.objects.filter(
            company=company, status__in=['sent', 'partial'],
            due_date__lt=date.today()
        ).aggregate(t=Sum('balance_due'))['t'] or 0

        return Response({
            'kpis': {
                'receivables': float(receivables),
                'payables': float(payables),
                'cash_balance': float(cash),
                'overdue': float(overdue),
                'working_capital': float(receivables + cash - payables),
            }
        })


# ─── Global Search API ─────────────────────────────────────────────────────

class GlobalSearchAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response({'results': []})

        company = request.user.primary_company
        results = []

        # Search customers
        from apps.crm.models import Customer
        for c in Customer.objects.filter(company=company, name__icontains=q, is_deleted=False)[:3]:
            results.append({'title': c.name, 'module': 'CRM', 'subtitle': 'Customer',
                            'icon': 'user-tie', 'url': f'/crm/customers/{c.pk}/'})

        # Search invoices
        from apps.sales.models import Invoice
        for inv in Invoice.objects.filter(company=company, number__icontains=q, is_deleted=False)[:3]:
            results.append({'title': inv.number, 'module': 'Sales', 'subtitle': inv.customer.name,
                            'icon': 'file-invoice-dollar', 'url': f'/sales/invoices/{inv.pk}/'})

        # Search employees
        from apps.hrms.models import Employee
        for emp in Employee.objects.filter(
            company=company, is_deleted=False
        ).filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(employee_id__icontains=q))[:3]:
            results.append({'title': emp.full_name, 'module': 'HRMS', 'subtitle': emp.employee_id,
                            'icon': 'id-badge', 'url': f'/hrms/employees/{emp.pk}/'})

        # Search products
        from apps.inventory.models import Product
        for p in Product.objects.filter(
            company=company, is_deleted=False
        ).filter(Q(name__icontains=q) | Q(sku__icontains=q))[:3]:
            results.append({'title': p.name, 'module': 'Inventory', 'subtitle': p.sku,
                            'icon': 'box', 'url': f'/inventory/products/{p.pk}/'})

        return Response({'results': results[:12]})


# ─── Web Views ─────────────────────────────────────────────────────────────

class DashboardIndexView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.primary_company

        # Recent invoices for template render
        if company:
            from apps.sales.models import Invoice
            ctx['recent_invoices'] = Invoice.objects.filter(
                company=company, is_deleted=False
            ).select_related('customer').order_by('-invoice_date')[:8]

            from apps.crm.models import Customer, Lead
            from apps.helpdesk.models import Ticket
            from apps.projects.models import Task
            from apps.sales.models import SalesOrder
            from django.db.models import Sum, Count
            ctx['top_customers'] = Customer.objects.filter(
                company=company, is_deleted=False
            ).annotate(
                order_count=Count('sales_orders'),
                total_revenue=Sum('sales_orders__total'),
            ).order_by('-total_revenue')[:6]

            ctx['secondary_kpis'] = [
                {
                    'label': 'Active Leads',
                    'value': Lead.objects.filter(company=company, is_deleted=False, status__in=['new', 'contacted', 'qualified']).count(),
                },
                {
                    'label': 'Unpaid Invoices',
                    'value': Invoice.objects.filter(company=company, is_deleted=False, status='sent').count(),
                },
                {
                    'label': 'Open Orders',
                    'value': SalesOrder.objects.filter(company=company, is_deleted=False, status='draft').count(),
                },
                {
                    'label': 'Open Tickets',
                    'value': Ticket.objects.filter(company=company, is_deleted=False).exclude(status='closed').count(),
                },
                {
                    'label': 'Pending Tasks',
                    'value': Task.objects.filter(company=company, is_deleted=False).exclude(status='done').count(),
                },
                {
                    'label': 'Total Customers',
                    'value': Customer.objects.filter(company=company, is_deleted=False).count(),
                },
            ]

        ctx['quick_actions'] = [
            {'label': 'New Quotation', 'url': '/sales/quotations/create/', 'icon': 'file-invoice'},
            {'label': 'Add Lead', 'url': '/crm/leads/create/', 'icon': 'user-plus'},
            {'label': 'Purchase Request', 'url': '/purchase/requests/create/', 'icon': 'shopping-cart'},
            {'label': 'Leave Request', 'url': '/hrms/leaves/create/', 'icon': 'calendar'},
            {'label': 'New Ticket', 'url': '/helpdesk/tickets/create/', 'icon': 'ticket-alt'},
            {'label': 'Add Task', 'url': '/projects/tasks/create/', 'icon': 'tasks'},
        ]
        return ctx

class SalesDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/sales.html'

class FinanceDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/finance.html'

class PurchaseDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/purchase.html'

class WarehouseDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/warehouse.html'

class HRDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/hr.html'

class CRMDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/crm.html'

class ProjectDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/projects.html'

class HelpdeskDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/helpdesk.html'

class ExecutiveKPIDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/executive_kpi.html'
