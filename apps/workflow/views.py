"""
Enterprise Workflow — Views
Includes: Designer, Pending Approvals, History, Delegation, Visual Flow API
"""
import json
from django.views.generic import ListView, View, CreateView, DetailView, TemplateView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q, Count

from apps.workflow.models import (
    WorkflowDefinition, WorkflowStep, WorkflowInstance,
    WorkflowAction, ApprovalDelegation, WorkflowNotificationTemplate,
    WorkflowEscalationLog
)
from apps.workflow.engine import WorkflowEngine


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW DEFINITION MANAGEMENT (Designer)
# ══════════════════════════════════════════════════════════════════════════════

class WorkflowListView(CompanyMixin, ListView):
    template_name = 'workflow/workflow_list.html'
    context_object_name = 'workflows'

    def get_queryset(self):
        return WorkflowDefinition.objects.filter(
            company=self.company(), is_deleted=False
        ).annotate(step_count=Count('steps')).order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['trigger_events'] = WorkflowDefinition.TriggerEvent.choices
        return ctx


class WorkflowCreateView(CompanyMixin, View):
    template_name = 'workflow/workflow_form.html'

    def get(self, request):
        from apps.authentication.models import User
        from apps.company.models import Department
        ctx = {
            'trigger_events': WorkflowDefinition.TriggerEvent.choices,
            'step_types': WorkflowStep.StepType.choices,
            'approver_types': WorkflowStep.ApproverType.choices,
            'escalation_actions': WorkflowStep.EscalationAction.choices,
            'users': User.objects.filter(
                usercompany__company=self.company(), usercompany__is_active=True
            ),
            'departments': Department.objects.filter(company=self.company()),
        }
        return render(request, self.template_name, ctx)

    def post(self, request):
        data = request.POST
        wf = WorkflowDefinition.objects.create(
            company=self.company(),
            name=data.get('name', 'Untitled Workflow'),
            description=data.get('description', ''),
            trigger_model=data.get('trigger_model', ''),
            trigger_event=data.get('trigger_event', 'on_submit'),
            notify_email=data.get('notify_email') == 'on',
            notify_whatsapp=data.get('notify_whatsapp') == 'on',
            notify_in_app=data.get('notify_in_app', 'on') == 'on',
            is_active=True,
        )
        messages.success(request, f"Workflow '{wf.name}' created. Now add approval steps.")
        return redirect('workflow:designer', pk=wf.pk)


class WorkflowDesignerView(CompanyMixin, DetailView):
    """Visual workflow designer — renders the canvas UI."""
    template_name = 'workflow/designer.html'
    context_object_name = 'workflow'

    def get_object(self):
        return get_object_or_404(WorkflowDefinition, pk=self.kwargs['pk'],
                                 company=self.company())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        wf = self.object
        from apps.authentication.models import User
        from apps.company.models import Department
        ctx.update({
            'steps': wf.steps.order_by('step_order'),
            'step_types': WorkflowStep.StepType.choices,
            'approver_types': WorkflowStep.ApproverType.choices,
            'escalation_actions': WorkflowStep.EscalationAction.choices,
            'users': User.objects.filter(
                usercompany__company=self.company(), usercompany__is_active=True
            ),
            'departments': Department.objects.filter(company=self.company()),
            'notification_templates': wf.notification_templates.all(),
            'steps_json': json.dumps([
                {
                    'id': str(s.id), 'name': s.name, 'step_order': s.step_order,
                    'step_type': s.step_type, 'approver_type': s.approver_type,
                    'approver_user': str(s.approver_user_id) if s.approver_user else None,
                    'approver_role': s.approver_role,
                    'escalation_enabled': s.escalation_enabled,
                    'escalation_hours': s.escalation_hours,
                    'min_amount': float(s.min_amount) if s.min_amount else None,
                    'max_amount': float(s.max_amount) if s.max_amount else None,
                    'x': s.canvas_x, 'y': s.canvas_y,
                } for s in wf.steps.order_by('step_order')
            ]),
        })
        return ctx


class WorkflowDesignerSaveAPI(CompanyMixin, View):
    """AJAX endpoint: saves the visual designer canvas layout."""
    def post(self, request, pk):
        wf = get_object_or_404(WorkflowDefinition, pk=pk, company=self.company())
        try:
            data = json.loads(request.body)
            wf.canvas_layout = data.get('layout', {})
            wf.save(update_fields=['canvas_layout'])

            # Update step positions if provided
            for node in data.get('nodes', []):
                WorkflowStep.objects.filter(
                    id=node['id'], workflow=wf
                ).update(canvas_x=node.get('x', 0), canvas_y=node.get('y', 0))

            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


