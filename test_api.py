import os
import django
import json
from django.apps import apps

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

model_map = {
    'sales': ('sales', 'SalesOrder'),
    'purchases': ('purchase', 'PurchaseOrder'),
    'inventory': ('inventory', 'InventoryTransaction'),
    'accounting': ('accounting', 'JournalItem'),
}

module_source = 'sales'
app_label, model_name = model_map.get(module_source, (None, None))
print(f"app_label={app_label}, model_name={model_name}")

try:
    ModelClass = apps.get_model(app_label, model_name)
    fields = [f.name for f in ModelClass._meta.get_fields() if not f.is_relation or f.many_to_one]
    print("fields=", sorted(fields))
except LookupError as e:
    print("LookupError:", e)
except Exception as e:
    print("Error:", e)
