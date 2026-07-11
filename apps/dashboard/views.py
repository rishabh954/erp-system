"""
Dashboard API Views
CEO, HR, Sales, Finance dashboards — all KPIs and chart data
"""

from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, F, Q, Sum
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


def get_period_dates(period="month"):
    today = timezone.localdate()
    if period == "today":
        return today, today
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if period == "month":
        return today.replace(day=1), today
    if period == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=q_start_month, day=1), today
    if period == "year":
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


# ─── CEO Dashboard API ─────────────────────────────────────────────────────


class CEODashboardAPIView(APIView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        if not company:
            return Response({"error": "No company assigned"}, status=400)

        period = request.query_params.get("period", "month")
        start_date, end_date = get_period_dates(period)

        return Response(
            {
                "kpis": self._get_kpis(company, start_date, end_date),
                "charts": self._get_charts(company, start_date, end_date),
                "meta": {"period": period, "start": start_date, "end": end_date},
            }
        )

    def _get_kpis(self, company, start, end):
        from apps.accounting.models import JournalItem
        from apps.hrms.models import Employee
        from apps.sales.models import Invoice

        # Revenue
        revenue = (
            Invoice.objects.filter(
                company=company,
                invoice_date__range=(start, end),
                status__in=["sent", "partial", "paid"],
            ).aggregate(total=Sum("total"))["total"]
            or 0
        )

        # Expenses (debit entries in expense accounts)
        expenses = (
            JournalItem.objects.filter(
                journal_entry__company=company,
                journal_entry__date__range=(start, end),
                journal_entry__status="posted",
                account__account_type="expense",
            ).aggregate(total=Sum("debit"))["total"]
            or 0
        )

        profit = revenue - expenses

        # Employees
        employees = Employee.objects.filter(
            company=company, status="active", is_deleted=False
        ).count()

        # Inventory value
        from apps.inventory.models import StockRecord

        inv_value = (
            StockRecord.objects.filter(company=company, is_deleted=False).aggregate(
                total=Sum(F("quantity_on_hand") * F("average_cost"))
            )["total"]
            or 0
        )

        # Outstanding receivables
        receivables = (
            Invoice.objects.filter(
                company=company, status__in=["sent", "partial"]
            ).aggregate(total=Sum("balance_due"))["total"]
            or 0
        )

        # Open leads
        from apps.crm.models import Lead

        open_leads = Lead.objects.filter(
            company=company,
            is_deleted=False,
            status__in=["new", "contacted", "qualified", "proposal", "negotiation"],
        ).count()

        # Open tickets
        from apps.helpdesk.models import Ticket

        open_tickets = Ticket.objects.filter(
            company=company, is_deleted=False, status__in=["open", "in_progress"]
        ).count()

        return {
            "revenue": float(revenue),
            "expenses": float(expenses),
            "profit": float(profit),
            "profit_margin": round(float(profit / revenue * 100), 1) if revenue else 0,
            "employees": employees,
            "inventory_value": float(inv_value),
            "receivables": float(receivables),
            "open_leads": open_leads,
            "open_tickets": open_tickets,
        }

    def _get_charts(self, company, start, end):
        import calendar

        from apps.accounting.models import JournalItem
        from apps.sales.models import Invoice

        months = []
        revenue_data = []
        expense_data = []

        from django.db.models import Count
        from django.db.models.functions import TruncMonth

        # Build monthly chart for last 12 months
        today = timezone.localdate()
        m_date_start = today.replace(day=1) - timedelta(days=11 * 28)
        m_date_start = m_date_start.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        m_end_today = today.replace(day=last_day)

        rev_qs = (
            Invoice.objects.filter(
                company=company,
                invoice_date__range=(m_date_start, m_end_today),
                status__in=["sent", "partial", "paid"],
            )
            .annotate(month=TruncMonth("invoice_date"))
            .values("month")
            .annotate(t=Sum("total"))
        )
        rev_dict = {
            (item["month"].date() if hasattr(item["month"], "date") else item["month"]).strftime("%b %y"): item["t"]
            for item in rev_qs
            if item["month"]
        }

        exp_qs = (
            JournalItem.objects.filter(
                journal_entry__company=company,
                journal_entry__date__range=(m_date_start, m_end_today),
                journal_entry__status="posted",
                account__account_type="expense",
            )
            .annotate(month=TruncMonth("journal_entry__date"))
            .values("month")
            .annotate(t=Sum("debit"))
        )
        exp_dict = {
            (item["month"].date() if hasattr(item["month"], "date") else item["month"]).strftime("%b %y"): item["t"]
            for item in exp_qs
            if item["month"]
        }

        for i in range(11, -1, -1):
            m_date = today.replace(day=1) - timedelta(days=i * 28)
            m_date = m_date.replace(day=1)

            label = m_date.strftime("%b %y")
            months.append(label)
            revenue_data.append(float(rev_dict.get(label, 0)))
            expense_data.append(float(exp_dict.get(label, 0)))

        # Pipeline by stage
        from apps.crm.models import Lead

        pipeline_qs = (
            Lead.objects.filter(
                company=company,
                is_deleted=False,
                status__in=["new", "contacted", "qualified", "proposal", "won"],
            )
            .values("status")
            .annotate(c=Count("id"))
        )
        pipeline_counts = {item["status"]: item["c"] for item in pipeline_qs}

        pipeline = {
            label: pipeline_counts.get(val, 0)
            for val, label in [
                ("new", "New"),
                ("contacted", "Contacted"),
                ("qualified", "Qualified"),
                ("proposal", "Proposal"),
                ("won", "Won"),
            ]
        }

        # Revenue breakdown by top product categories
        from apps.sales.models import InvoiceLine

        breakdown_qs = (
            InvoiceLine.objects.filter(
                invoice__company=company,
                invoice__invoice_date__range=(start, end),
                invoice__status__in=["sent", "partial", "paid"],
                product__category__isnull=False,
            )
            .values("product__category__name")
            .annotate(total=Sum("total"))
            .order_by("-total")[:5]
        )

        breakdown = {
            row["product__category__name"]: float(row["total"]) for row in breakdown_qs
        }
        if not breakdown:
            breakdown = {"Products": 60, "Services": 25, "Consulting": 10, "Other": 5}

        from apps.inventory.models import StockRecord

        inv_breakdown_qs = (
            StockRecord.objects.filter(
                company=company, is_deleted=False, product__category__isnull=False
            )
            .values("product__category__name")
            .annotate(total=Sum(F("quantity_on_hand") * F("average_cost")))
            .order_by("-total")[:6]
        )

        inv_categories = [row["product__category__name"] for row in inv_breakdown_qs]
        inv_values = [float(row["total"]) for row in inv_breakdown_qs]

        if not inv_categories:
            inv_categories = [
                "Electronics",
                "Raw Materials",
                "Finished Goods",
                "Consumables",
            ]
            inv_values = [0, 0, 0, 0]

        return {
            "months": months,
            "revenue": revenue_data,
            "expenses": expense_data,
            "pipeline": pipeline,
            "breakdown": breakdown,
            "inventory_categories": inv_categories,
            "inventory_values": inv_values,
            "cash_inflow": revenue_data,
            "cash_outflow": expense_data,
        }


# ─── HR Dashboard API ─────────────────────────────────────────────────────


class HRDashboardAPIView(APIView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        period = request.query_params.get("period", "month")
        start_date, end_date = get_period_dates(period)

        from apps.hrms.models import Attendance, Employee, LeaveRequest

        total_employees = Employee.objects.filter(
            company=company, status="active", is_deleted=False
        ).count()
        today = timezone.localdate()

        # Attendance today
        present_today = Attendance.objects.filter(
            company=company, date=today, status="present"
        ).count()

        absent_today = Attendance.objects.filter(
            company=company, date=today, status="absent"
        ).count()

        on_leave = Attendance.objects.filter(
            company=company, date=today, status="on_leave"
        ).count()

        # Pending leave requests
        pending_leaves = LeaveRequest.objects.filter(
            company=company, status="pending", is_deleted=False
        ).count()

        # Department distribution
        dept_data = (
            Employee.objects.filter(company=company, status="active", is_deleted=False)
            .values("department__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:8]
        )

        return Response(
            {
                "kpis": {
                    "total_employees": total_employees,
                    "present_today": present_today,
                    "absent_today": absent_today,
                    "on_leave": on_leave,
                    "pending_leaves": pending_leaves,
                    "attendance_rate": (
                        round(present_today / total_employees * 100, 1)
                        if total_employees
                        else 0
                    ),
                },
                "charts": {
                    "dept_labels": [
                        d["department__name"] or "Unassigned" for d in dept_data
                    ],
                    "dept_values": [d["count"] for d in dept_data],
                },
            }
        )


# ─── Sales Dashboard API ───────────────────────────────────────────────────


class SalesDashboardAPIView(APIView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        period = request.query_params.get("period", "month")
        start_date, end_date = get_period_dates(period)

        from apps.crm.models import Customer, Lead
        from apps.sales.models import Invoice, SalesOrder

        total_leads = Lead.objects.filter(company=company, is_deleted=False).count()
        won_leads = Lead.objects.filter(
            company=company, status="won", is_deleted=False
        ).count()
        conversion = round(won_leads / total_leads * 100, 1) if total_leads else 0

        revenue = (
            Invoice.objects.filter(
                company=company,
                invoice_date__range=(start_date, end_date),
                status__in=["sent", "partial", "paid"],
            ).aggregate(t=Sum("total"))["t"]
            or 0
        )

        open_orders = SalesOrder.objects.filter(
            company=company, status__in=["confirmed", "processing"], is_deleted=False
        ).count()

        return Response(
            {
                "kpis": {
                    "total_leads": total_leads,
                    "won_leads": won_leads,
                    "conversion_rate": conversion,
                    "revenue": float(revenue),
                    "open_orders": open_orders,
                    "total_customers": Customer.objects.filter(
                        company=company, is_deleted=False
                    ).count(),
                }
            }
        )


# ─── Finance Dashboard API ─────────────────────────────────────────────────


class FinanceDashboardAPIView(APIView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60 * 15))
    def get(self, request):
        company = request.user.primary_company
        period = request.query_params.get("period", "month")
        start_date, end_date = get_period_dates(period)

        from apps.accounting.models import BankAccount
        from apps.purchase.models import PurchaseOrder
        from apps.sales.models import Invoice

        receivables = (
            Invoice.objects.filter(
                company=company, status__in=["sent", "partial"]
            ).aggregate(t=Sum("balance_due"))["t"]
            or 0
        )

        payables = (
            PurchaseOrder.objects.filter(
                company=company, status__in=["confirmed", "partial"]
            ).aggregate(t=Sum("balance_due"))["t"]
            or 0
        )

        cash = (
            BankAccount.objects.filter(company=company, is_active=True).aggregate(
                t=Sum("current_balance")
            )["t"]
            or 0
        )

        overdue = (
            Invoice.objects.filter(
                company=company,
                status__in=["sent", "partial"],
                due_date__lt=timezone.localdate(),
            ).aggregate(t=Sum("balance_due"))["t"]
            or 0
        )

        return Response(
            {
                "kpis": {
                    "receivables": float(receivables),
                    "payables": float(payables),
                    "cash_balance": float(cash),
                    "overdue": float(overdue),
                    "working_capital": float(receivables + cash - payables),
                }
            }
        )


# ─── Global Search API ─────────────────────────────────────────────────────


class GlobalSearchAPIView(APIView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if len(q) < 2:
            return Response({"results": []})

        company = request.user.primary_company
        results = []

        # Search customers
        from apps.crm.models import Customer

        for c in Customer.objects.filter(
            company=company, name__icontains=q, is_deleted=False
        )[:3]:
            results.append(
                {
                    "title": c.name,
                    "module": "CRM",
                    "subtitle": "Customer",
                    "icon": "user-tie",
                    "url": f"/crm/customers/{c.pk}/",
                }
            )

        # Search invoices
        from apps.sales.models import Invoice

        for inv in Invoice.objects.filter(
            company=company, number__icontains=q, is_deleted=False
        )[:3]:
            results.append(
                {
                    "title": inv.number,
                    "module": "Sales",
                    "subtitle": inv.customer.name,
                    "icon": "file-invoice-dollar",
                    "url": f"/sales/invoices/{inv.pk}/",
                }
            )

        # Search employees
        from apps.hrms.models import Employee

        for emp in Employee.objects.filter(company=company, is_deleted=False).filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(employee_id__icontains=q)
        )[:3]:
            results.append(
                {
                    "title": emp.full_name,
                    "module": "HRMS",
                    "subtitle": emp.employee_id,
                    "icon": "id-badge",
                    "url": f"/hrms/employees/{emp.pk}/",
                }
            )

        # Search products
        from apps.inventory.models import Product

        for p in Product.objects.filter(company=company, is_deleted=False).filter(
            Q(name__icontains=q) | Q(sku__icontains=q)
        )[:3]:
            results.append(
                {
                    "title": p.name,
                    "module": "Inventory",
                    "subtitle": p.sku,
                    "icon": "box",
                    "url": f"/inventory/products/{p.pk}/",
                }
            )

        return Response({"results": results[:12]})


# ─── Web Views ─────────────────────────────────────────────────────────────


class DashboardIndexView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/index.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.primary_company:
            return redirect("company:create")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.primary_company

        # Recent invoices for template render
        if company:
            from apps.sales.models import Invoice

            ctx["recent_invoices"] = (
                Invoice.objects.filter(company=company, is_deleted=False)
                .select_related("customer")
                .order_by("-invoice_date")[:8]
            )

            from django.db.models import Count, Sum

            from apps.crm.models import Customer, Lead
            from apps.helpdesk.models import Ticket
            from apps.projects.models import Task
            from apps.sales.models import SalesOrder

            ctx["top_customers"] = (
                Customer.objects.filter(company=company, is_deleted=False)
                .annotate(
                    order_count=Count("sales_orders"),
                    total_revenue=Sum("sales_orders__total"),
                )
                .order_by("-total_revenue")[:6]
            )

            ctx["secondary_kpis"] = [
                {
                    "label": "Active Leads",
                    "value": Lead.objects.filter(
                        company=company,
                        is_deleted=False,
                        status__in=["new", "contacted", "qualified"],
                    ).count(),
                },
                {
                    "label": "Unpaid Invoices",
                    "value": Invoice.objects.filter(
                        company=company, is_deleted=False, status="sent"
                    ).count(),
                },
                {
                    "label": "Open Orders",
                    "value": SalesOrder.objects.filter(
                        company=company, is_deleted=False, status="draft"
                    ).count(),
                },
                {
                    "label": "Open Tickets",
                    "value": Ticket.objects.filter(company=company, is_deleted=False)
                    .exclude(status="closed")
                    .count(),
                },
                {
                    "label": "Pending Tasks",
                    "value": Task.objects.filter(company=company, is_deleted=False)
                    .exclude(status="done")
                    .count(),
                },
                {
                    "label": "Total Customers",
                    "value": Customer.objects.filter(
                        company=company, is_deleted=False
                    ).count(),
                },
            ]

        ctx["quick_actions"] = [
            {
                "label": "New Quotation",
                "url": "/sales/quotations/create/",
                "icon": "file-invoice",
            },
            {"label": "Add Lead", "url": "/crm/leads/create/", "icon": "user-plus"},
            {
                "label": "Purchase Request",
                "url": "/purchase/requests/create/",
                "icon": "shopping-cart",
            },
            {
                "label": "Leave Request",
                "url": "/hrms/leaves/create/",
                "icon": "calendar",
            },
            {
                "label": "New Ticket",
                "url": "/helpdesk/tickets/create/",
                "icon": "ticket-alt",
            },
            {"label": "Add Task", "url": "/projects/tasks/create/", "icon": "tasks"},
        ]
        return ctx


class SalesDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/sales.html"


class FinanceDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/finance.html"


class PurchaseDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/purchase.html"


class WarehouseDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/warehouse.html"


class HRDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/hr.html"


class CRMDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/crm.html"


class ProjectDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/projects.html"


class HelpdeskDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/helpdesk.html"


class ExecutiveKPIDashboardView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/executive_kpi.html"


from datetime import datetime

from django.http import JsonResponse
from django.views import View

from apps.crm.models import Lead, LeadActivity
from apps.hrms.models import LeaveRequest
from apps.projects.models import Milestone
from apps.projects.models import Task as ProjectTask
from apps.purchase.models import Bill
from apps.sales.models import Invoice


class CalendarView(LoginRequiredMixin, TemplateView):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    template_name = "dashboard/calendar.html"


class CalendarEventsAPIView(LoginRequiredMixin, View):
    required_permission = "dashboard.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "dashboard.create"
            elif request.method in ["PUT", "PATCH"]:
                return "dashboard.update"
            elif request.method == "DELETE":
                return "dashboard.delete"
        return self.required_permission
    def get(self, request, *args, **kwargs):
        start_str = request.GET.get("start")
        end_str = request.GET.get("end")

        events = []
        company = getattr(request.user, "primary_company", None)
        if not company:
            return JsonResponse(events, safe=False)

        if start_str and end_str:
            start_date = datetime.fromisoformat(start_str.replace("Z", "+00:00")).date()
            end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00")).date()

            # HRMS Leaves
            if request.GET.get("leaves") == "true":
                leaves = LeaveRequest.objects.filter(
                    employee__company=company,
                    status="approved",
                    start_date__lt=end_date,
                    end_date__gte=start_date,
                )
                for leave in leaves:
                    events.append(
                        {
                            "id": f"leave_{leave.id}",
                            "title": f"{leave.employee.user.full_name} (Leave)",
                            "start": leave.start_date.isoformat(),
                            "end": (
                                leave.end_date + timezone.timedelta(days=1)
                            ).isoformat(),  # exclusive end
                            "color": "#17a2b8",  # info blue
                            "url": "/hrms/leaves/",
                        }
                    )

            # CRM Leads closing
            if request.GET.get("crm_leads") == "true":
                leads = Lead.objects.filter(
                    company=company, expected_close_date__range=[start_date, end_date]
                )
                for lead in leads:
                    events.append(
                        {
                            "id": f"lead_{lead.id}",
                            "title": f"Close: {lead.name}",
                            "start": lead.expected_close_date.isoformat(),
                            "color": "#28a745",  # success green
                            "url": f"/crm/leads/{lead.id}/",
                        }
                    )

            # CRM Activities
            if request.GET.get("crm_activities") == "true":
                from django.db.models import Q

                crm_activities = LeadActivity.objects.filter(
                    Q(lead__company=company)
                    & (
                        Q(scheduled_at__date__range=[start_date, end_date])
                        | Q(created_at__date__range=[start_date, end_date])
                    )
                )
                for act in crm_activities:
                    act_date = act.scheduled_at if act.scheduled_at else act.created_at
                    events.append(
                        {
                            "id": f"crmact_{act.id}",
                            "title": f"{act.get_activity_type_display()}: {act.lead.name}",
                            "start": act_date.isoformat() if act_date else None,
                            "color": "#20c997",  # teal
                            "url": f"/crm/leads/{act.lead.id}/",
                        }
                    )

            # Invoices Due
            if request.GET.get("invoices") == "true":
                invoices = Invoice.objects.filter(
                    company=company, due_date__range=[start_date, end_date]
                ).exclude(status="paid")
                for inv in invoices:
                    events.append(
                        {
                            "id": f"inv_{inv.id}",
                            "title": f"Inv Due: {inv.number}",
                            "start": inv.due_date.isoformat(),
                            "color": "#dc3545",  # danger red
                            "url": f"/sales/invoices/{inv.id}/",
                        }
                    )

            # Bills Due
            if request.GET.get("bills") == "true":
                bills = Bill.objects.filter(
                    company=company, due_date__range=[start_date, end_date]
                ).exclude(status="paid")
                for bill in bills:
                    events.append(
                        {
                            "id": f"bill_{bill.id}",
                            "title": f"Bill Due: {bill.number}",
                            "start": bill.due_date.isoformat(),
                            "color": "#fd7e14",  # warning orange
                            "url": f"/purchase/bills/{bill.id}/",
                        }
                    )

            # Project Tasks
            if request.GET.get("project_tasks") == "true":
                tasks = ProjectTask.objects.filter(
                    project__company=company, due_date__range=[start_date, end_date]
                ).exclude(status="completed")
                for task in tasks:
                    events.append(
                        {
                            "id": f"task_{task.id}",
                            "title": f"Task: {task.title}",
                            "start": task.due_date.isoformat(),
                            "color": "#6f42c1",  # purple
                            "url": f"/projects/{task.project.id}/",
                        }
                    )

            # Project Milestones
            if request.GET.get("project_milestones") == "true":
                milestones = Milestone.objects.filter(
                    project__company=company,
                    due_date__range=[start_date, end_date],
                    is_completed=False,
                )
                for m in milestones:
                    events.append(
                        {
                            "id": f"milestone_{m.id}",
                            "title": f"Milestone: {m.name}",
                            "start": m.due_date.isoformat(),
                            "color": "#e83e8c",  # pink
                            "url": f"/projects/{m.project.id}/",
                        }
                    )

        return JsonResponse(events, safe=False)
