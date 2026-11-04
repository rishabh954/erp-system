"""
Enterprise Workflow — Views
Includes: Designer, Pending Approvals, History, Delegation, Visual Flow API
"""

import json
import logging
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView, View

from apps.workflow.engine import WorkflowEngine
from apps.workflow.models import (
    ApprovalDelegation,
    WorkflowAction,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNotificationTemplate,
    WorkflowStep,
)
from core.mixins import CompanyMixin
from core.tenancy import get_active_company

logger = logging.getLogger(__name__)


def _workflow_text(data, key, label, max_length):
    value = str(data.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    if len(value) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    return value


def _workflow_date(value, label):
    if value is None or not str(value).strip():
        raise ValueError(f"{label} is required.")
    try:
        result = date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Enter a valid {label.lower()}.") from None
    return result


def _workflow_decimal(value, label, *, optional=False, max_digits=15, places=2):
    raw = "" if value is None else str(value).strip()
    if not raw and optional:
        return None
    if not raw:
        raise ValueError(f"{label} is required.")
    try:
        result = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid number for {label.lower()}.") from None
    if (
        not result.is_finite()
        or result.as_tuple().exponent < -places
        or abs(result) >= Decimal(10) ** (max_digits - places)
    ):
        raise ValueError(f"Enter a valid number for {label.lower()}.")
    if result < 0:
        raise ValueError(f"{label} cannot be negative.")
    return result


def _workflow_company_user(value, company, label):
    from apps.authentication.models import User

    if value is None or not str(value).strip():
        return None
    try:
        user = User.objects.filter(
            pk=value,
            is_active=True,
            usercompany__company=company,
            usercompany__is_active=True,
        ).first()
    except (ValidationError, TypeError, ValueError):
        user = None
    if user is None:
        raise ValueError(f"Select an active {label} from this company.")
    return user


def _workflow_boolean(value):
    return str(value or "").lower() in {"on", "true", "1", "yes"}


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW DEFINITION MANAGEMENT (Designer)
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowListView(CompanyMixin, ListView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    template_name = "workflow/workflow_list.html"
    context_object_name = "workflows"

    def get_queryset(self):
        return (
            WorkflowDefinition.objects.filter(company=self.company(), is_deleted=False)
            .annotate(step_count=Count("steps"))
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["trigger_events"] = WorkflowDefinition.TriggerEvent.choices
        return ctx


class WorkflowCreateView(CompanyMixin, View):
    required_permission = "workflow.create"
    template_name = "workflow/workflow_form.html"

    def get(self, request):
        from apps.authentication.models import User
        from apps.company.models import Department

        ctx = {
            "trigger_events": WorkflowDefinition.TriggerEvent.choices,
            "step_types": WorkflowStep.StepType.choices,
            "approver_types": WorkflowStep.ApproverType.choices,
            "escalation_actions": WorkflowStep.EscalationAction.choices,
            "users": User.objects.filter(
                usercompany__company=self.company(), usercompany__is_active=True
            ),
            "departments": Department.objects.filter(company=self.company()),
        }
        return render(request, self.template_name, ctx)

    @transaction.atomic
    def post(self, request):
        data = request.POST
        try:
            company = self.company()
            name = _workflow_text(data, "name", "Workflow name", 200)
            trigger_model = str(
                data.get("trigger_model") or data.get("content_type_model") or ""
            ).strip()
            if not trigger_model or len(trigger_model) > 100:
                raise ValueError("A valid trigger model is required.")
            trigger_event = str(
                data.get("trigger_event", WorkflowDefinition.TriggerEvent.ON_SUBMIT)
            ).strip()
            if trigger_event not in WorkflowDefinition.TriggerEvent.values:
                raise ValueError("Select a valid workflow trigger event.")
            if len(str(data.get("description", ""))) > 10000:
                raise ValueError("Workflow description is too long.")
            wf = WorkflowDefinition.objects.create(
                company=company,
                name=name,
                description=data.get("description", "").strip(),
                trigger_model=trigger_model,
                trigger_event=trigger_event,
                notify_email=_workflow_boolean(data.get("notify_email")),
                notify_whatsapp=_workflow_boolean(data.get("notify_whatsapp")),
                notify_in_app=_workflow_boolean(data.get("notify_in_app", "on")),
                is_active=True,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("workflow:list")
        messages.success(
            request, f"Workflow '{wf.name}' created. Now add approval steps."
        )
        return redirect("workflow:designer", pk=wf.pk)


class WorkflowDesignerView(CompanyMixin, DetailView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    """Visual workflow designer — renders the canvas UI."""

    template_name = "workflow/designer.html"
    context_object_name = "workflow"

    def get_object(self):
        return get_object_or_404(
            WorkflowDefinition, pk=self.kwargs["pk"], company=self.company()
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        wf = self.object
        from apps.authentication.models import User
        from apps.company.models import Department

        ctx.update(
            {
                "steps": wf.steps.order_by("step_order"),
                "step_types": WorkflowStep.StepType.choices,
                "approver_types": WorkflowStep.ApproverType.choices,
                "escalation_actions": WorkflowStep.EscalationAction.choices,
                "users": User.objects.filter(
                    usercompany__company=self.company(), usercompany__is_active=True
                ),
                "departments": Department.objects.filter(company=self.company()),
                "notification_templates": wf.notification_templates.all(),
                "steps_json": json.dumps(
                    [
                        {
                            "id": str(s.id),
                            "name": s.name,
                            "step_order": s.step_order,
                            "step_type": s.step_type,
                            "approver_type": s.approver_type,
                            "approver_user": (
                                str(s.approver_user_id) if s.approver_user else None
                            ),
                            "approver_role": s.approver_role,
                            "escalation_enabled": s.escalation_enabled,
                            "escalation_hours": s.escalation_hours,
                            "min_amount": float(s.min_amount) if s.min_amount else None,
                            "max_amount": float(s.max_amount) if s.max_amount else None,
                            "x": s.canvas_x,
                            "y": s.canvas_y,
                        }
                        for s in wf.steps.order_by("step_order")
                    ]
                ),
            }
        )
        return ctx


class WorkflowDesignerSaveAPI(CompanyMixin, View):
    required_permission = "workflow.update"
    """AJAX endpoint: saves the visual designer canvas layout."""

    @transaction.atomic
    def post(self, request, pk):
        wf = get_object_or_404(WorkflowDefinition, pk=pk, company=self.company())
        try:
            data = json.loads(request.body)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            layout = data.get("layout", {})
            nodes = data.get("nodes", [])
            if not isinstance(layout, dict) or not isinstance(nodes, list):
                raise ValueError("Layout must be an object and nodes must be a list.")
            positions = []
            seen = set()
            existing = {str(step.pk): step for step in wf.steps.all()}
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValueError("Each node must be an object.")
                try:
                    step_id = str(uuid.UUID(str(node["id"])))
                except (KeyError, TypeError, ValueError):
                    raise ValueError("Each node must reference a valid workflow step.") from None
                if step_id not in existing or step_id in seen:
                    raise ValueError("A node references an invalid or repeated step.")
                seen.add(step_id)
                coords = []
                for key in ("x", "y"):
                    value = node.get(key, 0)
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise ValueError("Step positions must be whole numbers.")
                    coords.append(value)
                positions.append((existing[step_id], coords[0], coords[1]))
            wf.canvas_layout = layout
            wf.save(update_fields=["canvas_layout"])
            for step, x, y in positions:
                step.canvas_x = x
                step.canvas_y = y
                step.save(update_fields=["canvas_x", "canvas_y"])

            return JsonResponse({"status": "ok"})
        except (ValueError, json.JSONDecodeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("Workflow designer layout save failed")
            return JsonResponse({"error": "Unable to save workflow layout."}, status=400)


class WorkflowVisualFlowAPI(CompanyMixin, View):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    """Returns the workflow as a JSON graph for front-end rendering."""

    def get(self, request, pk):
        wf = get_object_or_404(WorkflowDefinition, pk=pk, company=self.company())
        steps = list(wf.steps.order_by("step_order"))

        nodes = []
        edges = []

        # Start node
        nodes.append(
            {"id": "start", "label": "Start", "type": "start", "x": 100, "y": 200}
        )

        for i, step in enumerate(steps):
            node_id = str(step.id)
            nodes.append(
                {
                    "id": node_id,
                    "label": step.name,
                    "type": step.step_type,
                    "approver_type": step.approver_type,
                    "escalation_enabled": step.escalation_enabled,
                    "escalation_hours": step.escalation_hours,
                    "x": step.canvas_x or (250 + i * 220),
                    "y": step.canvas_y or 200,
                }
            )

            # Edge from previous node
            if i == 0:
                edges.append({"from": "start", "to": node_id, "label": ""})
            else:
                edges.append(
                    {"from": str(steps[i - 1].id), "to": node_id, "label": "Next"}
                )

            # Conditional branches
            if step.step_type == WorkflowStep.StepType.CONDITION:
                for rule in step.condition_rules or []:
                    # Find target step by order
                    target_order = rule.get("next_step_order")
                    target_step = next(
                        (s for s in steps if s.step_order == target_order), None
                    )
                    if target_step:
                        edges.append(
                            {
                                "from": node_id,
                                "to": str(target_step.id),
                                "label": f"{rule.get('field')} {rule.get('operator')} {rule.get('value')}",
                                "type": "condition",
                            }
                        )

        # End node
        nodes.append(
            {
                "id": "end",
                "label": "End",
                "type": "end",
                "x": 250 + len(steps) * 220,
                "y": 200,
            }
        )
        if steps:
            edges.append({"from": str(steps[-1].id), "to": "end", "label": "Complete"})
        else:
            edges.append({"from": "start", "to": "end", "label": "Complete"})

        return JsonResponse(
            {
                "nodes": nodes,
                "edges": edges,
                "workflow": {
                    "id": str(wf.pk),
                    "name": wf.name,
                    "trigger_model": wf.trigger_model,
                },
            }
        )


# ══════════════════════════════════════════════════════════════════════════════
# STEP MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════


class StepCreateView(CompanyMixin, View):
    required_permission = "workflow.create"

    @transaction.atomic
    def post(self, request, workflow_pk):
        wf = get_object_or_404(
            WorkflowDefinition, pk=workflow_pk, company=self.company()
        )
        data = request.POST
        try:
            name = _workflow_text(data, "name", "Step name", 200)
            step_type = str(data.get("step_type", WorkflowStep.StepType.APPROVAL)).strip()
            approver_type = str(
                data.get("approver_type", WorkflowStep.ApproverType.USER)
            ).strip()
            escalation_action = str(
                data.get("escalation_action", WorkflowStep.EscalationAction.NOTIFY)
            ).strip()
            if step_type not in WorkflowStep.StepType.values:
                raise ValueError("Select a valid step type.")
            if approver_type not in WorkflowStep.ApproverType.values:
                raise ValueError("Select a valid approver type.")
            if escalation_action not in WorkflowStep.EscalationAction.values:
                raise ValueError("Select a valid escalation action.")

            min_amt = _workflow_decimal(
                data.get("min_amount"), "Minimum amount", optional=True
            )
            max_amt = _workflow_decimal(
                data.get("max_amount"), "Maximum amount", optional=True
            )
            if min_amt is not None and max_amt is not None and min_amt > max_amt:
                raise ValueError("Minimum amount cannot exceed maximum amount.")
            try:
                escalation_hours = int(data.get("escalation_hours") or 24)
                if str(data.get("escalation_hours") or 24).strip() != str(
                    escalation_hours
                ) or not 1 <= escalation_hours <= 2147483647:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(
                    "Escalation hours must be a whole number greater than zero."
                ) from None

            approver_user = _workflow_company_user(
                data.get("approver_user"), self.company(), "approver"
            )
            escalation_to = _workflow_company_user(
                data.get("escalation_to"), self.company(), "escalation assignee"
            )
            if (
                step_type == WorkflowStep.StepType.APPROVAL
                and approver_type == WorkflowStep.ApproverType.USER
                and approver_user is None
            ):
                raise ValueError("Select an approver for this approval step.")
            if (
                step_type == WorkflowStep.StepType.APPROVAL
                and approver_type == WorkflowStep.ApproverType.ROLE
                and not str(data.get("approver_role", "")).strip()
            ):
                raise ValueError("Approver role is required.")
            if (
                step_type == WorkflowStep.StepType.APPROVAL
                and approver_type == WorkflowStep.ApproverType.DYNAMIC
                and not str(data.get("approver_field", "")).strip()
            ):
                raise ValueError("Approver field is required.")
            escalation_enabled = _workflow_boolean(data.get("escalation_enabled"))
            if (
                escalation_enabled
                and escalation_action == WorkflowStep.EscalationAction.REASSIGN
                and escalation_to is None
            ):
                raise ValueError("Select a user for escalation reassignment.")
            last_order = wf.steps.count()
            step = WorkflowStep.objects.create(
                workflow=wf,
                name=name,
                step_order=last_order + 1,
                step_type=step_type,
                approver_type=approver_type,
                approver_user=approver_user,
                approver_role=str(data.get("approver_role", "")).strip(),
                approver_field=str(data.get("approver_field", "")).strip(),
                min_amount=min_amt,
                max_amount=max_amt,
                escalation_enabled=escalation_enabled,
                escalation_hours=escalation_hours,
                escalation_action=escalation_action,
                escalation_to=escalation_to,
                is_required=_workflow_boolean(data.get("is_required", "on")),
            )
        except ValueError as exc:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect("workflow:designer", pk=workflow_pk)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {"status": "ok", "step_id": str(step.id), "step_order": step.step_order}
            )

        messages.success(request, f"Step '{step.name}' added.")
        return redirect("workflow:designer", pk=workflow_pk)


class StepDeleteView(CompanyMixin, View):
    required_permission = "workflow.delete"
    def post(self, request, pk):
        step = get_object_or_404(WorkflowStep, pk=pk, workflow__company=self.company())
        wf_pk = step.workflow_id
        step.delete()
        messages.success(request, "Step removed.")
        return redirect("workflow:designer", pk=wf_pk)


class StepReorderView(CompanyMixin, View):
    required_permission = "workflow.update"
    """AJAX: reorder steps by posting a list of IDs."""

    @transaction.atomic
    def post(self, request, workflow_pk):
        try:
            wf = get_object_or_404(
                WorkflowDefinition, pk=workflow_pk, company=self.company()
            )
            payload = json.loads(request.body)
            ids = payload.get("ids") if isinstance(payload, dict) else None
            if not isinstance(ids, list):
                raise ValueError("Step IDs must be provided as a list.")
            try:
                normalized = [str(uuid.UUID(str(step_id))) for step_id in ids]
            except (TypeError, ValueError):
                raise ValueError("All step IDs must be valid.") from None
            existing = {str(step_id) for step_id in wf.steps.values_list("pk", flat=True)}
            if len(normalized) != len(set(normalized)) or set(normalized) != existing:
                raise ValueError("Provide each step in this workflow exactly once.")
            steps = {str(step.pk): step for step in wf.steps.all()}
            for order, step_id in enumerate(normalized, 1):
                step = steps[step_id]
                step.step_order = order
                step.save(update_fields=["step_order"])
            return JsonResponse({"status": "ok"})
        except (ValueError, json.JSONDecodeError) as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("Workflow step reorder failed")
            return JsonResponse({"error": "Unable to reorder workflow steps."}, status=400)


# ══════════════════════════════════════════════════════════════════════════════
# PENDING APPROVALS
# ══════════════════════════════════════════════════════════════════════════════


class PendingApprovalsListView(CompanyMixin, ListView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    template_name = "workflow/pending_approvals.html"
    context_object_name = "instances"

    def get_queryset(self):
        company = self.company()
        all_instances = WorkflowInstance.objects.filter(
            company=company,
            status__in=[
                WorkflowInstance.Status.PENDING,
                WorkflowInstance.Status.IN_PROGRESS,
                WorkflowInstance.Status.ESCALATED,
            ],
        ).select_related("definition", "current_step", "initiated_by", "content_type")

        result = []
        for inst in all_instances:
            approvers = WorkflowEngine.get_pending_approvers(inst)
            role = self.request.user.get_role_for_company(company)
            is_admin = self.request.user.is_superuser or role in (
                "super_admin",
                "company_admin",
            )
            if self.request.user in approvers or is_admin:
                result.append(inst)
        return result

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_pending"] = len(ctx["instances"])
        ctx["escalated_count"] = sum(
            1 for i in ctx["instances"] if i.status == "escalated"
        )
        return ctx


class WorkflowActionAPIView(LoginRequiredMixin, View):
    required_permission = "workflow.approve"
    """Handle approve / reject / delegate / return actions."""

    def post(self, request, instance_id):
        action = request.POST.get("action")
        comment = request.POST.get("comment", "")
        delegatee_id = request.POST.get("delegatee_id")

        try:
            company = get_active_company(request)
            instance = get_object_or_404(
                WorkflowInstance, pk=instance_id, company=company
            )

            if action == "approve":
                WorkflowEngine.approve(instance, request.user, comment)
                messages.success(request, "Workflow step approved successfully.")

            elif action == "reject":
                WorkflowEngine.reject(instance, request.user, comment)
                messages.warning(request, "Workflow step rejected.")

            elif action == "delegate":
                from apps.authentication.models import User

                delegatee = get_object_or_404(
                    User.objects.filter(
                        usercompany__company=company,
                        usercompany__is_active=True,
                        is_active=True,
                    ),
                    pk=delegatee_id,
                )
                WorkflowEngine.delegate(instance, request.user, delegatee, comment)
                messages.success(
                    request, f"Approval delegated to {delegatee.get_full_name()}."
                )

            elif action == "return":
                WorkflowEngine.return_for_clarification(instance, request.user, comment)
                messages.info(request, "Returned to submitter for clarification.")

            else:
                return JsonResponse({"error": "Invalid action"}, status=400)

        except (PermissionError, ValueError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")

        return redirect(
            request.META.get("HTTP_REFERER", reverse("workflow:pending_approvals"))
        )


# ══════════════════════════════════════════════════════════════════════════════
# APPROVAL HISTORY
# ══════════════════════════════════════════════════════════════════════════════


class ApprovalHistoryListView(CompanyMixin, ListView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    template_name = "workflow/approval_history.html"
    context_object_name = "actions"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            WorkflowAction.objects.filter(
                company=self.company(),
            )
            .select_related(
                "instance__definition",
                "instance__content_type",
                "step",
                "actor",
                "delegated_to",
            )
            .order_by("-acted_at")
        )

        # Optional: filter to current user only
        if self.request.GET.get("mine") == "1":
            qs = qs.filter(actor=self.request.user)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mine_only"] = self.request.GET.get("mine") == "1"
        return ctx


class WorkflowInstanceDetailView(CompanyMixin, DetailView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    """Full audit timeline for one workflow instance."""

    template_name = "workflow/instance_detail.html"
    context_object_name = "instance"

    def get_object(self):
        return get_object_or_404(
            WorkflowInstance, pk=self.kwargs["pk"], company=self.company()
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inst = self.object
        ctx["actions"] = inst.actions.select_related(
            "actor", "step", "delegated_to"
        ).order_by("acted_at")
        ctx["steps"] = inst.definition.steps.order_by("step_order")
        ctx["escalation_logs"] = inst.escalation_logs.order_by("escalated_at")
        ctx["approvers"] = (
            WorkflowEngine.get_pending_approvers(inst) if inst.current_step else []
        )
        ctx["document"] = inst.related_object
        return ctx


# ══════════════════════════════════════════════════════════════════════════════
# DELEGATION MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════


class DelegatedApprovalsListView(CompanyMixin, ListView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    template_name = "workflow/delegations.html"
    context_object_name = "delegations"

    def get_queryset(self):
        return (
            ApprovalDelegation.objects.filter(
                company=self.company(),
                delegator=self.request.user,
            )
            .select_related("delegatee", "workflow")
            .order_by("-start_date")
        )


class ApprovalDelegationCreateView(CompanyMixin, View):
    required_permission = "workflow.create"
    template_name = "workflow/delegation_form.html"

    def get(self, request):
        from apps.authentication.models import User

        ctx = {
            "users": User.objects.filter(
                usercompany__company=self.company(), usercompany__is_active=True
            ).exclude(pk=request.user.pk),
            "workflows": WorkflowDefinition.objects.filter(
                company=self.company(), is_active=True
            ),
        }
        return render(request, self.template_name, ctx)

    @transaction.atomic
    def post(self, request):
        data = request.POST
        try:
            company = self.company()
            delegatee = _workflow_company_user(
                data.get("delegatee"), company, "delegatee"
            )
            if delegatee is None:
                raise ValueError("A delegatee is required.")
            if delegatee.pk == request.user.pk:
                raise ValueError("You cannot delegate approvals to yourself.")
            start_date = _workflow_date(data.get("start_date"), "Start date")
            end_date = _workflow_date(data.get("end_date"), "End date")
            if end_date < start_date:
                raise ValueError("End date cannot be before start date.")
            workflow = None
            workflow_id = str(data.get("workflow", "") or "").strip()
            if workflow_id:
                try:
                    workflow = WorkflowDefinition.objects.filter(
                        pk=workflow_id, company=company, is_active=True
                    ).first()
                except (ValidationError, TypeError, ValueError):
                    workflow = None
                if workflow is None:
                    raise ValueError("Select an active workflow for this company.")
            notes = str(data.get("notes", "") or "")
            if len(notes) > 2000:
                raise ValueError("Delegation notes must be 2000 characters or fewer.")
            ApprovalDelegation.objects.create(
                company=company,
                delegator=request.user,
                delegatee=delegatee,
                start_date=start_date,
                end_date=end_date,
                is_active=True,
                notes=notes.strip(),
                workflow=workflow,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("workflow:delegation_create")
        messages.success(request, f"Delegation to {delegatee.get_full_name()} created.")
        return redirect("workflow:delegations")


class ApprovalDelegationDeleteView(CompanyMixin, View):
    required_permission = "workflow.delete"
    def post(self, request, pk):
        delegation = get_object_or_404(
            ApprovalDelegation, pk=pk, company=self.company(), delegator=request.user
        )
        delegation.is_active = False
        delegation.save(update_fields=["is_active"])
        messages.success(request, "Delegation deactivated.")
        return redirect("workflow:delegations")


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION TEMPLATE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════


class NotificationTemplateView(CompanyMixin, View):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    """Create/update email or WhatsApp notification templates per workflow."""

    template_name = "workflow/notification_templates.html"

    def get(self, request, workflow_pk):
        wf = get_object_or_404(
            WorkflowDefinition, pk=workflow_pk, company=self.company()
        )
        return render(
            request,
            self.template_name,
            {
                "workflow": wf,
                "templates": wf.notification_templates.order_by("channel", "event"),
                "channels": WorkflowNotificationTemplate.Channel.choices,
                "events": WorkflowNotificationTemplate.Event.choices,
                "steps": wf.steps.order_by("step_order"),
            },
        )

    def post(self, request, workflow_pk):
        wf = get_object_or_404(
            WorkflowDefinition, pk=workflow_pk, company=self.company()
        )
        data = request.POST

        step = None
        if data.get("step"):
            step = WorkflowStep.objects.filter(pk=data["step"], workflow=wf).first()

        WorkflowNotificationTemplate.objects.create(
            workflow=wf,
            step=step,
            channel=data.get("channel", "email"),
            event=data.get("event", "step_assigned"),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            is_active=True,
        )
        messages.success(request, "Notification template saved.")
        return redirect("workflow:notification_templates", workflow_pk=workflow_pk)


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowDashboardView(CompanyMixin, TemplateView):
    required_permission = "workflow.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "workflow.create"
            elif request.method in ["PUT", "PATCH"]:
                return "workflow.update"
            elif request.method == "DELETE":
                return "workflow.delete"
        return self.required_permission
    template_name = "workflow/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        user = self.request.user

        # Pending for me
        all_pending = WorkflowInstance.objects.filter(
            company=company,
            status__in=["pending", "in_progress", "escalated"],
        ).select_related("definition", "current_step", "initiated_by")

        pending_for_me = []
        for inst in all_pending:
            approvers = WorkflowEngine.get_pending_approvers(inst)
            is_admin = getattr(user, "role", "") in ("super_admin", "company_admin")
            if user in approvers or is_admin:
                pending_for_me.append(inst)

        ctx["pending_count"] = len(pending_for_me)
        ctx["pending_list"] = pending_for_me[:10]
        ctx["escalated_count"] = WorkflowInstance.objects.filter(
            company=company, status="escalated"
        ).count()
        ctx["my_actions"] = WorkflowAction.objects.filter(
            company=company, actor=user
        ).order_by("-acted_at")[:5]
        ctx["active_workflows"] = WorkflowDefinition.objects.filter(
            company=company, is_active=True
        ).annotate(
            in_progress=Count(
                "workflowinstance",
                filter=Q(workflowinstance__status__in=["pending", "in_progress"]),
            )
        )
        return ctx
