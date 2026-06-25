from django.views.generic import ListView, View, CreateView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from rest_framework import viewsets
from apps.workflow.models import WorkflowInstance, WorkflowAction, ApprovalDelegation
from apps.workflow.engine import WorkflowEngine

class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company

class WorkflowInstanceViewSet(viewsets.ModelViewSet):
    queryset = WorkflowInstance.objects.all()
    
    def get_serializer_class(self):
        from rest_framework import serializers
        class WorkflowInstanceSerializer(serializers.ModelSerializer):
            class Meta:
                model = WorkflowInstance
                fields = '__all__'
        return WorkflowInstanceSerializer


class PendingApprovalsListView(CompanyMixin, ListView):
    template_name = 'workflow/pending_approvals.html'
    context_object_name = 'instances'

    def get_queryset(self):
        # A bit complex to filter via ORM because get_pending_approvers is dynamic.
        # We will fetch all PENDING/IN_PROGRESS for company, then filter in python.
        company = self.company()
        instances = WorkflowInstance.objects.filter(
            company=company,
            status__in=[WorkflowInstance.Status.PENDING, WorkflowInstance.Status.IN_PROGRESS]
        ).select_related('definition', 'current_step', 'initiated_by', 'content_type')
        
        pending_for_me = []
        for inst in instances:
            approvers = WorkflowEngine.get_pending_approvers(inst)
            if self.request.user in approvers or self.request.user.role == 'super_admin':
                pending_for_me.append(inst)
                
        return pending_for_me


class ApprovalHistoryListView(CompanyMixin, ListView):
    template_name = 'workflow/approval_history.html'
    context_object_name = 'actions'

    def get_queryset(self):
        return WorkflowAction.objects.filter(
            company=self.company(),
            actor=self.request.user
        ).select_related('instance__definition', 'instance__content_type', 'step').order_by('-acted_at')


class DelegatedApprovalsListView(CompanyMixin, ListView):
    template_name = 'workflow/delegations.html'
    context_object_name = 'delegations'

    def get_queryset(self):
        return ApprovalDelegation.objects.filter(
            company=self.company()
        ).filter(delegator=self.request.user).order_by('-start_date')


class ApprovalDelegationCreateView(CompanyMixin, CreateView):
    model = ApprovalDelegation
    template_name = 'workflow/delegation_form.html'
    fields = ['delegatee', 'start_date', 'end_date', 'notes']
    success_url = reverse_lazy('workflow:delegations')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.authentication.models import User
        # Only allow delegating to other active users in the same company
        ctx['users'] = User.objects.filter(usercompany__company=self.company(), usercompany__is_active=True).exclude(pk=self.request.user.pk)
        return ctx

    def form_valid(self, form):
        form.instance.company = self.company()
        form.instance.delegator = self.request.user
        form.instance.is_active = True
        messages.success(self.request, 'Delegation created successfully.')
        return super().form_valid(form)




class WorkflowActionAPIView(LoginRequiredMixin, View):
    def post(self, request, instance_id):
        action = request.POST.get('action')
        comment = request.POST.get('comment', '')
        
        try:
            instance = WorkflowInstance.objects.get(pk=instance_id)
            if action == 'approve':
                WorkflowEngine.approve(instance, request.user, comment)
                messages.success(request, 'Workflow step approved successfully.')
            elif action == 'reject':
                WorkflowEngine.reject(instance, request.user, comment)
                messages.error(request, 'Workflow step rejected.')
            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
                
        except Exception as e:
            messages.error(request, f"Error processing approval: {str(e)}")
            
        return redirect(request.META.get('HTTP_REFERER', 'workflow:pending_approvals'))
