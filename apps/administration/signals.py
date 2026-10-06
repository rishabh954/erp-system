"""
Administration Signals
Automatically captures field-level changes for all registered models
into AuditLog without modifying any existing model code.

The legacy implementation previously used a process-wide mutable dictionary to
store pre-save state. That pattern is unsafe across concurrent requests,
multiple Gunicorn workers, Celery tasks, and async execution. This version uses
context-local state instead so each execution context tracks its own snapshot.
"""

import contextvars

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

# Models to audit — add any app.Model string here
AUDITED_MODELS = [
    "apps.crm.models.Customer",
    "apps.crm.models.Lead",
    "apps.sales.models.Invoice",
    "apps.sales.models.SalesOrder",
    "apps.purchase.models.PurchaseOrder",
    "apps.purchase.models.Vendor",
    "apps.inventory.models.Product",
    "apps.hrms.models.Employee",
    "apps.hrms.models.LeaveRequest",
    "apps.hrms.models.ExpenseClaim",
    "apps.manufacturing.models.ManufacturingOrder",
    "apps.accounting.models.JournalEntry",
]

# Context-local storage avoids global mutable request state.
_PRE_SAVE_STATE = contextvars.ContextVar("audit_pre_save_state", default=None)


def _get_model_class(model_path):
    module_path, class_name = model_path.rsplit(".", 1)
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _serialize_instance(instance):
    """Return a dict of field→value for an instance."""
    data = {}
    for field in instance._meta.get_fields():
        if hasattr(field, "attname"):
            data[field.attname] = str(getattr(instance, field.attname, ""))
    return data


def _write_audit(action, instance, changes=None, user=None):
    try:
        from apps.administration.models import AuditLog

        company = getattr(instance, "company", None)
        AuditLog.objects.create(
            company=company,
            user=user,
            action=action,
            model_name=instance.__class__.__name__,
            object_id=str(instance.pk),
            object_repr=str(instance)[:300],
            changes=changes or {},
            timestamp=timezone.now(),
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to save audit log: %s", e, exc_info=True)


def register_audit_signals():
    """Dynamically register pre_save / post_save / post_delete for all audited models."""
    for model_path in AUDITED_MODELS:
        try:
            model_cls = _get_model_class(model_path)

            def make_pre_save(cls):
                @receiver(pre_save, sender=cls, weak=False)
                def _pre_save(sender, instance, **kwargs):
                    if not instance.pk:
                        return
                    try:
                        old = sender.objects.get(pk=instance.pk)
                    except sender.DoesNotExist:
                        return
                    state = _PRE_SAVE_STATE.get() or {}
                    state[str(instance.pk)] = _serialize_instance(old)
                    _PRE_SAVE_STATE.set(state)

                return _pre_save

            def make_post_save(cls):
                @receiver(post_save, sender=cls, weak=False)
                def _post_save(sender, instance, created, **kwargs):
                    action = "create" if created else "update"
                    changes = {}
                    if not created:
                        state = _PRE_SAVE_STATE.get() or {}
                        old_state = state.pop(str(instance.pk), {})
                        new_state = _serialize_instance(instance)
                        for k, v in new_state.items():
                            if old_state.get(k) != v:
                                changes[k] = {"old": old_state.get(k), "new": v}
                        if state:
                            _PRE_SAVE_STATE.set(state)
                        else:
                            _PRE_SAVE_STATE.set(None)
                    _write_audit(action, instance, changes)

                return _post_save

            def make_post_delete(cls):
                @receiver(post_delete, sender=cls, weak=False)
                def _post_delete(sender, instance, **kwargs):
                    _write_audit("delete", instance)

                return _post_delete

            make_pre_save(model_cls)
            make_post_save(model_cls)
            make_post_delete(model_cls)

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Model not found: %s", e)


# Register on app ready
register_audit_signals()
