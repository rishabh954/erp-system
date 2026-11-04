"""
HelpDesk Views - Tickets, SLA, Knowledge Base
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import DetailView, ListView, View

from core.mixins import CompanyMixin
from core.services import BaseService

from .forms import TicketCreateForm, TicketUpdateForm
from .models import Ticket, TicketCategory, TicketReply


class TicketListView(CompanyMixin, ListView):
    required_permission = "helpdesk.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "helpdesk.create"
            elif request.method in ["PUT", "PATCH"]:
                return "helpdesk.update"
            elif request.method == "DELETE":
                return "helpdesk.delete"
        return self.required_permission
    template_name = "helpdesk/tickets/list.html"
    context_object_name = "tickets"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Ticket.objects.filter(company=self.company(), is_deleted=False)
            .select_related("assigned_to", "requester", "category")
            .order_by("-created_at")
        )

        status = self.request.GET.get("status", "")
        priority = self.request.GET.get("priority", "")
        q = self.request.GET.get("q", "")

        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))

        if self.request.user.get_role_for_company(self.company()) not in (
            "company_admin",
            "super_admin",
        ):
            qs = qs.filter(
                Q(assigned_to=self.request.user) | Q(requester=self.request.user)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        ctx["status_choices"] = Ticket.Status.choices
        ctx["priority_choices"] = Ticket.Priority.choices
        ctx["open_count"] = Ticket.objects.filter(
            company=c, status="open", is_deleted=False
        ).count()
        ctx["sla_breached"] = Ticket.objects.filter(
            company=c,
            sla_breached=True,
            is_deleted=False,
            status__in=["open", "in_progress"],
        ).count()
        return ctx


class TicketDetailView(CompanyMixin, DetailView):
    required_permission = "helpdesk.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "helpdesk.create"
            elif request.method in ["PUT", "PATCH"]:
                return "helpdesk.update"
            elif request.method == "DELETE":
                return "helpdesk.delete"
        return self.required_permission
    template_name = "helpdesk/tickets/detail.html"
    context_object_name = "ticket"

    def get_object(self):
        return get_object_or_404(
            Ticket, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["replies"] = (
            self.object.replies.filter(is_deleted=False)
            .select_related("author")
            .order_by("created_at")
        )
        ctx["status_choices"] = Ticket.Status.choices
        from apps.authentication.models import User

        ctx["agents"] = User.objects.filter(
            companies=self.company(), is_active=True
        ).order_by("first_name")
        # Mark first response time
        ticket = self.object
        if (
            not ticket.first_response_at
            and ticket.replies.filter(is_deleted=False).exists()
        ):
            ticket.first_response_at = (
                ticket.replies.filter(is_deleted=False)
                .earliest("created_at")
                .created_at
            )
            ticket.save(update_fields=["first_response_at"])
        return ctx


class TicketCreateView(CompanyMixin, View):
    required_permission = "helpdesk.create"
    template_name = "helpdesk/tickets/form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "categories": TicketCategory.objects.filter(
                    company=self.company(), is_active=True, is_deleted=False
                ),
                "priority_choices": Ticket.Priority.choices,
                "source_choices": Ticket.Source.choices,
            },
        )

    def post(self, request):
        company = self.company()
        category_id = request.POST.get("category")
        if category_id:
            try:
                category_pk = TicketCategory._meta.pk.to_python(category_id)
            except (TypeError, ValueError, ValidationError):
                category_pk = None
            if (
                category_pk is not None
                and TicketCategory.objects.filter(pk=category_pk)
                .exclude(company=company)
                .exists()
            ):
                raise Http404("Ticket category not found for this company.")

        form = TicketCreateForm(request.POST, company=company)
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(
                    error for errors in form.errors.values() for error in errors
                ),
            )
            return redirect("helpdesk:tickets")

        data = form.cleaned_data
        with transaction.atomic():
            ticket = Ticket(
                company=company,
                title=data["title"],
                description=data["description"],
                category=data["category"],
                requester=request.user,
                priority=data["priority"],
                source=data["source"],
                status="open",
            )
            ticket.number = BaseService.generate_sequence_number(
                "TKT", Ticket, company.pk
            )

            if data["category"]:
                from datetime import timedelta

                ticket.sla_due_at = timezone.now() + timedelta(
                    hours=data["category"].sla_hours
                )
                if data["category"].auto_assign_to:
                    ticket.assigned_to = data["category"].auto_assign_to

            ticket.save()
        messages.success(request, f"Ticket {ticket.number} created.")
        return redirect("helpdesk:ticket_detail", pk=ticket.pk)


class AddReplyView(CompanyMixin, View):
    required_permission = "helpdesk.create"

    def post(self, request, pk):
        ticket = get_object_or_404(
            Ticket, pk=pk, company=self.company(), is_deleted=False
        )
        form = TicketUpdateForm(request.POST, company=self.company())
        if not form.is_valid():
            messages.error(
                request,
                "; ".join(
                    error for errors in form.errors.values() for error in errors
                ),
            )
            return redirect("helpdesk:ticket_detail", pk=pk)

        data = form.cleaned_data
        content = data["content"]
        with transaction.atomic():
            if content:
                reply = TicketReply(
                    company=self.company(),
                    ticket=ticket,
                    author=request.user,
                    content=content,
                    is_internal=data["is_internal"],
                )
                if request.FILES.get("attachment"):
                    reply.attachment = request.FILES["attachment"]
                reply.save()

                if ticket.status == Ticket.Status.OPEN and not data["is_internal"]:
                    ticket.status = Ticket.Status.IN_PROGRESS
                    if not ticket.first_response_at:
                        ticket.first_response_at = timezone.now()
                    ticket.save(update_fields=["status", "first_response_at"])

            new_status = data["new_status"]
            if new_status:
                ticket.status = new_status
                if new_status == "resolved":
                    ticket.resolved_at = timezone.now()
                elif new_status == "closed":
                    ticket.closed_at = timezone.now()
                ticket.save(update_fields=["status", "resolved_at", "closed_at"])

            if data["assigned_to"]:
                ticket.assigned_to = data["assigned_to"]
                ticket.save(update_fields=["assigned_to"])

        messages.success(request, "Reply added.")
        return redirect("helpdesk:ticket_detail", pk=pk)


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path  # noqa: E402

app_name = "helpdesk"

urlpatterns = [
    path("tickets/", TicketListView.as_view(), name="tickets"),
    path("tickets/create/", TicketCreateView.as_view(), name="ticket_create"),
    path("tickets/<uuid:pk>/", TicketDetailView.as_view(), name="ticket_detail"),
    path("tickets/<uuid:pk>/reply/", AddReplyView.as_view(), name="ticket_reply"),
]
