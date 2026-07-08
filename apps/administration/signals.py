"""
Administration Signals
Automatically captures field-level changes for all registered models
into AuditLog without modifying any existing model code.
"""

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

# Map model class → previous state storage key
_PRE_SAVE_STATE = {}


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
    except Exception:
        pass  # Never let audit fail silently block the main operation


def register_audit_signals():
    """Dynamically register pre_save / post_save / post_delete for all audited models."""
    for model_path in AUDITED_MODELS:
        try:
            model_cls = _get_model_class(model_path)

            # Pre-save: capture old state
            def make_pre_save(cls):
                @receiver(pre_save, sender=cls, weak=False)
                def _pre_save(sender, instance, **kwargs):
                    if instance.pk:
                        try:
                            old = sender.objects.get(pk=instance.pk)
                            _PRE_SAVE_STATE[str(instance.pk)] = _serialize_instance(old)
                        except sender.DoesNotExist:
                            pass

                return _pre_save

            # Post-save: diff and write
            def make_post_save(cls):
                @receiver(post_save, sender=cls, weak=False)
                def _post_save(sender, instance, created, **kwargs):
                    action = "create" if created else "update"
                    changes = {}
                    if not created:
                        old_state = _PRE_SAVE_STATE.pop(str(instance.pk), {})
                        new_state = _serialize_instance(instance)
                        for k, v in new_state.items():
                            if old_state.get(k) != v:
                                changes[k] = {"old": old_state.get(k), "new": v}
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

        except Exception:
            pass  # If a model can't be imported yet, skip gracefully


# Register on app ready
register_audit_signals()
