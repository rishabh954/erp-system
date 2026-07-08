import glob
import os
import re

import pytest
from django.apps import apps
from django.db.models import UUIDField
from django.urls import get_resolver


@pytest.mark.django_db
def test_url_pk_consistency():
    """
    Walk every path() in urls.py, resolve the view, inspect the model class it operates on,
    and flag any <int:pk> route pointing at a UUID-keyed model (or vice versa).
    """
    resolver = get_resolver()

    # Simple regex to extract <int:pk> or <uuid:pk> from URL patterns
    uuid_pattern = re.compile(r"<uuid:[^>]+>")
    int_pattern = re.compile(r"<int:[^>]+>")

    def extract_model_from_view(view_func):
        # Class-based views
        if hasattr(view_func, "view_class"):
            cls = view_func.view_class
            if hasattr(cls, "model") and cls.model is not None:
                return cls.model
            if hasattr(cls, "queryset") and cls.queryset is not None:
                return cls.queryset.model
        return None

    errors = []

    def check_patterns(patterns, prefix=""):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                check_patterns(pattern.url_patterns, prefix + str(pattern.pattern))
            else:
                full_pattern = prefix + str(pattern.pattern)
                model = extract_model_from_view(pattern.callback)
                if model:
                    pk_field = model._meta.pk
                    is_uuid = isinstance(pk_field, UUIDField)

                    if is_uuid and int_pattern.search(full_pattern):
                        errors.append(
                            f"URL {full_pattern} uses <int:pk> but model {model.__name__} has a UUID PK."
                        )
                    elif not is_uuid and uuid_pattern.search(full_pattern):
                        errors.append(
                            f"URL {full_pattern} uses <uuid:pk> but model {model.__name__} has an int PK."
                        )

    check_patterns(resolver.url_patterns)

    if errors:
        pytest.fail("\n".join(errors))


def test_template_field_references():
    """
    Grep-diff {{ x.y }} references against Model._meta.get_fields() names
    for every model referenced in context.
    """
    # Mapping commonly used context variables to their actual Django models
    # This acts as a heuristic to catch issues like order.date where order = SalesOrder
    model_mapping = {
        "order": [
            "sales.SalesOrder",
            "purchase.PurchaseOrder",
            "manufacturing.ManufacturingOrder",
        ],
        "sales_order": ["sales.SalesOrder"],
        "purchase_order": ["purchase.PurchaseOrder"],
        "bill": ["purchase.Bill"],
        "invoice": ["sales.Invoice"],
        "customer": [
            "crm.Customer",
            "authentication.User",
        ],  # User is often customer portal user
        "vendor": ["purchase.Vendor"],
        "payment": ["sales.Payment", "purchase.Payment"],
        "shipment": ["sales.Shipment", "inventory.Shipment"],
        "ticket": ["helpdesk.Ticket"],
        "stmt": ["accounting.BankStatement"],
        "picklist": ["inventory.PickList"],
        "lot": ["inventory.LotBatch", "inventory.Lot"],
        "serial": ["inventory.SerialNumber"],
    }

    # Resolve strings to actual model classes
    resolved_models = {}
    for var_name, model_strings in model_mapping.items():
        classes = []
        for ms in model_strings:
            try:
                app_label, model_name = ms.split(".")
                classes.append(apps.get_model(app_label, model_name))
            except LookupError:
                pass
        resolved_models[var_name] = classes

    templates_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "templates"
    )
    template_files = glob.glob(
        os.path.join(templates_dir, "**", "*.html"), recursive=True
    )

    errors = []

    # Regex to find {{ var.field }} or {% if var.field %}
    var_pattern = re.compile(r"\{\{.*?(?:\b([a-zA-Z_]+)\.([a-zA-Z_]+)\b).*?\}\}")
    tag_pattern = re.compile(r"\{%.*?(?:\b([a-zA-Z_]+)\.([a-zA-Z_]+)\b).*?%\}")

    # Valid model properties/methods that might not be in get_fields()
    allowed_methods = [
        "pk",
        "id",
        "get_status_display",
        "get_priority_display",
        "get_method_display",
        "get_movement_type_display",
        "get_allocation_method_display",
        "get_cost_type_display",
        "get_full_name",
    ]

    for filepath in template_files:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        matches = var_pattern.findall(content) + tag_pattern.findall(content)

        for var_name, field_name in matches:
            if var_name in resolved_models:
                models_to_check = resolved_models[var_name]
                if not models_to_check:
                    continue

                # If the field_name matches a valid field/property on AT LEAST ONE of the potential models, it's valid
                is_valid = False
                for model in models_to_check:
                    # Check fields
                    field_names = [f.name for f in model._meta.get_fields()]
                    if field_name in field_names or field_name in allowed_methods:
                        is_valid = True
                        break

                    # Check if it's a property (like 'total', 'subtotal' if they are properties)
                    if hasattr(model, field_name):
                        is_valid = True
                        break

                if not is_valid:
                    rel_path = os.path.relpath(filepath, templates_dir)
                    errors.append(
                        f"Template {rel_path}: '{var_name}.{field_name}' referenced, but '{field_name}' not found on {var_name} models {[m.__name__ for m in models_to_check]}."
                    )

    # Filter duplicates
    errors = list(set(errors))

    if errors:
        pytest.fail("\n".join(sorted(errors)))
