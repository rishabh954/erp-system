import logging
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from apps.workflow.models import WorkflowDefinition, WorkflowStep, WorkflowInstance, WorkflowAction, ApprovalDelegation
from apps.notifications.models import Notification
from django.db.models import Q

logger = logging.getLogger(__name__)

class WorkflowEngine:
    
    @classmethod
    def trigger(cls, document, trigger_event, user):
        """Triggers a workflow for a document if a definition matches."""
        model_name = document.__class__.__name__
        company = getattr(document, 'company', getattr(user, 'company', None))
        
        if not company:
            logger.warning(f"WorkflowEngine: Cannot determine company for {document}")
            return None
            
        definition = WorkflowDefinition.objects.filter(
            company=company,
            trigger_model=model_name,
            trigger_event=trigger_event,
            is_active=True
        ).first()
        
        if not definition:
            return None # No workflow required
            
        content_type = ContentType.objects.get_for_model(document)
        
        # Check if already running
        existing = WorkflowInstance.objects.filter(
            content_type=content_type, 
            object_id=str(document.pk),
            status__in=[WorkflowInstance.Status.PENDING, WorkflowInstance.Status.IN_PROGRESS]
        ).exists()
        if existing:
            return None
            
        instance = WorkflowInstance.objects.create(
            company=company,
            definition=definition,
            content_type=content_type,
            object_id=str(document.pk),
            status=WorkflowInstance.Status.PENDING,
            initiated_by=user
        )
        
        cls._advance_to_next_step(instance, document)
        return instance

    @classmethod
    def _advance_to_next_step(cls, instance, document, current_step_order=0):
        """Finds the next valid step and routes to it."""
        steps = instance.definition.steps.filter(step_order__gt=current_step_order).order_by('step_order')
        
        amount = getattr(document, 'amount', getattr(document, 'total_amount', getattr(document, 'net_amount', 0)))
        
        next_step = None
        for step in steps:
            # Check amount conditions
            if step.min_amount and amount < step.min_amount:
                continue
            if step.max_amount and amount > step.max_amount:
                continue
            
            # Check department condition (if document has department)
            doc_dept = getattr(document, 'department_id', getattr(getattr(instance.initiated_by, 'employee_profile', None), 'department_id', None))
            if step.department_id and step.department_id != doc_dept:
                continue
                
            next_step = step
            break
            
        if next_step:
            instance.current_step = next_step
            instance.status = WorkflowInstance.Status.IN_PROGRESS if next_step.step_order > 1 else WorkflowInstance.Status.PENDING
            instance.save()
            cls._notify_approvers(instance, next_step, document)
        else:
            # No more steps -> Fully Approved
            cls._mark_completed(instance, document, WorkflowInstance.Status.APPROVED)

    @classmethod
    def _notify_approvers(cls, instance, step, document):
        """Sends notification to the pending approvers."""
        approvers = cls.get_pending_approvers(instance)
        doc_str = f"{document.__class__.__name__} {getattr(document, 'number', document.pk)}"
        
        for approver in approvers:
            Notification.objects.create(
                company=instance.company,
                recipient=approver,
                title=f"Approval Required: {doc_str}",
                message=f"You have a pending approval request for {doc_str} submitted by {instance.initiated_by.get_full_name()}.",
                notification_type=Notification.NotificationType.WARNING
            )

    @classmethod
    def get_pending_approvers(cls, instance):
        """Returns a list of users who can approve the current step."""
        if not instance.current_step:
            return []
            
        step = instance.current_step
        approvers = set()
        
        if step.approver_type == 'user' and step.approver_user:
            approvers.add(step.approver_user)
        elif step.approver_type == 'role' and step.approver_role:
            from apps.authentication.models import User
            approvers.update(User.objects.filter(role=step.approver_role, usercompany__company=instance.company, usercompany__is_active=True))
        elif step.approver_type == 'manager':
            # Logic to find direct manager via HRMS Employee profile
            initiator_emp = getattr(instance.initiated_by, 'employee_profile', None)
            if initiator_emp and getattr(initiator_emp, 'manager', None) and initiator_emp.manager.user:
                approvers.add(initiator_emp.manager.user)
                
        # Resolve Delegations
        final_approvers = set()
        today = timezone.now().date()
        for app in approvers:
            delegation = ApprovalDelegation.objects.filter(
                delegator=app, 
                is_active=True,
                start_date__lte=today,
                end_date__gte=today
            ).first()
            if delegation:
                final_approvers.add(delegation.delegatee)
            else:
                final_approvers.add(app)
                
        return list(final_approvers)

    @classmethod
    def approve(cls, instance, user, comment=''):
        """Approves the current step."""
        if instance.status not in [WorkflowInstance.Status.PENDING, WorkflowInstance.Status.IN_PROGRESS]:
            raise ValueError("Workflow is not pending.")
            
        approvers = cls.get_pending_approvers(instance)
        if user not in approvers and not user.role == 'super_admin':
            raise PermissionError("You are not authorized to approve this step.")
            
        WorkflowAction.objects.create(
            company=instance.company,
            instance=instance,
            step=instance.current_step,
            actor=user,
            action=WorkflowAction.Action.APPROVED,
            comment=comment
        )
        
        document = instance.related_object
        cls._advance_to_next_step(instance, document, current_step_order=instance.current_step.step_order)
        return True

    @classmethod
    def reject(cls, instance, user, comment=''):
        """Rejects the workflow."""
        if instance.status not in [WorkflowInstance.Status.PENDING, WorkflowInstance.Status.IN_PROGRESS]:
            raise ValueError("Workflow is not pending.")
            
        approvers = cls.get_pending_approvers(instance)
        if user not in approvers and not user.role == 'super_admin':
            raise PermissionError("You are not authorized to reject this step.")
            
        WorkflowAction.objects.create(
            company=instance.company,
            instance=instance,
            step=instance.current_step,
            actor=user,
            action=WorkflowAction.Action.REJECTED,
            comment=comment
        )
        
        document = instance.related_object
        cls._mark_completed(instance, document, WorkflowInstance.Status.REJECTED)
        return True

    @classmethod
    def _mark_completed(cls, instance, document, status):
        """Marks the workflow completed and updates the document status."""
        instance.status = status
        instance.current_step = None
        instance.completed_at = timezone.now()
        instance.save()
        
        # Auto-update document status if it has one
        if hasattr(document, 'status'):
            if status == WorkflowInstance.Status.APPROVED:
                if document.status == 'draft' or document.status == 'pending':
                    document.status = 'approved'
            elif status == WorkflowInstance.Status.REJECTED:
                document.status = 'rejected'
            document.save(update_fields=['status'])
            
        # Notify initiator
        doc_str = f"{document.__class__.__name__} {getattr(document, 'number', document.pk)}"
        Notification.objects.create(
            company=instance.company,
            recipient=instance.initiated_by,
            title=f"Workflow {status.title()}: {doc_str}",
            message=f"Your {doc_str} has been {status}.",
            notification_type=Notification.NotificationType.SUCCESS if status == WorkflowInstance.Status.APPROVED else Notification.NotificationType.ERROR
        )