class WorkflowVisualFlowAPI(CompanyMixin, View):
    """Returns the workflow as a JSON graph for front-end rendering."""
    def get(self, request, pk):
        wf = get_object_or_404(WorkflowDefinition, pk=pk, company=self.company())
        steps = list(wf.steps.order_by('step_order'))

        nodes = []
        edges = []

        # Start node
        nodes.append({'id': 'start', 'label': 'Start', 'type': 'start', 'x': 100, 'y': 200})

        for i, step in enumerate(steps):
            node_id = str(step.id)
            nodes.append({
                'id': node_id,
                'label': step.name,
                'type': step.step_type,
                'approver_type': step.approver_type,
                'escalation_enabled': step.escalation_enabled,
                'escalation_hours': step.escalation_hours,
                'x': step.canvas_x or (250 + i * 220),
                'y': step.canvas_y or 200,
            })

            # Edge from previous node
            if i == 0:
                edges.append({'from': 'start', 'to': node_id, 'label': ''})
            else:
                edges.append({'from': str(steps[i - 1].id), 'to': node_id, 'label': 'Next'})

            # Conditional branches
            if step.step_type == WorkflowStep.StepType.CONDITION:
                for rule in (step.condition_rules or []):
                    # Find target step by order
                    target_order = rule.get('next_step_order')
                    target_step = next(
                        (s for s in steps if s.step_order == target_order), None
                    )
                    if target_step:
                        edges.append({
                            'from': node_id,
                            'to': str(target_step.id),
                            'label': f"{rule.get('field')} {rule.get('operator')} {rule.get('value')}",
                            'type': 'condition',
                        })

        # End node
        nodes.append({'id': 'end', 'label': 'End', 'type': 'end',
                      'x': 250 + len(steps) * 220, 'y': 200})
        if steps:
            edges.append({'from': str(steps[-1].id), 'to': 'end', 'label': 'Complete'})
        else:
            edges.append({'from': 'start', 'to': 'end', 'label': 'Complete'})

        return JsonResponse({'nodes': nodes, 'edges': edges, 'workflow': {
            'id': str(wf.pk), 'name': wf.name, 'trigger_model': wf.trigger_model,
        }})


# ══════════════════════════════════════════════════════════════════════════════
# STEP MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class StepCreateView(CompanyMixin, View):
    def post(self, request, workflow_pk):
        wf   = get_object_or_404(WorkflowDefinition, pk=workflow_pk, company=self.company())
        data = request.POST
        last_order = wf.steps.count()

        try:
            min_amt = float(data.get('min_amount')) if data.get('min_amount') else None
            max_amt = float(data.get('max_amount')) if data.get('max_amount') else None
        except ValueError:
            min_amt = max_amt = None

        step = WorkflowStep.objects.create(
            workflow=wf,
            name=data.get('name', f'Step {last_order + 1}'),
            step_order=last_order + 1,
            step_type=data.get('step_type', 'approval'),
            approver_type=data.get('approver_type', 'user'),
            approver_user_id=data.get('approver_user') or None,
            approver_role=data.get('approver_role', ''),
            approver_field=data.get('approver_field', ''),
            min_amount=min_amt,
            max_amount=max_amt,
            escalation_enabled=data.get('escalation_enabled') == 'on',
            escalation_hours=int(data.get('escalation_hours') or 24),
            escalation_action=data.get('escalation_action', 'notify'),
            escalation_to_id=data.get('escalation_to') or None,
            is_required=data.get('is_required', 'on') == 'on',
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'ok', 'step_id': str(step.id), 'step_order': step.step_order})

        messages.success(request, f"Step '{step.name}' added.")
        return redirect('workflow:designer', pk=workflow_pk)


class StepDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        step = get_object_or_404(WorkflowStep, pk=pk, workflow__company=self.company())
        wf_pk = step.workflow_id
        step.delete()
        messages.success(request, "Step removed.")
        return redirect('workflow:designer', pk=wf_pk)


