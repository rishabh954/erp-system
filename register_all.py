import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.apps import apps
from django.contrib import admin

missing_by_app = {}

for app_config in apps.get_app_configs():
    if 'apps.' in app_config.name or app_config.name == 'core':
        for model in app_config.get_models():
            if not admin.site.is_registered(model):
                missing_by_app.setdefault(app_config.name, []).append(model)

with open(r"c:\Users\OM\erp_system\erp_system\core\admin.py", "a", encoding="utf-8") as f:
    f.write("\n\n# --- Automatically Generated Admin Registrations ---\n")
    for app_name, models in missing_by_app.items():
        if not models:
            continue
        model_names = [m.__name__ for m in models]
        f.write(f"\nfrom {app_name}.models import {', '.join(model_names)}\n")
        for model in models:
            fields = [fld.name for fld in model._meta.fields if not fld.name in ('id', 'created_at', 'updated_at', 'is_deleted', 'deleted_at', 'deleted_by', 'password', 'token')][:6]
            if not fields:
                fields = ['id']
            fields_str = ', '.join([f"'{fld}'" for fld in fields])
            f.write(f"\n@admin.register({model.__name__})\n")
            f.write(f"class {model.__name__}Admin(admin.ModelAdmin):\n")
            f.write(f"    list_display = [{fields_str}]\n")

print(f"Added {sum(len(m) for m in missing_by_app.values())} missing models to core/admin.py")
