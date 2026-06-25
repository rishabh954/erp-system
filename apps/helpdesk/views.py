"""
HelpDesk Views - Tickets, SLA, Knowledge Base
"""
from django.views.generic import ListView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from .models import Ticket, TicketCategory, TicketReply, KnowledgeBaseArticle
from core.services import BaseService


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


class TicketListView(CompanyMixin, ListView):
    template_name = 'helpdesk/tickets/list.html'
    context_object_name = 'tickets'
    paginate_by = 25

    def get_queryset(self):
        qs = Ticket.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('assigned_to', 'requester', 'category').order_by('-created_at')

        status   = self.request.GET.get('status', '')
        priority = self.request.GET.get('priority', '')
        q        = self.request.GET.get('q', '')

        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))

        if self.request.user.role not in ('company_admin', 'super_admin'):
            qs = qs.filter(
                Q(assigned_to=self.request.user) | Q(requester=self.request.user)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        ctx['status_choices']   = Ticket.Status.choices
        ctx['priority_choices'] = Ticket.Priority.choices
        ctx['open_count']   = Ticket.objects.filter(company=c, status='open', is_deleted=False).count()
        ctx['sla_breached'] = Ticket.objects.filter(company=c, sla_breached=True, is_deleted=False,
                                                     status__in=['open','in_progress']).count()
        return ctx


class TicketDetailView(CompanyMixin, DetailView):
    template_name = 'helpdesk/tickets/detail.html'
    context_object_name = 'ticket'

    def get_object(self):
        return get_object_or_404(Ticket, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['replies'] = self.object.replies.filter(is_deleted=False).select_related('author').order_by('created_at')
        ctx['status_choices'] = Ticket.Status.choices
        from apps.authentication.models import User
        ctx['agents'] = User.objects.filter(companies=self.company(), is_active=True).order_by('first_name')
        # Mark first response time
        ticket = self.object
        if not ticket.first_response_at and ticket.replies.filter(is_deleted=False).exists():
            ticket.first_response_at = ticket.replies.filter(is_deleted=False).earliest('created_at').created_at
            ticket.save(update_fields=['first_response_at'])
        return ctx


class TicketCreateView(CompanyMixin, View):
    template_name = 'helpdesk/tickets/form.html'

    def get(self, request):
        return render(request, self.template_name, {
            'categories': TicketCategory.objects.filter(company=self.company(), is_active=True, is_deleted=False),
            'priority_choices': Ticket.Priority.choices,
            'source_choices': Ticket.Source.choices,
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            category_id = data.get('category') or None
            ticket = Ticket(
                company=company,
                title=data['title'],
                description=data['description'],
                category_id=category_id,
                requester=request.user,
                priority=data.get('priority', 'medium'),
                source=data.get('source', 'portal'),
                status='open',
            )
            ticket.number = BaseService.generate_sequence_number('TKT', Ticket, company.pk)

            # Set SLA due time
            if category_id:
                try:
                    cat = TicketCategory.objects.get(pk=category_id)
                    from datetime import timedelta
                    ticket.sla_due_at = timezone.now() + timedelta(hours=cat.sla_hours)
                    # Auto-assign if configured
                    if cat.auto_assign_to:
                        ticket.assigned_to = cat.auto_assign_to
                except TicketCategory.DoesNotExist:
                    pass

            ticket.save()
            messages.success(request, f'Ticket {ticket.number} created.')
            return redirect('helpdesk:ticket_detail', pk=ticket.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('helpdesk:tickets')


class AddReplyView(CompanyMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk, company=self.company(), is_deleted=False)
        content = request.POST.get('content', '').strip()
        is_internal = request.POST.get('is_internal') == 'on'

        if content:
            reply = TicketReply(
                company=self.company(),
                ticket=ticket,
                author=request.user,
                content=content,
                is_internal=is_internal,
            )
            if request.FILES.get('attachment'):
                reply.attachment = request.FILES['attachment']
            reply.save()

            # Update status if agent replies
            if ticket.status == 'open' and not is_internal:
                ticket.status = 'in_progress'
                if not ticket.first_response_at:
                    ticket.first_response_at = timezone.now()
                ticket.save(update_fields=['status', 'first_response_at'])

        # Handle status change
        new_status = request.POST.get('new_status', '')
        if new_status and new_status in dict(Ticket.Status.choices):
            ticket.status = new_status
            if new_status == 'resolved':
                ticket.resolved_at = timezone.now()
            elif new_status == 'closed':
                ticket.closed_at = timezone.now()
            ticket.save(update_fields=['status', 'resolved_at', 'closed_at'])

        # Handle assignment
        new_assignee = request.POST.get('assigned_to', '')
        if new_assignee:
            ticket.assigned_to_id = new_assignee
            ticket.save(update_fields=['assigned_to'])

        messages.success(request, 'Reply added.')
        return redirect('helpdesk:ticket_detail', pk=pk)


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = 'helpdesk'

urlpatterns = [
    path('tickets/', TicketListView.as_view(), name='tickets'),
    path('tickets/create/', TicketCreateView.as_view(), name='ticket_create'),
    path('tickets/<uuid:pk>/', TicketDetailView.as_view(), name='ticket_detail'),
    path('tickets/<uuid:pk>/reply/', AddReplyView.as_view(), name='ticket_reply'),
]