class StepReorderView(CompanyMixin, View):
    """AJAX: reorder steps by posting a list of IDs."""
    def post(self, request, workflow_pk):
        try:
            ids = json.loads(request.body).get('ids', [])
            for i, step_id in enumerate(ids, 1):
                WorkflowStep.objects.filter(
                    id=step_id, workflow__company=self.company()
                ).update(step_order=i)
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


# ══════════════════════════════════════════════════════════════════════════════
# PENDING APPROVALS
# ══════════════════════════════════════════════════════════════════════════════

class PendingApprovalsListView(CompanyMixin, ListView):
    template_name = 'workflow/pending_approvals.html'
    context_object_name = 'instances'

    def get_queryset(self):
        company = self.company()
        all_instances = WorkflowInstance.objects.filter(
            company=company,
            status__in=[WorkflowInstance.Status.PENDING,
                       WorkflowInstance.Status.IN_PROGRESS,
                       WorkflowInstance.Status.ESCALATED],
        ).select_related('definition', 'current_step', 'initiated_by', 'content_type')

        result = []
        for inst in all_instances:
            approvers = WorkflowEngine.get_pending_approvers(inst)
            is_admin  = getattr(self.request.user, 'role', '') in ('super_admin', 'company_admin')
            if self.request.user in approvers or is_admin:
                result.append(inst)
        return result

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_pending'] = len(ctx['instances'])
        ctx['escalated_count'] = sum(
            1 for i in ctx['instances'] if i.status == 'escalated'
        )
        return ctx


