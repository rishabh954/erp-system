from django.core.exceptions import ValidationError


def validate_company_relation(instance, field_name, company):
    """Resolve a submitted relation only when it belongs to the active company."""
    field = instance._meta.get_field(field_name)
    related_model = field.remote_field.model
    object_id = getattr(instance, f"{field_name}_id")
    if not object_id:
        return

    try:
        related = related_model.objects.get(pk=object_id, company=company)
    except (related_model.DoesNotExist, TypeError, ValueError, ValidationError):
        raise ValidationError(
            {field_name: "Select a valid record belonging to this company."}
        ) from None
    setattr(instance, field_name, related)


def validate_instance(instance):
    """Run Django field, choice, length, relation, and uniqueness validation."""
    try:
        instance.full_clean()
    except ValidationError as exc:
        raise ValueError("; ".join(exc.messages)) from exc
