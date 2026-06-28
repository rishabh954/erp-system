"""
Enterprise Workflow Engine
Handles: Unlimited Approval Levels, Conditional Routing, Escalation,
         Delegation, Email Notifications, WhatsApp Notifications
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template

from apps.workflow.models import (
    WorkflowDefinition, WorkflowStep, WorkflowInstance,
    WorkflowAction, ApprovalDelegation, WorkflowNotificationTemplate,
    WorkflowEscalationLog
)
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Central workflow orchestrator.
    Usage:
        WorkflowEngine.trigger(document, 'on_submit', request.user)
        WorkflowEngine.approve(instance, request.user, comment='LGTM')
        WorkflowEngine.reject(instance, request.user, comment='Invalid amount')
        WorkflowEngine.delegate(instance, request.user, delegatee, comment='On leave')
    """

    # ──────────────────────────────────────────────────────────────────────────
    # TRIGGER
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def trigger(cls, document, trigger_event: str, user):
        """Starts a workflow for a document if a matching definition is found."""
        model_name = document.__class__.__name__
        company    = getattr(document, 'company', getattr(user, 'primary_company', None))

        if not company:
            logger.warning(f"WorkflowEngine.trigger: No company for {document!r}")
            return None

        definitions = WorkflowDefinition.objects.filter(
            company=company,
            trigger_model=model_name,
            trigger_event=trigger_event,
            is_active=True,
        )

        matched = None
        for defn in definitions:
            if cls._check_definition_conditions(defn, document):
                matched = defn
                break

        if not matched:
            return None

        content_type = ContentType.objects.get_for_model(document)

        # Idempotency — don't double-start
        if WorkflowInstance.objects.filter(
            content_type=content_type,
            object_id=str(document.pk),
            status__in=[WorkflowInstance.Status.PENDING, WorkflowInstance.Status.IN_PROGRESS],
        ).exists():
            return None

        instance = WorkflowInstance.objects.create(
            company=company,
            definition=matched,
            content_type=content_type,
            object_id=str(document.pk),
            status=WorkflowInstance.Status.PENDING,
            initiated_by=user,
        )

        cls._advance_to_next_step(instance, document, current_step_order=-1)
        return instance

    # ──────────────────────────────────────────────────────────────────────────
    # APPROVE
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def approve(cls, instance, user, comment: str = ''):
        if instance.status not in [WorkflowInstance.Status.PENDING,
                                   WorkflowInstance.Status.IN_PROGRESS,
                                   WorkflowInstance.Status.ESCALATED]:
            raise ValueError("Workflow is not in an approvable state.")

        approvers = cls.get_pending_approvers(instance)
        is_admin  = getattr(user, 'role', '') in ('super_admin', 'company_admin')

        if user not in approvers and not is_admin:
            raise PermissionError("You are not authorised to approve this step.")

        WorkflowAction.objects.create(
            company=instance.company,
            instance=instance,
            step=instance.current_step,
            actor=user,
            action=WorkflowAction.Action.APPROVED,
            comment=comment,
        )

        document = instance.related_object
        cls._send_notifications(instance, document,
                                event=WorkflowNotificationTemplate.Event.APPROVED,
                                recipients=[instance.initiated_by])

        cls._advance_to_next_step(
            instance, document,
            current_step_order=instance.current_step.step_order
        )
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # REJECT
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def reject(cls, instance, user, comment: str = ''):
        if instance.status not in [WorkflowInstance.Status.PENDING,
                                   WorkflowInstance.Status.IN_PROGRESS,
                                   WorkflowInstance.Status.ESCALATED]:
            raise ValueError("Workflow is not in an approvable state.")

        approvers = cls.get_pending_approvers(instance)
        is_admin  = getattr(user, 'role', '') in ('super_admin', 'company_admin')

        if user not in approvers and not is_admin:
            raise PermissionError("You are not authorised to reject this step.")

        WorkflowAction.objects.create(
            company=instance.company,
            instance=instance,
            step=instance.current_step,
            actor=user,
            action=WorkflowAction.Action.REJECTED,
            comment=comment,
        )

        document = instance.related_object
        cls._mark_completed(instance, document, WorkflowInstance.Status.REJECTED)
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # DELEGATE
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def delegate(cls, instance, user, delegatee, comment: str = ''):
        """Delegate this step from `user` to `delegatee`."""
        approvers = cls.get_pending_approvers(instance)
        if user not in approvers:
            raise PermissionError("Only pending approvers can delegate.")

        WorkflowAction.objects.create(
            company=instance.company,
            instance=instance,
            step=instance.current_step,
            actor=user,
            action=WorkflowAction.Action.DELEGATED,
            comment=comment,
            delegated_to=delegatee,
        )

        # Update the step's approver_user temporarily for this instance
        # We handle this at the engine level: redirect next get_pending_approvers to delegatee
        # Create a delegation record for today → today
        today = timezone.now().date()
        ApprovalDelegation.objects.create(
            company=instance.company,
            delegator=user,
            delegatee=delegatee,
            start_date=today,
            end_date=today + timedelta(days=365),
            is_active=True,
            workflow=instance.definition,
            notes=comment,
        )

        document = instance.related_object
        cls._send_notifications(
            instance, document,
            event=WorkflowNotificationTemplate.Event.DELEGATED,
            recipients=[delegatee],
        )
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # RETURN FOR CLARIFICATION
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def return_for_clarification(cls, instance, user, comment: str = ''):
        WorkflowAction.objects.create(
            company=instance.company,
            instance=instance,
            step=instance.current_step,
            actor=user,
            action=WorkflowAction.Action.RETURNED,
            comment=comment,
        )
        # Notify the initiator
        document = instance.related_object
        cls._send_notifications(
            instance, document,
            event=WorkflowNotificationTemplate.Event.REJECTED,
            recipients=[instance.initiated_by],
            extra_context={'action_label': 'Returned for Clarification'},
        )
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # ESCALATION  (called by Celery Beat task)
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def check_and_escalate(cls):
        """
        Scans all in-progress instances whose current step has escalation enabled
        and has exceeded the escalation_hours SLA.
        Called periodically by a Celery Beat task.
        """
        now = timezone.now()
        instances = WorkflowInstance.objects.filter(
            status__in=[WorkflowInstance.Status.IN_PROGRESS, WorkflowInstance.Status.ESCALATED],
            current_step__escalation_enabled=True,
            current_step_started_at__isnull=False,
        ).select_related('current_step', 'definition', 'initiated_by', 'company')

        for inst in instances:
            step = inst.current_step
            deadline = inst.current_step_started_at + timedelta(hours=step.escalation_hours)

            if now < deadline:
                continue   # Not yet overdue

            already_escalated = WorkflowEscalationLog.objects.filter(
                instance=inst, step=step
            ).exists()

            action = step.escalation_action

            if action == WorkflowStep.EscalationAction.NOTIFY:
                if not already_escalated:
                    approvers = cls.get_pending_approvers(inst)
                    document = inst.related_object
                    cls._send_notifications(
                        inst, document,
                        event=WorkflowNotificationTemplate.Event.ESCALATED,
                        recipients=approvers,
                    )
                    WorkflowEscalationLog.objects.create(
                        instance=inst, step=step,
                        action_taken='notify',
                        notes='Escalation reminder sent.',
                    )

            elif action == WorkflowStep.EscalationAction.REASSIGN and step.escalation_to:
                WorkflowEscalationLog.objects.create(
                    instance=inst, step=step,
                    action_taken='reassign',
                    escalated_to=step.escalation_to,
                )
                inst.status = WorkflowInstance.Status.ESCALATED
                inst.save(update_fields=['status'])
                document = inst.related_object
                cls._send_notifications(
                    inst, document,
                    event=WorkflowNotificationTemplate.Event.ESCALATED,
                    recipients=[step.escalation_to],
                )

            elif action == WorkflowStep.EscalationAction.AUTO_APPROVE:
                WorkflowEscalationLog.objects.create(
                    instance=inst, step=step,
                    action_taken='auto_approve',
                    notes='Auto-approved due to SLA breach.',
                )
                document = inst.related_object
                WorkflowAction.objects.create(
                    company=inst.company,
                    instance=inst,
                    step=step,
                    actor=inst.initiated_by,  # system actor
                    action=WorkflowAction.Action.APPROVED,
                    comment='Auto-approved: SLA escalation threshold exceeded.',
                )
                cls._advance_to_next_step(inst, document, current_step_order=step.step_order)

            elif action == WorkflowStep.EscalationAction.AUTO_REJECT:
                WorkflowEscalationLog.objects.create(
                    instance=inst, step=step,
                    action_taken='auto_reject',
                    notes='Auto-rejected due to SLA breach.',
                )
                document = inst.related_object
                WorkflowAction.objects.create(
                    company=inst.company,
                    instance=inst,
                    step=step,
                    actor=inst.initiated_by,
                    action=WorkflowAction.Action.REJECTED,
                    comment='Auto-rejected: SLA escalation threshold exceeded.',
                )
                cls._mark_completed(inst, document, WorkflowInstance.Status.REJECTED)

    # ──────────────────────────────────────────────────────────────────────────
    # GET PENDING APPROVERS
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_pending_approvers(cls, instance):
        """Returns current approvers respecting delegation."""
        if not instance.current_step:
            return []

        step = instance.current_step
        approvers = set()

        if step.approver_type == WorkflowStep.ApproverType.USER and step.approver_user:
            approvers.add(step.approver_user)

        elif step.approver_type == WorkflowStep.ApproverType.ROLE and step.approver_role:
            from apps.authentication.models import User
            approvers.update(User.objects.filter(
                role=step.approver_role,
                usercompany__company=instance.company,
                usercompany__is_active=True,
            ))

        elif step.approver_type == WorkflowStep.ApproverType.MANAGER:
            emp = getattr(instance.initiated_by, 'employee_profile', None)
            if emp:
                manager_emp = getattr(emp, 'manager', None)
                if manager_emp and getattr(manager_emp, 'user', None):
                    approvers.add(manager_emp.user)

        elif step.approver_type == WorkflowStep.ApproverType.DEPARTMENT_HEAD:
            document = instance.related_object
            dept = getattr(document, 'department', None) or getattr(
                getattr(instance.initiated_by, 'employee_profile', None), 'department', None
            )
            if dept:
                from apps.authentication.models import User
                approvers.update(User.objects.filter(
                    role='department_head',
                    usercompany__company=instance.company,
                    usercompany__is_active=True,
                ))

        elif step.approver_type == WorkflowStep.ApproverType.DYNAMIC and step.approver_field:
            document = instance.related_object
            approver_obj = document
            for attr in step.approver_field.split('__'):
                approver_obj = getattr(approver_obj, attr, None)
                if approver_obj is None:
                    break
            if approver_obj and hasattr(approver_obj, 'pk'):
                from apps.authentication.models import User
                if isinstance(approver_obj, User):
                    approvers.add(approver_obj)

        # Resolve active delegations
        today = timezone.now().date()
        final_approvers = set()
        for approver in approvers:
            delegation = ApprovalDelegation.objects.filter(
                delegator=approver,
                is_active=True,
                start_date__lte=today,
                end_date__gte=today,
            ).filter(
                models.Q(workflow__isnull=True) | models.Q(workflow=instance.definition)
            ).first()

            if delegation:
                final_approvers.add(delegation.delegatee)
            else:
                final_approvers.add(approver)

        return list(final_approvers)

    # ──────────────────────────────────────────────────────────────────────────
    # INTERNAL: ADVANCE TO NEXT STEP (supports conditional branching)
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _advance_to_next_step(cls, instance, document, current_step_order=-1):
        steps = instance.definition.steps.filter(
            step_order__gt=current_step_order
        ).order_by('step_order')

        amount = cls._get_amount(document)
        doc_dept_id = cls._get_dept_id(document, instance)

        next_step = None
        for step in steps:
            # ── Amount filter ─────────────────────────────────────────────
            if step.min_amount is not None and amount < step.min_amount:
                continue
            if step.max_amount is not None and amount > step.max_amount:
                continue

            # ── Department filter ─────────────────────────────────────────
            if step.department_id and step.department_id != doc_dept_id:
                continue

            # ── Condition step: evaluate rules, find target step ──────────
            if step.step_type == WorkflowStep.StepType.CONDITION:
                target_order = cls._evaluate_condition_rules(step, document, amount)
                if target_order is not None:
                    cls._advance_to_next_step(instance, document, current_step_order=target_order - 1)
                    return
                continue  # condition didn't match — skip

            next_step = step
            break

        if next_step:
            instance.current_step = next_step
            instance.status = WorkflowInstance.Status.IN_PROGRESS
            instance.current_step_started_at = timezone.now()
            instance.save()

            # Notify approvers
            approvers = cls.get_pending_approvers(instance)
            cls._send_notifications(
                instance, document,
                event=WorkflowNotificationTemplate.Event.STEP_ASSIGNED,
                recipients=approvers,
            )
        else:
            cls._mark_completed(instance, document, WorkflowInstance.Status.APPROVED)

    @classmethod
    def _evaluate_condition_rules(cls, step, document, amount):
        """
        Evaluate step.condition_rules and return next_step_order to jump to,
        or None if no rule matched.
        """
        for rule in step.condition_rules:
            field    = rule.get('field', '')
            operator = rule.get('operator', 'eq')
            value    = rule.get('value')
            next_ord = rule.get('next_step_order')

            # Get field value from document
            doc_val = document
            for part in field.split('__'):
                doc_val = getattr(doc_val, part, None)
                if doc_val is None:
                    break

            try:
                if operator == 'eq'  and doc_val == value:     return next_ord
                if operator == 'neq' and doc_val != value:     return next_ord
                if operator == 'gt'  and float(doc_val or 0) >  float(value): return next_ord
                if operator == 'gte' and float(doc_val or 0) >= float(value): return next_ord
                if operator == 'lt'  and float(doc_val or 0) <  float(value): return next_ord
                if operator == 'lte' and float(doc_val or 0) <= float(value): return next_ord
                if operator == 'in'  and doc_val in (value if isinstance(value, list) else [value]): return next_ord
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _mark_completed(cls, instance, document, status):
        instance.status      = status
        instance.current_step = None
        instance.completed_at = timezone.now()
        instance.save()

        if hasattr(document, 'status'):
            if status == WorkflowInstance.Status.APPROVED:
                if document.status in ('draft', 'pending', 'submitted'):
                    document.status = 'approved'
            elif status == WorkflowInstance.Status.REJECTED:
                document.status = 'rejected'
            try:
                document.save(update_fields=['status'])
            except Exception:
                pass

        event = (WorkflowNotificationTemplate.Event.APPROVED
                 if status == WorkflowInstance.Status.APPROVED
                 else WorkflowNotificationTemplate.Event.REJECTED)
        cls._send_notifications(
            instance, document, event=event,
            recipients=[instance.initiated_by]
        )

    # ──────────────────────────────────────────────────────────────────────────
    # NOTIFICATIONS  (Email + WhatsApp + In-App)
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _send_notifications(cls, instance, document, event: str,
                            recipients: list, extra_context: dict = None):
        """
        Send notifications through all enabled channels.
        Attempts to render per-step templates; falls back to system defaults.
        """
        defn = instance.definition
        extra_context = extra_context or {}

        doc_str    = f"{document.__class__.__name__} {getattr(document, 'number', str(document.pk))}"
        doc_label  = doc_str

        ctx = {
            'document':   doc_label,
            'submitter':  instance.initiated_by.get_full_name() if hasattr(instance.initiated_by, 'get_full_name') else str(instance.initiated_by),
            'company':    str(instance.company),
            'workflow':   defn.name,
            'action_label': event.replace('_', ' ').title(),
            **extra_context,
        }

        # ── In-App ────────────────────────────────────────────────────────────
        if defn.notify_in_app:
            title_map = {
                WorkflowNotificationTemplate.Event.STEP_ASSIGNED: f"Approval Required: {doc_label}",
                WorkflowNotificationTemplate.Event.APPROVED:      f"Approved: {doc_label}",
                WorkflowNotificationTemplate.Event.REJECTED:      f"Rejected: {doc_label}",
                WorkflowNotificationTemplate.Event.ESCALATED:     f"Escalation: {doc_label}",
                WorkflowNotificationTemplate.Event.DELEGATED:     f"Delegated to you: {doc_label}",
            }
            msg_map = {
                WorkflowNotificationTemplate.Event.STEP_ASSIGNED: f"You have a pending approval for {doc_label} submitted by {ctx['submitter']}.",
                WorkflowNotificationTemplate.Event.APPROVED:      f"Your {doc_label} has been approved.",
                WorkflowNotificationTemplate.Event.REJECTED:      f"Your {doc_label} has been rejected.",
                WorkflowNotificationTemplate.Event.ESCALATED:     f"Escalation: {doc_label} is overdue and has been escalated to you.",
                WorkflowNotificationTemplate.Event.DELEGATED:     f"{doc_label} approval has been delegated to you.",
            }
            from apps.notifications.models import Notification
            for recipient in recipients:
                if recipient:
                    Notification.objects.create(
                        company=instance.company,
                        recipient=recipient,
                        title=title_map.get(event, f"Workflow Update: {doc_label}"),
                        message=msg_map.get(event, f"Workflow update on {doc_label}."),
                        notification_type=(
                            Notification.NotificationType.SUCCESS if event == WorkflowNotificationTemplate.Event.APPROVED
                            else Notification.NotificationType.ERROR if event == WorkflowNotificationTemplate.Event.REJECTED
                            else Notification.NotificationType.WARNING
                        )
                    )

        # ── Email ─────────────────────────────────────────────────────────────
        if defn.notify_email:
            cls._send_email(instance, event, recipients, ctx, doc_label)

        # ── WhatsApp ──────────────────────────────────────────────────────────
        if defn.notify_whatsapp:
            cls._send_whatsapp(instance, event, recipients, ctx, doc_label)

    @classmethod
    def _send_email(cls, instance, event, recipients, ctx, doc_label):
        try:
            from django.core.mail import send_mail
            from django.conf import settings

            tmpl = WorkflowNotificationTemplate.objects.filter(
                workflow=instance.definition,
                channel=WorkflowNotificationTemplate.Channel.EMAIL,
                event=event,
                is_active=True,
            ).first()

            if tmpl:
                subject = cls._render_template(tmpl.subject, ctx)
                body    = cls._render_template(tmpl.body, ctx)
            else:
                subject = f"[ERP] Workflow: {ctx['action_label']} — {doc_label}"
                body    = (
                    f"Hello,\n\n"
                    f"Workflow Update: {ctx['action_label']}\n"
                    f"Document: {doc_label}\n"
                    f"Submitted by: {ctx['submitter']}\n"
                    f"Company: {ctx['company']}\n\n"
                    f"Please log in to your ERP system to take action.\n"
                )

            email_list = [r.email for r in recipients if r and getattr(r, 'email', None)]
            if email_list:
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@erp.com'),
                    recipient_list=email_list,
                    fail_silently=True,
                )
        except Exception as e:
            logger.error(f"WorkflowEngine email error: {e}")

    @classmethod
    def _send_whatsapp(cls, instance, event, recipients, ctx, doc_label):
        """
        Sends a WhatsApp message via Twilio API (if configured).
        Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM in settings.
        """
        try:
            from django.conf import settings
            account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
            auth_token  = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
            from_number = getattr(settings, 'TWILIO_WHATSAPP_FROM', None)

            if not all([account_sid, auth_token, from_number]):
                logger.debug("WhatsApp not configured — skipping.")
                return

            from twilio.rest import Client  # type: ignore
            client = Client(account_sid, auth_token)

            tmpl = WorkflowNotificationTemplate.objects.filter(
                workflow=instance.definition,
                channel=WorkflowNotificationTemplate.Channel.WHATSAPP,
                event=event,
                is_active=True,
            ).first()

            if tmpl:
                body = cls._render_template(tmpl.body, ctx)
            else:
                body = (
                    f"*ERP Workflow — {ctx['action_label']}*\n"
                    f"Document: {doc_label}\n"
                    f"Submitted by: {ctx['submitter']}\n"
                    f"Company: {ctx['company']}\n"
                    f"Please log in to take action."
                )

            for recipient in recipients:
                phone = getattr(recipient, 'mobile', None) or getattr(recipient, 'phone', None)
                if phone:
                    client.messages.create(
                        from_=f'whatsapp:{from_number}',
                        to=f'whatsapp:{phone}',
                        body=body,
                    )
        except Exception as e:
            logger.error(f"WorkflowEngine WhatsApp error: {e}")

    @classmethod
    def _render_template(cls, template_str: str, ctx: dict) -> str:
        """Render a Django template string with context."""
        try:
            t = Template(template_str)
            return t.render(Context(ctx))
        except Exception:
            return template_str

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _check_definition_conditions(cls, defn, document) -> bool:
        """Evaluate global conditions dict against the document."""
        conditions = defn.conditions or {}
        for key, expected in conditions.items():
            val = document
            for part in key.split('__'):
                val = getattr(val, part, None)
                if val is None:
                    break
            if val != expected:
                return False
        return True

    @classmethod
    def _get_amount(cls, document):
        from decimal import Decimal
        for f in ('total', 'amount', 'total_amount', 'net_amount', 'grand_total'):
            v = getattr(document, f, None)
            if v is not None:
                try:
                    return Decimal(str(v))
                except Exception:
                    pass
        return Decimal('0')

    @classmethod
    def _get_dept_id(cls, document, instance):
        dept = getattr(document, 'department_id', None)
        if dept is None:
            emp = getattr(instance.initiated_by, 'employee_profile', None)
            dept = getattr(emp, 'department_id', None) if emp else None
        return dept


# Make the engine importable from django.db.models in conditional filters
import django.db.models as models