class WorkflowActionAPIView(LoginRequiredMixin, View):
    """Handle approve / reject / delegate / return actions."""

    def post(self, request, instance_id):
        action    = request.POST.get('action')
        comment   = request.POST.get('comment', '')
        delegatee_id = request.POST.get('delegatee_id')

        try:
            instance = get_object_or_404(WorkflowInstance, pk=instance_id)

            if action == 'approve':
                WorkflowEngine.approve(instance, request.user, comment)
                messages.success(request, 'Workflow step approved successfully.')

            elif action == 'reject':
                WorkflowEngine.reject(instance, request.user, comment)
                messages.warning(request, 'Workflow step rejected.')

            elif action == 'delegate':
                from apps.authentication.models import User
                delegatee = get_object_or_404(User, pk=delegatee_id)
                WorkflowEngine.delegate(instance, request.user, delegatee, comment)
                messages.success(request, f'Approval delegated to {delegatee.get_full_name()}.')

            elif action == 'return':
                WorkflowEngine.return_for_clarification(instance, request.user, comment)
                messages.info(request, 'Returned to submitter for clarification.')

            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)

        except (PermissionError, ValueError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")

        return redirect(request.META.get('HTTP_REFERER', reverse('workflow:pending_approvals')))


# ══════════════════════════════════════════════════════════════════════════════
# APPROVAL HISTORY
# ══════════════════════════════════════════════════════════════════════════════

class ApprovalHistoryListView(CompanyMixin, ListView):
    template_name = 'workflow/approval_history.html'
    context_object_name = 'actions'
    paginate_by = 50

    def get_queryset(self):
        qs = WorkflowAction.objects.filter(
            company=self.company(),
        ).select_related(
            'instance__definition', 'instance__content_type',
            'step', 'actor', 'delegated_to'
        ).order_by('-acted_at')

        # Optional: filter to current user only
        if self.request.GET.get('mine') == '1':
            qs = qs.filter(actor=self.request.user)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['mine_only'] = self.request.GET.get('mine') == '1'
        return ctx


class WorkflowInstanceDetailView(CompanyMixin, DetailView):
    """Full audit timeline for one workflow instance."""
    template_name = 'workflow/instance_detail.html'
    context_object_name = 'instance'

    def get_object(self):
        return get_object_or_404(WorkflowInstance, pk=self.kwargs['pk'],
                                 company=self.company())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inst = self.object
        ctx['actions'] = inst.actions.select_related('actor', 'step', 'delegated_to').order_by('acted_at')
        ctx['steps'] = inst.definition.steps.order_by('step_order')
        ctx['escalation_logs'] = inst.escalation_logs.order_by('escalated_at')
        ctx['approvers'] = WorkflowEngine.get_pending_approvers(inst) if inst.current_step else []
        ctx['document'] = inst.related_object
        return ctx


# ══════════════════════════════════════════════════════════════════════════════
# DELEGATION MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class DelegatedApprovalsListView(CompanyMixin, ListView):
    template_name = 'workflow/delegations.html'
    context_object_name = 'delegations'

    def get_queryset(self):
        return ApprovalDelegation.objects.filter(
            company=self.company(),
            delegator=self.request.user,
        ).select_related('delegatee', 'workflow').order_by('-start_date')


class ApprovalDelegationCreateView(CompanyMixin, View):
    template_name = 'workflow/delegation_form.html'

    def get(self, request):
        from apps.authentication.models import User
        ctx = {
            'users': User.objects.filter(
                usercompany__company=self.company(), usercompany__is_active=True
            ).exclude(pk=request.user.pk),
            'workflows': WorkflowDefinition.objects.filter(
                company=self.company(), is_active=True
            ),
        }
        return render(request, self.template_name, ctx)

    def post(self, request):
        data = request.POST
        from apps.authentication.models import User
        delegatee = get_object_or_404(User, pk=data.get('delegatee'))
        workflow  = None
        if data.get('workflow'):
            workflow = WorkflowDefinition.objects.filter(pk=data['workflow']).first()

        ApprovalDelegation.objects.create(
            company=self.company(),
            delegator=request.user,
            delegatee=delegatee,
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            is_active=True,
            notes=data.get('notes', ''),
            workflow=workflow,
        )
        messages.success(request, f'Delegation to {delegatee.get_full_name()} created.')
        return redirect('workflow:delegations')


class ApprovalDelegationDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        delegation = get_object_or_404(ApprovalDelegation, pk=pk,
                                       company=self.company(), delegator=request.user)
        delegation.is_active = False
        delegation.save(update_fields=['is_active'])
        messages.success(request, 'Delegation deactivated.')
        return redirect('workflow:delegations')


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION TEMPLATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class NotificationTemplateView(CompanyMixin, View):
    """Create/update email or WhatsApp notification templates per workflow."""
    template_name = 'workflow/notification_templates.html'

    def get(self, request, workflow_pk):
        wf = get_object_or_404(WorkflowDefinition, pk=workflow_pk, company=self.company())
        return render(request, self.template_name, {
            'workflow': wf,
            'templates': wf.notification_templates.order_by('channel', 'event'),
            'channels': WorkflowNotificationTemplate.Channel.choices,
            'events': WorkflowNotificationTemplate.Event.choices,
            'steps': wf.steps.order_by('step_order'),
        })

    def post(self, request, workflow_pk):
        wf = get_object_or_404(WorkflowDefinition, pk=workflow_pk, company=self.company())
        data = request.POST

        step = None
        if data.get('step'):
            step = WorkflowStep.objects.filter(pk=data['step'], workflow=wf).first()

        WorkflowNotificationTemplate.objects.create(
            workflow=wf,
            step=step,
            channel=data.get('channel', 'email'),
            event=data.get('event', 'step_assigned'),
            subject=data.get('subject', ''),
            body=data.get('body', ''),
            is_active=True,
        )
        messages.success(request, 'Notification template saved.')
        return redirect('workflow:notification_templates', workflow_pk=workflow_pk)


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

class WorkflowDashboardView(CompanyMixin, TemplateView):
    template_name = 'workflow/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        user    = self.request.user

        # Pending for me
        all_pending = WorkflowInstance.objects.filter(
            company=company,
            status__in=['pending', 'in_progress', 'escalated'],
        ).select_related('definition', 'current_step', 'initiated_by')

        pending_for_me = []
        for inst in all_pending:
            approvers = WorkflowEngine.get_pending_approvers(inst)
            is_admin  = getattr(user, 'role', '') in ('super_admin', 'company_admin')
            if user in approvers or is_admin:
                pending_for_me.append(inst)

        ctx['pending_count']   = len(pending_for_me)
        ctx['pending_list']    = pending_for_me[:10]
        ctx['escalated_count'] = WorkflowInstance.objects.filter(
            company=company, status='escalated'
        ).count()
        ctx['my_actions']      = WorkflowAction.objects.filter(
            company=company, actor=user
        ).order_by('-acted_at')[:5]
        ctx['active_workflows'] = WorkflowDefinition.objects.filter(
            company=company, is_active=True
        ).annotate(
            in_progress=Count('workflowinstance',
                filter=Q(workflowinstance__status__in=['pending', 'in_progress']))
        )
        return ctx
